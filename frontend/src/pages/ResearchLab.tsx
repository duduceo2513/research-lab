import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FlaskConical, Plus } from 'lucide-react'
import { useResearchRuns } from '@/api/hooks'
import { CreateResearchRunModal } from '@/components/research/CreateResearchRunModal'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody } from '@/components/ui/Card'
import { EmptyState, ErrorNotice, Loading } from '@/components/ui/Feedback'
import { formatDateTime, humanize, researchRunStatusTone } from '@/lib/format'

export function ResearchLab() {
  const [createOpen, setCreateOpen] = useState(false)
  const runs = useResearchRuns({ ordering: '-created_at' })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Research Lab"
        description="Find articles, books, lectures and slides on a topic across many sources, read what was downloaded, or let the agents vet it all and draft an assignment."
        action={<Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>New search</Button>}
      />

      {runs.isPending ? <Loading /> : null}
      {runs.error ? <ErrorNotice error={runs.error} /> : null}
      {runs.data?.results.length === 0 ? (
        <Card>
          <EmptyState title="No research runs yet" hint="Start one to search, vet sources and draft an assignment on a topic."
                     action={<Button variant="accent" onClick={() => setCreateOpen(true)}>New research run</Button>} />
        </Card>
      ) : null}

      <div className="flex flex-col gap-3">
        {runs.data?.results.map((run) => (
          <Link key={run.id} to={`/research-lab/${run.id}`}>
            <Card className="transition-colors hover:border-border-strong">
              <CardBody className="flex items-center gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm border border-border bg-surface">
                  <FlaskConical className="h-4 w-4 text-ink-muted" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-[13px] font-medium text-ink">{run.topic}</p>
                    <Badge variant={researchRunStatusTone[run.status]}>{humanize(run.status)}</Badge>
                    {run.mode === 'SEARCH' ? <Badge variant="neutral">Search</Badge> : null}
                    {run.generate_assignment ? <Badge variant="neutral">Assignment</Badge> : null}
                  </div>
                  <p className="mt-0.5 truncate text-[12px] text-ink-muted">
                    {humanize(run.education_level)} · {run.current_step || 'Queued'} · started {formatDateTime(run.created_at)}
                  </p>
                </div>
              </CardBody>
            </Card>
          </Link>
        ))}
      </div>

      <CreateResearchRunModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}
