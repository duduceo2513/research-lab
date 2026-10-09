import { Copy, Download, ExternalLink, FileText, Loader2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, downloadFile, errorMessage, requestBlob } from '@/api/client'
import { useResearchSourceDetail, useResearchSources } from '@/api/hooks'
import type { ResearchContext, ResearchRun, ResearchSource } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorNotice, Loading } from '@/components/ui/Feedback'
import { Select } from '@/components/ui/Select'
import { cn } from '@/lib/utils'

export const PROVIDER_LABEL: Record<string, string> = {
  BRIGHTDATA: 'Bright Data', OPENALEX: 'OpenAlex', SEMANTIC_SCHOLAR: 'Semantic Scholar', CROSSREF: 'Crossref',
  ARXIV: 'arXiv', GOOGLE_BOOKS: 'Google Books', CORE: 'CORE', OPEN_LIBRARY: 'Open Library',
  WIKIPEDIA: 'Wikipedia', YOUTUBE: 'YouTube',
}
const TYPE_LABEL: Record<string, string> = {
  WEB: 'Web page', PAPER: 'Paper', BOOK: 'Book', DOCUMENTATION: 'Documentation', VIDEO: 'Video',
  ENCYCLOPEDIA: 'Encyclopedia', OTHER: 'Other',
}

// What the teacher cares about: can I read/open it, or is it only a description?
function availability(source: ResearchSource): { label: string; variant: 'good' | 'neutral' | 'warn' | 'critical' } {
  if (source.has_file) return { label: `${source.document_format} saved`, variant: 'good' }
  if (source.document_status === 'EXTRACTED') return { label: 'Text extracted', variant: 'good' }
  if (source.document_status === 'FAILED') return { label: 'Download failed', variant: 'critical' }
  if (source.document_status === 'PENDING') return { label: 'Pending', variant: 'neutral' }
  return { label: source.text_length > 0 ? 'Description only' : 'No text', variant: 'neutral' }
}

const formatBytes = (bytes: number) =>
  bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`

function useObjectUrl(load: (() => Promise<Blob>) | null, key: string) {
  const [state, setState] = useState<{ url: string | null; error: string | null; loading: boolean }>({ url: null, error: null, loading: false })
  useEffect(() => {
    if (!load) return undefined
    let cancelled = false
    let created: string | null = null
    setState({ url: null, error: null, loading: true })
    load().then(
      (blob) => {
        if (cancelled) return
        created = URL.createObjectURL(blob)
        setState({ url: created, error: null, loading: false })
      },
      (error) => !cancelled && setState({ url: null, error: errorMessage(error), loading: false }),
    )
    return () => {
      cancelled = true
      if (created) URL.revokeObjectURL(created)
    }
    // `key` identifies the file; `load` is rebuilt on every render and must not retrigger the fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

function PdfViewer({ run, source }: { run: ResearchRun; source: ResearchSource }) {
  const path = `research-lab/runs/${run.id}/sources/${source.id}/file/`
  const { url, error, loading } = useObjectUrl(() => requestBlob(path), path)
  if (loading) return <div className="flex h-64 items-center justify-center text-ink-faint"><Loader2 className="h-5 w-5 animate-spin" /></div>
  if (error) return <ErrorNotice error={new Error(error)} />
  return url ? <iframe title={source.title} src={url} className="h-[70vh] w-full rounded-sm border border-border bg-white" /> : null
}

const INITIAL_CHARS = 120_000

function FullText({ text }: { text: string }) {
  const [all, setAll] = useState(false)
  const shown = all ? text : text.slice(0, INITIAL_CHARS)
  const paragraphs = useMemo(() => shown.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean), [shown])
  return (
    <div className="max-h-[70vh] overflow-y-auto rounded-sm border border-border bg-white px-5 py-4">
      <div className="mx-auto max-w-3xl space-y-3 text-[13.5px] leading-relaxed text-ink">
        {paragraphs.map((paragraph, i) => <p key={i} className="whitespace-pre-line">{paragraph}</p>)}
      </div>
      {!all && text.length > INITIAL_CHARS ? (
        <div className="mt-4 text-center">
          <Button size="sm" onClick={() => setAll(true)}>Show the remaining {(text.length - INITIAL_CHARS).toLocaleString()} characters</Button>
        </div>
      ) : null}
    </div>
  )
}

function MaterialCard({ run, source, onClose }: { run: ResearchRun; source: ResearchSource; onClose: () => void }) {
  const detail = useResearchSourceDetail(run, source.id)
  const [view, setView] = useState<'document' | 'text'>(source.has_file && source.document_format === 'PDF' ? 'document' : 'text')
  const [copied, setCopied] = useState(false)
  const data = detail.data
  const state = availability(source)
  const filePath = `research-lab/runs/${run.id}/sources/${source.id}/file/`

  const copy = () => {
    if (!data) return
    void navigator.clipboard.writeText(data.text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <Card className="flex min-w-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold leading-snug text-ink">{source.title}</h3>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge variant="accent">{PROVIDER_LABEL[source.provider] ?? source.provider}</Badge>
            <Badge>{TYPE_LABEL[source.source_type] ?? source.source_type}</Badge>
            {source.document_format ? <Badge>{source.document_format}</Badge> : null}
            <Badge variant={state.variant}>{state.label}</Badge>
            {source.open_access ? <Badge variant="good">Open access</Badge> : null}
          </div>
          <p className="mt-2 text-[12px] text-ink-muted">
            {[source.authors.slice(0, 4).join(', '), source.publisher, source.published_at?.slice(0, 4), source.doi && `DOI ${source.doi}`]
              .filter(Boolean).join(' · ')}
          </p>
        </div>
        <button type="button" onClick={onClose} className="shrink-0 text-[12px] text-ink-muted hover:text-ink lg:hidden">Close</button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2.5">
        {source.has_file ? (
          <Button size="sm" icon={<Download className="h-3.5 w-3.5" />}
                  onClick={() => downloadFile(filePath, { download: 1 }, source.file_name || 'document')}>
            Download original{source.file_size ? ` (${formatBytes(source.file_size)})` : ''}
          </Button>
        ) : null}
        {source.url ? (
          <a href={source.url} target="_blank" rel="noopener noreferrer"
             className="inline-flex h-8 items-center gap-1.5 rounded-sm border border-border px-2.5 text-[12px] text-ink-muted hover:text-ink">
            <ExternalLink className="h-3.5 w-3.5" /> Open source
          </a>
        ) : null}
        <Button size="sm" icon={<Copy className="h-3.5 w-3.5" />} onClick={copy} disabled={!data?.text}>
          {copied ? 'Copied' : 'Copy text'}
        </Button>
        <div className="ml-auto flex rounded-sm border border-border p-0.5 text-[12px]">
          {(['document', 'text'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              disabled={tab === 'document' && !source.has_file}
              onClick={() => setView(tab)}
              className={cn('rounded-[3px] px-2.5 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40',
                view === tab ? 'bg-ink text-white' : 'text-ink-muted hover:text-ink')}
            >
              {tab === 'document' ? 'Document' : 'Text'}
            </button>
          ))}
        </div>
      </div>

      <div className="p-5">
        {source.document_error ? <p className="mb-3 text-[12.5px] text-warn">{source.document_error}</p> : null}
        {view === 'document' && source.has_file ? (
          source.document_format === 'PDF' ? (
            <PdfViewer run={run} source={source} />
          ) : (
            <div className="flex flex-col items-center gap-3 rounded-sm border border-dashed border-border py-10 text-center">
              <FileText className="h-8 w-8 text-ink-faint" />
              <p className="text-[13px] text-ink-muted">{source.document_format} files can't be previewed in the browser. Download the original or read the extracted text.</p>
            </div>
          )
        ) : detail.isPending ? (
          <Loading />
        ) : detail.error || !data ? (
          <ErrorNotice error={detail.error} />
        ) : data.text ? (
          <>
            <p className="mb-2 text-[12px] text-ink-faint">
              {data.text_origin === 'document' ? 'Text extracted from the document' : 'Description provided by the source (no full text available)'}
              {' · '}{data.text.length.toLocaleString()} characters
            </p>
            <FullText text={data.text} />
          </>
        ) : (
          <EmptyState title="No text available" hint="The source did not provide any text for this material." />
        )}
      </div>
    </Card>
  )
}

function MaterialRow({ source, selected, onSelect }: { source: ResearchSource; selected: boolean; onSelect: () => void }) {
  const state = availability(source)
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn('w-full border-b border-border px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-surface',
        selected && 'bg-accent-soft/50')}
    >
      <p className="line-clamp-2 text-[13px] font-medium leading-snug text-ink">{source.title}</p>
      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[11.5px] text-ink-muted">
        <span>{PROVIDER_LABEL[source.provider] ?? source.provider}</span>
        <span className="text-ink-faint">·</span>
        <span>{TYPE_LABEL[source.source_type] ?? source.source_type}</span>
        {source.document_format ? <><span className="text-ink-faint">·</span><span>{source.document_format}</span></> : null}
        <span className="text-ink-faint">·</span>
        <span className={cn(state.variant === 'good' && 'text-good', state.variant === 'critical' && 'text-critical')}>{state.label}</span>
      </p>
      {source.text_preview ? <p className="mt-1 line-clamp-2 text-[12px] text-ink-faint">{source.text_preview}</p> : null}
    </button>
  )
}

// The teacher's view of what a search found: filterable list, the downloaded documents (PDFs open right
// in the browser) and the complete text of each material.
export function Materials({ run }: { run: ResearchRun }) {
  const sources = useResearchSources(run)
  const [provider, setProvider] = useState('')
  const [type, setType] = useState('')
  const [format, setFormat] = useState('')
  const [downloadedOnly, setDownloadedOnly] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const all = useMemo(() => sources.data ?? [], [sources.data])
  const options = useMemo(() => ({
    providers: [...new Set(all.map((s) => s.provider))].sort(),
    types: [...new Set(all.map((s) => s.source_type))].sort(),
    formats: [...new Set(all.map((s) => s.document_format).filter(Boolean))].sort(),
  }), [all])

  const visible = all.filter((s) =>
    (!provider || s.provider === provider) && (!type || s.source_type === type)
    && (!format || s.document_format === format) && (!downloadedOnly || s.has_file))
  const selected = all.find((s) => s.id === selectedId) ?? null
  const downloaded = all.filter((s) => s.has_file).length

  const exportContext = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const context = await api.get<ResearchContext>(`research-lab/runs/${run.id}/context/`)
      if (!context.materials) throw new Error('There is no text to export yet.')
      await downloadFile(`research-lab/runs/${run.id}/context/`, { download: 1 }, `${run.topic.replace(/\W+/g, '-').toLowerCase()}-context.txt`)
    } catch (error) {
      setExportError(errorMessage(error))
    } finally {
      setExporting(false)
    }
  }

  if (sources.isPending) return <Loading />
  if (sources.error) return <ErrorNotice error={sources.error} />
  if (all.length === 0) {
    return <EmptyState title={run.is_active ? 'Searching…' : 'Nothing found'}
                       hint={run.is_active ? 'Materials appear here as soon as the sources answer.' : 'No source returned results for this topic.'} />
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">All sources</option>
          {options.providers.map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p] ?? p}</option>)}
        </Select>
        <Select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option>
          {options.types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}
        </Select>
        <Select value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="">All formats</option>
          {options.formats.map((f) => <option key={f} value={f}>{f}</option>)}
        </Select>
        <label className="flex cursor-pointer items-center gap-1.5 text-[12.5px] text-ink-muted">
          <input type="checkbox" checked={downloadedOnly} onChange={(e) => setDownloadedOnly(e.target.checked)} />
          Downloaded files only
        </label>
        <span className="ml-auto text-[12px] text-ink-faint">{visible.length} of {all.length} · {downloaded} files saved</span>
        <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={exportContext} disabled={exporting}>
          {exporting ? 'Preparing…' : 'Export all text'}
        </Button>
      </div>
      {exportError ? <p className="text-[12.5px] text-warn">{exportError}</p> : null}

      <div className="grid items-start gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className={cn('max-h-[78vh] overflow-y-auto', selected && 'hidden lg:block')}>
          {visible.length === 0 ? <p className="px-4 py-8 text-center text-[13px] text-ink-faint">No materials match these filters.</p> : null}
          {visible.map((source) => (
            <MaterialRow key={source.id} source={source} selected={source.id === selectedId} onSelect={() => setSelectedId(source.id)} />
          ))}
        </Card>
        {selected ? (
          <MaterialCard key={selected.id} run={run} source={selected} onClose={() => setSelectedId(null)} />
        ) : (
          <Card className="hidden lg:block"><EmptyState title="Select a material" hint="Open a PDF in the browser, download the original or read the full extracted text." /></Card>
        )}
      </div>
    </div>
  )
}
