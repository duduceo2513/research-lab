import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, tokenStore } from './client'
import type { ResearchEvent, WorkspaceState } from './types'

export type WorkspaceSocketStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

const CLOSE_UNAUTHENTICATED = 4401
const CLOSE_NOT_FOUND = 4404
const PING_INTERVAL_MS = 25_000
const MAX_BACKOFF_MS = 10_000
// Snapshot refresh after an event burst, and the polling used only while the socket is down.
const REFRESH_DEBOUNCE_MS = 500
const FALLBACK_POLL_MS = 3000
const MAX_EVENTS_KEPT = 3000
// How long an edge stays highlighted after a hand-off event arrived over the socket.
export const HANDOFF_FLASH_MS = 5000

function socketUrl(runId: number, token: string) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/ws/research-lab/runs/${runId}/?token=${encodeURIComponent(token)}`
}

const workspaceKey = (runId: number | undefined) => ['research-lab/runs', 'workspace', runId]

// Everything the Agent Workspace shows comes from the backend:
//   * `workspace` — a server-computed snapshot (statuses, models, counts, load), refetched whenever
//     events arrive, so a reload restores the exact state;
//   * `events` — the persisted event journal (history from REST, then live over the WebSocket);
//   * `flashes` — hand-offs that arrived live in the last few seconds, used to light up graph edges.
// The WebSocket is only a notification channel: nothing lives only there. State is per run, so the
// caller remounts this hook's component (key={runId}) when the run changes.
export function useResearchWorkspace(runId: number | undefined, isActive: boolean) {
  const queryClient = useQueryClient()
  const [events, setEvents] = useState<ResearchEvent[]>([])
  const [socketStatus, setSocketStatus] = useState<WorkspaceSocketStatus>('connecting')
  const [closeReason, setCloseReason] = useState<string | null>(null)
  const [flashes, setFlashes] = useState<Record<string, number>>({})
  const [now, setNow] = useState(() => Date.now())
  const seen = useRef(new Set<number>())
  const lastId = useRef(0)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const workspace = useQuery({
    queryKey: workspaceKey(runId),
    queryFn: () => api.get<WorkspaceState>(`research-lab/runs/${runId}/workspace/`),
    enabled: runId !== undefined,
    refetchInterval: isActive && socketStatus !== 'open' ? FALLBACK_POLL_MS : false,
  })

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) return
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = undefined
      void queryClient.invalidateQueries({ queryKey: workspaceKey(runId) })
    }, REFRESH_DEBOUNCE_MS)
  }, [queryClient, runId])

  const addEvents = useCallback((incoming: ResearchEvent[], live: boolean) => {
    const fresh = incoming.filter((event) => !seen.current.has(event.id))
    if (fresh.length === 0) return
    for (const event of fresh) {
      seen.current.add(event.id)
      lastId.current = Math.max(lastId.current, event.id)
    }
    setEvents((current) => [...current, ...fresh].sort((a, b) => a.id - b.id).slice(-MAX_EVENTS_KEPT))
    if (live) {
      const handoffs = fresh.filter((event) => event.type === 'agent_handoff')
      if (handoffs.length) {
        const stamp = Date.now()
        setFlashes((current) => {
          const next = { ...current }
          for (const event of handoffs) next[`${event.payload.from_agent}>${event.payload.to_agent}`] = stamp
          return next
        })
      }
    }
    scheduleRefresh()
  }, [scheduleRefresh])

  // History: everything persisted so far (also used to fill the gap after a reconnect).
  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    if (runId === undefined) return
    for (;;) {
      const rows = await api.get<ResearchEvent[]>(
        `research-lab/runs/${runId}/events/`, { after_id: lastId.current, limit: 2000 }, signal)
      addEvents(rows, false)
      if (rows.length < 2000) return
    }
  }, [runId, addEvents])

  useEffect(() => {
    if (runId === undefined) return undefined
    const controller = new AbortController()
    loadHistory(controller.signal).catch(() => undefined)
    return () => controller.abort()
  }, [runId, loadHistory])

  useEffect(() => {
    if (runId === undefined) return undefined
    let disposed = false
    let attempt = 0
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let pingTimer: ReturnType<typeof setInterval> | undefined
    let socket: WebSocket | null = null

    const connect = () => {
      const token = tokenStore.access
      if (!token) {
        setSocketStatus('closed')
        setCloseReason('Your session expired. Sign in again.')
        return
      }
      socket = new WebSocket(socketUrl(runId, token))
      socket.onopen = () => {
        attempt = 0
        setSocketStatus('open')
        setCloseReason(null)
        pingTimer = setInterval(() => socket?.send(JSON.stringify({ action: 'ping' })), PING_INTERVAL_MS)
        // Anything written while we were not listening is recovered from the database.
        loadHistory().catch(() => undefined)
        scheduleRefresh()
      }
      socket.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data as string) as { event: string; payload: ResearchEvent }
          if (data.event === 'research_event') addEvents([data.payload], true)
        } catch {
          // ignore malformed frames
        }
      }
      socket.onclose = (closeEvent) => {
        clearInterval(pingTimer)
        if (disposed) return
        if (closeEvent.code === CLOSE_UNAUTHENTICATED && attempt === 0) {
          // The access token may just have expired: a REST call refreshes it, then retry once.
          attempt += 1
          setSocketStatus('reconnecting')
          api.get('accounts/me/').then(() => !disposed && connect()).catch(() => {
            setSocketStatus('closed')
            setCloseReason('Your session expired. Sign in again.')
          })
          return
        }
        if (closeEvent.code === CLOSE_NOT_FOUND || closeEvent.code === 4403 || closeEvent.code === CLOSE_UNAUTHENTICATED) {
          setSocketStatus('closed')
          setCloseReason('Live updates are not available for this run.')
          return
        }
        setSocketStatus('reconnecting')
        attempt += 1
        retryTimer = setTimeout(connect, Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS))
      }
    }

    connect()
    return () => {
      disposed = true
      clearTimeout(retryTimer)
      clearInterval(pingTimer)
      clearTimeout(refreshTimer.current)
      refreshTimer.current = undefined
      socket?.close()
    }
  }, [runId, addEvents, loadHistory, scheduleRefresh])

  // A 1s clock only while a hand-off highlight is still fading, so idle pages do not re-render.
  const flashing = Object.values(flashes).some((stamp) => now - stamp < HANDOFF_FLASH_MS)
  useEffect(() => {
    if (!flashing) return undefined
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [flashing])

  const activeEdges = useMemo(() => {
    const result = new Set<string>()
    for (const [key, stamp] of Object.entries(flashes)) if (now - stamp < HANDOFF_FLASH_MS) result.add(key)
    return result
  }, [flashes, now])

  return { workspace, events, socketStatus, closeReason, activeEdges }
}

// The same server-computed snapshot without the socket, for tabs that only need the numbers.
export function useWorkspaceSnapshot(runId: number | undefined, isActive: boolean) {
  return useQuery({
    queryKey: workspaceKey(runId),
    queryFn: () => api.get<WorkspaceState>(`research-lab/runs/${runId}/workspace/`),
    enabled: runId !== undefined,
    refetchInterval: isActive ? FALLBACK_POLL_MS : false,
  })
}
