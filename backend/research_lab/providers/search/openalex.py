"""OpenAlex Works API — keyless (an API key only raises the rate limit; see settings.OPENALEX_API_KEY).

https://docs.openalex.org/api-entities/works/search-works
"""
from __future__ import annotations

import logging
from datetime import date

from django.conf import settings

from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

logger = logging.getLogger('research_lab')

BASE_URL = 'https://api.openalex.org/works'


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """OpenAlex never returns a plain abstract — only a word -> [positions] map (publisher
    licensing). Rebuild the text by placing each word at its recorded position(s)."""
    if not inverted_index:
        return ''
    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        for i in indices:
            positions[i] = word
    return ' '.join(positions[i] for i in sorted(positions))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class OpenAlexProvider(SearchProvider):
    code = SourceProvider.OPENALEX

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        params = {'search': query, 'per_page': min(limit, 25)}
        if settings.OPENALEX_MAILTO:
            params['mailto'] = settings.OPENALEX_MAILTO
        if settings.OPENALEX_API_KEY:
            params['api_key'] = settings.OPENALEX_API_KEY

        data = get_json(BASE_URL, params=params)
        candidates = []
        for item in data.get('results', []):
            best_oa = item.get('best_oa_location') or item.get('primary_location') or {}
            open_access = bool((item.get('open_access') or {}).get('is_oa'))
            doi = (item.get('doi') or '').removeprefix('https://doi.org/')
            authors = [
                a['author']['display_name']
                for a in item.get('authorships', [])
                if a.get('author', {}).get('display_name')
            ]
            source_name = ((item.get('primary_location') or {}).get('source') or {}).get('display_name', '')
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.PAPER,
                title=item.get('display_name') or item.get('title') or 'Untitled',
                url=item.get('id', ''), external_id=item.get('id', ''), authors=authors,
                publisher=source_name, published_at=_parse_date(item.get('publication_date')),
                abstract=_reconstruct_abstract(item.get('abstract_inverted_index')), doi=doi,
                citation_count=item.get('cited_by_count'), open_access=open_access,
                pdf_url=best_oa.get('pdf_url') or '',
                metadata={'openalex_id': item.get('id'), 'type': item.get('type')},
            ))
        return candidates
