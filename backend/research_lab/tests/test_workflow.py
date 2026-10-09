"""End-to-end multi-agent workflow tests (``agents.boss.run_workflow``). Every external boundary
(search providers, document fetching, the LLM) is mocked — see ``research_lab/tests/fakes.py`` —
so these exercise the orchestration logic itself: state transitions, fault tolerance and the
generator<->reviewer loop, deterministically and without cost.
"""
from django.test import override_settings

from core.testing import BaseTestCase, make_llm_config, make_teacher
from llm.models import PromptCode
from research_lab.agents.boss import run_workflow
from research_lab.models import (ExecutionStatus, LLMMode, ResearchRun, ResearchRunStatus, ReviewStatus,
                                 ValidationDecision)
from research_lab.tests.fakes import FakeProvider, make_candidate, patch_fetch, patch_llm_json, patch_providers

ACCEPT_JSON = {'relevance': 90, 'authority': 85, 'educational_value': 88, 'academic_credibility': 90,
               'level_match': 92, 'recency': 70, 'completeness': 80, 'overall_score': 90,
               'decision': 'accept', 'reasons': ['Directly on topic', 'Credible academic source']}
REJECT_JSON = {**ACCEPT_JSON, 'overall_score': 20, 'decision': 'reject', 'reasons': ['Off topic']}
GENERATION_JSON = {'title': 'RAG Assignment', 'objectives': ['Understand RAG'],
                   'instructions': 'Read the sources and answer the questions.',
                   'questions': [{'type': 'short_answer', 'prompt': 'Explain RAG in your own words.', 'points': 10}],
                   'grading_criteria': 'Award full marks for a correct explanation.',
                   'references': [{'source_id': 1, 'citation': '[1]'}], 'answer_key': 'RAG = retrieval + generation.'}
APPROVED_JSON = {'decision': 'approved', 'score': 95, 'issues': []}
NEEDS_REVISION_JSON = {'decision': 'needs_revision', 'score': 40, 'issues': ['Questions are too vague.']}
LECTURE_JSON = {'title': 'Introduction to RAG', 'learning_objectives': ['Understand RAG'],
                'sections': [{'title': 'What is RAG?', 'content': 'RAG combines retrieval with generation.',
                             'key_points': ['Retriever + generator'], 'examples': ['Open-domain QA'],
                             'source_ids': []}],  # grounding-filter behaviour is covered in test_lecture_builder.py
                'summary': 'RAG improves factual grounding.', 'self_check_questions': ['What problem does RAG solve?'],
                'references': [{'source_id': 1, 'citation': '[1]'}]}
LECTURE_APPROVED_JSON = {'decision': 'approved', 'score': 95, 'issues': []}
LECTURE_NEEDS_REVISION_JSON = {'decision': 'needs_revision', 'score': 35, 'issues': ['Too shallow.']}


def make_run(**kw) -> ResearchRun:
    teacher = kw.pop('user', None) or make_teacher()
    kw.setdefault('llm_mode', LLMMode.CLOUD)
    return ResearchRun.objects.create(user=teacher, topic=kw.pop('topic', 'Retrieval-Augmented Generation'),
                                      **kw)


def _validation_responses(**overrides):
    return {
        PromptCode.RESEARCH_SOURCE_VALIDATION: ACCEPT_JSON,
        PromptCode.RESEARCH_ASSIGNMENT_GENERATION: GENERATION_JSON,
        PromptCode.RESEARCH_ASSIGNMENT_REVISION: GENERATION_JSON,
        PromptCode.RESEARCH_ASSIGNMENT_REVIEW: APPROVED_JSON,
        **overrides,
    }


def _lecture_responses(**overrides):
    return {
        PromptCode.RESEARCH_LECTURE_GENERATION: LECTURE_JSON,
        PromptCode.RESEARCH_LECTURE_REVISION: LECTURE_JSON,
        PromptCode.RESEARCH_LECTURE_REVIEW: LECTURE_APPROVED_JSON,
        **overrides,
    }


class FullWorkflowTests(BaseTestCase):
    def setUp(self):
        make_llm_config()  # a default, active LLMConfiguration for resolve_configuration() to find

    def test_all_providers_work_end_to_end(self):
        run = make_run()
        web = [FakeProvider('BRIGHTDATA', [make_candidate('RAG course notes', provider='BRIGHTDATA')])]
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]

        with patch_providers(web=web, academic=academic), patch_fetch(), patch_llm_json(_validation_responses()):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertEqual(run.sources.count(), 2)
        self.assertTrue(run.sources.filter(decision=ValidationDecision.ACCEPT).exists())
        self.assertEqual(run.assignment.title, 'RAG Assignment')
        self.assertEqual(run.assignment.review_status, ReviewStatus.APPROVED)
        agents = list(run.agent_executions.order_by('sequence').values_list('agent', 'status'))
        self.assertTrue(all(status == ExecutionStatus.SUCCESS for _agent, status in agents))
        self.assertEqual([a for a, _ in agents],
                         ['BOSS', 'WEB_RESEARCH', 'ACADEMIC_RESEARCH', 'DOCUMENT_RETRIEVAL', 'DOCUMENT_ANALYSIS',
                          'SOURCE_VALIDATOR', 'ASSIGNMENT_GENERATOR', 'FINAL_REVIEWER'])
        self.assertTrue(run.tool_executions.filter(tool='BRIGHTDATA', status='SUCCESS').exists())
        self.assertTrue(run.tool_executions.filter(tool='OPENALEX', status='SUCCESS').exists())

    def test_one_provider_failing_does_not_abort_the_run(self):
        run = make_run()
        web = [FakeProvider('BRIGHTDATA', fail=True)]
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')]),
                   FakeProvider('ARXIV', fail=True)]

        with patch_providers(web=web, academic=academic), patch_fetch(), patch_llm_json(_validation_responses()):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)  # provider failures are logged, not fatal
        self.assertEqual(run.sources.count(), 1)
        self.assertTrue(run.tool_executions.filter(tool='BRIGHTDATA', status='FAILED').exists())
        self.assertTrue(run.tool_executions.filter(tool='ARXIV', status='FAILED').exists())

    def test_unconfigured_provider_is_skipped_not_failed(self):
        run = make_run()
        web = [FakeProvider('BRIGHTDATA', is_configured=False)]

        with patch_providers(web=web, academic=[]), patch_fetch(), patch_llm_json(_validation_responses()):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertTrue(run.tool_executions.filter(tool='BRIGHTDATA', status='SKIPPED').exists())

    def test_all_sources_rejected_completes_without_an_assignment(self):
        run = make_run()
        academic = [FakeProvider('OPENALEX', [make_candidate('Irrelevant paper', provider='OPENALEX', doi='10.1/x')])]

        with patch_providers(web=[], academic=academic), patch_fetch(), \
                patch_llm_json(_validation_responses(**{PromptCode.RESEARCH_SOURCE_VALIDATION: REJECT_JSON})):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertFalse(run.sources.filter(decision=ValidationDecision.ACCEPT).exists())
        self.assertEqual(run.assignment.review_status, ReviewStatus.PENDING)  # never reviewed: nothing to review
        self.assertIn('No sources passed validation', run.assignment.instructions)

    def test_reviewer_requests_one_revision_then_approves(self):
        run = make_run()
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        responses = _validation_responses(**{
            PromptCode.RESEARCH_ASSIGNMENT_REVIEW: [NEEDS_REVISION_JSON, APPROVED_JSON],
        })

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(responses) as calls:
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertEqual(run.revision_count, 1)
        self.assertEqual(run.assignment.review_status, ReviewStatus.APPROVED)
        self.assertEqual(calls.count(PromptCode.RESEARCH_ASSIGNMENT_REVIEW), 2)
        self.assertEqual(calls.count(PromptCode.RESEARCH_ASSIGNMENT_REVISION), 1)

    @override_settings(RESEARCH_LAB_MAX_REVISION_CYCLES=1)
    def test_revision_limit_is_enforced(self):
        run = make_run()
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        responses = _validation_responses(**{PromptCode.RESEARCH_ASSIGNMENT_REVIEW: NEEDS_REVISION_JSON})

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(responses):
            run_workflow(run.pk)

        run.refresh_from_db()
        # The loop was cut off, but the best draft is kept and labelled: that is not a failed run.
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertEqual(run.revision_count, 1)
        self.assertEqual(run.assignment.review_status, ReviewStatus.REVISION_LIMIT_REACHED)

    @override_settings(RESEARCH_LAB_MAX_RUNTIME_SECONDS=0)
    def test_workflow_timeout_yields_partial(self):
        run = make_run()
        with patch_providers(web=[], academic=[]), patch_fetch(), patch_llm_json(_validation_responses()):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.PARTIAL)
        self.assertIn('runtime', run.error_message.lower())

    def test_cancellation_is_cooperative(self):
        run = make_run()
        academic = [FakeProvider('OPENALEX', [make_candidate(f'Paper {i}', provider='OPENALEX', doi=f'10.1/{i}')
                                              for i in range(5)])]
        run.cancel_requested = True
        run.save(update_fields=['cancel_requested'])

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(_validation_responses()):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.CANCELLED)

    def test_disabled_research_lab_fails_the_run_without_crashing(self):
        from research_lab.tasks import run_research_task

        run = make_run()
        with override_settings(RESEARCH_LAB_ENABLED=False):
            run_research_task(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.FAILED)
        self.assertIn('disabled', run.error_message.lower())

    def test_running_an_already_finished_run_is_a_noop(self):
        run = make_run(status=ResearchRunStatus.COMPLETED)
        run_workflow(run.pk)  # must not re-run or raise
        run.refresh_from_db()
        self.assertEqual(run.agent_executions.count(), 0)
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)

    def test_hybrid_mode_routes_validator_local_and_generator_cloud(self):
        from llm.models import LLMConfiguration, ProviderCode
        from research_lab.models import AGENT_ASSIGNMENT_GENERATOR, AGENT_SOURCE_VALIDATOR
        from research_lab.services.llm_router import resolve_configuration

        LLMConfiguration.objects.all().delete()  # a clean slate: this test asserts exact routing identity
        local = make_llm_config(code=ProviderCode.LOCAL, default=False, name='local-cfg')
        cloud = make_llm_config(code=ProviderCode.OPENAI, default=False, name='cloud-cfg')
        run = make_run(llm_mode=LLMMode.HYBRID)
        self.assertEqual(resolve_configuration(run, AGENT_SOURCE_VALIDATOR), local)
        self.assertEqual(resolve_configuration(run, AGENT_ASSIGNMENT_GENERATOR), cloud)


class LectureWorkflowTests(BaseTestCase):
    """The Lecture Builder is optional (``generate_lecture``, default False) — same as the
    Assignment Generator. It runs between Source Validator and Assignment Generator, with its own
    review/revision loop capped at ``RESEARCH_LAB_MAX_LECTURE_REVISIONS``; the (reviewed) lecture
    is then handed to the Assignment Generator (see ``agents/boss.py``)."""

    def setUp(self):
        make_llm_config()

    def test_lecture_is_skipped_entirely_when_not_requested(self):
        run = make_run()  # generate_lecture defaults to False
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(_validation_responses()):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertFalse(run.lectures.exists())
        self.assertNotIn('LECTURE_BUILDER', list(run.agent_executions.values_list('agent', flat=True)))

    def test_lecture_is_built_reviewed_and_feeds_the_assignment(self):
        run = make_run(generate_lecture=True)
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        responses = {**_validation_responses(), **_lecture_responses()}

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(responses):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        lecture = run.lectures.order_by('-version').first()
        self.assertEqual((lecture.version, lecture.title, lecture.status), (1, 'Introduction to RAG', 'APPROVED'))
        self.assertEqual(run.assignment.title, 'RAG Assignment')
        agents = list(run.agent_executions.order_by('sequence').values_list('agent', 'status'))
        self.assertTrue(all(status == ExecutionStatus.SUCCESS for _agent, status in agents))
        self.assertEqual([a for a, _ in agents],
                         ['BOSS', 'WEB_RESEARCH', 'ACADEMIC_RESEARCH', 'DOCUMENT_RETRIEVAL', 'DOCUMENT_ANALYSIS', 'SOURCE_VALIDATOR',
                          'LECTURE_BUILDER', 'FINAL_REVIEWER', 'ASSIGNMENT_GENERATOR', 'FINAL_REVIEWER'])

    def test_insufficient_sources_does_not_block_the_rest_of_the_run(self):
        run = make_run(generate_lecture=True)
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        responses = {**_validation_responses(), **_lecture_responses(**{
            PromptCode.RESEARCH_LECTURE_GENERATION: {'status': 'insufficient_sources',
                                                     'missing_topics': ['core theory']},
        })}

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(responses):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)  # a declared gap, not a crash
        lecture = run.lectures.order_by('-version').first()
        self.assertEqual(lecture.status, 'INSUFFICIENT_SOURCES')
        self.assertIn('insufficient sources', run.error_message.lower())
        self.assertEqual(run.assignment.title, 'RAG Assignment')  # still generated, from the sources alone
        agents = [a for a, _ in run.agent_executions.order_by('sequence').values_list('agent', 'status')]
        self.assertNotIn('FINAL_REVIEWER', agents[:agents.index('ASSIGNMENT_GENERATOR')])  # no lecture review ran

    def test_lecture_reviewer_requests_one_revision_then_approves(self):
        run = make_run(generate_lecture=True)
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        responses = {**_validation_responses(), **_lecture_responses(**{
            PromptCode.RESEARCH_LECTURE_REVIEW: [LECTURE_NEEDS_REVISION_JSON, LECTURE_APPROVED_JSON],
        })}

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(responses) as calls:
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertEqual(run.lecture_revision_count, 1)
        lecture = run.lectures.order_by('-version').first()
        self.assertEqual((lecture.version, lecture.status), (2, 'APPROVED'))
        self.assertEqual(calls.count(PromptCode.RESEARCH_LECTURE_REVIEW), 2)
        self.assertEqual(calls.count(PromptCode.RESEARCH_LECTURE_REVISION), 1)

    @override_settings(RESEARCH_LAB_MAX_LECTURE_REVISIONS=1)
    def test_lecture_revision_limit_is_enforced(self):
        run = make_run(generate_lecture=True)
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        responses = {**_validation_responses(), **_lecture_responses(**{
            PromptCode.RESEARCH_LECTURE_REVIEW: LECTURE_NEEDS_REVISION_JSON,
        })}

        with patch_providers(web=[], academic=academic), patch_fetch(), patch_llm_json(responses):
            run_workflow(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, ResearchRunStatus.COMPLETED)
        self.assertEqual(run.lecture_revision_count, 1)
        lecture = run.lectures.order_by('-version').first()
        self.assertEqual(lecture.status, 'REVISION_LIMIT_REACHED')
