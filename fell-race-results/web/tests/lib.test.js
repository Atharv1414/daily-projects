import { describe, expect, it } from 'vitest'
import { paths } from '../src/api.js'
import { parseResults, suggestUploadId } from '../src/lib/csv.js'
import { describeCategory, formatGap, formatTime, ordinal, parseTime } from '../src/lib/format.js'
import { distanceAt, elevationAt, gapAt, legTable, storyline, timeAtDistance } from '../src/lib/ghost.js'
import { matchPath } from '../src/router.jsx'
import { contract } from './mockApi.js'

describe('format', () => {
  it.each([
    [0, '0:00'],
    [59, '0:59'],
    [61, '1:01'],
    [3599, '59:59'],
    [3600, '1:00:00'],
    [3888, '1:04:48'],
    [null, '–'],
  ])('formatTime(%s) is %s', (s, expected) => {
    expect(formatTime(s)).toBe(expected)
  })

  it('formats gaps and ordinals', () => {
    expect(formatGap(0)).toBe('level')
    expect(formatGap(-19)).toBe('19 s')
    expect(formatGap(75)).toBe('1:15')
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(ordinal)).toEqual(
      ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st', '111th'],
    )
  })

  it.each([
    ['14:47', 887],
    ['1:04:48', 3888],
    ['905', 905],
    [' 7:05 ', 425],
    ['7:65', null],
    ['1:75:00', null],
    ['fast', null],
    ['', null],
  ])('parseTime(%j) is %s', (text, expected) => {
    expect(parseTime(text)).toBe(expected)
  })

  it('explains FRA categories', () => {
    expect(describeCategory('AM')).toBe('Category AM: at least 50 m of climb per km, mostly off path, 10 to 20 km')
  })
})

describe('ghost race geometry', () => {
  const cps = [2, 5, 10]
  const splits = [600, 1800, 3000]

  it('interpolates position between checkpoints', () => {
    expect(distanceAt(cps, splits, 0)).toBe(0)
    expect(distanceAt(cps, splits, 300)).toBeCloseTo(1)
    expect(distanceAt(cps, splits, 600)).toBe(2)
    expect(distanceAt(cps, splits, 1200)).toBeCloseTo(3.5)
    expect(distanceAt(cps, splits, 9999)).toBe(10)
  })

  it('stops a retired runner at their last checkpoint', () => {
    expect(distanceAt(cps, [600, 1800], 5000)).toBe(5)
    expect(timeAtDistance(cps, [600, 1800], 7)).toBeNull()
  })

  it('timeAtDistance is the inverse of distanceAt', () => {
    for (const t of [0, 100, 600, 1234, 2999]) {
      expect(timeAtDistance(cps, splits, distanceAt(cps, splits, t))).toBeCloseTo(t)
    }
  })

  it('measures the gap where the trailing runner is', () => {
    const a = { runner_id: 'A', splits: [600, 1800, 3000] }
    const b = { runner_id: 'B', splits: [660, 1860, 3060] }
    const gap = gapAt(cps, a, b, 1200)
    expect(gap.leader).toBe('A')
    expect(gap.seconds).toBe(60)
    expect(gap.metres).toBe(150)
    expect(gapAt(cps, a, a, 1200).leader).toBeNull()
  })

  it('interpolates elevation and handles the ends of the profile', () => {
    const profile = [[0, 100], [1, 300], [2, 200]]
    expect(elevationAt(profile, 0.5)).toBe(200)
    expect(elevationAt(profile, -1)).toBe(100)
    expect(elevationAt(profile, 5)).toBe(200)
  })

  it('tells the Scar Edge story from the contract data', () => {
    const ghost = contract.examples['/api/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084']
    const [hamish, ewan] = ghost.runners
    const rows = legTable(ghost.checkpoints, hamish, ewan)
    expect(rows.at(-1).gap).toBeLessThan(0) // Ewan ahead at the finish
    expect(rows[2].gap).toBeGreaterThan(0) // Hamish ahead at Cairn Top
    const story = storyline(ghost.checkpoints, hamish, ewan)
    expect(story[0]).toBe('Ewan leads by 1 s at Low Scar.')
    expect(story[1]).toBe('Hamish takes the lead by 19 s at High Scar.')
    expect(story.at(-1)).toBe('Ewan takes the lead by 2 s at the finish.')
  })
})

describe('organiser paste', () => {
  it('reads finishers, DNFs, comments and blank lines', () => {
    const { rows, problems } = parseResults('# header\nr0012, 13:32, 24:26\n\nR0031\t17:15\tDNF\n', 2)
    expect(problems).toEqual([])
    expect(rows).toEqual([
      { runner_id: 'R0012', status: 'finished', splits: [812, 1466], version: 1 },
      { runner_id: 'R0031', status: 'dnf', splits: [1035], version: 1 },
    ])
  })

  it('reports every problem with its line number', () => {
    const text = ['bob, 1:00, 2:00', 'R0001, 2:00, 1:00', 'R0002, 1:00', 'R0003, 1:00, 2:00, DNF', 'R0004, soon, 2:00', 'R0005', 'R0006, 1:00, 2:00', 'R0006, 1:00, 2:01'].join('\n')
    const { rows, problems } = parseResults(text, 2)
    expect(rows.map((r) => r.runner_id)).toEqual(['R0006'])
    expect(problems.map((p) => p.line)).toEqual([1, 2, 3, 4, 5, 6, 8])
    expect(problems[3].message).toMatch(/marked DNF but has a finish/)
  })

  it('suggests a valid upload reference', () => {
    const id = suggestUploadId('raven-crag-race', 2026, new Date('2026-11-26T09:30:00Z'))
    expect(id).toBe('raven-crag-race-2026-202611260930')
    expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
  })
})

describe('api paths and routing', () => {
  it('builds exactly the URLs recorded in the contract', () => {
    const built = [
      paths.health(),
      paths.races(2026),
      paths.race('scar-edge-horseshoe'),
      paths.race('raven-crag-race'),
      paths.results({ slug: 'scar-edge-horseshoe', season: 2026 }),
      paths.results({ slug: 'scar-edge-horseshoe', season: 2026, sex: 'F' }),
      paths.standings({ season: 2026, sex: 'F' }),
      paths.standings({ season: 2026, sex: 'M' }),
      paths.records(),
      paths.searchRunners('ruth'),
      paths.runner('R0090'),
      paths.ghost({ race: 'scar-edge-horseshoe', season: '2026', runners: ['R0090', 'R0084'] }),
    ].map((p) => `/api${p}`)
    expect(built).toEqual(Object.keys(contract.examples))
  })

  it('matches path patterns', () => {
    expect(matchPath('/races/:slug', '/races/gill-head-gallop')).toEqual({ slug: 'gill-head-gallop' })
    expect(matchPath('/races/:slug', '/races')).toBeNull()
    expect(matchPath('/runners/:id', '/races/x')).toBeNull()
  })
})
