import { MarkerType, ReactFlow, type Edge, type NodeTypes } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import type { WorkspaceState } from '@/api/types'
import { AgentNodeCard, type AgentFlowNode } from './AgentNode'
import { EDGE_DEFS, NODE_POSITIONS, edgeKey } from './workflow'

const nodeTypes: NodeTypes = { agent: AgentNodeCard }

const COLORS = { idle: '#e2e0de', done: '#a8a5a2', active: '#a21e39', revision: '#a3690f' }

// Edge state comes from real hand-off events only:
//   idle   - nothing has been handed over on this edge yet
//   done   - at least one hand-off happened
//   active - a hand-off event arrived over the socket in the last few seconds (animated)
// The graph is a fixed, non-interactive diagram (no pan/zoom), so the page keeps scrolling normally.
export function AgentGraph({
  state, selected, onSelect, activeEdges,
}: {
  state: WorkspaceState
  selected: string
  onSelect: (agent: string) => void
  activeEdges: Set<string>
}) {
  const nodes = useMemo<AgentFlowNode[]>(
    () => state.agents.map((agent) => ({
      id: agent.agent,
      type: 'agent',
      position: NODE_POSITIONS[agent.agent] ?? { x: 0, y: 0 },
      draggable: false,
      data: { agent, selected: selected === agent.agent },
    })),
    [state.agents, selected],
  )

  const edges = useMemo<Edge[]>(() => {
    const latest = new Map<string, WorkspaceState['handoffs'][number]>()
    for (const handoff of state.handoffs) latest.set(edgeKey(handoff.from, handoff.to), handoff)
    return EDGE_DEFS.map((def) => {
      const key = edgeKey(def.from, def.to)
      const last = latest.get(key)
      const active = activeEdges.has(key)
      const color = active ? COLORS.active : last?.revision ? COLORS.revision : last ? COLORS.done : COLORS.idle
      return {
        id: key,
        source: def.from,
        target: def.to,
        sourceHandle: def.sourceHandle,
        targetHandle: def.targetHandle,
        type: 'smoothstep',
        animated: active,
        style: {
          stroke: color,
          strokeWidth: active ? 2 : 1.25,
          strokeDasharray: last?.revision && !active ? '4 3' : undefined,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 12, height: 12 },
        zIndex: active ? 10 : last ? 5 : 0,
      }
    })
  }, [state.handoffs, activeEdges])

  return (
    <div className="h-[190px] w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect(node.id)}
        fitView
        fitViewOptions={{ padding: 0.04 }}
        minZoom={0.2}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        panOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      />
    </div>
  )
}
