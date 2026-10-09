import type { GenerationRun, ResearchAgentName, ResearchRunStatus } from '@/api/types'

export type BadgeTone = 'neutral' | 'accent' | 'good' | 'warn' | 'critical' | 'ink'

export function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatMs(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`
}

export function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return (parts[0]?.[0] ?? '?').concat(parts[1]?.[0] ?? '').toUpperCase()
}

export function humanize(value: string) {
  return value.charAt(0) + value.slice(1).toLowerCase().replace(/_/g, ' ')
}

export function average(values: (number | null | undefined)[]) {
  const numbers = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  if (!numbers.length) return null
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length
}

export function groupBy<T>(items: T[], key: (item: T) => string | number) {
  const groups = new Map<string | number, T[]>()
  for (const item of items) {
    const k = key(item)
    const bucket = groups.get(k)
    if (bucket) bucket.push(item)
    else groups.set(k, [item])
  }
  return groups
}

export const researchRunStatusTone: Record<ResearchRunStatus, BadgeTone> = {
  PENDING: 'neutral', PLANNING: 'accent', SEARCHING: 'accent', ANALYZING: 'accent',
  VALIDATING: 'accent', BUILDING_LECTURE: 'accent', REVIEWING_LECTURE: 'accent',
  GENERATING: 'accent', REVIEWING: 'accent',
  COMPLETED: 'good', PARTIAL: 'warn', FAILED: 'critical', CANCELLED: 'neutral',
}

export const researchAgentLabel: Record<ResearchAgentName, string> = {
  BOSS: 'Boss / Orchestrator', WEB_RESEARCH: 'Web Research', ACADEMIC_RESEARCH: 'Academic Research',
  DOCUMENT_RETRIEVAL: 'Document Retrieval', DOCUMENT_ANALYSIS: 'Document Analysis', SOURCE_VALIDATOR: 'Source Validator',
  LECTURE_BUILDER: 'Lecture Builder',
  ASSIGNMENT_GENERATOR: 'Assignment Generator', FINAL_REVIEWER: 'Final Reviewer',
}

export function providerLabel(run: Pick<GenerationRun, 'provider_code'>) {
  const code = run.provider_code?.toLowerCase() ?? 'unknown'
  if (code.includes('openai')) return 'OpenAI'
  if (code.includes('anthropic') || code.includes('claude')) return 'Claude'
  if (code.includes('local') || code.includes('ollama')) return 'Local LLM'
  return run.provider_code ?? 'Unknown'
}
