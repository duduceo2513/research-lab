// Static topology of the Research Lab workflow: a fixed, compact left-to-right layout (7 columns, at
// most 2 rows) and the hand-offs that can happen. Whether an edge is idle, done or lit up comes from
// real `agent_handoff` events — never from here.

export const NODE_WIDTH = 172
export const NODE_HEIGHT = 48

const COL = NODE_WIDTH + 34
const ROW_TOP = 0
const ROW_BOTTOM = NODE_HEIGHT + 22
const ROW_MID = (ROW_TOP + ROW_BOTTOM) / 2

export const NODE_POSITIONS: Record<string, { x: number; y: number }> = {
  boss: { x: 0, y: ROW_MID },
  web_research: { x: COL, y: ROW_TOP },
  academic_research: { x: COL, y: ROW_BOTTOM },
  document_retrieval: { x: COL * 2, y: ROW_MID },
  document_analysis: { x: COL * 3, y: ROW_MID },
  source_validator: { x: COL * 4, y: ROW_MID },
  lecture_builder: { x: COL * 5, y: ROW_TOP },
  assignment_generator: { x: COL * 5, y: ROW_BOTTOM },
  final_reviewer: { x: COL * 6, y: ROW_MID },
}

export type HandleId =
  | 'top-in' | 'top-out' | 'bottom-in' | 'bottom-out' | 'left-in' | 'left-out' | 'right-in' | 'right-out'

export interface EdgeDef {
  from: string
  to: string
  sourceHandle: HandleId
  targetHandle: HandleId
}

const forward = (from: string, to: string): EdgeDef =>
  ({ from, to, sourceHandle: 'right-out', targetHandle: 'left-in' })

export const EDGE_DEFS: EdgeDef[] = [
  forward('boss', 'web_research'),
  forward('boss', 'academic_research'),
  forward('web_research', 'document_retrieval'),
  forward('academic_research', 'document_retrieval'),
  forward('document_retrieval', 'document_analysis'),
  forward('document_analysis', 'source_validator'),
  forward('source_validator', 'lecture_builder'),
  forward('source_validator', 'assignment_generator'),
  forward('lecture_builder', 'final_reviewer'),
  forward('assignment_generator', 'final_reviewer'),
  // The reviewer sending work back loops around over/under the author columns.
  { from: 'final_reviewer', to: 'lecture_builder', sourceHandle: 'top-out', targetHandle: 'top-in' },
  { from: 'final_reviewer', to: 'assignment_generator', sourceHandle: 'bottom-out', targetHandle: 'bottom-in' },
]

export const edgeKey = (from: string, to: string) => `${from}>${to}`
