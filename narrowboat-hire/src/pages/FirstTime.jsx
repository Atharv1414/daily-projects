import LockDiagram from '../components/LockDiagram.jsx'
import { Link } from '../lib/router.jsx'
import { usePageTitle } from '../lib/usePageTitle.js'

const QUESTIONS = [
  ['Do I need a licence or any experience?', 'No. Most of our crews have never steered a boat. At handover an instructor takes you out, up the first lock and back, and stays until you are happy. It takes about an hour.'],
  ['How fast do boats go?', 'The limit is 4 mph, and slower past moored boats: if you are making a wash, you are going too fast. In practice, with locks, three miles an hour is a good day.'],
  ['Where do we stop for the night?', 'Almost anywhere on the towpath side, for up to 14 days, unless signs say otherwise. Not on lock landings, water points, bends or bridge holes. The planner chooses places with moorings and usually a pub.'],
  ['What about the tunnel?', 'Fenny Tunnel is 1,320 yards long with no towpath. Headlight on, horn at the portal, keep right, and go slowly. It takes about a quarter of an hour, and children love it.'],
  ['Water, toilets and rubbish?', 'Each boat carries water for two or three days. There are water points at most wharves and junctions, and the wharf staff will mark the ones on your route before you leave. Pump-outs are included in the price.'],
  ['What happens if it rains a lot?', 'The Tenbridge Navigation runs along the river for two reaches. Level boards at each end show green, amber or red. On red, wait where you are and ring the wharf: we will help you change plans.'],
]

export default function FirstTime() {
  usePageTitle('First time at the tiller')
  return (
    <>
      <header className="page-head">
        <p className="milepost">For new crews</p>
        <h1 tabIndex={-1}>First time at the tiller</h1>
        <p className="lede">
          Nobody is born knowing how to work a lock. Step through one below and you&apos;ll know more than most people do
          when they arrive at the wharf.
        </p>
      </header>
      <LockDiagram />
      <section className="faq" aria-labelledby="faq-heading">
        <h2 id="faq-heading">Questions people ask at the wharf</h2>
        {QUESTIONS.map(([q, a]) => (
          <details key={q}>
            <summary>{q}</summary>
            <p>{a}</p>
          </details>
        ))}
      </section>
      <p className="cta-line">
        Ready? <Link to="/routes">Plan a route</Link> or <Link to="/book">book a boat</Link>.
      </p>
    </>
  )
}
