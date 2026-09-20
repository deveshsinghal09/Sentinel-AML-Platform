import {
  type FormEvent,
  lazy,
  memo,
  Suspense,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { checkHealth, exportSar, getDatasets, runQuery } from '../api'
import { ExecutionTrace } from '../components/ExecutionTrace'
import ExportPanel from '../components/ExportPanel'
import RiskContributionBar from '../components/RiskContributionBar'
import RiskSummary from '../components/RiskSummary'
import TransactionEvidenceList from '../components/TransactionEvidenceList'
import UploadModal from '../components/UploadModal'
import { saveInvestigation } from '../store/investigations'
import type {
  AgentResponse,
  ApiStatus,
  DatasetUploadResult,
  FlaggedEntity,
  PlotlyChartData,
} from '../types'
import '../App.css'

const ReviewerChart = lazy(() => import('../charts/ReviewerChart'))

const EXAMPLES = [
  'Find structuring activity for account 803D95360',
  'Detect layering and circular transfer patterns',
  'Give me a broad exploratory analysis of this dataset',
  'Show transactions above $500,000',
]

const ACTION_LABELS: Record<string, string> = {
  monitor: 'Monitor',
  flag_for_review: 'Review',
  report: 'Report',
}

function formatLabel(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatFilterValue(value: unknown) {
  if (Array.isArray(value)) return value.join(' → ')
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

function Header({ status, datasetName }: { status: ApiStatus; datasetName: string }) {
  const statusLabel =
    status === 'online' ? 'API connected' : status === 'offline' ? 'API unavailable' : 'Checking API'

  return (
    <header className="site-header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <div>
          <strong>Sentinel AML</strong>
          <span>Suspicious activity intelligence</span>
        </div>
      </div>
      <div className="header-status">
        <span className="phase-badge">Evidence · {datasetName}</span>
        <span className={`api-status api-status--${status}`}>
          <span className="status-dot" aria-hidden="true" />
          {statusLabel}
        </span>
      </div>
    </header>
  )
}

interface QueryPanelProps {
  query: string
  loading: boolean
  onQueryChange: (value: string) => void
  onSubmit: (event: FormEvent) => void
  onExample: (query: string) => void
  onUploadDataset: () => void
}

function QueryPanel({
  query,
  loading,
  onQueryChange,
  onSubmit,
  onExample,
  onUploadDataset,
}: QueryPanelProps) {
  return (
    <section
      className={`query-hero${loading ? ' query-hero--active' : ''}`}
      aria-labelledby="query-heading"
    >
      <div className="hero-copy">
        <span className="eyebrow">Dynamic AML investigation</span>
        <h1 id="query-heading">
          Same transactions.<br />
          <em>Clearer risk.</em>
        </h1>
        <p>
          Describe an entity, pattern, or time window. Sentinel selects the
          smallest defensible toolchain and shows exactly what ran.
        </p>
      </div>

      <form className="query-box" onSubmit={onSubmit}>
        <div className="query-box__header">
          <label htmlFor="analyst-query">Investigation query</label>
          <button
            type="button"
            className="query-upload-action"
            onClick={onUploadDataset}
            disabled={loading}
          >
            <span aria-hidden="true">+</span>
            Upload dataset
          </button>
        </div>
        <div className="query-input-row">
          <textarea
            id="analyst-query"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="e.g. Find structuring activity for account 803D95360"
            rows={3}
            disabled={loading}
          />
          <button
            type="submit"
            className="button-primary"
            disabled={loading || !query.trim()}
          >
            {loading ? (
              <>
                <span className="spinner" aria-hidden="true" />
                Analysing
              </>
            ) : (
              <>
                Run analysis
                <span className="button-arrow" aria-hidden="true">
                  <span>↗</span><span>↗</span>
                </span>
              </>
            )}
          </button>
        </div>
        <div className="example-row" aria-label="Example queries">
          <span>Try</span>
          {EXAMPLES.map((example, index) => (
            <button
              type="button"
              className="example-chip"
              key={example}
              onClick={() => onExample(example)}
              disabled={loading}
            >
              <span>0{index + 1}</span>
              {example}
            </button>
          ))}
        </div>
      </form>
    </section>
  )
}

function IntentSummary({ response }: { response: AgentResponse }) {
  const filters = Object.entries(response.intent.filters).filter(
    ([, value]) => value !== null && value !== undefined && value !== '',
  )

  return (
    <section className="panel intent-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">01 · Interpretation</span>
          <h2>Intent & scope</h2>
        </div>
        <span className="confidence-chip">Validated</span>
      </div>
      <dl className="intent-grid">
        <div>
          <dt>Intent</dt>
          <dd>{formatLabel(response.intent.intent)}</dd>
        </div>
        <div>
          <dt>Pattern class</dt>
          <dd>
            {response.intent.pattern_type
              ? formatLabel(response.intent.pattern_type)
              : 'General analysis'}
          </dd>
        </div>
        <div>
          <dt>Plan depth</dt>
          <dd>{response.plan.steps.length} tools selected</dd>
        </div>
      </dl>
      <div className="filter-list">
        {filters.length ? (
          filters.map(([key, value]) => (
            <span className="filter-chip" key={key}>
              <small>{formatLabel(key)}</small>
              {formatFilterValue(value)}
            </span>
          ))
        ) : (
          <p className="muted-copy">No restrictive filters — capped dataset slice.</p>
        )}
      </div>
      <p className="plan-reasoning">{response.plan.reasoning}</p>
    </section>
  )
}

type SortKey = 'entity_id' | 'risk_score' | 'escalation_action'

function FlaggedTable({
  entities,
  onSelect,
}: {
  entities: FlaggedEntity[]
  onSelect: (entity: FlaggedEntity) => void
}) {
  const [sortKey, setSortKey] = useState<SortKey>('risk_score')
  const [ascending, setAscending] = useState(false)

  const sorted = useMemo(() => {
    return [...entities].sort((a, b) => {
      const left = a[sortKey]
      const right = b[sortKey]
      const result =
        typeof left === 'number' && typeof right === 'number'
          ? left - right
          : String(left).localeCompare(String(right))
      return ascending ? result : -result
    })
  }, [entities, sortKey, ascending])

  function changeSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setAscending((value) => !value)
    } else {
      setSortKey(nextKey)
      setAscending(nextKey !== 'risk_score')
    }
  }

  const sortGlyph = (key: SortKey) =>
    key === sortKey ? (ascending ? '↑' : '↓') : '↕'

  return (
    <section className="panel entity-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">03 · Prioritisation</span>
          <h2>Flagged entities</h2>
        </div>
        <span className="entity-count">{entities.length} shown</span>
      </div>
      {entities.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>
                  <button onClick={() => changeSort('entity_id')}>
                    Entity {sortGlyph('entity_id')}
                  </button>
                </th>
                <th>
                  <button onClick={() => changeSort('risk_score')}>
                    Risk {sortGlyph('risk_score')}
                  </button>
                </th>
                <th>Typology</th>
                <th>Rule signals</th>
                <th>
                  <button onClick={() => changeSort('escalation_action')}>
                    Action {sortGlyph('escalation_action')}
                  </button>
                </th>
                <th><span className="sr-only">Open details</span></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((entity) => (
                <tr key={entity.entity_id}>
                  <td>
                    <button className="entity-id" onClick={() => onSelect(entity)}>
                      {entity.entity_id}
                    </button>
                  </td>
                  <td>
                    <div className="risk-cell">
                      <span className={`risk-badge risk-badge--${entity.risk_label}`}>
                        {(entity.risk_score * 100).toFixed(0)}
                      </span>
                      <div>
                        <strong>{formatLabel(entity.risk_label)}</strong>
                        <span className="risk-bar">
                          <span
                            className={`risk-bar__fill risk-bar__fill--${entity.risk_label}`}
                            style={{ width: `${entity.risk_score * 100}%` }}
                          />
                        </span>
                      </div>
                    </div>
                  </td>
                  <td>{entity.saml_d_typology || '—'}</td>
                  <td>
                    <div className="rule-flags">
                      {entity.rule_flags.length
                        ? entity.rule_flags.slice(0, 2).map((flag) => (
                          <span key={flag}>{formatLabel(flag)}</span>
                        ))
                        : '—'}
                    </div>
                  </td>
                  <td>
                    <span className={`action-chip action-chip--${entity.escalation_action}`}>
                      {ACTION_LABELS[entity.escalation_action] ?? formatLabel(entity.escalation_action)}
                    </span>
                  </td>
                  <td>
                    <button
                      className="detail-button"
                      onClick={() => onSelect(entity)}
                      aria-label={`View details for ${entity.entity_id}`}
                    >
                      →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-panel">
          <span aria-hidden="true">✓</span>
          <div>
            <strong>No entities crossed the review threshold</strong>
            <p>The query completed successfully with no medium or high-risk entities.</p>
          </div>
        </div>
      )}
    </section>
  )
}

function EntityDetailDrawer({
  entity,
  investigationId,
  onClose,
}: {
  entity: FlaggedEntity | null
  investigationId?: string | null
  onClose: () => void
}) {
  const [exportError, setExportError] = useState('')
  const [exporting, setExporting] = useState('')
  useEffect(() => {
    if (!entity) return
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [entity, onClose])

  if (!entity) return null

  async function downloadSar(format: 'txt' | 'pdf') {
    if (!entity || !investigationId) return
    setExporting(format)
    setExportError('')
    try {
      await exportSar(entity.entity_id, investigationId, format)
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : 'SAR export failed')
    } finally {
      setExporting('')
    }
  }

  return (
    <div className="drawer-layer" role="presentation" onMouseDown={onClose}>
      <aside
        className="entity-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-header">
          <div>
            <span className="section-kicker">Entity investigation</span>
            <h2 id="drawer-title">{entity.entity_id}</h2>
          </div>
          <button className="close-button" onClick={onClose} aria-label="Close details">
            ×
          </button>
        </div>
        <div className="drawer-risk">
          <span className={`risk-score-large risk-score-large--${entity.risk_label}`}>
            {(entity.risk_score * 100).toFixed(0)}
          </span>
          <div>
            <strong>{formatLabel(entity.risk_label)} risk</strong>
            <span>{ACTION_LABELS[entity.escalation_action]}</span>
          </div>
        </div>
        <div
          className={`escalation-segments escalation-segments--${entity.escalation_action}`}
          role="group"
          aria-label={`Recommended action: ${ACTION_LABELS[entity.escalation_action]}`}
        >
          <span>Monitor</span>
          <span>Review</span>
          <span>Report</span>
        </div>
        <dl className="score-grid">
          <div><dt>Rules</dt><dd>{(entity.rule_score * 100).toFixed(0)}</dd></div>
          <div><dt>Statistical</dt><dd>{(entity.stat_score * 100).toFixed(0)}</dd></div>
          <div><dt>ML</dt><dd>{(entity.ml_score * 100).toFixed(0)}</dd></div>
        </dl>
        <RiskContributionBar contribution={entity.risk_contributions} />
        <section className="entity-facts" aria-label="Entity activity summary">
          <div><strong>{entity.txn_count.toLocaleString()}</strong><span>Transactions</span></div>
          <div><strong>${entity.total_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong><span>Observed value</span></div>
          <div><strong>{entity.distinct_counterparties.toLocaleString()}</strong><span>Counterparties</span></div>
        </section>
        <TransactionEvidenceList transactions={entity.top_transactions} />
        <section>
          <span className="drawer-label">Grounded explanation</span>
          <p>{entity.explanation || 'No explanation was generated.'}</p>
        </section>
        <section>
          <span className="drawer-label">SAR draft</span>
          <p>{entity.sar_draft || 'No SAR draft was generated.'}</p>
        </section>
        <section className="drawer-export">
          <span className="drawer-label">Export this entity</span>
          <p>Drafts require qualified human review before any filing.</p>
          <div className="export-actions">
            <button disabled={!investigationId || Boolean(exporting)} onClick={() => void downloadSar('txt')}>SAR Draft TXT</button>
            <button disabled={!investigationId || Boolean(exporting)} onClick={() => void downloadSar('pdf')}>SAR Draft PDF</button>
          </div>
          {exportError ? <span className="export-error">{exportError}</span> : null}
        </section>
        <section className="citation-box">
          <span className="drawer-label">Evidence citation</span>
          <p>{entity.citation || 'No citation available.'}</p>
        </section>
      </aside>
    </div>
  )
}

const EDACharts = memo(function EDACharts({ charts }: { charts: PlotlyChartData[] }) {
  if (!charts.length) return null

  return (
    <section className="panel charts-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">04 · Distribution view</span>
          <h2>Exploratory analysis</h2>
        </div>
        <span className="entity-count">{charts.length} charts</span>
      </div>
      <div className="charts-grid">
        {charts.map((chart) => (
          <article className="chart-card" key={chart.chart_id}>
            <h3>{chart.title}</h3>
            <ReviewerChart
              data={chart.data}
              layout={{
                ...chart.layout,
                autosize: true,
                paper_bgcolor: 'transparent',
                plot_bgcolor: 'transparent',
                font: { color: '#9ca3af', family: 'Inter, sans-serif', size: 12 },
                margin: { l: 58, r: 18, t: 18, b: 52 },
                xaxis: {
                  ...chart.layout.xaxis,
                  gridcolor: '#1f2937',
                  zerolinecolor: '#374151',
                },
                yaxis: {
                  ...chart.layout.yaxis,
                  gridcolor: '#1f2937',
                  zerolinecolor: '#374151',
                },
              }}
              config={{ displayModeBar: false, responsive: true }}
              useResizeHandler
              style={{ width: '100%', height: '330px' }}
            />
            {chart.meta?.note && <p className="chart-note">{chart.meta.note}</p>}
          </article>
        ))}
      </div>
    </section>
  )
})

function GraphSummary({ response }: { response: AgentResponse }) {
  const graph = response.graph
  if (!graph) return null

  const patternCount =
    graph.cycles.length +
    graph.fan_in.length +
    graph.fan_out.length +
    graph.bipartite.length +
    graph.gather_scatter.length +
    graph.scatter_gather.length

  return (
    <section className="panel graph-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">04 · Network topology</span>
          <h2>Graph findings</h2>
        </div>
        <span className={`graph-status graph-status--${graph.status}`}>{graph.status}</span>
      </div>
      <div className="graph-metrics">
        <div><strong>{graph.summary.nodes?.toLocaleString() ?? '—'}</strong><span>Accounts</span></div>
        <div><strong>{graph.summary.edges?.toLocaleString() ?? '—'}</strong><span>Directed edges</span></div>
        <div><strong>{graph.cycles.length}</strong><span>Cycles</span></div>
        <div><strong>{patternCount}</strong><span>Total patterns</span></div>
      </div>
      <p className="graph-note">{graph.note}</p>
    </section>
  )
}

const ResultsPanel = memo(function ResultsPanel({
  response,
  onSelectEntity,
}: {
  response: AgentResponse
  onSelectEntity: (entity: FlaggedEntity) => void
}) {
  return (
    <main className="results" aria-live="polite">
      <div className="results-heading">
        <div>
          <span className="eyebrow">Analysis complete</span>
          <h2>Investigation results</h2>
        </div>
        <span className="result-query">“{response.query}”</span>
      </div>
      <ExportPanel investigationId={response.investigation_id} />
      <div className="overview-grid">
        <IntentSummary response={response} />
        <ExecutionTrace steps={response.execution_trace} />
      </div>
      <RiskSummary stats={response.summary_stats} />
      {response.aggregation ? (
        <AggregationPanel aggregation={response.aggregation} />
      ) : null}
      <FlaggedTable entities={response.top_entities} onSelect={onSelectEntity} />
      {response.charts?.length ? (
        <Suspense fallback={<div className="workspace-loading">Loading reviewer charts…</div>}>
          <EDACharts charts={response.charts} />
        </Suspense>
      ) : null}
      <GraphSummary response={response} />
    </main>
  )
})

function AggregationPanel({
  aggregation,
}: {
  aggregation: NonNullable<AgentResponse['aggregation']>
}) {
  return (
    <section className="panel aggregation-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Direct aggregation</span>
          <h2>Threshold matches</h2>
        </div>
        <span className="entity-count">{aggregation.total_groups} groups</span>
      </div>
      {aggregation.rows.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Entity</th>
                <th>Transactions</th>
                <th>Total amount</th>
                <th>Average</th>
                <th>Counterparties</th>
                <th>Observed window</th>
              </tr>
            </thead>
            <tbody>
              {aggregation.rows.map((row) => (
                <tr key={row.entity_id}>
                  <td><strong>{row.entity_id}</strong></td>
                  <td>{row.txn_count.toLocaleString()}</td>
                  <td>${row.total_amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                  <td>${row.avg_amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                  <td>{row.distinct_counterparties.toLocaleString()}</td>
                  <td>{row.date_first.slice(0, 10)} → {row.date_last.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="panel-empty">No account groups matched the requested thresholds.</p>
      )}
    </section>
  )
}

function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [query, setQuery] = useState(
    () => searchParams.get('query')?.trim() || EXAMPLES[0],
  )
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<AgentResponse | null>(null)
  const [selectedEntity, setSelectedEntity] = useState<FlaggedEntity | null>(null)
  const [error, setError] = useState('')
  const [activeDataset, setActiveDataset] = useState<{ id: string; name: string } | null>(null)
  const [showUpload, setShowUpload] = useState(false)
  const [uploadedDataset, setUploadedDataset] = useState<DatasetUploadResult | null>(null)

  useEffect(() => {
    checkHealth()
      .then(() => setApiStatus('online'))
      .catch(() => setApiStatus('offline'))
    getDatasets()
      .then((datasets) => {
        const active = datasets.find(
          (dataset) => dataset.dataset_type === 'primary' && dataset.is_active,
        )
        setActiveDataset(
          active ? { id: active.dataset_id, name: active.display_name } : null,
        )
      })
      .catch(() => setActiveDataset(null))
  }, [])

  useEffect(() => {
    const routeQuery = searchParams.get('query')?.trim()
    if (routeQuery) setQuery(routeQuery)
  }, [searchParams])

  async function submitQuery(nextQuery: string) {
    const trimmed = nextQuery.trim()
    if (!trimmed || loading) return
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current)
        next.set('query', trimmed)
        return next
      },
      { replace: true },
    )
    setLoading(true)
    setError('')
    setSelectedEntity(null)
    try {
      const nextResponse = await runQuery(trimmed, activeDataset?.id)
      setResponse(nextResponse)
      saveInvestigation(nextResponse)
      setApiStatus('online')
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'The investigation could not be completed.',
      )
      setApiStatus('offline')
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void submitQuery(query)
  }

  function handleExample(example: string) {
    setQuery(example)
    void submitQuery(example)
  }

  function handleDatasetUploaded(result: DatasetUploadResult) {
    setShowUpload(false)
    setUploadedDataset(result)
    getDatasets()
      .then((datasets) => {
        const active = datasets.find(
          (dataset) => dataset.dataset_type === 'primary' && dataset.is_active,
        )
        setActiveDataset(
          active ? { id: active.dataset_id, name: active.display_name } : null,
        )
      })
      .catch(() => undefined)
  }

  return (
    <div className="command-center">
      <Header status={apiStatus} datasetName={activeDataset?.name ?? 'No active dataset'} />
      <QueryPanel
        query={query}
        loading={loading}
        onQueryChange={setQuery}
        onSubmit={handleSubmit}
        onExample={handleExample}
        onUploadDataset={() => setShowUpload(true)}
      />
      {uploadedDataset ? (
        <div className="query-upload-notice" role="status">
          <div>
            <strong>{uploadedDataset.display_name} uploaded successfully</strong>
            <span>
              {uploadedDataset.row_count.toLocaleString()} rows were validated in an
              isolated workspace.
            </span>
          </div>
          <Link to="/datasets">Review and activate</Link>
          <button
            type="button"
            aria-label="Dismiss upload confirmation"
            onClick={() => setUploadedDataset(null)}
          >
            {'\u00d7'}
          </button>
        </div>
      ) : null}
      {error && (
        <div className="error-banner" role="alert">
          <span aria-hidden="true">!</span>
          <div>
            <strong>Analysis unavailable</strong>
            <p>{error}</p>
          </div>
          <button onClick={() => setError('')} aria-label="Dismiss error">×</button>
        </div>
      )}
      {response ? (
        <ResultsPanel response={response} onSelectEntity={setSelectedEntity} />
      ) : (
        <section className="empty-state">
          <span className="empty-orbit" aria-hidden="true"><span /></span>
          <div>
            <span className="section-kicker">Ready for investigation</span>
            <h2>Your decision trail will appear here</h2>
            <p>Run a query to see selected tools, risk scores, grounded explanations, and escalation actions.</p>
          </div>
        </section>
      )}
      <EntityDetailDrawer
        entity={selectedEntity}
        investigationId={response?.investigation_id}
        onClose={() => setSelectedEntity(null)}
      />
      {showUpload ? (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onUploaded={handleDatasetUploaded}
        />
      ) : null}
      <footer>
        <span>Sentinel AML · Decision-support system</span>
        <span>Human review required before reporting</span>
      </footer>
    </div>
  )
}

export default CommandCenter
