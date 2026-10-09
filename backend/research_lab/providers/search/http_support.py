"""Shared HTTP plumbing for search providers: a short-timeout client and uniform error wrapping."""
from __future__ import annotations

import re

import httpx

from research_lab.exceptions import ProviderError

DEFAULT_TIMEOUT = 10.0

_SECRET_PARAM = re.compile(r"""(?i)([?&](?:key|api_key|apikey|token|access_token)=)[^&\s'"]+""")


def scrub(message: object) -> str:
    """Removes API keys/tokens that an HTTP library may echo back inside an error message."""
    return _SECRET_PARAM.sub(r'\1[REDACTED]', str(message))


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> dict:
    try:
        # follow_redirects: httpx defaults to False, and a public API moving http->https (as arXiv
        # did) or adding a trailing-slash redirect would otherwise surface as a opaque 3xx failure.
        response = httpx.get(url, params=params, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f'{url} returned HTTP {exc.response.status_code}') from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f'{url} request failed: {type(exc).__name__}: {scrub(exc)}') from exc
    except ValueError as exc:  # json.JSONDecodeError
        raise ProviderError(f'{url} returned a non-JSON response') from exc
