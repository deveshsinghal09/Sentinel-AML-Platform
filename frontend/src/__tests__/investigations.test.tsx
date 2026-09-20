import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { getInvestigation, getInvestigations } from '../api'
import Investigations from '../pages/Investigations'
import {
  loadInvestigations,
  saveInvestigation,
} from '../store/investigations'
import type { AgentResponse } from '../types'
import {
  investigationRecord,
  investigationSummaries,
} from './testData'


vi.mock('../api', () => ({
  getInvestigation: vi.fn(),
  getInvestigations: vi.fn(),
}))

const response: AgentResponse = {
  query: 'Which customers made 10+ transactions under $10,000?',
  intent: {
    intent: 'aggregation',
    pattern_type: 'structuring',
    filters: {
      date_range: null,
      entity_id: null,
      from_country: null,
      payment_format: null,
      min_amount: null,
      max_amount: 10_000,
      min_count: 10,
    },
    entities: [],
    require_ml: false,
    require_graph: false,
    require_eda: false,
  },
  plan: {
    steps: ['data_loader', 'aggregation'],
    skipped: [],
    reasoning: 'Direct grouped threshold query',
  },
  execution_trace: [],
  top_entities: [],
  summary_stats: {
    total_analyzed: 100,
    flagged: 0,
    high_risk: 0,
  },
}

describe('investigation history store', () => {
  beforeEach(() => localStorage.clear())

  it('persists a completed investigation across page loads', () => {
    const saved = saveInvestigation(response)
    const loaded = loadInvestigations()

    expect(loaded).toHaveLength(1)
    expect(loaded[0].id).toBe(saved.id)
    expect(loaded[0].query).toBe(response.query)
    expect(loaded[0].disposition).toBe('pending')
  })
})


describe('Investigation register workspace', () => {
  beforeEach(() => {
    vi.mocked(getInvestigations).mockResolvedValue(investigationSummaries)
    vi.mocked(getInvestigation).mockResolvedValue(investigationRecord)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows retained plan rationale, skipped tools, and top evidence', async () => {
    render(
      <MemoryRouter>
        <Investigations />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Targeted structuring analysis uses only justified tools.')).toBeTruthy()
    expect(screen.getByText('Broad profiling is unnecessary for this targeted request.')).toBeTruthy()
    expect(screen.getByText('ACC-17')).toBeTruthy()
    expect(screen.getByText('Eight sub-threshold transactions in four days.')).toBeTruthy()
  })

  it('filters the retained register by workflow status and query text', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Investigations />
      </MemoryRouter>,
    )
    const structuringButton = await screen.findByRole('button', {
      name: /Find structuring in June/,
    })
    const register = structuringButton.closest('section')
    expect(register).not.toBeNull()

    await user.selectOptions(screen.getByLabelText('Workflow status'), 'closed')
    expect(within(register!).getByText('Find layering networks')).toBeTruthy()
    expect(within(register!).queryByText('Find structuring in June')).toBeNull()
    await user.type(screen.getByLabelText('Search register'), 'no match')
    expect(screen.getByText('No investigations match these filters.')).toBeTruthy()
  })
})
