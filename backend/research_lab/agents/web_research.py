"""Agent 2 — Web Research. Searches the open web via Bright Data SERP, with a small, deterministic
set of query variants per topic (see ``build_queries``) — not an LLM call: the variants are cheap,
predictable templates, so spending a model call to invent them would add latency and cost for no
real benefit.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

from research_lab.exceptions import ProviderError
from research_lab.models import AGENT_WEB_RESEARCH, ResearchRun
from research_lab.providers.search.registry import WEB_PROVIDERS
from research_lab.schemas import SourceCandidate
from research_lab.services import journal, provider_gate
from research_lab.services.resilience import retry_with_backoff

logger = logging.getLogger('research_lab')

# Ordered by how often each finds real documents (PDF notes, slides, university pages): with the default
# of four queries per run, the most productive ones always run first.
QUERY_TEMPLATES = [
    '{topic} lecture notes filetype:pdf',
    '{topic} slides filetype:pptx',
    '{topic} tutorial university',
    '{topic} site:edu',
    '{topic} university course',
    '{topic} course material',
    '{topic} lecture slides pdf',
    '{topic} lecture notes',
]


def build_queries(topic: str) -> list[str]:
    return [t.format(topic=topic) for t in QUERY_TEMPLATES][:settings.RESEARCH_LAB_MAX_SEARCH_QUERIES]


def run(research_run: ResearchRun, sequence: int) -> tuple[int, list[SourceCandidate]]:
    candidates: list[SourceCandidate] = []
    with journal.agent_step(research_run, AGENT_WEB_RESEARCH, sequence,
                            input_summary={'topic': research_run.topic}) as execution:
        queries = build_queries(research_run.topic)
        per_provider: dict[str, int] = {}
        journal.note(execution, f'Prepared {len(queries)} search queries: ' + '; '.join(queries), 'thought')
        steps = [{'id': p.code, 'label': p.code, 'status': 'pending'} for p in WEB_PROVIDERS]

        def mark(code: str, status: str, detail: str = '') -> None:
            for step in steps:
                if step['id'] == code:
                    step.update(status=status, detail=detail)
            journal.progress(execution, steps)

        journal.progress(execution, steps)

        for provider in WEB_PROVIDERS:
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
            found = 0
            mark(provider.code, 'active')
            # Web search benefits from several narrower queries; the other sources get just the topic.
            for query in (queries if provider.multi_query else [research_run.topic]):
                started = time.perf_counter()
                journal.note(execution, f'Searching {provider.code}: "{query}"')
                journal.tool_start(execution, provider.code, 'search', query=query)
                try:
                    results = retry_with_backoff(
                        lambda q=query: provider.search(q, limit=settings.RESEARCH_LAB_MAX_RESULTS_PER_QUERY),
                        attempts=2, exceptions=(ProviderError,))
                except ProviderError as exc:
                    provider_gate.record_health(provider.code, False, str(exc))
                    journal.note(execution, f'{provider.code} failed: {exc}', 'warn')
                    journal.log_tool(research_run, execution, provider.code, status='FAILED', operation='search',
                                     request_summary={'query': query}, error_message=str(exc),
                                     latency_ms=int((time.perf_counter() - started) * 1000))
                    continue
                provider_gate.record_health(provider.code, True)
                journal.log_tool(research_run, execution, provider.code, status='SUCCESS', operation='search',
                                 request_summary={'query': query}, response_summary={'count': len(results), 'results': [journal.candidate_summary(c) for c in results]},
                                 latency_ms=int((time.perf_counter() - started) * 1000))
                journal.note(execution, f'Found {len(results)} results.', 'result')
                candidates.extend(results)
                found += len(results)
            per_provider[provider.code] = found
            mark(provider.code, 'done', f'{found} results')

        execution.output_summary = {'queries': queries, 'results_by_provider': per_provider,
                                    'total_found': len(candidates)}
        journal.decide(execution, 'handoff', f'{len(candidates)} web results collected.',
                       reason='Searched every enabled web provider with the prepared query variants.',
                       next_action='Pass the candidates to Document Analysis.', total_found=len(candidates))
    return sequence + 1, candidates
