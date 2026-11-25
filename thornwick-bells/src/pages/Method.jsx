import { useEffect, useMemo } from 'react'
import BlueLine from '../components/BlueLine.jsx'
import { Link, useQuery } from '../lib/router.jsx'
import { findMethod } from '../ringing/methods.js'
import { BELL_NAMES, rowToString } from '../ringing/notation.js'
import { schedule } from '../ringing/striking.js'
import { describe, factorial, pathOf, ring } from '../ringing/touch.js'
import { useRinging } from '../ringing/useRinging.js'
import NotFound from './NotFound.jsx'

const NAMES = { p: 'Plain', b: 'Bob', s: 'Single' }
const SPEEDS = { slow: 0.32, steady: 0.24, brisk: 0.17 }

export default function Method({ id }) {
  const method = findMethod(id)
  return method ? <Sheet method={method} /> : <NotFound what="That method is not in our book." />
}

/** Calls come from the address, so anything that does not belong is dropped rather than trusted. */
export function readCalls(text, method) {
  const letters = method.calls ? (method.calls.single ? 'pbs' : 'pb') : ''
  return [...(text ?? '')].filter((c) => letters.includes(c)).slice(0, 60).join('')
}

function Sheet({ method }) {
  const [query, setQuery] = useQuery()
  const asked = Number(query.get('bell'))
  const bell = Number.isInteger(asked) && asked >= 1 && asked <= method.stage ? asked : 2
  const calls = readCalls(query.get('calls'), method)
  const speed = SPEEDS[query.get('speed')] ? query.get('speed') : 'steady'
  const touch = useMemo(() => ring(method, calls), [method, calls])
  const blows = useMemo(() => schedule(touch.rows, { gap: SPEEDS[speed], cover: method.stage % 2 === 1 }), [touch, speed, method])
  const { playing, current, play, stop } = useRinging()
  useEffect(() => stop, [touch, speed, stop])
  const here = playing && current >= 0 ? blows[current] : null
  const leads = touch.leadHeads.map((l, i) => ({
    ...l, from: i * touch.leadLength, rows: touch.rows.slice(i * touch.leadLength, (i + 1) * touch.leadLength + 1),
  }))
  const total = method.stage % 2 ? method.stage + 1 : method.stage
  const path = useMemo(() => pathOf(touch.rows, bell), [touch, bell])
  const setCall = (i, value) => {
    const list = [...(calls || 'p'.repeat(touch.leadHeads.length))]
    list[i] = value
    setQuery({ calls: list.join('') })
  }

  return (
    <div className="page">
      <p className="crumb"><Link to="/methods">The method book</Link></p>
      <header className="page__head">
        <h1>{method.name}</h1>
        <p className="lead">{method.story}</p>
        <p className="notation"><span>Place notation</span><code>{method.notation}</code></p>
      </header>
      <div className="sheet">
        <div className="sheet__tools">
          <fieldset className="picker">
            <legend>Follow bell</legend>
            {Array.from({ length: method.stage }, (_, i) => i + 1).map((b) => (
              <label key={b}><input type="radio" name="bell" checked={b === bell} onChange={() => setQuery({ bell: b })} /><span>{BELL_NAMES[b - 1]}</span></label>
            ))}
          </fieldset>
          <fieldset className="picker picker--wide">
            <legend>Speed</legend>
            {Object.keys(SPEEDS).map((s) => (
              <label key={s}><input type="radio" name="speed" checked={s === speed} onChange={() => setQuery({ speed: s })} /><span>{s[0].toUpperCase() + s.slice(1)}</span></label>
            ))}
          </fieldset>
          <button className="go" onClick={() => (playing ? stop() : play(blows, total))}>{playing ? 'Stand' : 'Ring it'}</button>
          <p className="sheet__now" aria-live="off">
            <b>{rowToString(touch.rows[here?.row ?? 0])}</b>
            <span>{here ? `Change ${here.row}: your bell is ${describe(path, here.row)}` : 'Rounds. Ready when you are.'}</span>
          </p>
          <div className={touch.isTrue && touch.cameRound ? 'proof' : 'proof proof--false'} role="status">
            <p><b>{touch.changes} changes</b> of {factorial(method.stage).toLocaleString('en-GB')} possible.</p>
            <p>{touch.isTrue ? 'True: no row is repeated.' : `False: ${touch.repeats[0].row} is rung at change ${touch.repeats[0].first} and again at ${touch.repeats[0].again}.`}</p>
            <p>{touch.cameRound ? 'It comes round.' : `It stops on ${touch.leadHeads.at(-1).head}, so it does not come round.`}</p>
          </div>
          {method.calls ? (
            <section className="calls">
              <h2>Be the conductor</h2>
              <p>Call a bob{method.calls.single ? ' or a single' : ''} at the end of a lead and the bells go a different way. Find a touch that is true and comes round.</p>
              {method.touches && <p className="calls__ready">{method.touches.map((t) => <button key={t.name} className="plain" onClick={() => setQuery({ calls: t.calls })}>{t.name}</button>)}</p>}
              <ol>
                {touch.leadHeads.map((l, i) => (
                  <li key={i}>
                    <label>Lead {i + 1}
                      <select value={l.call} onChange={(e) => setCall(i, e.target.value)}>
                        {['p', 'b', ...(method.calls.single ? ['s'] : [])].map((c) => <option key={c} value={c}>{NAMES[c]}</option>)}
                      </select>
                    </label>
                    <span>{l.head}</span>
                  </li>
                ))}
              </ol>
              <p className="calls__row">
                <button className="plain" disabled={touch.leadHeads.length >= 60} onClick={() => setQuery({ calls: `${calls || 'p'.repeat(touch.leadHeads.length)}p` })}>Add a lead</button>
                <button className="plain" disabled={touch.leadHeads.length <= 1} onClick={() => setQuery({ calls: (calls || 'p'.repeat(touch.leadHeads.length)).slice(0, -1) })}>Take one off</button>
                <button className="plain" disabled={!calls} onClick={() => setQuery({ calls: null })}>Plain course</button>
              </p>
            </section>
          ) : <p className="calls__none">This one is rung as a plain course here.</p>}
        </div>
        <div className="sheet__leads" tabIndex={0} role="region" aria-label={`Every lead of ${method.name}`}>
          {leads.map((l, i) => (
            <figure key={i}>
              <figcaption>Lead {i + 1}{l.call !== 'p' && <b>{NAMES[l.call]}</b>}</figcaption>
              <BlueLine rows={l.rows} bell={bell} from={l.from} currentRow={here?.row ?? -1} label={`Lead ${i + 1}, bell ${bell}, ending on ${l.head}`} />
            </figure>
          ))}
        </div>
      </div>
    </div>
  )
}
