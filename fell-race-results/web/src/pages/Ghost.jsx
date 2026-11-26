import { useEffect, useMemo, useState } from 'react'
import { paths, useApi } from '../api.js'
import ElevationProfile from '../components/ElevationProfile.jsx'
import { ErrorState, Loading } from '../components/Layout.jsx'
import { formatGap, formatTime } from '../lib/format.js'
import { distanceAt, elevationAt, gapAt, legTable, storyline } from '../lib/ghost.js'
import { Link, useQueryParam } from '../router.jsx'

const RACES = [
  ['hollin-pike-dash', 'Hollin Pike Dash'],
  ['beckside-round', 'Beckside Round'],
  ['scar-edge-horseshoe', 'Scar Edge Horseshoe'],
  ['thrang-moss-trot', 'Thrang Moss Trot'],
  ['raven-crag-race', 'Raven Crag Race'],
  ['three-tarns-traverse', 'Three Tarns Traverse'],
  ['gill-head-gallop', 'Gill Head Gallop'],
  ['long-stile-fell-race', 'Long Stile Fell Race'],
]

function usePrefersReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => window.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.(query)
    if (!mq) return undefined
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduced
}

function Picker({ race, runners, onChange }) {
  const [a, setA] = useState(runners[0] ?? '')
  const [b, setB] = useState(runners[1] ?? '')
  const [problem, setProblem] = useState('')
  const submit = (event) => {
    event.preventDefault()
    const ids = [a, b].map((x) => x.trim().toUpperCase())
    if (!ids.every((x) => /^R\d{4}$/.test(x))) {
      setProblem('Runner numbers look like R0123. Find them on a race results page.')
      return
    }
    if (ids[0] === ids[1]) {
      setProblem('Pick two different runners.')
      return
    }
    setProblem('')
    onChange(race, ids)
  }
  return (
    <form className="picker" onSubmit={submit} noValidate>
      <label className="field">
        <span>Race</span>
        <select value={race} onChange={(e) => onChange(e.target.value, runners)}>
          {RACES.map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}
        </select>
      </label>
      <label className="field">
        <span>Runner A</span>
        <input value={a} onChange={(e) => setA(e.target.value)} placeholder="R0090" aria-invalid={Boolean(problem)} aria-describedby={problem ? 'picker-error' : undefined} />
      </label>
      <label className="field">
        <span>Runner B</span>
        <input value={b} onChange={(e) => setB(e.target.value)} placeholder="R0084" aria-invalid={Boolean(problem)} aria-describedby={problem ? 'picker-error' : undefined} />
      </label>
      <button type="submit" className="button">Race them</button>
      {problem && <p id="picker-error" className="field__error" role="alert">{problem}</p>}
    </form>
  )
}

export default function Ghost({ headingRef }) {
  const [race, setRace] = useQueryParam('race', 'scar-edge-horseshoe')
  const [runnersText] = useQueryParam('runners')
  const [season] = useQueryParam('season', '2026')
  const runners = useMemo(() => runnersText.split(',').filter(Boolean), [runnersText])
  const ready = runners.length === 2
  const { data, error, retry } = useApi(ready ? paths.ghost({ race, season, runners }) : null)
  const reduced = usePrefersReducedMotion()
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)

  const end = data ? Math.max(...data.runners.map((r) => r.splits[r.splits.length - 1])) : 0
  const cpKm = data?.checkpoints.map((c) => c.km) ?? []

  useEffect(() => {
    if (!playing || !end) return undefined
    // Thirty race-seconds per tick; under reduced motion, bigger and slower steps.
    const step = reduced ? 120 : 30
    const timer = window.setInterval(() => {
      setT((now) => {
        const next = Math.min(end, now + step)
        if (next >= end) setPlaying(false)
        return next
      })
    }, reduced ? 600 : 80)
    return () => window.clearInterval(timer)
  }, [playing, end, reduced])

  const change = (nextRace, ids) => {
    setT(0)
    setPlaying(false)
    setRace(nextRace, { runners: ids.join(','), season })
  }

  const [a, b] = data?.runners ?? []
  const gap = data ? gapAt(cpKm, a, b, t) : null
  const leaderName = gap?.leader ? data.runners.find((r) => r.runner_id === gap.leader).name : null
  const markers = data
    ? data.runners.map((r, i) => ({ km: distanceAt(cpKm, r.splits, t), label: r.name, tone: i === 0 ? 'a' : 'b' }))
    : []

  return (
    <section className="page page--ghost">
      <h1 ref={headingRef} tabIndex={-1}>Ghost race</h1>
      <p className="lede">
        Two runners, one race, replayed from their checkpoint times. Between checkpoints we
        assume an even pace, so the dots are an estimate; the checkpoint times are exact.
      </p>
      <Picker key={`${race}:${runnersText}`} race={race} runners={runners} onChange={change} />
      {!ready && (
        <p className="hint">
          Choose two runners, or try <Link to="/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084">Hamish against Ewan on Scar Edge</Link>.
        </p>
      )}
      {error && <ErrorState error={error} retry={error.status === 404 ? undefined : retry} />}
      {ready && !data && !error && <Loading label="Lining them up" />}
      {data && (
        <>
          <ElevationProfile profile={data.profile} checkpoints={data.checkpoints} markers={markers} title="Course with both runners" />
          <div className="scrubber">
            <button type="button" className="button" onClick={() => (t >= end ? (setT(0), setPlaying(true)) : setPlaying((p) => !p))} aria-pressed={playing}>
              {playing ? 'Pause' : t >= end ? 'Replay' : 'Play'}
            </button>
            <label className="scrubber__range">
              <span className="visually-hidden">Race clock</span>
              <input type="range" min="0" max={end} step="1" value={t} onChange={(e) => { setPlaying(false); setT(Number(e.target.value)) }} aria-valuetext={`${formatTime(t)} into the race`} />
            </label>
            <output className="scrubber__clock num" aria-label="Race clock">{formatTime(t)}</output>
          </div>
          <div className="duel" aria-live={playing ? 'off' : 'polite'}>
            {data.runners.map((r, i) => {
              const km = distanceAt(cpKm, r.splits, t)
              const done = r.status === 'finished' && t >= r.time_s
              const out = r.status === 'dnf' && t >= r.splits[r.splits.length - 1]
              return (
                <div key={r.runner_id} className={`duel__runner duel__runner--${i === 0 ? 'a' : 'b'}`}>
                  <Link to={`/runners/${r.runner_id}`}>{r.name}</Link>
                  <span className="num">{km.toFixed(2)} km · {Math.round(elevationAt(data.profile, km))} m</span>
                  <span>{done ? `finished in ${formatTime(r.time_s)}` : out ? 'retired' : 'running'}</span>
                </div>
              )
            })}
            <p className="duel__gap" data-testid="gap">
              {gap.leader ? `${leaderName.split(' ')[0]} leads by ${gap.metres} m (${formatGap(gap.seconds)})` : 'Side by side'}
            </p>
          </div>
          <h2>Checkpoint by checkpoint</h2>
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Checkpoint splits">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Checkpoint</th>
                  <th scope="col" className="num">{a.name}</th>
                  <th scope="col" className="num">{b.name}</th>
                  <th scope="col" className="num">Gap</th>
                  <th scope="col" className="num hide-sm">On this leg</th>
                </tr>
              </thead>
              <tbody>
                {legTable(data.checkpoints, a, b).map((row) => (
                  <tr key={row.name}>
                    <th scope="row">{row.name} <span className="sub">{row.km} km</span></th>
                    <td className="num">{formatTime(row.a)}</td>
                    <td className="num">{formatTime(row.b)}</td>
                    <td className="num">{row.gap == null ? '–' : `${row.gap > 0 ? a.name.split(' ')[0] : row.gap < 0 ? b.name.split(' ')[0] : ''} ${formatGap(row.gap)}`}</td>
                    <td className="num hide-sm">{row.legDelta == null ? '–' : row.legDelta === 0 ? 'level' : `${row.legDelta > 0 ? a.name.split(' ')[0] : b.name.split(' ')[0]} +${formatGap(row.legDelta)}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="story">
            {storyline(data.checkpoints, a, b).map((line) => <li key={line}>{line}</li>)}
          </ul>
        </>
      )}
    </section>
  )
}
