import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Bell from '../components/Bell.jsx'
import { Link, useQuery } from '../lib/router.jsx'
import { findMethod } from '../ringing/methods.js'
import { rounds } from '../ringing/notation.js'
import { advise, schedule, score } from '../ringing/striking.js'
import { ring } from '../ringing/touch.js'
import { useRinging } from '../ringing/useRinging.js'

const STAGE = 6
const PIECES = {
  rounds: { name: 'Rounds', rows: () => Array.from({ length: 12 }, () => rounds(STAGE)) },
  hunt: { name: 'Plain hunt', rows: () => [rounds(STAGE), rounds(STAGE), ...ring({ stage: STAGE, notation: 'x16', name: 'Plain hunt' }).rows.slice(1)] },
  bob: { name: 'A lead of Plain Bob', rows: () => [rounds(STAGE), rounds(STAGE), ...ring(findMethod('plain-bob-minor'), 'p').rows.slice(1)] },
}
const SPEEDS = { slow: 0.42, steady: 0.32 }

export default function Practice() {
  const [query, setQuery] = useQuery()
  const piece = PIECES[query.get('piece')] ? query.get('piece') : 'rounds'
  const speed = SPEEDS[query.get('speed')] ? query.get('speed') : 'slow'
  const asked = Number(query.get('bell'))
  const bell = Number.isInteger(asked) && asked >= 1 && asked <= STAGE ? asked : 3
  const rows = useMemo(() => PIECES[piece].rows(), [piece])
  const blows = useMemo(() => schedule(rows, { gap: SPEEDS[speed] }), [rows, speed])
  const { playing, current, play, stop, strikeNow } = useRinging()
  const pulls = useRef([])
  const [result, setResult] = useState(null)
  const [pulled, setPulled] = useState(0)
  const here = current >= 0 ? blows[current] : null

  const start = () => {
    pulls.current = []
    setResult(null)
    play(blows, STAGE, {
      silent: bell,
      onEnd: () => setResult(score(blows.filter((b) => b.bell === bell).map((b) => b.at), pulls.current)),
    })
  }
  const pull = useCallback(async () => {
    setPulled((n) => n + 1)
    pulls.current.push(await strikeNow(bell, STAGE))
  }, [bell, strikeNow])

  useEffect(() => {
    if (!playing) return undefined
    const onKey = (e) => {
      if (e.code !== 'Space' || e.repeat) return
      e.preventDefault()
      pull()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playing, pull])

  const change = (next) => {
    stop()
    setResult(null)
    setQuery(next)
  }

  return (
    <div className="page">
      <header className="page__head">
        <h1>Ring with us</h1>
        <p className="lead">We ring five bells. The gap is yours. Press <kbd>Space</kbd>, or tap your bell, so that it falls evenly between its neighbours.</p>
      </header>
      <div className="circle">
        <div className="circle__tools">
          <fieldset className="picker"><legend>Your bell</legend>
            {rounds(STAGE).map((b) => <label key={b}><input type="radio" name="bell" checked={b === bell} onChange={() => change({ bell: b })} /><span>{b}</span></label>)}
          </fieldset>
          <fieldset className="picker picker--wide"><legend>Piece</legend>
            {Object.entries(PIECES).map(([k, p]) => <label key={k}><input type="radio" name="piece" checked={k === piece} onChange={() => change({ piece: k })} /><span>{p.name}</span></label>)}
          </fieldset>
          <fieldset className="picker picker--wide"><legend>Speed</legend>
            {Object.keys(SPEEDS).map((s) => <label key={s}><input type="radio" name="speed" checked={s === speed} onChange={() => change({ speed: s })} /><span>{s[0].toUpperCase() + s.slice(1)}</span></label>)}
          </fieldset>
          <button className="go" onClick={() => (playing ? stop() : start())}>{playing ? 'Stand' : 'Look to'}</button>
        </div>
        <div className="circle__tower">
          <ol className="circle__row" aria-label={here ? `Row ${here.row + 1} of ${rows.length}` : 'The first row'}>
            {rows[here?.row ?? 0].map((b, i) => (
              <li key={b} className={[b === bell && 'is-mine', playing && here && i + 1 === here.place && 'is-now'].filter(Boolean).join(' ') || undefined}>{b}</li>
            ))}
          </ol>
          <button className="circle__bell" onClick={playing ? pull : () => strikeNow(bell, STAGE)} aria-label={`Pull bell ${bell}`}>
            <span key={pulled} className={pulled ? 'is-pulled' : undefined}><Bell size={1.01} /></span>
          </button>
          <p className="circle__next">{playing ? (here ? `Row ${here.row + 1} of ${rows.length}. You are in place ${rows[here.row].indexOf(bell) + 1}.` : 'Look to. Treble’s going…') : 'Tap the bell to hear it, or say “Look to” to start.'}</p>
        </div>
      </div>
      <section className="verdict" aria-live="polite">
        {result ? <Verdict result={result} /> : <p>Your striking will appear here, one mark for each pull.</p>}
      </section>
      <p>Ready for the real thing? <Link to={`/visit?rope=${bell}`}>Book rope {bell} on a Tuesday</Link>.</p>
    </div>
  )
}

export function Verdict({ result }) {
  const reach = 0.4
  return (
    <>
      <h2>{result.percent}% struck</h2>
      <p className="lead">{advise(result)}</p>
      <ol className="striking">
        {result.results.map((r, i) => (
          <li key={i} className={`striking__${r.grade}`}>
            <span className="striking__lane" aria-hidden="true">{r.error !== null && <i style={{ left: `${50 + Math.max(-1, Math.min(1, r.error / reach)) * 50}%` }} />}</span>
            <span>Pull {i + 1}: {r.error === null ? 'missed' : Math.abs(r.error) < 0.005 ? 'exact' : `${Math.round(Math.abs(r.error) * 1000)} ms ${r.error > 0 ? 'late' : 'early'}`}</span>
          </li>
        ))}
      </ol>
      {result.extras > 0 && <p>{result.extras === 1 ? 'One extra pull.' : `${result.extras} extra pulls.`}</p>}
    </>
  )
}
