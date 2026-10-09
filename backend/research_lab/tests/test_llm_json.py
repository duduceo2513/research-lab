from unittest import mock

from core.exceptions import ExternalServiceError
from core.testing import BaseTestCase, fake_llm, make_llm_config
from llm.models import PromptCode
from research_lab.services import llm_json
from research_lab.services.llm_json import _close_unbalanced_brackets


class CallStructuredTests(BaseTestCase):
    def test_parses_a_clean_json_reply(self):
        config = make_llm_config()
        with fake_llm('{"decision": "approved", "score": 90, "issues": []}'):
            parsed, run = llm_json.call_structured(
                question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW, configuration=config,
                variables={'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''},
                metadata={})
        self.assertEqual(parsed, {'decision': 'approved', 'score': 90, 'issues': []})
        self.assertEqual(run.status, 'SUCCESS')

    def test_strips_markdown_code_fences(self):
        config = make_llm_config()
        with fake_llm('```json\n{"decision": "approved", "score": 90, "issues": []}\n```'):
            parsed, _run = llm_json.call_structured(
                question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW, configuration=config,
                variables={'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''},
                metadata={})
        self.assertEqual(parsed['decision'], 'approved')

    def test_unparsable_reply_returns_none_without_raising(self):
        config = make_llm_config()
        with fake_llm('Sure, here is my opinion on the assignment: looks good!'):
            parsed, run = llm_json.call_structured(
                question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW, configuration=config,
                variables={'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''},
                metadata={})
        self.assertIsNone(parsed)
        self.assertEqual(run.status, 'SUCCESS')  # the call itself succeeded; only parsing failed

    def test_retries_once_on_a_transient_provider_failure(self):
        config = make_llm_config()
        good_run = mock.Mock(response_text='{"decision": "approved", "score": 90, "issues": []}')
        with mock.patch('research_lab.services.llm_json.generation.generate_answer',
                        side_effect=[ExternalServiceError('provider timed out'), good_run]), \
                mock.patch('time.sleep'):
            parsed, run = llm_json.call_structured(
                question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW, configuration=config,
                variables={'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''},
                metadata={})
        self.assertEqual(parsed['decision'], 'approved')
        self.assertIs(run, good_run)

    def test_raises_after_exhausting_retries(self):
        config = make_llm_config()
        with mock.patch('research_lab.services.llm_json.generation.generate_answer',
                        side_effect=ExternalServiceError('still down')), mock.patch('time.sleep'):
            with self.assertRaises(ExternalServiceError):
                llm_json.call_structured(
                    question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW, configuration=config,
                    variables={'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''},
                    metadata={})

    def test_a_reply_missing_only_the_final_brace_is_repaired_and_parsed(self):
        # Regression test: a local reasoning model (qwen3.5) was observed stopping generation
        # (finish_reason: stop, well under max_tokens) exactly one character short of the closing
        # "}", on ~15% of real Source Validator calls — otherwise perfectly valid JSON.
        config = make_llm_config()
        truncated = ('{"relevance": 85, "overall_score": 51, "decision": "review", '
                    '"reasons": ["a", "b"]')
        with fake_llm(truncated):
            parsed, run = llm_json.call_structured(
                question='q', prompt_code=PromptCode.RESEARCH_SOURCE_VALIDATION, configuration=config,
                variables={}, metadata={})
        self.assertEqual(parsed, {'relevance': 85, 'overall_score': 51, 'decision': 'review', 'reasons': ['a', 'b']})
        self.assertEqual(run.status, 'SUCCESS')


class BracketRepairTests(BaseTestCase):
    def test_leaves_already_balanced_text_unchanged(self):
        text = '{"a": 1, "b": ["x", "y"]}'
        self.assertEqual(_close_unbalanced_brackets(text), text)

    def test_closes_a_missing_outer_brace(self):
        self.assertEqual(_close_unbalanced_brackets('{"a": 1, "b": ["x"]'), '{"a": 1, "b": ["x"]}')

    def test_closes_a_missing_array_and_object(self):
        self.assertEqual(_close_unbalanced_brackets('{"a": 1, "b": ["x", "y"'), '{"a": 1, "b": ["x", "y"]}')

    def test_ignores_brace_like_characters_inside_strings(self):
        self.assertEqual(_close_unbalanced_brackets('{"a": "looks like } but isn\'t"'),
                         '{"a": "looks like } but isn\'t"}')

    def test_closes_a_dangling_unterminated_string_too(self):
        self.assertEqual(_close_unbalanced_brackets('{"a": "oops, cut off mid-strin'),
                         '{"a": "oops, cut off mid-strin"}')

    def test_closes_an_array_the_model_forgot_before_a_closer_for_the_wrong_level(self):
        # Regression test: a real Source Validator reply closed the outer object but never the
        # "reasons" array around it — {"reasons": ["a", "b"} (note the `}` where `]` was due).
        self.assertEqual(_close_unbalanced_brackets('{"reasons": ["a", "b"}'), '{"reasons": ["a", "b"]}')

    def test_drops_a_stray_closer_once_nothing_is_left_open(self):
        # Regression test: another real reply closed in the wrong order *and* left a redundant
        # trailing closer — {"reasons": ["a"}] (]  at the very end has nothing left to close).
        self.assertEqual(_close_unbalanced_brackets('{"reasons": ["a"}]'), '{"reasons": ["a"]}')


class FallbackTests(BaseTestCase):
    VARIABLES = {'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''}

    def call(self, config):
        real = llm_json.generation.generate_answer
        used = []

        def generate(question, *, configuration, **kwargs):
            used.append(configuration.name)
            if configuration.provider.code == 'LOCAL':
                raise ExternalServiceError('Ollama is switched off')
            return real(question, configuration=configuration, **kwargs)

        with fake_llm('{"decision": "approved", "score": 90, "issues": []}'), \
                mock.patch.object(llm_json.generation, 'generate_answer', side_effect=generate), \
                mock.patch('research_lab.services.llm_json.RETRY_ATTEMPTS', 1):
            parsed, _ = llm_json.call_structured(question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW,
                                                 configuration=config, variables=self.VARIABLES, metadata={})
        return parsed, used

    def test_an_unreachable_local_model_falls_back_to_the_cloud_model(self):
        local = make_llm_config('LOCAL', name='local-qwen')
        make_llm_config('ANTHROPIC', default=False, name='claude')
        parsed, used = self.call(local)
        self.assertEqual((parsed['decision'], used), ('approved', ['local-qwen', 'claude']))

    def test_with_no_other_tier_the_original_error_surfaces(self):
        local = make_llm_config('LOCAL', name='local-qwen')
        with self.assertRaises(ExternalServiceError):
            self.call(local)


class OutputBudgetTests(BaseTestCase):
    VARIABLES = {'topic': 't', 'education_level': 'MASTER', 'sources': '', 'assignment': ''}

    def test_agent_calls_get_room_for_long_documents_whatever_the_chat_limit_is(self):
        config = make_llm_config(max_tokens=1024)
        sent = []
        real = llm_json.generation.execute_run

        def spy(run, **kwargs):
            sent.append(run.metadata.get('max_tokens_override'))
            return real(run, **kwargs)

        with fake_llm('{"decision": "approved", "score": 90, "issues": []}'), \
                mock.patch.object(llm_json.generation, 'execute_run', side_effect=spy):
            llm_json.call_structured(question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW,
                                     configuration=config, variables=self.VARIABLES, metadata={})
        self.assertEqual(sent, [8192])

    def test_a_reply_cut_off_by_the_token_limit_is_requested_again_with_more_room(self):
        config = make_llm_config(max_tokens=1024)
        sent = []
        real = llm_json.generation.execute_run

        def truncating(run, **kwargs):
            sent.append(run.metadata.get('max_tokens_override'))
            result = real(run, **kwargs)
            if len(sent) == 1:  # first answer: cut off mid-document
                result.response_text = '{"decision": "approved", "score": 9'
                result.metadata = {**result.metadata, 'finish_reason': 'max_tokens'}
            return result

        with fake_llm('{"decision": "approved", "score": 90, "issues": []}'), \
                mock.patch.object(llm_json.generation, 'execute_run', side_effect=truncating):
            parsed, _ = llm_json.call_structured(question='q', prompt_code=PromptCode.RESEARCH_ASSIGNMENT_REVIEW,
                                                 configuration=config, variables=self.VARIABLES, metadata={})
        self.assertEqual((parsed['score'], sent), (90, [8192, 16384]))
