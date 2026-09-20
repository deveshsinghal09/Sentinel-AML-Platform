import type { SummaryStats } from '../types'
import { useCountUp } from '../hooks/useMotion'

interface RiskSummaryProps {
  stats: SummaryStats
}

function percent(numerator: number, denominator: number) {
  if (!denominator) return '0.0'
  return ((numerator / denominator) * 100).toFixed(1)
}

export default function RiskSummary({ stats }: RiskSummaryProps) {
  const flaggedRate = percent(stats.flagged, stats.total_analyzed)
  const highRiskShare = percent(stats.high_risk, stats.flagged)
  const analysedCount = useCountUp(stats.total_analyzed)
  const flaggedCount = useCountUp(stats.flagged)
  const highRiskCount = useCountUp(stats.high_risk)

  return (
    <section className="risk-summary" aria-label="Investigation risk summary">
      <article aria-label={`${stats.total_analyzed} transactions analysed`}>
        <span
          className="metric-icon metric-icon--indigo"
          aria-hidden="true"
        >
          Σ
        </span>
        <div>
          <span>Transactions analysed</span>
          <strong>{analysedCount.toLocaleString()}</strong>
          <small>Filtered query slice</small>
        </div>
      </article>
      <article aria-label={`${stats.flagged} entities flagged`}>
        <span
          className="metric-icon metric-icon--amber"
          aria-hidden="true"
        >
          !
        </span>
        <div>
          <span>Entities flagged</span>
          <strong>{flaggedCount.toLocaleString()}</strong>
          <small>{flaggedRate}% of analysed rows</small>
        </div>
      </article>
      <article aria-label={`${stats.high_risk} high-risk entities`}>
        <span
          className="metric-icon metric-icon--red"
          aria-hidden="true"
        >
          ↑
        </span>
        <div>
          <span>High risk</span>
          <strong>{highRiskCount.toLocaleString()}</strong>
          <small>
            {stats.flagged
              ? `${highRiskShare}% of flagged entities`
              : 'No immediate escalations'}
          </small>
        </div>
      </article>
    </section>
  )
}
