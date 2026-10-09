"""Turns fetched bytes into plain text.

PDF, DOCX and PPTX go through ``services/extractors`` (pypdf, python-docx, python-pptx); HTML uses
BeautifulSoup to strip boilerplate (navigation, headers, footers, scripts, cookie banners).
"""
from __future__ import annotations

import io
import logging
import time

from bs4 import BeautifulSoup

from research_lab.schemas import ExtractResult
from research_lab.services.extractors.base import clean_text
from research_lab.services.extractors.docx import extract_docx
from research_lab.services.extractors.pdf import extract_pdf
from research_lab.services.extractors.pptx import extract_pptx

# pypdf logs one WARNING per font it cannot fully decode (fontTools is optional); that is noise here.
logging.getLogger('pypdf').setLevel(logging.ERROR)

#: Tags that are never part of the readable article body.
BOILERPLATE_TAGS = ('script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript', 'svg')


def _extract_html(content: bytes) -> str:
    soup = BeautifulSoup(content, 'lxml')
    for tag in soup.find_all(BOILERPLATE_TAGS):
        tag.decompose()
    # Common boilerplate landmarks that aren't always semantic <nav>/<footer> tags.
    for selector in ('[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
                     '.cookie-banner', '.cookie-consent', '#cookie-banner'):
        for tag in soup.select(selector):
            tag.decompose()
    text = soup.get_text(separator='\n')
    lines = [line.strip() for line in text.splitlines()]
    return clean_text('\n'.join(line for line in lines if line))


def _extract_plain(content: bytes) -> str:
    for encoding in ('utf-8', 'cp1251', 'latin-1'):
        try:
            return clean_text(content.decode(encoding))
        except UnicodeDecodeError:
            continue
    return clean_text(content.decode('utf-8', errors='replace'))


def extract_text(content: bytes, content_type: str) -> ExtractResult:
    """Dispatches on ``content_type`` ('HTML' | 'PDF' | 'DOCX' | 'PPTX' | 'TXT'); raises ``ValueError``
    for anything else. Pages/slides/paragraphs are joined with blank lines so the text stays readable."""
    started = time.perf_counter()
    if content_type == 'HTML':
        text = _extract_html(content)
    elif content_type == 'PDF':
        parts = extract_pdf(io.BytesIO(content))
        text = '\n\n'.join(p.text for p in parts if p.text)
    elif content_type == 'DOCX':
        parts = extract_docx(io.BytesIO(content))
        text = '\n\n'.join(p.text for p in parts if p.text)
    elif content_type == 'PPTX':
        parts = extract_pptx(io.BytesIO(content))
        text = '\n\n'.join(f'--- Slide {p.index + 1} ---\n{p.text}' for p in parts if p.text)
    elif content_type == 'TXT':
        text = _extract_plain(content)
    else:
        raise ValueError(f'Unsupported content type for extraction: {content_type!r}')
    return ExtractResult(text=text, latency_ms=int((time.perf_counter() - started) * 1000))
