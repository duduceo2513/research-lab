"""SSRF and fallback-chain tests for ``research_lab.services.fetcher``. All network I/O is mocked."""
from unittest import mock

import httpx
from django.test import SimpleTestCase, override_settings

from research_lab.exceptions import FetchError, SsrfBlocked
from research_lab.models import FetchMethod
from research_lab.services import fetcher


def _stream_ctx(status_code=200, content=b'hello', headers=None, is_redirect=False, location=None):
    response = mock.MagicMock()
    response.is_redirect = is_redirect
    response.status_code = status_code
    response.headers = headers or {'content-type': 'text/html'}
    if is_redirect:
        response.headers = {**response.headers, 'location': location}
    response.raise_for_status = mock.Mock() if status_code < 400 else mock.Mock(
        side_effect=httpx.HTTPStatusError('error', request=mock.Mock(), response=response))
    response.iter_bytes = mock.Mock(return_value=iter([content]))
    ctx = mock.MagicMock()
    ctx.__enter__ = mock.Mock(return_value=response)
    ctx.__exit__ = mock.Mock(return_value=False)
    return ctx


class SsrfProtectionTests(SimpleTestCase):
    def test_private_address_is_blocked(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('10.0.0.5', 80))]):
            with self.assertRaises(SsrfBlocked):
                fetcher.fetch_url('http://internal.example.com/secret')

    def test_loopback_is_blocked(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
            with self.assertRaises(SsrfBlocked):
                fetcher.fetch_url('http://localhost/secret')

    def test_unresolvable_host_is_blocked(self):
        import socket

        with mock.patch('socket.getaddrinfo', side_effect=socket.gaierror('no such host')):
            with self.assertRaises(SsrfBlocked):
                fetcher.fetch_url('http://does-not-exist.invalid/')

    def test_non_http_scheme_is_blocked(self):
        with self.assertRaises(SsrfBlocked):
            fetcher.fetch_url('file:///etc/passwd')

    def test_public_address_is_allowed(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
                mock.patch('httpx.stream', return_value=_stream_ctx(content=b'x' * 500)):
            result = fetcher.fetch_url('http://example.com/')
        self.assertEqual(result.fetch_method, FetchMethod.HTTP)


class RedirectTests(SimpleTestCase):
    def test_a_redirect_hop_resolves_to_a_real_url_string_and_is_refetched(self):
        # Regression test: _fetch_http used to call the non-existent httpx.URL.human_repr() here,
        # which raised AttributeError on the very first redirect hop in production (a real DOI
        # resolver 302) instead of FetchError/content — this exercises the real httpx.URL.join()
        # + str() logic rather than mocking it away.
        redirect = _stream_ctx(is_redirect=True, location='/landing')
        final = _stream_ctx(content=b'x' * 500)
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
                mock.patch('httpx.stream', side_effect=[redirect, final]):
            result = fetcher.fetch_url('http://example.com/doi-link')
        self.assertEqual((result.fetch_method, result.final_url), (FetchMethod.HTTP, 'http://example.com/landing'))


class FallbackChainTests(SimpleTestCase):
    def test_too_little_content_triggers_playwright_fallback_when_installed(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
                mock.patch('httpx.stream', return_value=_stream_ctx(content=b'x' * 10)), \
                mock.patch('research_lab.services.fetcher._try_playwright', return_value=b'<html>rendered</html>'):
            result = fetcher.fetch_url('http://example.com/js-app')
        self.assertEqual((result.fetch_method, result.content), (FetchMethod.PLAYWRIGHT, b'<html>rendered</html>'))

    def test_falls_back_to_brightdata_when_playwright_unavailable(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
                mock.patch('httpx.stream', return_value=_stream_ctx(content=b'x' * 10)), \
                mock.patch('research_lab.services.fetcher._try_playwright', return_value=None), \
                mock.patch('research_lab.services.fetcher.fetch_via_unlocker', return_value=(b'<html>ok</html>', 42)):
            result = fetcher.fetch_url('http://example.com/js-app')
        self.assertEqual((result.fetch_method, result.content), (FetchMethod.BRIGHTDATA_BROWSER, b'<html>ok</html>'))

    def test_raises_when_every_stage_fails(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
                mock.patch('httpx.stream', side_effect=httpx.ConnectError('down')), \
                mock.patch('research_lab.services.fetcher._try_playwright', return_value=None), \
                mock.patch('research_lab.services.fetcher.fetch_via_unlocker',
                          side_effect=FetchError('unlocker down')):
            with self.assertRaises(FetchError):
                fetcher.fetch_url('http://example.com/blocked')

    @override_settings(RESEARCH_LAB_MAX_DOWNLOAD_MB=0)
    def test_download_size_limit_is_enforced(self):
        with mock.patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 80))]), \
                mock.patch('httpx.stream', return_value=_stream_ctx(content=b'x' * 1000)), \
                mock.patch('research_lab.services.fetcher._try_playwright', return_value=None), \
                mock.patch('research_lab.services.fetcher.fetch_via_unlocker', side_effect=FetchError('n/a')):
            with self.assertRaises(FetchError):
                fetcher.fetch_url('http://example.com/huge')
