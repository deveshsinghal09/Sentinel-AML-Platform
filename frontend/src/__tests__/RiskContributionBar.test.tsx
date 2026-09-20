import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import RiskContributionBar from '../components/RiskContributionBar'

afterEach(cleanup)

describe('RiskContributionBar', () => {
  it('renders a reconcilable detector breakdown', () => {
    render(
      <RiskContributionBar
        contribution={{
          rule_score: 0.8,
          rule_weight: 0.4,
          rule_contribution: 0.32,
          stat_score: 0.4,
          stat_weight: 0.25,
          stat_contribution: 0.1,
          ml_score: 0.6,
          ml_weight: 0.35,
          ml_contribution: 0.21,
          country_boost: 0.1,
          active_detector_count: 3,
          final_risk_score: 0.73,
          formula: 'rule + statistical + ml + country_boost',
        }}
      />,
    )

    expect(screen.getByText('73 / 100')).toBeTruthy()
    expect(screen.getByText('32.0 pts')).toBeTruthy()
    expect(screen.getByText('+10.0 pts')).toBeTruthy()
  })
})
