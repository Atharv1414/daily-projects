import { Link } from '../lib/router.jsx'

export default function NotFound({ what = 'There is nothing at this address.' }) {
  return (
    <div className="page">
      <h1>Off the line</h1>
      <p className="lead">{what} It happens to every ringer: listen for the treble and find your way back.</p>
      <p><Link className="go" to="/">Back to rounds</Link></p>
    </div>
  )
}
