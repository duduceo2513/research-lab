import { useState, type FormEvent, type ReactNode } from 'react'
import { api } from '@/api/client'
import {
  useApiMutation,
  useLLMConfigurations,
  useLocalModels,
  useResearchLabSettings,
  useTestResearchProvider,
  useUpdateResearchLabSettings,
} from '@/api/hooks'
import type { LLMConfiguration, ResearchLabProviderStatus, User } from '@/api/types'
import { useAuth } from '@/auth/context'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ErrorNotice, Loading } from '@/components/ui/Feedback'
import { Toggle } from '@/components/ui/Field'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Tabs } from '@/components/ui/Tabs'
import { providerLabel } from '@/lib/format'

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid grid-cols-1 gap-1.5 sm:grid-cols-[180px_1fr] sm:items-center sm:gap-4">
      <span className="text-[13px] font-medium text-ink">{label}</span>
      {children}
    </label>
  )
}

function ProfileTab() {
  const { user, refreshUser } = useAuth()
  const [firstName, setFirstName] = useState(user?.first_name ?? '')
  const [lastName, setLastName] = useState(user?.last_name ?? '')
  const [username, setUsername] = useState(user?.username ?? '')
  const save = useApiMutation(
    (input: { first_name: string; last_name: string; username: string }) => api.patch<User>('accounts/me/', input),
    [],
  )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate({ first_name: firstName, last_name: lastName, username }, { onSuccess: () => void refreshUser() })
  }

  return (
    <Card>
      <CardHeader title="Profile" description="Your account details" />
      <CardBody>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Row label="E-mail">
            <Input value={user?.email ?? ''} disabled className="max-w-sm" />
          </Row>
          <Row label="Role">
            <span className="text-[13px] text-ink">{user?.role}</span>
          </Row>
          <Row label="First name">
            <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} className="max-w-sm" />
          </Row>
          <Row label="Last name">
            <Input value={lastName} onChange={(e) => setLastName(e.target.value)} className="max-w-sm" />
          </Row>
          <Row label="Username">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} className="max-w-sm" />
          </Row>
          {save.error ? <ErrorNotice error={save.error} /> : null}
          <div className="flex items-center gap-3 pt-2">
            <Button variant="primary" size="sm" type="submit" disabled={save.isPending}>Save changes</Button>
            {save.isSuccess ? <span className="text-[12px] text-good">Saved</span> : null}
          </div>
        </form>
      </CardBody>
    </Card>
  )
}

function SecurityTab() {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const change = useApiMutation(
    (input: { old_password: string; new_password: string }) => api.post('accounts/me/password/', input),
    [],
  )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    change.mutate(
      { old_password: oldPassword, new_password: newPassword },
      {
        onSuccess: () => {
          setOldPassword('')
          setNewPassword('')
        },
      },
    )
  }

  return (
    <Card>
      <CardHeader title="Password" description="Change the password used to sign in" />
      <CardBody>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Row label="Current password">
            <Input type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} required autoComplete="current-password" className="max-w-sm" />
          </Row>
          <Row label="New password">
            <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required autoComplete="new-password" className="max-w-sm" />
          </Row>
          {change.error ? <ErrorNotice error={change.error} /> : null}
          <div className="flex items-center gap-3 pt-2">
            <Button variant="primary" size="sm" type="submit" disabled={change.isPending}>Change password</Button>
            {change.isSuccess ? <span className="text-[12px] text-good">Password changed</span> : null}
          </div>
        </form>
      </CardBody>
    </Card>
  )
}

//: Deliberately round numbers for the slider steps (not e.g. 1500, 6000) — easy to reason about,
// and each step doubles the previous one's "thinking" headroom for a local reasoning model.
const TOKEN_STEPS = [512, 1024, 2048, 4096, 8192, 16384, 32768]
// Claude / OpenAI can write much longer answers than a local model; lectures and assignments need the room.
const CLOUD_TOKEN_STEPS = [1024, 2048, 4096, 8192, 16384, 32768, 64000]

function nearestTokenStepIndex(value: number): number {
  return TOKEN_STEPS.reduce(
    (best, step, index) => (Math.abs(step - value) < Math.abs(TOKEN_STEPS[best] - value) ? index : best), 0)
}

function isReasoningOn(config: LLMConfiguration): boolean {
  return config.metadata?.reasoning_effort !== 'none'
}

function LocalModelsSection() {
  const localModels = useLocalModels()
  const configurations = useLLMConfigurations()
  const [selectedModel, setSelectedModel] = useState<Record<number, string>>({})
  const [tokenStepIndex, setTokenStepIndex] = useState<Record<number, number>>({})
  const [reasoningOn, setReasoningOn] = useState<Record<number, boolean>>({})

  const updateModel = useApiMutation(
    ({ id, model_name }: { id: number; model_name: string }) =>
      api.patch(`llm/configurations/${id}/`, { model_name }),
    ['llm/configurations'],
  )

  const updateGeneration = useApiMutation(
    ({ id, max_tokens, metadata }: { id: number; max_tokens: number; metadata: Record<string, unknown> }) =>
      api.patch(`llm/configurations/${id}/`, { max_tokens, metadata }),
    ['llm/configurations'],
  )

  const models = localModels.data?.models ?? []
  const localConfigs = (configurations.data ?? []).filter((config) => config.provider_code === 'LOCAL')

  return (
    <Card>
      <CardHeader
        title="Local models"
        description="Models currently pulled on the local server (e.g. via Ollama) — admin only"
        action={
          <Button size="sm" onClick={() => void localModels.refetch()} disabled={localModels.isFetching}>
            {localModels.isFetching ? 'Checking…' : 'Refresh list'}
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-4">
        {localModels.error ? <ErrorNotice error={localModels.error} /> : null}
        {localModels.data?.detail ? <p className="text-[12px] text-bad">{localModels.data.detail}</p> : null}
        {models.length ? (
          <p className="text-[12px] text-ink-muted">
            Found {models.length} model{models.length === 1 ? '' : 's'} on the local server: {models.join(', ')}
          </p>
        ) : !localModels.isFetching && !localModels.data?.detail ? (
          <p className="text-[12px] text-ink-muted">No models found — is the local server running and reachable?</p>
        ) : null}
        {updateModel.error ? <ErrorNotice error={updateModel.error} /> : null}
        {updateModel.isSuccess ? <p className="text-[12px] text-good">Model updated</p> : null}
        {updateGeneration.error ? <ErrorNotice error={updateGeneration.error} /> : null}
        {updateGeneration.isSuccess ? <p className="text-[12px] text-good">Generation settings saved</p> : null}
        <div className="divide-y divide-border">
          {localConfigs.map((config) => {
            const currentModel = selectedModel[config.id] ?? config.model_name
            const stepIndex = tokenStepIndex[config.id] ?? nearestTokenStepIndex(config.max_tokens)
            const maxTokens = TOKEN_STEPS[stepIndex]
            const reasoning = reasoningOn[config.id] ?? isReasoningOn(config)

            return (
              <div key={config.id} className="flex flex-col gap-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-[13px] font-medium text-ink">{config.name}</p>
                    <p className="text-[12px] text-ink-muted">Currently using: {config.model_name}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={currentModel}
                      onChange={(e) => setSelectedModel((prev) => ({ ...prev, [config.id]: e.target.value }))}
                    >
                      {!models.includes(config.model_name) ? (
                        <option value={config.model_name}>{config.model_name} (not in live list)</option>
                      ) : null}
                      {models.map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </Select>
                    <Button
                      size="sm"
                      disabled={updateModel.isPending || currentModel === config.model_name}
                      onClick={() => updateModel.mutate({ id: config.id, model_name: currentModel })}
                    >
                      Use this model
                    </Button>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-5 rounded-sm border border-border bg-surface px-3 py-2.5">
                  <div className="flex min-w-[240px] flex-1 items-center gap-3">
                    <span className="whitespace-nowrap text-[12px] font-medium text-ink">Max tokens: {maxTokens}</span>
                    <input
                      type="range"
                      min={0}
                      max={TOKEN_STEPS.length - 1}
                      step={1}
                      value={stepIndex}
                      onChange={(e) => setTokenStepIndex((prev) => ({ ...prev, [config.id]: Number(e.target.value) }))}
                      className="w-full accent-ink"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-medium text-ink">Reasoning</span>
                    <Toggle
                      checked={reasoning}
                      onChange={(value) => setReasoningOn((prev) => ({ ...prev, [config.id]: value }))}
                      labels={['On', 'Off']}
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={updateGeneration.isPending}
                    onClick={() => updateGeneration.mutate({
                      id: config.id, max_tokens: maxTokens,
                      metadata: { ...config.metadata, reasoning_effort: reasoning ? 'medium' : 'none' },
                    })}
                  >
                    Save
                  </Button>
                </div>
                <p className="text-[11px] text-ink-faint">
                  Reasoning models (e.g. the Qwen3 family) spend part of their token budget "thinking" before the
                  visible answer — too low a limit truncates mid-thought and the reply comes back empty. Turn
                  reasoning off for faster, cheaper, GPU-lighter replies once you don't need it.
                </p>
              </div>
            )
          })}
          {!localConfigs.length ? (
            <p className="py-3 text-[12px] text-ink-muted">
              No local configuration yet — run `python manage.py seed_defaults` or add one in the Django admin
              with provider "Local LLM (OpenAI-compatible)".
            </p>
          ) : null}
        </div>
      </CardBody>
    </Card>
  )
}

function AiTab() {
  const { isAdmin } = useAuth()
  const configurations = useLLMConfigurations()
  const [health, setHealth] = useState<Record<number, string>>({})

  const makeDefault = useApiMutation(
    (id: number) => api.patch(`llm/configurations/${id}/`, { is_default: true }),
    ['llm/configurations', 'research-lab/settings', 'research-lab/config'],
  )

  const check = async (id: number) => {
    setHealth((current) => ({ ...current, [id]: 'Checking…' }))
    try {
      const result = await api.get<{ ok: boolean; detail: string; latency_ms: number | null }>(`llm/configurations/${id}/health/`)
      setHealth((current) => ({ ...current, [id]: result.ok ? `OK${result.latency_ms ? ` · ${Math.round(result.latency_ms)} ms` : ''}` : `Failed: ${result.detail}` }))
    } catch (error) {
      setHealth((current) => ({ ...current, [id]: error instanceof Error ? error.message : 'Failed' }))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {makeDefault.error ? <ErrorNotice error={makeDefault.error} /> : null}

      <Card>
        <CardHeader title="Language models" description={isAdmin ? 'Configurations the agents can use' : 'Configured by administrators'} />
        {configurations.isPending ? <Loading /> : null}
        {configurations.error ? <ErrorNotice error={configurations.error} className="m-4" /> : null}
        <div className="divide-y divide-border">
          {configurations.data?.map((config: LLMConfiguration) => (
            <div key={config.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
              <div>
                <p className="flex items-center gap-2 text-[13px] font-medium text-ink">
                  {config.name}
                  {config.is_default ? <Badge variant="accent">default</Badge> : null}
                  {!config.is_active ? <Badge>inactive</Badge> : null}
                </p>
                <p className="text-[12px] text-ink-muted">
                  {providerLabel({ provider_code: config.provider_code })} · {config.model_name} · temp {config.temperature}
                </p>
              </div>
              {isAdmin ? (
                <div className="flex items-center gap-2">
                  {health[config.id] ? <span className="text-[12px] text-ink-muted">{health[config.id]}</span> : null}
                  <Button size="sm" onClick={() => void check(config.id)}>Health check</Button>
                  {!config.is_default ? (
                    <Button size="sm" onClick={() => makeDefault.mutate(config.id)}>Make default</Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </Card>

    </div>
  )
}

const SOURCE_STATE: Record<string, { label: string; variant: 'good' | 'neutral' | 'warn' | 'critical' }> = {
  active: { label: 'Active', variant: 'good' },
  disabled: { label: 'Disabled', variant: 'neutral' },
  missing_key: { label: 'API key missing', variant: 'warn' },
  error: { label: 'Connection error', variant: 'critical' },
}

function sourceNote(provider: ResearchLabProviderStatus): string {
  if (provider.state === 'missing_key') return `Set ${provider.missing_settings.join(' and ')} in the server's .env — the source is skipped until then.`
  if (provider.state === 'error') return provider.last_error || 'The last request failed.'
  if (provider.state === 'disabled') return 'Not queried by any search.'
  return provider.metadata_only ? 'Descriptions and metadata only — nothing to download.' : 'Documents are downloaded when openly available.'
}

// One cloud configuration (Claude / OpenAI): which one is used, and how long its answers may be.
function CloudModelRow({ config, onMakeDefault }: { config: LLMConfiguration; onMakeDefault: () => void }) {
  const nearest = CLOUD_TOKEN_STEPS.reduce(
    (best, step, index) => (Math.abs(step - config.max_tokens) < Math.abs(CLOUD_TOKEN_STEPS[best] - config.max_tokens) ? index : best), 0)
  const [stepIndex, setStepIndex] = useState<number | null>(null)
  const index = stepIndex ?? nearest
  const maxTokens = CLOUD_TOKEN_STEPS[index]
  const save = useApiMutation(
    (value: number) => api.patch(`llm/configurations/${config.id}/`, { max_tokens: value }),
    ['llm/configurations'],
  )
  const dirty = maxTokens !== config.max_tokens

  return (
    <div className="flex flex-col gap-3 px-5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-[13px] font-medium text-ink">
            {config.name}
            {config.is_default ? <Badge variant="accent">default</Badge> : null}
            {!config.is_active ? <Badge>inactive</Badge> : null}
          </p>
          <p className="text-[12px] text-ink-muted">
            {providerLabel({ provider_code: config.provider_code })} · {config.model_name}
          </p>
        </div>
        {!config.is_default ? <Button size="sm" onClick={onMakeDefault}>Use this</Button> : null}
      </div>
      <div className="flex flex-wrap items-center gap-5 rounded-sm border border-border bg-surface px-3 py-2.5">
        <div className="flex min-w-[240px] flex-1 items-center gap-3">
          <span className="whitespace-nowrap text-[12px] font-medium text-ink">Max tokens: {maxTokens.toLocaleString('en-US')}</span>
          <input
            type="range" min={0} max={CLOUD_TOKEN_STEPS.length - 1} step={1} value={index}
            onChange={(e) => setStepIndex(Number(e.target.value))}
            className="w-full accent-ink"
          />
        </div>
        <Button size="sm" variant="primary" disabled={save.isPending || !dirty} onClick={() => save.mutate(maxTokens)}>
          {save.isPending ? 'Saving…' : 'Save'}
        </Button>
        {save.isSuccess && !dirty ? <span className="text-[12px] text-good">Saved</span> : null}
      </div>
      {save.error ? <ErrorNotice error={save.error} /> : null}
    </div>
  )
}

function ResearchLabTab() {
  const testProvider = useTestResearchProvider()
  const moduleSettings = useResearchLabSettings()
  const configurations = useLLMConfigurations()
  const update = useUpdateResearchLabSettings()

  const makeDefault = useApiMutation(
    (id: number) => api.patch(`llm/configurations/${id}/`, { is_default: true }),
    ['llm/configurations', 'research-lab/settings', 'research-lab/config'],
  )

  const toggleProvider = (code: string, nextEnabled: boolean) => {
    const current = moduleSettings.data?.disabled_providers ?? []
    const next = nextEnabled ? current.filter((c) => c !== code) : [...current, code]
    update.mutate({ disabled_providers: next })
  }

  const cloudConfigs = (configurations.data ?? []).filter((config) => config.provider_code !== 'LOCAL')

  return (
    <div className="flex flex-col gap-6">
      {moduleSettings.isPending ? <Loading /> : null}
      {moduleSettings.error ? <ErrorNotice error={moduleSettings.error} /> : null}
      {update.error ? <ErrorNotice error={update.error} /> : null}

      <Card>
        <CardHeader
          title="Default AI mode"
          description="Which tier of model the module's 7 agents use by default for a new run"
        />
        <CardBody className="flex flex-col gap-3">
          <Select
            value={moduleSettings.data?.default_llm_mode ?? 'LOCAL'}
            onChange={(e) => update.mutate({ default_llm_mode: e.target.value })}
            className="w-full max-w-sm"
          >
            <option value="LOCAL">Local only</option>
            <option value="CLOUD">Cloud only (Claude / OpenAI)</option>
            <option value="HYBRID">Hybrid (local for scoring, cloud for writing/review)</option>
          </Select>
          <p className="text-[12px] text-ink-muted">
            New research runs start with this mode selected; each run can still override it when it's created.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Materials search"
          description="The “Materials search only” mode: find, download and read sources without writing a lecture or assignment"
        />
        <CardBody className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-[12px] text-ink-muted">
            Turn it off to offer only the full agent pipeline when creating a new search. Existing searches stay available.
          </p>
          <Toggle
            checked={moduleSettings.data?.materials_search_enabled ?? true}
            onChange={(value) => update.mutate({ materials_search_enabled: value })}
            labels={['On', 'Off']}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Search sources"
          description="Every search queries only the sources switched on here. The choice is saved — no .env or code change needed."
        />
        <div className="divide-y divide-border">
          {(moduleSettings.data?.providers ?? []).map((provider) => {
            const state = SOURCE_STATE[provider.state] ?? SOURCE_STATE.active
            return (
              <div key={provider.code} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-[13px] font-medium text-ink">
                    {provider.label}
                    <Badge variant={state.variant}>{state.label}</Badge>
                  </p>
                  <p className="truncate text-[12px] text-ink-muted" title={sourceNote(provider)}>{sourceNote(provider)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <Button
                    size="sm"
                    disabled={!provider.configured || testProvider.isPending}
                    onClick={() => testProvider.mutate(provider.code)}
                  >
                    {testProvider.isPending && testProvider.variables === provider.code ? 'Testing…' : 'Test'}
                  </Button>
                  <Toggle checked={provider.enabled} onChange={(value) => toggleProvider(provider.code, value)} labels={['On', 'Off']} />
                </div>
              </div>
            )
          })}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Cloud provider"
          description="Which model is used when a run (or the Hybrid tier) calls the cloud, and how long its answers may be. Research Lab always allows at least 8,192 tokens for lectures and assignments."
        />
        <div className="divide-y divide-border">
          {cloudConfigs.map((config) => (
            <CloudModelRow key={config.id} config={config} onMakeDefault={() => makeDefault.mutate(config.id)} />
          ))}
          {!cloudConfigs.length ? (
            <p className="px-5 py-3 text-[12px] text-ink-muted">
              No cloud configuration yet — run `python manage.py seed_defaults` or add one in the Django admin
              (provider OpenAI or Anthropic), with its API key set in the server's .env.
            </p>
          ) : null}
        </div>
      </Card>

      <LocalModelsSection />
    </div>
  )
}

export function Settings() {
  const { isStaff, isAdmin } = useAuth()
  const [tab, setTab] = useState('profile')
  const tabs = [
    { key: 'profile', label: 'Profile' },
    { key: 'security', label: 'Security' },
    ...(isStaff ? [{ key: 'ai', label: 'AI Models' }] : []),
    ...(isAdmin ? [{ key: 'research-lab', label: 'Research Lab' }] : []),
  ]

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Settings" description="Your account and, for staff, the AI configuration in use." />
      <Tabs items={tabs} active={tab} onChange={setTab} />
      {tab === 'profile' ? <ProfileTab /> : null}
      {tab === 'security' ? <SecurityTab /> : null}
      {tab === 'ai' && isStaff ? <AiTab /> : null}
      {tab === 'research-lab' && isAdmin ? <ResearchLabTab /> : null}
    </div>
  )
}
