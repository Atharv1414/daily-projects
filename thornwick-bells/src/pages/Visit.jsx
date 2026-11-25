import { useMemo, useRef, useState } from 'react'
import Field, { ErrorSummary } from '../components/Field.jsx'
import { checkVisit, isoDate, longDate, nextEvenings, takenRopes } from '../lib/evenings.js'
import { useQuery } from '../lib/router.jsx'

export default function Visit({ today = new Date() }) {
  const [query, setQuery] = useQuery()
  const stamp = isoDate(today)
  const evenings = useMemo(() => nextEvenings(new Date(`${stamp}T12:00`)), [stamp])
  const evening = evenings.find((e) => isoDate(e) === query.get('date')) ?? null
  const taken = evening ? takenRopes(evening) : new Set()
  const asked = Number(query.get('rope'))
  const rope = asked >= 1 && asked <= 8 && Number.isInteger(asked) && !taken.has(asked) ? asked : null
  const [form, setForm] = useState({ name: '', email: '', age: '', guardian: '' })
  const [errors, setErrors] = useState({})
  const [done, setDone] = useState(null)
  const summary = useRef(null)
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }))
  const young = Number(form.age) >= 10 && Number(form.age) < 18

  const submit = (e) => {
    e.preventDefault()
    const found = checkVisit({ ...form, date: evening, rope })
    setErrors(found)
    if (Object.keys(found).length) requestAnimationFrame(() => summary.current?.focus())
    else setDone({ name: form.name.trim(), evening, rope })
  }

  return (
    <div className="page page--visit">
      <header className="page__head">
        <h1>Book a rope</h1>
        <p className="lead">Your first evening is an hour with one teacher and one bell, tied so that it cannot sound. By the end you will have handled a bell that weighs more than you do.</p>
      </header>
      {done ? (
        <section className="booked" role="status">
          <h2>Rope {done.rope} is yours, {done.name}</h2>
          <p>{longDate(done.evening)}, half past seven. Come to the small door on the north side. This is a demonstration, so nothing has been sent or saved.</p>
          <button className="plain" onClick={() => setDone(null)}>Change the booking</button>
        </section>
      ) : (
        <form className="visit" onSubmit={submit} noValidate>
          <ErrorSummary errors={errors} boxRef={summary} />
          <fieldset className="visit__dates">
            <legend>Choose an evening</legend>
            {evenings.map((e) => (
              <label key={isoDate(e)}>
                <input type="radio" name="date" checked={evening === e} onChange={() => setQuery({ date: isoDate(e) })} />
                <span><b>{e.getDate()}</b>{e.toLocaleDateString('en-GB', { month: 'short' })}<small>{8 - takenRopes(e).size} free</small></span>
              </label>
            ))}
          </fieldset>
          <fieldset className="visit__ropes" disabled={!evening}>
            <legend>Choose a rope</legend>
            {!evening && <p className="field__hint">Pick an evening first. Some ropes are already spoken for.</p>}
            <div>
              {Array.from({ length: 8 }, (_, i) => i + 1).map((r) => (
                <label key={r} className={taken.has(r) ? 'is-taken' : undefined}>
                  <input type="radio" name="rope" disabled={taken.has(r)} checked={rope === r && Boolean(evening)} onChange={() => setQuery({ rope: r })} />
                  <span><i aria-hidden="true" />{r}<small>{taken.has(r) ? 'Taken' : r === 1 ? 'Lightest' : r === 8 ? 'Heaviest' : ' '}</small></span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="visit__you">
            <Field label="Your name" autoComplete="name" value={form.name} onChange={set('name')} error={errors.name} />
            <Field label="Email" type="email" autoComplete="email" value={form.email} onChange={set('email')} error={errors.email} />
            <Field label="Age" hint="10 or over. Our oldest ringer is 91." inputMode="numeric" value={form.age} onChange={set('age')} error={errors.age} />
            {young && <Field label="Adult coming with you" value={form.guardian} onChange={set('guardian')} error={errors.guardian} />}
            <button className="go">{evening && rope ? `Book rope ${rope} for ${longDate(evening)}` : 'Book'}</button>
          </div>
        </form>
      )}
      <section className="find">
        <h2>Getting up there</h2>
        <svg className="find__tower" viewBox="0 0 300 420" role="img" aria-label="The tower in section: door, 41 steps, ringing room, clock room, bells">
          <path className="find__wall" d="M60 410V70l90-50 90 50v340M50 410h200" />
          <path className="find__floor" d="M60 290h180M60 210h180M60 120h180" />
          <path className="find__stair" d="M70 408v-12h12v-12h12v-12h12v-12h12v-12h12v-12h12v-12h12v-12h12v-12h10" />
          <path className="find__rope" d="M100 120v132M125 120v138M150 120v140M175 120v138M200 120v132" />
          <path className="find__bells" d="M88 92h24l5 22H83zM118 88h24l6 26h-36zM152 86h26l7 28h-40zM190 90h24l5 24h-34z" />
          <circle className="find__clock" cx="150" cy="165" r="22" /><path className="find__stair" d="M150 165v-14M150 165h10" />
          <text x="150" y="60">Bells</text><text x="202" y="170">Clock</text><text x="150" y="282">Ringing room</text><text x="192" y="350">41 steps</text>
        </svg>
        <div>
          <p>The stair is a tight spiral with a rope rail, and there is no lift. If stairs are a problem, tell us: there is a set of handbells in the north aisle and we ring the same methods on those.</p>
          <p>St Osyth’s is five minutes from Thornwick bus station. Park in Crake Street after six.</p>
        </div>
      </section>
    </div>
  )
}
