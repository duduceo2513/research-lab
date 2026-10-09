"""CORE (core.ac.uk) — the world's largest collection of open-access research papers. Needs an API
key (``CORE_API_KEY``). Many results carry the full text already, which saves a download.

https://api.core.ac.uk/docs/v3
"""
from __future__ import annotations

from django.conf import settings

from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://api.core.ac.uk/v3/search/works'


def _pdf_link(item: dict) -> str:
    if item.get('downloadUrl'):
        return item['downloadUrl']
    for link in item.get('links') or []:
        if isinstance(link, dict) and 'pdf' in str(link).lower() and link.get('url'):
            return link['url']
    return ''


class CoreProvider(SearchProvider):
    code = SourceProvider.CORE
    required_settings = ('CORE_API_KEY',)

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        data = get_json(BASE_URL, params={'q': query, 'limit': min(limit, 30)},
                        headers={'Authorization': f'Bearer {settings.CORE_API_KEY}'})
        candidates = []
        for item in data.get('results', []):
            pdf = _pdf_link(item)
            doi = (item.get('doi') or '').removeprefix('https://doi.org/')
            authors = [a.get('name') for a in item.get('authors') or [] if isinstance(a, dict) and a.get('name')]
            year = item.get('yearPublished')
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.PAPER, title=item.get('title') or 'Untitled',
                url=(f'https://doi.org/{doi}' if doi else pdf) or f"https://core.ac.uk/works/{item.get('id', '')}",
                external_id=str(item.get('id') or ''), authors=authors, doi=doi,
                abstract=item.get('abstract') or '', full_text=item.get('fullText') or '',
                open_access=True, pdf_url=pdf, metadata={'year': year, 'core_id': item.get('id')},
            ))
        return candidates
