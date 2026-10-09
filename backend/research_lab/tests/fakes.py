"""Fakes for provider/fetch calls, so tests never hit the real internet."""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

from research_lab.exceptions import FetchError, ProviderError
from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.schemas import FetchResult, SourceCandidate


class FakeProvider(SearchProvider):
    """Returns a fixed list of candidates, or raises ``ProviderError`` if told to fail."""

    def __init__(self, code: str, candidates: list[SourceCandidate] | None = None,
                fail: bool = False, is_configured: bool = True) -> None:
        self.code = code
        self._candidates = candidates or []
        self._fail = fail
        self._is_configured = is_configured
        self.calls: list[str] = []

    def configured(self) -> bool:
        return self._is_configured

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        self.calls.append(query)
        if self._fail:
            raise ProviderError(f'{self.code} is down')
        return list(self._candidates)[:limit]


def make_candidate(title: str = 'A test source', provider: str = SourceProvider.OPENALEX, **kw) -> SourceCandidate:
    return SourceCandidate(provider=provider, source_type=kw.pop('source_type', SourceType.PAPER),
                           title=title, url=kw.pop('url', f'https://example.com/{title}'), **kw)


@contextmanager
def patch_providers(*, web=None, academic=None):
    """Replaces the WEB_PROVIDERS / ACADEMIC_PROVIDERS registries used by the agents."""
    import research_lab.providers.search.registry as registry

    with mock.patch.object(registry, 'WEB_PROVIDERS', web if web is not None else registry.WEB_PROVIDERS), \
            mock.patch.object(registry, 'ACADEMIC_PROVIDERS',
                              academic if academic is not None else registry.ACADEMIC_PROVIDERS):
        with mock.patch('research_lab.agents.web_research.WEB_PROVIDERS',
                        web if web is not None else registry.WEB_PROVIDERS), \
                mock.patch('research_lab.agents.academic_research.ACADEMIC_PROVIDERS',
                          academic if academic is not None else registry.ACADEMIC_PROVIDERS):
            yield


@contextmanager
def patch_llm_json(responses: dict[str, dict | list] | None = None, *, fail_codes: set[str] | None = None,
                   fail_with: Exception | None = None):
    """Replaces ``research_lab.services.llm_json.call_structured`` with one keyed by ``prompt_code``,
    so each agent (validator/generator/reviewer) can be given its own canned JSON reply without
    routing everything through the shared ``llm`` app's provider layer (see
    ``research_lab/tests/test_workflow.py`` for why: three different JSON shapes are needed in the
    same run, which ``core.testing.fake_llm`` — one shared canned answer — cannot express)."""
    calls: list[str] = []
    cursors: dict[str, int] = {}

    def fake_call_structured(*, prompt_code, **kwargs):
        calls.append(prompt_code)
        if fail_codes and prompt_code in fail_codes:
            from core.exceptions import ExternalServiceError

            raise fail_with or ExternalServiceError('the model is unavailable')
        value = (responses or {}).get(prompt_code)
        if isinstance(value, list):
            # A list of responses is consumed in order (one per call), repeating the last entry
            # once exhausted — e.g. the reviewer returning "needs_revision" then "approved".
            index = cursors.get(prompt_code, 0)
            cursors[prompt_code] = min(index + 1, len(value) - 1)
            return value[index], None
        return value, None

    with mock.patch('research_lab.services.llm_json.call_structured', side_effect=fake_call_structured):
        yield calls


@contextmanager
def patch_fetch(text: str = 'Fetched page content about the topic.', fail: bool = False):
    """Replaces ``research_lab.services.fetcher.fetch_url`` (used by document_analysis)."""
    def fake_fetch(url: str) -> FetchResult:
        if fail:
            raise FetchError(f'could not fetch {url}')
        return FetchResult(content=text.encode(), content_type='HTML', final_url=url,
                           fetch_method='HTTP', latency_ms=5)

    with mock.patch('research_lab.agents.document_retrieval.fetch_url', side_effect=fake_fetch) as mocked:
        yield mocked
