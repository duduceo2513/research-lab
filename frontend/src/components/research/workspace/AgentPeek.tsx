import { X } from 'lucide-react'
import { useMemo } from 'react'
import type { ResearchEvent, WorkspaceAgent } from '@/api/types'
import { AGENT_TASK, StatusGlyph, formatClock, shortModel, shortStatus, toolLabel } from './meta'

const RECENT_ACTIONS = 5

function actionText(event: ResearchEvent): string | null {
  switch (event.type) {
    case 'tool_completed':
      return event.payload.operation === 'search'
        ? `${toolLabel(String(event.payload.tool))} — ${event.status === 'completed' ? `${event.payload.result_count ?? 0} sources` : event.status}`
        : null
    case 'agent_handoff': return `Handed over: ${event.summary}`
    case 'agent_decision': return event.payload.source_id ? null : event.summary
    case 'agent_note': return event.payload.kind === 'info' ? null : event.summary
    case 'agent_started': return 'Started'
    case 'agent_completed': return event.status === 'warning' ? 'Finished with warnings' : 'Finished'
    case 'agent_failed': return event.status === 'cancelled' ? 'Stopped' : 'Failed'
    default: return null
  }
}

// Closed by default; opens when an agent card is clicked. Only the essentials: task, status, model,
// last result and the last few actions. The complete record is in Agent Logs.
export function AgentPeek({ agent, events, onClose }: { agent: WorkspaceAgent; events: ResearchEvent[]; onClose: () => void }) {
  const actions = useMemo(() => {
    const lines: { id: number; time: string; text: string }[] = []
    for (const event of events) {
      if (event.agent !== agent.agent) continue
      const text = actionText(event)
      if (text && text !== lines[lines.length - 1]?.text) lines.push({ id: event.id, time: formatClock(event.created_at), text: text.slice(0, 110) })
    }
    return lines.slice(-RECENT_ACTIONS).reverse()
  }, [events, agent.agent])

  return (
    <div className="rounded-lg border border-border bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2 text-[13px]">
          <StatusGlyph status={agent.status} compact />
          <span className="font-semibold text-ink">{agent.name}</span>
          <span className="truncate text-ink-muted">{shortStatus(agent.status)} · {shortModel(agent)}</span>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="text-ink-faint hover:text-ink">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid gap-x-8 gap-y-3 px-4 py-3 text-[13px] sm:grid-cols-2">
        <div className="space-y-2">
          <div>
            <p className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">Task</p>
            <p className="text-ink">{AGENT_TASK[agent.agent]}</p>
            {agent.current_action && ['working', 'using_tool', 'reviewing'].includes(agent.status) ? (
              <p className="mt-0.5 truncate text-ink-muted">{agent.current_action}</p>
            ) : null}
          </div>
          <div>
            <p className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">Last result</p>
            <p className="text-ink">{agent.result || (agent.enabled ? '—' : agent.disabled_reason)}</p>
          </div>
        </div>
        <div>
          <p className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">Recent actions</p>
          {actions.length === 0 ? <p className="text-ink-faint">None yet</p> : (
            <ul className="mt-0.5 space-y-0.5">
              {actions.map((action) => (
                <li key={action.id} className="flex gap-2">
                  <span className="shrink-0 font-mono text-[10.5px] tabular-nums leading-5 text-ink-faint">{action.time}</span>
                  <span className="min-w-0 truncate text-ink-muted">{action.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
