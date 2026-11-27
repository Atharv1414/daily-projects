import { BASE, PLACES, REACHES, placeById } from '../data/network.js'

// The boater's rule of thumb: a lock takes about as long as a mile, and boats do about three miles an hour.
export const LOCK_MILES_PER_HOUR = 3

export const PACES = {
  gentle: { label: 'Gentle', hours: 4, note: 'Long lunches and early moorings' },
  steady: { label: 'Steady', hours: 6, note: 'Most of the day on the move' },
  keen: { label: 'Keen', hours: 8, note: 'Up early, moored late' },
}

// You collect the boat after a 2 pm handover, so the first afternoon gives about three hours,
// and you must be back by 9 am on the last day, so that morning gives none.
export const FIRST_AFTERNOON_HOURS = 3

export function cruisingHours(miles, locks) {
  return (miles + locks) / LOCK_MILES_PER_HOUR
}

export function availableHours(nights, pace) {
  const perDay = PACES[pace]?.hours
  if (!perDay || !Number.isInteger(nights) || nights < 1) throw new Error('Choose a pace and at least one night')
  return FIRST_AFTERNOON_HOURS + (nights - 1) * perDay
}

const adjacency = new Map(PLACES.map((p) => [p.id, []]))
for (const reach of REACHES) {
  adjacency.get(reach.from).push({ reach, to: reach.to })
  adjacency.get(reach.to).push({ reach, to: reach.from })
}

/** A leg is one reach travelled in one direction. */
function leg(reach, from) {
  const to = reach.from === from ? reach.to : reach.from
  return { reach, from, to }
}

function summarise(legs) {
  const miles = legs.reduce((s, l) => s + l.reach.miles, 0)
  const locks = legs.reduce((s, l) => s + l.reach.locks, 0)
  return {
    miles,
    locks,
    hours: cruisingHours(miles, locks),
    maxLength: Math.min(...legs.map((l) => l.reach.maxLength)),
    tunnels: legs.filter((l) => l.reach.tunnel).map((l) => l.reach.tunnel.name),
    waterways: [...new Set(legs.map((l) => l.reach.waterway))],
  }
}

/** Simple paths from `start`, each as a list of legs, never revisiting a place. */
function simplePaths(start, maxLegs = 12) {
  const out = []
  const walk = (at, visited, legs) => {
    for (const { reach, to } of adjacency.get(at)) {
      if (visited.has(to)) continue
      const next = [...legs, leg(reach, at)]
      out.push(next)
      if (next.length < maxLegs) walk(to, new Set([...visited, to]), next)
    }
  }
  walk(start, new Set([start]), [])
  return out
}

/** Quickest path by cruising hours (Dijkstra; the network is small, so a sorted array is enough). */
export function quickestPath(from, to, avoid = new Set()) {
  const best = new Map([[from, { hours: 0, legs: [] }]])
  const queue = [from]
  const done = new Set()
  while (queue.length) {
    queue.sort((a, b) => best.get(a).hours - best.get(b).hours)
    const at = queue.shift()
    if (done.has(at)) continue
    done.add(at)
    if (at === to) return best.get(at).legs
    for (const { reach, to: next } of adjacency.get(at)) {
      if (avoid.has(next) && next !== to) continue
      const hours = best.get(at).hours + cruisingHours(reach.miles, reach.locks)
      if (!best.has(next) || hours < best.get(next).hours) {
        best.set(next, { hours, legs: [...best.get(at).legs, leg(reach, at)] })
        queue.push(next)
      }
    }
  }
  return null
}

/** Every simple cycle in the network, once each, as legs starting at its first place. */
function cycles() {
  const found = new Map()
  for (const place of PLACES) {
    for (const path of simplePaths(place.id)) {
      const end = path.at(-1).to
      for (const { reach } of adjacency.get(end)) {
        const closes = (reach.from === place.id || reach.to === place.id) && !path.some((l) => l.reach.id === reach.id)
        if (!closes || path.length < 2) continue
        const legs = [...path, leg(reach, end)]
        const key = legs.map((l) => l.reach.id).sort().join(',')
        if (!found.has(key)) found.set(key, legs)
      }
    }
  }
  return [...found.values()]
}

/** The same ring, starting and ending at `place`. */
function rotate(legs, place) {
  const index = legs.findIndex((l) => l.from === place)
  return [...legs.slice(index), ...legs.slice(0, index)]
}

const reverse = (legs) => [...legs].reverse().map((l) => ({ reach: l.reach, from: l.to, to: l.from }))

function listOf(names) {
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

/** Non-empty subsets of up to `max` items, smallest first. */
function subsets(items, max) {
  const out = []
  const pick = (from, chosen) => {
    if (chosen.length) out.push(chosen)
    if (chosen.length === max) return
    for (let i = from; i < items.length; i++) pick(i + 1, [...chosen, items[i]])
  }
  pick(0, [])
  return out
}

function ringName(legs) {
  const waterways = new Set(legs.map((l) => l.reach.waterway))
  if (waterways.has('hollins') && waterways.has('tenbridge')) return 'Grand Figure of Eight'
  if (waterways.has('hollins')) return 'Hollins Ring'
  return 'Tenbridge Ring'
}

/** Reaches the ring from the base by the quickest path, goes round, and comes back the same way. */
function fromBase(ringLegs) {
  const places = new Set(ringLegs.map((l) => l.from))
  if (places.has(BASE)) return rotate(ringLegs, BASE)
  const entries = [...places].map((p) => ({ p, path: quickestPath(BASE, p, places) })).filter((e) => e.path)
  const { p, path } = entries.sort((a, b) => summarise(a.path).hours - summarise(b.path).hours)[0]
  return [...path, ...rotate(ringLegs, p), ...reverse(path)]
}

/**
 * Every holiday you can start and finish at the base: rings (reached by the quickest way), a
 * figure of eight where two rings share a junction, trips out to a winding hole and back, and rings
 * with a there-and-back run added. Boats can only turn round at winding holes.
 */
export function allRoutes() {
  const rings = cycles()
  const routes = []
  const add = (route) => routes.push({ ...route, ...summarise(route.legs) })

  for (const ring of rings) {
    add({ id: `ring:${ring.map((l) => l.reach.id).sort().join('-')}`, kind: 'ring', legs: fromBase(ring), name: ringName(ring) })
  }

  for (let i = 0; i < rings.length; i++) {
    for (let j = i + 1; j < rings.length; j++) {
      const a = new Set(rings[i].map((l) => l.from))
      const shared = rings[j].map((l) => l.from).filter((p) => a.has(p))
      const sharesReach = rings[i].some((l) => rings[j].some((m) => m.reach.id === l.reach.id))
      if (shared.length !== 1 || sharesReach) continue
      const first = fromBase(rings[i])
      const at = first.findIndex((l) => l.from === shared[0])
      const legs = [...first.slice(0, at), ...rotate(rings[j], shared[0]), ...first.slice(at)]
      add({ id: `eight:${i}-${j}`, kind: 'figure-of-eight', legs, name: ringName(legs) })
    }
  }

  for (const place of PLACES) {
    if (!place.winding || place.base) continue
    const path = quickestPath(BASE, place.id)
    add({ id: `out:${place.id}`, kind: 'there-and-back', turn: place.id, legs: [...path, ...reverse(path)], name: `Out to ${place.name} and back` })
  }

  // Add up to three there-and-back runs to a ring or figure of eight, for longer holidays.
  for (const ring of routes.filter((r) => r.kind === 'ring' || r.kind === 'figure-of-eight')) {
    const onRing = new Set(ring.legs.map((l) => l.from))
    const spurs = []
    for (const place of PLACES) {
      if (!place.winding || onRing.has(place.id)) continue
      const options = ring.legs
        .map((l, index) => ({ index, path: quickestPath(l.from, place.id, onRing) }))
        .filter((o) => o.path && o.path.length <= 3 && o.path.every((l) => !onRing.has(l.to)))
        .sort((a, b) => a.path.length - b.path.length || a.index - b.index)
      if (options.length) spurs.push({ place, ...options[0] })
    }
    for (const combo of subsets(spurs, 3)) {
      // A run to Kiln Green already passes Ashlock Top; a separate run to Ashlock Top would repeat it.
      const overlaps = combo.some((a) => combo.some((b) => a !== b && b.path.some((l) => l.to === a.place.id)))
      if (overlaps) continue
      // Splice from the last spur back, so earlier indexes stay valid.
      let legs = ring.legs
      for (const spur of [...combo].sort((a, b) => b.index - a.index)) {
        legs = [...legs.slice(0, spur.index), ...spur.path, ...reverse(spur.path), ...legs.slice(spur.index)]
      }
      const names = combo.map((c) => c.place.name)
      add({
        id: `${ring.id}+${combo.map((c) => c.place.id).join('+')}`,
        kind: 'ring-and-spur',
        turn: combo[0].place.id,
        legs,
        name: `${ring.name}, with ${combo.length === 1 ? 'a run' : 'runs'} to ${listOf(names)}`,
      })
    }
  }
  return routes
}

const ALL = allRoutes()

/**
 * Routes that suit a holiday, best first. A good route uses most of the cruising time you have
 * without asking for more; one that needs less than half of it leaves you moored for days.
 */
export function suggestRoutes({ nights, pace, boatLength }) {
  const available = availableHours(nights, pace)
  const target = available * 0.85
  const allowed = ALL.filter((r) => r.maxLength >= boatLength)
  const usage = (r) => r.hours / available
  const fits = allowed
    .filter((r) => usage(r) <= 1.05 && usage(r) >= 0.5)
    .map((r) => ({ ...r, usage: usage(r) }))
    .sort((a, b) => Math.abs(a.hours - target) - Math.abs(b.hours - target) || a.id.localeCompare(b.id))
  const blocked = ALL.filter((r) => r.maxLength < boatLength && usage(r) <= 1.05 && usage(r) >= 0.5).length
  if (fits.length) return { available, routes: fits, blockedByLength: blocked, spareTime: false }

  // Nothing fills the time: offer the longest routes that still fit, and say there will be days to spare.
  const longest = allowed
    .filter((r) => usage(r) <= 1.05)
    .sort((a, b) => b.hours - a.hours || a.id.localeCompare(b.id))
    .slice(0, 3)
    .map((r) => ({ ...r, usage: usage(r) }))
  return { available, routes: longest, blockedByLength: blocked, spareTime: longest.length > 0 }
}

export function routeById(id) {
  return ALL.find((r) => r.id === id) ?? null
}

/**
 * Splits a route into one cruising day per night, each ending at a mooring. Chooses where to moor
 * with a small dynamic programme: running over a day's hours costs a lot, finishing early costs a
 * little, and a day spent moored costs a little more, so days come out even and nobody stops in the
 * middle of a lock flight.
 */
export function itinerary(route, nights, pace) {
  const perDay = PACES[pace].hours
  const legs = route.legs
  const n = legs.length
  const hoursOf = legs.map((l) => cruisingHours(l.reach.miles, l.reach.locks))
  const prefix = [0]
  for (const h of hoursOf) prefix.push(prefix.at(-1) + h)
  const budget = (day) => (day === 0 ? FIRST_AFTERNOON_HOURS : perDay)
  const canStopAfter = (j) => j === n || placeById[legs[j - 1].to].mooring
  const cost = (day, i, j) => {
    if (i === j) return 0.3 * budget(day) ** 2 * 0.1 + 0.5
    const hours = prefix[j] - prefix[i]
    const over = Math.max(0, hours - budget(day))
    const under = Math.max(0, budget(day) - hours)
    return over * over * 10 + under * under * 0.1
  }

  const best = Array.from({ length: nights + 1 }, () => new Array(n + 1).fill(Infinity))
  const from = Array.from({ length: nights + 1 }, () => new Array(n + 1).fill(-1))
  best[0][0] = 0
  for (let d = 0; d < nights; d++) {
    for (let i = 0; i <= n; i++) {
      if (best[d][i] === Infinity) continue
      for (let j = i; j <= n; j++) {
        if (j > i && !canStopAfter(j)) continue
        const total = best[d][i] + cost(d, i, j)
        if (total < best[d + 1][j]) {
          best[d + 1][j] = total
          from[d + 1][j] = i
        }
      }
    }
  }

  const cuts = [n]
  for (let d = nights; d > 0; d--) cuts.unshift(from[d][cuts[0]])
  const days = []
  let place = legs[0].from
  for (let d = 0; d < nights; d++) {
    const dayLegs = legs.slice(cuts[d], cuts[d + 1])
    const miles = dayLegs.reduce((s, l) => s + l.reach.miles, 0)
    const locks = dayLegs.reduce((s, l) => s + l.reach.locks, 0)
    const hours = cruisingHours(miles, locks)
    const to = dayLegs.length ? dayLegs.at(-1).to : place
    days.push({
      number: d + 1,
      from: place,
      to,
      legs: dayLegs,
      miles,
      locks,
      hours,
      budget: budget(d),
      overrun: hours > budget(d) + 0.5,
      rest: dayLegs.length === 0,
      pubs: dayLegs.map((l) => placeById[l.to].pub).filter(Boolean),
    })
    place = to
  }
  return days
}

/**
 * Points for the side elevation: distance along the route against height. Locks in a flight are
 * drawn close together; elsewhere they are spread along the reach.
 */
export function profile(route) {
  const points = [{ mile: 0, elevation: placeById[route.legs[0].from].elevation }]
  let mile = 0
  for (const l of route.legs) {
    const from = placeById[l.from].elevation
    const to = placeById[l.to].elevation
    const step = l.reach.locks ? (to - from) / l.reach.locks : 0
    let height = from
    for (let i = 0; i < l.reach.locks; i++) {
      const fraction = l.reach.flight ? 0.35 + (0.3 * (i + 0.5)) / l.reach.locks : (i + 0.5) / l.reach.locks
      const at = mile + fraction * l.reach.miles
      points.push({ mile: at, elevation: height })
      height += step
      points.push({ mile: at, elevation: height, lock: true })
    }
    mile += l.reach.miles
    points.push({ mile, elevation: to, place: l.to })
  }
  return points
}
