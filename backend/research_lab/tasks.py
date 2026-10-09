"""Runs a research run in the background — a daemon thread inside the Django process, so no broker
or worker is needed. The run's state lives in the database and its live events go through the
in-memory channel layer of this same process (see ``services/events.py``)."""
from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.db import close_old_connections, connection

from research_lab.models import ACTIVE_RUN_STATUSES, ResearchRun, ResearchRunStatus

logger = logging.getLogger('research_lab')


def run_research_task(run_id: int) -> int:
    """Runs the whole multi-agent workflow for one ResearchRun. See ``agents.boss.run_workflow``
    for why this never raises: the run's final status is always persisted."""
    if not settings.RESEARCH_LAB_ENABLED:
        ResearchRun.objects.filter(pk=run_id).update(
            status=ResearchRunStatus.FAILED, error_message='Research Lab is disabled on this server.')
        return run_id
    from research_lab.agents.boss import run_workflow

    run_workflow(run_id)
    return run_id


def _run_in_thread(run_id: int) -> None:
    close_old_connections()
    try:
        run_research_task(run_id)
    except Exception:  # noqa: BLE001 - run_workflow already persists failures; never kill silently
        logger.exception('Research run %s crashed outside the workflow', run_id)
    finally:
        connection.close()  # each thread owns its own connection


def dispatch(run_id: int) -> None:
    """Starts the run. Inline when ``RESEARCH_LAB_RUN_INLINE`` is set (tests, debugging)."""
    if settings.RESEARCH_LAB_RUN_INLINE:
        run_research_task(run_id)
        return
    threading.Thread(target=_run_in_thread, args=(run_id,), name=f'research-run-{run_id}', daemon=True).start()


def fail_interrupted_runs() -> int:
    """Background threads die with the server process: a run that was still active when the server
    stopped can never finish. Marks such runs as FAILED; called once when the server starts."""
    return ResearchRun.objects.filter(status__in=ACTIVE_RUN_STATUSES).update(
        status=ResearchRunStatus.FAILED, current_step='',
        error_message='The server stopped while this run was in progress.')
