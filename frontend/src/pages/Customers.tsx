import { type FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCustomer, getCustomers } from '../api'
import type {
  CustomerDetail,
  CustomerPage,
  CustomerRiskLabel,
} from '../types'

const PAGE_SIZE = 25

function money(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export default function Customers() {
  const [searchDraft, setSearchDraft] = useState('')
  const [riskDraft, setRiskDraft] = useState<CustomerRiskLabel | ''>('')
  const [search, setSearch] = useState('')
  const [risk, setRisk] = useState<CustomerRiskLabel | ''>('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<CustomerPage | null>(null)
  const [selected, setSelected] = useState<CustomerDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    getCustomers({
      search,
      risk_label: risk,
      limit: PAGE_SIZE,
      offset,
    })
      .then((response) => {
        if (active) setPage(response)
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Unable to load customers')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [offset, risk, search])

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setSearch(searchDraft.trim())
    setRisk(riskDraft)
    setSelected(null)
  }

  const openCustomer = async (accountId: string) => {
    setDetailLoading(true)
    setError(null)
    try {
      setSelected(await getCustomer(accountId))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load customer')
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div><span className="eyebrow">Entity intelligence</span><h1>Customers</h1><p>Search accounts and inspect consolidated transaction behavior, counterparties, workflow alerts, and current risk.</p></div>
        <span className="metric-pill">{page?.total.toLocaleString() ?? '—'} accounts</span>
      </header>

      <form className="evidence-filters evidence-filters--customers" onSubmit={applyFilters}>
        <label><span>Account search</span><input aria-label="Account search" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Account ID contains…" /></label>
        <label><span>Risk</span><select aria-label="Risk filter" value={riskDraft} onChange={(event) => setRiskDraft(event.target.value as CustomerRiskLabel | '')}><option value="">All risk states</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="unscored">Unscored</option></select></label>
        <button type="submit">Search customers</button>
      </form>
      {error ? <div className="workspace-error" role="alert">{error}</div> : null}
      {loading ? <div className="workspace-loading">Aggregating customer activity…</div> : null}

      {!loading && page ? (
        <div className="customer-layout">
          <section className="evidence-table-panel">
            <div className="evidence-table-scroll">
              <table className="evidence-table">
                <thead><tr><th>Account</th><th>Risk</th><th>Activity</th><th>Sent</th><th>Received</th><th>Alerts</th></tr></thead>
                <tbody>
                  {page.items.map((customer) => (
                    <tr className={selected?.summary.account_id === customer.account_id ? 'row--selected' : ''} key={customer.account_id}>
                      <td><button className="entity-link" onClick={() => void openCustomer(customer.account_id)}><strong>{customer.account_id}</strong><small>Bank {customer.primary_bank || '—'}</small></button></td>
                      <td><span className={`customer-risk customer-risk--${customer.risk_label}`}>{customer.max_risk_score === null ? 'Unscored' : `${Math.round(customer.max_risk_score * 100)}% ${customer.risk_label}`}</span></td>
                      <td><strong>{(customer.outbound_count + customer.inbound_count).toLocaleString()}</strong><small>{customer.distinct_counterparties.toLocaleString()} counterparties</small></td>
                      <td>{money(customer.total_sent)}</td><td>{money(customer.total_received)}</td>
                      <td><strong>{customer.open_alert_count}</strong><small>{customer.alert_count} total</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!page.items.length ? <p className="panel-empty">No customers match these filters.</p> : null}
            </div>
            <div className="pagination-bar"><span>{page.total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, page.total)} of ${page.total.toLocaleString()}` : '0 results'}</span><div><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div></div>
          </section>

          <aside className="customer-detail">
            {detailLoading ? <div className="workspace-loading">Building customer profile…</div> : null}
            {!selected && !detailLoading ? <div className="detail-empty"><span>◎</span><h2>Select an account</h2><p>Open a customer to inspect behavior, relationships, and alert history.</p></div> : null}
            {selected && !detailLoading ? (
              <>
                <div className="detail-heading-row"><div><span className="section-kicker">Customer profile</span><h2>{selected.summary.account_id}</h2></div><span className={`customer-risk customer-risk--${selected.summary.risk_label}`}>{selected.summary.risk_label}</span></div>
                <div className="customer-facts"><div><strong>{selected.summary.outbound_count.toLocaleString()}</strong><span>Outbound</span></div><div><strong>{selected.summary.inbound_count.toLocaleString()}</strong><span>Inbound</span></div><div><strong>{selected.summary.distinct_counterparties.toLocaleString()}</strong><span>Counterparties</span></div><div><strong>{selected.known_laundering_transactions.toLocaleString()}</strong><span>Known labels</span></div></div>
                <h3>Top relationships</h3>
                <div className="counterparty-list">{selected.top_counterparties.map((item) => <div key={`${item.direction}-${item.account_id}`}><span><strong>{item.account_id}</strong><small>{item.direction} · {item.transaction_count.toLocaleString()} transactions</small></span><strong>{money(item.total_amount)}</strong></div>)}</div>
                <h3>Payment mix</h3><div className="country-chips">{Object.entries(selected.payment_formats).map(([format, count]) => <span key={format}>{format} · {count.toLocaleString()}</span>)}</div>
                <h3>Workflow alerts</h3><div className="customer-alerts">{selected.alerts.slice(0, 5).map((alert) => <div key={alert.alert_id}><span className={`status-badge status-badge--${alert.status}`}>{alert.status.replaceAll('_', ' ')}</span><strong>{Math.round(alert.risk_score * 100)}%</strong><small>{alert.saml_d_typology || alert.escalation_action.replaceAll('_', ' ')}</small></div>)}{!selected.alerts.length ? <p>No workflow alerts for this account.</p> : null}</div>
                <Link className="evidence-link-button" to={`/transactions?account_id=${encodeURIComponent(selected.summary.account_id)}`}>View linked transactions →</Link>
                <p className="source-label-note">“Known labels” are source-dataset ground truth for evaluation, not Sentinel predictions.</p>
              </>
            ) : null}
          </aside>
        </div>
      ) : null}
    </main>
  )
}
