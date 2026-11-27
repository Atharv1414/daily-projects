import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

// A small History API router. Search parameters are first-class, because the planner and the
// booking keep their state in the address so it can be shared or bookmarked.

const RouterContext = createContext(null)

const readLocation = () => ({ path: window.location.pathname, search: window.location.search })

export function Router({ children }) {
  const [location, setLocation] = useState(readLocation)

  useEffect(() => {
    const onPop = () => setLocation(readLocation())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to, { replace = false, keepScroll = false } = {}) => {
    const url = new URL(to, window.location.origin)
    const next = url.pathname + url.search
    if (next === window.location.pathname + window.location.search) return
    window.history[replace ? 'replaceState' : 'pushState'](null, '', next)
    setLocation(readLocation())
    if (!keepScroll && !replace) window.scrollTo({ top: 0 })
  }, [])

  const value = useMemo(() => ({ ...location, params: new URLSearchParams(location.search), navigate }), [location, navigate])
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function useRouter() {
  const value = useContext(RouterContext)
  if (!value) throw new Error('useRouter must be used inside <Router>')
  return value
}

/** Reads and writes a set of search parameters, replacing history so the back button skips small edits. */
export function useSearchState(defaults) {
  const { path, params, navigate } = useRouter()
  const state = Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, params.get(k) ?? v]))
  const update = useCallback(
    (changes) => {
      const next = new URLSearchParams(window.location.search)
      for (const [k, v] of Object.entries(changes)) {
        if (v === null || v === undefined || v === '' || v === defaults[k]) next.delete(k)
        else next.set(k, String(v))
      }
      const query = next.toString()
      navigate(`${path}${query ? `?${query}` : ''}`, { replace: true })
    },
    // defaults is a literal at each call site; its keys never change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [navigate, path],
  )
  return [state, update]
}

export function Link({ to, children, onClick, ...rest }) {
  const { navigate, path } = useRouter()
  const handle = (event) => {
    onClick?.(event)
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
  }
  const current = new URL(to, 'http://x').pathname === path ? 'page' : undefined
  return (
    <a href={to} onClick={handle} aria-current={rest['aria-current'] ?? current} {...rest}>
      {children}
    </a>
  )
}
