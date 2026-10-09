import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useApiMutation, useResearchLabConfig } from '@/api/hooks'
import type {
  LectureDetailLevel, MaterialType, ResearchAssignmentType, ResearchDifficulty, ResearchRun, ResearchRunMode,
} from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/Feedback'
import { Field, Textarea, Toggle } from '@/components/ui/Field'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { Select } from '@/components/ui/Select'
import { humanize } from '@/lib/format'

interface Props {
  open: boolean
  onClose: () => void
}

const MATERIAL_LABELS: Record<MaterialType, string> = {
  WEB: 'Web / university materials', PAPERS: 'Scientific papers', BOOKS: 'Books', DOCUMENTATION: 'Documentation',
}

const STATE_HINT: Record<string, string> = {
  disabled: 'Turned off in Settings', missing_key: 'API key missing', error: 'Last call failed',
}

export function CreateResearchRunModal({ open, onClose }: Props) {
  const navigate = useNavigate()
  const config = useResearchLabConfig()
  const [mode, setMode] = useState<ResearchRunMode>('RESEARCH')
  // null = every source that is currently usable (the default); otherwise the teacher's own pick.
  const [pickedSources, setPickedSources] = useState<string[] | null>(null)
  const [topic, setTopic] = useState('')
  const [description, setDescription] = useState('')
  const [educationLevel, setEducationLevel] = useState('UNDERGRADUATE')
  const [materialTypes, setMaterialTypes] = useState<MaterialType[]>(['WEB', 'PAPERS'])
  const [generateLecture, setGenerateLecture] = useState(true)
  const [lectureDuration, setLectureDuration] = useState(60)
  const [lectureDetailLevel, setLectureDetailLevel] = useState<LectureDetailLevel>('MEDIUM')
  const [lectureIncludeExamples, setLectureIncludeExamples] = useState(true)
  const [lectureIncludeSummary, setLectureIncludeSummary] = useState(true)
  const [generateAssignment, setGenerateAssignment] = useState(true)
  const [assignmentType, setAssignmentType] = useState<ResearchAssignmentType>('MIXED')
  const [difficulty, setDifficulty] = useState<ResearchDifficulty>('MEDIUM')
  const [llmMode, setLlmMode] = useState<string | null>(null)
  const effectiveLlmMode = llmMode ?? config.data?.default_llm_mode ?? 'HYBRID'

  const create = useApiMutation(
    (input: Record<string, unknown>) => api.post<ResearchRun>('research-lab/runs/', input),
    ['research-lab/runs'],
  )

  const providers = config.data?.providers ?? []
  // Switched-off sources and sources without a key can't run, so they can't be picked either.
  const usable = providers.filter((p) => p.enabled && p.configured).map((p) => p.code)
  const chosen = (pickedSources ?? usable).filter((code) => usable.includes(code))
  const toggleSource = (code: string) =>
    setPickedSources(chosen.includes(code) ? chosen.filter((c) => c !== code) : [...chosen, code])
  // The switch in Settings can take the search-only mode away; never submit it then.
  const searchOnly = mode === 'SEARCH' && config.data?.materials_search_enabled !== false

  const toggleMaterialType = (type: MaterialType) => {
    setMaterialTypes((current) => (current.includes(type) ? current.filter((t) => t !== type) : [...current, type]))
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!topic.trim() || chosen.length === 0) return
    create.mutate(
      {
        mode: searchOnly ? 'SEARCH' : 'RESEARCH', selected_providers: chosen.length === usable.length ? [] : chosen,
        topic: topic.trim(), description: description.trim(), education_level: educationLevel,
        material_types: materialTypes,
        generate_lecture: generateLecture, lecture_target_duration_minutes: lectureDuration,
        lecture_detail_level: lectureDetailLevel, lecture_include_examples: lectureIncludeExamples,
        lecture_include_summary: lectureIncludeSummary,
        generate_assignment: generateAssignment,
        assignment_type: assignmentType, difficulty, llm_mode: effectiveLlmMode,
      },
      { onSuccess: (run) => navigate(`/research-lab/${run.id}`) },
    )
  }

  return (
    <Modal
      wide
      open={open}
      onClose={onClose}
      title={searchOnly ? 'New materials search' : 'New research run'}
      description={searchOnly
        ? 'Finds articles, books, lectures and slides on a topic, downloads what is openly available and extracts its text — in the background.'
        : 'Research Lab plans a search, vets sources and (optionally) drafts an assignment — this runs in the background.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="accent" type="submit" form="create-research-run" disabled={create.isPending || !topic.trim() || chosen.length === 0}>
            {create.isPending ? 'Starting…' : searchOnly ? 'Start search' : 'Start research'}
          </Button>
        </>
      }
    >
      <form id="create-research-run" onSubmit={submit} className="grid gap-x-8 gap-y-4 md:grid-cols-2">
        {config.data?.materials_search_enabled === false ? null : <div className="flex rounded-sm border border-border p-0.5 text-[12.5px] md:col-span-2">
          {([['RESEARCH', 'Full research with agents'], ['SEARCH', 'Materials search only']] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              className={`flex-1 rounded-[3px] px-3 py-1.5 font-medium ${mode === value ? 'bg-ink text-white' : 'text-ink-muted hover:text-ink'}`}
            >
              {label}
            </button>
          ))}
        </div>}

        <div className="flex flex-col gap-4">
          <Field label="Topic">
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              maxLength={255}
              placeholder="e.g. Retrieval-Augmented Generation"
              className="h-9 w-full rounded-sm border border-border bg-white px-2.5 text-[13px] text-ink placeholder:text-ink-faint outline-none hover:border-border-strong focus:border-ink"
            />
          </Field>
          <Field label="Description" hint="Optional — narrows the search.">
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} />
          </Field>
        </div>

        <div className="flex flex-col gap-4">
          {searchOnly ? null : (
            <div className="grid grid-cols-2 gap-4">
              <Field label="Education level">
                <Select value={educationLevel} onChange={(e) => setEducationLevel(e.target.value)} className="w-full">
                  {(config.data?.education_levels ?? ['SCHOOL', 'UNDERGRADUATE', 'MASTER', 'PHD', 'PROFESSIONAL']).map((level) => (
                    <option key={level} value={level}>{humanize(level)}</option>
                  ))}
                </Select>
              </Field>
              <Field label="AI model mode">
                <Select value={effectiveLlmMode} onChange={(e) => setLlmMode(e.target.value)} className="w-full">
                  <option value="LOCAL">Local only</option>
                  <option value="CLOUD">Cloud only</option>
                  <option value="HYBRID">Hybrid</option>
                </Select>
              </Field>
            </div>
          )}
          <Field label="Sources" hint={`${chosen.length} of ${providers.length} selected. Turn sources on or off for everyone in Settings → Research Lab.`}>
            <div className="flex flex-wrap gap-2">
              {providers.map((provider) => {
                const available = usable.includes(provider.code)
                const picked = chosen.includes(provider.code)
                return (
                  <button
                    key={provider.code}
                    type="button"
                    disabled={!available}
                    title={available ? undefined : provider.state === 'missing_key'
                      ? `${STATE_HINT.missing_key}: ${provider.missing_settings.join(', ')}` : STATE_HINT[provider.state]}
                    onClick={() => toggleSource(provider.code)}
                    className={`rounded-sm border px-2.5 py-1 text-[12px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${picked ? 'border-accent bg-accent-soft text-accent' : 'border-border text-ink-muted'}`}
                  >
                    {provider.label}
                  </button>
                )
              })}
            </div>
          </Field>
        </div>

        {searchOnly ? null : (<>
          <div className="md:col-span-2">
            <Field label="Material types" hint="Leave none selected to search everything.">
              <div className="flex flex-wrap gap-2">
                {(config.data?.material_types ?? (Object.keys(MATERIAL_LABELS) as MaterialType[])).map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => toggleMaterialType(type)}
                    className={`rounded-sm border px-2.5 py-1 text-[12px] font-medium ${materialTypes.includes(type) ? 'border-accent bg-accent-soft text-accent' : 'border-border text-ink-muted'}`}
                  >
                    {MATERIAL_LABELS[type] ?? humanize(type)}
                  </button>
                ))}
              </div>
            </Field>
          </div>

          <div className="flex flex-col gap-4 rounded-md border border-border p-4">
            <Field label="Generate a lecture" hint="Builds a full lecture from the approved sources.">
              <Toggle checked={generateLecture} onChange={setGenerateLecture} labels={['Yes', 'No']} />
            </Field>
            {generateLecture ? (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <Field label="Duration (minutes)">
                    <Input type="number" min={10} max={240} value={lectureDuration}
                           onChange={(e) => setLectureDuration(Number(e.target.value) || 60)} />
                  </Field>
                  <Field label="Detail level">
                    <Select value={lectureDetailLevel} onChange={(e) => setLectureDetailLevel(e.target.value as LectureDetailLevel)} className="w-full">
                      <option value="LOW">Low (concise)</option>
                      <option value="MEDIUM">Medium</option>
                      <option value="HIGH">High (in-depth)</option>
                    </Select>
                  </Field>
                </div>
                <div className="flex gap-6">
                  <Field label="Include examples">
                    <Toggle checked={lectureIncludeExamples} onChange={setLectureIncludeExamples} labels={['Yes', 'No']} />
                  </Field>
                  <Field label="Include a summary">
                    <Toggle checked={lectureIncludeSummary} onChange={setLectureIncludeSummary} labels={['Yes', 'No']} />
                  </Field>
                </div>
              </>
            ) : null}
          </div>

          <div className="flex flex-col gap-4 rounded-md border border-border p-4">
            <Field label="Generate an assignment" hint={generateLecture ? 'Written to match the generated lecture, not just the raw sources.' : undefined}>
              <Toggle checked={generateAssignment} onChange={setGenerateAssignment} labels={['Yes', 'No']} />
            </Field>
            {generateAssignment ? (
              <div className="grid grid-cols-2 gap-4">
                <Field label="Assignment type">
                  <Select value={assignmentType} onChange={(e) => setAssignmentType(e.target.value as ResearchAssignmentType)} className="w-full">
                    <option value="THEORETICAL">Theoretical</option>
                    <option value="PRACTICAL">Practical</option>
                    <option value="MIXED">Mixed</option>
                  </Select>
                </Field>
                <Field label="Difficulty">
                  <Select value={difficulty} onChange={(e) => setDifficulty(e.target.value as ResearchDifficulty)} className="w-full">
                    <option value="EASY">Easy</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HARD">Hard</option>
                  </Select>
                </Field>
              </div>
            ) : null}
          </div>
        </>)}
        {create.error ? <div className="md:col-span-2"><ErrorNotice error={create.error} /></div> : null}
      </form>
    </Modal>
  )
}
