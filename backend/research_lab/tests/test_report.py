"""The load report: shares are computed from LLM + tool calls and checked against the 40% rule."""
from io import StringIO

from django.core.management import call_command

from core.testing import BaseTestCase, api_client, make_llm_config, make_teacher
from llm.models import GenerationRun
from research_lab.agents.boss import run_workflow
from research_lab.models import AgentExecution, ModuleSettings, ToolExecution
from research_lab.services import report
from research_lab.tests.fakes import FakeProvider, make_candidate, patch_fetch, patch_llm_json, patch_providers
from research_lab.tests.test_workflow import _lecture_responses, _validation_responses, make_run


def finished_run(**kw):
    run = make_run(generate_lecture=True, **kw)
    web = [FakeProvider('BRIGHTDATA', [make_candidate('Notes', provider='BRIGHTDATA')])]
    academic = [FakeProvider('OPENALEX', [make_candidate('Paper', provider='OPENALEX', doi='10.1/a')])]
    with patch_providers(web=web, academic=academic), patch_fetch(), \
            patch_llm_json({**_validation_responses(), **_lecture_responses()}):
        run_workflow(run.pk)
    run.refresh_from_db()
    return run


class LoadShareTests(BaseTestCase):
    def setUp(self):
        make_llm_config()

    def test_shares_are_calls_over_all_calls_and_sum_to_100(self):
        run = finished_run()
        # The LLM is faked out in workflow tests, so give the run real call records to count.
        validator = run.agent_executions.get(agent='SOURCE_VALIDATOR')
        config = make_llm_config(default=False, name='claude-test')
        for _ in range(3):
            GenerationRun.objects.create(configuration=config, question_text='q', status='SUCCESS', total_tokens=10,
                                         metadata={'run_id': run.pk, 'agent': 'SOURCE_VALIDATOR'})
        shares, total = report.load_shares(run)
        by_agent = {s['agent']: s for s in shares}
        self.assertEqual(by_agent['source_validator']['llm_calls'], 3)
        self.assertEqual(total, sum(s['calls'] for s in shares))
        self.assertAlmostEqual(sum(s['pct'] for s in shares), 100.0, delta=0.6)
        self.assertEqual(by_agent['boss']['calls'], 0)  # the orchestrator only plans: no LLM, no tool calls
        self.assertTrue(validator.pk)

    def test_skipped_tools_are_not_counted_as_calls(self):
        run = make_run()
        execution = AgentExecution.objects.create(run=run, agent='WEB_RESEARCH', sequence=1)
        ToolExecution.objects.create(run=run, agent_execution=execution, tool='YOUTUBE', status='SKIPPED')
        ToolExecution.objects.create(run=run, agent_execution=execution, tool='WIKIPEDIA', status='SUCCESS')
        ToolExecution.objects.create(run=run, agent_execution=execution, tool='WIKIPEDIA', status='FAILED')
        self.assertEqual(report.agent_calls(run)['WEB_RESEARCH']['tools'], 2)

    def test_the_limit_is_flagged_when_one_agent_does_too_much(self):
        run = make_run()
        web = AgentExecution.objects.create(run=run, agent='WEB_RESEARCH', sequence=1)
        acad = AgentExecution.objects.create(run=run, agent='ACADEMIC_RESEARCH', sequence=2)
        for _ in range(9):
            ToolExecution.objects.create(run=run, agent_execution=web, tool='BRIGHTDATA', status='SUCCESS')
        ToolExecution.objects.create(run=run, agent_execution=acad, tool='ARXIV', status='SUCCESS')
        data = report.build_report(run)
        self.assertFalse(data['load']['passed'])
        self.assertEqual((data['load']['max_pct'], data['load']['busiest_agent']), (90.0, 'Web Research'))
        self.assertIn('OVER', report.render_markdown(data))

    def test_a_full_pipeline_run_stays_within_the_limit_and_nine_agents_exist(self):
        data = report.build_report(finished_run())
        self.assertEqual(len(data['agents']), 9)
        self.assertTrue(data['load']['passed'], data['load'])
        self.assertEqual(data['run']['status'], 'COMPLETED')


class ReportEndpointTests(BaseTestCase):
    def setUp(self):
        make_llm_config()
        self.run = finished_run()

    def test_json_markdown_and_command(self):
        client = api_client(self.run.user)
        base = f'/api/v1/research-lab/runs/{self.run.pk}/report/'
        data = client.get(base).data
        self.assertEqual(data['run']['id'], self.run.pk)
        self.assertIn('limit_pct', data['load'])
        markdown = client.get(base + '?as=markdown')
        self.assertIn('attachment', markdown['Content-Disposition'])
        self.assertIn('Load distribution', markdown.content.decode())
        self.assertEqual(client.get(base + '?as=json')['Content-Type'], 'application/json')
        out = StringIO()
        call_command('research_report', self.run.pk, stdout=out)
        self.assertIn('Busiest agent', out.getvalue())

    def test_other_users_cannot_read_it(self):
        self.assertIn(api_client(make_teacher()).get(f'/api/v1/research-lab/runs/{self.run.pk}/report/').status_code, (403, 404))


class MaterialsSearchSwitchTests(BaseTestCase):
    def test_switching_it_off_blocks_new_searches_but_not_full_runs(self):
        teacher = make_teacher()
        ModuleSettings.objects.update_or_create(pk=1, defaults={'materials_search_enabled': False})
        client = api_client(teacher)
        blocked = client.post('/api/v1/research-lab/runs/', {'topic': 'x', 'mode': 'SEARCH', 'llm_mode': 'LOCAL'}, format='json')
        full = client.post('/api/v1/research-lab/runs/', {'topic': 'x', 'mode': 'RESEARCH', 'llm_mode': 'LOCAL'}, format='json')
        self.assertEqual((blocked.status_code, full.status_code), (400, 201))
        self.assertFalse(client.get('/api/v1/research-lab/config/').data['materials_search_enabled'])
        ModuleSettings.objects.filter(pk=1).update(materials_search_enabled=True)
        again = client.post('/api/v1/research-lab/runs/', {'topic': 'x', 'mode': 'SEARCH', 'llm_mode': 'LOCAL'}, format='json')
        self.assertEqual(again.status_code, 201)


class StartTimeTests(BaseTestCase):
    def test_a_finished_run_remembers_when_it_started(self):
        make_llm_config()
        run = finished_run()
        self.assertIsNotNone(run.started_at)
        self.assertGreaterEqual(report.build_report(run)['run']['duration_seconds'], 0)
