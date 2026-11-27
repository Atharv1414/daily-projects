import { placeById } from '../data/network.js'

// A route as a straight line: stops along it, locks as red ticks, overnight stops filled in.
// Used where the full map would be too much, such as the list of suggestions.

export default function StripMap({ route, nightStops = [] }) {
  const total = route.miles
  let mile = 0
  const stops = [{ id: route.legs[0].from, mile: 0 }]
  const locks = []
  for (const l of route.legs) {
    for (let i = 0; i < l.reach.locks; i++) {
      const f = l.reach.flight ? 0.35 + (0.3 * (i + 0.5)) / l.reach.locks : (i + 0.5) / l.reach.locks
      locks.push(mile + f * l.reach.miles)
    }
    mile += l.reach.miles
    stops.push({ id: l.to, mile })
  }
  const x = (m) => 8 + (m / total) * 584
  const nights = new Set(nightStops)
  return (
    <svg viewBox="0 0 600 40" className="strip" aria-hidden="true">
      <line x1="8" x2="592" y1="20" y2="20" className="strip__water" />
      {locks.map((m, i) => (
        <line key={i} x1={x(m)} x2={x(m)} y1="12" y2="28" className="strip__lock" />
      ))}
      {stops.map((s, i) => (
        <circle
          key={`${s.id}-${i}`}
          cx={x(s.mile)}
          cy="20"
          r={placeById[s.id].base ? 6 : 4}
          className={`strip__stop${nights.has(i) ? ' strip__stop--night' : ''}${placeById[s.id].base ? ' strip__stop--base' : ''}`}
        />
      ))}
    </svg>
  )
}
