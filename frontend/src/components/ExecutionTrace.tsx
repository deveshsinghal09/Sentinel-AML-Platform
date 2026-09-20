import type { CSSProperties } from 'react'
import type { ExecutionStep } from '../types'

const TOOL_LABELS: Record<string, string> = {
  data_loader: 'Data loader',
  aggregation: 'Threshold aggregation',
  eda: 'Exploratory analysis',
  feature_engineering: 'Feature engineering',
  rule_engine: 'Rule engine',
  statistical: 'Statistical detector',
  ml_engine: 'ML detector',
  graph_tool: 'Graph analysis',
  risk_scorer: 'Risk scorer',
  escalation: 'Escalation',
  explanation: 'Explanation',
}

function formatLabel(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatDuration(durationMs: number) {
  if (!durationMs) return '—'
  return durationMs >= 1_000
    ? `${(durationMs / 1_000).toFixed(2)}s`
    : `${durationMs.toFixed(durationMs < 10 ? 1 : 0)}ms`
}

function TraceItem({ step, index }: { step: ExecutionStep; index: number }) {
  const isRun = step.status === 'run'
  const style = { '--trace-delay': `${index * 65}ms` } as CSSProperties

  return (
    <li
      className={`trace-item trace-item--${step.status}`}
      style={style}
      aria-label={`${TOOL_LABELS[step.tool] ?? formatLabel(step.tool)} ${
        isRun ? 'executed' : 'skipped'
      }`}
    >
      <span className="trace-marker" aria-hidden="true">
        {isRun ? '✓' : '×'}
      </span>
      <div className="trace-tool">
        <strong>{TOOL_LABELS[step.tool] ?? formatLabel(step.tool)}</strong>
        <code>{step.tool}</code>
      </div>
      <span className="trace-duration">{formatDuration(step.duration_ms)}</span>
      <p>{step.reason}</p>
    </li>
  )
}

export function ExecutionTrace({ steps }: { steps: ExecutionStep[] }) {
  const ran = steps.filter((step) => step.status === 'run').length
  const skipped = steps.length - ran
  const durationMs = steps.reduce(
    (total, step) => total + step.duration_ms,
    0,
  )

  return (
    <section className="panel trace-panel" aria-label="Agent execution trace">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">02 · Execution trace</span>
          <h2>Decision path</h2>
        </div>
        <span className="trace-count">{ran}/{steps.length} selected</span>
      </div>
      <p className="muted-copy" role="status">
        {ran} tools ran · {skipped} skipped · {formatDuration(durationMs)} total
      </p>
      {steps.length ? (
        <ol className="trace-list">
          {steps.map((step, index) => (
            <TraceItem
              key={`${step.tool}-${step.status}-${index}`}
              step={step}
              index={index}
            />
          ))}
        </ol>
      ) : (
        <p className="panel-empty">
          No tools were selected for this investigation.
        </p>
      )}
    </section>
  )
}
