import { describe as group, expect, it } from 'vitest'
import { METHODS, findMethod } from '../src/ringing/methods.js'
import { NotationError, applyChange, parseNotation, rounds, rowToString } from '../src/ringing/notation.js'
import { describe, factorial, pathOf, prove, ring } from '../src/ringing/touch.js'

group('place notation', () => {
  it('reads a cross as everybody swapping', () => expect(applyChange(rounds(6), parseNotation('x', 6)[0])).toEqual([2, 1, 4, 3, 6, 5]))
  it('accepts x, X and a dash alike', () => expect(parseNotation('-16-16', 6)).toEqual(parseNotation('x16X16', 6)))
  it('leaves the stated places alone', () => expect(applyChange(rounds(6), parseNotation('14', 6)[0])).toEqual([1, 3, 2, 4, 6, 5]))
  it('fills in outside places that are left unsaid', () => expect(parseNotation('4', 6)).toEqual([[1, 4]]))
  it('rings a symmetric block back again without repeating its middle', () => expect(parseNotation('&x16x36', 6)).toHaveLength(7))
  it.each([['9', 8], ['13', 6], ['x', 5], ['&', 6], ['1?', 6]])('refuses %s on %i bells', (text, stage) => {
    expect(() => parseNotation(text, stage)).toThrow(NotationError)
  })
  it('never moves a bell more than one place', () => {
    for (const method of METHODS) {
      const { rows } = ring(method)
      for (let i = 1; i < rows.length; i++) {
        for (const bell of rows[i]) expect(Math.abs(rows[i].indexOf(bell) - rows[i - 1].indexOf(bell))).toBeLessThanOrEqual(1)
      }
    }
  })
})

group('the method book', () => {
  it.each(METHODS.map((m) => [m.name, m]))('%s has its published course length, is true and comes round', (_, method) => {
    const touch = ring(method)
    expect(touch.changes).toBe(method.course)
    expect(touch.isTrue).toBe(true)
    expect(touch.cameRound).toBe(true)
  })
  it.each([['plain-bob-minor', '135264'], ['cambridge-minor', '156342'], ['grandsire-triples', '1253746'], ['plain-bob-major', '13527486'], ['cambridge-major', '15738264'], ['yorkshire-major', '15738264']])('%s has the known first lead head', (id, head) => {
    expect(ring(findMethod(id)).leadHeads[0].head).toBe(head)
  })
  const touches = METHODS.flatMap((m) => (m.touches ?? []).map((t) => [`${m.name}: ${t.name}`, m, t]))
  it.each(touches)('%s is a true touch of the length it claims', (_, method, t) => {
    const touch = ring(method, t.calls)
    expect([touch.isTrue, touch.cameRound]).toEqual([true, true])
    expect(String(touch.changes)).toBe(t.name.match(/\d+/)[0])
  })
  it('rings every possible row once in an extent', () => {
    const touch = ring(findMethod('plain-bob-minor'), findMethod('plain-bob-minor').touches.at(-1).calls)
    expect(new Set(touch.rows.map(rowToString)).size).toBe(factorial(6))
  })
})

group('touches', () => {
  const minor = findMethod('plain-bob-minor')
  it('finds where a false touch repeats itself', () => {
    const touch = ring(minor, 'p'.repeat(6))
    expect(touch.isTrue).toBe(false)
    expect(touch.repeats[0]).toEqual({ row: '214365', first: 1, again: 61 })
  })
  it('does not count the rounds at each end as a repeat', () => expect(prove([rounds(4), [2, 1, 4, 3], rounds(4)]).isTrue).toBe(true))
  it('says when a touch stops short', () => expect(ring(minor, 'pp').cameRound).toBe(false))
  it('refuses a call the method does not have', () => expect(() => ring(findMethod('stedman-doubles'), 'b')).toThrow(/no call/))
  it('follows one bell', () => expect(pathOf(ring(minor).rows, 1).slice(0, 8)).toEqual([1, 2, 3, 4, 5, 6, 6, 5]))
  it.each([[1, 'hunting up'], [5, 'making a place'], [7, 'hunting down']])('describes the treble at change %i as %s', (i, words) => {
    expect(describe(pathOf(ring(minor).rows, 1), i)).toBe(words)
  })
  it('knows a dodge when it sees one', () => expect(describe([3, 4, 3, 4], 1)).toBe('dodging'))
})
