"""Agent 7 (spec section 7) — Source Validator. Independently scores every analyzed, non-duplicate
source; only ``ACCEPT``ed sources are handed to the Assignment Generator.

Sources are scored in small batches (``RESEARCH_LAB_VALIDATION_BATCH``, default 4) — one request judges
several sources, each independently — which keeps this agent's share of all LLM/tool calls well under the
40% ceiling of the project brief (one call per source made it the busiest agent). A source the model
skips, or a reply that cannot be parsed, falls back to a single-source request. There is no one
``GenerationRun`` for the step, so every call's metadata carries ``run_id``/``agent``, which is how the
metrics aggregate token/cost usage for this agent.
"""
from __future__ import annotations

import logging

from django.conf import settings

from llm.models import PromptCode
from research_lab.models import AGENT_SOURCE_VALIDATOR, ResearchRun, ResearchSource, ValidationDecision
from research_lab.schemas import ValidationResult
from research_lab.services import journal, llm_json, passages
from research_lab.services.llm_router import resolve_configuration

logger = logging.getLogger('research_lab')

_DECISION_MAP = {'accept': ValidationDecision.ACCEPT, 'reject': ValidationDecision.REJECT,
                 'review': ValidationDecision.REVIEW}
_SCORE_KEYS = ('relevance', 'authority', 'educational_value', 'academic_credibility', 'level_match',
              'recency', 'completeness', 'overall_score')


def _clamp(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _parse_validation(parsed: dict) -> ValidationResult:
    scores = {key: _clamp(parsed.get(key)) for key in _SCORE_KEYS}
    decision = _DECISION_MAP.get(str(parsed.get('decision', '')).strip().lower(), ValidationDecision.REVIEW)
    reasons = parsed.get('reasons')
    reasons = [str(r) for r in reasons] if isinstance(reasons, list) else []
    return ValidationResult(
        relevance=scores['relevance'], authority=scores['authority'],
        educational_value=scores['educational_value'], academic_credibility=scores['academic_credibility'],
        level_match=scores['level_match'], recency=scores['recency'], completeness=scores['completeness'],
        overall_score=scores['overall_score'], decision=decision, reasons=reasons,
    )


#: Writers need real material: with fewer approved sources than this, the best "needs review" ones join.
MIN_GROUNDING_SOURCES = 4
#: ...but only if the validator still thought them reasonably good (0-100 overall score).
PROVISIONAL_MIN_SCORE = 35.0


def with_provisional(research_run: ResearchRun, accepted: list[ResearchSource],
                     analyzed: list[ResearchSource]) -> list[ResearchSource]:
    """A strict validator (or a topic found mostly in beginner material) can leave a single approved
    source — too little for a lecture. Top up with the best-scored ``REVIEW`` sources; their stored
    decision stays ``REVIEW`` so the UI still shows they were not fully approved."""
    missing = MIN_GROUNDING_SOURCES - len(accepted)
    if missing <= 0:
        return accepted
    candidates = sorted(
        (s for s in analyzed if s.decision == ValidationDecision.REVIEW and (s.overall_score or 0) >= PROVISIONAL_MIN_SCORE),
        key=lambda s: s.overall_score or 0, reverse=True)[:missing]
    if candidates:
        logger.info('Run %s: %d approved source(s) is too few; adding %d provisional.', research_run.pk, len(accepted), len(candidates))
    return [*accepted, *candidates]


def _excerpt(research_run: ResearchRun, source: ResearchSource, limit: int) -> str:
    document = getattr(source, 'document', None)
    content = (document.text if document else '') or source.abstract
    # Long documents: the passages about the topic, not the first pages (title, contents, preface).
    return passages.select_context(content, f'{research_run.topic} {research_run.description}', limit)


def _single_call(research_run: ResearchRun, config, source: ResearchSource):
    parsed, _ = llm_json.call_structured(
        question=f'Validate source: {source.title}', prompt_code=PromptCode.RESEARCH_SOURCE_VALIDATION,
        configuration=config,
        variables={
            'topic': research_run.topic, 'education_level': research_run.education_level,
            'title': source.title, 'authors': ', '.join(source.authors),
            'published': str(source.published_at or ''), 'abstract': source.abstract[:1000],
            'content': _excerpt(research_run, source, settings.RESEARCH_LAB_VALIDATION_EXCERPT_CHARS),
        },
        metadata={'run_id': research_run.pk, 'source_id': source.pk, 'agent': AGENT_SOURCE_VALIDATOR},
    )
    return parsed if isinstance(parsed, dict) else None


def _batch_call(research_run: ResearchRun, config, chunk: list[ResearchSource]) -> dict[int, dict]:
    """One request scoring several sources at once. Returns ``{source.pk: scores}`` for every source the
    model answered; sources it skipped (or an unreadable reply) are simply absent, and the caller scores
    those one by one, so a bad batch costs extra calls but never a wrong or missing verdict."""
    per_source = max(settings.RESEARCH_LAB_VALIDATION_EXCERPT_CHARS // 2, 1200)
    blocks = []
    for position, source in enumerate(chunk, start=1):
        blocks.append(
            f'### Source id={source.pk}\nTitle: {source.title}\nAuthors: {", ".join(source.authors[:4])}\n'
            f'Published: {source.published_at or ""}\nAbstract: {source.abstract[:600]}\n'
            f'Content excerpt:\n{_excerpt(research_run, source, per_source)}')
    parsed, _ = llm_json.call_structured(
        question=f'Validate {len(chunk)} sources', prompt_code=PromptCode.RESEARCH_SOURCE_VALIDATION_BATCH,
        configuration=config,
        variables={'topic': research_run.topic, 'education_level': research_run.education_level,
                   'sources': '\n\n'.join(blocks)},
        metadata={'run_id': research_run.pk, 'source_ids': [s.pk for s in chunk], 'agent': AGENT_SOURCE_VALIDATOR},
    )
    items = parsed.get('results') if isinstance(parsed, dict) else parsed
    answered: dict[int, dict] = {}
    by_position = {i: s.pk for i, s in enumerate(chunk, start=1)}
    valid = {s.pk for s in chunk}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            ident = int(str(item.get('source_id')).strip().strip('[]'))
        except ValueError:
            continue
        pk = ident if ident in valid else by_position.get(ident)
        if pk is not None and pk not in answered:
            answered[pk] = item
    return answered


def run(research_run: ResearchRun, sequence: int, sources: list[ResearchSource]) -> tuple[int, list[ResearchSource]]:
    from django.utils import timezone

    config = resolve_configuration(research_run, AGENT_SOURCE_VALIDATOR)
    tally = {'accept': 0, 'reject': 0, 'review': 0, 'unparsable': 0}
    batch_size = max(1, settings.RESEARCH_LAB_VALIDATION_BATCH)
    llm_calls = 0

    with journal.agent_step(research_run, AGENT_SOURCE_VALIDATOR, sequence,
                            input_summary={'source_count': len(sources), 'model': config.name,
                                           'batch_size': batch_size}) as execution:
        journal.note(execution, f'Scoring {len(sources)} sources, {batch_size} per request, with {config.name}: '
                                f'relevance, authority, educational value, credibility, level match, recency, '
                                f'completeness.', 'thought')

        def report(reviewed: int, current: str = '') -> None:
            journal.progress(execution, [
                {'id': 'review', 'label': 'Score sources', 'status': 'active' if reviewed < len(sources) else 'done',
                 'detail': f'{reviewed} / {len(sources)}'},
                {'id': 'decide', 'label': 'Accept / reject', 'status': 'done' if reviewed >= len(sources) else 'pending',
                 'detail': f"{tally['accept']} accepted, {tally['reject']} rejected"},
            ], input_sources=len(sources), reviewed=reviewed, current_source=current, accepted=tally['accept'],
                rejected=tally['reject'], needs_review=tally['review'] + tally['unparsable'])

        def apply(index: int, source: ResearchSource, parsed: dict | None) -> None:
            label = f'[{index}/{len(sources)}] {source.title[:80]}'
            if parsed is None:
                source.decision = ValidationDecision.REVIEW
                source.decision_reasons = ['The validator model returned an unparsable response.']
                tally['unparsable'] += 1
                journal.note(execution, f'{label}: the model gave an unreadable answer, flagged for human review.', 'warn')
                journal.decide(execution, 'review', 'Unreadable validator answer, flagged for human review.',
                               reason='The validator model did not return valid JSON.',
                               next_action='Left out of the lecture and assignment.',
                               source_id=source.pk, source_title=source.title[:120])
            else:
                result = _parse_validation(parsed)
                source.relevance_score = result.relevance
                source.authority_score = result.authority
                source.educational_value_score = result.educational_value
                source.academic_credibility_score = result.academic_credibility
                source.level_match_score = result.level_match
                source.recency_score = result.recency
                source.completeness_score = result.completeness
                source.overall_score = result.overall_score
                source.decision = result.decision
                source.decision_reasons = result.reasons
                tally[result.decision.lower()] = tally.get(result.decision.lower(), 0) + 1
                journal.note(execution, f'{label}: {result.decision} ({result.overall_score:.0f}/100; '
                                        f'relevance {result.relevance:.0f}, authority {result.authority:.0f}, '
                                        f'level {result.level_match:.0f}). ' + ' '.join(result.reasons[:3]), 'thought')
                journal.decide(execution, result.decision.lower(),
                               f'{result.decision} SOURCE: {source.title[:100]}',
                               reason=' '.join(result.reasons[:3]) or f'Overall score {result.overall_score:.0f}/100.',
                               next_action=('Used for the lecture and assignment.' if result.decision == ValidationDecision.ACCEPT
                                            else 'Not used.'),
                               source_id=source.pk, source_title=source.title[:120], score=result.overall_score)
            source.validated_at = timezone.now()
            source.save()
            report(index)

        report(0)
        for offset in range(0, len(sources), batch_size):
            chunk = sources[offset:offset + batch_size]
            journal.note(execution, f'Judging sources {offset + 1}-{offset + len(chunk)} of {len(sources)}…')
            report(offset, chunk[0].title[:140])
            answered = _batch_call(research_run, config, chunk) if len(chunk) > 1 else {}
            llm_calls += 1 if len(chunk) > 1 else 0
            for index, source in enumerate(chunk, start=offset + 1):
                parsed = answered.get(source.pk)
                if parsed is None:  # skipped by the batch (or a lone source): score it on its own
                    parsed = _single_call(research_run, config, source)
                    llm_calls += 1
                apply(index, source, parsed)

        journal.note(execution, f"Verdict: {tally['accept']} accepted, {tally['reject']} rejected, "
                                f"{tally['review'] + tally['unparsable']} need review.", 'result')
        execution.output_summary = {'validated': len(sources), 'llm_calls': llm_calls, **tally}
        journal.decide(execution, 'handoff', f"{tally['accept']} approved sources.",
                       reason=f"{tally['reject']} rejected, {tally['review'] + tally['unparsable']} need human review.",
                       next_action='Hand the approved sources to the content-building agents.',
                       accepted=tally['accept'], rejected=tally['reject'])

    accepted = [s for s in sources if s.decision == ValidationDecision.ACCEPT]
    return sequence + 1, accepted
