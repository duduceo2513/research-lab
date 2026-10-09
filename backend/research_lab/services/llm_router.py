"""Resolves which ``llm.LLMConfiguration`` an agent should use, per ``ResearchRun.llm_mode``.

This sits on top of the existing ``llm`` app (providers/factory, ``generation.generate_answer``)
rather than building a second LLM abstraction — see ``research_lab/README.md`` -> "What's reused".
"""
from __future__ import annotations

import logging

from llm.models import LLMConfiguration, ProviderCode
from llm.services.generation import get_default_configuration
from research_lab.models import (AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER, AGENT_LECTURE_BUILDER,
                                 AGENT_SOURCE_VALIDATOR, LLMMode, ResearchRun)

logger = logging.getLogger('research_lab')

CLOUD_PROVIDER_CODES = (ProviderCode.OPENAI, ProviderCode.ANTHROPIC)

#: HYBRID policy: cheap/bulk scoring stays local; final content generation and review (quality-
#: sensitive, low-volume) use a cloud model.
HYBRID_CLOUD_AGENTS = (AGENT_LECTURE_BUILDER, AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER)
HYBRID_LOCAL_AGENTS = (AGENT_SOURCE_VALIDATOR,)


def _first_active(**filters) -> LLMConfiguration | None:
    return LLMConfiguration.objects.select_related('provider').filter(
        is_active=True, provider__is_active=True, **filters).order_by('-is_default', 'pk').first()


def fallback_configuration(failed: LLMConfiguration) -> LLMConfiguration | None:
    """The other tier's model, for when ``failed`` cannot be reached (Ollama switched off, an API key
    that is out of credit...): a local failure falls back to the cloud model and vice versa. ``None``
    when the other tier has nothing active."""
    if failed.provider.code == ProviderCode.LOCAL:
        return _first_active(provider__code__in=CLOUD_PROVIDER_CODES)
    return _first_active(provider__code=ProviderCode.LOCAL)


def resolve_configuration(run: ResearchRun, agent: str) -> LLMConfiguration:
    """Never raises: falls back through local -> cloud -> the platform default configuration, so an
    agent step always has *some* model to call (research_lab/README.md -> Fault tolerance)."""
    mode = run.llm_mode

    if mode == LLMMode.CUSTOM:
        override_id = (run.agent_model_overrides or {}).get(agent)
        if override_id:
            config = LLMConfiguration.objects.select_related('provider').filter(
                pk=override_id, is_active=True, provider__is_active=True).first()
            if config:
                return config
            logger.warning('Run %s: custom override for %s (config %s) is missing/inactive; falling back.',
                          run.pk, agent, override_id)

    elif mode == LLMMode.LOCAL:
        config = _first_active(provider__code=ProviderCode.LOCAL)
        if config:
            return config

    elif mode == LLMMode.CLOUD:
        config = _first_active(provider__code__in=CLOUD_PROVIDER_CODES)
        if config:
            return config

    elif mode == LLMMode.HYBRID:
        wants_cloud = agent in HYBRID_CLOUD_AGENTS
        config = _first_active(provider__code__in=CLOUD_PROVIDER_CODES if wants_cloud else [ProviderCode.LOCAL])
        if config:
            return config
        # The preferred tier for this agent has nothing active — try the other tier before giving up.
        other = _first_active(provider__code__in=[ProviderCode.LOCAL] if wants_cloud else CLOUD_PROVIDER_CODES)
        if other:
            return other

    return get_default_configuration()
