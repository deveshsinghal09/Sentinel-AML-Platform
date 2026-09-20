import type { TransactionEvidence } from '../types'

function formatTimestamp(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('en', {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(parsed)
}

export default function TransactionEvidenceList({
  transactions,
}: {
  transactions: TransactionEvidence[]
}) {
  return (
    <section className="evidence-section">
      <div className="evidence-section__heading">
        <span className="drawer-label">Supporting transactions</span>
        <span>{transactions.length} shown</span>
      </div>
      {transactions.length ? (
        <div className="evidence-list">
          {transactions.map((transaction) => (
            <article className="evidence-item" key={transaction.txn_id}>
              <div>
                <strong>${transaction.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong>
                <span>{transaction.payment_format || 'Unknown format'} → {transaction.to_account || 'Unknown counterparty'}</span>
              </div>
              <time>{formatTimestamp(transaction.timestamp)}</time>
              {transaction.triggered_rules.length ? (
                <div className="evidence-tags">
                  {transaction.triggered_rules.map((rule) => (
                    <span key={rule}>{rule.replaceAll('_', ' ')}</span>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className="panel-empty">No supporting transaction rows are available.</p>
      )}
    </section>
  )
}
