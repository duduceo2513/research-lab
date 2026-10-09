from __future__ import annotations

from django.conf import settings

from core.exceptions import ExternalServiceError
from llm.models import LLMProvider
from llm.providers.openai_provider import OpenAIProvider


class LocalProvider(OpenAIProvider):
    """A local model behind an OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp server, LM Studio).

    The endpoint comes from ``LLMProvider.base_url`` or ``LOCAL_LLM_BASE_URL``. An API key is optional.
    """

    token_param = 'max_tokens'
    supports_stream_usage = False  # not every local server accepts stream_options
    api_key_required = False

    def _base_url(self) -> str | None:
        return self.provider.base_url or settings.LOCAL_LLM_BASE_URL


def list_local_models(provider: LLMProvider | None = None) -> list[str]:
    """Live model names available on the local OpenAI-compatible server (e.g. ``ollama list``),
    queried via the same ``/models`` endpoint ``OpenAIProvider.health_check`` already uses — not a
    hardcoded list, since what's actually pulled varies per machine."""
    from openai import OpenAI

    base_url = (provider.base_url if provider else None) or settings.LOCAL_LLM_BASE_URL
    try:
        client = OpenAI(api_key='not-needed', base_url=base_url, timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS)
        response = client.models.list()
    except Exception as exc:
        raise ExternalServiceError(f'Could not reach the local model server: {type(exc).__name__}: {exc}') from exc
    return sorted({model.id for model in response.data})
