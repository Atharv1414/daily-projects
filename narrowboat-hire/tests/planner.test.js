import { describe, expect, it } from 'vitest'
import { BASE, PLACES, REACHES, placeById } from '../src/data/network.js'
import { allRoutes, availableHours, cruisingHours, itinerary, profile, quickestPath, routeById, suggestRoutes } from '../src/lib/planner.js'

const routes = allRoutes()

describe('the lock-mile rule', () => {
  it('counts a lock as a mile at three miles an hour', () => {
    expect(cruisingHours(12, 9)).toBe(7)
    expect(cruisingHours(0, 0)).toBe(0)
  })

  it('gives a short first afternoon and full days after it', () => {
    expect(availableHours(3, 'gentle')).toBe(3 + 2 * 4)
    expect(availableHours(7, 'steady')).toBe(3 + 6 * 6)
    expect(() => availableHours(0, 'steady')).toThrow()
    expect(() => availableHours(7, 'sprint')).toThrow()
  })
})

describe('the network data', () => {
  it.each(REACHES)('$id changes height only where it has locks', (reach) => {
    const rise = placeById[reach.to].elevation - placeById[reach.from].elevation
    expect(rise === 0).toBe(reach.locks === 0)
    if (reach.locks) expect(Math.abs(rise / reach.locks)).toBeLessThanOrEqual(14)
  })

  it('reaches every place from the wharf', () => {
    for (const place of PLACES) if (!place.base) expect(quickestPath(BASE, place.id)).not.toBeNull()
  })
})

describe('route building', () => {
  it('starts and ends every route at the wharf, with each leg joining the last', () => {
    expect(routes.length).toBeGreaterThan(30)
    for (const route of routes) {
      expect(route.legs[0].from).toBe(BASE)
      expect(route.legs.at(-1).to).toBe(BASE)
      route.legs.slice(1).forEach((leg, i) => expect(leg.from).toBe(route.legs[i].to))
    }
  })

  it('only turns a boat round at a winding hole', () => {
    for (const route of routes) {
      route.legs.slice(1).forEach((leg, i) => {
        if (leg.reach.id === route.legs[i].reach.id) expect(placeById[leg.from].winding, `${route.id} turns at ${leg.from}`).toBe(true)
      })
    }
  })

  it('finds both rings and the figure of eight, with honest totals', () => {
    const hollins = routeById('ring:r1-r12-r13-r14-r15')
    expect(hollins).toMatchObject({ name: 'Hollins Ring', miles: 22, locks: 11, maxLength: 57 })
    expect(routeById('ring:r11-r2-r3-r5-r7-r8-r9')).toMatchObject({ name: 'Tenbridge Ring', locks: 28, maxLength: 70 })
    expect(routes.some((r) => r.kind === 'figure-of-eight')).toBe(true)
  })

  it('never adds two runs where one already passes the other', () => {
    for (const route of routes.filter((r) => r.name.includes('Ashlock Top and Kiln Green'))) throw new Error(route.name)
  })
})

describe('suggestions', () => {
  it('fill between half and all of the time, closest to 85% first', () => {
    const { available, routes: found } = suggestRoutes({ nights: 7, pace: 'steady', boatLength: 57 })
    expect(found.length).toBeGreaterThan(3)
    for (const r of found) expect(r.hours / available).toBeGreaterThanOrEqual(0.5)
    for (const r of found) expect(r.hours / available).toBeLessThanOrEqual(1.05)
    const gaps = found.map((r) => Math.abs(r.hours - available * 0.85))
    expect(gaps).toEqual([...gaps].sort((a, b) => a - b))
  })

  it('keep long boats off the narrow locks and say how many routes that rules out', () => {
    const long = suggestRoutes({ nights: 4, pace: 'steady', boatLength: 62 })
    expect(long.routes.every((r) => r.maxLength >= 62)).toBe(true)
    expect(long.routes.some((r) => r.name.includes('Hollins'))).toBe(false)
    expect(long.blockedByLength).toBeGreaterThan(0)
    expect(suggestRoutes({ nights: 4, pace: 'steady', boatLength: 57 }).blockedByLength).toBe(0)
  })

  it('offer the longest routes, flagged, when nothing fills a fortnight', () => {
    const result = suggestRoutes({ nights: 14, pace: 'steady', boatLength: 69 })
    expect(result.spareTime).toBe(true)
    expect(result.routes).toHaveLength(3)
  })
})

describe('day-by-day plans', () => {
  const route = suggestRoutes({ nights: 7, pace: 'steady', boatLength: 57 }).routes[0]
  const days = itinerary(route, 7, 'steady')

  it('has one cruising day per night that adds up to the whole route', () => {
    expect(days).toHaveLength(7)
    expect(days.reduce((s, d) => s + d.miles, 0)).toBe(route.miles)
    expect(days.reduce((s, d) => s + d.locks, 0)).toBe(route.locks)
    expect(days.at(-1).to).toBe(BASE)
  })

  it('ends every day at a mooring, and each day starts where the last ended', () => {
    days.forEach((d, i) => {
      expect(placeById[d.to].mooring).toBe(true)
      if (i) expect(d.from).toBe(days[i - 1].to)
    })
  })

  it('keeps days within the pace when the route allows it', () => {
    expect(days.filter((d) => d.overrun).length).toBeLessThanOrEqual(1)
    expect(Math.max(...days.slice(1).map((d) => d.hours))).toBeLessThanOrEqual(6.5)
  })

  it('adds days moored up when a short route meets a long holiday', () => {
    const short = itinerary(routeById('ring:r1-r12-r13-r14-r15'), 7, 'steady')
    expect(short).toHaveLength(7)
    expect(short.some((d) => d.rest)).toBe(true)
  })
})

describe('the side elevation', () => {
  it('climbs once per lock and comes home to the same level', () => {
    const route = routeById('ring:r11-r2-r3-r5-r7-r8-r9')
    const points = profile(route)
    expect(points.filter((p) => p.lock)).toHaveLength(route.locks)
    expect(points[0].elevation).toBe(210)
    expect(points.at(-1).elevation).toBe(210)
    expect(Math.max(...points.map((p) => p.elevation))).toBe(306)
  })
})
