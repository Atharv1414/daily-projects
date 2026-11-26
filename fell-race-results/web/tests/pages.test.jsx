import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from '../src/api.js'
import App from '../src/App.jsx'
import { contract, goTo, mockApi } from './mockApi.js'

beforeEach(() => {
  window.scrollTo = vi.fn()
  window.matchMedia = vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})

afterEach(() => {
  vi.unstubAllGlobals()
  goTo('/')
})

describe('pages', () => {
  it('home shows the fixtures and both championship leaders', async () => {
    mockApi()
    goTo('/')
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Up the gill')
    expect(await screen.findByRole('link', { name: 'Scar Edge Horseshoe' })).toHaveAttribute('href', '/races/scar-edge-horseshoe')
    const women = await screen.findByRole('region', { name: 'Women' })
    const leader = contract.examples['/api/standings?season=2026&sex=F'].rows[0]
    expect(within(women).getByRole('link', { name: leader.name })).toBeInTheDocument()
    expect(within(women).getByText(leader.total.toFixed(1))).toBeInTheDocument()
  })

  it('navigates between pages without a reload and marks the current link', async () => {
    mockApi()
    goTo('/')
    render(<App />)
    await userEvent.click(screen.getByRole('link', { name: 'Championship' }))
    expect(window.location.pathname).toBe('/championship')
    expect(screen.getByRole('link', { name: 'Championship' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('heading', { level: 1 })).toHaveFocus()
  })

  it('championship filters by category and keeps the filter in the address', async () => {
    mockApi()
    goTo('/championship?sex=F')
    render(<App />)
    const table = await screen.findByRole('table')
    const all = within(table).getAllByRole('row').length
    await userEvent.selectOptions(screen.getByLabelText('Age category'), 'V50')
    expect(window.location.search).toBe('?sex=F&category=V50')
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows.length).toBeLessThan(all - 1)
    expect(rows.every((r) => within(r).getByText('V50'))).toBe(true)
    expect(within(rows[0]).getAllByRole('cell')[0]).toHaveTextContent('1')
  })

  it('race page lists results, filters women, and offers a ghost race for two ticks', async () => {
    const { calls } = mockApi()
    goTo('/races/scar-edge-horseshoe')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Scar Edge Horseshoe' })).toBeInTheDocument()
    const results = contract.examples['/api/races/scar-edge-horseshoe/results?season=2026&page=1&page_size=50']
    expect(await screen.findByText(`Page 1 of ${Math.ceil(results.total / 50)} · ${results.total} runners`)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Women'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('sex=F'))).toBe(true))
    const women = contract.examples['/api/races/scar-edge-horseshoe/results?season=2026&sex=F&page=1&page_size=50'].items
    await userEvent.click(await screen.findByLabelText(`Compare ${women[0].name}`))
    await userEvent.click(screen.getByLabelText(`Compare ${women[1].name}`))
    await userEvent.click(screen.getByRole('button', { name: /ghost race the two/i }))
    expect(window.location.search).toBe(`?race=scar-edge-horseshoe&season=2026&runners=${women[0].runner_id},${women[1].runner_id}`)
  })

  it('ghost race moves the runners with the clock and tells the story', async () => {
    mockApi()
    goTo('/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084')
    render(<App />)
    const clock = await screen.findByRole('slider', { name: 'Race clock' })
    expect(screen.getByTestId('gap')).toHaveTextContent('Side by side')
    fireEvent.change(clock, { target: { value: '2575' } }) // Hamish reaches Cairn Top
    expect(screen.getByTestId('gap')).toHaveTextContent(/^Hamish leads by \d+ m \(1:0\d\)$/)
    fireEvent.change(clock, { target: { value: '3888' } })
    expect(screen.getByText('finished in 1:04:46')).toBeInTheDocument()
    expect(screen.getByText('Ewan takes the lead by 2 s at the finish.')).toBeInTheDocument()
  })

  it('ghost race checks runner numbers before asking the API', async () => {
    const { calls } = mockApi()
    goTo('/ghost')
    render(<App />)
    await userEvent.type(screen.getByLabelText('Runner A'), 'Hamish')
    await userEvent.type(screen.getByLabelText('Runner B'), 'R0084')
    await userEvent.click(screen.getByRole('button', { name: 'Race them' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Runner numbers look like R0123')
    expect(calls.some((c) => c.url.startsWith('/api/ghost'))).toBe(false)
  })

  it('runner search and profile', async () => {
    mockApi()
    goTo('/runners')
    render(<App />)
    await userEvent.type(screen.getByLabelText('First name or surname'), 'ruth')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    const ruths = contract.examples['/api/runners?q=ruth']
    expect(await screen.findByRole('link', { name: ruths[0].name })).toBeInTheDocument()
    expect(window.location.search).toBe('?q=ruth')
  })

  it('runner profile shows history with personal bests marked', async () => {
    mockApi()
    goTo('/runners/R0090')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Hamish MacLeod' })).toBeInTheDocument()
    const profile = contract.examples['/api/runners/R0090']
    const rows = within(screen.getByRole('region', { name: 'Race history' })).getAllByRole('row')
    expect(rows).toHaveLength(profile.results.length + 1)
    expect(screen.getAllByTitle('Personal best').length).toBe(Object.keys(profile.personal_bests).length)
  })

  it('an unknown runner shows a not-found state', async () => {
    mockApi()
    goTo('/runners/R0001')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Runner not found' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('nothing at /api/runners/R0001')
  })

  it('organiser upload validates, sends and shows the receipt', async () => {
    const { calls } = mockApi()
    goTo('/submit')
    render(<App />)
    await screen.findByText(/A finisher needs 2 times/)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Send results' }))
    expect(screen.getByText('The organiser token is required.')).toBeInTheDocument()
    expect(screen.getByText('Paste at least one result.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Results'), 'R0012, 13:32')
    expect(screen.getByText(/Line 1: R0012 needs 2 times/)).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Results'))
    await user.type(screen.getByLabelText('Results'), 'R0012, 13:32, 24:26')
    await user.type(screen.getByLabelText('Organiser token'), 'good-token')
    await user.click(screen.getByRole('button', { name: 'Send results' }))
    expect(await screen.findByRole('heading', { name: 'Results received' })).toBeInTheDocument()
    expect(screen.getByText(/R9999\): unknown runner id/)).toBeInTheDocument()
    const post = calls.find((c) => c.init.method === 'POST')
    expect(JSON.parse(post.init.body).results).toEqual([{ runner_id: 'R0012', status: 'finished', splits: [812, 1466], version: 1 }])
  })

  it('a rejected token is explained', async () => {
    mockApi()
    goTo('/submit')
    render(<App />)
    await screen.findByText(/A finisher needs 2 times/)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Results'), 'R0012, 13:32, 24:26')
    await user.type(screen.getByLabelText('Organiser token'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Send results' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That organiser token was not accepted.')
  })

  it('unknown paths get a friendly page', () => {
    mockApi()
    goTo('/fell-top')
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Off the route')
  })

  it('request() turns network failures and API errors into ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    await expect(request('/health')).rejects.toMatchObject({ status: 0, message: expect.stringMatching(/not reachable/) })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('oops', { status: 502 })))
    const err = await request('/health').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe('The results service answered 502')
    await act(async () => {})
  })
})
