import type {
  AgentResponse,
  ExecutionStep,
  FlaggedEntity,
  IntentResult,
  PlanResult,
  SummaryStats,
} from '../types'

export interface SavedInvestigation {
  id: string
  query: string
  timestamp: string
  intent: IntentResult
  plan: PlanResult
  execution_trace: ExecutionStep[]
  top_entities: FlaggedEntity[]
  summary_stats: SummaryStats
  status: 'open' | 'closed' | 'escalated'
  analyst_notes: string
  disposition: 'true_positive' | 'false_positive' | 'pending' | null
}

const STORAGE_KEY = 'sentinel_investigations'
const MAX_INVESTIGATIONS = 200

function newId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `INV-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function loadInvestigations(): SavedInvestigation[] {
  try {
    const payload = localStorage.getItem(STORAGE_KEY)
    if (!payload) return []
    const parsed = JSON.parse(payload)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveInvestigation(
  response: AgentResponse,
): SavedInvestigation {
  const investigation: SavedInvestigation = {
    id: newId(),
    query: response.query,
    timestamp: new Date().toISOString(),
    intent: response.intent,
    plan: response.plan,
    execution_trace: response.execution_trace,
    top_entities: response.top_entities,
    summary_stats: response.summary_stats,
    status: 'open',
    analyst_notes: '',
    disposition: 'pending',
  }
  const existing = loadInvestigations()
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(
        [investigation, ...existing].slice(0, MAX_INVESTIGATIONS),
      ),
    )
  } catch {
    // Investigation execution must still succeed if browser storage is full
    // or disabled. Server-side retention is introduced in Phase B.
  }
  return investigation
}
