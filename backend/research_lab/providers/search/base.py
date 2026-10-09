"""Provider interface every search/academic provider implements.

Every ``.search()`` call must either return a list (possibly empty) or raise ``ProviderError`` /
``ProviderUnavailable`` — never let an unrelated exception (e.g. a ``KeyError`` from a malformed
response) escape unclassified, since the caller logs ``ProviderError`` as a normal, expected
failure and keeps the run going (see ``research_lab/agents/web_research.py`` and
``academic_research.py``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from django.conf import settings

from research_lab.schemas import SourceCandidate


class SearchProvider(ABC):
    #: a research_lab.models.SourceProvider value; used as ToolExecution.tool and SourceCandidate.provider.
    code: str
    #: Names of the Django settings (= environment variables) that must be non-empty for this
    #: provider to work at all. Most public APIs need none.
    required_settings: tuple[str, ...] = ()
    #: True when results only describe a resource (a catalogue record, a landing page, a video):
    #: the description is kept as the text and no document download is attempted.
    metadata_only: bool = False
    #: True when several narrower query variants pay off (web search); other providers get one query.
    multi_query: bool = False

    def missing_settings(self) -> list[str]:
        return [name for name in self.required_settings if not getattr(settings, name, '')]

    def configured(self) -> bool:
        """True when this provider has everything it needs to run (most need nothing: they are
        public, keyless APIs). Unconfigured providers are skipped, not treated as failures."""
        return not self.missing_settings()

    @abstractmethod
    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        """Return up to ``limit`` candidates for ``query``. Raises ``ProviderError`` on failure."""
