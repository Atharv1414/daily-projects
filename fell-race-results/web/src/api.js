/**
 * The only module that knows about HTTP. Every URL the site requests is built here, in the
 * same parameter order as contract/examples.json, which the tests replay.
 */
import { useCallback, useEffect, useState } from 'react'

const BASE = '/api'

export class ApiError extends Error {
  constructor(status, message, details = []) {
    super(message)
    this.status = status
    this.details = details
  }
}

function query(params) {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v).replace(/%2C/g, ',')}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export const paths = {
  health: () => '/health',
  races: (season) => `/races${query({ season })}`,
  race: (slug) => `/races/${slug}`,
  results: ({ slug, season, sex, page = 1, pageSize = 50 }) =>
    `/races/${slug}/results${query({ season, sex, page, page_size: pageSize })}`,
  standings: ({ season, sex, category }) => `/standings${query({ season, sex, category })}`,
  records: () => '/records',
  searchRunners: (q) => `/runners${query({ q })}`,
  runner: (id) => `/runners/${id}`,
  ghost: ({ race, season, runners }) => `/ghost${query({ race, season, runners: runners.join(',') })}`,
  upload: (slug) => `/races/${slug}/results`,
}

export async function request(path, { method = 'GET', body, token, signal } = {}) {
  const headers = { accept: 'application/json' }
  if (body !== undefined) headers['content-type'] = 'application/json'
  if (token) headers.authorization = `Bearer ${token}`
  let response
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(0, 'The results service is not reachable. Is the API running?')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data?.error?.message ?? `The results service answered ${response.status}`,
      data?.error?.details ?? [],
    )
  }
  return data
}

/** Loads `path` (null means "nothing to load yet"), cancelling stale requests. */
export function useApi(path) {
  const [state, setState] = useState({ path: null, data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!path) return undefined
    const controller = new AbortController()
    request(path, { signal: controller.signal })
      .then((data) => setState({ path, data, error: null }))
      .catch((error) => {
        if (error.name !== 'AbortError') setState({ path, data: null, error })
      })
    return () => controller.abort()
  }, [path, attempt])

  const retry = useCallback(() => {
    setState((s) => ({ ...s, path: null }))
    setAttempt((n) => n + 1)
  }, [])

  const current = state.path === path
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: Boolean(path) && !current,
    retry,
  }
}
