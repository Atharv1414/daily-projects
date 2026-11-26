/**
 * A small history-API router. Pages read their state from the address (path and query), so
 * every filtered table and every ghost race can be shared as a link.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'

const EVENT = 'hollinbeck:navigate'

function subscribe(callback) {
  window.addEventListener('popstate', callback)
  window.addEventListener(EVENT, callback)
  return () => {
    window.removeEventListener('popstate', callback)
    window.removeEventListener(EVENT, callback)
  }
}

const snapshot = () => window.location.pathname + window.location.search

export function navigate(to, { replace = false } = {}) {
  if (to === snapshot()) return
  window.history[replace ? 'replaceState' : 'pushState'](null, '', to)
  window.dispatchEvent(new Event(EVENT))
}

/** Matches "/races/:slug" style patterns. Returns params or null. */
export function matchPath(pattern, pathname) {
  const want = pattern.split('/').filter(Boolean)
  const got = pathname.split('/').filter(Boolean)
  if (want.length !== got.length) return null
  const params = {}
  for (let i = 0; i < want.length; i += 1) {
    if (want[i].startsWith(':')) params[want[i].slice(1)] = decodeURIComponent(got[i])
    else if (want[i] !== got[i]) return null
  }
  return params
}

export function useLocation() {
  const href = useSyncExternalStore(subscribe, snapshot, snapshot)
  const url = new URL(href, 'http://local')
  return { pathname: url.pathname, search: url.searchParams }
}

/** Query-string state: [value, set]. Setting replaces history so filters do not pile up. */
export function useQueryParam(name, fallback = '') {
  const { search } = useLocation()
  const value = search.get(name) ?? fallback
  const set = useCallback(
    (next, extra = {}) => {
      const params = new URLSearchParams(window.location.search)
      for (const [k, v] of Object.entries({ [name]: next, ...extra })) {
        if (v === '' || v === null || v === undefined) params.delete(k)
        else params.set(k, v)
      }
      const qs = params.toString().replace(/%2C/g, ',')
      navigate(window.location.pathname + (qs ? `?${qs}` : ''), { replace: true })
    },
    [name],
  )
  return [value, set]
}

export function Link({ to, children, ...rest }) {
  const onClick = (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
  }
  return (
    <a href={to} onClick={onClick} {...rest}>
      {children}
    </a>
  )
}

/** Moves focus to the main heading after a page change, so screen readers announce it. */
export function useFocusOnNavigate(ref, key) {
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false // leave focus alone on the first load
      return
    }
    ref.current?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }, [ref, key])
}
