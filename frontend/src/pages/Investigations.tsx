import { useEffect, useMemo, useState } from 'react'
import { getInvestigation, getInvestigations } from '../api'
import type { InvestigationRecord, InvestigationSummary } from '../types'

function formatDate(value: string) {
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export default function Investigations() {
  const [items, setItems] = useState<InvestigationSummary[]>([])
  const [selected, setSelected] = useState<InvestigationRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    let active = true
    getInvestigations()
      .then(async (records) => {
        if (!active) return
        setItems(records)
        if (records[0]) setSelected(await getInvestigation(records[0].investigation_id))
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Unable to load investigations')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [refreshVersion])

  const selectRecord = async (record: InvestigationSummary) => {
    setDetailLoading(true)
    setError(null)
    try {
      setSelected(await getInvestigation(record.investigation_id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load investigation')
    } finally {
      setDetailLoading(false)
    }
  }

  const filteredItems = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    return items.filter((record) => {
      const matchesStatus = statusFilter === 'all' || record.status === statusFilter
      const matchesSearch = !query
        || record.query.toLocaleLowerCase().includes(query)
        || record.investigation_id.toLocaleLowerCase().includes(query)
        || (record.pattern_type ?? '').toLocaleLowerCase().includes(query)
      return matchesStatus && matchesSearch
    })
  }, [items, search, statusFilter])

  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div>
          <span className="eyebrow">Decision history</span>
          <h1>Investigations</h1>
          <p>Server-retained query, plan, evidence, and outcome records.</p>
        </div>
        <span className="metric-pill">{items.length} retained</span>
      </header>

      <section className="workspace-toolbar" aria-label="Investigation filters">
        <label>
          <span>Search register</span>
          <input
            type="search"
            value={search}
            placeholder="Query, ID, or typology"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          <span>Workflow status</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="open">Open</option>
            <option value="in_review">In review</option>
            <option value="escalated">Escalated</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <button
          className="button-secondary"
          disabled={loading}
          onClick={() => {
            setLoading(true)
            setRefreshVersion((value) => value + 1)
          }}
        >
          {loading ? 'Refreshing…' : 'Refresh register'}
        </button>
      </section>

      {error ? <div className="workspace-error" role="alert">{error}</div> : null}
      {loading ? <div className="workspace-loading">Loading investigation register…</div> : null}

      {!loading && items.length ? (
        <div className="investigation-layout">
          <section className="investigation-list" aria-label="Investigation history">
            <p className="register-count">{filteredItems.length} of {items.length} investigations shown</p>
            {filteredItems.map((record) => (
              <button
                className={`investigation-card${selected?.investigation_id === record.investigation_id ? ' investigation-card--active' : ''}`}
                key={record.investigation_id}
                onClick={() => void selectRecord(record)}
              >
                <span>{formatDate(record.created_at)} · {record.investigation_id}</span>
                <strong>{record.query}</strong>
                <div>
                  <span>{record.intent.replaceAll('_', ' ')}</span>
                  <span>{record.flagged_count} flagged</span>
                  <span>{record.status.replaceAll('_', ' ')}</span>
                </div>
              </button>
            ))}
            {!filteredItems.length
              ? <p className="panel-empty">No investigations match these filters.</p>
              : null}
          </section>

          {selected ? (
            <section className="investigation-detail" aria-busy={detailLoading}>
              <div className="detail-heading-row">
                <span className="section-kicker">Investigation record</span>
                <span className={`status-badge status-badge--${selected.status}`}>{selected.status.replaceAll('_', ' ')}</span>
              </div>
              <h2>{selected.query}</h2>
              <dl className="investigation-context">
                <div><dt>Dataset</dt><dd>{selected.dataset_name || selected.dataset_id || 'Active at execution'}</dd></div>
                <div><dt>Intent</dt><dd>{selected.intent.replaceAll('_', ' ')}</dd></div>
                <div><dt>Typology</dt><dd>{selected.pattern_type?.replaceAll('_', ' ') || 'Broad analysis'}</dd></div>
                <div><dt>Disposition</dt><dd>{selected.disposition?.replaceAll('_', ' ') || 'Pending'}</dd></div>
              </dl>
              <div className="investigation-detail__metrics">
                <div><strong>{selected.response.summary_stats.total_analyzed}</strong><span>Analyzed</span></div>
                <div><strong>{selected.flagged_count}</strong><span>Flagged</span></div>
                <div><strong>{selected.high_risk_count}</strong><span>High risk</span></div>
              </div>
              <h3>Agent decision</h3>
              <p className="decision-reasoning">{selected.response.plan.reasoning}</p>
              <h3>Execution plan</h3>
              <ol className="compact-plan">
                {selected.response.plan.steps.map((step) => <li key={step}>{step.replaceAll('_', ' ')}</li>)}
              </ol>
              {selected.response.plan.skipped.length ? (
                <>
                  <h3>Deliberately skipped</h3>
                  <ul className="skipped-plan">
                    {selected.response.plan.skipped.map((step) => (
                      <li key={step.tool}><strong>{step.tool.replaceAll('_', ' ')}</strong><span>{step.reason}</span></li>
                    ))}
                  </ul>
                </>
              ) : null}
              {selected.response.top_entities[0] ? (
                <>
                  <h3>Highest-risk result</h3>
                  <div className="investigation-finding">
                    <div><strong>{selected.response.top_entities[0].entity_id}</strong><span>{selected.response.top_entities[0].risk_label} · {(selected.response.top_entities[0].risk_score * 100).toFixed(0)}%</span></div>
                    <p>{selected.response.top_entities[0].explanation || 'Evidence explanation is pending.'}</p>
                  </div>
                </>
              ) : null}
              <p className="investigation-retention-note">Persisted in the governed workflow store with versioned audit events.</p>
            </section>
          ) : null}
        </div>
      ) : null}

      {!loading && !items.length ? (
        <section className="workspace-placeholder">
          <span className="workspace-placeholder__mark" aria-hidden="true">⌕</span>
          <div><h2>No retained investigations</h2><p>Run an analysis from Command center. Its response and decision trace will be retained here.</p></div>
        </section>
      ) : null}
    </main>
  )
}
