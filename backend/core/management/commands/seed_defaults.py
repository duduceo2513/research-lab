"""Idempotent bootstrap of LLM providers, LLM configurations and the Research Lab prompt templates.

No secrets are written: providers only reference environment variable NAMES.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from llm.models import LLMConfiguration, LLMProvider, PromptTemplate
from llm.prompts.defaults import DEFAULT_PROMPTS

PROVIDERS = [
    {'code': 'OPENAI', 'display_name': 'OpenAI', 'secret_env_name': 'OPENAI_API_KEY', 'base_url': None},
    {'code': 'ANTHROPIC', 'display_name': 'Anthropic (Claude)', 'secret_env_name': 'ANTHROPIC_API_KEY',
     'base_url': None},
    {'code': 'LOCAL', 'display_name': 'Local LLM (OpenAI-compatible)', 'secret_env_name': None,
     'base_url': None},
]

# pricing = USD per 1M tokens (used for GenerationRun.estimated_cost); adjust to your contract.
CONFIGURATIONS = [
    {'provider': 'Anthropic (Claude)', 'name': 'Claude Opus 5', 'model_name': 'claude-opus-5',
     'temperature': 0.2, 'max_tokens': 1024, 'context_window': 1_000_000, 'is_default': True,
     'metadata': {'pricing': {'input_per_1m': 5.0, 'output_per_1m': 25.0}}},
    {'provider': 'Anthropic (Claude)', 'name': 'Claude Sonnet 5', 'model_name': 'claude-sonnet-5',
     'temperature': 0.2, 'max_tokens': 1024, 'context_window': 1_000_000, 'is_default': False,
     'metadata': {'pricing': {'input_per_1m': 2.0, 'output_per_1m': 10.0}}},
    {'provider': 'OpenAI', 'name': 'GPT-4o mini', 'model_name': 'gpt-4o-mini',
     'temperature': 0.2, 'max_tokens': 1024, 'context_window': 128_000, 'is_default': False,
     'metadata': {'pricing': {'input_per_1m': 0.15, 'output_per_1m': 0.6}}},
    # model_name is only a starting point — it must match a model actually pulled in Ollama (or
    # whatever OpenAI-compatible server LOCAL_LLM_BASE_URL points at). An admin can repoint this at
    # any locally available model from Settings -> Research Lab (which lists them live).
    # max_tokens is deliberately generous: a "thinking" local model (e.g. the Qwen3 family) spends
    # a variable, sometimes large number of its output budget on hidden chain-of-thought before the
    # visible answer — too small a cap truncates mid-thought and the response comes back empty.
    {'provider': 'Local LLM (OpenAI-compatible)', 'name': 'Local model', 'model_name': 'qwen3:8b',
     'temperature': 0.2, 'max_tokens': 8192, 'context_window': 32_768, 'is_default': False,
     'metadata': {'pricing': {'input_per_1m': 0.0, 'output_per_1m': 0.0}}},
]


class Command(BaseCommand):
    help = 'Create default LLM providers/configurations and prompt templates.'

    @transaction.atomic
    def handle(self, *args, **options):
        providers = {}
        for spec in PROVIDERS:
            obj, _ = LLMProvider.objects.get_or_create(display_name=spec['display_name'], defaults=spec)
            providers[obj.display_name] = obj

        for spec in CONFIGURATIONS:
            spec = dict(spec)
            provider = providers[spec.pop('provider')]
            is_default = spec.pop('is_default') and not LLMConfiguration.objects.filter(is_default=True).exists()
            LLMConfiguration.objects.get_or_create(name=spec['name'], defaults={
                **spec, 'provider': provider, 'is_default': is_default})

        for spec in DEFAULT_PROMPTS:
            PromptTemplate.objects.get_or_create(code=spec['code'], version=1, defaults={
                'name': spec['name'], 'system_prompt': spec['system_prompt'],
                'user_template': spec['user_template'],
                'is_active': not PromptTemplate.objects.filter(code=spec['code'], is_active=True).exists()})

        self.stdout.write(self.style.SUCCESS('Defaults are in place.'))
