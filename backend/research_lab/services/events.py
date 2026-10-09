"""Research Lab event bus: persist first, then fan out over Channels.

    agent code -> ``emit()`` -> ``ResearchEvent`` row (PostgreSQL) -> channel layer group
    ``research_run_<id>`` -> ``ResearchRunConsumer`` -> browser

Persisting first means the WebSocket is only a notification channel: the frontend rebuilds history
from ``GET runs/<id>/events/`` and the graph from ``GET runs/<id>/workspace/``, then keeps
listening. ``emit()`` never raises — a journalling or broadcast failure must not break the agent
that is doing real work.

Event types (``type``): ``agent_started``, ``agent_status`` (queued / using_tool / working again /
warning ...), ``agent_completed``, ``agent_failed``, ``tool_started``, ``tool_completed``,
``agent_decision``, ``agent_handoff``, plus ``agent_note`` (one-line activity), ``agent_progress``
(real sub-steps) and ``run_status``. The agent key is lower-case, e.g.
``source_validator``. No event ever carries raw model reasoning: only the short, deliberately
written ``summary`` / ``reason`` / ``next_action`` fields the agent code itself produced.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from research_lab.models import (AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER, AGENT_LECTURE_BUILDER,
                                 AGENT_SOURCE_VALIDATOR, ResearchEvent, ResearchRun)

logger = logging.getLogger('research_lab')

RUN_STATUS = 'run_status'
AGENT_STARTED = 'agent_started'
AGENT_STATUS = 'agent_status'
AGENT_COMPLETED = 'agent_completed'
AGENT_FAILED = 'agent_failed'
AGENT_NOTE = 'agent_note'
AGENT_PROGRESS = 'agent_progress'
TOOL_STARTED = 'tool_started'
TOOL_COMPLETED = 'tool_completed'
AGENT_DECISION = 'agent_decision'
AGENT_HANDOFF = 'agent_handoff'
EVENT_TYPES = (RUN_STATUS, AGENT_STARTED, AGENT_STATUS, AGENT_COMPLETED, AGENT_FAILED, AGENT_NOTE, AGENT_PROGRESS,
               TOOL_STARTED, TOOL_COMPLETED, AGENT_DECISION, AGENT_HANDOFF)
#: Event types that carry an agent's lifecycle status in ``ResearchEvent.status``.
STATUS_EVENT_TYPES = (AGENT_STARTED, AGENT_STATUS, AGENT_COMPLETED, AGENT_FAILED)

#: The agents that call a language model. The others (boss, web/academic research, document
#: analysis) are deterministic services, so they report provider ``system`` (shown as SYSTEM).
LLM_AGENTS = (AGENT_SOURCE_VALIDATOR, AGENT_LECTURE_BUILDER, AGENT_ASSIGNMENT_GENERATOR, AGENT_FINAL_REVIEWER)

#: Provider "kind" shown as the LOCAL / CLOUD badge.
_KIND = {'LOCAL': 'local', 'OPENAI': 'cloud', 'ANTHROPIC': 'cloud'}


def agent_key(agent: str) -> str:
    return agent.lower()


def group_name(run_id: int) -> str:
    return f'research_run_{run_id}'


def model_info(run: ResearchRun, agent: str) -> dict:
    """Which provider/model this agent uses for ``run``. Never raises."""
    if agent not in LLM_AGENTS:
        return {'provider': 'system', 'provider_kind': 'system', 'model_name': '', 'configuration': ''}
    try:
        from research_lab.services.llm_router import resolve_configuration

        config = resolve_configuration(run, agent)
        code = config.provider.code
        return {'provider': code.lower(), 'provider_kind': _KIND.get(code, 'cloud'),
                'model_name': config.model_name, 'configuration': config.name}
    except Exception:  # noqa: BLE001
        logger.exception('Could not resolve the model for %s in run %s', agent, run.pk)
        return {'provider': 'unknown', 'provider_kind': 'unknown', 'model_name': '', 'configuration': ''}


def serialize(event: ResearchEvent) -> dict:
    return {
        'id': event.pk, 'run': event.run_id, 'type': event.type, 'agent': event.agent,
        'provider': event.provider, 'model_name': event.model_name, 'status': event.status,
        'summary': event.summary, 'payload': event.payload, 'created_at': event.created_at.isoformat(),
    }


def _broadcast(run_id: int, data: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group_name(run_id), {'type': 'research.event', 'event': data})
    except Exception:  # noqa: BLE001 - a broken channel layer must never fail the agent
        logger.exception('Broadcasting research event for run %s failed', run_id)


def emit(run: ResearchRun | int, type: str, agent: str = '', *, status: str = '', summary: str = '',
         info: dict | None = None, **payload) -> ResearchEvent | None:
    """Persists one event and broadcasts it. ``info`` is a ``model_info()`` dict (provider/model)."""
    try:
        run_id = run.pk if isinstance(run, ResearchRun) else run
        info = info or {}
        with transaction.atomic():  # a savepoint: a failed insert must not poison the caller's transaction
            event = ResearchEvent.objects.create(
                run_id=run_id, type=type, agent=agent_key(agent) if agent else '', status=str(status)[:32],
                provider=info.get('provider', ''), model_name=str(info.get('model_name', ''))[:128],
                summary=str(summary)[:600],
                payload={**({'provider_kind': info['provider_kind']} if info.get('provider_kind') else {}), **payload},
            )
        data = serialize(event)
        transaction.on_commit(lambda: _broadcast(run_id, data))
        return event
    except Exception:  # noqa: BLE001
        logger.exception('Could not record research event %s for run %s', type, run)
        return None
