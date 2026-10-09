"""Read model for the Agent Workspace: everything the page shows, computed on the server from the
persisted journal (``AgentExecution``, ``ToolExecution``, ``ResearchEvent``, ``llm.GenerationRun``)
so the frontend never invents a status, a count or a percentage — it only renders this.

The live WebSocket stream tells the page *that something happened*; this snapshot tells it *what the
state is now* (and is what a page reload restores).
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from llm.models import GenerationRun
from research_lab.models import (AGENT_ACADEMIC_RESEARCH, AGENT_ASSIGNMENT_GENERATOR, AGENT_BOSS,
                                 AGENT_DOCUMENT_ANALYSIS, AGENT_DOCUMENT_RETRIEVAL, AGENT_FINAL_REVIEWER, AGENT_LECTURE_BUILDER,
                                 AGENT_SOURCE_VALIDATOR, AGENT_WEB_RESEARCH, TERMINAL_RUN_STATUSES, AgentName,
                                 MaterialType, ResearchEvent, ResearchRun, ResearchSource, ToolExecution,
                                 ValidationDecision)
from research_lab.services import events, report

#: The workflow in display order (also the order of the graph's layers).
AGENT_ORDER = (AGENT_BOSS, AGENT_WEB_RESEARCH, AGENT_ACADEMIC_RESEARCH, AGENT_DOCUMENT_RETRIEVAL, AGENT_DOCUMENT_ANALYSIS,
               AGENT_SOURCE_VALIDATOR, AGENT_LECTURE_BUILDER, AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER)

#: Spec requirement: no single agent should carry more than 40% of the work.
MAX_AGENT_LOAD_PCT = 40.0

_ACADEMIC = (MaterialType.PAPERS, MaterialType.BOOKS, MaterialType.DOCUMENTATION)


def disabled_reason(run: ResearchRun, agent: str) -> str:
    """Mirrors the "not requested, so this agent never runs" conditions in ``agents/boss.py``."""
    wants = lambda *types: not run.material_types or any(t in run.material_types for t in types)  # noqa: E731
    if run.mode == 'SEARCH' and agent in (AGENT_SOURCE_VALIDATOR, AGENT_LECTURE_BUILDER,
                                          AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER):
        return 'Not used in a materials search'
    if agent == AGENT_WEB_RESEARCH and not wants(MaterialType.WEB):
        return 'Web materials were not requested'
    if agent == AGENT_ACADEMIC_RESEARCH and not wants(*_ACADEMIC):
        return 'No academic material types were requested'
    if agent == AGENT_LECTURE_BUILDER and not run.generate_lecture:
        return 'No lecture was requested'
    if agent == AGENT_ASSIGNMENT_GENERATOR and not run.generate_assignment:
        return 'No assignment was requested'
    if agent == AGENT_FINAL_REVIEWER and not (run.generate_lecture or run.generate_assignment):
        return 'Nothing to review'
    return ''


def _decimal(value) -> float:
    return float(value or Decimal(0))


_BUSY = ('working', 'using_tool', 'reviewing', 'retrying')

_MISSION_TITLE = {
    'web_research': 'Web search', 'academic_research': 'Academic search', 'document_retrieval': 'Document download',
    'document_analysis': 'Text extraction',
    'source_validator': 'Source validation', 'lecture_builder': 'Lecture building',
    'assignment_generator': 'Assignment generation', 'final_reviewer': 'Final review',
}


def _successor(run: ResearchRun, key: str) -> str:
    return {
        'boss': 'Web Research / Academic Research', 'web_research': 'Document Retrieval',
        'academic_research': 'Document Retrieval', 'document_retrieval': 'Document Analysis',
        'document_analysis': 'Source Validator',
        'source_validator': 'Lecture Builder' if run.generate_lecture else 'Assignment Generator',
        'lecture_builder': 'Final Reviewer', 'assignment_generator': 'Final Reviewer',
        'final_reviewer': 'Run complete',
    }.get(key, '')


def _result(key: str, decision, progress: dict | None, found: int) -> str:
    """What the agent has produced so far, in one short line, from its own recorded facts."""
    extra = progress or {}
    if key == 'source_validator' and extra.get('input_sources'):
        return f"{extra.get('accepted', 0)} accepted · {extra.get('rejected', 0)} rejected"
    if key in ('document_retrieval', 'document_analysis') and extra.get('total'):
        verb = 'downloaded' if key == 'document_retrieval' else 'read'
        return f"{extra.get('processed', 0)} / {extra.get('total', 0)} documents {verb}"
    if key in ('web_research', 'academic_research') and found:
        return f'{found} sources found'
    if decision is not None and not decision.payload.get('source_id'):
        return decision.summary
    return ''


def _mission(run: ResearchRun, agents: list[dict], terminal: bool) -> dict:
    """The single "what is the team doing right now" block, built only from the live agent's real
    progress (reviewed 13 / 20 …) — never from elapsed time."""
    if terminal:
        return {'agent': '', 'agent_name': '', 'title': run.get_status_display(), 'done': None, 'total': None,
                'percent': 100 if run.status in ('COMPLETED', 'PARTIAL') else None, 'current_item': '',
                'finished': True}
    busy = [a for a in agents if a['status'] in _BUSY and a['agent'] != 'boss']
    live = max(busy, key=lambda a: a['last_event_pk'], default=None)
    if live is None:
        queued = max((a for a in agents if a['status'] == 'queued'), key=lambda a: a['last_event_pk'], default=None)
        return {'agent': queued['agent'] if queued else 'boss', 'agent_name': queued['name'] if queued else 'Boss / Orchestrator',
                'title': 'Planning' if not queued else _MISSION_TITLE.get(queued['agent'], 'Starting'),
                'done': None, 'total': None, 'percent': None, 'current_item': '', 'finished': False}
    progress = live['progress'] or {}
    steps = progress.get('steps') or []
    done = total = None
    if progress.get('input_sources'):
        done, total = int(progress.get('reviewed', 0)), int(progress['input_sources'])
    elif progress.get('total'):
        done, total = int(progress.get('processed', 0)), int(progress['total'])
    elif steps:
        done = sum(1 for s in steps if s.get('status') in ('done', 'skipped', 'failed'))
        total = len(steps)
    return {'agent': live['agent'], 'agent_name': live['name'], 'title': _MISSION_TITLE.get(live['agent'], live['name']),
            'done': done, 'total': total,
            'percent': round(done / total * 100) if total else None,
            'current_item': progress.get('current_source') or progress.get('current_item') or '',
            'finished': False}


def build(run: ResearchRun) -> dict:
    now = timezone.now()
    terminal = run.status in TERMINAL_RUN_STATUSES

    # -- the event journal, newest first: latest status / note / decision / progress per agent -------
    latest: dict[str, dict[str, ResearchEvent]] = {}
    handoffs: list[ResearchEvent] = []
    reviews: dict[str, ResearchEvent] = {}
    found_by_agent: dict[str, int] = {}
    last_event_id = 0
    for event in ResearchEvent.objects.filter(run=run).order_by('-id')[:4000]:
        last_event_id = max(last_event_id, event.pk)
        if event.type == events.AGENT_HANDOFF:
            handoffs.append(event)
        if event.agent:
            slot = latest.setdefault(event.agent, {})
            slot.setdefault(event.type, event)
            if event.type in events.STATUS_EVENT_TYPES:
                slot.setdefault('status_event', event)
                if event.status != 'queued':
                    slot.setdefault('model_event', event)
            if (event.type == events.TOOL_COMPLETED and event.status == 'completed'
                    and event.payload.get('operation') == 'search'):
                found_by_agent[event.agent] = found_by_agent.get(event.agent, 0) + int(event.payload.get('result_count') or 0)
            if event.type == events.AGENT_DECISION and event.agent == events.agent_key(AGENT_FINAL_REVIEWER):
                reviews.setdefault(event.payload.get('target', ''), event)
    handoffs.reverse()

    executions = list(run.agent_executions.all())
    tool_counts = dict(ToolExecution.objects.filter(run=run, agent_execution__isnull=False).exclude(status='SKIPPED')
                       .values_list('agent_execution__agent').annotate(n=Count('id')))
    usage: dict[str, dict] = {}
    for row in (GenerationRun.objects.filter(metadata__run_id=run.pk)
                .values('metadata__agent', 'configuration__provider__code')
                .annotate(calls=Count('id'), tokens=Sum('total_tokens'), cost=Sum('estimated_cost'))):
        agent = row['metadata__agent'] or ''
        entry = usage.setdefault(agent, {'calls': 0, 'tokens': 0, 'cost': 0.0, 'local': 0, 'cloud': 0})
        entry['calls'] += row['calls']
        entry['tokens'] += row['tokens'] or 0
        entry['cost'] += _decimal(row['cost'])
        entry['local' if row['configuration__provider__code'] == 'LOCAL' else 'cloud'] += row['calls']

    agents = []
    busy_ms: dict[str, int] = {}
    for position, agent in enumerate(AGENT_ORDER):
        key = events.agent_key(agent)
        slot = latest.get(key, {})
        own = [e for e in executions if e.agent == agent]
        busy = 0
        for execution in own:
            busy += execution.latency_ms if execution.latency_ms is not None else int(
                (now - execution.started_at).total_seconds() * 1000)
        if agent == AGENT_BOSS and not terminal and run.started_at:
            busy = int((now - run.started_at).total_seconds() * 1000)  # it orchestrates the whole run
        busy_ms[agent] = busy

        reason = disabled_reason(run, agent)
        status_event = slot.get('status_event')
        status = status_event.status if status_event else ('disabled' if reason else ('not_run' if terminal else 'waiting'))
        if reason and not own:
            status = 'disabled'

        model_event = slot.get('model_event') or slot.get('status_event')
        if model_event and model_event.provider:
            info = {'provider': model_event.provider, 'model_name': model_event.model_name,
                    'provider_kind': model_event.payload.get('provider_kind', 'system')}
        else:
            info = events.model_info(run, agent)

        note = slot.get(events.AGENT_NOTE)
        tool_started, tool_done = slot.get(events.TOOL_STARTED), slot.get(events.TOOL_COMPLETED)
        tool = tool_started if tool_started and (tool_done is None or tool_started.pk > tool_done.pk) else None
        current = max((e for e in (note, tool) if e), key=lambda e: e.pk, default=None)
        decision = slot.get(events.AGENT_DECISION)
        progress = slot.get(events.AGENT_PROGRESS)
        stats = usage.get(agent, {})
        agents.append({
            'agent': key, 'name': AgentName(agent).label, 'order': position,
            'enabled': not reason, 'disabled_reason': reason,
            'status': status, 'status_summary': status_event.summary if status_event else '',
            'provider': info.get('provider', 'system'), 'provider_kind': info.get('provider_kind', 'system'),
            'model_name': info.get('model_name', ''),
            'current_action': current.summary if current else '',
            'current_tool': (tool.payload.get('tool', '') if tool else ''),
            'last_event_pk': status_event.pk if status_event else 0,
            'decision': ({'decision': decision.status, 'summary': decision.summary,
                          'reason': decision.payload.get('reason', ''),
                          'next_action': decision.payload.get('next_action', ''),
                          'source_id': decision.payload.get('source_id')} if decision else None),
            'progress': ({'steps': progress.payload.get('steps', []),
                          **{k: v for k, v in progress.payload.items() if k not in ('steps', 'provider_kind', 'execution_id')}}
                         if progress else None),
            'executions': len(own), 'tool_calls': tool_counts.get(agent, 0),
            'llm_calls': stats.get('calls', 0), 'tokens': stats.get('tokens', 0), 'cost': round(stats.get('cost', 0.0), 6),
            'duration_ms': busy,
            'started_at': own[0].started_at.isoformat() if own else None,
            'result': _result(key, decision, progress.payload if progress else None, found_by_agent.get(key, 0)),
            'next_step': ((decision.payload.get('next_action') if decision and not decision.payload.get('source_id') else '')
                          or (f'Hand over to {_successor(run, key)}' if _successor(run, key) else '')),
        })

    # -- research state ---------------------------------------------------------------------------
    sources = ResearchSource.objects.filter(run=run)
    found = sum(int((e.output_summary or {}).get('total_found', 0)) for e in executions
                if e.agent in (AGENT_WEB_RESEARCH, AGENT_ACADEMIC_RESEARCH))
    doc = next((e for e in executions if e.agent == AGENT_DOCUMENT_RETRIEVAL), None)
    lecture = run.lectures.order_by('-version').first()
    assignment = getattr(run, 'assignment', None)
    research_state = {
        'topic': run.topic, 'education_level': run.education_level, 'status': run.status,
        'current_step': run.current_step,
        'sources_discovered': found,
        'sources_unique': int((doc.output_summary or {}).get('unique_after_metadata_dedup', 0)) if doc else 0,
        'sources_analyzed': sources.filter(document__isnull=False).count(),
        'sources_accepted': sources.filter(decision=ValidationDecision.ACCEPT).count(),
        'sources_rejected': sources.filter(decision=ValidationDecision.REJECT).count(),
        'sources_need_review': sources.filter(decision=ValidationDecision.REVIEW).count(),
        'lecture': ({'status': lecture.status, 'version': lecture.version, 'score': lecture.review_score,
                     'title': lecture.title, 'sections': len(lecture.content_json.get('sections') or [])}
                    if lecture else {'status': 'WAITING' if run.generate_lecture else 'NOT_REQUESTED'}),
        'assignment': ({'status': assignment.review_status, 'version': run.revision_count + 1,
                        'score': assignment.review_score, 'title': assignment.title,
                        'questions': len(assignment.questions or [])}
                       if assignment else {'status': 'WAITING' if run.generate_assignment else 'NOT_REQUESTED'}),
    }

    # -- metrics -----------------------------------------------------------------------------------
    # Load is measured as the brief defines it: each agent's share of all LLM + tool calls (not of time).
    load, _total_calls = report.load_shares(run)
    total_busy = sum(busy_ms.values()) or 1
    for item in load:
        item['time_pct'] = round(busy_ms[next(a for a in AGENT_ORDER if events.agent_key(a) == item['agent'])] / total_busy * 100, 1)
    max_load = max((item['pct'] for item in load), default=0.0)
    elapsed = None
    if run.started_at:
        elapsed = ((run.finished_at or now) - run.started_at).total_seconds()
    local_calls = sum(u['local'] for u in usage.values())
    cloud_calls = sum(u['cloud'] for u in usage.values())
    cloud_cost = sum(_decimal(r['cost']) for r in (
        GenerationRun.objects.filter(metadata__run_id=run.pk).exclude(configuration__provider__code='LOCAL')
        .values('configuration__provider__code').annotate(cost=Sum('estimated_cost'))))
    metrics = {
        'sources': research_state['sources_discovered'], 'analyzed': research_state['sources_analyzed'],
        'accepted': research_state['sources_accepted'],
        # Three different things, never mixed: an agent *run* is one step of an agent, an *LLM call*
        # is one model request, a *tool call* is one external call (search API, download, parser).
        'agent_runs': len(executions), 'llm_calls': local_calls + cloud_calls, 'tool_calls': sum(tool_counts.values()),
        'local_calls': local_calls, 'claude_calls': cloud_calls,
        'tokens': sum(u['tokens'] for u in usage.values()),
        'cloud_cost': round(cloud_cost, 6), 'elapsed_seconds': elapsed,
        'load': load, 'load_basis': 'calls', 'max_agent_load_pct': max_load, 'load_limit_pct': MAX_AGENT_LOAD_PCT,
        'load_ok': max_load <= MAX_AGENT_LOAD_PCT,
    }

    return {
        'run': {'id': run.pk, 'topic': run.topic, 'status': run.status, 'current_step': run.current_step,
                'is_active': run.is_active, 'llm_mode': run.llm_mode, 'revision_count': run.revision_count,
                'lecture_revision_count': run.lecture_revision_count,
                'started_at': run.started_at.isoformat() if run.started_at else None,
                'finished_at': run.finished_at.isoformat() if run.finished_at else None,
                'error_message': run.error_message},
        'agents': agents, 'research_state': research_state, 'metrics': metrics,
        'mission': _mission(run, agents, terminal),
        'handoffs': [{'id': e.pk, 'from': e.payload.get('from_agent'), 'to': e.payload.get('to_agent'),
                      'summary': e.summary, 'created_at': e.created_at.isoformat(),
                      'revision': bool(e.payload.get('revision')), 'target': e.payload.get('target', ''),
                      'version': e.payload.get('version')} for e in handoffs[-120:]],
        'reviews': {target: {'decision': e.status, 'score': e.payload.get('score'),
                             'issues': e.payload.get('issues', []), 'summary': e.summary}
                    for target, e in reviews.items() if target},
        'last_event_id': last_event_id,
    }
