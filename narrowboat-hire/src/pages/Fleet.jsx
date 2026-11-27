import Boat from '../components/Boat.jsx'
import { FLEET, boatById } from '../data/fleet.js'
import { allRoutes } from '../lib/planner.js'
import { DURATIONS, fromPrice, money } from '../lib/pricing.js'
import { Link } from '../lib/router.jsx'
import { usePageTitle } from '../lib/usePageTitle.js'
import NotFound from './NotFound.jsx'

const ROUTES = allRoutes()
const routesFor = (boat) => ROUTES.filter((r) => r.maxLength >= boat.length).length

export function Fleet() {
  usePageTitle('Boats')
  return (
    <>
      <header className="page-head">
        <p className="milepost">The fleet</p>
        <h1 tabIndex={-1}>Boats</h1>
        <p className="lede">
          Five steel narrowboats, drawn here to scale against each other. Shorter boats are easier to steer and fit
          every lock on our water. Longer ones have more room but stay on the broad canals.
        </p>
      </header>
      <ul className="fleet">
        {FLEET.map((boat) => (
          <li key={boat.id} className="fleet__row">
            <Boat boat={boat} decorative />
            <div className="fleet__text">
              <h2>
                <Link to={`/fleet/${boat.id}`}>{boat.name}</Link>
              </h2>
              <dl className="specs">
                <div><dt>Length</dt><dd>{boat.length} ft</dd></div>
                <div><dt>Sleeps</dt><dd>{boat.berths}</dd></div>
                <div><dt>Dogs</dt><dd>{boat.dogs ? 'Welcome' : 'No'}</dd></div>
                <div><dt>From</dt><dd>{money(fromPrice(boat))}</dd></div>
              </dl>
              <p>{boat.blurb}</p>
              <p className="fleet__routes">
                {routesFor(boat)} of {ROUTES.length} planned routes {boat.length > 57 ? '(not the Hollins Arm)' : '(all of them)'}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}

export function BoatPage({ id }) {
  const boat = boatById[id]
  usePageTitle(boat ? boat.name : 'Boat not found')
  if (!boat) return <NotFound what="That boat is not in our fleet." />
  return (
    <article className="boat-page">
      <header className="page-head">
        <p className="milepost">
          <Link to="/fleet">The fleet</Link> · {boat.length} ft
        </p>
        <h1 tabIndex={-1}>{boat.name}</h1>
        <p className="lede">{boat.blurb}</p>
      </header>
      <Boat boat={boat} scale="own" />
      <div className="boat-page__grid">
        <section aria-labelledby="aboard-heading">
          <h2 id="aboard-heading">On board</h2>
          <ul className="ticks">
            {boat.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
            <li>{boat.cabins} {boat.cabins === 1 ? 'cabin' : 'cabins'}, sleeping {boat.berths}</li>
            <li>{boat.dogs ? 'Dogs welcome, up to two' : 'Sorry, no dogs on this boat'}</li>
          </ul>
        </section>
        <section aria-labelledby="prices-heading">
          <h2 id="prices-heading">Prices</h2>
          <div className="table-wrap" role="region" aria-label={`${boat.name} prices`} tabIndex={0}>
            <table className="prices">
              <caption>Whole boat, including diesel for heating. Engine diesel is paid on return.</caption>
              <thead>
                <tr>
                  <th scope="col">Stay</th>
                  <th scope="col">Nov to Mar</th>
                  <th scope="col">Apr, May, Sep, Oct</th>
                  <th scope="col">Jun to Aug</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(DURATIONS).map(([nights, d]) => (
                  <tr key={nights}>
                    <th scope="row">{d.label}</th>
                    {['low', 'shoulder', 'peak'].map((season) => (
                      <td key={season}>{money(Math.round((boat.weekly[season] * d.factor) / 5) * 5)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <div className="boat-page__actions">
        <Link to={`/book?boat=${boat.id}`} className="button button--buoy">Book {boat.name}</Link>
        <Link to={`/routes?boat=${boat.id}`} className="button button--quiet">Routes for {boat.name}</Link>
      </div>
    </article>
  )
}
