"""Provider-neutral LLM interface: every backend implements generate / stream / health_check."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

from core.exceptions import ExternalServiceError
from llm.models import LLMConfiguration, LLMProvider

DEFAULT_SECRET_ENV = {'OPENAI': 'OPENAI_API_KEY', 'ANTHROPIC': 'ANTHROPIC_API_KEY'}


@dataclass
class GenerationRequest:
    system_prompt: str
    user_prompt: str
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class GenerationResult:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str = ''
    model: str = ''
    #: True when token counts were estimated because the backend did not report usage.
    usage_estimated: bool = False


@dataclass
class StreamEvent:
    """Either a text delta or (last event) the final ``GenerationResult``."""

    delta: str = ''
    final: GenerationResult | None = None


@dataclass
class HealthStatus:
    ok: bool
    detail: str = ''
    latency_ms: int | None = None
    extra: dict = field(default_factory=dict)


class BaseLLMProvider(ABC):
    def __init__(self, configuration: LLMConfiguration) -> None:
        self.configuration = configuration
        self.provider: LLMProvider = configuration.provider

    # -- helpers -----------------------------------------------------------------------------
    @property
    def model(self) -> str:
        return self.configuration.model_name

    def resolve_api_key(self, *, required: bool = True) -> str:
        """Read the key from the environment variable named on the provider. Never from the DB."""
        env_name = self.provider.secret_env_name or DEFAULT_SECRET_ENV.get(self.provider.code, '')
        key = os.environ.get(env_name, '') if env_name else ''
        if not key and required:
            raise ExternalServiceError(
                f'Environment variable {env_name or "(secret_env_name not set)"} is not set '
                f'for provider "{self.provider.display_name}".', code='missing_api_key')
        return key

    def request_params(self, request: GenerationRequest) -> tuple[float, int]:
        temperature = self.configuration.temperature if request.temperature is None else request.temperature
        max_tokens = request.max_tokens or self.configuration.max_tokens
        return temperature, max_tokens

    # -- interface ---------------------------------------------------------------------------
    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abstractmethod
    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]: ...

    @abstractmethod
    def health_check(self) -> HealthStatus: ...
