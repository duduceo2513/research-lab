import { useMemo, useState } from 'react'
import type { ResearchEvent, WorkspaceAgent } from '@/api/types'
import { cn } from '@/lib/utils'
import { formatClock, toolLabel } from './meta'

const RECENT = 5
const MAX_HISTORY = 200

interface Line {
  id: number
  time: string
  tone: 'ok' | 'warn' | 'bad' | 'flow'
  text: string
}

const TONE_CLASS: Record<Line['tone'], string> = { ok: 'text-good', warn: 'text-warn', bad: 'text-critical', flow: 'text-ink-faint' }
const TONE_MARK: Record<Line['tone'], string> = { ok: '✓', warn: '⚠', bad: '✕', flow: '→' }

function failureWord(error: string): string {
  const text = error.toLowerCase()
  if (text.includes('429') || text.includes('rate')) return 'Rate limited'
  if (text.includes('timeout') || text.includes('timed out')) return 'Timed out'
  return 'Failed'
}

const count = (value: unknown): number => (typeof value === 'number' ? value : 0)

// One short line per significant event. Per-document and per-source chatter, "started" markers and
// hand-off decisions that repeat a hand-off are left out (the full journal is in Agent Logs).
function toLine(event: ResearchEvent, names: Record<string, WorkspaceAgent>): Line | null {
  const base = { id: event.id, time: formatClock(event.created_at) }
  const agentName = names[event.agent]?.name ?? event.agent
  switch (event.type) {
    case 'tool_completed': {
      if (event.payload.operation !== 'search') return null
      const tool = toolLabel(String(event.payload.tool))
      if (event.status === 'completed') return { ...base, tone: 'ok', text: `${tool} — ${count(event.payload.result_count)} sources` }
      if (event.status === 'skipped') return null
      return { ...base, tone: 'warn', text: `${tool} — ${failureWord(String(event.payload.error ?? ''))}` }
    }
    case 'agent_handoff': {
      const to = names[String(event.payload.to_agent)]?.name ?? String(event.payload.to_agent)
      return event.payload.revision
        ? { ...base, tone: 'warn', text: `↻ ${to} — revision` }
        : { ...base, tone: 'flow', text: `${to}${event.summary ? ` · ${event.summary}` : ''}` }
    }
    case 'agent_failed':
      return { ...base, tone: 'bad', text: `${agentName} ${event.status === 'cancelled' ? 'stopped' : 'failed'}` }
    case 'agent_decision': {
      if (event.agent !== 'final_reviewer') return null
      const target = String(event.payload.target ?? 'result')
      const score = typeof event.payload.score === 'number' ? ` · ${event.payload.score.toFixed(0)}` : ''
      return event.status === 'approved'
        ? { ...base, tone: 'ok', text: `${target[0].toUpperCase()}${target.slice(1)} approved${score}` }
        : { ...base, tone: 'warn', text: `${target[0].toUpperCase()}${target.slice(1)} needs revision${score}` }
    }
    default:
      return null
  }
}

function dedupe(lines: Line[]): Line[] {
  return lines.filter((line, i) => i === 0 || line.text !== lines[i - 1].text)
}

export function ActivityFeed({ events, agents, className }: { events: ResearchEvent[]; agents: WorkspaceAgent[]; className?: string }) {
  const [all, setAll] = useState(false)
  const names = useMemo(() => Object.fromEntries(agents.map((a) => [a.agent, a])), [agents])
  const lines = useMemo(
    () => dedupe(events.map((e) => toLine(e, names)).filter((l): l is Line => l !== null)).reverse(),
    [events, names],
  )
  const shown = all ? lines.slice(0, MAX_HISTORY) : lines.slice(0, RECENT)

  return (
    <div className={cn('rounded-lg border border-border bg-white', className)}>
      <div className="flex items-center justify-between px-4 py-2.5">
        <h3 className="text-[12px] font-semibold uppercase tracking-wider text-ink-muted">Activity</h3>
        {lines.length > RECENT ? (
          <button type="button" onClick={() => setAll((v) => !v)} className="text-[12px] text-ink-muted hover:text-ink">
            {all ? 'Show less' : `Show all (${lines.length})`}
          </button>
        ) : null}
      </div>
      {shown.length === 0 ? (
        <p className="px-4 pb-4 text-[13px] text-ink-faint">Nothing yet.</p>
      ) : (
        <ul className={cn('divide-y divide-border border-t border-border', all && 'max-h-80 overflow-y-auto')}>
          {shown.map((line) => (
            <li key={line.id} className="flex items-baseline gap-2.5 px-4 py-1.5 text-[13px]">
              <span className={cn('w-3 shrink-0 text-center text-[12px]', TONE_CLASS[line.tone])}>{TONE_MARK[line.tone]}</span>
              <span className="min-w-0 flex-1 truncate text-ink">{line.text}</span>
              <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-ink-faint">{line.time}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
