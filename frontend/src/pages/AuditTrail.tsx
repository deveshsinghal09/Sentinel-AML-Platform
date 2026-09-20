import { useEffect, useState } from 'react'
import { getAuditEvents } from '../api'
import type { AuditEvent } from '../types'

const EVENT_TYPES = ['', 'query_received', 'plan_created', 'tool_executed', 'tool_skipped', 'alert_created', 'alert_assigned', 'analyst_note_added', 'alert_dispositioned']

export default function AuditTrail() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [eventType, setEventType] = useState('')
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getAuditEvents(eventType || undefined)
      .then((response) => {
        if (active) { setEvents(response.items); setTotal(response.total) }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Unable to load audit trail')
      })
    return () => { active = false }
  }, [eventType])

  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div><span className="eyebrow">Control evidence</span><h1>Audit trail</h1><p>Append-only agent decisions, tool executions, and analyst actions with reproducibility metadata.</p></div>
        <span className="metric-pill">{total} events</span>
      </header>
      <div className="audit-toolbar">
        <label><span>Event type</span><select value={eventType} onChange={(event) => setEventType(event.target.value)}>{EVENT_TYPES.map((type) => <option key={type || 'all'} value={type}>{type ? type.replaceAll('_', ' ') : 'All events'}</option>)}</select></label>
        <span>Read only · no public event-write API</span>
      </div>
      {error ? <div className="workspace-error">{error}</div> : null}
      <section className="audit-list">
        {events.map((event) => (
          <article className="audit-event" key={event.event_id}>
            <span className="audit-event__rail" />
            <div className="audit-event__heading">
              <div><strong>{event.event_type.replaceAll('_', ' ')}</strong><span>{new Date(event.created_at).toLocaleString()}</span></div>
              <span>{event.actor}</span>
            </div>
            <div className="audit-event__links"><code>{event.investigation_id ?? 'system'}</code>{event.alert_id ? <code>{event.alert_id}</code> : null}</div>
            <details><summary>Evidence payload</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>
            <footer><span>Policy {event.risk_policy_version}</span><span>Model {event.model_version}</span><span>{event.dataset_snapshot}</span></footer>
          </article>
        ))}
        {!events.length && !error ? <div className="workspace-loading">No audit events match this filter.</div> : null}
      </section>
    </main>
  )
}
