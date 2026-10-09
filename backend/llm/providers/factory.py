from __future__ import annotations

from core.exceptions import ServiceError
from llm.models import LLMConfiguration, ProviderCode
from llm.providers.anthropic_provider import AnthropicProvider
from llm.providers.base import BaseLLMProvider
from llm.providers.local_provider import LocalProvider
from llm.providers.openai_provider import OpenAIProvider

_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    ProviderCode.OPENAI: OpenAIProvider,
    ProviderCode.ANTHROPIC: AnthropicProvider,
    ProviderCode.LOCAL: LocalProvider,
}


def register_provider(code: str, cls: type[BaseLLMProvider]) -> None:
    """Plug in a custom provider class (also handy for tests)."""
    _REGISTRY[code] = cls


def get_provider(configuration: LLMConfiguration) -> BaseLLMProvider:
    provider = configuration.provider
    if not provider.is_active:
        raise ServiceError(f'Provider "{provider.display_name}" is disabled.', code='provider_disabled')
    try:
        cls = _REGISTRY[provider.code]
    except KeyError:
        raise ServiceError(f'Unsupported provider code "{provider.code}".', code='unknown_provider') from None
    return cls(configuration)
