"""Exceptions specific to Research Lab's fault-tolerance design.

A ``ProviderError`` (or any exception) from one search/academic provider or one document fetch is
always caught at the call site and logged as a failed ``ToolExecution`` — it must never abort the
whole run. Only ``BudgetExceeded`` (step/time/document limits) and ``RunCancelled`` stop a run early.
"""
from __future__ import annotations


class ProviderError(Exception):
    """A search/academic provider call failed (HTTP error, bad response shape, missing config)."""


class ProviderUnavailable(ProviderError):
    """The provider is not configured (e.g. no API token) — expected, not logged as an error."""


class FetchError(Exception):
    """Fetching a URL's content failed (network, blocked, too large, disallowed host)."""


class SsrfBlocked(FetchError):
    """The target host resolves to a private/loopback/link-local address — refused on principle."""


class BudgetExceeded(Exception):
    """The run hit its step count, document count or wall-clock time limit."""


class RunCancelled(Exception):
    """The user requested cancellation (``ResearchRun.cancel_requested``)."""
