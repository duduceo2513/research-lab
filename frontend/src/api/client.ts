export const API_BASE = '/api/v1'

const ACCESS_KEY = 'research-lab.access'
const REFRESH_KEY = 'research-lab.refresh'

export const AUTH_LOST_EVENT = 'research-lab:auth-lost'

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY)
  },
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export class ApiError extends Error {
  status: number
  code?: string
  fields: Record<string, string[]>

  constructor(status: number, message: string, code?: string, fields: Record<string, string[]> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields
  }
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>

function buildQuery(params?: QueryParams) {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

function flatten(value: unknown): string {
  if (Array.isArray(value)) return value.map(flatten).join(' ')
  if (value && typeof value === 'object') return Object.values(value).map(flatten).join(' ')
  return String(value)
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // non-JSON error body (proxy error page, gateway timeout)
  }
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const record = body as Record<string, unknown>
    if (typeof record.detail === 'string') {
      return new ApiError(response.status, record.detail, typeof record.code === 'string' ? record.code : undefined)
    }
    const fields: Record<string, string[]> = {}
    for (const [key, value] of Object.entries(record)) {
      fields[key] = Array.isArray(value) ? value.map(flatten) : [flatten(value)]
    }
    const message = Object.entries(fields)
      .map(([key, messages]) => (key === 'non_field_errors' ? messages.join(' ') : `${key}: ${messages.join(' ')}`))
      .join('; ')
    return new ApiError(response.status, message || response.statusText, undefined, fields)
  }
  if (Array.isArray(body)) return new ApiError(response.status, flatten(body))
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    return new ApiError(response.status, 'The server is unavailable. Is the backend running?')
  }
  return new ApiError(response.status, response.statusText || `HTTP ${response.status}`)
}

let refreshing: Promise<boolean> | null = null

function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    const refresh = tokenStore.refresh
    if (!refresh) return false
    try {
      const response = await fetch(`${API_BASE}/accounts/auth/token/refresh/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      })
      if (!response.ok) return false
      const data = (await response.json()) as { access: string; refresh?: string }
      tokenStore.set(data.access, data.refresh)
      return true
    } catch {
      return false
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  query?: QueryParams
  json?: unknown
  form?: FormData
  auth?: boolean
  signal?: AbortSignal
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, json, form, auth = true, signal } = options
  const url = `${API_BASE}/${path.replace(/^\//, '')}${buildQuery(query)}`

  const send = () => {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (json !== undefined) headers['Content-Type'] = 'application/json'
    if (auth && tokenStore.access) headers.Authorization = `Bearer ${tokenStore.access}`
    return fetch(url, {
      method,
      headers,
      body: form ?? (json !== undefined ? JSON.stringify(json) : undefined),
      signal,
    })
  }

  let response = await send()
  if (response.status === 401 && auth && tokenStore.refresh) {
    if (await refreshAccessToken()) {
      response = await send()
    } else {
      tokenStore.clear()
      window.dispatchEvent(new Event(AUTH_LOST_EVENT))
    }
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function requestBlob(path: string, query?: QueryParams): Promise<Blob> {
  const url = `${API_BASE}/${path.replace(/^\//, '')}${buildQuery(query)}`
  const send = () => {
    const headers: Record<string, string> = {}
    if (tokenStore.access) headers.Authorization = `Bearer ${tokenStore.access}`
    return fetch(url, { headers })
  }
  let response = await send()
  if (response.status === 401 && tokenStore.refresh) {
    if (await refreshAccessToken()) {
      response = await send()
    } else {
      tokenStore.clear()
      window.dispatchEvent(new Event(AUTH_LOST_EVENT))
    }
  }
  if (!response.ok) throw await toApiError(response)
  return response.blob()
}

export const api = {
  get: <T>(path: string, query?: QueryParams, signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T>(path: string, json?: unknown) => request<T>(path, { method: 'POST', json }),
  patch: <T>(path: string, json?: unknown) => request<T>(path, { method: 'PATCH', json }),
  delete: <T = void>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', form }),
  downloadBlob: (path: string, query?: QueryParams) => requestBlob(path, query),
}

// Triggers a browser download of an authenticated-endpoint's file response (plain api.get can't:
// it always parses JSON). Used by the Research Lab Lecture tab's Export actions.
export async function downloadFile(path: string, query: QueryParams, filename: string): Promise<void> {
  const blob = await requestBlob(path, query)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

const MAX_PAGES = 20

// Follows DRF pagination; used where the UI aggregates over a whole collection (counts, analytics).
export async function fetchAll<T>(path: string, query: QueryParams = {}): Promise<T[]> {
  const results: T[] = []
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const data = await api.get<Paginated<T>>(path, { ...query, page_size: 200, page })
    results.push(...data.results)
    if (!data.next) break
  }
  return results
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
