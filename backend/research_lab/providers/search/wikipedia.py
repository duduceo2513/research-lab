"""Wikipedia — keyless encyclopedia search. The article itself is fetched and extracted by Document
Analysis (it is plain HTML), so results carry the search snippet only until then.

https://www.mediawiki.org/wiki/API:Search
"""
from __future__ import annotations

from urllib.parse import quote

from bs4 import BeautifulSoup
from django.conf import settings

from research_lab.exceptions import ProviderError
from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import get_json
from research_lab.schemas import SourceCandidate

BASE_URL = 'https://en.wikipedia.org/w/api.php'


class WikipediaProvider(SearchProvider):
    code = SourceProvider.WIKIPEDIA

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        # Wikimedia rejects (HTTP 403) clients that do not identify themselves with a descriptive User-Agent.
        agent = settings.RESEARCH_LAB_FETCH_USER_AGENT + (f' ({settings.API_CONTACT_EMAIL})' if settings.API_CONTACT_EMAIL else '')
        data = get_json(BASE_URL, headers={'User-Agent': agent}, params={
            'action': 'query', 'list': 'search', 'srsearch': query, 'srlimit': min(limit, 50), 'format': 'json'})
        if data.get('error'):
            raise ProviderError(f"Wikipedia error: {str(data['error'])[:200]}")
        candidates = []
        for item in data.get('query', {}).get('search', []):
            title = item.get('title') or 'Untitled'
            url = 'https://en.wikipedia.org/wiki/' + quote(title.replace(' ', '_'))
            candidates.append(SourceCandidate(
                provider=self.code, source_type=SourceType.ENCYCLOPEDIA, title=title, url=url, external_id=url,
                publisher='Wikipedia', open_access=True,
                abstract=BeautifulSoup(item.get('snippet', ''), 'html.parser').get_text(' ', strip=True),
                metadata={'pageid': item.get('pageid'), 'wordcount': item.get('wordcount')},
            ))
        return candidates
