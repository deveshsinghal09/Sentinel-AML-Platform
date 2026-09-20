import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import {
  checkHealth,
  getDatasets,
  runQuery,
} from '../api'
import CommandCenter from '../pages/CommandCenter'
import { agentResponse, dataset } from './testData'


vi.mock('../api', () => ({
  checkHealth: vi.fn(),
  exportEntities: vi.fn(),
  exportInvestigation: vi.fn(),
  exportSar: vi.fn(),
  exportTrace: vi.fn(),
  getDatasets: vi.fn(),
  inspectDataset: vi.fn(),
  runQuery: vi.fn(),
  uploadDataset: vi.fn(),
}))
vi.mock('../store/investigations', () => ({
  saveInvestigation: vi.fn(),
}))
vi.mock('react-plotly.js', () => ({
  default: () => null,
}))


describe('Command center analyst workflow', () => {
  beforeEach(() => {
    vi.mocked(checkHealth).mockResolvedValue({ status: 'ok', phase: 'test' })
    vi.mocked(getDatasets).mockResolvedValue([dataset])
    vi.mocked(runQuery).mockResolvedValue(agentResponse)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('submits the natural-language query against the active dataset', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CommandCenter />
      </MemoryRouter>,
    )
    const query = screen.getByLabelText('Investigation query')
    await user.clear(query)
    await user.type(query, agentResponse.query)
    await user.click(screen.getByRole('button', { name: 'Run analysis' }))

    await waitFor(() => {
      expect(runQuery).toHaveBeenCalledWith(
        agentResponse.query,
        dataset.dataset_id,
      )
    })
    expect(await screen.findByText('Intent & scope')).toBeTruthy()
    expect(screen.getByText('Targeted structuring analysis uses only justified tools.')).toBeTruthy()
    expect(screen.getByText('ACC-17')).toBeTruthy()
    expect(screen.getByText('Targeted request.')).toBeTruthy()
  })

  it('shows a safe failure state without erasing the analyst query', async () => {
    vi.mocked(runQuery).mockRejectedValue(new Error('Investigation service unavailable'))
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CommandCenter />
      </MemoryRouter>,
    )
    const query = screen.getByLabelText('Investigation query')
    await user.clear(query)
    await user.type(query, 'Find layering')
    await user.click(screen.getByRole('button', { name: 'Run analysis' }))

    expect((await screen.findByRole('alert')).textContent).toContain(
      'Investigation service unavailable',
    )
    expect((query as HTMLTextAreaElement).value).toBe('Find layering')
  })

  it('opens the governed dataset upload from the command center', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CommandCenter />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: 'Upload dataset' }))

    expect(
      screen.getByRole('dialog', { name: 'Upload dataset' }),
    ).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Close upload' }))
    expect(screen.queryByRole('dialog', { name: 'Upload dataset' })).toBeNull()
  })
})
