"""SSRF-safe URL fetching, with an escalating fallback chain:

    plain HTTP GET
     -> (if blocked/empty and Playwright is installed) render with Playwright
     -> (if that fails or is unavailable) Bright Data Browser/Unlocker

Each stage is optional-on-failure: a missing Playwright install or missing Bright Data credentials
just means that stage is skipped, not that the fetch fails outright (see ``research_lab/README.md``
-> Fault tolerance).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

import httpx
from django.conf import settings

from research_lab.exceptions import FetchError, ProviderUnavailable, SsrfBlocked
from research_lab.models import FetchMethod
from research_lab.providers.search.brightdata import fetch_via_unlocker
from research_lab.schemas import FetchResult

logger = logging.getLogger('research_lab')

ALLOWED_SCHEMES = {'http', 'https'}
#: The server said "you may not have this". That is a decision, not a glitch: it is never worked
#: around (no JS rendering, no unlocker service) — the material is simply not downloaded.
ACCESS_DENIED_STATUSES = {401, 402, 403, 451}
MAX_REDIRECTS = 5
#: Below this much extracted-looking content, a page is treated as "probably needs JS rendering".
JS_RENDER_HEURISTIC_BYTES = 200


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


def _assert_public_host(host: str) -> None:
    """Resolve ``host`` and reject it if any resolved address is private/loopback/etc. Resolving
    (rather than trusting the hostname string) is what actually closes the DNS-rebinding SSRF hole."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfBlocked(f'Could not resolve host {host!r}: {exc}') from exc
    for info in infos:
        ip = info[4][0]
        if not _is_public_ip(ip):
            raise SsrfBlocked(f'Host {host!r} resolves to a non-public address ({ip}); refusing to fetch it.')


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfBlocked(f'Unsupported URL scheme {parsed.scheme!r}.')
    if not parsed.hostname:
        raise SsrfBlocked('URL has no host.')
    _assert_public_host(parsed.hostname)


def _detect_content_type(content_type_header: str, url: str, content: bytes = b'') -> str:
    header = (content_type_header or '').lower()
    path = urlparse(url).path.lower()
    if content[:5] == b'%PDF-' or 'pdf' in header or path.endswith('.pdf'):
        return 'PDF'
    if 'officedocument.wordprocessingml' in header or path.endswith('.docx'):
        return 'DOCX'
    if 'officedocument.presentationml' in header or path.endswith('.pptx'):
        return 'PPTX'
    if (header.startswith('text/plain') or path.endswith(('.txt', '.md'))) and content[:100].lstrip()[:1] != b'<':
        return 'TXT'
    return 'HTML'


def _fetch_http(url: str, *, max_bytes: int, timeout: float) -> tuple[bytes, str, str]:
    """Plain HTTP GET with manual, SSRF-checked redirect following (every hop is re-validated)."""
    current = url
    headers = {'User-Agent': settings.RESEARCH_LAB_FETCH_USER_AGENT}
    for _ in range(MAX_REDIRECTS + 1):
        _check_url(current)
        with httpx.stream('GET', current, headers=headers, timeout=timeout, follow_redirects=False) as response:
            if response.is_redirect:
                location = response.headers.get('location')
                if not location:
                    raise FetchError(f'{current} redirected without a Location header.')
                current = str(httpx.URL(current).join(location))
                continue
            response.raise_for_status()
            content_type = response.headers.get('content-type', '')
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(f'{current} exceeded the {max_bytes} byte download limit.')
                chunks.append(chunk)
            return b''.join(chunks), content_type, current
    raise FetchError(f'{url}: too many redirects.')


def _try_playwright(url: str, *, timeout: float) -> bytes | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None  # optional dependency not installed — silently skip this stage
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, timeout=timeout * 1000, wait_until='networkidle')
                return page.content().encode('utf-8')
            finally:
                browser.close()
    except Exception as exc:  # Playwright failures are varied; treat them all as "this stage failed"
        logger.warning('Playwright fetch failed for %s: %s', url, exc)
        return None


def fetch_url(url: str) -> FetchResult:
    """Fetch ``url`` through the fallback chain. Raises ``FetchError``/``SsrfBlocked`` only when
    every stage has failed (or is unavailable)."""
    timeout = settings.RESEARCH_LAB_FETCH_TIMEOUT_SECONDS
    max_bytes = settings.RESEARCH_LAB_MAX_DOWNLOAD_MB * 1024 * 1024
    started = time.perf_counter()

    try:
        content, content_type_header, final_url = _fetch_http(url, max_bytes=max_bytes, timeout=timeout)
        content_type = _detect_content_type(content_type_header, final_url, content)
        looks_empty = content_type == 'HTML' and len(content) < JS_RENDER_HEURISTIC_BYTES
        if not looks_empty:
            return FetchResult(content=content, content_type=content_type, final_url=final_url,
                               fetch_method=FetchMethod.HTTP, latency_ms=int((time.perf_counter() - started) * 1000))
        logger.info('%s returned suspiciously little HTML; trying a JS-rendering fallback.', url)
    except SsrfBlocked:
        raise  # never escalate past an explicit SSRF block
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in ACCESS_DENIED_STATUSES:
            raise FetchError(f'Access denied (HTTP {exc.response.status_code}); not downloaded.') from exc
        logger.info('Plain HTTP fetch failed for %s (%s); trying fallbacks.', url, exc)
    except (FetchError, httpx.HTTPError) as exc:
        # FetchError is raised by _fetch_http itself (size limit, bad redirect); httpx.HTTPError
        # covers everything the library can raise (connection errors, timeouts, 4xx/5xx) — both
        # just mean "plain HTTP didn't work", so both fall through to the next stage.
        logger.info('Plain HTTP fetch failed for %s (%s); trying fallbacks.', url, exc)

    rendered = _try_playwright(url, timeout=timeout)
    if rendered:
        return FetchResult(content=rendered, content_type='HTML', final_url=url,
                           fetch_method=FetchMethod.PLAYWRIGHT, latency_ms=int((time.perf_counter() - started) * 1000))

    try:
        content, latency_ms = fetch_via_unlocker(url, timeout=timeout)
        return FetchResult(content=content, content_type='HTML', final_url=url,
                           fetch_method=FetchMethod.BRIGHTDATA_BROWSER, latency_ms=latency_ms)
    except ProviderUnavailable:
        pass  # no Bright Data credentials — nothing left to try
    except FetchError as exc:
        logger.info('Bright Data Unlocker fallback also failed for %s: %s', url, exc)

    raise FetchError(f'All fetch strategies failed for {url}.')
