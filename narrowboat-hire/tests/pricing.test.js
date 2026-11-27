import { describe, expect, it } from 'vitest'
import { boatById } from '../src/data/fleet.js'
import { validateCrew, bookingReference, normalisePhone } from '../src/lib/booking.js'
import { formatDay, nextStarts, parseDay, quote, seasonFor, startProblem, weekday } from '../src/lib/pricing.js'

const today = parseDay('2027-03-01') // a Monday

describe('dates and seasons', () => {
  it('reads only real calendar days', () => {
    expect(parseDay('2027-02-30')).toBeNull()
    expect(parseDay('27-02-01')).toBeNull()
    expect(formatDay(parseDay('2028-02-29'))).toBe('2028-02-29')
  })

  it.each([
    ['2027-01-15', 'low'],
    ['2027-04-02', 'shoulder'],
    ['2027-06-01', 'peak'],
    ['2027-08-31', 'peak'],
    ['2027-10-29', 'shoulder'],
    ['2027-11-01', 'low'],
  ])('%s is %s season', (day, season) => expect(seasonFor(parseDay(day))).toBe(season))

  it('explains why a start date will not do', () => {
    expect(startProblem('2027-03-10', 7, today)).toMatch(/Monday or Friday/)
    expect(startProblem('2027-03-08', 3, today)).toMatch(/Friday/)
    expect(startProblem('2027-03-02', 7, today)).toMatch(/Monday or Friday/)
    expect(startProblem('2027-03-01', 4, today)).toMatch(/two days/)
    expect(startProblem('2029-03-02', 7, today)).toMatch(/18 months/)
    expect(startProblem('2027-03-05', 7, today)).toBeNull()
  })

  it('offers only start days that suit the stay', () => {
    const starts = nextStarts(4, today)
    expect(starts).toHaveLength(6)
    expect(starts.every((d) => weekday(parseDay(d)) === 'Mon')).toBe(true)
    expect(starts[0]).toBe('2027-03-08')
  })
})

describe('quotes', () => {
  const kestrel = boatById.kestrel

  it('prices a peak week, a shoulder weekend and a low-season fortnight', () => {
    expect(quote({ boat: kestrel, nights: 7, start: '2027-07-02', today }).total).toBe(1915)
    expect(quote({ boat: kestrel, nights: 3, start: '2027-04-02', today }).total).toBe(950) // 1530 x 0.62 = 948.6, to the nearest £5
    expect(quote({ boat: kestrel, nights: 14, start: '2027-11-05', today }).total).toBe(2185)
  })

  it('adds extras and caps bikes at four', () => {
    const q = quote({ boat: boatById.dabchick, nights: 7, start: '2027-07-02', today, extras: { dog: true, bikes: 9, lesson: true } })
    expect(q.lines.map((l) => l.amount)).toEqual([1720, 45, 140, 60])
    expect(q.total).toBe(1965)
  })

  it('refuses a dog on a boat that does not take them', () => {
    expect(quote({ boat: kestrel, nights: 7, start: '2027-07-02', today, extras: { dog: true } })).toMatchObject({ ok: false })
  })

  it('takes a 25% deposit when far enough ahead, and the lot when not', () => {
    const far = quote({ boat: kestrel, nights: 7, start: '2027-07-02', today })
    expect(far).toMatchObject({ dueNow: 479, balance: 1436, balanceDue: '2027-05-07', end: '2027-07-09' })
    const near = quote({ boat: kestrel, nights: 7, start: '2027-04-23', today })
    expect(near).toMatchObject({ dueNow: near.total, balance: 0, balanceDue: null })
  })
})

describe('crew details', () => {
  const good = { name: 'Asha Rao', email: 'asha@example.com', phone: '+44 7700 900123', crew: '4', experience: 'none', adultAtHelm: true, terms: true }

  it('accepts a complete form, including an international-format UK number', () => {
    expect(validateCrew(good, boatById.kestrel)).toEqual({})
    expect(normalisePhone('+44 (0)7700 900123'.replace('(0)', ''))).toBe('07700900123')
  })

  it('says what to fix for every missing or wrong answer', () => {
    const errors = validateCrew({ name: 'A', email: 'nope', phone: '123', crew: '0' }, boatById.kestrel)
    expect(Object.keys(errors).sort()).toEqual(['adultAtHelm', 'crew', 'email', 'experience', 'name', 'phone', 'terms'])
  })

  it('will not overfill a boat', () => {
    expect(validateCrew({ ...good, crew: '3' }, boatById.moorhen).crew).toMatch(/Moorhen sleeps 2/)
  })

  it('makes the same reference for the same booking and a different one otherwise', () => {
    const a = bookingReference({ boat: 'kestrel', start: '2027-07-02' })
    expect(a).toMatch(/^KL-[0-9A-Z]{7}$/)
    expect(bookingReference({ boat: 'kestrel', start: '2027-07-02' })).toBe(a)
    expect(bookingReference({ boat: 'kestrel', start: '2027-07-05' })).not.toBe(a)
  })
})
