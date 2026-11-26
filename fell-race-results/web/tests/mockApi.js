import { vi } from 'vitest'
import contract from '../../contract/examples.json'

export { contract }

/**
 * Replaces fetch with the API's recorded responses from contract/examples.json. Requests
 * the contract does not cover get the API's own 404 shape, which exercises error states.
 */
export function mockApi({ uploadReply } = {}) {
  const calls = []
  const fetchMock = vi.fn(async (input, init = {}) => {
    const url = decodeURIComponent(String(input))
    calls.push({ url, init })
    if ((init.method ?? 'GET') === 'POST') {
      if (init.headers?.authorization !== 'Bearer good-token') {
        return json(401, { error: { code: 'unauthorised', message: 'organiser token not recognised' } })
      }
      return json(200, uploadReply ?? contract.upload.response)
    }
    const body = contract.examples[url]
    if (body === undefined) return json(404, { error: { code: 'not_found', message: `nothing at ${url}` } })
    return json(200, body)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

export function goTo(path) {
  window.history.replaceState(null, '', path)
}
