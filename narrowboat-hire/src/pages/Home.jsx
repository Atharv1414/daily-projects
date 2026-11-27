import { useState } from 'react'
import Boat from '../components/Boat.jsx'
import StripMap from '../components/StripMap.jsx'
import { FLEET, boatById } from '../data/fleet.js'
import { cruisingHours, routeById } from '../lib/planner.js'
import { Link } from '../lib/router.jsx'
import { fromPrice, money } from '../lib/pricing.js'
import { usePageTitle } from '../lib/usePageTitle.js'

const FEATURED = [
  { id: 'out:larkspur', nights: 7, pace: 'gentle', note: 'Up the Ashlock Flight, through Fenny Tunnel and along the Long Pound to the Heron & Pike.' },
  { id: 'ring:r1-r12-r13-r14-r15', nights: 3, pace: 'gentle', note: 'A weekend loop on narrow locks, over the Wren Aqueduct and home by Sunday lunch.' },
  { id: 'ring:r11-r2-r3-r5-r7-r8-r9', nights: 7, pace: 'steady', note: 'The big one: up 96 ft, through the tunnel, and back down the river to Tenbridge.' },
]

function Milepost({ children }) {
  return <p className="milepost">{children}</p>
}

function LockMiles() {
  const [miles, setMiles] = useState(12)
  const [locks, setLocks] = useState(9)
  const hours = cruisingHours(Number(miles) || 0, Number(locks) || 0)
  const whole = Math.floor(hours)
  const minutes = Math.round((hours - whole) * 60)
  return (
    <form className="lockmiles" onSubmit={(e) => e.preventDefault()} aria-labelledby="lockmiles-heading">
      <h3 id="lockmiles-heading">Lock-miles calculator</h3>
      <div className="lockmiles__inputs">
        <label>
          Miles
          <input type="number" min="0" max="200" value={miles} onChange={(e) => setMiles(e.target.value)} />
        </label>
        <span aria-hidden="true">+</span>
        <label>
          Locks
          <input type="number" min="0" max="200" value={locks} onChange={(e) => setLocks(e.target.value)} />
        </label>
        <span aria-hidden="true">÷ 3 =</span>
        <output aria-live="polite" className="lockmiles__out">
          {whole} h {minutes.toString().padStart(2, '0')} min
        </output>
      </div>
    </form>
  )
}

export default function Home() {
  usePageTitle(null)
  const kestrel = boatById.kestrel
  return (
    <>
      <section className="hero">
        <div className="hero__text">
          <Milepost>Mile 0 · Marrowby Wharf</Milepost>
          <h1 tabIndex={-1}>Three miles an hour, and every lock by hand.</h1>
          <p className="lede">
            Hire a narrowboat for a weekend or a fortnight. We&apos;ll show you how to steer, how to work a lock and where the
            good moorings are. Then the canal is yours.
          </p>
          <div className="hero__actions">
            <Link to="/routes" className="button button--buoy">Plan a route</Link>
            <Link to="/fleet" className="button button--quiet">Meet the boats</Link>
          </div>
        </div>
        <div className="hero__art">
          <Boat boat={kestrel} scale="own" />
          <p className="hero__caption">
            <strong>Kestrel</strong>, 57 ft. The longest boat that fits every lock on our water.
          </p>
        </div>
      </section>

      <section className="band" aria-labelledby="routes-heading">
        <Milepost>Mile 4 · Saltmoor Junction</Milepost>
        <h2 id="routes-heading">Three ways out of the wharf</h2>
        <ol className="featured">
          {FEATURED.map((f) => {
            const route = routeById(f.id)
            return (
              <li key={f.id} className="featured__item">
                <div className="featured__head">
                  <h3>
                    <Link to={`/routes?nights=${f.nights}&pace=${f.pace}&route=${encodeURIComponent(f.id)}`}>{route.name}</Link>
                  </h3>
                  <p className="featured__numbers">
                    {route.miles} miles · {route.locks} locks · {f.nights} nights
                  </p>
                </div>
                <StripMap route={route} />
                <p>{f.note}</p>
              </li>
            )
          })}
        </ol>
      </section>

      <section className="split" aria-labelledby="time-heading">
        <div>
          <Milepost>Mile 11 · Ashlock Bottom Lock</Milepost>
          <h2 id="time-heading">How far can you get?</h2>
          <p>
            Boaters plan in <em>lock-miles</em>. A lock takes about as long as a mile of open water, and a boat moves at
            about three miles an hour. Add the miles to the locks and divide by three. That gives you the hours, and
            it&apos;s surprisingly close.
          </p>
          <p>
            Our planner uses the same rule. It also knows which locks are too short for the longer boats, and it plans
            each night at a proper mooring.
          </p>
        </div>
        <LockMiles />
      </section>

      <section className="band" aria-labelledby="fleet-heading">
        <Milepost>Mile 12.5 · Ashlock Top</Milepost>
        <h2 id="fleet-heading">Five boats, 45 to 69 feet</h2>
        <ul className="fleet-strip">
          {FLEET.map((boat) => (
            <li key={boat.id}>
              <Link to={`/fleet/${boat.id}`} className="fleet-strip__link">
                <Boat boat={boat} decorative />
                <span className="fleet-strip__name">{boat.name}</span>
                <span className="fleet-strip__meta">
                  {boat.length} ft · sleeps {boat.berths} · from {money(fromPrice(boat))}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}
