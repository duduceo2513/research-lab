"""Finding the relevant part of a long document — without a model.

A textbook or a thesis can be 100-200 pages; no model should be handed all of it, and the first few
thousand characters (front matter, a table of contents) are rarely what the topic needs. This module
splits a document into passages, scores each against the topic with BM25 (the classic keyword
ranking: rare query words count more, repeats saturate, long passages are not favoured) and returns
only the best ones, in their original order, within a character budget.

It is deliberately dependency-free and deterministic: the same document and topic always give the
same excerpts, and a 1 MB document is ranked in a few milliseconds.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

#: Target size of one passage; paragraphs are merged up to this and longer ones are split.
PASSAGE_CHARS = 900
#: A document this short is simply used whole.
WHOLE_DOCUMENT_CHARS = 2500
BM25_K1 = 1.5
BM25_B = 0.75

_WORD = re.compile(r'\w+', re.UNICODE)
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')
_STOPWORDS = frozenset(
    'a an the and or but if then else of to in on at by for with from as is are was were be been being it its this '
    'that these those which who whom what when where why how not no do does did can could should would may might '
    'will shall into over under about than so such also very more most other some any each both between during '
    'и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от '
    'меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж '
    'вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без '
    'будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один '
    'почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после '
    'над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой '
    'перед иногда лучше чуть том нельзя такой им более всегда конечно всю между'.split())


@dataclass(frozen=True)
class Passage:
    index: int
    text: str


def tokens(text: str) -> list[str]:
    """Lower-cased content words with a light suffix strip, so "loops"/"looping"/"looped" meet."""
    out = []
    for word in _WORD.findall(text.lower()):
        if len(word) < 3 or word in _STOPWORDS or word.isdigit():
            continue
        for suffix in ('ing', 'ed', 'es', 'ly', 's'):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                word = word[:-len(suffix)]
                break
        out.append(word)
    return out


def _split_long(paragraph: str) -> list[str]:
    if len(paragraph) <= PASSAGE_CHARS * 1.5:
        return [paragraph]
    pieces, current = [], ''
    for sentence in _SENTENCE_END.split(paragraph):
        if current and len(current) + len(sentence) > PASSAGE_CHARS:
            pieces.append(current)
            current = ''
        current = f'{current} {sentence}'.strip()
        while len(current) > PASSAGE_CHARS * 2:  # no sentence breaks at all (e.g. extracted tables)
            pieces.append(current[:PASSAGE_CHARS * 2])
            current = current[PASSAGE_CHARS * 2:]
    if current:
        pieces.append(current)
    return pieces


def split_passages(text: str) -> list[Passage]:
    """Paragraph-based passages of roughly ``PASSAGE_CHARS``; a short heading stays with what follows it."""
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if len(paragraphs) <= 1:  # extractors that only emit single newlines
        paragraphs = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        pieces.extend(_split_long(paragraph))
    merged: list[str] = []
    buffer = ''
    for piece in pieces:
        # Never merge boilerplate (reference lists...) with prose: it would hide inside a good passage.
        mixes = buffer and _looks_like_boilerplate(buffer) != _looks_like_boilerplate(piece)
        if buffer and (mixes or (len(buffer) + len(piece) > PASSAGE_CHARS and len(buffer) > 120)):
            merged.append(buffer)
            buffer = ''
        buffer = f'{buffer}\n\n{piece}'.strip() if buffer else piece
    if buffer:
        merged.append(buffer)
    return [Passage(i, p) for i, p in enumerate(merged)]


def _looks_like_boilerplate(text: str) -> bool:
    """Reference lists, licence blocks, number tables: rarely what a teacher wants to read."""
    head = text[:60].lower()
    if head.startswith(('references', 'bibliography', 'литература', 'список литературы')):
        return True
    if text.lower().count('doi.org') + text.lower().count('http') >= 4:
        return True
    digits = sum(ch.isdigit() for ch in text)
    return len(text) > 200 and digits / len(text) > 0.3


def rank_passages(passages: list[Passage], query: str) -> list[tuple[float, Passage]]:
    """Every passage with its BM25 score for ``query``, best first."""
    query_terms = list(dict.fromkeys(tokens(query)))
    if not passages or not query_terms:
        return [(0.0, p) for p in passages]
    docs = [Counter(tokens(p.text)) for p in passages]
    lengths = [sum(d.values()) or 1 for d in docs]
    average = sum(lengths) / len(lengths)
    n = len(passages)
    scored = []
    for passage, doc, length in zip(passages, docs, lengths):
        score = 0.0
        for term in query_terms:
            frequency = doc.get(term, 0)
            if not frequency:
                continue
            containing = sum(1 for d in docs if term in d)
            idf = math.log(1 + (n - containing + 0.5) / (containing + 0.5))
            score += idf * frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average))
        first_line = passage.text.split('\n', 1)[0]
        if score and len(first_line) < 90 and not first_line.endswith('.') and set(tokens(first_line)) & set(query_terms):
            score *= 1.3  # a heading that names the topic
        if _looks_like_boilerplate(passage.text):
            score *= 0.2
        scored.append((score, passage))
    scored.sort(key=lambda pair: (-pair[0], pair[1].index))
    return scored


def select_context(text: str, query: str, budget_chars: int) -> str:
    """The parts of ``text`` most relevant to ``query``, in document order, within ``budget_chars``.

    Short documents are returned whole. When nothing matches the query at all, the opening of the
    document is returned instead (an introduction is the best blind guess).
    """
    text = (text or '').strip()
    if len(text) <= max(budget_chars, 0) or len(text) <= WHOLE_DOCUMENT_CHARS:
        return text[:budget_chars] if budget_chars > 0 else ''
    ranked = rank_passages(split_passages(text), query)
    if not ranked or ranked[0][0] <= 0:
        ranked = [(0.0, p) for p in sorted((p for _, p in ranked), key=lambda p: p.index)]
    chosen: list[Passage] = []
    used = 0
    for score, passage in ranked:
        if chosen and score <= 0 and used >= budget_chars * 0.5:
            break
        room = budget_chars - used
        if room < 200:
            break
        if chosen and _looks_like_boilerplate(passage.text):
            continue  # reference lists only when there is nothing better
        chosen.append(Passage(passage.index, passage.text[:room]))
        used += len(chosen[-1].text) + 7
    chosen.sort(key=lambda p: p.index)
    parts, previous = [], None
    for passage in chosen:
        if previous is not None and passage.index != previous + 1:
            parts.append('[…]')  # a gap: the passages in between were left out
        parts.append(passage.text)
        previous = passage.index
    return '\n\n'.join(parts)
