import { useEffect, useMemo, useState } from 'react'
import { addAlertNote, assignAlert, dispositionAlert, getQueue } from '../api'
import type { AlertQueueItem, WorkflowStatus } from '../types'

const TABS: Array<{ label: string; value: WorkflowStatus | 'all' }> = [
  { label: 'All', value: 'all' }, { label: 'New', value: 'new' },
  { label: 'In review', value: 'in_review' }, { label: 'Escalated', value: 'escalated' },
  { label: 'Closed', value: 'closed' },
]

export default function ReviewQueue() {
  const [items, setItems] = useState<AlertQueueItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<WorkflowStatus | 'all'>('all')
  const [assignee, setAssignee] = useState('demo.analyst')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      const response = await getQueue(tab === 'all' ? undefined : tab)
      setItems(response.items)
      setSelectedId((current) => response.items.some((item) => item.alert_id === current) ? current : response.items[0]?.alert_id ?? null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load review queue')
    }
  }
  useEffect(() => { void load() }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps

  const selected = useMemo(() => items.find((item) => item.alert_id === selectedId) ?? null, [items, selectedId])
  const mutate = async (operation: () => Promise<AlertQueueItem>) => {
    setBusy(true); setError(null)
    try {
      const updated = await operation()
      setItems((current) => current.map((item) => item.alert_id === updated.alert_id ? updated : item))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Workflow action failed')
    } finally { setBusy(false) }
  }

  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div><span className="eyebrow">Analyst operations</span><h1>Review queue</h1><p>Risk-ranked alerts with ownership, SLA context, notes, and human disposition.</p></div>
        <span className="metric-pill">{items.length} visible</span>
      </header>
      <div className="queue-tabs" role="tablist" aria-label="Queue status">
        {TABS.map((item) => <button className={tab === item.value ? 'queue-tab queue-tab--active' : 'queue-tab'} key={item.value} onClick={() => setTab(item.value)} role="tab">{item.label}</button>)}
      </div>
      {error ? <div className="workspace-error">{error}</div> : null}

      {items.length ? (
        <div className="queue-layout">
          <section className="queue-list" aria-label="Alerts">
            <div className="queue-list__head"><span>Entity / alert</span><span>Risk</span><span>SLA</span><span>Status</span></div>
            {items.map((item) => {
              const remaining = item.sla_hours - item.age_hours
              return (
                <button className={selectedId === item.alert_id ? 'queue-row queue-row--active' : 'queue-row'} key={item.alert_id} onClick={() => setSelectedId(item.alert_id)}>
                  <span><strong>{item.entity_id}</strong><small>{item.alert_id}</small></span>
                  <span><strong className={`risk-text risk-text--${item.risk_label}`}>{Math.round(item.risk_score * 100)}%</strong><small>{item.risk_label}</small></span>
                  <span><strong className={remaining < 0 ? 'sla-breached' : ''}>{remaining < 0 ? 'Breached' : `${Math.ceil(remaining)}h`}</strong><small>{item.sla_hours}h target</small></span>
                  <span><span className={`status-badge status-badge--${item.status}`}>{item.status.replaceAll('_', ' ')}</span></span>
                </button>
              )
            })}
          </section>

          {selected ? (
            <aside className="queue-detail">
              <div className="detail-heading-row">
                <div><span className="section-kicker">Case triage</span><h2>{selected.entity_id}</h2></div>
                <strong className={`risk-orb risk-orb--${selected.risk_label}`}>{Math.round(selected.risk_score * 100)}%</strong>
              </div>
              <dl className="detail-facts">
                <div><dt>Typology</dt><dd>{selected.saml_d_typology || 'Unclassified anomaly'}</dd></div>
                <div><dt>Recommendation</dt><dd>{selected.escalation_action.replaceAll('_', ' ')}</dd></div>
                <div><dt>Owner</dt><dd>{selected.assigned_to ?? 'Unassigned'}</dd></div>
                <div><dt>Disposition</dt><dd>{selected.disposition?.replaceAll('_', ' ') ?? 'Pending'}</dd></div>
              </dl>
              <label className="workflow-field"><span>Assign analyst</span><div><input value={assignee} onChange={(event) => setAssignee(event.target.value)} /><button disabled={busy || !assignee.trim()} onClick={() => void mutate(() => assignAlert(selected.alert_id, assignee))}>Assign</button></div></label>
              <label className="workflow-field"><span>Add immutable note event</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Document evidence reviewed or rationale…" /><button disabled={busy || !note.trim()} onClick={() => void mutate(async () => { const updated = await addAlertNote(selected.alert_id, note); setNote(''); return updated })}>Append note</button></label>
              {selected.notes ? <pre className="analyst-notes">{selected.notes}</pre> : null}
              <div className="disposition-actions">
                <span>Analyst disposition</span>
                <div>
                  <button disabled={busy} onClick={() => void mutate(() => dispositionAlert(selected.alert_id, 'true_positive'))}>True positive</button>
                  <button disabled={busy} onClick={() => void mutate(() => dispositionAlert(selected.alert_id, 'false_positive'))}>False positive</button>
                  <button className="button--danger" disabled={busy} onClick={() => void mutate(() => dispositionAlert(selected.alert_id, 'escalated'))}>Escalate</button>
                </div>
                <small>SAR filing remains outside this demo and requires an authorized compliance workflow.</small>
              </div>
            </aside>
          ) : null}
        </div>
      ) : <section className="workspace-placeholder"><span className="workspace-placeholder__mark" aria-hidden="true">✓</span><div><h2>No alerts in this view</h2><p>Run an investigation or select another queue status.</p></div></section>}
    </main>
  )
}
