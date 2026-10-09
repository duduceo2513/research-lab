"""In-memory data shapes passed between agents/providers, before anything is persisted.

Plain dataclasses, matching the rest of the codebase's convention (``llm/providers/base.py``,
``rag/services/types.py``) — no Pydantic dependency added just for this.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SourceCandidate:
    """One normalised search result, regardless of which provider found it."""

    provider: str  # a research_lab.models.SourceProvider value
    source_type: str  # a research_lab.models.SourceType value
    title: str
    url: str = ''
    external_id: str = ''
    authors: list[str] = field(default_factory=list)
    publisher: str = ''
    published_at: date | None = None
    abstract: str = ''
    #: Complete text when the API itself returned it (e.g. CORE); stored as the document text, no download needed.
    full_text: str = ''
    doi: str = ''
    isbn: str = ''
    citation_count: int | None = None
    open_access: bool = False
    pdf_url: str = ''
    metadata: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    """Raw bytes fetched for a candidate, before extraction."""

    content: bytes
    content_type: str  # 'HTML' | 'PDF' | 'DOCX'
    final_url: str
    fetch_method: str  # a research_lab.models.FetchMethod value
    latency_ms: int


@dataclass
class ExtractResult:
    text: str
    latency_ms: int


@dataclass
class BossDecision:
    """The orchestrator's structured decision, logged on every step for observability — even
    though the routing itself is a deterministic state machine, not an LLM call (see
    ``agents/boss.py`` for why)."""

    action: str  # 'continue' | 'retry' | 'skip' | 'stop'
    next_agent: str | None
    reason: str
    retry: bool = False


@dataclass
class ValidationResult:
    relevance: float
    authority: float
    educational_value: float
    academic_credibility: float
    level_match: float
    recency: float
    completeness: float
    overall_score: float
    decision: str  # a research_lab.models.ValidationDecision value
    reasons: list[str] = field(default_factory=list)


@dataclass
class AssignmentDraft:
    title: str
    objectives: list[str]
    instructions: str
    questions: list[dict]
    grading_criteria: str
    references: list[dict]
    answer_key: str = ''


@dataclass
class LectureSectionDraft:
    title: str
    content: str
    key_points: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    source_ids: list[int] = field(default_factory=list)


@dataclass
class LectureDraft:
    title: str
    learning_objectives: list[str]
    sections: list[LectureSectionDraft]
    summary: str = ''
    self_check_questions: list[str] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    status: str = 'ok'  # 'ok' | 'insufficient_sources'
    missing_topics: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    decision: str  # 'approved' | 'needs_revision'
    score: float
    issues: list[str] = field(default_factory=list)
