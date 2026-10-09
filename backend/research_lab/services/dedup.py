"""Deduplication, in two phases (see research_lab/README.md -> Deduplication):

Phase 1 (``dedupe_candidates``) runs on bare metadata, before any fetch/LLM budget is spent: DOI,
ISBN, normalised URL, then fuzzy (title, author-set, year). Phase 2 (``content_hash``) runs after
extraction, to catch the same content reachable at two different URLs (e.g. a paper's publisher
page and its university mirror).
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlunparse

from research_lab.schemas import SourceCandidate

TITLE_SIMILARITY_THRESHOLD = 0.92
_WHITESPACE = re.compile(r'\s+')


def normalize_url(url: str) -> str:
    """Strips scheme, query, fragment and a trailing slash, and lowercases the host, so that
    ``http://Example.com/x?utm=1`` and ``https://example.com/x/`` compare equal."""
    if not url:
        return ''
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    return urlunparse(('', parsed.netloc.lower(), path, '', '', ''))


def normalize_doi(doi: str) -> str:
    return doi.strip().lower().removeprefix('https://doi.org/').removeprefix('doi:')


def normalize_isbn(isbn: str) -> str:
    return re.sub(r'[^0-9x]', '', isbn.lower())


def _normalize_title(title: str) -> str:
    return _WHITESPACE.sub(' ', title.strip().lower())


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8', errors='ignore')).hexdigest()


def _same_title(a: str, b: str) -> bool:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio() >= TITLE_SIMILARITY_THRESHOLD


def dedupe_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    """Returns ``candidates`` with exact/near duplicates removed, keeping the first occurrence
    (providers earlier in the search order — typically the more authoritative ones — win)."""
    kept: list[SourceCandidate] = []
    seen_dois: set[str] = set()
    seen_isbns: set[str] = set()
    seen_urls: set[str] = set()

    for candidate in candidates:
        doi = normalize_doi(candidate.doi)
        isbn = normalize_isbn(candidate.isbn)
        url = normalize_url(candidate.url)

        if doi and doi in seen_dois:
            continue
        if isbn and isbn in seen_isbns:
            continue
        if url and url in seen_urls:
            continue
        if any(
            _same_title(candidate.title, other.title)
            and (candidate.authors[:1] == other.authors[:1])
            and (candidate.published_at is None or other.published_at is None
                 or candidate.published_at.year == other.published_at.year)
            for other in kept
        ):
            continue

        if doi:
            seen_dois.add(doi)
        if isbn:
            seen_isbns.add(isbn)
        if url:
            seen_urls.add(url)
        kept.append(candidate)

    return kept
