import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import {
  checkHealth,
  getDatasets,
  getQueueSummary,
} from '../api'
import { dataset } from './testData'

function mockNavigationViewport(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches,
      media: '(max-width: 780px)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    checkHealth: vi.fn(),
    getDatasets: vi.fn(),
    getQueueSummary: vi.fn(),
  }
})

describe('workspace navigation controls', () => {
  beforeEach(() => {
    mockNavigationViewport(false)
    vi.mocked(checkHealth).mockResolvedValue({ status: 'ok', phase: 'test' })
    vi.mocked(getDatasets).mockResolvedValue([dataset])
    vi.mocked(getQueueSummary).mockResolvedValue({
      new: 4,
      in_review: 2,
      escalated: 1,
      closed: 0,
      total: 7,
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('collapses the desktop sidebar with the cross and restores it with the menu button', async () => {
    const user = userEvent.setup()
    const { container } = render(<App />)
    const shell = container.querySelector('.workspace-shell')
    const sidebar = screen.getByRole('complementary', {
      name: 'Sentinel AML workspace',
    })
    const closeButton = within(sidebar).getByRole('button', {
      name: 'Close navigation',
    })

    expect(shell?.classList.contains('workspace-shell--sidebar-collapsed')).toBe(false)

    await user.click(closeButton)

    expect(shell?.classList.contains('workspace-shell--sidebar-collapsed')).toBe(true)
    const menuButton = screen.getByRole('button', {
      name: 'Open workspace navigation',
    })
    expect(menuButton.getAttribute('aria-expanded')).toBe('false')

    await user.click(menuButton)

    await waitFor(() => {
      expect(shell?.classList.contains('workspace-shell--sidebar-collapsed')).toBe(false)
    })
    expect(
      screen.getByRole('button', { name: 'Close workspace navigation' })
        .getAttribute('aria-expanded'),
    ).toBe('true')
  })

  it('opens and closes the compact navigation drawer', async () => {
    mockNavigationViewport(true)
    const user = userEvent.setup()
    const { container } = render(<App />)
    const shell = container.querySelector('.workspace-shell')
    const menuButton = screen.getByRole('button', {
      name: 'Open workspace navigation',
    })

    await user.click(menuButton)

    expect(shell?.classList.contains('workspace-shell--nav-open')).toBe(true)
    const sidebar = screen.getByRole('complementary', {
      name: 'Sentinel AML workspace',
    })
    await user.click(
      within(sidebar).getByRole('button', { name: 'Close navigation' }),
    )

    expect(shell?.classList.contains('workspace-shell--nav-open')).toBe(false)
    expect(
      screen.getByRole('button', { name: 'Open workspace navigation' })
        .getAttribute('aria-expanded'),
    ).toBe('false')
  })
})
