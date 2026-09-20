import type { Data, Layout } from 'plotly.js'

export type ApiStatus = 'checking' | 'online' | 'offline'
export type RiskLabel = 'low' | 'medium' | 'high'
export type EscalationAction = 'monitor' | 'flag_for_review' | 'report'

export interface ApiErrorPayload {
  detail?: string
  code?: string
  request_id?: string
}

export type WorkspaceRouteId =
  | 'command'
  | 'investigations'
  | 'queue'
  | 'customers'
  | 'transactions'
  | 'datasets'
  | 'model'
  | 'audit'
  | 'policy'

export interface WorkspaceRouteMetadata {
  id: WorkspaceRouteId
  path: string
  title: string
  context: string
}

export interface IntentFilters {
  date_range: [string, string] | null
  entity_id: string | null
  from_country: string | null
  payment_format: string | null
  min_amount: number | null
  max_amount: number | null
  min_count: number | null
}

export interface IntentResult {
  intent: 'pattern_search' | 'aggregation' | 'entity_lookup' | 'broad_eda'
  pattern_type: string | null
  filters: IntentFilters
  entities: string[]
  require_ml: boolean
  require_graph: boolean
  require_eda: boolean
}

export interface SkippedTool {
  tool: string
  reason: string
}

export interface PlanResult {
  steps: string[]
  skipped: SkippedTool[]
  reasoning: string
}

export interface ExecutionStep {
  tool: string
  status: 'run' | 'skipped'
  duration_ms: number
  reason: string
}

export interface FlaggedEntity {
  entity_id: string
  risk_score: number
  risk_label: RiskLabel
  escalation_action: EscalationAction
  rule_flags: string[]
  rule_score: number
  stat_score: number
  ml_score: number
  saml_d_typology: string
  explanation: string
  sar_draft: string
  citation: string
  risk_contributions: RiskContribution | null
  top_transactions: TransactionEvidence[]
  txn_count: number
  total_amount: number
  observation_window: [string, string] | null
  distinct_counterparties: number
}

export interface TransactionEvidence {
  txn_id: string
  timestamp: string
  amount: number
  payment_format: string
  to_account: string
  from_country: string | null
  to_country: string | null
  triggered_rules: string[]
}

export interface RiskContribution {
  rule_score: number
  rule_weight: number
  rule_contribution: number
  stat_score: number
  stat_weight: number
  stat_contribution: number
  ml_score: number
  ml_weight: number
  ml_contribution: number
  country_boost: number
  active_detector_count: number
  final_risk_score: number
  formula: string
}

export interface AggregationRow {
  entity_id: string
  txn_count: number
  total_amount: number
  avg_amount: number
  min_amount: number
  max_amount: number
  date_first: string
  date_last: string
  distinct_counterparties: number
  risk_score: number
  risk_label: RiskLabel
}

export interface AggregationResult {
  rows: AggregationRow[]
  total_groups: number
  filter_applied: Record<string, unknown>
  group_by_field: string
}

export interface SummaryStats {
  total_analyzed: number
  flagged: number
  high_risk: number
}

export interface PlotlyChartData {
  chart_id: string
  title: string
  data: Data[]
  layout: Partial<Layout>
  meta?: {
    note?: string
    [key: string]: unknown
  }
}

export interface GraphResult {
  status: 'ok' | 'skipped'
  summary: {
    input_rows: number
    nodes: number | null
    edges: number | null
    self_loops: number
    density: number
  }
  cycles: unknown[]
  fan_in: unknown[]
  fan_out: unknown[]
  bipartite: unknown[]
  gather_scatter: unknown[]
  scatter_gather: unknown[]
  note: string
}

export interface AgentResponse {
  investigation_id?: string | null
  dataset_id?: string | null
  dataset_name?: string | null
  query: string
  intent: IntentResult
  plan: PlanResult
  execution_trace: ExecutionStep[]
  top_entities: FlaggedEntity[]
  summary_stats: SummaryStats
  eda_summary?: Record<string, unknown> | null
  charts?: PlotlyChartData[] | null
  graph?: GraphResult | null
  aggregation?: AggregationResult | null
}

export interface HealthResponse {
  status: 'ok'
  phase: string
}

export interface ModelCard {
  model_id: string
  model_type: string
  library: string
  library_version: string
  algorithm: string
  training_dataset: string
  training_rows: number
  contamination_rate: number
  random_state: number
  n_estimators: number
  features: string[]
  feature_count: number
  score_range: {
    raw_min: number
    raw_max: number
  }
  decision_rule: string
  normalization: string
  status: string
  drift_status: string
  limitations: string[]
  grounding: string
}

export interface DriftFeature {
  feature: string
  psi: number
  status: 'stable' | 'caution' | 'drift'
  baseline_mean: number
  current_mean: number
}

export interface ModelDriftReport {
  model_id: string
  method: 'population_stability_index'
  status: 'stable' | 'caution' | 'drift'
  overall_psi: number
  thresholds: {
    stable_below: number
    drift_above: number
  }
  baseline_rows: number
  current_rows: number
  features: DriftFeature[]
  compared_at: string
  interpretation: string
  current_dataset: string
  baseline_dataset: string
}

export type WorkflowStatus = 'new' | 'in_review' | 'escalated' | 'closed'
export type AlertDisposition =
  | 'pending'
  | 'true_positive'
  | 'false_positive'
  | 'escalated'
  | 'sar_filed'

export interface InvestigationSummary {
  investigation_id: string
  dataset_id?: string | null
  dataset_name?: string | null
  query: string
  intent: string
  pattern_type: string | null
  status: 'open' | 'in_review' | 'escalated' | 'closed'
  disposition: string | null
  flagged_count: number
  high_risk_count: number
  alert_count: number
  created_at: string
  updated_at: string
}

export interface InvestigationRecord extends InvestigationSummary {
  response: AgentResponse
}

export interface AlertQueueItem {
  alert_id: string
  entity_id: string
  risk_score: number
  risk_label: RiskLabel
  escalation_action: EscalationAction
  saml_d_typology: string
  created_at: string
  sla_hours: number
  age_hours: number
  assigned_to: string | null
  status: WorkflowStatus
  disposition: AlertDisposition | null
  investigation_id: string
  notes: string
}

export interface QueueSummary {
  total: number
  new: number
  in_review: number
  escalated: number
  closed: number
}

export interface QueueResponse {
  items: AlertQueueItem[]
  returned: number
  summary: QueueSummary
}

export interface AuditEvent {
  event_id: string
  event_type: string
  actor: string
  investigation_id: string | null
  alert_id: string | null
  payload: Record<string, unknown>
  risk_policy_version: string
  model_version: string
  dataset_snapshot: string
  created_at: string
}

export interface AuditResponse {
  items: AuditEvent[]
  total: number
  limit: number
  offset: number
}

export interface PolicyResponse {
  version: string
  effective_date: string
  approved_by: string
  jurisdiction: string
  currency: string
  mode: 'read_only'
  thresholds: Record<string, number>
  risk_weights: Record<string, number>
  high_risk_countries: string[]
  change_history: unknown[]
  limitations: string[]
}

export interface DatasetInfo {
  dataset_id: string
  display_name: string
  source_file: string | null
  dataset_type: 'primary' | 'knowledge' | 'kyc'
  file_size_bytes: number
  row_count: number
  laundering_count: number
  laundering_rate: number
  date_min: string | null
  date_max: string | null
  schema_version: string
  md5_fingerprint: string | null
  ingested_at: string
  is_active: boolean
  notes: string
  column_map: Record<string, string>
  schema_detected: string
}

export interface DatasetUploadResult {
  dataset_id: string
  display_name: string
  row_count: number
  schema_detected: string
  warnings: string[]
  eda_summary: Record<string, unknown>
}

export interface DatasetInspection {
  schema_detected: string
  column_map: Record<string, string>
  columns: string[]
  preview: Record<string, unknown>[]
  warnings: string[]
}

export interface DatasetSwitchResult {
  previous_dataset_id: string | null
  active_dataset_id: string
  row_count: number
  message: string
}

export type CustomerRiskLabel = RiskLabel | 'unscored'

export interface CustomerSummary {
  account_id: string
  primary_bank: string
  outbound_count: number
  inbound_count: number
  total_sent: number
  total_received: number
  max_transaction: number
  distinct_counterparties: number
  first_seen: string
  last_seen: string
  alert_count: number
  open_alert_count: number
  max_risk_score: number | null
  risk_label: CustomerRiskLabel
}

export interface CounterpartySummary {
  account_id: string
  transaction_count: number
  total_amount: number
  direction: 'inbound' | 'outbound'
}

export interface CustomerDetail {
  summary: CustomerSummary
  payment_formats: Record<string, number>
  currencies: string[]
  known_laundering_transactions: number
  top_counterparties: CounterpartySummary[]
  alerts: AlertQueueItem[]
}

export interface CustomerPage {
  items: CustomerSummary[]
  total: number
  limit: number
  offset: number
}

export interface CustomerFilters {
  search?: string
  risk_label?: CustomerRiskLabel | ''
  limit?: number
  offset?: number
}

export interface TransactionRecord {
  transaction_id: string
  timestamp: string
  from_bank: string
  from_account: string
  to_bank: string
  to_account: string
  amount_paid: number
  amount_received: number
  paying_currency: string
  receiving_currency: string
  payment_format: string
  is_laundering: boolean
}

export interface TransactionPage {
  items: TransactionRecord[]
  total: number
  limit: number
  offset: number
}

export interface TransactionFilters {
  account_id?: string
  direction?: 'both' | 'inbound' | 'outbound'
  payment_format?: string
  min_amount?: number
  max_amount?: number
  date_from?: string
  date_to?: string
  laundering_only?: boolean
  limit?: number
  offset?: number
}
