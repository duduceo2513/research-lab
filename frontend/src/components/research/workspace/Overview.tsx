import { ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useResearchWorkspace, type WorkspaceSocketStatus } from '@/api/useResearchWorkspace'
import type { ResearchRun, WorkspaceState } from '@/api/types'
import { ErrorNotice, Loading } from '@/components/ui/Feedback'
import { cn } from '@/lib/utils'
import { ActivityFeed } from './ActivityFeed'
import { AgentGraph } from './AgentGraph'
import { AgentPeek } from './AgentPeek'
import { formatCost, formatElapsed } from './meta'

const MATERIAL_LABEL: Record<string, string> = { WEB: 'Web', PAPERS: 'Papers', BOOKS: 'Books', DOCUMENTATION: 'Docs' }
const MODE_LABEL: Record<string, string> = { LOCAL: 'Local', CLOUD: 'Cloud', HYBRID: 'Hybrid', CUSTOM: 'Custom' }
const LEVEL_LABEL: Record<string, string> = {
  SCHOOL: 'School', UNDERGRADUATE: 'Undergraduate', MASTER: 'Master', PHD: 'PhD', PROFESSIONAL: 'Professional',
}

// "Undergraduate · Web + Papers · Cloud · 15 min"
export function requestLine(run: ResearchRun): string {
  const materials = run.material_types.length ? run.material_types.map((t) => MATERIAL_LABEL[t] ?? t).join(' + ') : 'All materials'
  return [
    LEVEL_LABEL[run.education_level] ?? run.education_level, materials, MODE_LABEL[run.llm_mode] ?? run.llm_mode,
    run.generate_lecture ? `${run.lecture_target_duration_minutes} min` : '',
  ].filter(Boolean).join(' · ')
}

const SOCKET_LABEL: Record<WorkspaceSocketStatus, string> = { connecting: 'Connecting', open: 'Live', reconnecting: 'Reconnecting', closed: 'Offline' }

const LECTURE_SHORT: Record<string, string> = {
  APPROVED: 'Approved', DRAFT: 'Draft', NEEDS_REVISION: 'Needs revision', REVISION_LIMIT_REACHED: 'Revision limit reached',
  INSUFFICIENT_SOURCES: 'Not enough sources', WAITING: 'Waiting',
}
const ASSIGNMENT_SHORT: Record<string, string> = {
  APPROVED: 'Approved', PENDING: 'Draft', NEEDS_REVISION: 'Needs revision', REVISION_LIMIT_REACHED: 'Revision limit reached',
  WAITING: 'Waiting',
}

function resultText(item: { status: string; version?: number; score?: number | null }, labels: Record<string, string>): string {
  const parts = [labels[item.status] ?? item.status]
  if (item.version && item.status !== 'WAITING') parts.push(`v${item.version}`)
  if (item.score !== null && item.score !== undefined) parts.push(item.score.toFixed(0))
  return parts.join(' · ')
}

// One compact line per deliverable. The short status is always visible; the explanation is one click away.
function ResultRow({ label, status, detail }: { label: string; status: string; detail: string[] }) {
  const [open, setOpen] = useState(false)
  const bad = /not enough|revision|limit/i.test(status)
  const good = /^approved/i.test(status)
  return (
    <div className="border-t border-border first:border-t-0">
      <button
        type="button"
        onClick={() => detail.length && setOpen((v) => !v)}
        className={cn('flex w-full items-center gap-2 px-4 py-2 text-left text-[13px]', detail.length ? 'hover:bg-surface' : 'cursor-default')}
      >
        <span className="w-20 shrink-0 text-ink-muted">{label}</span>
        <span className={cn('min-w-0 flex-1 truncate', good ? 'text-good' : bad ? 'text-warn' : 'text-ink')}>{status}</span>
        {detail.length ? <ChevronDown className={cn('h-3.5 w-3.5 text-ink-faint transition-transform', open && 'rotate-180')} /> : null}
      </button>
      {open ? (
        <ul className="space-y-1 px-4 pb-3 pl-[6.5rem] text-[12.5px] text-ink-muted">
          {detail.map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      ) : null}
    </div>
  )
}

function detailsFor(state: WorkspaceState, target: 'lecture' | 'assignment'): string[] {
  const fromErrors = state.run.error_message.split('; ').filter((part) => part.toLowerCase().includes(target))
  const issues = state.reviews[target]?.issues ?? []
  return [...fromErrors, ...issues]
}

export function Progress({ state, elapsed }: { state: WorkspaceState; elapsed: number | null }) {
  const { mission, metrics, research_state: rs } = state
  const hasBar = mission.percent !== null && mission.total !== null
  return (
    <div className="rounded-lg border border-border bg-white">
      <div className="px-4 pb-3 pt-2.5">
        <div className="flex items-baseline justify-between">
          <h3 className="text-[12px] font-semibold uppercase tracking-wider text-ink-muted">Progress</h3>
          <span className="font-mono text-[11px] tabular-nums text-ink-faint">{formatElapsed(elapsed)}</span>
        </div>
        <p className="mt-1.5 flex items-baseline justify-between text-[14px] text-ink">
          <span className="font-medium">{mission.title}</span>
          {hasBar ? <span className="text-[12px] tabular-nums text-ink-muted">{mission.done} / {mission.total}</span> : null}
        </p>
        {hasBar ? (
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-border">
            <div className="h-full rounded-full bg-ink transition-all duration-500" style={{ width: `${mission.percent}%` }} />
          </div>
        ) : null}
        {mission.current_item ? <p className="mt-1.5 truncate text-[12px] text-ink-faint">{mission.current_item}</p> : null}
        <p className="mt-2.5 text-[12px] text-ink-muted">
          {metrics.sources} sources · {rs.sources_accepted} accepted · {metrics.llm_calls} LLM · {metrics.tool_calls} tools
          {metrics.cloud_cost > 0 ? ` · ${formatCost(metrics.cloud_cost)}` : ''}
        </p>
      </div>
      {rs.lecture.status !== 'NOT_REQUESTED' ? (
        <ResultRow label="Lecture" status={resultText(rs.lecture, LECTURE_SHORT)} detail={detailsFor(state, 'lecture')} />
      ) : null}
      {rs.assignment.status !== 'NOT_REQUESTED' ? (
        <ResultRow label="Assignment" status={resultText(rs.assignment, ASSIGNMENT_SHORT)} detail={detailsFor(state, 'assignment')} />
      ) : null}
    </div>
  )
}

// The whole run on one screen: the compact agent graph, a short progress card and the last few events.
// Facts only: a server-computed snapshot plus the persisted event stream (WebSocket for live updates).
export function Overview({ run }: { run: ResearchRun }) {
  const { workspace, events, socketStatus, activeEdges } = useResearchWorkspace(run.id, run.is_active)
  const [selected, setSelected] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!run.is_active) return undefined
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [run.is_active])

  const state = workspace.data
  if (workspace.isPending) return <Loading />
  if (workspace.error || !state) return <ErrorNotice error={workspace.error} />

  const agent = state.agents.find((a) => a.agent === selected) ?? null
  const started = state.run.started_at ? Date.parse(state.run.started_at) : null
  const elapsed = run.is_active && started ? (now - started) / 1000 : state.metrics.elapsed_seconds

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 text-[13px]">
        <p className="truncate text-ink-muted">{requestLine(run)}</p>
        {run.is_active ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[12px] text-ink-muted">
            <span className={cn('h-1.5 w-1.5 rounded-full', socketStatus === 'open' ? 'animate-pulse bg-good' : 'bg-warn')} />
            {SOCKET_LABEL[socketStatus]}
          </span>
        ) : null}
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-white p-3">
        <ReactFlowProvider>
          <AgentGraph state={state} selected={selected ?? ''} onSelect={(key) => setSelected((cur) => (cur === key ? null : key))} activeEdges={activeEdges} />
        </ReactFlowProvider>
      </div>

      {agent ? <AgentPeek agent={agent} events={events} onClose={() => setSelected(null)} /> : null}

      <div className="grid items-start gap-4 md:grid-cols-2">
        <Progress state={state} elapsed={elapsed} />
        <ActivityFeed events={events} agents={state.agents} />
      </div>
    </div>
  )
}
