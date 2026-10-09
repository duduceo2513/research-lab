"""Writes the ``AgentExecution``/``ToolExecution`` append-only journal that the frontend's
"Agent Logs" / "Tool Calls" tabs and the metrics endpoint read from.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from django.utils import timezone

from research_lab.exceptions import RunCancelled
from research_lab.models import AGENT_BOSS, AGENT_FINAL_REVIEWER, AgentExecution, ExecutionStatus, ResearchRun, ToolExecution
from research_lab.services import events


@contextmanager
def agent_step(run: ResearchRun, agent: str, sequence: int, *, input_summary: dict | None = None):
    """Creates a RUNNING ``AgentExecution``, yields it, and marks it SUCCESS/FAILED on exit.

    Usage::

        with journal.agent_step(run, AGENT_WEB_RESEARCH, seq, input_summary={...}) as execution:
            ... do the work, optionally: execution.generation_run = some_generation_run ...
            execution.output_summary = {...}
    """
    info = events.model_info(run, agent)
    execution = AgentExecution.objects.create(run=run, agent=agent, sequence=sequence,
                                              input_summary=input_summary or {},
                                              metadata={'model_info': info})
    started = time.perf_counter()
    events.emit(run, events.AGENT_STARTED, agent, info=info, status='reviewing' if agent == AGENT_FINAL_REVIEWER else 'working',
                summary='Started', execution_id=execution.pk, sequence=sequence)
    final_status, final_summary = 'completed', 'Finished'
    try:
        yield execution
    except Exception as exc:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = f'{type(exc).__name__}: {exc}'[:4000]
        final_status = 'cancelled' if isinstance(exc, RunCancelled) else 'failed'
        final_summary = str(exc)[:300]
        raise
    else:
        if execution.status == ExecutionStatus.RUNNING:  # the caller may have set SKIPPED itself
            execution.status = ExecutionStatus.SUCCESS
        if execution.status == ExecutionStatus.SKIPPED:
            final_status = 'skipped'
    finally:
        execution.latency_ms = int((time.perf_counter() - started) * 1000)
        execution.finished_at = timezone.now()
        execution.save()
        # The Boss keeps orchestrating after its planning step; its terminal status is emitted by
        # the workflow itself (``agents.boss``), not when this one step ends.
        if agent != AGENT_BOSS or final_status in ('failed', 'cancelled'):
            events.emit(run, events.AGENT_FAILED if final_status in ('failed', 'cancelled') else events.AGENT_COMPLETED,
                        agent, info=info, status=final_status, summary=final_summary,
                        execution_id=execution.pk, sequence=sequence, duration_ms=execution.latency_ms)


#: Kinds: ``info`` (what the agent is doing), ``thought`` (a conclusion/reasoning it reached),
#: ``result`` (an outcome), ``warn`` (something went wrong but the step carries on).
MAX_ACTIVITY_ENTRIES = 300


def note(execution: AgentExecution, text: str, kind: str = 'info') -> None:
    """Appends one line to the agent's live activity timeline and persists it immediately, so the
    frontend (polling) sees it while the step is still running. Never raises: a journalling
    hiccup must not break the agent that is doing real work."""
    try:
        if len(execution.activity) >= MAX_ACTIVITY_ENTRIES:
            return
        execution.activity.append({'at': timezone.now().isoformat(), 'kind': kind, 'text': str(text)[:600]})
        execution.save(update_fields=['activity'])
        events.emit(execution.run_id, events.AGENT_NOTE, execution.agent, info=_info(execution),
                    summary=str(text), kind=kind, execution_id=execution.pk)
    except Exception:  # noqa: BLE001
        pass


def _info(execution: AgentExecution) -> dict:
    return (execution.metadata or {}).get('model_info') or {}


def tool_start(execution: AgentExecution, tool: str, operation: str = '', **request) -> None:
    """Announces that ``tool`` is being called right now (the agent shows as USING_TOOL until the
    matching ``log_tool`` records the outcome)."""
    info = _info(execution)
    events.emit(execution.run_id, events.TOOL_STARTED, execution.agent, info=info, status='running',
                summary=f'{tool}.{operation}() …' if operation else f'{tool} …', tool=tool, operation=operation,
                request=request, execution_id=execution.pk)
    events.emit(execution.run_id, events.AGENT_STATUS, execution.agent, info=info, status='using_tool',
                summary=f'Calling {tool}', tool=tool, execution_id=execution.pk)


def progress(execution: AgentExecution, steps: list[dict], **extra) -> None:
    """Publishes the agent's real, ordered sub-steps: ``[{'id', 'label', 'status', 'detail'?}]`` with
    status ``done`` / ``active`` / ``pending`` / ``failed`` / ``skipped``. Each call is a full snapshot."""
    events.emit(execution.run_id, events.AGENT_PROGRESS, execution.agent, info=_info(execution),
                summary=next((s['label'] for s in steps if s.get('status') == 'active'), ''),
                steps=steps, execution_id=execution.pk, **extra)


def decide(execution: AgentExecution, decision: str, summary: str, *, reason: str = '', next_action: str = '',
           **extra) -> None:
    """A short, deliberately written decision record (never raw model reasoning)."""
    events.emit(execution.run_id, events.AGENT_DECISION, execution.agent, info=_info(execution),
                status=decision, summary=summary, decision=decision, reason=reason[:500],
                next_action=next_action[:300], execution_id=execution.pk, **extra)


def handoff(run: ResearchRun, from_agent: str, to_agent: str, summary: str, **extra) -> None:
    """Records a real hand-off of work between two agents; the target shows as QUEUED until it starts."""
    events.emit(run, events.AGENT_HANDOFF, from_agent, summary=summary, from_agent=events.agent_key(from_agent),
                to_agent=events.agent_key(to_agent), **extra)
    events.emit(run, events.AGENT_STATUS, to_agent, info=events.model_info(run, to_agent), status='queued',
                summary=f'Queued by {events.agent_key(from_agent)}: {summary}')


def candidate_summary(candidate) -> dict:
    """A compact, JSON-friendly view of one search result, kept as part of the tool call's response so the
    Agent Logs can show what a source actually returned (not just how many results)."""
    return {
        'title': candidate.title, 'url': candidate.url, 'pdf_url': candidate.pdf_url or None,
        'authors': candidate.authors[:4], 'year': candidate.published_at.year if candidate.published_at else None,
        'doi': candidate.doi or None, 'type': str(candidate.source_type),
        'abstract': (candidate.abstract[:300] + '…') if len(candidate.abstract) > 300 else candidate.abstract,
        'has_full_text': bool(candidate.full_text),
    }


def log_tool(run: ResearchRun, agent_execution: AgentExecution | None, tool: str, *, status: str,
            request_summary: dict | None = None, response_summary: dict | None = None,
            latency_ms: int | None = None, error_message: str = '', operation: str = '') -> ToolExecution:
    tool_execution = ToolExecution.objects.create(
        run=run, agent_execution=agent_execution, tool=tool, status=status,
        request_summary=request_summary or {}, response_summary=response_summary or {},
        latency_ms=latency_ms, error_message=error_message,
    )
    if agent_execution is not None:
        info = _info(agent_execution)
        count = (response_summary or {}).get('count')
        ok = status == ExecutionStatus.SUCCESS
        events.emit(run, events.TOOL_COMPLETED, agent_execution.agent, info=info, status={'SUCCESS': 'completed'}.get(status, status.lower()),
                    summary=(f'{tool}: {count} results' if count is not None else f'{tool}: {status.lower()}')
                    + (f' ({error_message[:120]})' if error_message else ''),
                    tool=tool, operation=operation, request=request_summary or {}, result_count=count, latency_ms=latency_ms,
                    error=error_message[:300], execution_id=agent_execution.pk)
        events.emit(run, events.AGENT_STATUS, agent_execution.agent, info=info,
                    status='working',
                    summary=f'{tool} {"done" if ok else status.lower()}', execution_id=agent_execution.pk)
    return tool_execution
