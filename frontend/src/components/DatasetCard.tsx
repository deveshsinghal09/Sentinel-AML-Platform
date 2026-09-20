import type { DatasetInfo } from '../types'

interface Props {
  dataset: DatasetInfo
  busy: boolean
  onActivate: (dataset: DatasetInfo) => void
  onAnalyze: (dataset: DatasetInfo) => void
  onDelete: (dataset: DatasetInfo) => void
}

function formatBytes(value: number) {
  if (!value) return 'Managed source'
  const units = ['B', 'KB', 'MB', 'GB']
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount.toFixed(index ? 1 : 0)} ${units[index]}`
}

export default function DatasetCard({
  dataset,
  busy,
  onActivate,
  onAnalyze,
  onDelete,
}: Props) {
  const protectedDataset = dataset.dataset_id === 'ibm-hi-small-v1'
    || dataset.dataset_id === 'saml-d-knowledge-v1'

  return (
    <article
      className={`dataset-card${dataset.is_active ? ' dataset-card--active' : ''}`}
      aria-busy={busy}
    >
      <header>
        <div>
          <span className="section-kicker">{dataset.dataset_type} workspace</span>
          <h2>{dataset.display_name}</h2>
        </div>
        <span className={dataset.is_active ? 'dataset-state dataset-state--active' : 'dataset-state'}>
          {dataset.is_active ? 'Active' : 'Available'}
        </span>
      </header>
      <p>{dataset.notes || 'Governed analytical dataset workspace.'}</p>
      <div className="dataset-metrics">
        <div><strong>{dataset.row_count.toLocaleString()}</strong><span>Rows</span></div>
        <div><strong>{dataset.laundering_count.toLocaleString()}</strong><span>Known labels</span></div>
        <div><strong>{(dataset.laundering_rate * 100).toFixed(3)}%</strong><span>Label prevalence</span></div>
      </div>
      <dl className="dataset-lineage">
        <div><dt>Schema</dt><dd>{dataset.schema_detected || 'Managed'}</dd></div>
        <div><dt>Source</dt><dd>{dataset.source_file || 'Internal source'}</dd></div>
        <div><dt>Size</dt><dd>{formatBytes(dataset.file_size_bytes)}</dd></div>
        {dataset.date_min ? <div><dt>Coverage</dt><dd>{dataset.date_min} → {dataset.date_max}</dd></div> : null}
        <div><dt>Ingested</dt><dd>{new Date(dataset.ingested_at).toLocaleDateString()}</dd></div>
        <div><dt>Schema version</dt><dd>{dataset.schema_version}</dd></div>
        <div><dt>Fingerprint</dt><dd>{dataset.md5_fingerprint?.slice(0, 20) || 'Managed'}</dd></div>
      </dl>
      <div className="dataset-actions">
        {!dataset.is_active && dataset.dataset_type !== 'kyc'
          ? <button disabled={busy} onClick={() => onActivate(dataset)}>{busy ? 'Activating…' : 'Activate'}</button>
          : null}
        {dataset.dataset_type === 'primary'
          ? <button className="button-secondary" disabled={busy} onClick={() => onAnalyze(dataset)}>Analyze</button>
          : null}
        {!protectedDataset && !dataset.is_active
          ? <button className="button-danger" disabled={busy} onClick={() => onDelete(dataset)}>{busy ? 'Working…' : 'Delete'}</button>
          : null}
      </div>
    </article>
  )
}
