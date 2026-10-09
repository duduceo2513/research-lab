"""Agent Workspace: the persisted event stream, the server-computed snapshot, the REST endpoints
and the live WebSocket. The workflow itself is the same mocked end-to-end run the other tests use."""
from unittest import mock

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import AccessToken

from core.asgi import application
from core.testing import (BaseTestCase, BaseTransactionTestCase, api_client, make_llm_config, make_student,
                          make_teacher)
from llm.models import PromptCode
from research_lab.agents.boss import run_workflow
from research_lab.models import LLMMode, ResearchEvent
from research_lab.services import events, workspace
from research_lab.tests.fakes import FakeProvider, make_candidate, patch_fetch, patch_llm_json, patch_providers
from research_lab.tests.test_workflow import (LECTURE_JSON, NEEDS_REVISION_JSON, _lecture_responses,
                                              _validation_responses, make_run)


def run_full(run, **overrides):
    web = [FakeProvider('BRIGHTDATA', [make_candidate('RAG course notes', provider='BRIGHTDATA')])]
    academic = [FakeProvider('OPENALEX', [make_candidate('A RAG Paper', provider='OPENALEX', doi='10.1/a')])]
    responses = {**_validation_responses(), **_lecture_responses(), **overrides}
    with patch_providers(web=web, academic=academic), patch_fetch(), patch_llm_json(responses):
        run_workflow(run.pk)


class EventStreamTests(BaseTestCase):
    def setUp(self):
        make_llm_config()

    def test_a_run_leaves_a_complete_persisted_trail(self):
        run = make_run(generate_lecture=True, llm_mode=LLMMode.LOCAL)
        run_full(run)

        by_type = {t: list(run.events.filter(type=t)) for t in events.EVENT_TYPES}
        for event_type in events.EVENT_TYPES:
            if event_type != events.AGENT_FAILED:  # nothing fails in a healthy run (see the cancel test)
                self.assertTrue(by_type[event_type], f'no {event_type} events were recorded')

        started = {e.agent for e in by_type[events.AGENT_STARTED] if e.status == 'working'}
        self.assertTrue({'boss', 'web_research', 'academic_research', 'document_retrieval', 'document_analysis', 'source_validator',
                         'lecture_builder', 'assignment_generator'} <= started)
        self.assertTrue(any(e.agent == 'final_reviewer' and e.status == 'reviewing'
                            for e in by_type[events.AGENT_STARTED]))

        pairs = {(e.payload['from_agent'], e.payload['to_agent']) for e in by_type[events.AGENT_HANDOFF]}
        self.assertTrue({('boss', 'web_research'), ('web_research', 'document_retrieval'),
                         ('document_retrieval', 'document_analysis'), ('document_analysis', 'source_validator'), ('source_validator', 'lecture_builder'),
                         ('lecture_builder', 'final_reviewer'), ('final_reviewer', 'assignment_generator'),
                         ('assignment_generator', 'final_reviewer')} <= pairs)

        tools = {e.payload['tool'] for e in by_type[events.TOOL_COMPLETED] + by_type[events.TOOL_STARTED]}
        self.assertTrue({'BRIGHTDATA', 'OPENALEX', 'HTTP', 'Extractor'} <= tools)
        completed_tool = next(e for e in by_type[events.TOOL_COMPLETED]
                              if e.payload['tool'] == 'OPENALEX' and e.status == 'completed')
        self.assertEqual(completed_tool.payload['result_count'], 1)

        decisions = {(e.agent, e.status) for e in by_type[events.AGENT_DECISION]}
        self.assertIn(('source_validator', 'accept'), decisions)
        self.assertIn(('final_reviewer', 'approved'), decisions)

    def test_events_never_carry_model_output(self):
        """Only the short written summaries are published, never the raw model response."""
        run = make_run(generate_lecture=True)
        run_full(run)
        blob = ' '.join(f'{e.summary} {e.payload}' for e in run.events.all())
        self.assertNotIn(LECTURE_JSON['sections'][0]['content'], blob)

    def test_reviewer_sending_work_back_is_a_real_revision_handoff(self):
        run = make_run(generate_lecture=False)
        run_full(run, **{PromptCode.RESEARCH_ASSIGNMENT_REVIEW: NEEDS_REVISION_JSON})
        revisions = [e for e in run.events.filter(type=events.AGENT_HANDOFF) if e.payload.get('revision')]
        self.assertTrue(revisions)
        self.assertEqual((revisions[0].payload['from_agent'], revisions[0].payload['to_agent']),
                         ('final_reviewer', 'assignment_generator'))
        self.assertEqual(revisions[0].payload['target'], 'assignment')
        self.assertTrue(run.events.filter(type=events.AGENT_DECISION, status='revision_required').exists())

    def test_cancelled_run_emits_agent_failed_and_run_status(self):
        run = make_run(cancel_requested=True)
        run_full(run)
        failed = list(run.events.filter(type=events.AGENT_FAILED))
        self.assertEqual([(e.agent, e.status) for e in failed], [('boss', 'cancelled')])
        self.assertTrue(run.events.filter(type=events.RUN_STATUS, status='cancelled').exists())

    def test_emit_failure_never_breaks_the_caller(self):
        run = make_run()
        with mock.patch.object(ResearchEvent.objects, 'create', side_effect=RuntimeError('db hiccup')):
            self.assertIsNone(events.emit(run, events.AGENT_NOTE, 'boss', summary='lost'))
        # ...and the surrounding transaction is still usable afterwards.
        self.assertIsNotNone(events.emit(run, events.AGENT_NOTE, 'boss', summary='fine'))


class WorkspaceSnapshotTests(BaseTestCase):
    def setUp(self):
        make_llm_config()

    def test_snapshot_reports_server_side_state_and_models(self):
        run = make_run(generate_lecture=True, llm_mode=LLMMode.LOCAL)
        run_full(run)
        run.refresh_from_db()
        state = workspace.build(run)
        agents = {a['agent']: a for a in state['agents']}

        self.assertEqual(state['agents'][0]['agent'], 'boss')
        self.assertEqual((agents['boss']['provider'], agents['boss']['provider_kind']), ('system', 'system'))  # deterministic
        self.assertEqual((agents['source_validator']['provider'], agents['source_validator']['provider_kind']),
                         ('local', 'local'))
        self.assertEqual(agents['source_validator']['model_name'], 'fake-model')
        self.assertEqual(agents['final_reviewer']['status'], 'completed')
        unique = run.sources.filter(is_duplicate=False).count()  # the fake fetcher returns identical content
        self.assertEqual(agents['source_validator']['progress']['reviewed'], unique)
        self.assertEqual(agents['source_validator']['progress']['accepted'], unique)
        self.assertEqual(agents['lecture_builder']['decision']['decision'], 'drafted')
        self.assertTrue(agents['academic_research']['progress']['steps'])

        rs = state['research_state']
        self.assertGreaterEqual(rs['sources_discovered'], 2)  # raw results, before de-duplication
        self.assertEqual(rs['sources_accepted'], unique)
        self.assertEqual(rs['lecture']['status'], 'APPROVED')
        self.assertEqual(rs['assignment']['status'], 'APPROVED')
        self.assertEqual(state['run']['status'], 'COMPLETED')
        self.assertEqual(state['last_event_id'], run.events.order_by('-id').first().pk)

        metrics = state['metrics']
        self.assertEqual(metrics['local_calls'] + metrics['claude_calls'], metrics['llm_calls'])
        self.assertAlmostEqual(sum(item['pct'] for item in metrics['load']), 100.0, delta=0.6)
        self.assertEqual(metrics['load_ok'], metrics['max_agent_load_pct'] <= 40.0)

    def test_mission_result_next_step_and_separate_counters(self):
        run = make_run(generate_lecture=True, llm_mode=LLMMode.LOCAL)
        run_full(run)
        run.refresh_from_db()
        state = workspace.build(run)
        agents = {a['agent']: a for a in state['agents']}
        self.assertTrue(state['mission']['finished'])
        self.assertIn('Document Analysis', agents['academic_research']['next_step'])
        self.assertIn('sources found', agents['academic_research']['result'])
        self.assertIn('accepted', agents['source_validator']['result'])
        metrics = state['metrics']
        for key in ('agent_runs', 'llm_calls', 'tool_calls', 'analyzed'):
            self.assertIn(key, metrics)
        self.assertEqual(metrics['agent_runs'], run.agent_executions.count())
        self.assertNotEqual(metrics['agent_runs'], metrics['tool_calls'])

    def test_live_mission_follows_real_validator_progress(self):
        run = make_run()
        events.emit(run, events.AGENT_STARTED, 'source_validator', status='working', summary='Started')
        events.emit(run, events.AGENT_PROGRESS, 'source_validator', steps=[], input_sources=20, reviewed=13,
                    accepted=7, rejected=6, current_source='Python Programming Lecture Notes')
        run.status = 'VALIDATING'
        run.save()
        mission = workspace.build(run)['mission']
        self.assertEqual((mission['title'], mission['done'], mission['total'], mission['percent']),
                         ('Source validation', 13, 20, 65))
        self.assertEqual(mission['current_item'], 'Python Programming Lecture Notes')

    def test_agents_that_were_not_requested_are_disabled_not_waiting(self):
        run = make_run(generate_lecture=False, generate_assignment=False, material_types=['PAPERS'])
        agents = {a['agent']: a for a in workspace.build(run)['agents']}
        for name in ('web_research', 'lecture_builder', 'assignment_generator', 'final_reviewer'):
            self.assertEqual(agents[name]['status'], 'disabled', name)
            self.assertTrue(agents[name]['disabled_reason'])
        self.assertEqual(agents['academic_research']['status'], 'waiting')

    def test_hybrid_mode_splits_local_and_cloud(self):
        make_llm_config('ANTHROPIC', default=False, model_name='claude-test')
        run = make_run(generate_lecture=True, llm_mode=LLMMode.HYBRID)
        agents = {a['agent']: a for a in workspace.build(run)['agents']}
        self.assertEqual(agents['source_validator']['provider_kind'], 'local')
        self.assertEqual(agents['lecture_builder']['provider'], 'anthropic')
        self.assertEqual(agents['lecture_builder']['provider_kind'], 'cloud')
        self.assertEqual(agents['lecture_builder']['model_name'], 'claude-test')


class WorkspaceApiTests(BaseTestCase):
    def setUp(self):
        make_llm_config()
        self.teacher = make_teacher()
        self.run = make_run(user=self.teacher)
        run_full(self.run)

    def test_events_endpoint_supports_resuming_after_an_id(self):
        client = api_client(self.teacher)
        everything = client.get(f'/api/v1/research-lab/runs/{self.run.pk}/events/').data
        self.assertEqual(len(everything), self.run.events.count())
        self.assertEqual([e['id'] for e in everything], sorted(e['id'] for e in everything))
        tail = client.get(f'/api/v1/research-lab/runs/{self.run.pk}/events/?after_id={everything[-3]["id"]}').data
        self.assertEqual([e['id'] for e in tail], [e['id'] for e in everything[-2:]])
        self.assertEqual(client.get(f'/api/v1/research-lab/runs/{self.run.pk}/events/?after_id=x').status_code, 400)

    def test_workspace_endpoint(self):
        data = api_client(self.teacher).get(f'/api/v1/research-lab/runs/{self.run.pk}/workspace/').data
        self.assertEqual(len(data['agents']), 9)
        self.assertEqual(data['run']['id'], self.run.pk)

    def test_other_teachers_and_students_get_nothing(self):
        for user in (make_teacher(), make_student()):
            client = api_client(user)
            for path in ('events', 'workspace'):
                self.assertIn(client.get(f'/api/v1/research-lab/runs/{self.run.pk}/{path}/').status_code, (403, 404))


class WorkspaceSocketTests(BaseTransactionTestCase):
    """TransactionTestCase: the consumer reads the DB from worker threads, so rows must be committed."""

    def setUp(self):
        make_llm_config()
        self.teacher = make_teacher()
        self.run = make_run(user=self.teacher)

    async def _connect(self, user, run_id=None):
        token = str(AccessToken.for_user(user))
        communicator = WebsocketCommunicator(
            application, f'/ws/research-lab/runs/{run_id or self.run.pk}/?token={token}')
        communicator.scope['headers'] = list(communicator.scope.get('headers', [])) + [
            (b'origin', b'http://localhost:5173')]
        connected, code = await communicator.connect()
        return communicator, connected, code

    async def test_owner_receives_events_as_they_are_written(self):
        comm, connected, _ = await self._connect(self.teacher)
        self.assertTrue(connected)
        self.assertEqual((await comm.receive_json_from(timeout=5))['event'], 'connected')

        event = await sync_to_async(events.emit)(self.run, events.AGENT_NOTE, 'web_research',
                                                 summary='Searching Bright Data', kind='info')
        message = await comm.receive_json_from(timeout=5)
        self.assertEqual(message['event'], 'research_event')
        self.assertEqual(message['payload']['id'], event.pk)
        self.assertEqual(message['payload']['summary'], 'Searching Bright Data')
        self.assertTrue(await sync_to_async(ResearchEvent.objects.filter(pk=event.pk).exists)())
        await comm.disconnect()

    async def test_other_users_and_anonymous_are_refused(self):
        _, connected, code = await self._connect(await sync_to_async(make_teacher)())
        self.assertFalse(connected)
        self.assertEqual(code, 4404)
        _, connected, code = await self._connect(await sync_to_async(make_student)())
        self.assertFalse(connected)
        self.assertEqual(code, 4403)
        comm = WebsocketCommunicator(application, f'/ws/research-lab/runs/{self.run.pk}/')
        comm.scope['headers'] = list(comm.scope.get('headers', [])) + [(b'origin', b'http://localhost:5173')]
        connected, code = await comm.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
