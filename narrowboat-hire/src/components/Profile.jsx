import { placeById } from '../data/network.js'
import { profile } from '../lib/planner.js'

// The route seen from the side: each lock is a step of water. A twelve-lock flight shows up as a
// staircase, which tells a crew more about their Tuesday than any table.

const W = 900
const H = 220
const PAD = { left: 48, right: 16, top: 18, bottom: 34 }

export default function Profile({ route }) {
  const points = profile(route)
  const maxMile = points.at(-1).mile
  const heights = points.map((p) => p.elevation)
  const low = Math.floor((Math.min(...heights) - 10) / 20) * 20
  const high = Math.ceil((Math.max(...heights) + 10) / 20) * 20
  const x = (mile) => PAD.left + (mile / maxMile) * (W - PAD.left - PAD.right)
  const y = (feet) => PAD.top + (1 - (feet - low) / (high - low)) * (H - PAD.top - PAD.bottom)
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.mile).toFixed(1)},${y(p.elevation).toFixed(1)}`).join(' ')
  const area = `${line} L${x(maxMile)},${H - PAD.bottom} L${x(0)},${H - PAD.bottom} Z`
  const ticks = []
  for (let f = low; f <= high; f += 40) ticks.push(f)
  const climb = points.reduce((s, p, i) => s + (i && p.lock ? Math.max(0, p.elevation - points[i - 1].elevation) : 0), 0)
  const highest = placeById[points.filter((p) => p.place).sort((a, b) => b.elevation - a.elevation)[0]?.place]

  return (
    <figure className="profile">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="profile-title">
        <title id="profile-title">
          {`Side view of the route: ${route.locks} locks, climbing ${climb} feet in all, highest at ${highest?.name ?? 'the wharf'} (${highest?.elevation ?? 0} ft).`}
        </title>
        {ticks.map((f) => (
          <g key={f} className="profile__grid">
            <line x1={PAD.left} x2={W - PAD.right} y1={y(f)} y2={y(f)} />
            <text x={PAD.left - 8} y={y(f) + 4} textAnchor="end">{f} ft</text>
          </g>
        ))}
        <path d={area} className="profile__water" />
        <path d={line} className="profile__line" />
        {points.filter((p) => p.lock).map((p, i) => (
          <line key={i} x1={x(p.mile)} x2={x(p.mile)} y1={y(p.elevation) - 4} y2={y(p.elevation) + 10} className="profile__gate" />
        ))}
        {[0, Math.round(maxMile / 2), maxMile].map((m) => (
          <text key={m} x={x(m)} y={H - 10} textAnchor={m === 0 ? 'start' : m === maxMile ? 'end' : 'middle'} className="profile__axis">
            {m === 0 ? 'Marrowby Wharf' : `${m} miles`}
          </text>
        ))}
      </svg>
      <figcaption>
        {route.locks} locks and {climb} ft of climbing (and the same back down). Each red mark is a lock gate.
      </figcaption>
    </figure>
  )
}
