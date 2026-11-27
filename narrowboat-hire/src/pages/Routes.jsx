import CanalMap from '../components/CanalMap.jsx'
import Profile from '../components/Profile.jsx'
import StripMap from '../components/StripMap.jsx'
import { FLEET, boatById } from '../data/fleet.js'
import { placeById } from '../data/network.js'
import { PACES, itinerary, routeById, suggestRoutes } from '../lib/planner.js'
import { DURATIONS } from '../lib/pricing.js'
import { Link, useSearchState } from '../lib/router.jsx'
import { usePageTitle } from '../lib/usePageTitle.js'

const DEFAULTS = { nights: '7', pace: 'steady', boat: 'kestrel', route: '' }

const hoursText = (h) => {
  const whole = Math.floor(h)
  const minutes = Math.round((h - whole) * 60)
  return minutes === 60 ? `${whole + 1} h` : minutes ? `${whole} h ${minutes} min` : `${whole} h`
}

export default function Routes() {
  usePageTitle('Plan a route')
  const [state, update] = useSearchState(DEFAULTS)
  const nights = DURATIONS[state.nights] ? Number(state.nights) : 7
  const pace = PACES[state.pace] ? state.pace : 'steady'
  const boat = boatById[state.boat] ?? boatById.kestrel
  const result = suggestRoutes({ nights, pace, boatLength: boat.length })
  const options = result.routes.slice(0, 5)
  const requested = state.route ? routeById(state.route) : null
  const requestedFits = requested && requested.maxLength >= boat.length
  const route = (requestedFits ? requested : null) ?? options[0] ?? null
  const days = route ? itinerary(route, nights, pace) : []
  const nightStops = []
  days.reduce((legsSoFar, d) => {
    const end = legsSoFar + d.legs.length
    if (d.number < days.length) nightStops.push(end)
    return end
  }, 0)

  return (
    <div className="planner">
      <header className="page-head">
        <p className="milepost">The planner</p>
        <h1 tabIndex={-1}>Plan a route</h1>
        <p className="lede">
          Tell us how long you have, how hard you want to work and which boat you fancy. We&apos;ll suggest routes that
          use most of that time, with each night at a good mooring.
        </p>
      </header>

      <form className="planner__controls" onSubmit={(e) => e.preventDefault()} aria-label="Holiday details">
        <label className="field">
          <span className="field__label">How long</span>
          <select value={nights} onChange={(e) => update({ nights: e.target.value, route: null })}>
            {Object.entries(DURATIONS).map(([n, d]) => (
              <option key={n} value={n}>{`${d.label} (${n} nights)`}</option>
            ))}
          </select>
        </label>
        <fieldset className="field field--pace">
          <legend className="field__label">Pace</legend>
          <div className="pace">
            {Object.entries(PACES).map(([key, p]) => (
              <label key={key} className="pace__option">
                <input type="radio" name="pace" value={key} checked={pace === key} onChange={() => update({ pace: key, route: null })} />
                <span>
                  <strong>{p.label}</strong> {p.hours} h a day
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="field">
          <span className="field__label">Boat</span>
          <select value={boat.id} onChange={(e) => update({ boat: e.target.value })}>
            {FLEET.map((b) => (
              <option key={b.id} value={b.id}>{`${b.name}: ${b.length} ft, sleeps ${b.berths}`}</option>
            ))}
          </select>
        </label>
      </form>

      <p className="planner__summary" aria-live="polite">
        {nights} nights at a {PACES[pace].label.toLowerCase()} pace gives about <strong>{hoursText(result.available)}</strong>{' '}
        of cruising, counting a three-hour first afternoon.
        {result.blockedByLength > 0 && ` ${boat.name} is too long for the narrow locks, which rules out ${result.blockedByLength} other routes.`}
        {result.spareTime && ' Nothing on our water fills that much time, so these routes leave you days to spare at the best moorings.'}
      </p>

      {requested && !requestedFits && (
        <p className="notice" role="status">
          {boat.name} is {boat.length} ft, too long for the {requested.name}. It needs a boat of {requested.maxLength} ft or less, so
          here are routes that suit her instead.
        </p>
      )}

      {options.length === 0 ? (
        <p className="notice" role="status">
          No route fits that holiday with {boat.name}. Try a different pace or a shorter boat.
        </p>
      ) : (
        <div className="planner__body">
          <section aria-labelledby="options-heading" className="options">
            <h2 id="options-heading">Suggested routes</h2>
            <ol className="options__list">
              {options.map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/routes?nights=${nights}&pace=${pace}&boat=${boat.id}&route=${encodeURIComponent(r.id)}`}
                    className={`option${route?.id === r.id ? ' option--on' : ''}`}
                    aria-current={route?.id === r.id ? 'true' : undefined}
                  >
                    <span className="option__name">{r.name}</span>
                    <span className="option__numbers">
                      {r.miles} mi · {r.locks} locks · {hoursText(r.hours)} · uses {Math.round(r.usage * 100)}%
                    </span>
                    <StripMap route={r} nightStops={route?.id === r.id ? nightStops : []} />
                  </Link>
                </li>
              ))}
            </ol>
          </section>

          {route && (
            <section aria-labelledby="chosen-heading" className="chosen">
              <h2 id="chosen-heading">{route.name}</h2>
              <p className="chosen__facts">
                {route.miles} miles, {route.locks} locks, about {hoursText(route.hours)} at the tiller
                {route.tunnels.length > 0 && `, through ${route.tunnels.join(' and ')}`}. Longest boat: {route.maxLength} ft.
              </p>
              <CanalMap route={route} boatLength={boat.length} />
              <Profile route={route} />
              <h3>Day by day</h3>
              <div className="table-wrap" role="region" aria-label="Day-by-day plan" tabIndex={0}>
                <table className="days">
                  <thead>
                    <tr>
                      <th scope="col">Day</th>
                      <th scope="col">From</th>
                      <th scope="col">To</th>
                      <th scope="col">Miles</th>
                      <th scope="col">Locks</th>
                      <th scope="col">Hours</th>
                      <th scope="col">Moor near</th>
                    </tr>
                  </thead>
                  <tbody>
                    {days.map((d) => (
                      <tr key={d.number} className={d.overrun ? 'days__row--long' : undefined}>
                        <th scope="row">{d.number}</th>
                        <td>{placeById[d.from].name}</td>
                        <td>{d.rest ? 'Stay put' : placeById[d.to].name}</td>
                        <td>{d.miles}</td>
                        <td>{d.locks}</td>
                        <td>
                          {d.rest ? '–' : hoursText(d.hours)}
                          {d.overrun && <span className="days__flag"> long day</span>}
                        </td>
                        <td>{d.rest ? 'A day off' : placeById[d.to].pub ?? 'Towpath mooring'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="chosen__return">Back at Marrowby Wharf by 9 am on day {nights + 1}.</p>
              <Link to={`/book?boat=${boat.id}&nights=${nights}&route=${encodeURIComponent(route.id)}`} className="button button--buoy">
                Book {boat.name} for this route
              </Link>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
