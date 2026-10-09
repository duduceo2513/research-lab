from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from django.conf import settings

from core.exceptions import ExternalServiceError
from llm.providers.base import (BaseLLMProvider, GenerationRequest, GenerationResult, HealthStatus,
                                StreamEvent)
from llm.tokens import count_tokens

logger = logging.getLogger('llm')

# Reasoning models reject a custom temperature.
_NO_TEMPERATURE_PREFIXES = ('o1', 'o3', 'o4', 'gpt-5')


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Chat Completions. Also the base for any OpenAI-compatible server."""

    #: Real OpenAI wants ``max_completion_tokens``; most compatible servers only know ``max_tokens``.
    token_param = 'max_completion_tokens'
    supports_stream_usage = True
    api_key_required = True

    def _base_url(self) -> str | None:
        return self.provider.base_url or None

    def _client(self):
        from openai import OpenAI

        key = self.resolve_api_key(required=self.api_key_required)
        return OpenAI(api_key=key or 'not-needed', base_url=self._base_url(),
                      timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS)

    def _kwargs(self, request: GenerationRequest) -> dict:
        temperature, max_tokens = self.request_params(request)
        kwargs = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': request.system_prompt},
                {'role': 'user', 'content': request.user_prompt},
            ],
            self.token_param: max_tokens,
        }
        if not self.model.lower().startswith(_NO_TEMPERATURE_PREFIXES):
            kwargs['temperature'] = temperature
        effort = self.configuration.metadata.get('reasoning_effort')
        if effort:
            kwargs['reasoning_effort'] = effort
        return kwargs

    def _wrap(self, exc: Exception) -> ExternalServiceError:
        logger.error('%s request failed (%s): %s', self.provider.code, type(exc).__name__, exc)
        return ExternalServiceError(f'{self.provider.display_name} request failed: {type(exc).__name__}')

    def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            response = self._client().chat.completions.create(**self._kwargs(request))
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
        choice = response.choices[0]
        text = choice.message.content or ''
        usage = getattr(response, 'usage', None)
        estimated = usage is None
        return GenerationResult(
            text=text,
            input_tokens=usage.prompt_tokens if usage else count_tokens(request.system_prompt + request.user_prompt),
            output_tokens=usage.completion_tokens if usage else count_tokens(text),
            finish_reason=choice.finish_reason or '',
            model=getattr(response, 'model', self.model),
            usage_estimated=estimated,
        )

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        kwargs = self._kwargs(request)
        kwargs['stream'] = True
        if self.supports_stream_usage:
            kwargs['stream_options'] = {'include_usage': True}
        parts: list[str] = []
        usage = None
        finish = ''
        try:
            for chunk in self._client().chat.completions.create(**kwargs):
                if getattr(chunk, 'usage', None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.delta and choice.delta.content:
                    parts.append(choice.delta.content)
                    yield StreamEvent(delta=choice.delta.content)
                if choice.finish_reason:
                    finish = choice.finish_reason
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
        text = ''.join(parts)
        yield StreamEvent(final=GenerationResult(
            text=text,
            input_tokens=usage.prompt_tokens if usage else count_tokens(request.system_prompt + request.user_prompt),
            output_tokens=usage.completion_tokens if usage else count_tokens(text),
            finish_reason=finish, model=self.model, usage_estimated=usage is None,
        ))

    def health_check(self) -> HealthStatus:
        started = time.perf_counter()
        try:
            self._client().models.list()
        except Exception as exc:
            return HealthStatus(ok=False, detail=f'{type(exc).__name__}: {exc}')
        return HealthStatus(ok=True, latency_ms=int((time.perf_counter() - started) * 1000))
