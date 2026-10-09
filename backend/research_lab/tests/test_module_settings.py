from core.testing import BaseTestCase, api_client, make_admin, make_llm_config, make_teacher
from research_lab.agents import academic_research, web_research
from research_lab.models import LLMMode, ModuleSettings, ResearchRun
from research_lab.tests.fakes import FakeProvider, make_candidate, patch_providers
from research_lab.tests.test_workflow import make_run


class ModuleSettingsModelTests(BaseTestCase):
    def test_load_is_a_singleton_with_sane_defaults(self):
        first = ModuleSettings.load()
        self.assertEqual((first.pk, first.default_llm_mode, first.disabled_providers), (1, LLMMode.LOCAL, []))
        self.assertEqual(ModuleSettings.load().pk, first.pk)

    def test_is_provider_enabled_reflects_the_disabled_list(self):
        settings_row = ModuleSettings.load()
        self.assertTrue(ModuleSettings.is_provider_enabled('ARXIV'))
        settings_row.disabled_providers = ['ARXIV']
        settings_row.save(update_fields=['disabled_providers'])
        self.assertFalse(ModuleSettings.is_provider_enabled('ARXIV'))
        self.assertTrue(ModuleSettings.is_provider_enabled('CROSSREF'))


class AgentGatingTests(BaseTestCase):
    def test_a_disabled_but_configured_provider_is_skipped_not_queried(self):
        ModuleSettings.load().__class__.objects.filter(pk=1).update(disabled_providers=['OPENALEX'])
        provider = FakeProvider('OPENALEX', [make_candidate('Should not appear')])
        with patch_providers(academic=[provider]):
            _, candidates = academic_research.run(make_run(), 1)
        self.assertEqual((candidates, provider.calls), ([], []))

    def test_a_disabled_web_provider_is_skipped_not_queried(self):
        ModuleSettings.load().__class__.objects.filter(pk=1).update(disabled_providers=['BRIGHTDATA'])
        provider = FakeProvider('BRIGHTDATA', [make_candidate('Should not appear')])
        with patch_providers(web=[provider]):
            _, candidates = web_research.run(make_run(), 1)
        self.assertEqual((candidates, provider.calls), ([], []))


class RunSerializerDefaultModeTests(BaseTestCase):
    def test_llm_mode_defaults_from_module_settings_when_omitted(self):
        make_llm_config()
        ModuleSettings.load().__class__.objects.filter(pk=1).update(default_llm_mode=LLMMode.CLOUD)
        with self.captureOnCommitCallbacks(execute=False):
            response = api_client(make_teacher()).post('/api/v1/research-lab/runs/', {
                'topic': 'x', 'education_level': 'MASTER', 'material_types': ['PAPERS'],
                'generate_assignment': False}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(ResearchRun.objects.get(pk=response.data['id']).llm_mode, LLMMode.CLOUD)


class ModuleSettingsApiTests(BaseTestCase):
    def test_only_admin_can_read_or_write_settings(self):
        teacher = api_client(make_teacher())
        self.assertEqual(teacher.get('/api/v1/research-lab/settings/').status_code, 403)
        self.assertEqual(teacher.patch('/api/v1/research-lab/settings/', {'default_llm_mode': 'CLOUD'},
                                       format='json').status_code, 403)

    def test_admin_can_read_and_update_settings(self):
        admin = api_client(make_admin())
        initial = admin.get('/api/v1/research-lab/settings/')
        self.assertEqual(initial.status_code, 200)
        self.assertIn('providers', initial.data)
        updated = admin.patch('/api/v1/research-lab/settings/',
                              {'default_llm_mode': 'HYBRID', 'disabled_providers': ['GOOGLE_BOOKS']}, format='json')
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual((updated.data['default_llm_mode'], updated.data['disabled_providers']),
                         ('HYBRID', ['GOOGLE_BOOKS']))
        provider_codes = {p['code']: p for p in updated.data['providers']}
        self.assertFalse(provider_codes['GOOGLE_BOOKS']['enabled'])
        self.assertTrue(provider_codes['ARXIV']['enabled'])

    def test_rejects_an_unknown_provider_code(self):
        response = api_client(make_admin()).patch('/api/v1/research-lab/settings/',
                                                   {'disabled_providers': ['NOT_A_PROVIDER']}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_config_endpoint_exposes_provider_status_and_default_mode_to_any_user(self):
        ModuleSettings.load().__class__.objects.filter(pk=1).update(disabled_providers=['CROSSREF'])
        response = api_client(make_teacher()).get('/api/v1/research-lab/config/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('default_llm_mode', response.data)
        codes = {p['code']: p['enabled'] for p in response.data['providers']}
        self.assertFalse(codes['CROSSREF'])
