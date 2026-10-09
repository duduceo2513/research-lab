"""Crossref Works API — keyless; used both as a source provider and (via ``lookup_doi``) for DOI
metadata verification.

https://api.crossref.org/swagger-ui/index.html
"""
from __future__ import annotations

from datetime import date

from django.conf import settings

from research_lab.exceptions import ProviderError
from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://api.crossref.org/works'


def _user_agent() -> str:
    # Crossref's "polite pool" (faster, more reliable) is granted to requests that identify
    # themselves with a mailto in the User-Agent — see https://api.crossref.org/swagger-ui/index.html#/Works.
    base = settings.RESEARCH_LAB_FETCH_USER_AGENT
    return f'{base} (mailto:{settings.CROSSREF_MAILTO})' if settings.CROSSREF_MAILTO else base


def _parse_date(parts: dict | None) -> date | None:
    date_parts = ((parts or {}).get('date-parts') or [[]])[0]
    if not date_parts:
        return None
    year = date_parts[0]
    month = date_parts[1] if len(date_parts) > 1 else 1
    day = date_parts[2] if len(date_parts) > 2 else 1
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, 1, 1)


def _authors(item: dict) -> list[str]:
    names = []
    for author in item.get('author', []) or []:
        name = ' '.join(filter(None, [author.get('given'), author.get('family')]))
        if name:
            names.append(name)
    return names


def _to_candidate(item: dict) -> SourceCandidate:
    published = item.get('published-print') or item.get('published-online') or item.get('published')
    return SourceCandidate(
        provider=SourceProvider.CROSSREF, source_type=SourceType.PAPER,
        title=(item.get('title') or ['Untitled'])[0], url=item.get('URL', ''),
        external_id=item.get('DOI', ''), authors=_authors(item),
        publisher=item.get('publisher', ''), published_at=_parse_date(published),
        abstract=item.get('abstract', ''), doi=item.get('DOI', ''),
        citation_count=item.get('is-referenced-by-count'),
        open_access=bool(item.get('license')),
        metadata={'type': item.get('type')},
    )


class CrossrefProvider(SearchProvider):
    code = SourceProvider.CROSSREF
    metadata_only = True  # abstracts and landing pages, not documents

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        data = get_json(BASE_URL, params={'query.bibliographic': query, 'rows': min(limit, 100)},
                        headers={'User-Agent': _user_agent()})
        items = (data.get('message') or {}).get('items', [])
        return [_to_candidate(item) for item in items]


def lookup_doi(doi: str) -> SourceCandidate | None:
    """Metadata verification for a known DOI (section 7's "DOI validation" use case)."""
    try:
        data = get_json(f'{BASE_URL}/{doi}', headers={'User-Agent': _user_agent()})
    except ProviderError:
        return None
    message = data.get('message')
    return _to_candidate(message) if message else None
