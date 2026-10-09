"""Token estimation without any tokenizer download, so it works offline and is deterministic: every
word or punctuation mark counts as ~1.3 tokens, which tracks BPE tokenizers closely for Latin and
Cyrillic. Used only when a backend does not report usage."""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r'\w+|[^\w\s]', re.UNICODE)
TOKENS_PER_WORD = 1.3


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(_TOKEN_RE.findall(text)) * TOKENS_PER_WORD))
