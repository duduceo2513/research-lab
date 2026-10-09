"""Agent 3 — Academic Research. Queries OpenAlex, Semantic Scholar, Crossref, arXiv and Google
Books in parallel-by-intent (executed sequentially within one run for simplicity and
predictable error handling). Any
provider that errors or has no results is logged and skipped; the others still run.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

from research_lab.exceptions import ProviderError
from research_lab.models import AGENT_ACADEMIC_RESEARCH, ResearchRun
from research_lab.providers.search.registry import ACADEMIC_PROVIDERS
from research_lab.schemas import SourceCandidate
from research_lab.services import journal, provider_gate
from research_lab.services.resilience import retry_with_backoff

logger = logging.getLogger('research_lab')


def run(research_run: ResearchRun, sequence: int) -> tuple[int, list[SourceCandidate]]:
    candidates: list[SourceCandidate] = []
    query = f'{research_run.topic} {research_run.description}'.strip()
    with journal.agent_step(research_run, AGENT_ACADEMIC_RESEARCH, sequence,
                            input_summary={'query': query}) as execution:
        per_provider: dict[str, int] = {}
        journal.note(execution, f'Searching scholarly databases for: "{query}"', 'thought')
        steps = [{'id': p.code, 'label': p.code, 'status': 'pending'} for p in ACADEMIC_PROVIDERS]

        def mark(code: str, status: str, detail: str = '') -> None:
            for step in steps:
                if step['id'] == code:
                    step.update(status=status, detail=detail)
            journal.progress(execution, steps, sources_found=len(candidates))

        journal.progress(execution, steps, sources_found=0)
        for provider in ACADEMIC_PROVIDERS:
            usable, why = provider_gate.allowed(research_run, provider)
            if not usable:
                journal.note(execution, f'{provider.code}: {why}, skipped.', 'warn')
                journal.log_tool(research_run, execution, provider.code, status='SKIPPED',
                                 response_summary={'reason': why})
                mark(provider.code, 'skipped', why)
                continue
            if not provider.configured():
                missing = ', '.join(provider.missing_settings()) or 'credentials'
                journal.note(execution, f'{provider.code}: API key missing ({missing}), skipped.', 'warn')
                journal.log_tool(research_run, execution, provider.code, status='SKIPPED',
                                 response_summary={'reason': f'API key missing: {missing}'})
                mark(provider.code, 'skipped', 'API key missing')
                continue
            started = time.perf_counter()
            journal.note(execution, f'Querying {provider.code}…')
            mark(provider.code, 'active')
            journal.tool_start(execution, provider.code, 'search', query=query)
            try:
                results = retry_with_backoff(
                    lambda p=provider: p.search(query, limit=settings.RESEARCH_LAB_MAX_RESULTS_PER_QUERY),
                    attempts=2, exceptions=(ProviderError,))
            except ProviderError as exc:
                provider_gate.record_health(provider.code, False, str(exc))
                journal.note(execution, f'{provider.code} failed: {exc}', 'warn')
                journal.log_tool(research_run, execution, provider.code, status='FAILED', operation='search',
                                 request_summary={'query': query}, error_message=str(exc),
                                 latency_ms=int((time.perf_counter() - started) * 1000))
                per_provider[provider.code] = 0
                mark(provider.code, 'failed', str(exc)[:120])
                continue
            provider_gate.record_health(provider.code, True)
            journal.log_tool(research_run, execution, provider.code, status='SUCCESS', operation='search',
                             request_summary={'query': query}, response_summary={'count': len(results), 'results': [journal.candidate_summary(c) for c in results]},
                             latency_ms=int((time.perf_counter() - started) * 1000))
            journal.note(execution, f'{provider.code}: {len(results)} results'
                         + (f' (e.g. "{results[0].title[:90]}")' if results else '.'), 'result')
            candidates.extend(results)
            per_provider[provider.code] = len(results)
            mark(provider.code, 'done', f'{len(results)} results')

        execution.output_summary = {'query': query, 'results_by_provider': per_provider,
                                    'total_found': len(candidates)}
        journal.decide(execution, 'handoff', f'{len(candidates)} academic results collected.',
                       reason='Queried every enabled scholarly database; failed providers were skipped.',
                       next_action='Pass the candidates to Document Analysis.', total_found=len(candidates))
    return sequence + 1, candidates
