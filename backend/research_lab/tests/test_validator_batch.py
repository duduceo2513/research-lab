"""The Source Validator judges sources in batches, so it does not dominate the call count."""
from django.test import override_settings

from core.testing import BaseTestCase, make_llm_config
from llm.models import PromptCode
from research_lab.agents import source_validator
from research_lab.models import ResearchSource
from research_lab.tests.fakes import patch_llm_json
from research_lab.tests.test_workflow import ACCEPT_JSON, REJECT_JSON, make_run


def item(source_id, base=ACCEPT_JSON):
    return {**base, 'source_id': source_id}


class BatchValidationTests(BaseTestCase):
    def setUp(self):
        make_llm_config()
        self.run_obj = make_run()
        self.sources = [ResearchSource.objects.create(run=self.run_obj, provider='ARXIV', external_id=str(i), title=f'Paper {i}')
                        for i in range(1, 9)]

    def validate(self, responses, sources=None):
        with patch_llm_json(responses) as calls:
            _, accepted = source_validator.run(self.run_obj, 1, sources or self.sources)
        return calls, accepted

    @override_settings(RESEARCH_LAB_VALIDATION_BATCH=4)
    def test_eight_sources_take_two_requests_not_eight(self):
        batch = {'results': [item(i) for i in range(1, 5)]}  # answered by position within the batch
        calls, accepted = self.validate({PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH: batch})
        self.assertEqual(calls, [PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH] * 2)
        self.assertEqual(len(accepted), 8)
        self.assertEqual(self.run_obj.agent_executions.get().output_summary['llm_calls'], 2)

    @override_settings(RESEARCH_LAB_VALIDATION_BATCH=4)
    def test_a_source_the_batch_skipped_is_scored_on_its_own(self):
        batch = {'results': [item(1), item(2, REJECT_JSON), item(4)]}  # position 3 is missing
        calls, accepted = self.validate({PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH: batch,
                                         PromptCode.RESEARCH_SOURCE_VALIDATION: ACCEPT_JSON}, self.sources[:4])
        self.assertEqual(calls, [PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH, PromptCode.RESEARCH_SOURCE_VALIDATION])
        self.assertEqual([s.decision for s in self.sources[:4]], ['ACCEPT', 'REJECT', 'ACCEPT', 'ACCEPT'])

    @override_settings(RESEARCH_LAB_VALIDATION_BATCH=4)
    def test_results_are_matched_by_database_id_too(self):
        batch = {'results': [item(s.pk, REJECT_JSON) for s in self.sources[:4]]}
        calls, accepted = self.validate({PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH: batch}, self.sources[:4])
        self.assertEqual((calls, accepted), ([PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH], []))

    @override_settings(RESEARCH_LAB_VALIDATION_BATCH=4)
    def test_an_unreadable_batch_falls_back_to_single_requests(self):
        calls, accepted = self.validate({PromptCode.RESEARCH_SOURCE_VALIDATION: ACCEPT_JSON}, self.sources[:4])
        self.assertEqual(calls, [PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH] + [PromptCode.RESEARCH_SOURCE_VALIDATION] * 4)
        self.assertEqual(len(accepted), 4)

    @override_settings(RESEARCH_LAB_VALIDATION_BATCH=1)
    def test_batch_size_one_restores_one_request_per_source(self):
        calls, _ = self.validate({PromptCode.RESEARCH_SOURCE_VALIDATION: ACCEPT_JSON}, self.sources[:3])
        self.assertEqual(calls, [PromptCode.RESEARCH_SOURCE_VALIDATION] * 3)
