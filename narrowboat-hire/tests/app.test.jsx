import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../src/App.jsx'
import LockDiagram, { LOCK_STEPS } from '../src/components/LockDiagram.jsx'

// Each booking step moves focus to its heading on the next frame; let that happen before typing.
const settle = () => act(() => new Promise((resolve) => requestAnimationFrame(resolve)))

function visit(path) {
  window.history.pushState(null, '', path)
  return render(<App />)
}

beforeEach(() => window.history.replaceState(null, '', '/'))

describe('pages', () => {
  it('shows the home page with links straight into the planner', () => {
    visit('/')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Three miles an hour')
    const link = screen.getByRole('link', { name: 'Hollins Ring' })
    expect(link.getAttribute('href')).toContain('route=ring%3Ar1-r12-r13-r14-r15')
    expect(screen.getByText(/nothing you type is sent anywhere/)).toBeInTheDocument()
  })

  it('works out lock-miles as you type', async () => {
    visit('/')
    const miles = screen.getByLabelText('Miles')
    await userEvent.clear(miles)
    await userEvent.type(miles, '24')
    expect(screen.getByText('11 h 00 min')).toBeInTheDocument()
  })

  it('lists five boats and has a page for each, and a friendly 404 for a boat that does not exist', () => {
    const { unmount } = visit('/fleet')
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(5)
    unmount()
    const page = visit('/fleet/heron')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Heron')
    expect(screen.getByRole('cell', { name: '£2,265' })).toBeInTheDocument()
    page.unmount()
    visit('/fleet/titanic')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent("You've run out of canal")
  })

  it('moves between pages without a reload and marks where you are', async () => {
    visit('/')
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Boats' }))
    expect(window.location.pathname).toBe('/fleet')
    expect(screen.getByRole('link', { name: 'Boats' })).toHaveAttribute('aria-current', 'page')
    expect(document.title).toBe('Boats · Kestrel & Lock')
  })
})

describe('the planner', () => {
  it('keeps its choices in the address so a plan can be shared', async () => {
    visit('/routes')
    await userEvent.selectOptions(screen.getByLabelText('Boat'), 'heron')
    await userEvent.click(screen.getByLabelText(/Gentle/))
    expect(window.location.search).toContain('boat=heron')
    expect(window.location.search).toContain('pace=gentle')
    expect(screen.getByText(/Heron is too long for the narrow locks/)).toBeInTheDocument()
  })

  it('says when a shared route is too long for the chosen boat, and offers others', () => {
    visit('/routes?nights=3&pace=gentle&boat=water-vole&route=ring%3Ar1-r12-r13-r14-r15')
    expect(screen.getByRole('status')).toHaveTextContent('Water Vole is 69 ft, too long for the Hollins Ring')
    expect(screen.getByRole('heading', { level: 2, name: /Out to/ })).toBeInTheDocument()
  })

  it('shows a day-by-day plan with one row per night and a link to book it', () => {
    visit('/routes?nights=4&pace=steady&boat=kestrel')
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(1 + 4)
    expect(screen.getByRole('link', { name: 'Book Kestrel for this route' }).getAttribute('href')).toMatch(/^\/book\?boat=kestrel&nights=4&route=/)
  })
})

describe('the lock guide', () => {
  it('steps through working a lock and stops at each end', async () => {
    render(<LockDiagram />)
    const previous = screen.getByRole('button', { name: 'Previous step' })
    const next = screen.getByRole('button', { name: 'Next step' })
    expect(previous).toBeDisabled()
    for (let i = 1; i < LOCK_STEPS.length; i++) await userEvent.click(next)
    expect(screen.getByText(`Step ${LOCK_STEPS.length} of ${LOCK_STEPS.length}`)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Open the top gates and go')
    expect(next).toBeDisabled()
  })
})

describe('booking', () => {
  it('goes from a boat and date to a confirmed reference, catching mistakes on the way', async () => {
    const user = userEvent.setup()
    visit('/book?boat=dabchick&nights=7')
    expect(screen.getByRole('button', { name: 'Continue to extras' })).toBeDisabled()
    await user.click(screen.getAllByRole('button', { pressed: false })[0])
    await user.click(screen.getByRole('button', { name: 'Continue to extras' }))
    await settle()
    expect(document.activeElement).toHaveTextContent('Extras')

    await user.click(screen.getByLabelText(/A dog/))
    expect(screen.getByText('A dog (up to two)', { selector: '.summary li span' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Continue to your crew' }))
    await settle()

    await user.type(screen.getByLabelText('Lead name'), 'Asha Rao')
    await user.type(screen.getByLabelText(/How many people/), '6')
    await user.click(screen.getByRole('button', { name: 'Check the booking' }))
    await settle()
    expect(document.activeElement).toBe(screen.getByRole('alert'))
    const summary = screen.getByRole('alert')
    expect(summary).toHaveTextContent('There are 6 problems')
    expect(summary).toHaveTextContent('Dabchick sleeps 4')
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')

    await user.type(screen.getByLabelText('Email'), 'asha@example.com')
    await user.type(screen.getByLabelText(/Mobile number/), '07700 900123')
    await user.clear(screen.getByLabelText(/How many people/))
    await user.type(screen.getByLabelText(/How many people/), '4')
    await user.selectOptions(screen.getByLabelText(/steered a narrowboat/), 'none')
    await user.click(screen.getByLabelText(/An adult will be at the tiller/))
    await user.click(screen.getByLabelText(/hire terms/))
    await user.click(screen.getByRole('button', { name: 'Check the booking' }))
    await settle()

    expect(screen.getByRole('heading', { level: 2, name: 'Check and confirm' })).toBeInTheDocument()
    expect(window.location.search).not.toContain('asha')
    await user.click(screen.getByRole('button', { name: 'Confirm booking (demo)' }))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('See you at the wharf, Asha')
    expect(screen.getByText(/^KL-/)).toBeInTheDocument()
    expect(screen.getByText(/nothing has been sent or charged/)).toBeInTheDocument()
  })

  it('does not offer a dog place on a boat without one', async () => {
    visit('/book?boat=kestrel&nights=7&step=2')
    expect(screen.getByLabelText(/A dog/)).toBeDisabled()
    expect(screen.getByText(/Kestrel is not a dog-friendly boat/)).toBeInTheDocument()
  })

  it('explains a confirmation page reached after a reload', () => {
    visit('/book?step=done')
    expect(screen.getByText(/only kept in the tab/)).toBeInTheDocument()
  })

  it('flags a start date on the wrong day of the week', async () => {
    visit('/book?boat=kestrel&nights=3&start=2030-01-01')
    await act(async () => {})
    expect(screen.getByText(/18 months|Weekend breaks start on a Friday/)).toBeInTheDocument()
  })
})
