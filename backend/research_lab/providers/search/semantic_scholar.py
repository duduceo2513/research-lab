"""Semantic Scholar Academic Graph API — keyless (rate-limited); a key raises the rate limit.

https://api.semanticscholar.org/api-docs/graph#tag/Paper-Data/operation/get_graph_get_paper_search
"""
from __future__ import annotations

from datetime import date

from django.conf import settings

from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://api.semanticscholar.org/graph/v1/paper/search'
FIELDS = ('paperId,title,abstract,url,year,authors,venue,citationCount,'
          'isOpenAccess,openAccessPdf,externalIds,publicationDate')


def _parse_date(value: str | None, year: int | None) -> date | None:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    if year:
        return date(year, 1, 1)
    return None


class SemanticScholarProvider(SearchProvider):
    code = SourceProvider.SEMANTIC_SCHOLAR

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        headers = {}
        if settings.SEMANTIC_SCHOLAR_API_KEY:
            headers['x-api-key'] = settings.SEMANTIC_SCHOLAR_API_KEY
        data = get_json(BASE_URL, params={'query': query, 'limit': min(limit, 100), 'fields': FIELDS},
                        headers=headers)
        candidates = []
        for item in data.get('data', []):
            external_ids = item.get('externalIds') or {}
            pdf = item.get('openAccessPdf') or {}
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.PAPER,
                title=item.get('title') or 'Untitled', url=item.get('url', ''),
                external_id=item.get('paperId', ''),
                authors=[a['name'] for a in item.get('authors', []) if a.get('name')],
                publisher=item.get('venue', ''),
                published_at=_parse_date(item.get('publicationDate'), item.get('year')),
                abstract=item.get('abstract') or '', doi=external_ids.get('DOI', ''),
                citation_count=item.get('citationCount'), open_access=bool(item.get('isOpenAccess')),
                pdf_url=pdf.get('url', ''), metadata={'external_ids': external_ids},
            ))
        return candidates
