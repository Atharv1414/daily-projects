import { PLACES, REACHES, WATERWAYS, placeById } from '../data/network.js'

// Schematic map of the network. Locks are red ticks across the water, flights are tight bunches of
// them, the tunnel is dashed, and reaches too short for the chosen boat are drawn faint and hatched.

function lockTicks(reach) {
  const a = placeById[reach.from]
  const b = placeById[reach.to]
  const dx = b.x - a.x
  const dy = b.y - a.y
  const length = Math.hypot(dx, dy)
  const nx = -dy / length
  const ny = dx / length
  return Array.from({ length: reach.locks }, (_, i) => {
    const t = reach.flight ? 0.35 + (0.3 * (i + 0.5)) / reach.locks : (i + 0.5) / reach.locks
    const x = a.x + dx * t
    const y = a.y + dy * t
    return { x1: x - nx * 9, y1: y - ny * 9, x2: x + nx * 9, y2: y + ny * 9, key: `${reach.id}-${i}` }
  })
}

export default function CanalMap({ route = null, boatLength = 0, title = 'Map of the waterways around Marrowby Wharf' }) {
  const onRoute = new Set(route?.legs.map((l) => l.reach.id) ?? [])
  const stops = new Set(route?.legs.flatMap((l) => [l.from, l.to]) ?? [])
  const description = route
    ? `${route.name}: ${route.miles} miles and ${route.locks} locks from Marrowby Wharf, highlighted on the map.`
    : 'Fourteen places on four waterways, with Marrowby Wharf near the middle.'

  return (
    <div className="map" role="region" aria-label="Canal map" tabIndex={0}>
      <svg viewBox="0 0 1000 640" className="map__svg" role="img" aria-labelledby="map-title map-desc">
        <title id="map-title">{title}</title>
        <desc id="map-desc">{description}</desc>
        <defs>
          <pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="8" className="map__hatch" />
          </pattern>
        </defs>

        {REACHES.map((reach) => {
          const a = placeById[reach.from]
          const b = placeById[reach.to]
          const tooShort = boatLength > reach.maxLength
          const narrow = WATERWAYS[reach.waterway].gauge === 'narrow'
          const classes = [
            'map__reach',
            narrow && 'map__reach--narrow',
            onRoute.has(reach.id) && 'map__reach--on',
            tooShort && 'map__reach--blocked',
            reach.tunnel && 'map__reach--tunnel',
            reach.river && 'map__reach--river',
          ]
            .filter(Boolean)
            .join(' ')
          return (
            <g key={reach.id} className={classes}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="map__bank" />
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="map__water" stroke={tooShort ? 'url(#hatch)' : undefined} />
              {lockTicks(reach).map((t) => (
                <line key={t.key} {...t} className="map__lock" />
              ))}
            </g>
          )
        })}

        {REACHES.filter((r) => r.tunnel || r.aqueduct || r.flight).map((r) => {
          const a = placeById[r.from]
          const b = placeById[r.to]
          return (
            <text
              key={`${r.id}-label`}
              x={r.labelAt?.[0] ?? (a.x + b.x) / 2 + 14}
              y={r.labelAt?.[1] ?? (a.y + b.y) / 2 - 12}
              className="map__feature"
            >
              {r.tunnel?.name ?? r.aqueduct ?? `${r.flight} (${r.locks})`}
            </text>
          )
        })}

        {PLACES.map((p) => {
          const on = stops.has(p.id)
          const anchor = p.x > 820 ? 'end' : p.x < 160 ? 'start' : 'middle'
          return (
            <g key={p.id} className={`map__place${on ? ' map__place--on' : ''}${p.base ? ' map__place--base' : ''}`}>
              {p.base ? <rect x={p.x - 11} y={p.y - 11} width="22" height="22" /> : <circle cx={p.x} cy={p.y} r={p.winding ? 8 : 6} />}
              <text x={p.x} y={p.y + (p.y > 560 ? -18 : 30)} textAnchor={anchor} className="map__label">
                {p.name}
              </text>
            </g>
          )
        })}
      </svg>
      <ul className="map__key" aria-label="Map key">
        <li><span className="key key--lock" aria-hidden="true" />Lock</li>
        <li><span className="key key--narrow" aria-hidden="true" />Narrow locks, 57 ft and under</li>
        <li><span className="key key--tunnel" aria-hidden="true" />Tunnel, no towpath</li>
        <li><span className="key key--base" aria-hidden="true" />Our wharf</li>
        {boatLength > 57 && <li><span className="key key--blocked" aria-hidden="true" />Too short for a {boatLength} ft boat</li>}
      </ul>
    </div>
  )
}
