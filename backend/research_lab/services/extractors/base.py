from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Protocol


@dataclass
class ParsedPart:
    """Format-neutral result of extraction (one page, slide or section)."""

    part_type: str  # 'PAGE' | 'SLIDE' | 'SECTION'
    index: int
    text: str
    title: str = ''
    page_number: int | None = None
    slide_number: int | None = None
    metadata: dict = field(default_factory=dict)


class Extractor(Protocol):
    def __call__(self, fh: BinaryIO) -> list[ParsedPart]: ...


def clean_text(text: str | None) -> str:
    """Strip NUL bytes (rejected by many databases and tools) and normalise line endings."""
    if not text:
        return ''
    text = text.replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n')
    return text.strip()
