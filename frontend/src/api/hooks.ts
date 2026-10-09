import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { api, fetchAll, type Paginated, type QueryParams } from './client'
import type {
  AgentExecution,
  Assignment,
  GeneratedLecture,
  GenerationRun,
  LLMConfiguration,
  LLMProvider,
  ResearchLabConfig,
  ResearchLabSettings,
  ResearchEvent,
  ResearchLabProviderStatus,
  ResearchSourceDetail,
  ResearchMetrics,
  ResearchRun,
  ResearchSource,
  ToolExecution,
} from './types'

// `refetchInterval` also accepts a predicate (poll while the data says the job is still running)
// — typed over `TData` so each hook below can type it
// against whatever shape its own query actually returns (Paginated<T>, T[] or T).
interface QueryOptions<TData = unknown> {
  enabled?: boolean
  refetchInterval?: number | false | ((query: { state: { data: TData | undefined } }) => number | false | undefined)
}

export function useList<T>(path: string, params?: QueryParams, options: QueryOptions<Paginated<T>> = {}) {
  return useQuery({
    queryKey: [path, 'page', params ?? {}],
    queryFn: ({ signal }) => api.get<Paginated<T>>(path, params, signal),
    placeholderData: keepPreviousData,
    ...options,
  })
}

export function useCount(path: string, params?: QueryParams, enabled = true) {
  return useQuery({
    queryKey: [path, 'count', params ?? {}],
    queryFn: async () => (await api.get<Paginated<unknown>>(path, { ...params, page_size: 1 })).count,
    enabled,
  })
}

export function useAll<T>(path: string, params?: QueryParams, options: QueryOptions<T[]> = {}) {
  return useQuery({
    queryKey: [path, 'all', params ?? {}],
    queryFn: () => fetchAll<T>(path, params),
    ...options,
  })
}

export function useDetail<T>(path: string, id: number | string | null | undefined, options: QueryOptions<T> = {}) {
  return useQuery({
    queryKey: [path, 'detail', id],
    queryFn: ({ signal }) => api.get<T>(`${path}/${id}/`, undefined, signal),
    enabled: id !== null && id !== undefined,
    ...options,
  })
}

export function invalidate(queryClient: QueryClient, ...paths: string[]) {
  return queryClient.invalidateQueries({
    predicate: (query) => typeof query.queryKey[0] === 'string' && paths.includes(query.queryKey[0]),
  })
}

export function useApiMutation<TInput, TOutput>(fn: (input: TInput) => Promise<TOutput>, invalidates: string[] = []) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate(queryClient, ...invalidates),
  })
}

// -- llm --------------------------------------------------------------------------------------
export const useLLMProviders = (enabled = true) => useAll<LLMProvider>('llm/providers', undefined, { enabled })
export const useLLMConfigurations = (enabled = true) =>
  useAll<LLMConfiguration>('llm/configurations', undefined, { enabled })
export const useLocalModels = (enabled = true) =>
  useQuery({
    queryKey: ['llm/local-models', 'all'],
    queryFn: () => api.get<{ models: string[]; detail?: string }>('llm/local-models/'),
    enabled,
    retry: false,
  })
export const useGenerationRuns = (params?: QueryParams, enabled = true) =>
  useAll<GenerationRun>('llm/generation-runs', params, { enabled })
export const useGenerationRunPage = (params?: QueryParams) => useList<GenerationRun>('llm/generation-runs', params)

// -- research lab -------------------------------------------------------------------------------
export const RESEARCH_ACTIVE_STATUSES = [
  'PENDING', 'PLANNING', 'SEARCHING', 'ANALYZING', 'VALIDATING', 'BUILDING_LECTURE', 'REVIEWING_LECTURE', 'GENERATING', 'REVIEWING',
]

export const useResearchLabConfig = () =>
  useQuery({ queryKey: ['research-lab/config'], queryFn: () => api.get<ResearchLabConfig>('research-lab/config/') })

export const useResearchLabSettings = (enabled = true) =>
  useQuery({
    queryKey: ['research-lab/settings'],
    queryFn: () => api.get<ResearchLabSettings>('research-lab/settings/'),
    enabled,
  })

// What a source's badge reads once its switch is flipped (mirrors services/module_settings.py).
function sourceStateAfterToggle(provider: ResearchLabProviderStatus, enabled: boolean): ResearchLabProviderStatus['state'] {
  if (!enabled) return 'disabled'
  if (!provider.configured) return 'missing_key'
  return provider.last_error ? 'error' : 'active'
}

// Optimistic: the switch moves the instant it is clicked; the server's answer then replaces the guess
// (and a failed save puts the switch back), instead of waiting for a PATCH plus two refetches.
export function useUpdateResearchLabSettings() {
  const queryClient = useQueryClient()
  const key = ['research-lab/settings']
  return useMutation({
    mutationFn: (input: { default_llm_mode?: string; disabled_providers?: string[]; materials_search_enabled?: boolean }) =>
      api.patch<ResearchLabSettings>('research-lab/settings/', input),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<ResearchLabSettings>(key)
      if (previous) {
        const disabled = input.disabled_providers ?? previous.disabled_providers
        queryClient.setQueryData<ResearchLabSettings>(key, {
          ...previous,
          default_llm_mode: (input.default_llm_mode as ResearchLabSettings['default_llm_mode']) ?? previous.default_llm_mode,
          disabled_providers: disabled,
          materials_search_enabled: input.materials_search_enabled ?? previous.materials_search_enabled,
          providers: previous.providers.map((provider) => {
            const enabled = !disabled.includes(provider.code)
            return { ...provider, enabled, state: sourceStateAfterToggle(provider, enabled) }
          }),
        })
      }
      return { previous }
    },
    onError: (_error, _input, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },
    onSuccess: (saved) => queryClient.setQueryData(key, saved),
    onSettled: () => invalidate(queryClient, 'research-lab/config'),
  })
}

export const useResearchRuns = (params?: QueryParams) =>
  useList<ResearchRun>('research-lab/runs', params, {
    refetchInterval: (query) =>
      query.state.data?.results.some((run) => RESEARCH_ACTIVE_STATUSES.includes(run.status)) ? 2000 : false,
  })

export const useResearchRun = (id: number | undefined) =>
  useDetail<ResearchRun>('research-lab/runs', id, {
    refetchInterval: (query) => (query.state.data && RESEARCH_ACTIVE_STATUSES.includes(query.state.data.status) ? 1500 : false),
  })

function useResearchSubresource<T>(path: string, run: ResearchRun | undefined) {
  return useAll<T>(`research-lab/runs/${run?.id}/${path}`, undefined, {
    enabled: Boolean(run),
    refetchInterval: run && RESEARCH_ACTIVE_STATUSES.includes(run.status) ? 2000 : false,
  })
}

export const useResearchSources = (run: ResearchRun | undefined) => useResearchSubresource<ResearchSource>('sources', run)
export const useResearchAgents = (run: ResearchRun | undefined) => useResearchSubresource<AgentExecution>('agents', run)
export const useResearchTools = (run: ResearchRun | undefined) => useResearchSubresource<ToolExecution>('tools', run)
export const useResearchSourceDetail = (run: ResearchRun | undefined, sourceId: number | null) =>
  useQuery({
    queryKey: ['research-lab/runs', 'source', run?.id, sourceId],
    queryFn: () => api.get<ResearchSourceDetail>(`research-lab/runs/${run?.id}/sources/${sourceId}/`),
    enabled: run !== undefined && sourceId !== null,
    // Text arrives while the run is still downloading; follow it until the run is over.
    refetchInterval: run && RESEARCH_ACTIVE_STATUSES.includes(run.status) ? 4000 : false,
  })

export function useTestResearchProvider() {
  return useApiMutation(
    (code: string) => api.post<ResearchLabProviderStatus>(`research-lab/settings/providers/${code}/test/`, {}),
    ['research-lab/settings', 'research-lab/config'],
  )
}

// The raw persisted event journal, for the Debug / Technical Logs tab (the Workspace streams it live).
export const useResearchEvents = (run: ResearchRun | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ['research-lab/runs', 'events', run?.id],
    queryFn: () => api.get<ResearchEvent[]>(`research-lab/runs/${run?.id}/events/`, { limit: 2000 }),
    enabled: enabled && run !== undefined,
    refetchInterval: run && RESEARCH_ACTIVE_STATUSES.includes(run.status) ? 3000 : false,
  })

export const useResearchAssignment = (run: ResearchRun | undefined) =>
  useQuery({
    queryKey: ['research-lab/runs', 'assignment', run?.id],
    queryFn: () => api.get<Assignment>(`research-lab/runs/${run?.id}/assignment/`),
    enabled: Boolean(run) && run?.generate_assignment,
    retry: false,
    refetchInterval: run && RESEARCH_ACTIVE_STATUSES.includes(run.status) ? 2000 : false,
  })

export const useResearchLecture = (run: ResearchRun | undefined) =>
  useQuery({
    queryKey: ['research-lab/runs', 'lecture', run?.id],
    queryFn: () => api.get<GeneratedLecture>(`research-lab/runs/${run?.id}/lecture/`),
    enabled: Boolean(run) && run?.generate_lecture,
    retry: false,
    refetchInterval: run && RESEARCH_ACTIVE_STATUSES.includes(run.status) ? 2000 : false,
  })

export const useResearchMetrics = (run: ResearchRun | undefined) =>
  useQuery({
    queryKey: ['research-lab/runs', 'metrics', run?.id],
    queryFn: () => api.get<ResearchMetrics>(`research-lab/runs/${run?.id}/metrics/`),
    enabled: Boolean(run),
    refetchInterval: run && RESEARCH_ACTIVE_STATUSES.includes(run.status) ? 2000 : false,
  })
