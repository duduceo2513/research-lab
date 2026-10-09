import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import {
  BookOpen, ClipboardList, Download, FileText, Globe, GraduationCap, Network, ScanSearch, ShieldCheck, type LucideIcon,
} from 'lucide-react'
import { memo, type CSSProperties } from 'react'
import type { WorkspaceAgent } from '@/api/types'
import { cn } from '@/lib/utils'
import { StatusGlyph, shortModel, shortStatus, statusMeta } from './meta'
import { NODE_HEIGHT, NODE_WIDTH, type HandleId } from './workflow'

export interface AgentNodeData extends Record<string, unknown> {
  agent: WorkspaceAgent
  selected: boolean
}

export type AgentFlowNode = Node<AgentNodeData, 'agent'>

const ICONS: Record<string, LucideIcon> = {
  boss: Network, web_research: Globe, academic_research: GraduationCap, document_retrieval: Download, document_analysis: FileText,
  source_validator: ShieldCheck, lecture_builder: BookOpen, assignment_generator: ClipboardList,
  final_reviewer: ScanSearch,
}

const HANDLES: { id: HandleId; type: 'source' | 'target'; position: Position; style?: CSSProperties }[] = [
  { id: 'left-in', type: 'target', position: Position.Left },
  { id: 'right-out', type: 'source', position: Position.Right },
  { id: 'top-in', type: 'target', position: Position.Top, style: { left: '35%' } },
  { id: 'top-out', type: 'source', position: Position.Top, style: { left: '65%' } },
  { id: 'bottom-in', type: 'target', position: Position.Bottom, style: { left: '35%' } },
  { id: 'bottom-out', type: 'source', position: Position.Bottom, style: { left: '65%' } },
]

// A fixed-size card: icon, name, status · model. Nothing else — details live in the agent peek.
function AgentNodeView({ data }: NodeProps<AgentFlowNode>) {
  const { agent, selected } = data
  const meta = statusMeta(agent.status)
  const Icon = ICONS[agent.agent] ?? Network
  const dim = ['disabled', 'not_run'].includes(agent.status)
  const idle = ['waiting', 'queued'].includes(agent.status)

  return (
    <div
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      title={agent.status === 'disabled' ? agent.disabled_reason : undefined}
      className={cn(
        'flex flex-col justify-center rounded-md border bg-white px-2.5 transition-colors',
        meta.live ? 'border-accent bg-accent-soft/50' : meta.tone === 'bad' ? 'border-critical/50'
          : meta.tone === 'warn' ? 'border-warn/50' : 'border-border-strong',
        selected && 'ring-2 ring-ink/60',
        (dim || idle) && 'opacity-60',
        dim && 'border-dashed',
      )}
    >
      {HANDLES.map((handle) => (
        <Handle key={handle.id} {...handle} isConnectable={false} className="!h-1 !w-1 !border-0 !bg-transparent" />
      ))}
      <div className="flex items-center gap-1.5">
        <Icon className={cn('h-3.5 w-3.5 shrink-0', meta.live ? 'text-accent' : 'text-ink-muted')} strokeWidth={2} />
        <span className="truncate text-[12px] font-semibold text-ink">{agent.name}</span>
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-muted">
        <StatusGlyph status={agent.status} compact />
        <span className="truncate">{shortStatus(agent.status)} · {shortModel(agent)}</span>
      </div>
    </div>
  )
}

export const AgentNodeCard = memo(AgentNodeView)
