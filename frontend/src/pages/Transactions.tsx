import { type FormEvent, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getTransactionPaymentFormats, getTransactions } from '../api'
import type { TransactionFilters, TransactionPage, TransactionRecord } from '../types'

const PAGE_SIZE = 50
const initialFilters = (accountId: string): TransactionFilters => ({
  account_id: accountId,
  direction: 'both',
  limit: PAGE_SIZE,
  offset: 0,
})

function amount(value: number, currency: string) {
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value)} ${currency}`
}

export default function Transactions() {
  const [params, setParams] = useSearchParams()
  const initialAccount = params.get('account_id') ?? ''
  const [draft, setDraft] = useState<TransactionFilters>(initialFilters(initialAccount))
  const [filters, setFilters] = useState<TransactionFilters>(initialFilters(initialAccount))
  const [page, setPage] = useState<TransactionPage | null>(null)
  const [formats, setFormats] = useState<string[]>([])
  const [selected, setSelected] = useState<TransactionRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getTransactionPaymentFormats().then((response) => setFormats(response.items)).catch(() => setFormats([]))
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true); setError(null)
    getTransactions(filters)
      .then((response) => {
        if (active) {
          setPage(response)
          setSelected((current) => response.items.find((item) => item.transaction_id === current?.transaction_id) ?? null)
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Unable to load transactions')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [filters])

  const applyFilters = (event: FormEvent) => {
    event.preventDefault()
    const next = { ...draft, account_id: draft.account_id?.trim(), limit: PAGE_SIZE, offset: 0 }
    setFilters(next)
    setParams(next.account_id ? { account_id: next.account_id } : {})
    setSelected(null)
  }
  const reset = () => {
    const next = initialFilters('')
    setDraft(next); setFilters(next); setParams({}); setSelected(null)
  }
  const movePage = (nextOffset: number) => setFilters((current) => ({ ...current, offset: nextOffset }))

  return (
    <main className="workspace-page workspace-page--wide">
      <header className="workspace-page__header">
        <div><span className="eyebrow">Evidence browser</span><h1>Transactions</h1><p>Filter governed transaction evidence by account, direction, date, payment format, amount, or source label.</p></div>
        <span className="metric-pill">{page?.total.toLocaleString() ?? '—'} matches</span>
      </header>
      <form className="evidence-filters transaction-filter-grid" onSubmit={applyFilters}>
        <label><span>Account ID</span><input aria-label="Transaction account" value={draft.account_id ?? ''} onChange={(event) => setDraft({ ...draft, account_id: event.target.value })} placeholder="Optional exact account" /></label>
        <label><span>Direction</span><select aria-label="Direction" value={draft.direction ?? 'both'} onChange={(event) => setDraft({ ...draft, direction: event.target.value as TransactionFilters['direction'] })}><option value="both">Both</option><option value="outbound">Outbound</option><option value="inbound">Inbound</option></select></label>
        <label><span>Payment format</span><select aria-label="Payment format" value={draft.payment_format ?? ''} onChange={(event) => setDraft({ ...draft, payment_format: event.target.value })}><option value="">All formats</option>{formats.map((format) => <option key={format}>{format}</option>)}</select></label>
        <label><span>Minimum amount</span><input aria-label="Minimum amount" type="number" min="0" value={draft.min_amount ?? ''} onChange={(event) => setDraft({ ...draft, min_amount: event.target.value ? Number(event.target.value) : undefined })} /></label>
        <label><span>Maximum amount</span><input aria-label="Maximum amount" type="number" min="0" value={draft.max_amount ?? ''} onChange={(event) => setDraft({ ...draft, max_amount: event.target.value ? Number(event.target.value) : undefined })} /></label>
        <label><span>From date</span><input aria-label="From date" type="date" value={draft.date_from ?? ''} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} /></label>
        <label><span>To date</span><input aria-label="To date" type="date" value={draft.date_to ?? ''} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} /></label>
        <label className="checkbox-field"><input type="checkbox" checked={draft.laundering_only ?? false} onChange={(event) => setDraft({ ...draft, laundering_only: event.target.checked })} /><span>Known laundering labels only</span></label>
        <div className="filter-actions"><button type="submit">Apply filters</button><button type="button" onClick={reset}>Reset</button></div>
      </form>
      {error ? <div className="workspace-error" role="alert">{error}</div> : null}
      {loading ? <div className="workspace-loading">Loading bounded transaction evidence…</div> : null}
      {!loading && page ? (
        <div className="transaction-layout">
          <section className="evidence-table-panel">
            <div className="evidence-table-scroll">
              <table className="evidence-table transaction-table">
                <thead><tr><th>Time / ID</th><th>From</th><th>To</th><th>Amount paid</th><th>Format</th><th>Source label</th></tr></thead>
                <tbody>{page.items.map((transaction) => <tr className={selected?.transaction_id === transaction.transaction_id ? 'row--selected' : ''} key={transaction.transaction_id} onClick={() => setSelected(transaction)}><td><strong>{new Date(transaction.timestamp).toLocaleString()}</strong><small>{transaction.transaction_id}</small></td><td><strong>{transaction.from_account}</strong><small>Bank {transaction.from_bank}</small></td><td><strong>{transaction.to_account}</strong><small>Bank {transaction.to_bank}</small></td><td>{amount(transaction.amount_paid, transaction.paying_currency)}</td><td>{transaction.payment_format}</td><td>{transaction.is_laundering ? <span className="source-label source-label--positive">Known laundering</span> : <span className="source-label">Not labelled</span>}</td></tr>)}</tbody>
              </table>
              {!page.items.length ? <p className="panel-empty">No transactions match these filters.</p> : null}
            </div>
            <div className="pagination-bar"><span>{page.total ? `${(filters.offset ?? 0) + 1}–${Math.min((filters.offset ?? 0) + PAGE_SIZE, page.total)} of ${page.total.toLocaleString()}` : '0 results'}</span><div><button disabled={(filters.offset ?? 0) === 0} onClick={() => movePage(Math.max(0, (filters.offset ?? 0) - PAGE_SIZE))}>Previous</button><button disabled={(filters.offset ?? 0) + PAGE_SIZE >= page.total} onClick={() => movePage((filters.offset ?? 0) + PAGE_SIZE)}>Next</button></div></div>
          </section>
          <aside className="transaction-detail">
            {selected ? <><span className="section-kicker">Evidence record</span><h2>{selected.transaction_id}</h2><dl className="transaction-facts"><div><dt>Timestamp</dt><dd>{new Date(selected.timestamp).toLocaleString()}</dd></div><div><dt>Payment format</dt><dd>{selected.payment_format}</dd></div><div><dt>Sender</dt><dd>{selected.from_account} · Bank {selected.from_bank}</dd></div><div><dt>Recipient</dt><dd>{selected.to_account} · Bank {selected.to_bank}</dd></div><div><dt>Paid</dt><dd>{amount(selected.amount_paid, selected.paying_currency)}</dd></div><div><dt>Received</dt><dd>{amount(selected.amount_received, selected.receiving_currency)}</dd></div></dl><div className={selected.is_laundering ? 'source-disclosure source-disclosure--positive' : 'source-disclosure'}><strong>{selected.is_laundering ? 'Known laundering source label' : 'No laundering source label'}</strong><p>This field is dataset ground truth for evaluation. It is not a Sentinel risk prediction or analyst disposition.</p></div></> : <div className="detail-empty"><span>⇄</span><h2>Select a transaction</h2><p>Open a row to inspect complete transfer evidence and currencies.</p></div>}
          </aside>
        </div>
      ) : null}
    </main>
  )
}
