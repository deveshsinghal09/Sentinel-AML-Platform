import { useEffect, useState } from 'react'
import { getPolicy } from '../api'
import type { PolicyResponse } from '../types'

function label(value: string) {
  return value.replaceAll('_', ' ')
}

export default function PolicySettings() {
  const [policy, setPolicy] = useState<PolicyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getPolicy().then(setPolicy).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Unable to load policy'))
  }, [])

  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div><span className="eyebrow">Risk governance</span><h1>Policy settings</h1><p>Effective risk thresholds, detector weights, and jurisdiction controls surfaced from executable configuration.</p></div>
        <span className="metric-pill">Read only</span>
      </header>
      {error ? <div className="workspace-error">{error}</div> : null}
      {policy ? (
        <>
          <section className="policy-banner"><div><span>Policy version</span><strong>{policy.version}</strong></div><div><span>Effective</span><strong>{policy.effective_date}</strong></div><div><span>Jurisdiction</span><strong>{policy.jurisdiction}</strong></div><div><span>Approved by</span><strong>{policy.approved_by}</strong></div></section>
          <div className="governance-grid">
            <section className="governance-card"><span className="section-kicker">Executable thresholds</span><h2>Detection controls</h2><dl>{Object.entries(policy.thresholds).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{value}</dd></div>)}</dl></section>
            <section className="governance-card"><span className="section-kicker">Hybrid score</span><h2>Signal weights</h2><dl>{Object.entries(policy.risk_weights).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{Math.round(value * 100)}%</dd></div>)}</dl></section>
            <section className="governance-card governance-card--wide"><span className="section-kicker">Jurisdiction control</span><h2>High-risk country set</h2><div className="country-chips">{policy.high_risk_countries.map((country) => <span key={country}>{country}</span>)}</div></section>
            <section className="governance-card governance-card--wide"><span className="section-kicker">Model risk disclosure</span><h2>Known limitations</h2><ul>{policy.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>
          </div>
        </>
      ) : !error ? <div className="workspace-loading">Loading effective policy…</div> : null}
    </main>
  )
}
