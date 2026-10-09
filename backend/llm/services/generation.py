"""Runs an LLM call and records everything about it in a ``GenerationRun``.

Lifecycle: ``create_run`` (PENDING, prompts rendered) → ``execute_run`` (RUNNING → SUCCESS/FAILED).
``generate_answer`` does both.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from decimal import Decimal

from core.exceptions import ServiceError
from llm.models import GenerationRun, GenerationStatus, LLMConfiguration, PromptTemplate
from llm.prompts.defaults import DEFAULT_PROMPTS
from llm.providers.base import GenerationRequest, GenerationResult
from llm.providers.factory import get_provider
from llm.tokens import count_tokens

logger = logging.getLogger('llm')

MAX_ERROR_LEN = 4000


class _SafeDict(dict):
    def __missing__(self, key):  # unknown placeholders render empty instead of raising
        return ''


def render_template(template: str, variables: dict) -> str:
    try:
        return template.format_map(_SafeDict(variables))
    except (ValueError, IndexError, KeyError, AttributeError):
        return template  # a malformed template must not take the lecture down


def get_default_configuration() -> LLMConfiguration:
    base = LLMConfiguration.objects.select_related('provider').filter(is_active=True, provider__is_active=True)
    config = base.filter(is_default=True).first() or base.order_by('pk').first()
    if config is None:
        raise ServiceError('No active LLM configuration is defined.', code='no_llm_configuration')
    return config


def get_active_prompt(code: str) -> PromptTemplate:
    """Active template for ``code``; falls back to the built-in default (created on first use)."""
    template = PromptTemplate.objects.filter(code=code, is_active=True).order_by('-version').first()
    if template is not None:
        return template
    defaults = next((p for p in DEFAULT_PROMPTS if p['code'] == code), None)
    if defaults is None:
        raise ServiceError(f'No prompt template for code "{code}".', code='no_prompt_template')
    template, _ = PromptTemplate.objects.get_or_create(code=code, version=1, defaults={
        'name': defaults['name'], 'system_prompt': defaults['system_prompt'],
        'user_template': defaults['user_template'],
        'is_active': not PromptTemplate.objects.filter(code=code, is_active=True).exists(),
    })
    return template


def estimate_cost(configuration: LLMConfiguration, input_tokens: int | None,
                  output_tokens: int | None) -> Decimal | None:
    """USD cost from ``configuration.metadata['pricing']`` (per 1M tokens); None when unpriced."""
    pricing = configuration.metadata.get('pricing') if isinstance(configuration.metadata, dict) else None
    if not pricing or input_tokens is None or output_tokens is None:
        return None
    try:
        cost = (Decimal(str(pricing.get('input_per_1m', 0))) * input_tokens
                + Decimal(str(pricing.get('output_per_1m', 0))) * output_tokens) / Decimal(1_000_000)
    except Exception:
        return None
    return cost.quantize(Decimal('0.000001'))


def build_prompts(question: str, *, template: PromptTemplate,
                  variables: dict | None = None) -> tuple[str, str]:
    """Render the system/user prompts of ``template``."""
    values = {'question': question, **(variables or {})}
    system = render_template(template.system_prompt, values)
    user = render_template(template.user_template, values) if template.user_template else question
    return system, user


def _base_metadata(configuration: LLMConfiguration, extra: dict | None) -> dict:
    return {
        **(extra or {}),
        'provider': configuration.provider.code,
        'model': configuration.model_name,
        'params': {'temperature': configuration.temperature, 'max_tokens': configuration.max_tokens},
    }


def create_run(question: str, *, prompt_template: PromptTemplate, user=None,
               configuration: LLMConfiguration | None = None, variables: dict | None = None,
               metadata: dict | None = None) -> GenerationRun:
    configuration = configuration or get_default_configuration()
    system_prompt, user_prompt = build_prompts(question, template=prompt_template, variables=variables)
    return GenerationRun.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        configuration=configuration, prompt_template=prompt_template, question_text=question,
        system_prompt=system_prompt, user_prompt=user_prompt, status=GenerationStatus.PENDING,
        metadata={**_base_metadata(configuration, metadata),
                  'prompt': {'code': prompt_template.code, 'version': prompt_template.version}},
    )


def execute_run(run: GenerationRun, *, on_chunk: Callable[[str], None] | None = None) -> GenerationRun:
    """Call the provider for a prepared run and record latency, tokens, cost and outcome.

    Raises on provider failure *after* persisting it as FAILED.
    """
    configuration = run.configuration
    run.status = GenerationStatus.RUNNING
    run.save(update_fields=['status'])

    request = GenerationRequest(system_prompt=run.system_prompt, user_prompt=run.user_prompt,
                                max_tokens=run.metadata.get('max_tokens_override'))
    started = time.perf_counter()
    first_token_ms: int | None = None
    streaming = on_chunk is not None and configuration.supports_streaming
    try:
        provider = get_provider(configuration)
        if streaming:
            result: GenerationResult | None = None
            parts: list[str] = []
            for event in provider.stream(request):
                if event.delta:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    parts.append(event.delta)
                    on_chunk(event.delta)
                if event.final is not None:
                    result = event.final
            if result is None:
                text = ''.join(parts)
                result = GenerationResult(text=text, output_tokens=count_tokens(text), usage_estimated=True)
        else:
            result = provider.generate(request)
    except Exception as exc:
        logger.exception('Generation run %s failed', run.pk)
        run.status = GenerationStatus.FAILED
        run.error_message = f'{type(exc).__name__}: {exc}'[:MAX_ERROR_LEN]
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.save(update_fields=['status', 'error_message', 'latency_ms'])
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    input_tokens, output_tokens = result.input_tokens, result.output_tokens
    total = None if input_tokens is None and output_tokens is None else (input_tokens or 0) + (output_tokens or 0)
    # Decode speed excludes time-to-first-token when streaming; otherwise it spans the whole call.
    decode_ms = latency_ms - (first_token_ms or 0)
    tps = round(output_tokens / (decode_ms / 1000), 2) if output_tokens and decode_ms > 0 else None

    run.response_text = result.text
    run.input_tokens, run.output_tokens, run.total_tokens = input_tokens, output_tokens, total
    run.latency_ms = latency_ms
    run.first_token_latency_ms = first_token_ms
    run.tokens_per_second = tps
    run.estimated_cost = estimate_cost(configuration, input_tokens, output_tokens)
    run.status = GenerationStatus.SUCCESS
    run.error_message = ''
    run.metadata = {**run.metadata, 'streamed': streaming, 'finish_reason': result.finish_reason,
                    'response_model': result.model, 'usage_estimated': result.usage_estimated,
                    'tps_basis': 'decode' if streaming else 'total'}
    run.save()
    return run


def generate_answer(question: str, *, prompt_template: PromptTemplate, user=None,
                    configuration: LLMConfiguration | None = None, variables: dict | None = None,
                    metadata: dict | None = None, on_chunk: Callable[[str], None] | None = None) -> GenerationRun:
    """create_run + execute_run. ``on_chunk`` (called per text delta) enables streaming."""
    run = create_run(question, user=user, configuration=configuration, prompt_template=prompt_template,
                     variables=variables, metadata=metadata)
    return execute_run(run, on_chunk=on_chunk)
