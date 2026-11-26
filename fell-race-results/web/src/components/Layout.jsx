import { Link, useLocation } from '../router.jsx'

const NAV = [
  ['/races', 'Races'],
  ['/championship', 'Championship'],
  ['/runners', 'Runners'],
  ['/ghost', 'Ghost race'],
  ['/submit', 'Organisers'],
]

export function Crest() {
  return (
    <svg className="crest" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path className="crest__sky" d="M4 40V12a20 20 0 0 1 40 0v28Z" />
      <path className="crest__fell" d="M4 40 15 22l6 7 8-15 15 26Z" />
      <path className="crest__contour" d="M9 34c6-3 10-3 15 0s9 3 15 0M12 29c4-2 7-2 11 0" />
      <path className="crest__beck" d="M27 40c-2-3 3-5 0-8" />
    </svg>
  )
}

export function Header() {
  const { pathname } = useLocation()
  return (
    <header className="masthead">
      <div className="masthead__inner">
        <Link to="/" className="brand">
          <Crest />
          <span className="brand__name">
            Hollinbeck <span>Harriers</span>
          </span>
        </Link>
        <nav aria-label="Main">
          <ul className="nav">
            {NAV.map(([to, label]) => (
              <li key={to}>
                <Link to={to} aria-current={pathname === to || pathname.startsWith(`${to}/`) ? 'page' : undefined}>
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  )
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner">
        <p>
          <strong>Hollinbeck Harriers is not a real club.</strong> The races, fells, runners and
          results on this site are invented, and nothing you type here is sent anywhere except to
          this site&rsquo;s own local results service.
        </p>
        <p>Scores: 100 × winner&rsquo;s time ÷ your time, best five of eight races count.</p>
      </div>
    </footer>
  )
}

export function Loading({ label = 'Loading results' }) {
  return (
    <p className="status status--loading" role="status">
      <span className="status__dot" aria-hidden="true" /> {label}…
    </p>
  )
}

export function ErrorState({ error, retry }) {
  return (
    <div className="status status--error" role="alert">
      <p>
        <strong>That did not load.</strong> {error?.message}
      </p>
      {retry && (
        <button type="button" className="button button--quiet" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ children }) {
  return <p className="status status--empty">{children}</p>
}
