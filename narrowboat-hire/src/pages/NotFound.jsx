import { Link } from '../lib/router.jsx'
import { usePageTitle } from '../lib/usePageTitle.js'

export default function NotFound({ what = 'There is no page at this address.' }) {
  usePageTitle('Not found')
  return (
    <section className="page-head page-head--lost">
      <p className="milepost">Winding hole</p>
      <h1 tabIndex={-1}>You&apos;ve run out of canal</h1>
      <p className="lede">{what} Turn the boat round and head back to the wharf.</p>
      <Link to="/" className="button">Back to Marrowby Wharf</Link>
    </section>
  )
}
