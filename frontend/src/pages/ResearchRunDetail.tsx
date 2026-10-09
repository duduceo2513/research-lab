import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronRight, Copy, ExternalLink } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { api, downloadFile, errorMessage } from '@/api/client'
import { useWorkspaceSnapshot } from '@/api/useResearchWorkspace'
import {
  invalidate, useApiMutation, useResearchAgents, useResearchAssignment, useResearchLecture,
  useResearchEvents, useResearchMetrics, useResearchRun, useResearchSources, useResearchTools,
} from '@/api/hooks'
import type { AgentExecution, ResearchRun, ResearchSource, ToolExecution, ValidationDecision } from '@/api/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadDistribution, ModelDistribution } from '@/components/research/workspace/SidePanels'
import { Overview } from '@/components/research/workspace/Overview'
import { Materials } from '@/components/research/Materials'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { EmptyState, ErrorNotice, Loading } from '@/components/ui/Feedback'
import { StatCard } from '@/components/ui/StatCard'
import { Tabs } from '@/components/ui/Tabs'
import { formatDateTime, formatMs, humanize, researchAgentLabel, researchRunStatusTone } from '@/lib/format'

function SourcesTable({ sources }: { sources: ResearchSource[] }) {
  if (sources.length === 0) return <EmptyState title="No sources yet" />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-border text-[11px] uppercase tracking-wide text-ink-faint">
            <th className="px-4 py-2 font-medium">Title</th>
            <th className="px-4 py-2 font-medium">Type</th>
            <th className="px-4 py-2 font-medium">Provider</th>
            <th className="px-4 py-2 font-medium">Author</th>
            <th className="px-4 py-2 font-medium">Year</th>
            <th className="px-4 py-2 font-medium">Score</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">OA</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sources.map((source) => (
            <tr key={source.id}>
              <td className="max-w-xs truncate px-4 py-2.5 text-ink" title={source.title}>{source.title}</td>
              <td className="px-4 py-2.5 text-ink-muted">{humanize(source.source_type)}</td>
              <td className="px-4 py-2.5 text-ink-muted">{humanize(source.provider)}</td>
              <td className="px-4 py-2.5 text-ink-muted">{source.authors[0] ?? '—'}</td>
              <td className="px-4 py-2.5 text-ink-muted">{source.published_at ? source.published_at.slice(0, 4) : '—'}</td>
              <td className="px-4 py-2.5 text-ink">{source.overall_score !== null ? source.overall_score.toFixed(0) : '—'}</td>
              <td className="px-4 py-2.5">
                <Badge variant={source.decision === 'ACCEPT' ? 'good' : source.decision === 'REJECT' ? 'critical' : 'neutral'}>
                  {humanize(source.decision)}
                </Badge>
                {source.is_duplicate ? <Badge variant="neutral" className="ml-1">Duplicate</Badge> : null}
              </td>
              <td className="px-4 py-2.5 text-ink-muted">{source.open_access ? 'Yes' : 'No'}</td>
              <td className="px-4 py-2.5 text-right">
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-ink-faint hover:text-accent">
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AssignmentTab({ run }: { run: ResearchRun }) {
  const assignment = useResearchAssignment(run)
  if (!run.generate_assignment) return <EmptyState title="No assignment was requested for this run" />
  if (assignment.isPending) return <Loading />
  if (assignment.error) return <EmptyState title="No assignment yet" hint={errorMessage(assignment.error)} />
  const data = assignment.data
  if (!data) return null
  return (
    <Card>
      <CardHeader
        title={data.title}
        description={`${humanize(data.assignment_type)} · ${humanize(data.difficulty)}`}
        action={
          <Badge variant={data.review_status === 'APPROVED' ? 'good' : data.review_status === 'PENDING' ? 'neutral' : 'warn'}>
            {humanize(data.review_status)}{data.review_score !== null ? ` · ${data.review_score.toFixed(0)}` : ''}
          </Badge>
        }
      />
      <CardBody className="flex flex-col gap-4 text-[13px] text-ink">
        {data.objectives.length ? (
          <div>
            <p className="mb-1 font-semibold">Objectives</p>
            <ul className="list-disc space-y-1 pl-5">{data.objectives.map((o, i) => <li key={i}>{o}</li>)}</ul>
          </div>
        ) : null}
        <div>
          <p className="mb-1 font-semibold">Instructions</p>
          <p className="whitespace-pre-wrap text-ink-muted">{data.instructions}</p>
        </div>
        {data.questions.length ? (
          <div>
            <p className="mb-1 font-semibold">Questions</p>
            <ol className="list-decimal space-y-2 pl-5">
              {data.questions.map((q, i) => (
                <li key={i}>{q.prompt} {q.points ? <span className="text-ink-faint">({q.points} pts)</span> : null}</li>
              ))}
            </ol>
          </div>
        ) : null}
        {data.grading_criteria ? (
          <div>
            <p className="mb-1 font-semibold">Grading criteria</p>
            <p className="text-ink-muted">{data.grading_criteria}</p>
          </div>
        ) : null}
        {data.answer_key ? (
          <div>
            <p className="mb-1 font-semibold">Answer key</p>
            <p className="whitespace-pre-wrap text-ink-muted">{data.answer_key}</p>
          </div>
        ) : null}
        {data.review_issues.length ? (
          <div>
            <p className="mb-1 font-semibold">Reviewer notes</p>
            <ul className="list-disc space-y-1 pl-5 text-ink-muted">{data.review_issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}

const LECTURE_STATUS_TONE = {
  DRAFT: 'neutral', APPROVED: 'good', NEEDS_REVISION: 'warn', REVISION_LIMIT_REACHED: 'warn',
  INSUFFICIENT_SOURCES: 'critical',
} as const

function LectureTab({ run }: { run: ResearchRun }) {
  const lecture = useResearchLecture(run)
  const [copied, setCopied] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  if (!run.generate_lecture) return <EmptyState title="No lecture was requested for this run" />
  if (lecture.isPending) return <Loading />
  if (lecture.error) return <EmptyState title="No lecture yet" hint={errorMessage(lecture.error)} />
  const data = lecture.data
  if (!data) return null

  const copy = async () => {
    await navigator.clipboard.writeText(data.plain_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const exportFile = async (format: 'md' | 'txt' | 'docx') => {
    setExportError(null)
    try {
      const base = data.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'lecture'
      await downloadFile(`research-lab/runs/${run.id}/lecture/export/`, { export_format: format }, `${base}.${format}`)
    } catch (error) {
      setExportError(errorMessage(error))
    }
  }

  if (data.status === 'INSUFFICIENT_SOURCES') {
    return (
      <EmptyState
        title="Not enough approved sources to build a sound lecture"
        hint={data.content_json.missing_topics.length
          ? `Missing coverage: ${data.content_json.missing_topics.join(', ')}`
          : 'Try widening the material types or topic for this run.'}
      />
    )
  }

  return (
    <Card>
      <CardHeader
        title={data.title}
        description={`Version ${data.version}`}
        action={
          <div className="flex items-center gap-2">
            <Badge variant={LECTURE_STATUS_TONE[data.status]}>
              {humanize(data.status)}{data.review_score !== null ? ` · ${data.review_score.toFixed(0)}` : ''}
            </Badge>
            <Button size="sm" onClick={() => void copy()}>
              <Copy className="mr-1 h-3.5 w-3.5" /> {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button size="sm" onClick={() => void exportFile('md')}>Export Markdown</Button>
            <Button size="sm" onClick={() => void exportFile('txt')}>Export TXT</Button>
            <Button size="sm" onClick={() => void exportFile('docx')}>Export DOCX</Button>
          </div>
        }
      />
      <CardBody className="flex flex-col gap-4 text-[13px] text-ink">
        {exportError ? <ErrorNotice error={new Error(exportError)} /> : null}
        {data.learning_objectives.length ? (
          <div>
            <p className="mb-1 font-semibold">Learning objectives</p>
            <ul className="list-disc space-y-1 pl-5">{data.learning_objectives.map((o, i) => <li key={i}>{o}</li>)}</ul>
          </div>
        ) : null}
        {data.content_json.sections.map((section, i) => (
          <div key={i} className="border-t border-border pt-3 first:border-t-0 first:pt-0">
            <p className="mb-1 font-semibold">{section.title}</p>
            <p className="whitespace-pre-wrap text-ink-muted">{section.content}</p>
            {section.key_points.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-muted">
                {section.key_points.map((point, j) => <li key={j}>{point}</li>)}
              </ul>
            ) : null}
            {section.examples.length ? (
              <div className="mt-2">
                <p className="text-[12px] font-medium text-ink-muted">Examples</p>
                <ul className="list-disc space-y-1 pl-5 text-ink-muted">
                  {section.examples.map((example, j) => <li key={j}>{example}</li>)}
                </ul>
              </div>
            ) : null}
            {section.source_ids.length ? (
              <p className="mt-2 text-[11px] text-ink-faint">
                Sources: {section.source_ids.map((id) => `[${id}]`).join(', ')}
              </p>
            ) : null}
          </div>
        ))}
        {data.content_json.summary ? (
          <div className="border-t border-border pt-3">
            <p className="mb-1 font-semibold">Summary</p>
            <p className="text-ink-muted">{data.content_json.summary}</p>
          </div>
        ) : null}
        {data.content_json.self_check_questions.length ? (
          <div className="border-t border-border pt-3">
            <p className="mb-1 font-semibold">Self-check questions</p>
            <ol className="list-decimal space-y-1 pl-5 text-ink-muted">
              {data.content_json.self_check_questions.map((q, i) => <li key={i}>{q}</li>)}
            </ol>
          </div>
        ) : null}
        {data.content_json.references.length ? (
          <div className="border-t border-border pt-3">
            <p className="mb-1 font-semibold">References</p>
            <ul className="list-disc space-y-1 pl-5 text-ink-muted">
              {data.content_json.references.map((ref, i) => <li key={i}>{ref.citation}</li>)}
            </ul>
          </div>
        ) : null}
        {data.review_result.issues?.length ? (
          <div className="border-t border-border pt-3">
            <p className="mb-1 font-semibold">Reviewer notes</p>
            <ul className="list-disc space-y-1 pl-5 text-ink-muted">
              {data.review_result.issues.map((issue, i) => <li key={i}>{issue}</li>)}
            </ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}

function AgentLogsTab({ agents }: { agents: AgentExecution[] }) {
  if (agents.length === 0) return <EmptyState title="No agent activity yet" />
  return (
    <div className="flex flex-col divide-y divide-border">
      {agents.map((execution) => (
        <div key={execution.id} className="px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-semibold text-ink">#{execution.sequence} {researchAgentLabel[execution.agent]}</span>
            <Badge variant={execution.status === 'SUCCESS' ? 'good' : execution.status === 'FAILED' ? 'critical' : 'neutral'}>
              {execution.status}
            </Badge>
            <span className="text-[11px] text-ink-faint">{formatMs(execution.latency_ms)}</span>
            {execution.generation_run_tokens ? (
              <span className="text-[11px] text-ink-faint">{execution.generation_run_tokens} tokens</span>
            ) : null}
          </div>
          {execution.error_message ? <p className="mt-1 text-[12px] text-critical">{execution.error_message}</p> : null}
          {Object.keys(execution.output_summary).length ? (
            <pre className="mt-1.5 overflow-x-auto rounded-sm bg-surface p-2 text-[11px] text-ink-muted">
              {JSON.stringify(execution.output_summary, null, 2)}
            </pre>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">{label}</p>
      <pre className="max-h-96 overflow-auto rounded-sm border border-border bg-surface p-3 font-mono text-[11.5px] leading-relaxed text-ink">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

// Each call is a row; click it to see exactly what was asked and what came back (JSON).
function ToolCallsTab({ tools }: { tools: ToolExecution[] }) {
  const [open, setOpen] = useState<number | null>(null)
  if (tools.length === 0) return <EmptyState title="No tool calls yet" />
  return (
    <div className="flex flex-col divide-y divide-border">
      {tools.map((tool) => {
        const expanded = open === tool.id
        const hasResponse = Object.keys(tool.response_summary).length > 0
        return (
          <div key={tool.id}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : tool.id)}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-[13px] hover:bg-surface"
            >
              <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform ${expanded ? 'rotate-90' : ''}`} />
              <Badge variant={tool.status === 'SUCCESS' ? 'good' : tool.status === 'FAILED' ? 'critical' : 'neutral'}>
                {tool.status}
              </Badge>
              <span className="font-medium text-ink">{humanize(tool.tool)}</span>
              <span className="flex-1 truncate text-ink-faint">{JSON.stringify(tool.request_summary).slice(0, 80)}</span>
              <span className="text-ink-faint">{formatMs(tool.latency_ms)}</span>
            </button>
            {expanded ? (
              <div className="flex flex-col gap-3 border-t border-border bg-white px-4 py-3 pl-11">
                <JsonBlock label="Request" value={tool.request_summary} />
                {hasResponse ? <JsonBlock label="Response" value={tool.response_summary} /> : null}
                {tool.error_message ? <JsonBlock label="Error" value={tool.error_message} /> : null}
                {!hasResponse && !tool.error_message ? <p className="text-[12px] text-ink-faint">No response was recorded for this call.</p> : null}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function DebugTab({ run, agents, tools }: { run: ResearchRun; agents: AgentExecution[]; tools: ToolExecution[] }) {
  const [section, setSection] = useState('events')
  const events = useResearchEvents(run, section === 'events')
  const rows = [...(events.data ?? [])].reverse()
  return (
    <div className="flex flex-col gap-3">
      <Tabs
        items={[
          { key: 'events', label: 'Events', count: events.data?.length },
          { key: 'agents', label: 'Agent runs', count: agents.length },
          { key: 'tools', label: 'Tool calls', count: tools.length },
        ]}
        active={section} onChange={setSection}
      />
      {section === 'events' ? (
        <Card>
          {events.isPending ? <Loading /> : rows.length === 0 ? <EmptyState title="No events yet" /> : (
            <ul className="max-h-[640px] divide-y divide-border overflow-y-auto font-mono text-[11.5px]">
              {rows.map((event) => (
                <li key={event.id} className="px-4 py-2">
                  <div className="flex flex-wrap items-center gap-x-3 text-ink">
                    <span className="text-ink-faint">#{event.id}</span>
                    <span className="text-ink-faint">{new Date(event.created_at).toLocaleTimeString('en-GB', { hour12: false })}</span>
                    <b>{event.type}</b>
                    <span>{event.agent}</span>
                    {event.status ? <span className="text-accent">{event.status}</span> : null}
                    {event.provider ? <span className="text-ink-faint">{event.provider}{event.model_name ? ` · ${event.model_name}` : ''}</span> : null}
                  </div>
                  <p className="mt-0.5 break-words text-ink-muted">{event.summary}</p>
                  {Object.keys(event.payload).length ? (
                    <details className="mt-0.5">
                      <summary className="cursor-pointer text-ink-faint">payload</summary>
                      <pre className="mt-1 overflow-x-auto rounded-sm bg-surface p-2 text-ink-muted">{JSON.stringify(event.payload, null, 1)}</pre>
                    </details>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
      {section === 'agents' ? <Card><AgentLogsTab agents={agents} /></Card> : null}
      {section === 'tools' ? <Card><ToolCallsTab tools={tools} /></Card> : null}
    </div>
  )
}

function MetricsTab({ run }: { run: ResearchRun }) {
  const metrics = useResearchMetrics(run)
  const snapshot = useWorkspaceSnapshot(run.id, run.is_active)
  if (metrics.isPending) return <Loading />
  if (metrics.error || !metrics.data) return <ErrorNotice error={metrics.error} />
  const m = metrics.data
  return (
    <div className="flex flex-col gap-4">
    <div className="flex items-center justify-between gap-3 rounded-md border border-border px-4 py-3">
      <p className="text-[12.5px] text-ink-muted">
        Per-agent LLM and tool calls with each agent&apos;s share of the total (the 40% rule), totals and results.
      </p>
      <div className="flex gap-2">
        <Button size="sm" onClick={() => downloadFile(`research-lab/runs/${run.id}/report/`, { as: 'markdown' }, `run-${run.id}-report.md`)}>
          Load report (.md)
        </Button>
        <Button size="sm" onClick={() => downloadFile(`research-lab/runs/${run.id}/report/`, { as: 'json' }, `run-${run.id}-report.json`)}>
          JSON
        </Button>
      </div>
    </div>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatCard label="Sources found" value={m.sources_found} />
      <StatCard label="Unique sources" value={m.unique_sources} />
      <StatCard label="Accepted" value={m.accepted} accent />
      <StatCard label="Rejected" value={m.rejected} />
      <StatCard label="Agent calls" value={m.agent_calls_total} />
      <StatCard label="Max agent load" value={m.max_agent_load_pct} suffix="%" />
      <StatCard label="Tool calls" value={m.tool_calls_total} />
      <StatCard label="Revisions" value={m.revision_count} />
      <StatCard label="Execution time" value={m.execution_time_seconds ? `${m.execution_time_seconds.toFixed(0)}s` : '—'} />
      <StatCard label="Total tokens" value={m.total_tokens ?? '—'} />
      <StatCard label="Estimated cost" value={m.estimated_cost ? `$${m.estimated_cost}` : '—'} />
    </div>
    {snapshot.data ? (
      <div className="grid items-start gap-4 md:grid-cols-2">
        <ModelDistribution state={snapshot.data} />
        <LoadDistribution state={snapshot.data} />
      </div>
    ) : null}
    </div>
  )
}

export function ResearchRunDetail() {
  const { id } = useParams()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<string | null>(null)
  const run = useResearchRun(id ? Number(id) : undefined)
  const sources = useResearchSources(run.data)
  const agents = useResearchAgents(run.data)
  const tools = useResearchTools(run.data)
  const cancel = useApiMutation((runId: number) => api.post(`research-lab/runs/${runId}/cancel/`), [])

  if (run.isPending) return <Loading />
  if (run.error || !run.data) return <ErrorNotice error={run.error} />
  const data = run.data
  const allSources = sources.data ?? []
  const accepted = allSources.filter((s) => s.decision === ('ACCEPT' satisfies ValidationDecision))
  const rejected = allSources.filter((s) => s.decision === ('REJECT' satisfies ValidationDecision))

  // Overview always comes first; a plain materials search then goes straight to what it found.
  const isSearch = data.mode === 'SEARCH'
  const materialsTab = { key: 'materials', label: 'Materials', count: allSources.filter((s) => !s.is_duplicate).length }
  const tabs = [
    { key: 'overview', label: 'Overview' },
    materialsTab,
    ...(isSearch ? [] : [
      { key: 'sources', label: 'Sources', count: allSources.length },
      { key: 'accepted', label: 'Accepted', count: accepted.length },
      { key: 'rejected', label: 'Rejected', count: rejected.length },
    ]),
    ...(data.generate_lecture ? [{ key: 'lecture', label: 'Lecture' }] : []),
    ...(data.generate_assignment ? [{ key: 'assignment', label: 'Assignment' }] : []),
    { key: 'metrics', label: 'Metrics' },
    { key: 'debug', label: 'Agent Logs' },
  ]
  const activeTab = tab ?? 'overview'

  return (
    <div className="flex flex-col gap-6">
      <Link to="/research-lab" className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted hover:text-ink">
        <ArrowLeft className="h-3.5 w-3.5" /> Research Lab
      </Link>
      <PageHeader
        title={data.topic}
        description={`${humanize(data.status)} · ${formatDateTime(data.created_at)}`}
        action={
          <div className="flex items-center gap-2">
            <Badge variant={researchRunStatusTone[data.status]}>{humanize(data.status)}</Badge>
            {data.is_active ? (
              <Button
                variant="secondary" size="sm" disabled={cancel.isPending || data.cancel_requested}
                onClick={() => cancel.mutate(data.id, { onSuccess: () => invalidate(queryClient, 'research-lab/runs') })}
              >
                {data.cancel_requested ? 'Cancelling…' : 'Cancel'}
              </Button>
            ) : null}
          </div>
        }
      />

      <Tabs items={tabs} active={activeTab} onChange={setTab} />

      {activeTab === 'materials' ? <Materials key={data.id} run={data} /> : null}
      {activeTab === 'overview' ? <Overview key={data.id} run={data} /> : null}
      {activeTab === 'sources' ? <Card><SourcesTable sources={allSources} /></Card> : null}
      {activeTab === 'accepted' ? <Card><SourcesTable sources={accepted} /></Card> : null}
      {activeTab === 'rejected' ? <Card><SourcesTable sources={rejected} /></Card> : null}
      {activeTab === 'lecture' ? <LectureTab run={data} /> : null}
      {activeTab === 'assignment' ? <AssignmentTab run={data} /> : null}
      {activeTab === 'debug' ? <DebugTab run={data} agents={agents.data ?? []} tools={tools.data ?? []} /> : null}
      {activeTab === 'metrics' ? <MetricsTab run={data} /> : null}
    </div>
  )
}
