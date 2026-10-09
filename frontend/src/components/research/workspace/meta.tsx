import { Ban, Check, Clock, RotateCcw, Wrench, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { AgentStatus, ProviderKind, WorkspaceAgent } from '@/api/types'
import { cn } from '@/lib/utils'

// The graph and every panel read statuses, providers and models straight from the backend; this file
// only decides how a given backend value is drawn.

type Tone = 'idle' | 'queued' | 'active' | 'good' | 'warn' | 'bad' | 'off'

interface StatusMeta {
  label: string
  tone: Tone
  /** WORKING-like states get a pulse so it is obvious who is busy right now. */
  live: boolean
}

export const STATUS_META: Record<AgentStatus, StatusMeta> = {
  waiting: { label: 'WAITING', tone: 'idle', live: false },
  queued: { label: 'QUEUED', tone: 'queued', live: false },
  working: { label: 'WORKING', tone: 'active', live: true },
  using_tool: { label: 'USING TOOL', tone: 'active', live: true },
  reviewing: { label: 'REVIEWING', tone: 'active', live: true },
  completed: { label: 'COMPLETED', tone: 'good', live: false },
  retrying: { label: 'RETRYING', tone: 'warn', live: true },
  // Older runs may still carry this status; a finished agent is simply done, never an orange warning.
  warning: { label: 'COMPLETED', tone: 'good', live: false },
  failed: { label: 'FAILED', tone: 'bad', live: false },
  cancelled: { label: 'CANCELLED', tone: 'off', live: false },
  skipped: { label: 'SKIPPED', tone: 'off', live: false },
  disabled: { label: 'NOT USED', tone: 'off', live: false },
  not_run: { label: 'DID NOT RUN', tone: 'off', live: false },
}

export function statusMeta(status: string): StatusMeta {
  return STATUS_META[status as AgentStatus] ?? { label: status.toUpperCase(), tone: 'idle', live: false }
}

export const TONE_TEXT: Record<Tone, string> = {
  idle: 'text-ink-faint', queued: 'text-sky-700', active: 'text-accent', good: 'text-good',
  warn: 'text-warn', bad: 'text-critical', off: 'text-ink-faint',
}

export const TONE_BG: Record<Tone, string> = {
  idle: 'bg-ink-faint', queued: 'bg-sky-600', active: 'bg-accent', good: 'bg-good',
  warn: 'bg-warn', bad: 'bg-critical', off: 'bg-ink-faint',
}

const TONE_RING: Record<Tone, string> = {
  idle: 'border-border', queued: 'border-sky-300', active: 'border-accent', good: 'border-good/50',
  warn: 'border-warn/60', bad: 'border-critical/60', off: 'border-border',
}

export const nodeBorder = (status: string) => TONE_RING[statusMeta(status).tone]

export function StatusGlyph({ status, className, compact = false }: { status: string; className?: string; compact?: boolean }) {
  const meta = statusMeta(status)
  const size = compact ? 'h-3 w-3' : 'h-4 w-4'
  const glyph = compact ? 'h-2 w-2' : 'h-2.5 w-2.5'
  const icon: ReactNode =
    status === 'completed' || status === 'warning' ? <Check className={glyph} strokeWidth={3.5} />
    : status === 'failed' ? <X className={glyph} strokeWidth={3.5} />
    : status === 'warning' ? <span className={cn('font-bold leading-none', compact ? 'text-[8px]' : 'text-[10px]')}>!</span>
    : status === 'using_tool' ? <Wrench className={glyph} strokeWidth={3} />
    : status === 'retrying' ? <RotateCcw className={glyph} strokeWidth={3} />
    : status === 'queued' ? <Clock className={glyph} strokeWidth={3} />
    : status === 'cancelled' || status === 'skipped' || status === 'disabled' || status === 'not_run'
      ? <Ban className={glyph} strokeWidth={3} />
    : null
  return (
    <span className={cn('relative inline-flex shrink-0 items-center justify-center', size, className)}>
      {meta.live ? <span className={cn('absolute inset-0 animate-ping rounded-full opacity-40', TONE_BG[meta.tone])} /> : null}
      <span className={cn(
        'relative inline-flex items-center justify-center rounded-full', size,
        icon ? cn(TONE_BG[meta.tone], 'text-white') : cn('border-2 bg-white', TONE_RING[meta.tone]),
        meta.live && !icon && cn(TONE_BG[meta.tone], 'border-transparent animate-pulse'),
      )}>
        {icon}
      </span>
    </span>
  )
}

export function StatusLabel({ status }: { status: string }) {
  const meta = statusMeta(status)
  return <span className={cn('text-[11px] font-semibold tracking-wide', TONE_TEXT[meta.tone])}>{meta.label}</span>
}

/** LOCAL (Ollama) / CLOUD (Claude API) for model-backed agents; SYSTEM for deterministic services. */
export function providerBadge(provider: string, kind: ProviderKind): { label: string; className: string } {
  if (kind === 'system') return { label: 'SYSTEM', className: 'border-slate-300 bg-slate-100 text-slate-600' }
  if (kind === 'local') return { label: 'LOCAL', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' }
  if (kind === 'cloud') return { label: 'CLOUD', className: 'border-amber-300 bg-amber-50 text-amber-800' }
  return { label: provider.toUpperCase() || '?', className: 'border-border bg-surface text-ink-muted' }
}

/** Human name of the engine behind a provider badge. */
export function engineLabel(agent: Pick<WorkspaceAgent, 'provider' | 'provider_kind'>): string {
  if (agent.provider_kind === 'system') return 'Deterministic service'
  if (agent.provider_kind === 'local') return 'Ollama (local model)'
  if (agent.provider === 'anthropic') return 'Claude API'
  if (agent.provider === 'openai') return 'OpenAI API'
  return agent.provider
}

export function ProviderBadge({ agent, className }: { agent: Pick<WorkspaceAgent, 'provider' | 'provider_kind'>; className?: string }) {
  const badge = providerBadge(agent.provider, agent.provider_kind)
  return (
    <span className={cn('inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold tracking-wider', badge.className, className)}>
      {badge.label}
    </span>
  )
}

// -- small formatters ------------------------------------------------------------------------------
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

export const formatTokens = (n: number) => n.toLocaleString('en-US').replace(/,/g, ' ')

export const formatCost = (n: number) => (n > 0 && n < 0.01 ? '<$0.01' : `$${n.toFixed(2)}`)

export const formatClock = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-GB', { hour12: false })

export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '00:00'
  const s = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

// -- static wording ----------------------------------------------------------------------------------
/** What each agent is responsible for: its standing mission, shown on its card. */
export const AGENT_TASK: Record<string, string> = {
  boss: 'Coordinating the research',
  web_research: 'Searching web and university materials',
  academic_research: 'Searching academic materials',
  document_retrieval: 'Downloading the original documents',
  document_analysis: 'Extracting and de-duplicating text',
  source_validator: 'Validating source quality',
  lecture_builder: 'Building the lecture',
  assignment_generator: 'Writing the assignment',
  final_reviewer: 'Independently reviewing the results',
}

export const AGENT_ROLE: Record<string, string> = {
  boss: 'Orchestrator', web_research: 'Web search', academic_research: 'Scholarly search',
  document_retrieval: 'Document download', document_analysis: 'Text extraction', source_validator: 'Quality control',
  lecture_builder: 'Content author', assignment_generator: 'Content author', final_reviewer: 'Independent reviewer',
}

const TOOL_LABELS: Record<string, string> = {
  OPENALEX: 'OpenAlex', SEMANTIC_SCHOLAR: 'Semantic Scholar', CROSSREF: 'Crossref', ARXIV: 'arXiv',
  GOOGLE_BOOKS: 'Google Books', BRIGHTDATA: 'Bright Data', HTTP: 'Document download', PLAYWRIGHT: 'Browser download',
  BRIGHTDATA_BROWSER: 'Bright Data browser', Extractor: 'Document parser',
}

export const toolLabel = (code: string) => TOOL_LABELS[code] ?? code

// -- short wording for compact cards -----------------------------------------------------------------
const SHORT_STATUS: Record<AgentStatus, string> = {
  waiting: 'Waiting', queued: 'Queued', working: 'Working', using_tool: 'Tool', reviewing: 'Reviewing',
  completed: 'Done', retrying: 'Retry', warning: 'Done', failed: 'Failed', cancelled: 'Stopped',
  skipped: 'Skipped', disabled: 'Off', not_run: 'Not run',
}

export const shortStatus = (status: string) => SHORT_STATUS[status as AgentStatus] ?? status

/** Claude / OpenAI by name for cloud, the model tag for a local model, System for deterministic services. */
export function shortModel(agent: Pick<WorkspaceAgent, 'provider' | 'provider_kind' | 'model_name'>): string {
  if (agent.provider_kind === 'system') return 'System'
  if (agent.provider_kind === 'cloud') return agent.provider === 'anthropic' ? 'Claude' : agent.provider === 'openai' ? 'OpenAI' : 'Cloud'
  return agent.model_name || 'Local'
}
