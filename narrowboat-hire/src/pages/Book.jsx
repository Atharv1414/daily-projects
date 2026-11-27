import { useRef, useState } from 'react'
import Boat from '../components/Boat.jsx'
import { FLEET, boatById } from '../data/fleet.js'
import { bookingReference, normalisePhone, validateCrew } from '../lib/booking.js'
import { routeById } from '../lib/planner.js'
import { DURATIONS, EXTRAS, longDate, money, nextStarts, quote, startProblem } from '../lib/pricing.js'
import { Link, useSearchState } from '../lib/router.jsx'
import { today as todayUtc } from '../lib/today.js'
import { usePageTitle } from '../lib/usePageTitle.js'

const STEPS = ['Boat and dates', 'Extras', 'Your crew', 'Check and confirm']
const DEFAULTS = { step: '1', boat: 'kestrel', nights: '7', start: '', route: '', dog: '', bikes: '0', lesson: '', hamper: '' }

function Field({ id, label, hint, error, children }) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return (
    <div className={`field${error ? ' field--error' : ''}`}>
      <label htmlFor={id} className="field__label">{label}</label>
      {hint && <p id={`${id}-hint`} className="field__hint">{hint}</p>}
      {error && <p id={`${id}-error`} className="field__error">{error}</p>}
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
    </div>
  )
}

function Summary({ boat, nights, start, extras, route, today }) {
  const q = quote({ boat, nights, start, extras, today })
  return (
    <aside className="summary" aria-labelledby="summary-heading">
      <h2 id="summary-heading">Your holiday</h2>
      <Boat boat={boat} decorative />
      <p className="summary__what">
        <strong>{boat.name}</strong>, {nights} nights{start && q.ok ? ` from ${longDate(start)}` : ''}
      </p>
      {route && <p className="summary__route">Planned route: {route.name}</p>}
      {q.ok ? (
        <>
          <ul className="summary__lines">
            {q.lines.map((l) => (
              <li key={l.label}>
                <span>{l.label}</span> <span>{money(l.amount)}</span>
              </li>
            ))}
          </ul>
          <p className="summary__total">
            <span>Total</span> <span>{money(q.total)}</span>
          </p>
          <p className="summary__due">
            {q.balanceDue
              ? `${money(q.dueNow)} deposit today, then ${money(q.balance)} by ${longDate(q.balanceDue)}.`
              : `Less than eight weeks to go, so the full ${money(q.total)} is due today.`}{' '}
            We also hold a {money(q.securityDeposit)} refundable security deposit at handover.
          </p>
        </>
      ) : (
        <p className="summary__due">Choose a start date to see the price.</p>
      )}
    </aside>
  )
}

export default function Book() {
  usePageTitle('Book a boat')
  const [state, update] = useSearchState(DEFAULTS)
  const [crew, setCrew] = useState({ name: '', email: '', phone: '', crew: '', experience: '', adultAtHelm: false, terms: false })
  const [errors, setErrors] = useState({})
  const [confirmed, setConfirmed] = useState(null)
  const errorSummary = useRef(null)
  const today = todayUtc()

  const boat = boatById[state.boat] ?? boatById.kestrel
  const nights = DURATIONS[state.nights] ? Number(state.nights) : 7
  const route = state.route ? routeById(state.route) : null
  const routeFits = !route || route.maxLength >= boat.length
  const extras = { dog: state.dog === 'yes' && boat.dogs, bikes: Number(state.bikes) || 0, lesson: state.lesson === 'yes', hamper: state.hamper === 'yes' }
  const step = state.step === 'done' ? 'done' : Math.min(4, Math.max(1, Number(state.step) || 1))
  const dateProblem = state.start ? startProblem(state.start, nights, today) : null
  const go = (next) => {
    update({ step: String(next) })
    window.scrollTo({ top: 0 })
    requestAnimationFrame(() => document.querySelector('#book-step')?.focus())
  }

  const submitCrew = (event) => {
    event.preventDefault()
    const found = validateCrew(crew, boat)
    setErrors(found)
    if (Object.keys(found).length) {
      requestAnimationFrame(() => errorSummary.current?.focus())
      return
    }
    go(4)
  }

  const confirm = () => {
    const q = quote({ boat, nights, start: state.start, extras, today })
    const reference = bookingReference({ boat: boat.id, nights, start: state.start, email: crew.email.trim().toLowerCase() })
    setConfirmed({ reference, quote: q, name: crew.name.trim(), email: crew.email.trim() })
    update({ step: 'done' })
    requestAnimationFrame(() => document.querySelector('#book-step')?.focus())
  }

  if (step === 'done') {
    return (
      <section className="confirmed" aria-labelledby="book-step">
        <p className="milepost">Booked</p>
        <h1 id="book-step" tabIndex={-1}>{confirmed ? `See you at the wharf, ${confirmed.name.split(' ')[0]}` : 'Booking finished'}</h1>
        {confirmed ? (
          <>
            <p className="confirmed__ref">
              Reference <strong>{confirmed.reference}</strong>
            </p>
            <p>
              {boat.name} is yours from 2 pm on {longDate(state.start)} until 9 am on {longDate(confirmed.quote.end)}. In a real booking
              we would now email {confirmed.email}. This is a demonstration, so nothing has been sent or charged.
            </p>
            <p>
              <Link to="/first-time">Read the guide to working locks</Link> before you come.
            </p>
          </>
        ) : (
          <p>Booking details are only kept in the tab where you made them. Nothing was sent anywhere.</p>
        )}
        <Link to="/" className="button button--quiet">Back to the start</Link>
      </section>
    )
  }

  const errorList = Object.entries(errors)
  return (
    <div className="book">
      <header className="page-head">
        <p className="milepost">Booking</p>
        <h1 tabIndex={-1}>Book a boat</h1>
        <ol className="steps" aria-label="Booking steps">
          {STEPS.map((label, i) => (
            <li key={label} className={i + 1 === step ? 'steps__item steps__item--on' : i + 1 < step ? 'steps__item steps__item--done' : 'steps__item'} aria-current={i + 1 === step ? 'step' : undefined}>
              <span className="steps__n">{i + 1}</span> {label}
            </li>
          ))}
        </ol>
      </header>

      <div className="book__body">
        <div className="book__main">
          <h2 id="book-step" tabIndex={-1}>{STEPS[step - 1]}</h2>

          {step === 1 && (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                if (!state.start || dateProblem) {
                  update({ start: state.start || '' })
                  document.querySelector('#start')?.focus()
                  return
                }
                go(2)
              }}
              noValidate
            >
              <fieldset className="boats">
                <legend className="field__label">Boat</legend>
                {FLEET.map((b) => (
                  <label key={b.id} className={`boats__option${b.id === boat.id ? ' boats__option--on' : ''}`}>
                    <input type="radio" name="boat" value={b.id} checked={b.id === boat.id} onChange={() => update({ boat: b.id, dog: b.dogs ? state.dog : null })} />
                    <span className="boats__name">{b.name}</span>
                    <span className="boats__meta">{b.length} ft · sleeps {b.berths}{b.dogs ? ' · dogs welcome' : ''}</span>
                  </label>
                ))}
              </fieldset>
              {!routeFits && (
                <p className="notice" role="status">
                  {boat.name} is too long for the {route.name} you planned. <Link to={`/routes?boat=${boat.id}&nights=${nights}`}>Find a route for her</Link>{' '}
                  or pick a boat of {route.maxLength} ft or less.
                </p>
              )}
              <Field id="nights" label="How long">
                {(props) => (
                  <select {...props} value={nights} onChange={(e) => update({ nights: e.target.value, start: null })}>
                    {Object.entries(DURATIONS).map(([n, d]) => (
                      <option key={n} value={n}>{`${d.label}: ${n} nights, starting ${d.starts.map((s) => ({ Mon: 'Monday', Fri: 'Friday' })[s]).join(' or ')}`}</option>
                    ))}
                  </select>
                )}
              </Field>
              <div className="quick-dates">
                <p className="field__label" id="quick-label">Next available starts</p>
                <ul aria-labelledby="quick-label">
                  {nextStarts(nights, today).map((d) => (
                    <li key={d}>
                      <button type="button" className={`chip${state.start === d ? ' chip--on' : ''}`} aria-pressed={state.start === d} onClick={() => update({ start: d })}>
                        {longDate(d).replace(/ \d{4}$/, '')}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
              <Field id="start" label="Or choose a start date" hint="Collect the boat from 2 pm." error={dateProblem}>
                {(props) => <input type="date" {...props} value={state.start} onChange={(e) => update({ start: e.target.value })} />}
              </Field>
              <button type="submit" className="button" disabled={!state.start || Boolean(dateProblem)}>
                Continue to extras
              </button>
            </form>
          )}

          {step === 2 && (
            <form onSubmit={(e) => { e.preventDefault(); go(3) }}>
              <div className="extras">
                <label className={`extra${boat.dogs ? '' : ' extra--off'}`}>
                  <input type="checkbox" checked={extras.dog} disabled={!boat.dogs} onChange={(e) => update({ dog: e.target.checked ? 'yes' : null })} />
                  <span>
                    {EXTRAS.dog.label} <strong>{money(EXTRAS.dog.price)}</strong>
                    {!boat.dogs && <em> {boat.name} is not a dog-friendly boat.</em>}
                  </span>
                </label>
                <label className="extra extra--number">
                  <span>
                    {EXTRAS.bikes.label} <strong>{money(EXTRAS.bikes.price)} each</strong>
                  </span>
                  <input type="number" min="0" max={EXTRAS.bikes.max} value={extras.bikes} onChange={(e) => update({ bikes: String(Math.max(0, Math.min(EXTRAS.bikes.max, Number(e.target.value) || 0))) })} />
                </label>
                <label className="extra">
                  <input type="checkbox" checked={extras.lesson} onChange={(e) => update({ lesson: e.target.checked ? 'yes' : null })} />
                  <span>{EXTRAS.lesson.label} <strong>{money(EXTRAS.lesson.price)}</strong></span>
                </label>
                <label className="extra">
                  <input type="checkbox" checked={extras.hamper} onChange={(e) => update({ hamper: e.target.checked ? 'yes' : null })} />
                  <span>{EXTRAS.hamper.label} <strong>{money(EXTRAS.hamper.price)}</strong></span>
                </label>
              </div>
              <div className="book__nav">
                <button type="button" className="button button--quiet" onClick={() => go(1)}>Back</button>
                <button type="submit" className="button">Continue to your crew</button>
              </div>
            </form>
          )}

          {step === 3 && (
            <form onSubmit={submitCrew} noValidate>
              {errorList.length > 0 && (
                <div className="error-summary" role="alert" tabIndex={-1} ref={errorSummary} aria-labelledby="error-summary-title">
                  <h3 id="error-summary-title">There {errorList.length === 1 ? 'is a problem' : `are ${errorList.length} problems`}</h3>
                  <ul>
                    {errorList.map(([field, message]) => (
                      <li key={field}><a href={`#${field}`}>{message}</a></li>
                    ))}
                  </ul>
                </div>
              )}
              <Field id="name" label="Lead name" error={errors.name}>
                {(props) => <input {...props} autoComplete="name" value={crew.name} onChange={(e) => setCrew({ ...crew, name: e.target.value })} />}
              </Field>
              <Field id="email" label="Email" error={errors.email}>
                {(props) => <input {...props} type="email" autoComplete="email" value={crew.email} onChange={(e) => setCrew({ ...crew, email: e.target.value })} />}
              </Field>
              <Field id="phone" label="Mobile number" hint="For the wharf to reach you on the day." error={errors.phone}>
                {(props) => (
                  <input {...props} type="tel" autoComplete="tel" value={crew.phone} onChange={(e) => setCrew({ ...crew, phone: e.target.value })} onBlur={() => setCrew((c) => ({ ...c, phone: c.phone && /^0\d{9,10}$/.test(normalisePhone(c.phone)) ? normalisePhone(c.phone) : c.phone }))} />
                )}
              </Field>
              <Field id="crew" label="How many people, including children?" hint={`${boat.name} sleeps ${boat.berths}.`} error={errors.crew}>
                {(props) => <input {...props} type="number" min="1" max="12" inputMode="numeric" value={crew.crew} onChange={(e) => setCrew({ ...crew, crew: e.target.value })} />}
              </Field>
              <Field id="experience" label="Has anyone steered a narrowboat before?" error={errors.experience}>
                {(props) => (
                  <select {...props} value={crew.experience} onChange={(e) => setCrew({ ...crew, experience: e.target.value })}>
                    <option value="">Choose one</option>
                    <option value="none">No, this is our first time</option>
                    <option value="some">Yes, once or twice</option>
                    <option value="lots">Yes, we know what we are doing</option>
                  </select>
                )}
              </Field>
              <div className={`check${errors.adultAtHelm ? ' check--error' : ''}`}>
                {errors.adultAtHelm && <p id="adultAtHelm-error" className="field__error">{errors.adultAtHelm}</p>}
                <label>
                  <input id="adultAtHelm" type="checkbox" checked={crew.adultAtHelm} aria-describedby={errors.adultAtHelm ? 'adultAtHelm-error' : undefined} onChange={(e) => setCrew({ ...crew, adultAtHelm: e.target.checked })} />
                  An adult will be at the tiller whenever the boat is moving
                </label>
              </div>
              <div className={`check${errors.terms ? ' check--error' : ''}`}>
                {errors.terms && <p id="terms-error" className="field__error">{errors.terms}</p>}
                <label>
                  <input id="terms" type="checkbox" checked={crew.terms} aria-describedby={errors.terms ? 'terms-error' : undefined} onChange={(e) => setCrew({ ...crew, terms: e.target.checked })} />
                  I have read the hire terms (made up, like everything here)
                </label>
              </div>
              <div className="book__nav">
                <button type="button" className="button button--quiet" onClick={() => go(2)}>Back</button>
                <button type="submit" className="button">Check the booking</button>
              </div>
            </form>
          )}

          {step === 4 && (() => {
            const q = quote({ boat, nights, start: state.start, extras, today })
            const crewReady = Object.keys(validateCrew(crew, boat)).length === 0
            if (!q.ok || !crewReady) {
              return (
                <p className="notice" role="status">
                  Some details are missing{!crewReady ? ' (crew details are not kept if the page reloads)' : ''}.{' '}
                  <button type="button" className="linkish" onClick={() => go(q.ok ? 3 : 1)}>Go back and fill them in</button>
                </p>
              )
            }
            return (
              <div className="review">
                <dl className="review__list">
                  <div><dt>Boat</dt><dd>{boat.name}, {boat.length} ft</dd></div>
                  <div><dt>Collect</dt><dd>2 pm, {longDate(state.start)}</dd></div>
                  <div><dt>Return</dt><dd>9 am, {longDate(q.end)}</dd></div>
                  <div><dt>Route</dt><dd>{route && routeFits ? route.name : 'Not planned yet: talk to us at handover'}</dd></div>
                  <div><dt>Lead name</dt><dd>{crew.name}</dd></div>
                  <div><dt>Crew</dt><dd>{crew.crew}</dd></div>
                  <div><dt>Due today</dt><dd>{money(q.dueNow)}</dd></div>
                </dl>
                <div className="book__nav">
                  <button type="button" className="button button--quiet" onClick={() => go(3)}>Back</button>
                  <button type="button" className="button button--buoy" onClick={confirm}>Confirm booking (demo)</button>
                </div>
              </div>
            )
          })()}
        </div>
        <Summary boat={boat} nights={nights} start={dateProblem ? '' : state.start} extras={extras} route={route && routeFits ? route : null} today={today} />
      </div>
    </div>
  )
}
