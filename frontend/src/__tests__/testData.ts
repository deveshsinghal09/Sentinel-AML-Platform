import type {
  AgentResponse,
  DatasetInfo,
  InvestigationRecord,
  InvestigationSummary,
} from '../types'

export const dataset: DatasetInfo = {
  dataset_id: 'primary-v1',
  display_name: 'Primary evidence',
  source_file: 'transactions.csv',
  dataset_type: 'primary',
  file_size_bytes: 1_024,
  row_count: 120,
  laundering_count: 2,
  laundering_rate: 0.0167,
  date_min: '2026-06-01',
  date_max: '2026-06-30',
  schema_version: '1.0',
  md5_fingerprint: '1234567890abcdef1234567890abcdef',
  ingested_at: '2026-07-26T10:00:00Z',
  is_active: true,
  notes: 'Governed primary evidence.',
  column_map: {},
  schema_detected: 'ibm_aml',
}

export const knowledgeDataset: DatasetInfo = {
  ...dataset,
  dataset_id: 'knowledge-v1',
  display_name: 'SAML-D knowledge',
  dataset_type: 'knowledge',
  is_active: false,
  schema_detected: 'saml_d',
}

export const agentResponse: AgentResponse = {
  investigation_id: 'INV-001',
  dataset_id: dataset.dataset_id,
  dataset_name: dataset.display_name,
  query: 'Find structuring in June',
  intent: {
    intent: 'pattern_search',
    pattern_type: 'structuring',
    filters: {
      date_range: ['2026-06-01', '2026-06-30'],
      entity_id: null,
      from_country: null,
      payment_format: null,
      min_amount: null,
      max_amount: 10_000,
      min_count: null,
    },
    entities: [],
    require_ml: false,
    require_graph: false,
    require_eda: false,
  },
  plan: {
    steps: ['data_loader', 'feature_engineering', 'rule_engine', 'risk_engine'],
    skipped: [
      {
        tool: 'eda',
        reason: 'Broad profiling is unnecessary for this targeted request.',
      },
      {
        tool: 'ml_engine',
        reason: 'Deterministic evidence is sufficient.',
      },
    ],
    reasoning: 'Targeted structuring analysis uses only justified tools.',
  },
  execution_trace: [
    {
      tool: 'data_loader',
      status: 'run',
      duration_ms: 12,
      reason: 'Loaded the filtered June slice.',
    },
    {
      tool: 'eda',
      status: 'skipped',
      duration_ms: 0,
      reason: 'Targeted request.',
    },
  ],
  top_entities: [
    {
      entity_id: 'ACC-17',
      risk_score: 0.88,
      risk_label: 'high',
      escalation_action: 'report',
      rule_flags: ['STRUCTURING'],
      rule_score: 0.88,
      stat_score: 0,
      ml_score: 0,
      saml_d_typology: 'structuring',
      explanation: 'Eight sub-threshold transactions in four days.',
      sar_draft: 'Draft requiring review.',
      citation: 'https://www.fincen.gov/guidance',
      risk_contributions: null,
      top_transactions: [],
      txn_count: 8,
      total_amount: 78_400,
      observation_window: ['2026-06-04', '2026-06-07'],
      distinct_counterparties: 6,
    },
  ],
  summary_stats: {
    total_analyzed: 120,
    flagged: 1,
    high_risk: 1,
  },
  eda_summary: null,
  charts: null,
  graph: null,
  aggregation: null,
}

export const investigationSummaries: InvestigationSummary[] = [
  {
    investigation_id: 'INV-001',
    dataset_id: dataset.dataset_id,
    dataset_name: dataset.display_name,
    query: agentResponse.query,
    intent: 'pattern_search',
    pattern_type: 'structuring',
    status: 'open',
    disposition: 'pending',
    flagged_count: 1,
    high_risk_count: 1,
    alert_count: 1,
    created_at: '2026-07-26T10:00:00Z',
    updated_at: '2026-07-26T10:00:00Z',
  },
  {
    investigation_id: 'INV-002',
    dataset_id: dataset.dataset_id,
    dataset_name: dataset.display_name,
    query: 'Find layering networks',
    intent: 'pattern_search',
    pattern_type: 'layering',
    status: 'closed',
    disposition: 'false_positive',
    flagged_count: 0,
    high_risk_count: 0,
    alert_count: 0,
    created_at: '2026-07-25T10:00:00Z',
    updated_at: '2026-07-25T12:00:00Z',
  },
]

export const investigationRecord: InvestigationRecord = {
  ...investigationSummaries[0],
  response: agentResponse,
}
