import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.jsx'
import { Verdict } from '../src/pages/Practice.jsx'
import { score } from '../src/ringing/striking.js'

const at = (path) => {
  window.history.replaceState(null, '', path)
  return render(<App />)
}

beforeEach(() => {
  window.scrollTo = vi.fn()
})

describe('finding your way', () => {
  it('moves between pages, sets the title and moves focus', async () => {
    at('/')
    await userEvent.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Appeal' }))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Mend a bell')
    expect(document.title).toBe('Mend a bell | Thornwick Bells')
    expect(screen.getByRole('main')).toHaveFocus()
  })
  it('goes back', async () => {
    at('/methods')
    await userEvent.click(screen.getByRole('link', { name: 'Stedman Doubles' }))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Stedman Doubles')
    await act(async () => {
      window.history.back()
      await new Promise((r) => { setTimeout(r, 50) })
    })
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('The method book')
  })
  it.each(['/nowhere', '/methods/made-up'])('%s says so kindly', (path) => {
    at(path)
    expect(screen.getByRole('link', { name: 'Back to rounds' })).toBeInTheDocument()
  })
})

describe('front page', () => {
  it('lets you ring a bell and tells you about it', async () => {
    at('/')
    await userEvent.click(screen.getByRole('button', { name: 'Ring bell 7, Old Constant' }))
    expect(screen.getByText(/cast in 1602/)).toBeInTheDocument()
  })
  it('keeps Mercy silent', async () => {
    at('/')
    await userEvent.click(screen.getByRole('button', { name: 'Ring bell 5, Mercy' }))
    expect(screen.getByText(/all she does/)).toBeInTheDocument()
  })
})

describe('method book', () => {
  it('filters and keeps the filter in the address', async () => {
    at('/methods')
    await userEvent.selectOptions(screen.getByLabelText('Bells'), '7')
    expect(screen.getByText('1 method')).toBeInTheDocument()
    expect(window.location.search).toBe('?bells=7')
  })
  it('offers a way out of an empty result', async () => {
    at('/methods?bells=7&level=First+steps')
    await userEvent.click(screen.getByRole('button', { name: 'Show every method' }))
    expect(screen.getByText('13 methods')).toBeInTheDocument()
  })
  it('proves a touch as you call it', async () => {
    at('/methods/plain-bob-minor')
    expect(screen.getByText('60 changes')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Lead 1'), 'b')
    expect(screen.getByText(/does not come round/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'All 720' }))
    expect(screen.getByText('720 changes')).toBeInTheDocument()
    expect(screen.getByText('It comes round.')).toBeInTheDocument()
  })
  it('opens a shared address as it was left, and ignores nonsense in it', () => {
    at('/methods/plain-bob-minor?bell=4&calls=ppppp%3Cp')
    expect(screen.getByRole('radio', { name: '4' })).toBeChecked()
    expect(screen.getByText(/False: 214365/)).toBeInTheDocument()
  })
  it('falls back when the bell does not exist', () => {
    at('/methods/plain-bob-minor?bell=99')
    expect(screen.getByRole('radio', { name: '2' })).toBeChecked()
  })
})

describe('pledging', () => {
  it('shows what Gift Aid is worth, then thanks the donor', async () => {
    at('/appeal?bell=7')
    await userEvent.click(screen.getByRole('button', { name: '£200' }))
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.selectOptions(screen.getByLabelText(/Highest rate/), 'higher')
    expect(screen.getByText(/claim back £50, so it costs you £150/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Name for/), 'Asha Rao')
    await userEvent.type(screen.getByLabelText('Email'), 'asha@example.org')
    await userEvent.click(screen.getByRole('button', { name: 'Pledge £200' }))
    expect(screen.getByRole('heading', { name: 'Thank you, Asha Rao' })).toBeInTheDocument()
  })
  it('lists every problem and marks the fields', async () => {
    at('/appeal')
    await userEvent.clear(screen.getByLabelText('Amount in pounds'))
    await userEvent.click(screen.getByRole('button', { name: 'Pledge £0' }))
    expect(within(screen.getByRole('alert')).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByLabelText('Amount in pounds')).toBeInvalid()
  })
})

describe('booking', () => {
  it('asks young ringers for an adult', async () => {
    at('/visit')
    expect(screen.queryByLabelText(/Adult coming/)).toBeNull()
    await userEvent.type(screen.getByLabelText('Age'), '12')
    expect(screen.getByLabelText(/Adult coming/)).toBeInTheDocument()
  })
  it('waits for an evening before offering ropes', async () => {
    at('/visit')
    expect(screen.getByRole('group', { name: 'Choose a rope' })).toBeDisabled()
    await userEvent.click(screen.getAllByRole('radio')[0])
    expect(screen.getByRole('group', { name: 'Choose a rope' })).toBeEnabled()
  })
})

it('reports each pull in words', () => {
  render(<Verdict result={score([1, 2, 3], [1, 2.1])} />)
  expect(screen.getByText('Pull 1: exact')).toBeInTheDocument()
  expect(screen.getByText('Pull 2: 100 ms late')).toBeInTheDocument()
  expect(screen.getByText('Pull 3: missed')).toBeInTheDocument()
})
