import { useEffect, useRef } from 'react'
import { Link, useRouter } from '../lib/router.jsx'

const NAV = [
  ['/routes', 'Plan a route'],
  ['/fleet', 'Boats'],
  ['/first-time', 'First time?'],
  ['/book', 'Book'],
]

function Mark() {
  // A pair of mitred lock gates seen from above, closed against the water.
  return (
    <svg viewBox="0 0 40 40" className="brand__mark" aria-hidden="true">
      <rect x="2" y="2" width="36" height="36" rx="4" className="brand__plate" />
      <path d="M8,10 L20,22 L32,10" className="brand__gates" />
      <path d="M8,30 L32,30" className="brand__sill" />
    </svg>
  )
}

export default function Layout({ children }) {
  const { path } = useRouter()
  const main = useRef(null)
  const first = useRef(true)

  useEffect(() => {
    // Move focus to the new page's heading after client-side navigation, as a full page load would.
    if (first.current) {
      first.current = false
      return
    }
    main.current?.querySelector('h1')?.focus()
  }, [path])

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="masthead">
        <Link to="/" className="brand" aria-current={path === '/' ? 'page' : undefined}>
          <Mark />
          <span className="brand__name">Kestrel &amp; Lock</span>
          <span className="brand__where">Marrowby Wharf</span>
        </Link>
        <nav aria-label="Main">
          <ul className="nav">
            {NAV.map(([to, label]) => (
              <li key={to}>
                <Link to={to} className={to === '/book' ? 'nav__book' : undefined}>
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="main" ref={main}>
        {children}
      </main>
      <footer className="foot">
        <div>
          <p className="foot__name">Kestrel &amp; Lock</p>
          <p>Narrowboat hire from Marrowby Wharf, Mondays and Fridays, March to October and through the winter.</p>
        </div>
        <p className="foot__note">
          Kestrel &amp; Lock, Marrowby Wharf and every canal, pub and boat on this site are invented. This is a portfolio
          project: nothing you type is sent anywhere, and no booking is real.
        </p>
      </footer>
    </>
  )
}
