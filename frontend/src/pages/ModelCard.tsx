import { useEffect, useState } from 'react'
import { getModelCard, getModelDrift } from '../api'
import type { ModelCard as ModelCardData, ModelDriftReport } from '../types'

const FEATURE_DESCRIPTIONS: Record<string, string> = {
  txn_count_7d: 'Seven-day sending frequency',
  rolling_sum_7d: 'Seven-day aggregate transaction value',
  near_threshold_count: 'Repeated values close to the reporting threshold',
  amount_deviation: 'Deviation from the account’s normal transaction value',
  velocity_1hr: 'One-hour transaction burst intensity',
  fan_in_count: 'Distinct inbound counterparties',
}

export default function ModelCard() {
  const [card, setCard] = useState<ModelCardData | null>(null)
  const [drift, setDrift] = useState<ModelDriftReport | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([getModelCard(), getModelDrift()])
      .then(([modelCard, driftReport]) => {
        setCard(modelCard)
        setDrift(driftReport)
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : 'Model card unavailable'),
      )
  }, [])

  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div>
          <span className="eyebrow">Model governance</span>
          <h1>Model intelligence</h1>
          <p>Transparent methodology, training provenance, limits, and serving controls.</p>
        </div>
        <span className={`model-status${card ? ' model-status--live' : ''}`}>
          {card?.status.replaceAll('_', ' ') ?? 'Loading'}
        </span>
      </header>

      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      {!card && !error ? <div className="model-loading">Loading active model metadata…</div> : null}
      {card ? (
        <>
          <section className="model-metrics">
            <article><span>Model</span><strong>{card.model_type}</strong><small>{card.model_id}</small></article>
            <article><span>Training scale</span><strong>{card.training_rows.toLocaleString()}</strong><small>normal-behaviour rows</small></article>
            <article><span>Contamination</span><strong>{(card.contamination_rate * 100).toFixed(2)}%</strong><small>training assumption</small></article>
            <article><span>Estimators</span><strong>{card.n_estimators}</strong><small>{card.library} {card.library_version}</small></article>
          </section>

          <div className="model-grid">
            <section className="panel model-panel">
              <div className="panel-heading">
                <div><span className="section-kicker">Feature contract</span><h2>Serving features</h2></div>
                <span className="entity-count">{card.feature_count}</span>
              </div>
              <div className="feature-contract">
                {card.features.map((feature, index) => (
                  <div key={feature}>
                    <span>{String(index + 1).padStart(2, '0')}</span>
                    <div><strong>{feature}</strong><p>{FEATURE_DESCRIPTIONS[feature] ?? 'Model-ready AML behavioral feature'}</p></div>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel model-panel">
              <div className="panel-heading">
                <div><span className="section-kicker">Operational controls</span><h2>Score contract</h2></div>
              </div>
              <dl className="model-definition-list">
                <div><dt>Training dataset</dt><dd>{card.training_dataset}</dd></div>
                <div><dt>Decision rule</dt><dd>{card.decision_rule}</dd></div>
                <div><dt>Normalization</dt><dd>{card.normalization}</dd></div>
                <div><dt>Raw score range</dt><dd>{card.score_range.raw_min.toFixed(4)} → {card.score_range.raw_max.toFixed(4)}</dd></div>
                <div><dt>Drift monitoring</dt><dd className="warning-text">{card.drift_status.replaceAll('_', ' ')}</dd></div>
              </dl>
            </section>
          </div>

          <section className="panel limitations-panel">
            <div className="panel-heading">
              <div><span className="section-kicker">Required reading</span><h2>Known limitations</h2></div>
              <span className="warning-chip">Human review required</span>
            </div>
            <div className="limitations-grid">
              {card.limitations.map((limitation) => (
                <article key={limitation}><span aria-hidden="true">!</span><p>{limitation}</p></article>
              ))}
            </div>
          </section>

          {drift ? (
            <section className="panel drift-panel">
              <div className="panel-heading">
                <div><span className="section-kicker">Population stability index</span><h2>Feature drift monitoring</h2></div>
                <span className={`drift-status drift-status--${drift.status}`}>{drift.status} · {drift.overall_psi.toFixed(3)}</span>
              </div>
              <div className="drift-context">
                <span>{drift.baseline_dataset} · {drift.baseline_rows.toLocaleString()} rows</span>
                <span>{drift.current_dataset} · {drift.current_rows.toLocaleString()} rows</span>
              </div>
              <div className="drift-features">
                {drift.features.map((feature) => (
                  <article key={feature.feature}>
                    <div><strong>{feature.feature}</strong><span className={`drift-dot drift-dot--${feature.status}`}>{feature.status}</span></div>
                    <div className="drift-track"><span className={`drift-fill drift-fill--${feature.status}`} style={{ width: `${Math.min(feature.psi / drift.thresholds.drift_above, 1) * 100}%` }} /></div>
                    <footer><span>PSI {feature.psi.toFixed(3)}</span><span>baseline μ {feature.baseline_mean.toFixed(2)}</span><span>current μ {feature.current_mean.toFixed(2)}</span></footer>
                  </article>
                ))}
              </div>
              <p className="drift-interpretation">{drift.interpretation}</p>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  )
}
