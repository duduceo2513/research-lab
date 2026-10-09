from __future__ import annotations

from typing import BinaryIO

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from research_lab.services.extractors.base import ParsedPart, clean_text


def _iter_blocks(document):
    """Paragraphs and tables in document order."""
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            yield Paragraph(child, document)
        elif tag == 'tbl':
            yield Table(child, document)


def _is_heading(paragraph: Paragraph) -> bool:
    name = (paragraph.style.name or '') if paragraph.style is not None else ''
    return name.startswith('Heading') or name == 'Title'


def extract_docx(fh: BinaryIO) -> list[ParsedPart]:
    """Split a DOCX into sections at headings (one section if there are none)."""
    document = DocxDocument(fh)
    sections: list[tuple[str, list[str]]] = [('', [])]
    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            text = clean_text(block.text)
            if not text:
                continue
            if _is_heading(block):
                sections.append((text, []))
            else:
                sections[-1][1].append(text)
        else:
            for row in block.rows:
                cells = [clean_text(c.text) for c in row.cells]
                line = ' | '.join(c for c in cells if c)
                if line:
                    sections[-1][1].append(line)

    parts: list[ParsedPart] = []
    for title, lines in sections:
        if not title and not lines:
            continue
        text = '\n'.join(([title] if title else []) + lines)
        parts.append(ParsedPart(
            part_type='SECTION', index=len(parts), title=title[:500], text=text,
        ))
    return parts
