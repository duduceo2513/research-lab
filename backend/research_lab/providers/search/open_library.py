"""Open Library — keyless book catalogue. Records describe books (authors, year, subjects); there is
no text to download, so the catalogue metadata is kept as the description.

https://openlibrary.org/dev/docs/api/search
"""
from __future__ import annotations

from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://openlibrary.org/search.json'


class OpenLibraryProvider(SearchProvider):
    code = SourceProvider.OPEN_LIBRARY
    metadata_only = True

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        data = get_json(BASE_URL, params={'q': query, 'limit': min(limit, 50)})
        candidates = []
        for item in data.get('docs', []):
            authors = item.get('author_name') or []
            subjects = (item.get('subject') or [])[:15]
            year = item.get('first_publish_year')
            description = '; '.join(filter(None, [
                f"Authors: {', '.join(authors)}" if authors else '',
                f'First published: {year}' if year else '',
                f"Subjects: {', '.join(subjects)}" if subjects else '',
            ]))
            isbns = item.get('isbn') or []
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.BOOK, title=item.get('title') or 'Untitled',
                url=f"https://openlibrary.org{item.get('key', '')}", external_id=item.get('key', ''),
                authors=authors, publisher=', '.join((item.get('publisher') or [])[:2]), abstract=description,
                isbn=isbns[0] if isbns else '', metadata={'first_publish_year': year, 'subjects': subjects},
            ))
        return candidates
