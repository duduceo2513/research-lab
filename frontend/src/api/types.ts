// Mirrors the DRF serializers of the backend. Keep in sync with /api/docs/.

export type UserRole = 'ADMIN' | 'TEACHER' | 'STUDENT'

export interface User {
  id: number
  email: string
  username: string
  first_name: string
  last_name: string
  full_name: string
  role: UserRole
  is_active: boolean
  is_staff: boolean
  date_joined: string
  last_login: string | null
}

export interface TokenPair {
  access: string
  refresh: string
}

export interface LLMProvider {
  id: number
  code: string
  display_name: string
  base_url: string
  secret_env_name: string
  is_active: boolean
}

export interface LLMConfiguration {
  id: number
  provider: number
  provider_code: string
  name: string
  model_name: string
  temperature: number
  max_tokens: number
  context_window: number | null
  supports_streaming: boolean
  is_default: boolean
  is_active: boolean
  metadata: Record<string, unknown>
}

export type GenerationStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'

export interface GenerationRun {
  id: number
  configuration: number
  configuration_name?: string
  provider_code?: string
  question_text: string
  response_text: string
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  latency_ms: number | null
  first_token_latency_ms?: number | null
  tokens_per_second?: number | null
  estimated_cost?: string | number | null
  status: GenerationStatus
  error_message?: string
  created_at: string
}

export type EducationLevel = 'SCHOOL' | 'UNDERGRADUATE' | 'MASTER' | 'PHD' | 'PROFESSIONAL'
export type MaterialType = 'WEB' | 'PAPERS' | 'BOOKS' | 'DOCUMENTATION'
export type ResearchAssignmentType = 'THEORETICAL' | 'PRACTICAL' | 'MIXED'
export type ResearchDifficulty = 'EASY' | 'MEDIUM' | 'HARD'
export type LLMMode = 'LOCAL' | 'CLOUD' | 'HYBRID' | 'CUSTOM'
export type ResearchRunStatus =
  | 'PENDING' | 'PLANNING' | 'SEARCHING' | 'ANALYZING' | 'VALIDATING' | 'BUILDING_LECTURE'
  | 'REVIEWING_LECTURE' | 'GENERATING' | 'REVIEWING' | 'COMPLETED' | 'PARTIAL' | 'FAILED' | 'CANCELLED'
export type LectureDetailLevel = 'LOW' | 'MEDIUM' | 'HIGH'

export type ResearchRunMode = 'RESEARCH' | 'SEARCH'

export interface ResearchRun {
  id: number
  user: number
  user_email: string
  mode: ResearchRunMode
  selected_providers: ResearchSourceProvider[]
  topic: string
  description: string
  education_level: EducationLevel
  language: string
  material_types: MaterialType[]
  publication_year_from: number | null
  publication_year_to: number | null
  open_access_only: boolean
  generate_assignment: boolean
  assignment_type: ResearchAssignmentType
  difficulty: ResearchDifficulty
  generate_lecture: boolean
  lecture_target_duration_minutes: number
  lecture_detail_level: LectureDetailLevel
  lecture_include_examples: boolean
  lecture_include_summary: boolean
  lecture_revision_count: number
  llm_mode: LLMMode
  agent_model_overrides: Record<string, number>
  status: ResearchRunStatus
  current_step: string
  error_message: string
  cancel_requested: boolean
  revision_count: number
  is_active: boolean
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export type ResearchSourceProvider =
  | 'BRIGHTDATA' | 'OPENALEX' | 'SEMANTIC_SCHOLAR' | 'CROSSREF' | 'ARXIV' | 'GOOGLE_BOOKS'
  | 'CORE' | 'OPEN_LIBRARY' | 'WIKIPEDIA' | 'YOUTUBE'
export type ResearchSourceType = 'WEB' | 'PAPER' | 'BOOK' | 'DOCUMENTATION' | 'VIDEO' | 'ENCYCLOPEDIA' | 'OTHER'
export type ResearchDocumentStatus = 'PENDING' | 'FETCHED' | 'EXTRACTED' | 'FAILED' | 'SKIPPED'
export type DocumentFormat = 'PDF' | 'PPTX' | 'DOCX' | 'HTML' | 'TXT' | ''
export type ValidationDecision = 'PENDING' | 'ACCEPT' | 'REJECT' | 'REVIEW'

export interface ResearchSource {
  id: number
  run: number
  provider: ResearchSourceProvider
  source_type: ResearchSourceType
  title: string
  url: string
  authors: string[]
  publisher: string
  published_at: string | null
  doi: string
  isbn: string
  abstract: string
  citation_count: number | null
  open_access: boolean
  pdf_url: string
  is_duplicate: boolean
  duplicate_of: number | null
  relevance_score: number | null
  authority_score: number | null
  educational_value_score: number | null
  academic_credibility_score: number | null
  level_match_score: number | null
  recency_score: number | null
  completeness_score: number | null
  overall_score: number | null
  decision: ValidationDecision
  decision_reasons: string[]
  validated_at: string | null
  text_preview: string
  created_at: string
  document_status: ResearchDocumentStatus
  document_format: DocumentFormat
  has_file: boolean
  file_name: string
  file_size: number
  text_length: number
  document_error: string
}

export interface ResearchSourceDetail extends ResearchSource {
  text: string
  /** `document`: extracted from a file/page; `description`: only what the API returned. */
  text_origin: 'document' | 'description' | 'none'
  metadata: Record<string, unknown>
  fetch_method: string
}

export interface ResearchContext {
  run: number
  topic: string
  materials: number
  characters: number
  text: string
}

export type ResearchAgentName =
  | 'BOSS' | 'WEB_RESEARCH' | 'ACADEMIC_RESEARCH' | 'DOCUMENT_RETRIEVAL' | 'DOCUMENT_ANALYSIS' | 'SOURCE_VALIDATOR'
  | 'LECTURE_BUILDER' | 'ASSIGNMENT_GENERATOR' | 'FINAL_REVIEWER'
export type ExecutionStatus = 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED'

export interface AgentExecution {
  id: number
  run: number
  agent: ResearchAgentName
  sequence: number
  status: ExecutionStatus
  generation_run: number | null
  generation_run_tokens: number | null
  generation_run_cost: string | null
  input_summary: Record<string, unknown>
  output_summary: Record<string, unknown>
  error_message: string
  started_at: string
  finished_at: string | null
  latency_ms: number | null
}

export interface ToolExecution {
  id: number
  run: number
  agent_execution: number | null
  tool: string
  status: ExecutionStatus
  request_summary: Record<string, unknown>
  response_summary: Record<string, unknown>
  error_message: string
  latency_ms: number | null
  created_at: string
}

export type AssignmentReviewStatus = 'PENDING' | 'APPROVED' | 'NEEDS_REVISION' | 'REVISION_LIMIT_REACHED'

export interface ResearchAssignmentQuestion {
  type: string
  prompt: string
  points?: number
}

export interface Assignment {
  id: number
  run: number
  title: string
  objectives: string[]
  instructions: string
  questions: ResearchAssignmentQuestion[]
  grading_criteria: string
  references: { source_id: number; citation: string }[]
  answer_key: string
  assignment_type: ResearchAssignmentType
  difficulty: ResearchDifficulty
  review_status: AssignmentReviewStatus
  review_score: number | null
  review_issues: string[]
  generation_run: number | null
  reviewer_generation_run: number | null
  created_at: string
  updated_at: string
}

export type GeneratedLectureStatus = 'DRAFT' | 'APPROVED' | 'NEEDS_REVISION' | 'REVISION_LIMIT_REACHED' | 'INSUFFICIENT_SOURCES'

export interface LectureSection {
  title: string
  content: string
  key_points: string[]
  examples: string[]
  source_ids: number[]
}

export interface LectureContent {
  sections: LectureSection[]
  summary: string
  self_check_questions: string[]
  references: { source_id?: number; citation: string }[]
  missing_topics: string[]
}

export interface GeneratedLecture {
  id: number
  run: number
  version: number
  title: string
  learning_objectives: string[]
  content_json: LectureContent
  plain_text: string
  status: GeneratedLectureStatus
  review_score: number | null
  review_result: { decision?: string; issues?: string[] }
  generation_run: number | null
  reviewer_generation_run: number | null
  created_at: string
}

export type ProviderState = 'active' | 'disabled' | 'missing_key' | 'error'

export interface ResearchLabProviderStatus {
  code: string
  label: string
  configured: boolean
  enabled: boolean
  state: ProviderState
  missing_settings: string[]
  last_error: string
  last_checked: string | null
  metadata_only: boolean
}

export interface ResearchLabConfig {
  enabled: boolean
  education_levels: EducationLevel[]
  material_types: MaterialType[]
  max_search_queries: number
  max_results_per_query: number
  max_documents: number
  max_revision_cycles: number
  default_llm_mode: LLMMode
  materials_search_enabled: boolean
  providers: ResearchLabProviderStatus[]
}

export interface ResearchLabSettings {
  default_llm_mode: LLMMode
  materials_search_enabled: boolean
  disabled_providers: string[]
  providers: ResearchLabProviderStatus[]
  updated_at: string
}

export interface ResearchMetrics {
  sources_found: number
  unique_sources: number
  documents_analyzed: number
  accepted: number
  rejected: number
  needs_review: number
  agent_calls_by_agent: Record<string, number>
  agent_calls_total: number
  max_agent_load_pct: number
  tool_calls_total: number
  execution_time_seconds: number | null
  total_tokens: number | null
  estimated_cost: string | null
  revision_count: number
  status: ResearchRunStatus
}

// -- Research Lab: Agent Workspace (research_lab/services/events.py, services/workspace.py) -----------
export type WorkspaceEventType =
  | 'run_status' | 'agent_started' | 'agent_status' | 'agent_completed' | 'agent_failed' | 'agent_note'
  | 'agent_progress' | 'tool_started' | 'tool_completed' | 'agent_decision' | 'agent_handoff'

export interface ResearchEvent {
  id: number
  run: number
  type: WorkspaceEventType
  agent: string
  provider: string
  model_name: string
  status: string
  summary: string
  payload: Record<string, unknown>
  created_at: string
}

// Lower-case, as sent by the backend. `disabled`/`not_run` are server-computed for agents a run never uses.
export type AgentStatus =
  | 'waiting' | 'queued' | 'working' | 'using_tool' | 'reviewing' | 'completed' | 'retrying'
  | 'warning' | 'failed' | 'cancelled' | 'skipped' | 'disabled' | 'not_run'

// local = Ollama-style local model, cloud = Claude/OpenAI API, system = deterministic service (no model)
export type ProviderKind = 'local' | 'cloud' | 'system' | 'unknown'

export interface ProgressStep {
  id: string
  label: string
  status: 'done' | 'active' | 'pending' | 'failed' | 'skipped'
  detail?: string
}

export interface WorkspaceAgent {
  agent: string
  name: string
  order: number
  enabled: boolean
  disabled_reason: string
  status: AgentStatus
  status_summary: string
  provider: string
  provider_kind: ProviderKind
  model_name: string
  current_action: string
  current_tool: string
  decision: { decision: string; summary: string; reason: string; next_action: string; source_id: number | null } | null
  progress: ({ steps: ProgressStep[] } & Record<string, unknown>) | null
  executions: number
  result: string
  next_step: string
  last_event_pk: number
  tool_calls: number
  llm_calls: number
  tokens: number
  cost: number
  duration_ms: number
  started_at: string | null
}

export interface WorkspaceHandoff {
  id: number
  from: string
  to: string
  summary: string
  created_at: string
  revision: boolean
  target: string
  version: number | null
}

export interface WorkspaceReview {
  decision: string
  score: number | null
  issues: string[]
  summary: string
}

export interface WorkspaceMission {
  agent: string
  agent_name: string
  title: string
  done: number | null
  total: number | null
  percent: number | null
  current_item: string
  finished: boolean
}

export interface WorkspaceState {
  run: {
    id: number; topic: string; status: ResearchRunStatus; current_step: string; is_active: boolean
    llm_mode: string; revision_count: number; lecture_revision_count: number
    started_at: string | null; finished_at: string | null; error_message: string
  }
  agents: WorkspaceAgent[]
  research_state: {
    topic: string; education_level: string; status: ResearchRunStatus; current_step: string
    sources_discovered: number; sources_unique: number; sources_analyzed: number
    sources_accepted: number; sources_rejected: number; sources_need_review: number
    lecture: { status: string; version?: number; score?: number | null; title?: string; sections?: number }
    assignment: { status: string; version?: number; score?: number | null; title?: string; questions?: number }
  }
  metrics: {
    sources: number; analyzed: number; accepted: number; agent_runs: number; tool_calls: number; llm_calls: number
    local_calls: number; claude_calls: number; tokens: number; cloud_cost: number
    elapsed_seconds: number | null
    // Share of all LLM + tool calls (the brief's definition); `time_pct` is the share of working time.
    load: { agent: string; pct: number; calls: number; llm_calls: number; tool_calls: number; time_pct: number }[]
    max_agent_load_pct: number; load_limit_pct: number; load_ok: boolean
  }
  mission: WorkspaceMission
  handoffs: WorkspaceHandoff[]
  reviews: Record<string, WorkspaceReview>
  last_event_id: number
}
