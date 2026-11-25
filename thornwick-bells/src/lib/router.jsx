import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const RouterContext = createContext(null)
const read = () => ({ path: window.location.pathname, query: window.location.search })

export function Router({ children }) {
  const [place, setPlace] = useState(read)
  useEffect(() => {
    const back = () => setPlace(read())
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
  const go = useCallback((to, { replace = false } = {}) => {
    window.history[replace ? 'replaceState' : 'pushState'](null, '', to)
    setPlace(read())
    if (!replace) window.scrollTo(0, 0)
  }, [])
  const value = useMemo(() => ({ ...place, go }), [place, go])
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export const useRouter = () => useContext(RouterContext)

/** Reads and writes the query string, so a view can be shared by copying its address. */
export function useQuery() {
  const { path, query, go } = useRouter()
  const params = useMemo(() => new URLSearchParams(query), [query])
  const set = useCallback((changes) => {
    const next = new URLSearchParams(window.location.search)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    const text = next.toString()
    go(text ? `${path}?${text}` : path, { replace: true })
  }, [go, path])
  return [params, set]
}

export function Link({ to, children, ...rest }) {
  const { go, path } = useRouter()
  const onClick = (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    go(to)
  }
  const here = to === '/' ? path === '/' : path.startsWith(to)
  return <a href={to} onClick={onClick} aria-current={here ? 'page' : undefined} {...rest}>{children}</a>
}
