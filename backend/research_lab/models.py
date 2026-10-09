"""Research Lab — multi-agent research, lecture and assignment-generation module.

This app imports from ``llm`` (LLM calls, cost/token journal) and ``accounts`` (users and roles);
see ``docs/ARCHITECTURE.md``.
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import MetadataMixin, TimestampedModel


class EducationLevel(models.TextChoices):
    SCHOOL = 'SCHOOL', 'School'
    UNDERGRADUATE = 'UNDERGRADUATE', 'Undergraduate'
    MASTER = 'MASTER', 'Master'
    PHD = 'PHD', 'PhD'
    PROFESSIONAL = 'PROFESSIONAL', 'Professional'


class MaterialType(models.TextChoices):
    WEB = 'WEB', 'Web / university materials'
    PAPERS = 'PAPERS', 'Scientific papers'
    BOOKS = 'BOOKS', 'Books'
    DOCUMENTATION = 'DOCUMENTATION', 'Documentation'


class AssignmentType(models.TextChoices):
    THEORETICAL = 'THEORETICAL', 'Theoretical'
    PRACTICAL = 'PRACTICAL', 'Practical'
    MIXED = 'MIXED', 'Mixed'


class Difficulty(models.TextChoices):
    EASY = 'EASY', 'Easy'
    MEDIUM = 'MEDIUM', 'Medium'
    HARD = 'HARD', 'Hard'


class LectureDetailLevel(models.TextChoices):
    LOW = 'LOW', 'Low (concise overview)'
    MEDIUM = 'MEDIUM', 'Medium'
    HIGH = 'HIGH', 'High (in-depth)'


class RunMode(models.TextChoices):
    RESEARCH = 'RESEARCH', 'Full research (search, validation, lecture/assignment)'
    SEARCH = 'SEARCH', 'Materials search (find, download and extract only)'


class LLMMode(models.TextChoices):
    LOCAL = 'LOCAL', 'Local only'
    CLOUD = 'CLOUD', 'Cloud only'
    HYBRID = 'HYBRID', 'Hybrid (local for bulk work, cloud for generation/review)'
    CUSTOM = 'CUSTOM', 'Custom (per-agent configuration)'


class ResearchRunStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PLANNING = 'PLANNING', 'Planning'
    SEARCHING = 'SEARCHING', 'Searching'
    ANALYZING = 'ANALYZING', 'Analyzing'
    VALIDATING = 'VALIDATING', 'Validating'
    BUILDING_LECTURE = 'BUILDING_LECTURE', 'Building lecture'
    REVIEWING_LECTURE = 'REVIEWING_LECTURE', 'Reviewing lecture'
    GENERATING = 'GENERATING', 'Generating'
    REVIEWING = 'REVIEWING', 'Reviewing'
    COMPLETED = 'COMPLETED', 'Completed'
    PARTIAL = 'PARTIAL', 'Partial'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


#: Statuses in which the run is still executing (used by the frontend to decide whether to poll).
ACTIVE_RUN_STATUSES = [
    ResearchRunStatus.PENDING, ResearchRunStatus.PLANNING, ResearchRunStatus.SEARCHING,
    ResearchRunStatus.ANALYZING, ResearchRunStatus.VALIDATING, ResearchRunStatus.BUILDING_LECTURE,
    ResearchRunStatus.REVIEWING_LECTURE, ResearchRunStatus.GENERATING, ResearchRunStatus.REVIEWING,
]
TERMINAL_RUN_STATUSES = [
    ResearchRunStatus.COMPLETED, ResearchRunStatus.PARTIAL, ResearchRunStatus.FAILED,
    ResearchRunStatus.CANCELLED,
]

#: Agent names, shared by AgentExecution.agent and the orchestrator's dispatch table.
AGENT_BOSS = 'BOSS'
AGENT_WEB_RESEARCH = 'WEB_RESEARCH'
AGENT_ACADEMIC_RESEARCH = 'ACADEMIC_RESEARCH'
AGENT_DOCUMENT_RETRIEVAL = 'DOCUMENT_RETRIEVAL'
AGENT_DOCUMENT_ANALYSIS = 'DOCUMENT_ANALYSIS'
AGENT_SOURCE_VALIDATOR = 'SOURCE_VALIDATOR'
AGENT_LECTURE_BUILDER = 'LECTURE_BUILDER'
AGENT_ASSIGNMENT_GENERATOR = 'ASSIGNMENT_GENERATOR'
AGENT_FINAL_REVIEWER = 'FINAL_REVIEWER'


class AgentName(models.TextChoices):
    BOSS = AGENT_BOSS, 'Boss / Orchestrator'
    WEB_RESEARCH = AGENT_WEB_RESEARCH, 'Web Research'
    ACADEMIC_RESEARCH = AGENT_ACADEMIC_RESEARCH, 'Academic Research'
    DOCUMENT_RETRIEVAL = AGENT_DOCUMENT_RETRIEVAL, 'Document Retrieval'
    DOCUMENT_ANALYSIS = AGENT_DOCUMENT_ANALYSIS, 'Document Analysis'
    SOURCE_VALIDATOR = AGENT_SOURCE_VALIDATOR, 'Source Validator'
    LECTURE_BUILDER = AGENT_LECTURE_BUILDER, 'Lecture Builder'
    ASSIGNMENT_GENERATOR = AGENT_ASSIGNMENT_GENERATOR, 'Assignment Generator'
    FINAL_REVIEWER = AGENT_FINAL_REVIEWER, 'Final Reviewer'


class ModuleSettings(TimestampedModel):
    """Single persisted row of admin-editable module settings (``ModuleSettings.load()``) — lets an
    admin flip which search providers run and which LLM tier the module defaults to, at runtime,
    without a redeploy. Deliberately separate from the ``settings.RESEARCH_LAB_*`` Django settings
    (the feature flag and hard budget limits stay env-only); this is just the two choices exposed
    on the admin settings page."""

    default_llm_mode = models.CharField('default LLM mode', max_length=16, choices=LLMMode.choices,
                                        default=LLMMode.LOCAL)
    #: When off, the "Materials search only" mode is unavailable (new searches must be full research runs).
    materials_search_enabled = models.BooleanField('materials search enabled', default=True)
    #: Subset of SourceProvider values to skip even when `.configured()` would allow them to run.
    disabled_providers = models.JSONField('disabled search providers', default=list, blank=True)
    #: Outcome of the latest real call to each provider: ``{code: {"ok": bool, "error": str, "at": iso}}``.
    #: Written by the search agents and the "test connection" endpoint; drives the status badge.
    provider_health = models.JSONField('provider health', default=dict, blank=True)

    class Meta:
        verbose_name = 'module settings'
        verbose_name_plural = 'module settings'

    def __str__(self) -> str:
        return 'Research Lab settings'

    @classmethod
    def load(cls) -> 'ModuleSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def is_provider_enabled(cls, code: str) -> bool:
        return code not in cls.load().disabled_providers


class ResearchRun(TimestampedModel, MetadataMixin):
    """One research task: a topic goes in, a vetted source list (and optionally an Assignment)
    comes out. Owned by the teacher/admin who created it; see ``selectors.runs_for_user``."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='research_runs', verbose_name='user')

    mode = models.CharField('mode', max_length=16, choices=RunMode.choices, default=RunMode.RESEARCH)
    #: Subset of SourceProvider values this run may use (further limited by the global on/off switches
    #: in ModuleSettings). Empty means "every enabled source".
    selected_providers = models.JSONField('selected providers', default=list, blank=True)

    topic = models.CharField('topic', max_length=255)
    description = models.TextField('description', blank=True)
    education_level = models.CharField('education level', max_length=16, choices=EducationLevel.choices,
                                       default=EducationLevel.UNDERGRADUATE)
    language = models.CharField('language', max_length=16, default='en')
    material_types = models.JSONField('material types', default=list, blank=True,
                                      help_text='Subset of MaterialType values.')
    publication_year_from = models.PositiveSmallIntegerField('published after', null=True, blank=True)
    publication_year_to = models.PositiveSmallIntegerField('published before', null=True, blank=True)
    open_access_only = models.BooleanField('open access only', default=False)

    generate_assignment = models.BooleanField('generate assignment', default=True)
    assignment_type = models.CharField('assignment type', max_length=16, choices=AssignmentType.choices,
                                       default=AssignmentType.MIXED)
    difficulty = models.CharField('difficulty', max_length=16, choices=Difficulty.choices,
                                  default=Difficulty.MEDIUM)

    #: Optional, same as generate_assignment — a run can build a lecture, an assignment, both or
    #: neither. Runs before the Assignment Generator (see agents/boss.py): when both are requested,
    #: the assignment is written to match the generated lecture, not just the raw sources.
    generate_lecture = models.BooleanField('generate lecture', default=False)
    lecture_target_duration_minutes = models.PositiveSmallIntegerField('target duration (minutes)', default=60)
    lecture_detail_level = models.CharField('detail level', max_length=16, choices=LectureDetailLevel.choices,
                                            default=LectureDetailLevel.MEDIUM)
    lecture_include_examples = models.BooleanField('include examples', default=True)
    lecture_include_summary = models.BooleanField('include summary', default=True)
    lecture_revision_count = models.PositiveSmallIntegerField('lecture revision count', default=0)

    llm_mode = models.CharField('LLM mode', max_length=16, choices=LLMMode.choices, default=LLMMode.HYBRID)
    #: Only read when llm_mode == CUSTOM: {agent_name: llm_configuration_id}.
    agent_model_overrides = models.JSONField('agent model overrides', default=dict, blank=True)

    status = models.CharField('status', max_length=20, choices=ResearchRunStatus.choices,
                              default=ResearchRunStatus.PENDING, db_index=True)
    current_step = models.CharField('current step', max_length=64, blank=True)
    error_message = models.TextField('error message', blank=True)
    cancel_requested = models.BooleanField('cancellation requested', default=False)
    revision_count = models.PositiveSmallIntegerField('revision count', default=0)

    started_at = models.DateTimeField('started at', null=True, blank=True)
    finished_at = models.DateTimeField('finished at', null=True, blank=True)

    class Meta:
        verbose_name = 'research run'
        verbose_name_plural = 'research runs'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'status'], name='researchrun_user_status_idx')]

    def __str__(self) -> str:
        return f'{self.topic} [{self.status}]'

    def user_can_manage(self, user) -> bool:
        return user.is_superuser or user.role == 'ADMIN' or self.user_id == user.id

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_RUN_STATUSES


class SourceType(models.TextChoices):
    WEB = 'WEB', 'Web page'
    PAPER = 'PAPER', 'Paper'
    BOOK = 'BOOK', 'Book'
    DOCUMENTATION = 'DOCUMENTATION', 'Documentation'
    VIDEO = 'VIDEO', 'Video'
    ENCYCLOPEDIA = 'ENCYCLOPEDIA', 'Encyclopedia'
    OTHER = 'OTHER', 'Other'


class SourceProvider(models.TextChoices):
    BRIGHTDATA = 'BRIGHTDATA', 'Bright Data'
    OPENALEX = 'OPENALEX', 'OpenAlex'
    SEMANTIC_SCHOLAR = 'SEMANTIC_SCHOLAR', 'Semantic Scholar'
    CROSSREF = 'CROSSREF', 'Crossref'
    ARXIV = 'ARXIV', 'arXiv'
    GOOGLE_BOOKS = 'GOOGLE_BOOKS', 'Google Books'
    CORE = 'CORE', 'CORE'
    OPEN_LIBRARY = 'OPEN_LIBRARY', 'Open Library'
    WIKIPEDIA = 'WIKIPEDIA', 'Wikipedia'
    YOUTUBE = 'YOUTUBE', 'YouTube'


class ValidationDecision(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    ACCEPT = 'ACCEPT', 'Accept'
    REJECT = 'REJECT', 'Reject'
    REVIEW = 'REVIEW', 'Needs human review'


class ResearchSource(MetadataMixin):
    """A candidate source found by Web/Academic Research, normalised to one shape regardless of
    provider. Validation scores (by the Source Validator agent) live on this row too — a source is
    validated at most once per run, so a separate table would only add a join for no benefit."""

    run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name='sources', verbose_name='run')

    provider = models.CharField('provider', max_length=20, choices=SourceProvider.choices)
    external_id = models.CharField('external id', max_length=512, blank=True)
    source_type = models.CharField('source type', max_length=16, choices=SourceType.choices,
                                   default=SourceType.OTHER)

    title = models.CharField('title', max_length=1000)
    url = models.URLField('URL', max_length=2000, blank=True)
    authors = models.JSONField('authors', default=list, blank=True)
    publisher = models.CharField('publisher', max_length=500, blank=True)
    published_at = models.DateField('published at', null=True, blank=True)
    doi = models.CharField('DOI', max_length=255, blank=True, db_index=True)
    isbn = models.CharField('ISBN', max_length=32, blank=True, db_index=True)
    abstract = models.TextField('abstract', blank=True)
    citation_count = models.PositiveIntegerField('citation count', null=True, blank=True)
    open_access = models.BooleanField('open access', default=False)
    pdf_url = models.URLField('PDF URL', max_length=2000, blank=True)

    # -- deduplication -----------------------------------------------------------------------
    content_hash = models.CharField('content hash (SHA-256)', max_length=64, blank=True, db_index=True)
    is_duplicate = models.BooleanField('is duplicate', default=False)
    duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='duplicates', verbose_name='duplicate of')

    # -- validator agent output --------------------------------------------------------------
    relevance_score = models.FloatField('relevance', null=True, blank=True)
    authority_score = models.FloatField('authority', null=True, blank=True)
    educational_value_score = models.FloatField('educational value', null=True, blank=True)
    academic_credibility_score = models.FloatField('academic credibility', null=True, blank=True)
    level_match_score = models.FloatField('level match', null=True, blank=True)
    recency_score = models.FloatField('recency', null=True, blank=True)
    completeness_score = models.FloatField('completeness', null=True, blank=True)
    overall_score = models.FloatField('overall score', null=True, blank=True,
                                      validators=[MinValueValidator(0), MaxValueValidator(100)])
    decision = models.CharField('decision', max_length=16, choices=ValidationDecision.choices,
                                default=ValidationDecision.PENDING)
    decision_reasons = models.JSONField('decision reasons', default=list, blank=True)
    validated_at = models.DateTimeField('validated at', null=True, blank=True)

    created_at = models.DateTimeField('created at', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'research source'
        verbose_name_plural = 'research sources'
        ordering = ['run', '-overall_score']
        constraints = [
            models.UniqueConstraint(fields=['run', 'provider', 'external_id'],
                                    condition=~models.Q(external_id=''),
                                    name='uniq_source_run_provider_external_id'),
        ]
        indexes = [
            models.Index(fields=['run', 'decision'], name='source_run_decision_idx'),
            models.Index(fields=['run', 'is_duplicate'], name='source_run_duplicate_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.title[:60]} ({self.provider})'


class DocumentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    FETCHED = 'FETCHED', 'Fetched'
    EXTRACTED = 'EXTRACTED', 'Extracted'
    FAILED = 'FAILED', 'Failed'
    SKIPPED = 'SKIPPED', 'Skipped'


class FetchMethod(models.TextChoices):
    HTTP = 'HTTP', 'Plain HTTP'
    PLAYWRIGHT = 'PLAYWRIGHT', 'Playwright (JS rendering)'
    BRIGHTDATA_BROWSER = 'BRIGHTDATA_BROWSER', 'Bright Data Browser/Unlocker'
    NONE = 'NONE', 'Not fetched (metadata only, e.g. a book record)'


class ResearchDocument(MetadataMixin):
    """The fetched + extracted content of one ``ResearchSource``."""

    source = models.OneToOneField(ResearchSource, on_delete=models.CASCADE, related_name='document',
                                  verbose_name='source')
    status = models.CharField('status', max_length=16, choices=DocumentStatus.choices,
                              default=DocumentStatus.PENDING)
    fetch_method = models.CharField('fetch method', max_length=20, choices=FetchMethod.choices,
                                    default=FetchMethod.NONE)
    content_type = models.CharField('content type', max_length=16, blank=True)  # HTML / PDF / DOCX / PPTX / TXT
    #: The original downloaded file (PDF/PPTX/DOCX/TXT). HTML pages are not stored: only their text is.
    file = models.FileField('file', upload_to='research_lab/%Y/%m/', blank=True, max_length=500)
    file_name = models.CharField('file name', max_length=255, blank=True)
    mime_type = models.CharField('MIME type', max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField('file size (bytes)', default=0)
    text = models.TextField('extracted text', blank=True)
    text_length = models.PositiveIntegerField('text length', default=0)
    fetch_latency_ms = models.PositiveIntegerField('fetch latency (ms)', null=True, blank=True)
    extract_latency_ms = models.PositiveIntegerField('extract latency (ms)', null=True, blank=True)
    error_message = models.TextField('error message', blank=True)
    created_at = models.DateTimeField('created at', auto_now_add=True)
    updated_at = models.DateTimeField('updated at', auto_now=True)

    class Meta:
        verbose_name = 'research document'
        verbose_name_plural = 'research documents'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'Document for source {self.source_id} [{self.status}]'


class ExecutionStatus(models.TextChoices):
    RUNNING = 'RUNNING', 'Running'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    SKIPPED = 'SKIPPED', 'Skipped'


class AgentExecution(MetadataMixin):
    """Append-only journal entry: one step of one agent within one run. ``generation_run`` links to
    the actual LLM call (tokens/latency/cost already tracked there by the ``llm`` app) when this
    step used one."""

    run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name='agent_executions',
                            verbose_name='run')
    agent = models.CharField('agent', max_length=24, choices=AgentName.choices)
    sequence = models.PositiveIntegerField('sequence')
    status = models.CharField('status', max_length=16, choices=ExecutionStatus.choices,
                              default=ExecutionStatus.RUNNING)
    generation_run = models.ForeignKey('llm.GenerationRun', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='research_agent_executions', verbose_name='generation run')
    input_summary = models.JSONField('input summary', default=dict, blank=True)
    output_summary = models.JSONField('output summary', default=dict, blank=True)
    #: Live timeline of what the agent is doing / concluding, appended as it works (see
    #: ``services.journal.note``): ``[{at, kind, text}]``. Read by the frontend's live agent view.
    activity = models.JSONField('activity', default=list, blank=True)
    error_message = models.TextField('error message', blank=True)
    started_at = models.DateTimeField('started at', auto_now_add=True)
    finished_at = models.DateTimeField('finished at', null=True, blank=True)
    latency_ms = models.PositiveIntegerField('latency (ms)', null=True, blank=True)

    class Meta:
        verbose_name = 'agent execution'
        verbose_name_plural = 'agent executions'
        ordering = ['run', 'sequence']
        constraints = [
            models.UniqueConstraint(fields=['run', 'sequence'], name='uniq_agentexecution_run_sequence'),
        ]
        indexes = [models.Index(fields=['run', 'agent'], name='agentexec_run_agent_idx')]

    def __str__(self) -> str:
        return f'#{self.sequence} {self.agent} [{self.status}]'


class ToolExecution(models.Model):
    """Append-only journal entry: one external call (a search provider, a fetch, a browser
    fallback). Kept separate from ``AgentExecution`` because one agent step can make several tool
    calls (e.g. Web Research issues up to ``RESEARCH_LAB_MAX_SEARCH_QUERIES`` Bright Data calls)."""

    run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name='tool_executions',
                            verbose_name='run')
    agent_execution = models.ForeignKey(AgentExecution, on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='tool_executions', verbose_name='agent execution')
    tool = models.CharField('tool', max_length=32)  # provider code or 'http_fetch' / 'playwright' / ...
    status = models.CharField('status', max_length=16, choices=ExecutionStatus.choices)
    request_summary = models.JSONField('request summary', default=dict, blank=True)
    response_summary = models.JSONField('response summary', default=dict, blank=True)
    error_message = models.TextField('error message', blank=True)
    latency_ms = models.PositiveIntegerField('latency (ms)', null=True, blank=True)
    created_at = models.DateTimeField('created at', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'tool execution'
        verbose_name_plural = 'tool executions'
        ordering = ['run', 'created_at']
        indexes = [models.Index(fields=['run', 'tool'], name='toolexec_run_tool_idx')]

    def __str__(self) -> str:
        return f'{self.tool} [{self.status}]'


class ReviewStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    APPROVED = 'APPROVED', 'Approved'
    NEEDS_REVISION = 'NEEDS_REVISION', 'Needs revision'
    REVISION_LIMIT_REACHED = 'REVISION_LIMIT_REACHED', 'Revision limit reached'


class Assignment(MetadataMixin):
    """The generated learning assignment, reviewed independently by the Final Reviewer agent."""

    run = models.OneToOneField(ResearchRun, on_delete=models.CASCADE, related_name='assignment',
                               verbose_name='run')

    title = models.CharField('title', max_length=500)
    objectives = models.JSONField('objectives', default=list, blank=True)
    instructions = models.TextField('instructions', blank=True)
    questions = models.JSONField('questions / tasks', default=list, blank=True)
    grading_criteria = models.TextField('grading criteria', blank=True)
    references = models.JSONField('references', default=list, blank=True)  # [{source_id, citation}]
    answer_key = models.TextField('answer key', blank=True)

    assignment_type = models.CharField('assignment type', max_length=16, choices=AssignmentType.choices)
    difficulty = models.CharField('difficulty', max_length=16, choices=Difficulty.choices)

    review_status = models.CharField('review status', max_length=24, choices=ReviewStatus.choices,
                                     default=ReviewStatus.PENDING)
    review_score = models.FloatField('review score', null=True, blank=True)
    review_issues = models.JSONField('review issues', default=list, blank=True)

    generation_run = models.ForeignKey('llm.GenerationRun', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+', verbose_name='generation run')
    reviewer_generation_run = models.ForeignKey('llm.GenerationRun', on_delete=models.SET_NULL, null=True,
                                                blank=True, related_name='+', verbose_name='reviewer generation run')

    created_at = models.DateTimeField('created at', auto_now_add=True)
    updated_at = models.DateTimeField('updated at', auto_now=True)

    class Meta:
        verbose_name = 'assignment'
        verbose_name_plural = 'assignments'

    def __str__(self) -> str:
        return self.title


class LectureStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    APPROVED = 'APPROVED', 'Approved'
    NEEDS_REVISION = 'NEEDS_REVISION', 'Needs revision'
    REVISION_LIMIT_REACHED = 'REVISION_LIMIT_REACHED', 'Revision limit reached'
    INSUFFICIENT_SOURCES = 'INSUFFICIENT_SOURCES', 'Insufficient sources'


class GeneratedLecture(MetadataMixin):
    """A full lecture built by the Lecture Builder agent from ONLY approved (ACCEPT-decision)
    sources, reviewed independently by the Final Reviewer agent — see ``agents/lecture_builder.py``.

    Versioned rather than overwritten in place (unlike ``Assignment``): a revision creates a new
    row with ``version`` incremented, so earlier drafts are never lost. ``content_json`` is the
    canonical structured form (``{sections: [...], summary, self_check_questions, references,
    missing_topics}``); ``plain_text`` is a deterministic, code-rendered Markdown view of it (see
    ``services/lecture_format.py``) — the export formats (DOCX, and later PPTX) build on top of
    this structured content rather than asking the model to write it twice.
    """

    run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name='lectures', verbose_name='run')
    version = models.PositiveSmallIntegerField('version')

    title = models.CharField('title', max_length=500, blank=True)
    learning_objectives = models.JSONField('learning objectives', default=list, blank=True)
    content_json = models.JSONField('content', default=dict, blank=True)
    plain_text = models.TextField('plain text', blank=True)

    status = models.CharField('status', max_length=24, choices=LectureStatus.choices,
                              default=LectureStatus.DRAFT)
    review_score = models.FloatField('review score', null=True, blank=True)
    review_result = models.JSONField('review result', default=dict, blank=True)  # {decision, issues}

    generation_run = models.ForeignKey('llm.GenerationRun', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+', verbose_name='generation run')
    reviewer_generation_run = models.ForeignKey('llm.GenerationRun', on_delete=models.SET_NULL, null=True,
                                                blank=True, related_name='+', verbose_name='reviewer generation run')

    created_at = models.DateTimeField('created at', auto_now_add=True)

    class Meta:
        verbose_name = 'generated lecture'
        verbose_name_plural = 'generated lectures'
        ordering = ['run', '-version']
        constraints = [
            models.UniqueConstraint(fields=['run', 'version'], name='uniq_lecture_run_version'),
        ]

    def __str__(self) -> str:
        return f'{self.title or "(untitled)"} v{self.version} [{self.status}]'


class ResearchEvent(models.Model):
    """Append-only, persisted stream of what the agents are doing — the single source the live
    "Agent Workspace" is built from. Every event is written here *first* and only then broadcast over
    Channels (``services/events.py``), so a page reload can replay history and the WebSocket never
    holds state that exists nowhere else.

    ``type`` is one of ``services.events.EVENT_TYPES``. ``agent`` is the lower-case agent key (e.g.
    ``academic_research``); ``provider``/``model_name`` describe the model that agent used at that
    moment (``none`` for the deterministic agents that make no LLM call)."""

    run = models.ForeignKey(ResearchRun, on_delete=models.CASCADE, related_name='events', verbose_name='run')
    type = models.CharField('type', max_length=24)
    agent = models.CharField('agent', max_length=24, blank=True)
    provider = models.CharField('provider', max_length=16, blank=True)
    model_name = models.CharField('model', max_length=128, blank=True)
    status = models.CharField('status', max_length=32, blank=True)
    summary = models.CharField('summary', max_length=600, blank=True)
    payload = models.JSONField('payload', default=dict, blank=True)
    created_at = models.DateTimeField('created at', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'research event'
        verbose_name_plural = 'research events'
        ordering = ['id']
        indexes = [models.Index(fields=['run', 'id'], name='researchevent_run_id_idx')]

    def __str__(self) -> str:
        return f'{self.type} {self.agent} {self.summary[:40]}'
