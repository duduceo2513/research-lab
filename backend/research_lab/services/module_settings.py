"""Live status of each search source (configured via secrets/env, enabled via the Settings page, and
the outcome of its latest real call) — backs the public config endpoint, the admin settings endpoint
and the "test connection" action."""
from __future__ import annotations

from research_lab.models import ModuleSettings
from research_lab.providers.search import registry

#: What the badge in Settings -> Research Lab shows.
STATE_ACTIVE = 'active'
STATE_DISABLED = 'disabled'
STATE_MISSING_KEY = 'missing_key'
STATE_ERROR = 'error'


def all_providers() -> list:
    # Read the registries at call time so tests (and any future runtime registration) are honoured.
    return [*registry.WEB_PROVIDERS, *registry.ACADEMIC_PROVIDERS]


def provider_status(provider, settings_row: ModuleSettings | None = None) -> dict:
    settings_row = settings_row or ModuleSettings.load()
    code = str(provider.code)
    enabled = code not in set(settings_row.disabled_providers)
    missing = provider.missing_settings()
    configured = provider.configured()
    health = (settings_row.provider_health or {}).get(code) or {}
    if not enabled:
        state = STATE_DISABLED
    elif not configured:
        state = STATE_MISSING_KEY
    elif health and not health.get('ok', True):
        state = STATE_ERROR
    else:
        state = STATE_ACTIVE
    return {
        'code': code, 'label': provider.code.label if hasattr(provider.code, 'label') else code,
        'configured': configured, 'enabled': enabled, 'state': state, 'missing_settings': missing,
        'last_error': '' if health.get('ok', True) else health.get('error', ''),
        'last_checked': health.get('at'), 'metadata_only': bool(getattr(provider, 'metadata_only', False)),
    }


def provider_statuses() -> list[dict]:
    settings_row = ModuleSettings.load()
    return [provider_status(provider, settings_row) for provider in all_providers()]
