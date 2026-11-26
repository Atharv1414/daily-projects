import { useMemo, useState } from 'react'
import { ApiError, paths, request, useApi } from '../api.js'
import { ErrorState } from '../components/Layout.jsx'
import { parseResults, suggestUploadId } from '../lib/csv.js'
import { formatTime } from '../lib/format.js'
import { SEASON } from './Home.jsx'

const EXAMPLE = `# runner, then a time at each checkpoint (mm:ss or h:mm:ss)
R0012, 13:32, 24:26
R0031, 17:15, DNF`

export default function Submit({ headingRef }) {
  const races = useApi(paths.races(SEASON))
  const [slug, setSlug] = useState('raven-crag-race')
  const race = useApi(paths.race(slug))
  const [token, setToken] = useState('')
  const [text, setText] = useState('')
  const [uploadId, setUploadId] = useState(() => suggestUploadId('raven-crag-race', SEASON))
  const [state, setState] = useState({ status: 'idle' })
  const [touched, setTouched] = useState(false)

  const expected = race.data?.checkpoints.length ?? 0
  const parsed = useMemo(() => parseResults(text, expected), [text, expected])
  const tokenMissing = touched && !token.trim()
  const nothing = touched && parsed.rows.length === 0 && parsed.problems.length === 0

  const submit = async (event) => {
    event.preventDefault()
    setTouched(true)
    if (!token.trim() || parsed.rows.length === 0 || parsed.problems.length > 0) return
    setState({ status: 'sending' })
    try {
      const summary = await request(paths.upload(slug), {
        method: 'POST',
        token: token.trim(),
        body: { upload_id: uploadId, season: SEASON, results: parsed.rows },
      })
      setState({ status: 'done', summary })
    } catch (error) {
      setState({ status: 'failed', error: error instanceof ApiError ? error : new ApiError(0, String(error)) })
    }
  }

  const changeRace = (value) => {
    setSlug(value)
    setUploadId(suggestUploadId(value, SEASON))
    setState({ status: 'idle' })
  }

  return (
    <section className="page page--narrow">
      <h1 ref={headingRef} tabIndex={-1}>Send in results</h1>
      <p className="lede">
        For race organisers. Paste one runner per line with their time at each checkpoint. Sending
        the same upload twice is safe: the service recognises the upload reference and changes nothing.
      </p>
      <form className="form" onSubmit={submit} noValidate>
        <label className="field">
          <span>Race</span>
          <select value={slug} onChange={(e) => changeRace(e.target.value)}>
            {(races.data ?? []).map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}
            {!races.data && <option value="raven-crag-race">Raven Crag Race</option>}
          </select>
        </label>
        {race.data && (
          <p className="hint">
            Checkpoints in order: {race.data.checkpoints.map((c) => c.name).join(', ')}. A finisher needs {expected} times.
          </p>
        )}
        <label className="field">
          <span>Results</span>
          <textarea
            rows={8}
            value={text}
            placeholder={EXAMPLE}
            spellCheck={false}
            onChange={(e) => { setText(e.target.value); setState({ status: 'idle' }) }}
            aria-invalid={parsed.problems.length > 0 || nothing}
            aria-describedby="results-problems"
          />
        </label>
        <div id="results-problems" aria-live="polite">
          {parsed.problems.length > 0 && (
            <ul className="problems">
              {parsed.problems.map((p) => <li key={p.line}>Line {p.line}: {p.message}</li>)}
            </ul>
          )}
          {nothing && <p className="field__error">Paste at least one result.</p>}
          {parsed.rows.length > 0 && parsed.problems.length === 0 && (
            <p className="hint">
              Ready to send {parsed.rows.length} {parsed.rows.length === 1 ? 'result' : 'results'}:{' '}
              {parsed.rows.map((r) => `${r.runner_id} ${r.status === 'dnf' ? 'DNF' : formatTime(r.splits[r.splits.length - 1])}`).join(', ')}.
            </p>
          )}
        </div>
        <label className="field">
          <span>Upload reference</span>
          <input value={uploadId} onChange={(e) => setUploadId(e.target.value)} pattern="[A-Za-z0-9_-]{8,64}" />
        </label>
        <label className="field">
          <span>Organiser token</span>
          <input
            type="password"
            value={token}
            autoComplete="off"
            onChange={(e) => setToken(e.target.value)}
            aria-invalid={tokenMissing}
            aria-describedby={tokenMissing ? 'token-error' : 'token-hint'}
          />
        </label>
        {tokenMissing ? (
          <p id="token-error" className="field__error">The organiser token is required.</p>
        ) : (
          <p id="token-hint" className="hint">The local demo service prints its demo token in the README.</p>
        )}
        <button type="submit" className="button" disabled={state.status === 'sending'}>
          {state.status === 'sending' ? 'Sending…' : 'Send results'}
        </button>
      </form>

      {state.status === 'failed' && (
        <ErrorState error={{ message: state.error.status === 401 ? 'That organiser token was not accepted.' : state.error.message }} />
      )}
      {state.status === 'done' && (
        <section className="receipt" aria-labelledby="receipt" role="status">
          <h2 id="receipt">{state.summary.replayed ? 'Already received' : 'Results received'}</h2>
          <p>
            {state.summary.inserted} added, {state.summary.updated} corrected, {state.summary.unchanged} unchanged
            {state.summary.rejected.length ? `, ${state.summary.rejected.length} not accepted` : ''}.
          </p>
          {state.summary.rejected.length > 0 && (
            <ul className="problems">
              {state.summary.rejected.map((r) => <li key={r.row}>Line {r.row} ({r.runner_id}): {r.reason}</li>)}
            </ul>
          )}
        </section>
      )}
    </section>
  )
}
