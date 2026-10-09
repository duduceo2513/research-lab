"""Per-run report: who did how much, built only from the persisted journals.

The project brief requires that no agent performs more than 40% of all LLM and tool calls in a
typical scenario, "confirmed by logs". This module is that confirmation: it counts, per agent, the LLM
calls (``llm.GenerationRun`` rows tagged with the run and agent) and the tool calls
(``ToolExecution`` rows), and states the share of the total. The same numbers feed the "Agent load"
panel, the run report endpoint (JSON / Markdown) and the ``research_report`` command.

Load = (LLM calls + tool calls of the agent) / (all LLM calls + all tool calls of the run).
The Boss makes neither kind of call (it only plans and routes), so its share is 0 by construction.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum

from llm.models import GenerationRun
from research_lab.models import AgentName, ResearchRun, ToolExecution
from research_lab.services import events

LOAD_LIMIT_PCT = 40.0
#: Brief: at most this many tools per agent. Reported (with the actual tool names) rather than enforced.
TOOLS_PER_AGENT_LIMIT = 5

#: Agent order for tables (the pipeline order).
ORDER = [name for name, _ in AgentName.choices]


def agent_calls(run: ResearchRun) -> dict[str, dict]:
    """``{AGENT_NAME: {'llm': n, 'tools': n, 'tool_names': set, 'tokens': n, 'cost': float}}``."""
    stats: dict[str, dict] = defaultdict(lambda: {'llm': 0, 'tools': 0, 'tool_names': set(), 'tokens': 0, 'cost': 0.0,
                                                  'local_calls': 0, 'cloud_calls': 0, 'failed_tools': 0})
    for row in (GenerationRun.objects.filter(metadata__run_id=run.pk)
                .values('metadata__agent', 'configuration__provider__code')
                .annotate(calls=Count('id'), tokens=Sum('total_tokens'), cost=Sum('estimated_cost'))):
        entry = stats[row['metadata__agent'] or '']
        entry['llm'] += row['calls']
        entry['tokens'] += row['tokens'] or 0
        entry['cost'] += float(row['cost'] or Decimal(0))
        entry['local_calls' if row['configuration__provider__code'] == 'LOCAL' else 'cloud_calls'] += row['calls']
    for tool in ToolExecution.objects.filter(run=run, agent_execution__isnull=False).select_related('agent_execution'):
        # A skipped tool (disabled / no key) never ran: it is logged, but it is not a call.
        if tool.status == 'SKIPPED':
            continue
        entry = stats[tool.agent_execution.agent]
        entry['tools'] += 1
        entry['tool_names'].add(tool.tool)
        entry['failed_tools'] += tool.status == 'FAILED'
    return dict(stats)


def load_shares(run: ResearchRun) -> tuple[list[dict], int]:
    """Every agent with its call counts and share (percent) of the run's total calls."""
    stats = agent_calls(run)
    total = sum(s['llm'] + s['tools'] for s in stats.values())
    rows = []
    for name in ORDER:
        s = stats.get(name, {'llm': 0, 'tools': 0})
        calls = s['llm'] + s['tools']
        rows.append({'agent': events.agent_key(name), 'llm_calls': s['llm'], 'tool_calls': s['tools'],
                     'calls': calls, 'pct': round(calls / total * 100, 1) if total else 0.0})
    return rows, total


def build_report(run: ResearchRun) -> dict:
    stats = agent_calls(run)
    shares, total = load_shares(run)
    executions = defaultdict(lambda: {'runs': 0, 'ms': 0})
    for execution in run.agent_executions.all():
        executions[execution.agent]['runs'] += 1
        executions[execution.agent]['ms'] += execution.latency_ms or 0
    agents = []
    for name, share in zip(ORDER, shares):
        s = stats.get(name, {})
        tool_names = sorted(s.get('tool_names', set()))
        agents.append({
            **share, 'name': AgentName(name).label, 'runs': executions[name]['runs'],
            'duration_ms': executions[name]['ms'], 'tools': tool_names,
            'tokens': s.get('tokens', 0), 'cost': round(s.get('cost', 0.0), 6),
            'failed_tool_calls': s.get('failed_tools', 0),
            'within_load_limit': share['pct'] <= LOAD_LIMIT_PCT,
        })
    max_pct = max((a['pct'] for a in agents), default=0.0)
    busiest = max(agents, key=lambda a: a['pct'], default=None)
    all_tools = ToolExecution.objects.filter(run=run)
    steps = list(run.agent_executions.values_list('started_at', 'finished_at'))
    started = run.started_at or (min(s for s, _ in steps) if steps else None)  # runs recorded before started_at was saved
    finished = run.finished_at or (max((f for _, f in steps if f), default=None))
    return {
        'run': {'id': run.pk, 'topic': run.topic, 'mode': run.mode, 'status': run.status, 'llm_mode': run.llm_mode,
                'education_level': run.education_level,
                'started_at': started.isoformat() if started else None,
                'finished_at': finished.isoformat() if finished else None,
                'duration_seconds': (finished - started).total_seconds() if started and finished else None},
        'definition': 'load = (LLM calls + tool calls of an agent) / (all LLM calls + all tool calls of the run)',
        'agents': agents,
        'totals': {
            'llm_calls': sum(a['llm_calls'] for a in agents), 'tool_calls': sum(a['tool_calls'] for a in agents),
            'calls': total, 'tokens': sum(a['tokens'] for a in agents),
            'cost': round(sum(a['cost'] for a in agents), 6),
            'failed_tool_calls': all_tools.filter(status='FAILED').count(),
            'skipped_tool_calls': all_tools.filter(status='SKIPPED').count(),
            'events': run.events.count(),
        },
        'load': {'limit_pct': LOAD_LIMIT_PCT, 'max_pct': max_pct, 'busiest_agent': busiest['name'] if busiest else None,
                 'passed': max_pct <= LOAD_LIMIT_PCT},
        'tool_limit': {'limit': TOOLS_PER_AGENT_LIMIT,
                       'over': [a['name'] for a in agents if len(a['tools']) > TOOLS_PER_AGENT_LIMIT]},
        'deliverables': {
            'sources': run.sources.count(), 'accepted_sources': run.sources.filter(decision='ACCEPT').count(),
            'lecture': (lambda l: {'version': l.version, 'status': l.status, 'score': l.review_score} if l else None)(
                run.lectures.order_by('-version').first()),
            'assignment': (lambda a: {'status': a.review_status, 'score': a.review_score} if a else None)(
                getattr(run, 'assignment', None)),
        },
    }


def render_markdown(report: dict) -> str:
    run, totals, load = report['run'], report['totals'], report['load']
    lines = [
        f"# Run report — {run['topic']} (run {run['id']})", '',
        f"Status: **{run['status']}** · mode {run['mode']} · AI mode {run['llm_mode']} · level {run['education_level']}",
        f"Duration: {run['duration_seconds']:.0f} s" if run['duration_seconds'] is not None else 'Duration: n/a', '',
        f"Totals: {totals['llm_calls']} LLM calls, {totals['tool_calls']} tool calls ({totals['calls']} in all), "
        f"{totals['tokens']:,} tokens, ${totals['cost']:.4f}; {totals['failed_tool_calls']} failed and "
        f"{totals['skipped_tool_calls']} skipped tool calls; {totals['events']} logged events.", '',
        f"## Load distribution — {report['definition']}", '',
        '| Agent | LLM calls | Tool calls | Total | Share | Limit 40% | Tools |', '|---|---:|---:|---:|---:|:---:|---|',
    ]
    for a in report['agents']:
        lines.append(f"| {a['name']} | {a['llm_calls']} | {a['tool_calls']} | {a['calls']} | {a['pct']:.1f}% | "
                     f"{'ok' if a['within_load_limit'] else 'OVER'} | {', '.join(a['tools']) or '—'} |")
    lines += ['', f"Busiest agent: **{load['busiest_agent']}** at {load['max_pct']:.1f}% — "
                  f"{'within' if load['passed'] else 'OVER'} the {load['limit_pct']:.0f}% limit.", '']
    deliverables = report['deliverables']
    lines.append(f"Sources: {deliverables['sources']} found, {deliverables['accepted_sources']} approved. "
                 f"Lecture: {deliverables['lecture'] or 'not requested'}. Assignment: {deliverables['assignment'] or 'not requested'}.")
    if report['tool_limit']['over']:
        lines += ['', f"Note: more than {report['tool_limit']['limit']} distinct tools in this run for: "
                      + ', '.join(report['tool_limit']['over']) + '.']
    return '\n'.join(lines) + '\n'
