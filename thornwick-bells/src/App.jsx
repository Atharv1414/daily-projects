import { useEffect, useRef } from 'react'
import { Link, Router, useRouter } from './lib/router.jsx'
import Appeal from './pages/Appeal.jsx'
import Home from './pages/Home.jsx'
import Method from './pages/Method.jsx'
import Methods from './pages/Methods.jsx'
import NotFound from './pages/NotFound.jsx'
import Practice from './pages/Practice.jsx'
import Visit from './pages/Visit.jsx'
import { findMethod } from './ringing/methods.js'

const PAGES = {
  '/': ['Thornwick Bells', Home],
  '/methods': ['The method book', Methods],
  '/practice': ['Ring with us', Practice],
  '/appeal': ['Mend a bell', Appeal],
  '/visit': ['Book a rope', Visit],
}

export default function App() {
  return <Router><Site /></Router>
}

function Site() {
  const { path } = useRouter()
  const main = useRef(null)
  const first = useRef(true)
  const clean = path.length > 1 ? path.replace(/\/+$/, '') : path
  const methodId = clean.match(/^\/methods\/([^/]+)$/)?.[1]
  const [title, Page] = PAGES[clean] ?? ['Not found', NotFound]
  const heading = methodId ? findMethod(methodId)?.name ?? 'Not found' : title

  useEffect(() => {
    document.title = clean === '/' ? 'Thornwick Bells' : `${heading} | Thornwick Bells`
    if (first.current) first.current = false
    else main.current?.focus({ preventScroll: true })
  }, [clean, heading])

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <Link className="top__name" to="/">Thornwick Bells</Link>
        <nav aria-label="Main">
          <Link to="/methods">Methods</Link>
          <Link to="/practice">Practice</Link>
          <Link to="/appeal">Appeal</Link>
          <Link to="/visit">Visit</Link>
        </nav>
      </header>
      <main id="main" ref={main} tabIndex={-1}>{methodId ? <Method key={methodId} id={methodId} /> : <Page />}</main>
      <footer className="foot">
        <p>Thornwick, St Osyth’s and this trust are invented for a portfolio. Nothing you type is sent or stored. The ringing methods are traditional and real.</p>
      </footer>
    </>
  )
}
