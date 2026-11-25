import { useRef, useState } from 'react'
import Bell from '../components/Bell.jsx'
import Field, { ErrorSummary } from '../components/Field.jsx'
import { BELLS } from '../content/bells.js'
import { checkPledge, giftAid, pounds, totals } from '../lib/giving.js'
import { useQuery } from '../lib/router.jsx'

const AMOUNTS = [10, 50, 200, 1000]

export default function Appeal() {
  const [query, setQuery] = useQuery()
  const bell = BELLS.find((b) => String(b.number) === query.get('bell')) ?? BELLS[4]
  const sum = totals(BELLS)
  return (
    <div className="page">
      <header className="page__head">
        <h1>Mend a bell</h1>
        <p className="lead">{pounds(sum.left)} still to find. Every bell has its own fault and its own fund, so you can see what your money does.</p>
      </header>
      <ul className="peal" aria-label="The eight bells">
        {BELLS.map((b) => (
          <li key={b.number}>
            <button aria-pressed={b === bell} onClick={() => setQuery({ bell: b.number })}>
              <Bell size={0.5 + b.number * 0.0625} filled={b.raised / b.cost} cracked={b.number === 5} />
              <b>{b.name}</b>
              <span>{b.raised >= b.cost ? 'Paid for' : `${Math.floor((100 * b.raised) / b.cost)}% raised`}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="appeal">
        <section>
          <h2>{bell.name}</h2>
          <p className="inscription">“{bell.words}”</p>
          <dl className="facts">
            <div><dt>Bell</dt><dd>{bell.number} of 8, in {bell.note}</dd></div>
            <div><dt>Weight</dt><dd>{bell.weight.replace(/-/g, '–')} cwt</dd></div>
            <div><dt>Cast</dt><dd>{bell.cast}, {bell.founder}</dd></div>
            <div><dt>Fault</dt><dd>{bell.fault}</dd></div>
            <div><dt>Work</dt><dd>{bell.work}</dd></div>
            <div><dt>Cost</dt><dd>{pounds(bell.cost)}, of which {pounds(bell.raised)} raised</dd></div>
          </dl>
        </section>
        <Pledge key={bell.number} bell={bell} />
      </div>
    </div>
  )
}

function Pledge({ bell }) {
  const [form, setForm] = useState({ amount: '50', name: '', email: '' })
  const [eligible, setEligible] = useState(false)
  const [band, setBand] = useState('basic')
  const [errors, setErrors] = useState({})
  const [done, setDone] = useState(null)
  const summary = useRef(null)
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }))
  const amount = Number(form.amount) > 0 ? Number(form.amount) : 0
  const gift = giftAid(amount, { eligible, band })
  const left = bell.cost - bell.raised

  const submit = (e) => {
    e.preventDefault()
    const found = checkPledge(form)
    setErrors(found)
    if (Object.keys(found).length) requestAnimationFrame(() => summary.current?.focus())
    else setDone({ ...gift, name: form.name.trim() })
  }

  if (done) {
    return (
      <section className="pledge pledge--done" role="status">
        <h2>Thank you, {done.name}</h2>
        <p>{pounds(done.received)} would go to {bell.name}. This is a demonstration, so no money has been taken and nothing was sent.</p>
        <button className="plain" onClick={() => setDone(null)}>Change the pledge</button>
      </section>
    )
  }
  return (
    <form className="pledge" onSubmit={submit} noValidate aria-label={`Pledge to ${bell.name}`}>
      <h2>Pledge to {bell.name}</h2>
      {left <= 0 && <p className="pledge__note">{bell.name} is paid for. Anything you give here moves on to Mercy.</p>}
      <ErrorSummary errors={errors} boxRef={summary} />
      <div className="amounts" role="group" aria-label="Common amounts">
        {AMOUNTS.map((a) => <button type="button" key={a} aria-pressed={form.amount === String(a)} onClick={() => set('amount')(String(a))}>{pounds(a)}</button>)}
      </div>
      <Field label="Amount in pounds" prefix="£" inputMode="decimal" value={form.amount} onChange={set('amount')} error={errors.amount} />
      <Field label="Name for the donors’ board" autoComplete="name" value={form.name} onChange={set('name')} error={errors.name} />
      <Field label="Email" type="email" autoComplete="email" value={form.email} onChange={set('email')} error={errors.email} />
      <label className="tick"><input type="checkbox" checked={eligible} onChange={(e) => setEligible(e.target.checked)} /><span>I pay UK tax and would like the trust to claim Gift Aid</span></label>
      {eligible && (
        <label className="select">Highest rate of income tax you pay
          <select value={band} onChange={(e) => setBand(e.target.value)}>
            <option value="basic">Basic, 20%</option><option value="higher">Higher, 40%</option><option value="additional">Additional, 45%</option>
          </select>
        </label>
      )}
      <p className="receipt" role="status">
        <b>{pounds(gift.received)}</b> reaches the bell
        {gift.extra > 0 && <>, {pounds(gift.extra)} of it from Gift Aid</>}.
        {gift.reclaim > 0 && <> You can claim back {pounds(gift.reclaim)}, so it costs you {pounds(gift.cost)}.</>}
      </p>
      <button className="go">Pledge {pounds(amount)}</button>
    </form>
  )
}
