import { useRef } from 'react'
import { Footer, Header } from './components/Layout.jsx'
import Championship from './pages/Championship.jsx'
import Ghost from './pages/Ghost.jsx'
import Home from './pages/Home.jsx'
import { RaceList, RacePage } from './pages/Races.jsx'
import { RunnerPage, RunnerSearch } from './pages/Runners.jsx'
import Submit from './pages/Submit.jsx'
import { Link, matchPath, useFocusOnNavigate, useLocation } from './router.jsx'

function NotFound({ headingRef }) {
  return (
    <section className="page">
      <h1 ref={headingRef} tabIndex={-1}>Off the route</h1>
      <p className="lede">There is no page here. The path you followed may have been a sheep trod.</p>
      <Link to="/">Back to the start</Link>
    </section>
  )
}

export function route(pathname) {
  if (pathname === '/') return [Home, {}]
  if (pathname === '/races') return [RaceList, {}]
  if (pathname === '/championship') return [Championship, {}]
  if (pathname === '/runners') return [RunnerSearch, {}]
  if (pathname === '/ghost') return [Ghost, {}]
  if (pathname === '/submit') return [Submit, {}]
  const race = matchPath('/races/:slug', pathname)
  if (race) return [RacePage, { slug: race.slug }]
  const runner = matchPath('/runners/:id', pathname)
  if (runner) return [RunnerPage, { id: runner.id }]
  return [NotFound, {}]
}

export default function App() {
  const { pathname } = useLocation()
  const headingRef = useRef(null)
  useFocusOnNavigate(headingRef, pathname)
  const [Page, params] = route(pathname)
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <Header />
      <main id="main">
        <Page key={pathname} headingRef={headingRef} {...params} />
      </main>
      <Footer />
    </>
  )
}
