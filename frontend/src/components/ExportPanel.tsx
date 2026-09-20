import { useState } from 'react'
import { exportEntities, exportInvestigation, exportTrace } from '../api'

export default function ExportPanel({ investigationId }: { investigationId?: string | null }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label)
    setError('')
    try {
      await action()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Export failed')
    } finally {
      setBusy('')
    }
  }

  if (!investigationId) {
    return <p className="export-pending">Exports become available after the investigation is persisted.</p>
  }

  return (
    <section className="export-panel" aria-label="Export investigation">
      <div>
        <span className="section-kicker">Governed export</span>
        <strong>Download reviewer-ready evidence</strong>
        <small>Every file is tied to investigation {investigationId}.</small>
      </div>
      <div className="export-actions">
        <button disabled={Boolean(busy)} onClick={() => void run('csv', () => exportEntities(investigationId, 'csv'))}>Entities CSV</button>
        <button disabled={Boolean(busy)} onClick={() => void run('json', () => exportInvestigation(investigationId, 'json'))}>Evidence JSON</button>
        <button disabled={Boolean(busy)} onClick={() => void run('md', () => exportInvestigation(investigationId, 'md'))}>Report MD</button>
        <button disabled={Boolean(busy)} onClick={() => void run('trace', () => exportTrace(investigationId, 'csv'))}>Trace CSV</button>
      </div>
      {busy ? <span className="export-status" role="status">Preparing {busy}…</span> : null}
      {error ? <span className="export-error" role="alert">{error}</span> : null}
    </section>
  )
}
