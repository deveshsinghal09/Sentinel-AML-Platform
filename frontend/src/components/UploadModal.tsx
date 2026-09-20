import { type DragEvent, type FormEvent, useEffect, useState } from 'react'
import { inspectDataset, uploadDataset } from '../api'
import type { DatasetInfo, DatasetInspection, DatasetUploadResult } from '../types'

const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB || 25)

interface Props {
  onClose: () => void
  onUploaded: (result: DatasetUploadResult) => void
}

export default function UploadModal({ onClose, onUploaded }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [type, setType] = useState<DatasetInfo['dataset_type']>('primary')
  const [inspection, setInspection] = useState<DatasetInspection | null>(null)
  const [stage, setStage] = useState<'idle' | 'inspecting' | 'ingesting'>('idle')
  const [error, setError] = useState('')

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && stage !== 'ingesting') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose, stage])

  async function chooseFile(next: File | null) {
    if (!next) return
    const supported = /\.(csv|xlsx)$/i.test(next.name)
    const maxUploadMb = MAX_UPLOAD_MB
    if (!supported || next.size > maxUploadMb * 1024 * 1024) {
      setFile(null)
      setInspection(null)
      setError(
        !supported
          ? 'Choose a CSV or Excel (.xlsx) file.'
          : `Files larger than ${maxUploadMb} MB require the controlled batch-ingestion process.`,
      )
      return
    }
    setFile(next)
    setName(next.name.replace(/\.[^.]+$/, ''))
    setInspection(null)
    setError('')
    setStage('inspecting')
    try {
      setInspection(await inspectDataset(next))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to inspect dataset')
    } finally {
      setStage('idle')
    }
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault()
    void chooseFile(event.dataTransfer.files[0] ?? null)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file || !name.trim()) return
    setStage('ingesting')
    setError('')
    try {
      const result = await uploadDataset(file, name.trim(), type)
      onUploaded(result)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to ingest dataset')
      setStage('idle')
    }
  }

  return (
    <div className="modal-layer" role="presentation" onMouseDown={() => stage !== 'ingesting' && onClose()}>
      <section className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title" aria-describedby="upload-description" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><span className="section-kicker">Governed import</span><h2 id="upload-title">Upload dataset</h2><p id="upload-description">Inspect schema and mappings before creating an isolated evidence workspace.</p></div>
          <button type="button" className="close-button" disabled={stage === 'ingesting'} onClick={onClose} aria-label="Close upload">×</button>
        </header>
        <form onSubmit={submit}>
          <label className="upload-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
            <input aria-label="Dataset file" type="file" accept=".csv,.xlsx" onChange={(event) => void chooseFile(event.target.files?.[0] ?? null)} />
            <strong>{file ? file.name : 'Drop CSV or Excel here'}</strong>
            <span>{file ? `${(file.size / 1024).toFixed(1)} KB selected` : `CSV or XLSX, up to ${MAX_UPLOAD_MB} MB · inspected before ingest`}</span>
          </label>
          <div className="upload-fields">
            <label><span>Dataset name</span><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /></label>
            <label><span>Dataset type</span><select value={type} onChange={(event) => setType(event.target.value as DatasetInfo['dataset_type'])}><option value="primary">Primary transactions</option><option value="knowledge">AML knowledge</option><option value="kyc">KYC enrichment</option></select></label>
          </div>
          {stage === 'inspecting' ? <div className="upload-progress" role="status">Inspecting schema and required fields…</div> : null}
          {inspection ? (
            <section className="schema-preview">
              <header><div><span>Detected schema</span><strong>{inspection.schema_detected}</strong></div><span>{inspection.columns.length} columns</span></header>
              <div className="mapping-list">{Object.entries(inspection.column_map).map(([canonical, source]) => <span key={canonical}><strong>{canonical}</strong> ← {source}</span>)}</div>
              {inspection.preview.length ? <div className="preview-scroll"><table><thead><tr>{Object.keys(inspection.preview[0]).slice(0, 5).map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{inspection.preview.slice(0, 3).map((row, index) => <tr key={index}>{Object.keys(inspection.preview[0]).slice(0, 5).map((column) => <td key={column}>{String(row[column] ?? '')}</td>)}</tr>)}</tbody></table></div> : null}
              {inspection.warnings.map((warning) => <p className="schema-warning" key={warning}>{warning}</p>)}
            </section>
          ) : null}
          {error ? <div className="workspace-error" role="alert">{error}</div> : null}
          <footer>
            <button type="button" className="button-secondary" disabled={stage === 'ingesting'} onClick={onClose}>Cancel</button>
            <button type="submit" disabled={!file || !inspection || stage !== 'idle'}>{stage === 'ingesting' ? 'Validating and ingesting…' : 'Start governed ingest'}</button>
          </footer>
        </form>
      </section>
    </div>
  )
}
