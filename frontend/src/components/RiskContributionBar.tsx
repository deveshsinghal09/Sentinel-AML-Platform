import type { RiskContribution } from '../types'

const ROWS = [
  {
    key: 'rule',
    label: 'Rule engine',
    color: 'var(--risk-high)',
  },
  {
    key: 'stat',
    label: 'Statistical',
    color: 'var(--risk-medium)',
  },
  {
    key: 'ml',
    label: 'ML engine',
    color: 'var(--accent-bright)',
  },
] as const

export default function RiskContributionBar({
  contribution,
}: {
  contribution: RiskContribution | null
}) {
  if (!contribution) return null

  return (
    <section className="contribution-card" aria-label="Risk score breakdown">
      <div className="contribution-card__heading">
        <span className="drawer-label">Risk score breakdown</span>
        <strong>{Math.round(contribution.final_risk_score * 100)} / 100</strong>
      </div>
      <div className="contribution-list">
        {ROWS.map((row) => {
          const score = contribution[`${row.key}_score`]
          const weight = contribution[`${row.key}_weight`]
          const value = contribution[`${row.key}_contribution`]
          return (
            <div className="contribution-row" key={row.key}>
              <div>
                <span>{row.label}</span>
                <small>
                  {(score * 100).toFixed(0)}% signal · {(weight * 100).toFixed(0)}% base weight
                </small>
              </div>
              <div className="contribution-track" aria-hidden="true">
                <span
                  style={{
                    width: `${Math.min(100, value * 100)}%`,
                    background: row.color,
                  }}
                />
              </div>
              <strong>{(value * 100).toFixed(1)} pts</strong>
            </div>
          )
        })}
        <div className="contribution-row contribution-row--boost">
          <div>
            <span>Country overlay</span>
            <small>Policy-based jurisdiction risk</small>
          </div>
          <div className="contribution-track" aria-hidden="true">
            <span
              style={{
                width: `${contribution.country_boost * 100}%`,
                background: '#f97316',
              }}
            />
          </div>
          <strong>+{(contribution.country_boost * 100).toFixed(1)} pts</strong>
        </div>
      </div>
      <code>{contribution.formula}</code>
    </section>
  )
}
