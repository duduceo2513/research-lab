"""arXiv API — keyless, public. Returns Atom XML, parsed with the stdlib (no new XML dependency).

https://info.arxiv.org/help/api/user-manual.html
"""
from __future__ import annotations

from datetime import date, datetime
from xml.etree import ElementTree

import httpx

from research_lab.exceptions import ProviderError
from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import DEFAULT_TIMEOUT
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://export.arxiv.org/api/query'
ATOM = '{http://www.w3.org/2005/Atom}'


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except ValueError:
        return None


def _pdf_url(entry: ElementTree.Element, abs_url: str) -> str:
    for link in entry.findall(f'{ATOM}link'):
        if link.get('title') == 'pdf' or link.get('type') == 'application/pdf':
            return link.get('href', '')
    # arXiv's abstract and PDF URLs differ only by this path segment.
    return abs_url.replace('/abs/', '/pdf/') if '/abs/' in abs_url else ''


class ArxivProvider(SearchProvider):
    code = SourceProvider.ARXIV

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        params = {'search_query': f'all:{query}', 'start': 0, 'max_results': min(limit, 50)}
        try:
            response = httpx.get(BASE_URL, params=params, timeout=DEFAULT_TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except httpx.HTTPError as exc:
            raise ProviderError(f'arXiv request failed: {type(exc).__name__}: {exc}') from exc
        except ElementTree.ParseError as exc:
            raise ProviderError('arXiv returned malformed XML') from exc

        candidates = []
        for entry in root.findall(f'{ATOM}entry'):
            abs_url = (entry.findtext(f'{ATOM}id') or '').strip()
            title = ' '.join((entry.findtext(f'{ATOM}title') or '').split())
            summary = ' '.join((entry.findtext(f'{ATOM}summary') or '').split())
            authors = [
                name.strip() for name in (a.findtext(f'{ATOM}name') for a in entry.findall(f'{ATOM}author'))
                if name and name.strip()
            ]
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.PAPER, title=title or 'Untitled',
                url=abs_url, external_id=abs_url, authors=authors,
                publisher='arXiv', published_at=_parse_date(entry.findtext(f'{ATOM}published')),
                abstract=summary, open_access=True, pdf_url=_pdf_url(entry, abs_url),
            ))
        return candidates
