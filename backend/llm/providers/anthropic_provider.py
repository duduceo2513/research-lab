from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from django.conf import settings

from core.exceptions import ExternalServiceError
from llm.providers.base import (BaseLLMProvider, GenerationRequest, GenerationResult, HealthStatus,
                                StreamEvent)

logger = logging.getLogger('llm')

# Newer Claude models reject temperature/top_p/top_k (HTTP 400), so they must be omitted.
_NO_SAMPLING_PREFIXES = ('claude-opus-5', 'claude-opus-4-8', 'claude-opus-4-7', 'claude-sonnet-5',
                         'claude-fable', 'claude-mythos')


def supports_sampling_params(model: str) -> bool:
    return not model.lower().startswith(_NO_SAMPLING_PREFIXES)


#: Above this many output tokens the Anthropic SDK demands streaming (it would estimate > 10 minutes).
NON_STREAMING_MAX_TOKENS = 21_000


class AnthropicProvider(BaseLLMProvider):
    """Claude via the official ``anthropic`` SDK (Messages API)."""

    def _client(self):
        import anthropic

        return anthropic.Anthropic(
            api_key=self.resolve_api_key(), base_url=self.provider.base_url or None,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )

    def _kwargs(self, request: GenerationRequest) -> dict:
        temperature, max_tokens = self.request_params(request)
        kwargs: dict = {
            'model': self.model,
            'max_tokens': max_tokens,
            'system': request.system_prompt,
            'messages': [{'role': 'user', 'content': request.user_prompt}],
        }
        if supports_sampling_params(self.model):
            kwargs['temperature'] = temperature
        effort = self.configuration.metadata.get('effort')
        if effort:
            kwargs['output_config'] = {'effort': effort}
        return kwargs

    def _wrap(self, exc: Exception) -> ExternalServiceError:
        logger.error('Anthropic request failed (%s): %s', type(exc).__name__, exc)
        return ExternalServiceError(f'{self.provider.display_name} request failed: {type(exc).__name__}')

    @staticmethod
    def _result(message) -> GenerationResult:
        text = ''.join(b.text for b in message.content if getattr(b, 'type', '') == 'text')
        if message.stop_reason == 'refusal':
            raise ExternalServiceError('The model declined to answer this request.', code='model_refusal')
        usage = message.usage
        return GenerationResult(
            text=text, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            finish_reason=message.stop_reason or '', model=message.model,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            kwargs = self._kwargs(request)
            if kwargs['max_tokens'] > NON_STREAMING_MAX_TOKENS:
                # The SDK refuses a plain request that could run over ~10 minutes; a streamed one has no such
                # limit, and we still return the finished message.
                with self._client().messages.stream(**kwargs) as stream:
                    message = stream.get_final_message()
            else:
                message = self._client().messages.create(**kwargs)
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
        return self._result(message)

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        try:
            with self._client().messages.stream(**self._kwargs(request)) as stream:
                for delta in stream.text_stream:
                    yield StreamEvent(delta=delta)
                message = stream.get_final_message()
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise self._wrap(exc) from exc
        yield StreamEvent(final=self._result(message))

    def health_check(self) -> HealthStatus:
        started = time.perf_counter()
        try:
            self._client().models.retrieve(self.model)
        except Exception as exc:
            return HealthStatus(ok=False, detail=f'{type(exc).__name__}: {exc}')
        return HealthStatus(ok=True, latency_ms=int((time.perf_counter() - started) * 1000))
