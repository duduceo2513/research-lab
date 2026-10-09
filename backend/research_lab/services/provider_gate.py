"""Which search sources may run for a given run, and what the last real call to each one showed.

Two switches decide whether a source is used: the global on/off in ``ModuleSettings`` (Settings ->
Research Lab) and, optionally, the subset the teacher picked for this particular run. A source that
is enabled but missing its API key is *skipped*, not failed — see ``SearchProvider.configured``.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from research_lab.models import ModuleSettings, ResearchRun
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import scrub

logger = logging.getLogger('research_lab')


def allowed(run: ResearchRun, provider: SearchProvider) -> tuple[bool, str]:
    """``(True, '')`` when ``provider`` may be queried for ``run``, else ``(False, reason)``."""
    code = str(provider.code)
    if not ModuleSettings.is_provider_enabled(code):
        return False, 'disabled in settings'
    if run.selected_providers and code not in run.selected_providers:
        return False, 'not selected for this search'
    return True, ''


def record_health(code: str, ok: bool, error: str = '') -> None:
    """Remembers the outcome of the latest real call, for the status badge in Settings. Never raises."""
    try:
        settings_row = ModuleSettings.load()
        health = dict(settings_row.provider_health or {})
        health[str(code)] = {'ok': ok, 'error': '' if ok else scrub(error)[:300], 'at': timezone.now().isoformat()}
        settings_row.provider_health = health
        settings_row.save(update_fields=['provider_health', 'updated_at'])
    except Exception:  # noqa: BLE001 - bookkeeping must never break a search
        logger.exception('Could not record the health of provider %s', code)
