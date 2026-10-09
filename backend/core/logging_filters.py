"""Logging filter that scrubs secrets (API keys, bearer tokens, JWTs) from records."""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    (re.compile(r'(?i)(authorization["\']?\s*[:=]\s*)(bearer\s+)?[^\s,;"\']+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._\-]+'), 'Bearer [REDACTED]'),
    (re.compile(r'\bsk-[A-Za-z0-9_\-]{8,}'), '[REDACTED_KEY]'),
    (re.compile(r'\bxi-[A-Za-z0-9_\-]{8,}'), '[REDACTED_KEY]'),
    (re.compile(r'(?i)((?:api[_-]?key|secret|token|password|access|refresh)["\']?\s*[=:]\s*)[^\s&,;"\']+'),
     r'\1[REDACTED]'),
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*'), '[REDACTED_JWT]'),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: never break logging
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
