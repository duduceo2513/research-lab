"""Bright Data — web search (SERP) and, separately, the Browser/Unlocker fetch fallback.

Credentials only via ``BRIGHTDATA_API_TOKEN`` / ``BRIGHTDATA_SERP_ZONE`` (environment). Both calls
go through Bright Data's token-based "Request API" (``POST https://api.brightdata.com/request``),
which is their current unified entry point for both SERP zones and Web Unlocker zones:

    {"zone": <zone>, "url": <target>, "format": "json" | "raw"}
    Authorization: Bearer <token>

For a SERP zone, ``url`` is a search-engine URL with ``brd_json=1`` appended, which makes Bright
Data return already-parsed results instead of raw HTML. For a Web Unlocker zone (used as the
Document Analysis agent's last-resort fetch fallback), ``url`` is the page to render and
``format: "raw"`` returns the rendered HTML.

Response parsing follows the standalone ``web_search_apis/check_apis_with_text.py`` script, which was
verified against a live account: the SERP is requested with ``format: "raw"`` and may arrive as plain
JSON, as JSON wrapped in a ``body`` string, or as HTML — all three are handled. Any failure is an
ordinary, non-fatal ``ProviderError``/``FetchError`` (see ``research_lab/README.md`` -> Fault
tolerance), so a surprise here degrades the run, it does not break it.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup
from django.conf import settings

from research_lab.exceptions import FetchError, ProviderError, ProviderUnavailable
from research_lab.models import SourceProvider, SourceType
from research_lab.providers.search.base import SearchProvider
from research_lab.providers.search.http_support import scrub
from research_lab.schemas import SourceCandidate

logger = logging.getLogger('research_lab')

REQUEST_URL = 'https://api.brightdata.com/request'
SEARCH_URL = 'https://www.google.com/search?q={query}&brd_json=1'


def _headers() -> dict:
    return {'Authorization': f'Bearer {settings.BRIGHTDATA_API_TOKEN}', 'Content-Type': 'application/json'}


def _organic_results(raw: str) -> list[dict]:
    """Pulls the organic result list out of whatever the zone returned (JSON, JSON in a ``body``
    string, or an HTML results page). Raises ``ValueError`` if nothing usable is found."""
    raw = raw.lstrip('\ufeff').strip()
    if not raw:
        raise ValueError('Bright Data returned an empty response')
    try:
        data = json.loads(raw)
        for _ in range(3):  # unwrap {"body": "<json string>"} and double-encoded strings
            if isinstance(data, str):
                data = json.loads(data)
            elif isinstance(data, dict) and isinstance(data.get('body'), str):
                data = json.loads(data['body'])
            else:
                break
        if isinstance(data, dict):
            if data.get('error'):
                raise ValueError(f"Bright Data error: {str(data['error'])[:300]}")
            organic = data.get('organic')
            if organic is None and isinstance(data.get('results'), dict):
                organic = data['results'].get('organic')
            if organic is None and isinstance(data.get('results'), list):
                organic = data['results']
            if organic is None and isinstance(data.get('content'), dict):
                organic = data['content'].get('organic')
            if isinstance(organic, list):
                return [item for item in organic if isinstance(item, dict)]
            raise ValueError('Bright Data JSON has no "organic" results')
    except json.JSONDecodeError:
        pass
    if '<html' in raw[:2000].lower() or '<!doctype html' in raw[:2000].lower():
        links = []
        for anchor in BeautifulSoup(raw, 'html.parser').select('a[href]'):
            href = anchor.get('href', '')
            if href.startswith('/url?q='):
                href = href.split('/url?q=', 1)[1].split('&', 1)[0]
            title = anchor.get_text(' ', strip=True)
            if title and href.startswith('http') and 'google.com' not in urlparse(href).netloc:
                links.append({'title': title, 'link': href, 'description': ''})
        if links:
            return links
        raise ValueError('Bright Data returned HTML without usable result links')
    raise ValueError('Bright Data response is neither SERP JSON nor HTML')


def _format_hint(link: str) -> str:
    path = urlparse(link).path.lower()
    for extension in ('pdf', 'pptx', 'docx', 'txt'):
        if path.endswith('.' + extension):
            return extension
    return 'html'


def _parse_serp_response(results: list[dict]) -> list[SourceCandidate]:
    """One candidate per organic result, de-duplicated by link."""
    candidates = []
    seen: set[str] = set()
    for item in results:
        link = item.get('link') or item.get('url') or ''
        if not link.startswith('http') or link in seen:
            continue
        seen.add(link)
        candidates.append(SourceCandidate(
            provider=SourceProvider.BRIGHTDATA, source_type=SourceType.WEB,
            title=item.get('title') or link, url=link, external_id=link,
            abstract=item.get('description') or item.get('snippet') or '',
            metadata={'rank': item.get('rank'), 'format_hint': _format_hint(link)},
        ))
    return candidates


class BrightDataSearchProvider(SearchProvider):
    code = SourceProvider.BRIGHTDATA
    required_settings = ('BRIGHTDATA_API_TOKEN', 'BRIGHTDATA_SERP_ZONE')
    multi_query = True  # several narrower searches find PDFs and slides far more often than one big query

    def search(self, query: str, *, limit: int) -> list[SourceCandidate]:
        if not self.configured():
            raise ProviderUnavailable('BRIGHTDATA_API_TOKEN / BRIGHTDATA_SERP_ZONE is not set.')
        payload = {
            'zone': settings.BRIGHTDATA_SERP_ZONE,
            'url': SEARCH_URL.format(query=quote_plus(query)),
            'format': 'raw',
        }
        try:
            response = httpx.post(REQUEST_URL, json=payload, headers=_headers(), timeout=60.0)
            response.raise_for_status()
            organic = _organic_results(response.text)
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f'Bright Data returned HTTP {exc.response.status_code}: '
                                f'{scrub(exc.response.text[:200])}') from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f'Bright Data request failed: {type(exc).__name__}: {scrub(exc)}') from exc
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
        return _parse_serp_response(organic)[:limit]


def fetch_via_unlocker(url: str, *, timeout: float) -> tuple[bytes, int]:
    """Browser/Unlocker fallback fetch for a blocked or JS-rendered page. Returns (html_bytes, latency_ms).

    Only called after a plain HTTP fetch (and, if installed, Playwright) have both failed — see
    ``research_lab/services/fetcher.py``.
    """
    if not (settings.BRIGHTDATA_API_TOKEN and settings.BRIGHTDATA_SERP_ZONE):
        raise ProviderUnavailable('BRIGHTDATA_API_TOKEN / BRIGHTDATA_SERP_ZONE is not set.')
    payload = {'zone': settings.BRIGHTDATA_SERP_ZONE, 'url': url, 'format': 'raw'}
    started = time.perf_counter()
    try:
        response = httpx.post(REQUEST_URL, json=payload, headers=_headers(), timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FetchError(f'Bright Data Unlocker failed for {url}: {type(exc).__name__}: {exc}') from exc
    return response.content, int((time.perf_counter() - started) * 1000)
