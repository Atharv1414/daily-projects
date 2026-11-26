import { useId } from 'react'

const W = 800
const H = 260
const PAD = { top: 28, right: 18, bottom: 34, left: 46 }

function scales(profile) {
  const maxKm = profile[profile.length - 1][0]
  const heights = profile.map((p) => p[1])
  const lo = Math.floor(Math.min(...heights) / 50) * 50
  const hi = Math.ceil(Math.max(...heights) / 50) * 50 + 50
  const x = (km) => PAD.left + (km / maxKm) * (W - PAD.left - PAD.right)
  const y = (m) => PAD.top + (1 - (m - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom)
  return { x, y, lo, hi, maxKm }
}

export function profilePath(profile, x, y) {
  return profile.map(([km, m], i) => `${i ? 'L' : 'M'}${x(km).toFixed(1)},${y(m).toFixed(1)}`).join('')
}

/**
 * The course drawn as a hill: height against distance, checkpoints marked, and optional
 * runner markers ({ km, label, tone }) for the ghost race.
 */
export default function ElevationProfile({ profile, checkpoints = [], markers = [], title, compact = false }) {
  const id = useId()
  if (!profile?.length) return null
  const { x, y, lo, hi, maxKm } = scales(profile)
  const line = profilePath(profile, x, y)
  const area = `${line}L${x(maxKm)},${H - PAD.bottom}L${x(0)},${H - PAD.bottom}Z`
  const ticks = []
  for (let m = lo; m <= hi; m += hi - lo > 600 ? 200 : 100) ticks.push(m)
  const kmTicks = []
  const step = maxKm > 15 ? 5 : maxKm > 6 ? 2 : 1
  for (let k = 0; k <= maxKm + 1e-9; k += step) kmTicks.push(k)
  const top = profile.reduce((a, b) => (b[1] > a[1] ? b : a))

  return (
    <figure className={`profile${compact ? ' profile--compact' : ''}`}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${id}-t`} preserveAspectRatio="xMidYMid meet">
        <title id={`${id}-t`}>
          {title ?? 'Course profile'}: {maxKm} km, highest point {Math.round(top[1])} m
        </title>
        <defs>
          <linearGradient id={`${id}-fill`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--hill-top)" />
            <stop offset="1" stopColor="var(--hill-foot)" />
          </linearGradient>
        </defs>
        {ticks.map((m) => (
          <g key={m} className="profile__grid">
            <line x1={PAD.left} x2={W - PAD.right} y1={y(m)} y2={y(m)} />
            {m !== lo && <text x={PAD.left - 8} y={y(m) + 4} textAnchor="end">{m}</text>}
          </g>
        ))}
        {kmTicks.map((k) => (
          <text key={k} className="profile__km" x={x(k)} y={H - PAD.bottom + 18} textAnchor="middle">
            {k} km
          </text>
        ))}
        <path d={area} fill={`url(#${id}-fill)`} />
        <path d={line} className="profile__line" />
        {checkpoints.map((cp, i) => {
          const h = profile.find((p) => p[0] >= cp.km - 1e-9)?.[1] ?? top[1]
          const last = i === checkpoints.length - 1
          return (
            <g key={cp.name} className="profile__cp">
              <line x1={x(cp.km)} x2={x(cp.km)} y1={y(h)} y2={PAD.top - 6} />
              <circle cx={x(cp.km)} cy={y(h)} r="4" />
              {!compact && (
                <text x={x(cp.km)} y={PAD.top - 10} textAnchor={last ? 'end' : 'middle'}>
                  {cp.name}
                </text>
              )}
            </g>
          )
        })}
        {markers.map((mk) => {
          const h = interpolate(profile, mk.km)
          return (
            <g key={mk.label} className={`profile__runner profile__runner--${mk.tone}`}>
              <circle cx={x(mk.km)} cy={y(h)} r="9" />
              <text x={x(mk.km)} y={y(h) + 4} textAnchor="middle">{mk.label[0]}</text>
            </g>
          )
        })}
      </svg>
    </figure>
  )
}

function interpolate(profile, km) {
  for (let i = 1; i < profile.length; i += 1) {
    if (km <= profile[i][0]) {
      const [x0, y0] = profile[i - 1]
      const [x1, y1] = profile[i]
      return y0 + ((km - x0) / (x1 - x0 || 1)) * (y1 - y0)
    }
  }
  return profile[profile.length - 1][1]
}

/** A tiny unlabelled profile for lists. Decorative: the row text says the same. */
export function Sparkline({ profile }) {
  const w = 120
  const h = 32
  const maxKm = profile[profile.length - 1][0]
  const hs = profile.map((p) => p[1])
  const lo = Math.min(...hs)
  const hi = Math.max(...hs)
  const d = profile
    .map(([km, m], i) => `${i ? 'L' : 'M'}${((km / maxKm) * w).toFixed(1)},${(h - 2 - ((m - lo) / (hi - lo || 1)) * (h - 4)).toFixed(1)}`)
    .join('')
  return (
    <svg className="sparkline" viewBox={`0 0 ${w} ${h}`} aria-hidden="true" focusable="false">
      <path d={`${d}L${w},${h}L0,${h}Z`} />
    </svg>
  )
}
