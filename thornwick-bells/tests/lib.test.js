import { describe, expect, it } from 'vitest'
import { BELLS } from '../src/content/bells.js'
import { checkVisit, isoDate, nextEvenings, takenRopes } from '../src/lib/evenings.js'
import { checkPledge, giftAid, pounds, totals } from '../src/lib/giving.js'
import { findMethod } from '../src/ringing/methods.js'
import { readCalls } from '../src/pages/Method.jsx'

describe('giving', () => {
  it('adds a quarter for Gift Aid', () => expect(giftAid(100, { eligible: true, band: 'basic' })).toEqual({ received: 125, extra: 25, reclaim: 0, cost: 100 }))
  it('works out relief for higher and additional rates', () => {
    expect(giftAid(100, { eligible: true, band: 'higher' })).toMatchObject({ reclaim: 25, cost: 75 })
    expect(giftAid(100, { eligible: true, band: 'additional' })).toMatchObject({ reclaim: 31.25, cost: 68.75 })
  })
  it('adds nothing without a declaration', () => expect(giftAid(100, { eligible: false, band: 'higher' })).toEqual({ received: 100, extra: 0, reclaim: 0, cost: 100 }))
  it('keeps to whole pence', () => expect(giftAid(0.99, { eligible: true, band: 'basic' }).extra).toBe(0.25))
  it('adds up the fund', () => expect(totals(BELLS)).toMatchObject({ cost: 149000, raised: 81870, left: 67130 }))
  it('never shows a bell as overpaid', () => expect(BELLS.every((b) => b.raised <= b.cost)).toBe(true))
  it('writes pounds with pence only when there are some', () => expect([pounds(1000), pounds(62.5)]).toEqual(['£1,000', '£62.50']))
  it.each([['', /how much/], ['abc', /numbers/], ['0.5', /£1 or more/], ['30000', /treasurer/], ['10.555', /pounds and pence/]])('explains what is wrong with "%s"', (amount, message) => {
    expect(checkPledge({ amount, name: 'A', email: 'a@b.co' }).amount).toMatch(message)
  })
  it('accepts a good pledge', () => expect(checkPledge({ amount: '25.50', name: 'A', email: 'a@b.co' })).toEqual({}))
})

describe('evenings', () => {
  it('are always Tuesdays still to come', () => {
    const list = nextEvenings(new Date('2026-11-24T10:00')) // itself a Tuesday
    expect(list.every((d) => d.getDay() === 2)).toBe(true)
    expect(isoDate(list[0])).toBe('2026-12-01')
  })
  it('skip Christmas week', () => {
    const dates = nextEvenings(new Date('2024-12-10T10:00')).map(isoDate)
    expect(dates).not.toContain('2024-12-24')
    expect(dates).not.toContain('2024-12-31')
  })
  it('always leave room for somebody', () => {
    for (const d of nextEvenings(new Date('2026-01-05'), 60)) expect(takenRopes(d).size).toBeLessThanOrEqual(3)
  })
  const good = { name: 'A', email: 'a@b.co', date: new Date(), rope: 2, age: '30' }
  it('accept an adult', () => expect(checkVisit(good)).toEqual({}))
  it.each([['9', 'age'], ['', 'age'], ['ten', 'age'], ['12', 'guardian']])('ask more of age "%s"', (age, key) => expect(Object.keys(checkVisit({ ...good, age }))).toEqual([key]))
  it('let a young ringer come with an adult', () => expect(checkVisit({ ...good, age: '12', guardian: 'Mum' })).toEqual({}))
})

describe('calls in the address', () => {
  it('drops anything the method cannot do', () => {
    expect(readCalls('pbsXz<', findMethod('plain-bob-minor'))).toBe('pbs')
    expect(readCalls('pbs', findMethod('kent-minor'))).toBe('pb')
    expect(readCalls('ppb', findMethod('stedman-doubles'))).toBe('')
  })
  it('stops at sixty leads', () => expect(readCalls('p'.repeat(500), findMethod('plain-bob-minor'))).toHaveLength(60))
})
