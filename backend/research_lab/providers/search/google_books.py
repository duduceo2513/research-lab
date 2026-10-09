"""Google Books Volumes API — keyless (lower quota); a key raises the quota.

https://developers.google.com/books/docs/v1/using#WorkingVolumes
"""
from __future__ import annotations

from datetime import date

from django.conf import settings

from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://www.googleapis.com/books/v1/volumes'


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    parts = value.split('-')
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _isbn(identifiers: list[dict]) -> str:
    for ident in identifiers or []:
        if ident.get('type') in ('ISBN_13', 'ISBN_10'):
            return ident.get('identifier', '')
    return ''


class GoogleBooksProvider(SearchProvider):
    code = SourceProvider.GOOGLE_BOOKS
    metadata_only = True  # descriptions only; books are not downloaded

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        params = {'q': query, 'maxResults': min(limit, 40)}
        if settings.GOOGLE_BOOKS_API_KEY:
            params['key'] = settings.GOOGLE_BOOKS_API_KEY

        data = get_json(BASE_URL, params=params)
        candidates = []
        for item in data.get('items', []):
            info = item.get('volumeInfo', {})
            access = item.get('accessInfo', {})
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.BOOK,
                title=info.get('title') or 'Untitled', url=info.get('infoLink', ''),
                external_id=item.get('id', ''), authors=info.get('authors', []),
                publisher=info.get('publisher', ''), published_at=_parse_date(info.get('publishedDate')),
                abstract=info.get('description', ''), isbn=_isbn(info.get('industryIdentifiers')),
                open_access=access.get('viewability') == 'ALL_PAGES',
                metadata={'categories': info.get('categories', []), 'page_count': info.get('pageCount'),
                         'language': info.get('language'), 'preview_link': info.get('previewLink', '')},
            ))
        return candidates
