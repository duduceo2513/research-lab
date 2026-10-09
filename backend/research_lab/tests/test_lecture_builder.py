"""Unit tests for the Lecture Builder agent and the Final Reviewer's lecture-review path. All LLM
calls are faked via ``patch_llm_json`` (see ``research_lab/tests/fakes.py``); the full
orchestrated flow (boss.py wiring the two together, revision loop, the hand-off to Assignment
Generator) is covered in ``test_workflow.py``.
"""
from core.testing import BaseTestCase, make_llm_config
from llm.models import PromptCode
from research_lab.agents import final_reviewer, lecture_builder
from research_lab.models import LectureStatus, ResearchSource
from research_lab.tests.fakes import patch_llm_json
from research_lab.tests.test_workflow import make_run

LECTURE_JSON = {
    'title': 'Introduction to RAG', 'learning_objectives': ['Understand retrieval-augmented generation'],
    'sections': [
        {'title': 'What is RAG?', 'content': 'RAG combines retrieval with generation.',
         'key_points': ['Combines a retriever and a generator'], 'examples': ['Open-domain QA'],
         'source_ids': [999999]},  # a bogus id the agent must not trust
    ],
    'summary': 'RAG improves factual grounding.',
    'self_check_questions': ['What problem does RAG solve?'],
    'references': [{'source_id': 1, 'citation': '[1]'}],
}
INSUFFICIENT_JSON = {'status': 'insufficient_sources', 'missing_topics': ['formal definitions']}


def make_accepted_source(run, **kw) -> ResearchSource:
    return ResearchSource.objects.create(
        run=run, title=kw.pop('title', 'A RAG paper'), provider=kw.pop('provider', 'OPENALEX'),
        decision=kw.pop('decision', 'ACCEPT'), **kw)


class LectureBuilderTests(BaseTestCase):
    def setUp(self):
        self.config = make_llm_config()
        self.run = make_run()

    def test_no_accepted_sources_yields_an_insufficient_draft_without_calling_the_model(self):
        with patch_llm_json() as calls:
            sequence, lecture = lecture_builder.generate(self.run, 1, [])
        self.assertEqual(lecture.status, LectureStatus.INSUFFICIENT_SOURCES)
        self.assertEqual(calls, [])
        self.assertEqual(sequence, 2)
        self.assertEqual(lecture.version, 1)

    def test_builds_a_lecture_and_strips_a_hallucinated_source_id(self):
        source = make_accepted_source(self.run)
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_GENERATION: LECTURE_JSON}):
            _, lecture = lecture_builder.generate(self.run, 1, [source])
        self.assertEqual((lecture.version, lecture.title, lecture.status),
                         (1, 'Introduction to RAG', LectureStatus.DRAFT))
        self.assertEqual(lecture.content_json['sections'][0]['source_ids'], [])
        self.assertIn('Introduction to RAG', lecture.plain_text)

    def test_a_real_source_id_is_kept(self):
        source = make_accepted_source(self.run)
        grounded = {**LECTURE_JSON, 'sections': [{**LECTURE_JSON['sections'][0], 'source_ids': [source.pk]}]}
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_GENERATION: grounded}):
            _, lecture = lecture_builder.generate(self.run, 1, [source])
        self.assertEqual(lecture.content_json['sections'][0]['source_ids'], [source.pk])

    def test_model_declared_insufficient_sources_is_a_status_not_a_crash(self):
        source = make_accepted_source(self.run)
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_GENERATION: INSUFFICIENT_JSON}):
            _, lecture = lecture_builder.generate(self.run, 1, [source])
        self.assertEqual(lecture.status, LectureStatus.INSUFFICIENT_SOURCES)
        self.assertEqual(lecture.content_json['missing_topics'], ['formal definitions'])

    def test_unparsable_reply_is_recorded_as_insufficient_not_a_crash(self):
        source = make_accepted_source(self.run)
        with patch_llm_json():  # no mapping for RESEARCH_LECTURE_GENERATION -> parsed is None
            _, lecture = lecture_builder.generate(self.run, 1, [source])
        self.assertEqual(lecture.status, LectureStatus.INSUFFICIENT_SOURCES)
        self.assertIn('unparsable', lecture.content_json['missing_topics'][0])

    def test_a_revision_creates_a_new_version_rather_than_overwriting(self):
        source = make_accepted_source(self.run)
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_GENERATION: LECTURE_JSON}):
            _, first = lecture_builder.generate(self.run, 1, [source])
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_REVISION: LECTURE_JSON}) as calls:
            _, second = lecture_builder.generate(
                self.run, 2, [source], previous_draft={'title': first.title}, feedback=['Add more detail'])
        self.assertEqual((first.version, second.version), (1, 2))
        self.assertEqual(calls, [PromptCode.RESEARCH_LECTURE_REVISION])
        self.assertEqual(ResearchSource.objects.get(pk=source.pk).run_id, self.run.pk)  # sanity: same run throughout


class ReviewLectureTests(BaseTestCase):
    def setUp(self):
        self.config = make_llm_config()
        self.run = make_run()
        self.source = make_accepted_source(self.run)
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_GENERATION: LECTURE_JSON}):
            _, self.lecture = lecture_builder.generate(self.run, 1, [self.source])

    def test_approved_review_updates_the_lecture(self):
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_REVIEW: {'decision': 'approved', 'score': 92, 'issues': []}}):
            _, result = final_reviewer.review_lecture(self.run, 2, self.lecture, [self.source])
        self.lecture.refresh_from_db()
        self.assertEqual((result.decision, self.lecture.status, self.lecture.review_score),
                         ('approved', LectureStatus.APPROVED, 92))

    def test_needs_revision_is_recorded_with_its_issues(self):
        with patch_llm_json({PromptCode.RESEARCH_LECTURE_REVIEW: {
                'decision': 'needs_revision', 'score': 30, 'issues': ['Missing examples']}}):
            _, result = final_reviewer.review_lecture(self.run, 2, self.lecture, [self.source])
        self.lecture.refresh_from_db()
        self.assertEqual((result.decision, self.lecture.status, self.lecture.review_result['issues']),
                         ('needs_revision', LectureStatus.NEEDS_REVISION, ['Missing examples']))


class SourceCitationTests(BaseTestCase):
    def test_positions_and_ids_both_resolve_and_invented_numbers_are_dropped(self):
        from research_lab.agents.lecture_builder import resolve_source_id
        from research_lab.models import ResearchSource

        run = make_run()
        sources = [ResearchSource.objects.create(run=run, provider='ARXIV', external_id=str(i), title=f's{i}') for i in range(3)]
        first, second, third = sources
        # The model cites the list position ("source [2]") ...
        self.assertEqual([resolve_source_id(n, sources) for n in (1, 2, '3', '[2]')], [first.pk, second.pk, third.pk, second.pk])
        # ... or the database id shown as "(id=...)" ...
        high = ResearchSource.objects.create(run=run, provider='ARXIV', external_id='x', title='high')
        self.assertEqual(resolve_source_id(high.pk, [*sources, high]), high.pk)
        # ... but never a number that is neither, nor something that is not a number at all.
        self.assertIsNone(resolve_source_id(high.pk + 1000, sources))
        self.assertIsNone(resolve_source_id('abc', sources))
        self.assertIsNone(resolve_source_id(True, sources))


class ReviewerSeesTheWholeLectureTests(BaseTestCase):
    def test_key_points_and_examples_are_part_of_what_the_reviewer_reads(self):
        run = make_run()
        lecture = lecture_builder.GeneratedLecture.objects.create(
            run=run, version=1, title='Loops', content_json={'sections': [{
                'title': 'for loops', 'content': 'Body ' * 100, 'source_ids': [1],
                'key_points': ['Iterate directly over the list'], 'examples': ['for x in items: print(x)']}]})
        text = final_reviewer._format_lecture(lecture)
        self.assertIn('for x in items: print(x)', text)
        self.assertIn('Iterate directly over the list', text)
        self.assertGreater(len(text), 480)  # the section body is no longer cut to 300 characters
