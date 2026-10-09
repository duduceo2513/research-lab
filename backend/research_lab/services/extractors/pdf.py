from __future__ import annotations

import logging
from typing import BinaryIO

from pypdf import PdfReader

from research_lab.services.extractors.base import ParsedPart, clean_text

logger = logging.getLogger('research_lab')


def extract_pdf(fh: BinaryIO) -> list[ParsedPart]:
    """One part per page. Scanned pages without a text layer come back empty (no OCR)."""
    reader = PdfReader(fh)
    if reader.is_encrypted:
        # Empty-password PDFs are common; anything else cannot be processed.
        if not reader.decrypt(''):
            raise ValueError('The PDF is password-protected.')
    parts: list[ParsedPart] = []
    for i, page in enumerate(reader.pages):
        try:
            text = clean_text(page.extract_text() or '')
        except Exception as exc:  # a single broken page must not fail the whole document
            logger.warning('PDF page %s could not be extracted: %s', i + 1, exc)
            text = ''
        parts.append(ParsedPart(part_type='PAGE', index=i, text=text, page_number=i + 1,
                                metadata={} if text else {'needs_ocr': True}))
    return parts
