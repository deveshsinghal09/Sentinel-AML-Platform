import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ExecutionTrace } from '../components/ExecutionTrace'
import type { ExecutionStep } from '../types'

vi.mock('react-plotly.js', () => ({
  default: () => null,
}))

afterEach(cleanup)

const steps: ExecutionStep[] = [
  {
    tool: 'data_loader',
    status: 'run',
    duration_ms: 12,
    reason: 'loaded 500 transactions',
  },
  {
    tool: 'graph_tool',
    status: 'skipped',
    duration_ms: 0,
    reason: 'pattern does not require graph analysis',
  },
]

describe('ExecutionTrace', () => {
  it('renders run tools with a checkmark', () => {
    render(<ExecutionTrace steps={steps} />)
    expect(screen.getByText('✓')).toBeTruthy()
    expect(screen.getByText('Data loader')).toBeTruthy()
  })

  it('renders skipped tools with an X mark', () => {
    render(<ExecutionTrace steps={steps} />)
    expect(screen.getByText('×')).toBeTruthy()
    expect(screen.getByText('Graph analysis')).toBeTruthy()
  })

  it('shows duration for run tools', () => {
    render(<ExecutionTrace steps={steps} />)
    expect(screen.getByText('12ms')).toBeTruthy()
  })

  it('shows a reason for each step', () => {
    render(<ExecutionTrace steps={steps} />)
    expect(screen.getByText('loaded 500 transactions')).toBeTruthy()
    expect(
      screen.getByText('pattern does not require graph analysis'),
    ).toBeTruthy()
  })
})
