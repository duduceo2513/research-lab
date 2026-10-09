from django.test import override_settings

from core.testing import BaseTestCase, api_client, make_admin, make_llm_config, make_student, make_teacher
from llm.models import PromptCode
from research_lab.agents.boss import run_workflow
from research_lab.models import ResearchRun, ResearchRunStatus
from research_lab.tests.fakes import FakeProvider, make_candidate, patch_fetch, patch_llm_json, patch_providers
from research_lab.tests.test_workflow import ACCEPT_JSON, GENERATION_JSON, LECTURE_JSON, make_run

VALID_PAYLOAD = {'topic': 'Retrieval-Augmented Generation', 'education_level': 'MASTER',
                 'material_types': ['PAPERS'], 'generate_assignment': True, 'llm_mode': 'CLOUD'}


class ConfigApiTests(BaseTestCase):
    def test_config_is_readable_by_any_authenticated_user(self):
        response = api_client(make_student()).get('/api/v1/research-lab/config/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('enabled', response.data)

    def test_config_requires_authentication(self):
        self.assertEqual(api_client().get('/api/v1/research-lab/config/').status_code, 401)


class FeatureFlagTests(BaseTestCase):
    @override_settings(RESEARCH_LAB_ENABLED=False)
    def test_disabled_flag_403s_every_endpoint_for_staff_too(self):
        teacher = api_client(make_teacher())
        self.assertEqual(teacher.get('/api/v1/research-lab/runs/').status_code, 403)
        self.assertEqual(teacher.post('/api/v1/research-lab/runs/', VALID_PAYLOAD, format='json').status_code, 403)

    @override_settings(RESEARCH_LAB_ENABLED=False)
    def test_disabled_flag_still_serves_config_so_the_frontend_can_hide_the_link(self):
        response = api_client(make_teacher()).get('/api/v1/research-lab/config/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['enabled'])


class PermissionTests(BaseTestCase):
    def test_students_cannot_use_research_lab(self):
        client = api_client(make_student())
        self.assertEqual(client.get('/api/v1/research-lab/runs/').status_code, 403)
        self.assertEqual(client.post('/api/v1/research-lab/runs/', VALID_PAYLOAD, format='json').status_code, 403)

    def test_anonymous_is_rejected(self):
        self.assertEqual(api_client().get('/api/v1/research-lab/runs/').status_code, 401)

    def test_a_teacher_only_sees_their_own_runs(self):
        mine = make_run()
        make_run()  # someone else's
        client = api_client(mine.user)
        ids = [r['id'] for r in client.get('/api/v1/research-lab/runs/').data['results']]
        self.assertEqual(ids, [mine.pk])
        self.assertEqual(client.get(f'/api/v1/research-lab/runs/{mine.pk + 1}/').status_code, 404)

    def test_admin_sees_every_run(self):
        make_run()
        make_run()
        response = api_client(make_admin()).get('/api/v1/research-lab/runs/')
        self.assertEqual(response.data['count'], 2)

    def test_cannot_cancel_someone_elses_run(self):
        run = make_run()
        response = api_client(make_teacher()).post(f'/api/v1/research-lab/runs/{run.pk}/cancel/')
        self.assertEqual(response.status_code, 404)

    def test_nested_subresources_are_also_scoped_to_the_owner(self):
        run = make_run()
        other = api_client(make_teacher())
        for action in ('sources', 'agents', 'tools', 'metrics', 'assignment', 'lecture'):
            self.assertEqual(other.get(f'/api/v1/research-lab/runs/{run.pk}/{action}/').status_code, 404, action)
        self.assertEqual(other.get(f'/api/v1/research-lab/runs/{run.pk}/lecture/export/').status_code, 404)


class CreateAndCancelTests(BaseTestCase):
    def test_create_validates_material_types(self):
        teacher = make_teacher()
        make_llm_config()
        response = api_client(teacher).post('/api/v1/research-lab/runs/',
                                            {**VALID_PAYLOAD, 'material_types': ['NOT_A_TYPE']}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_custom_mode_requires_agent_overrides(self):
        teacher = make_teacher()
        make_llm_config()
        response = api_client(teacher).post('/api/v1/research-lab/runs/',
                                            {**VALID_PAYLOAD, 'llm_mode': 'CUSTOM'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_create_queues_the_workflow_and_assigns_the_owner(self):
        teacher = make_teacher()
        make_llm_config()
        with self.captureOnCommitCallbacks(execute=False):
            response = api_client(teacher).post('/api/v1/research-lab/runs/', VALID_PAYLOAD, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        run = ResearchRun.objects.get(pk=response.data['id'])
        self.assertEqual(run.user, teacher)
        self.assertEqual(run.status, ResearchRunStatus.PENDING)

    def test_create_accepts_the_lecture_option_which_is_off_by_default(self):
        teacher = make_teacher()
        make_llm_config()
        default_response = api_client(teacher).post('/api/v1/research-lab/runs/', VALID_PAYLOAD, format='json')
        self.assertEqual(default_response.data['generate_lecture'], False)

        with self.captureOnCommitCallbacks(execute=False):
            response = api_client(teacher).post('/api/v1/research-lab/runs/', {
                **VALID_PAYLOAD, 'generate_lecture': True, 'lecture_detail_level': 'HIGH'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.data['generate_lecture'], response.data['lecture_detail_level']), (True, 'HIGH'))

    def test_cancel_sets_the_flag_and_rejects_finished_runs(self):
        run = make_run()
        client = api_client(run.user)
        response = client.post(f'/api/v1/research-lab/runs/{run.pk}/cancel/')
        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        self.assertTrue(run.cancel_requested)

        run.status = ResearchRunStatus.COMPLETED
        run.save(update_fields=['status'])
        response = client.post(f'/api/v1/research-lab/runs/{run.pk}/cancel/')
        self.assertEqual(response.status_code, 409)


class SubresourceApiTests(BaseTestCase):
    def test_sources_agents_tools_assignment_and_metrics_after_a_real_run(self):
        make_llm_config()
        run = make_run()
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        with patch_providers(web=[], academic=academic), patch_fetch(), \
                patch_llm_json({PromptCode.RESEARCH_SOURCE_VALIDATION: ACCEPT_JSON,
                               PromptCode.RESEARCH_ASSIGNMENT_GENERATION: GENERATION_JSON,
                               PromptCode.RESEARCH_ASSIGNMENT_REVIEW: {'decision': 'approved', 'score': 90,
                                                                       'issues': []}}):
            run_workflow(run.pk)

        client = api_client(run.user)
        agents = client.get(f'/api/v1/research-lab/runs/{run.pk}/agents/')
        self.assertEqual(agents.status_code, 200)
        self.assertGreater(agents.data['count'], 0)

        assignment = client.get(f'/api/v1/research-lab/runs/{run.pk}/assignment/')
        self.assertEqual(assignment.status_code, 200)
        self.assertEqual(assignment.data['title'], 'RAG Assignment')

        metrics = client.get(f'/api/v1/research-lab/runs/{run.pk}/metrics/')
        self.assertEqual(metrics.status_code, 200)
        self.assertIn('max_agent_load_pct', metrics.data)
        self.assertEqual(metrics.data['status'], 'COMPLETED')

    def test_assignment_404s_when_none_was_generated(self):
        run = make_run(generate_assignment=False, status=ResearchRunStatus.COMPLETED)
        response = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/assignment/')
        self.assertEqual(response.status_code, 404)


class LectureApiTests(BaseTestCase):
    def _completed_run_with_lecture(self):
        make_llm_config()
        run = make_run(generate_lecture=True)
        academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
        with patch_providers(web=[], academic=academic), patch_fetch(), \
                patch_llm_json({PromptCode.RESEARCH_SOURCE_VALIDATION: ACCEPT_JSON,
                               PromptCode.RESEARCH_LECTURE_GENERATION: LECTURE_JSON,
                               PromptCode.RESEARCH_LECTURE_REVIEW: {'decision': 'approved', 'score': 90, 'issues': []},
                               PromptCode.RESEARCH_ASSIGNMENT_GENERATION: GENERATION_JSON,
                               PromptCode.RESEARCH_ASSIGNMENT_REVIEW: {'decision': 'approved', 'score': 90,
                                                                       'issues': []}}):
            run_workflow(run.pk)
        return run

    def test_lecture_action_returns_the_latest_version(self):
        run = self._completed_run_with_lecture()
        response = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/lecture/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data['title'], response.data['version'], response.data['status']),
                         ('Introduction to RAG', 1, 'APPROVED'))

    def test_lecture_404s_when_none_was_requested(self):
        run = make_run(generate_lecture=False, status=ResearchRunStatus.COMPLETED)
        response = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/lecture/')
        self.assertEqual(response.status_code, 404)

    def test_export_markdown_and_txt_download_the_plain_text(self):
        run = self._completed_run_with_lecture()
        client = api_client(run.user)
        for fmt, ext in (('md', 'md'), ('txt', 'txt')):
            response = client.get(f'/api/v1/research-lab/runs/{run.pk}/lecture/export/?export_format={fmt}')
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'.{ext}"', response['Content-Disposition'])
            self.assertIn('Introduction to RAG', response.content.decode())

    def test_export_docx_returns_a_real_word_document(self):
        run = self._completed_run_with_lecture()
        response = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/lecture/export/?export_format=docx')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'],
                         'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertIn('.docx"', response['Content-Disposition'])

        from docx import Document
        import io

        document = Document(io.BytesIO(response.content))
        text = '\n'.join(p.text for p in document.paragraphs)
        self.assertIn('Introduction to RAG', text)

    def test_export_404s_when_no_lecture_exists(self):
        run = make_run(generate_lecture=False, status=ResearchRunStatus.COMPLETED)
        response = api_client(run.user).get(f'/api/v1/research-lab/runs/{run.pk}/lecture/export/')
        self.assertEqual(response.status_code, 404)
