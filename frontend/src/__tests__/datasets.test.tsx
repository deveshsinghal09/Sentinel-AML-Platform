import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import {
  activateDataset,
  deleteDataset,
  getDatasets,
  inspectDataset,
  uploadDataset,
} from '../api'
import Datasets from '../pages/Datasets'
import { dataset, knowledgeDataset } from './testData'


vi.mock('../api', () => ({
  activateDataset: vi.fn(),
  deleteDataset: vi.fn(),
  getDatasets: vi.fn(),
  inspectDataset: vi.fn(),
  uploadDataset: vi.fn(),
}))


describe('Dataset workspace', () => {
  beforeEach(() => {
    vi.mocked(getDatasets).mockResolvedValue([dataset, knowledgeDataset])
    vi.mocked(activateDataset).mockResolvedValue({
      previous_dataset_id: dataset.dataset_id,
      active_dataset_id: knowledgeDataset.dataset_id,
      row_count: knowledgeDataset.row_count,
      message: 'Dataset activated.',
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('filters isolated datasets by name and type without hiding active context', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Datasets />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Primary evidence')).toBeTruthy()
    expect(screen.getByText('SAML-D knowledge')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Dataset type'), 'primary')
    expect(screen.queryByText('SAML-D knowledge')).toBeNull()
    expect(screen.getByText('Primary evidence')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Dataset type'), 'all')
    await user.type(screen.getByLabelText('Search datasets'), 'missing')
    expect(screen.getByText(/No datasets match these filters/)).toBeTruthy()
  })

  it('opens the governed upload inspector from the workspace header', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Datasets />
      </MemoryRouter>,
    )
    await screen.findByText('Primary evidence')
    await user.click(screen.getByRole('button', { name: 'Upload dataset' }))

    expect(screen.getByRole('dialog', { name: 'Upload dataset' })).toBeTruthy()
    expect(screen.getByText(/CSV or XLSX, up to 25 MB/)).toBeTruthy()
    expect(inspectDataset).not.toHaveBeenCalled()
    expect(uploadDataset).not.toHaveBeenCalled()
    expect(deleteDataset).not.toHaveBeenCalled()
  })
})
