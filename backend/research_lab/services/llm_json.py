"""Calls an agent's LLM step through the existing ``llm`` app and defensively parses its JSON reply.

A model can always return malformed JSON (markdown fences, trailing commentary, a refusal); that must
degrade this one agent step, never crash the run.
"""
from __future__ import annotations

import json
import logging
import re

from core.exceptions import ExternalServiceError
from llm.models import GenerationRun, LLMConfiguration
from llm.services import generation
from research_lab.services import events
from research_lab.services.llm_router import fallback_configuration
from research_lab.services.resilience import retry_with_backoff

logger = logging.getLogger('research_lab')

#: Strips ```json ... ``` / ``` ... ``` fences some models wrap structured output in.
_FENCE = re.compile(r'^```(?:json)?\s*|\s*```$', re.MULTILINE)
RETRY_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 32_000


def _parse(text: str):
    """Parsed JSON from a model reply (fences stripped, a slightly unbalanced reply repaired), or ``None``."""
    cleaned = _FENCE.sub('', text).strip()
    for candidate in (cleaned, None):
        try:
            return json.loads(candidate if candidate is not None else _close_unbalanced_brackets(cleaned))
        except (ValueError, TypeError):
            continue
    return None


def _close_unbalanced_brackets(text: str) -> str:
    """A local model occasionally stops generating (``finish_reason: stop``) one bracket short of
    well-formed JSON. Two shapes seen in practice (both from the same Source Validator prompt):

    * missing trailing bracket(s) entirely — ``{"a": 1, "b": ["x"`` -> ``{"a": 1, "b": ["x"]}``;
    * a closer for the wrong level — the model forgets to close an array before closing the
      object around it: ``{"reasons": ["x", "y"}`` (note the ``}`` where a ``]`` was due) ->
      ``{"reasons": ["x", "y"]}``, by closing whatever's still open *before* honouring that
      mismatched closer, on the assumption the model always intended a properly nested result.

    Walks the text tracking open brackets outside of strings; a no-op on already-balanced text."""
    stack: list[str] = []
    in_string = False
    escape = False
    out: list[str] = []
    for char in text:
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            out.append(char)
        elif char in '{[':
            stack.append('}' if char == '{' else ']')
            out.append(char)
        elif char in '}]':
            while stack and stack[-1] != char:
                out.append(stack.pop())
            if stack and stack[-1] == char:
                stack.pop()
                out.append(char)
            # else: a stray closer with nothing left open (the model's own ordering mistake) —
            # drop it rather than emit an unmatched closer that would corrupt the result.
        else:
            out.append(char)
    if in_string:
        out.append('"')  # close a dangling string first so the bracket stack below still applies
    out.append(''.join(reversed(stack)))
    return ''.join(out)


def call_structured(*, question: str, prompt_code: str, configuration: LLMConfiguration,
                    variables: dict, metadata: dict) -> tuple[dict | list | None, GenerationRun]:
    """Runs the prompt (retrying once on a transient provider failure) and returns
    ``(parsed_json_or_None, generation_run)``. Raises only if every attempt's *call* failed — a
    parse failure never raises, callers check for ``None`` and fall back instead (see each agent's
    docstring)."""
    template = generation.get_active_prompt(prompt_code)

    def generate(config: LLMConfiguration):
        return retry_with_backoff(
            lambda: generation.generate_answer(question, configuration=config, prompt_template=template,
                                               variables=variables, metadata=metadata),
            attempts=RETRY_ATTEMPTS, base_delay=2.0, exceptions=(ExternalServiceError,))

    from django.conf import settings

    budget = max(configuration.max_tokens or 0, settings.RESEARCH_LAB_MIN_OUTPUT_TOKENS)
    metadata = {**metadata, 'max_tokens_override': budget}
    try:
        run = generate(configuration)
    except ExternalServiceError as exc:
        # The chosen model is unreachable (local server off, cloud key invalid...). Every agent keeps
        # working by switching to the other tier instead of failing the step.
        alternative = fallback_configuration(configuration)
        if alternative is None:
            raise
        logger.warning('%s unreachable (%s); falling back to %s', configuration.name, exc, alternative.name)
        if metadata.get('run_id') and metadata.get('agent'):
            events.emit(metadata['run_id'], events.AGENT_NOTE, metadata['agent'], kind='warn',
                        summary=f'{configuration.name} is unavailable, switched to {alternative.name}.')
        run = generate(alternative)
    parsed = _parse(run.response_text)
    if run.metadata.get('finish_reason') in ('max_tokens', 'length') and budget < MAX_OUTPUT_TOKENS:
        # The model ran out of room mid-document. Even if the stump happens to parse after bracket repair
        # its values are unreliable (a score cut to "9"), so ask again with twice the room.
        logger.warning('Output cut off at %s tokens for %s; retrying with %s.', budget, prompt_code, budget * 2)
        metadata = {**metadata, 'max_tokens_override': min(budget * 2, MAX_OUTPUT_TOKENS)}
        run = generate(run.configuration)
        parsed = _parse(run.response_text)
    if parsed is not None:
        return parsed, run
    cleaned = _FENCE.sub('', run.response_text).strip()
    try:
        return json.loads(_close_unbalanced_brackets(cleaned)), run
    except (ValueError, TypeError) as exc:
        logger.warning('Run metadata %s: could not parse LLM JSON for %s: %s', metadata, prompt_code, exc)
        return None, run
