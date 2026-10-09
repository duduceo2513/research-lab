import type { ReactNode } from 'react'
import type { WorkspaceAgent, WorkspaceState } from '@/api/types'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { humanize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ProviderBadge, formatCost, formatElapsed } from './meta'

function ModelRow({ agent }: { agent: WorkspaceAgent }) {
  return (
    <li className={cn('flex items-center gap-2 py-1.5 text-[12.5px]', !agent.enabled && 'opacity-50')}>
      <span className="min-w-0 flex-1 truncate text-ink">{agent.name}</span>
      {agent.provider_kind === 'system' ? null : (
        <span className="hidden max-w-[140px] truncate text-[11px] text-ink-faint sm:inline" title={agent.model_name}>{agent.model_name}</span>
      )}
      <ProviderBadge agent={agent} className="w-[58px] justify-center" />
    </li>
  )
}

// Who runs on what. The provider and model are the ones the backend actually resolved for this run
// (so a CUSTOM run shows its real per-agent configuration).
export function ModelDistribution({ state }: { state: WorkspaceState }) {
  return (
    <Card>
      <CardHeader title={<span className="tracking-wide">MODELS</span>} description={`AI mode: ${humanize(state.run.llm_mode)}`} />
      <CardBody className="py-2">
        <ul className="divide-y divide-border">
          {state.agents.map((agent) => <ModelRow key={agent.agent} agent={agent} />)}
        </ul>
      </CardBody>
    </Card>
  )
}

export function LoadDistribution({ state }: { state: WorkspaceState }) {
  const { metrics, agents } = state
  const names = Object.fromEntries(agents.map((a) => [a.agent, a]))
  const rows = metrics.load.filter((item) => names[item.agent]?.enabled)
  return (
    <Card>
      <CardHeader
        title={<span className="tracking-wide">AGENT LOAD</span>}
        description="Share of all LLM + tool calls"
        action={
          <span className={cn('rounded-sm border px-1.5 py-0.5 text-[11px] font-bold', metrics.load_ok ? 'border-good/30 bg-good-soft text-good' : 'border-critical/30 bg-critical-soft text-critical')}>
            {metrics.load_ok ? 'PASS' : 'FAIL'}
          </span>
        }
      />
      <CardBody className="space-y-2 py-3">
        {rows.map((item) => (
          <div key={item.agent} className="text-[12px]">
            <div className="flex justify-between">
              <span className="text-ink-muted">{names[item.agent]?.name}</span>
              <span className="tabular-nums text-ink">
                <span className="mr-2 text-ink-faint">{item.llm_calls} LLM · {item.tool_calls} tools</span>{item.pct.toFixed(0)}%
              </span>
            </div>
            <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-border">
              <div
                className={cn('h-full rounded-full', item.pct > metrics.load_limit_pct ? 'bg-critical' : 'bg-ink/70')}
                style={{ width: `${Math.min(100, item.pct)}%` }}
              />
            </div>
          </div>
        ))}
        <div className="border-t border-border pt-2 text-[12px] text-ink-muted">
          Max agent load <b className="text-ink">{metrics.max_agent_load_pct.toFixed(0)}%</b> · requirement ≤ {metrics.load_limit_pct.toFixed(0)}%
        </div>
      </CardBody>
    </Card>
  )
}

function Metric({ label, value, accent }: { label: string; value: ReactNode; accent?: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</span>
      <span className={cn('text-[13px] font-semibold tabular-nums', accent ? 'text-accent' : 'text-ink')}>{value}</span>
    </div>
  )
}

export function MetricsBar({ state, elapsedSeconds }: { state: WorkspaceState; elapsedSeconds: number | null }) {
  const m = state.metrics
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-border bg-white px-5 py-3">
      <Metric label="Sources" value={m.sources} />
      <Metric label="Analyzed" value={m.analyzed} />
      <Metric label="Accepted" value={m.accepted} accent />
      <Metric label="Agent runs" value={m.agent_runs} />
      <Metric label="LLM calls" value={m.llm_calls} />
      <Metric label="Tool calls" value={m.tool_calls} />
      <Metric label="Claude calls" value={m.claude_calls} />
      <Metric label="Local calls" value={m.local_calls} />
      <Metric label="Cost" value={formatCost(m.cloud_cost)} />
      <Metric label="Time" value={formatElapsed(elapsedSeconds)} />
    </div>
  )
}
