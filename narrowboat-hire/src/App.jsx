import Layout from './components/Layout.jsx'
import Book from './pages/Book.jsx'
import FirstTime from './pages/FirstTime.jsx'
import { BoatPage, Fleet } from './pages/Fleet.jsx'
import Home from './pages/Home.jsx'
import NotFound from './pages/NotFound.jsx'
import Routes from './pages/Routes.jsx'
import { Router, useRouter } from './lib/router.jsx'

function Page() {
  const { path } = useRouter()
  const clean = path.replace(/\/+$/, '') || '/'
  if (clean === '/') return <Home />
  if (clean === '/routes') return <Routes />
  if (clean === '/fleet') return <Fleet />
  const boat = clean.match(/^\/fleet\/([a-z-]+)$/)
  if (boat) return <BoatPage id={boat[1]} />
  if (clean === '/book') return <Book />
  if (clean === '/first-time') return <FirstTime />
  return <NotFound />
}

export default function App() {
  return (
    <Router>
      <Layout>
        <Page />
      </Layout>
    </Router>
  )
}
