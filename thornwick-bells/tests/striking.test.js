import { expect, it } from 'vitest'
import { frequency } from '../src/ringing/audio.js'
import { advise, schedule, score } from '../src/ringing/striking.js'

const due = [1, 3, 5, 7]

it('spaces blows evenly and breathes before each handstroke', () => {
  const blows = schedule([[1, 2], [2, 1], [1, 2]], { gap: 0.5 })
  expect(blows.map((b) => b.at)).toEqual([0, 0.5, 1, 1.5, 2.5, 3])
})
it('adds the tenor behind when it is covering', () => {
  expect(schedule([[2, 1, 3]], { cover: true }).map((b) => b.bell)).toEqual([2, 1, 3, 4])
})
it('gives full marks for perfect striking', () => expect(score(due, due).percent).toBe(100))
it('marks a missing pull without moving the others', () => {
  expect(score(due, [1, 5, 7]).results.map((r) => r.grade)).toEqual(['struck', 'missed', 'struck', 'struck'])
})
it('grades by how far out each pull was', () => {
  expect(score(due, [1.05, 3.1, 5.3, 6.95]).results.map((r) => r.grade)).toEqual(['struck', 'close', 'clipped', 'struck'])
})
it('takes marks off for extra pulls, but never goes below nothing', () => {
  expect(score(due, [...due, 10]).percent).toBe(88)
  expect(score([1], [20, 30, 40]).percent).toBe(0)
})
it('never uses one pull twice', () => {
  const r = score([1, 1.5], [1.2])
  expect(r.results.filter((x) => x.error !== null)).toHaveLength(1)
})
it('reports which way the learner leans', () => expect(score(due, due.map((d) => d + 0.1)).mean).toBeCloseTo(0.1))
it.each([
  [[], 'did not hear'],
  [[1], 'lost your place'],
  [due.map((d) => d + 0.1), 'late'],
  [due.map((d) => d - 0.1), 'early'],
  [due, 'Beautifully'],
])('gives advice that fits: %j', (pulls, words) => expect(advise(score(due, pulls))).toContain(words))
it('tunes the treble an octave above the tenor', () => {
  expect(frequency(1, 8) / frequency(8, 8)).toBeCloseTo(2)
  expect(frequency(1, 6)).toBeLessThan(frequency(1, 8))
})
