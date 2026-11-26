import { useState } from 'react'
import { paths, useApi } from '../api.js'
import { Empty, ErrorState, Loading } from '../components/Layout.jsx'
import { formatTime, ordinal } from '../lib/format.js'
import { Link, useQueryParam } from '../router.jsx'

export function RunnerSearch({ headingRef }) {
  const [q, setQ] = useQueryParam('q')
  const [draft, setDraft] = useState(q)
  const ready = q.trim().length >= 2
  const { data, error, retry, loading } = useApi(ready ? paths.searchRunners(q.trim().toLowerCase()) : null)

  const submit = (event) => {
    event.preventDefault()
    setQ(draft.trim())
  }

  return (
    <section className="page">
      <h1 ref={headingRef} tabIndex={-1}>Runners</h1>
      <form className="search" role="search" onSubmit={submit}>
        <label className="field">
          <span>First name or surname</span>
          <input
            type="search"
            name="q"
            value={draft}
            minLength={2}
            maxLength={40}
            autoComplete="off"
            onChange={(e) => setDraft(e.target.value)}
            aria-describedby="search-hint"
          />
        </label>
        <button type="submit" className="button">Search</button>
        <p id="search-hint" className="hint">At least two letters, for example &ldquo;ruth&rdquo; or &ldquo;postle&rdquo;.</p>
      </form>
      {q && !ready && <p className="field__error" role="alert">Type at least two letters.</p>}
      {error && <ErrorState error={error} retry={retry} />}
      {loading && <Loading label="Searching" />}
      {data && data.length === 0 && <Empty>No runner matches &ldquo;{q}&rdquo;.</Empty>}
      {data && data.length > 0 && (
        <ul className="runner-list">
          {data.map((r) => (
            <li key={r.id}>
              <Link to={`/runners/${r.id}`}>{r.name}</Link>
              <span>{r.club}</span>
              <span className="num">{r.id}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Where in the field a runner finished: 0 is the winner, 1 is last. */
export function fieldPercentile(position, finishers) {
  if (!position || !finishers) return null
  return finishers === 1 ? 0 : (position - 1) / (finishers - 1)
}

export function RunnerPage({ id, headingRef }) {
  const { data, error, retry } = useApi(paths.runner(id))
  if (error) {
    return (
      <section className="page">
        <h1 ref={headingRef} tabIndex={-1}>Runner not found</h1>
        <ErrorState error={error} retry={error.status === 404 ? undefined : retry} />
        <Link to="/runners">Search for a runner</Link>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="page">
        <h1 ref={headingRef} tabIndex={-1}>Runner</h1>
        <Loading />
      </section>
    )
  }
  const { runner, results, personal_bests: pbs } = data
  const finished = results.filter((r) => r.status === 'finished')
  const wins = finished.filter((r) => r.position === 1).length
  return (
    <section className="page">
      <p className="eyebrow"><Link to="/runners">Runners</Link> / {runner.id}</p>
      <h1 ref={headingRef} tabIndex={-1}>{runner.name}</h1>
      <p className="lede">
        {runner.club}, born {runner.birth_year}. {finished.length} finishes
        {wins ? `, ${wins} ${wins === 1 ? 'win' : 'wins'}` : ''} across {new Set(results.map((r) => r.season)).size} seasons.
      </p>

      <h2>Where in the field</h2>
      <figure className="strip">
        <svg viewBox="0 0 600 70" role="img" aria-labelledby="strip-title">
          <title id="strip-title">Finishing position as a share of the field for each race; left is the front.</title>
          <line x1="20" x2="580" y1="35" y2="35" className="strip__axis" />
          <text x="20" y="64" className="strip__label">winner</text>
          <text x="580" y="64" textAnchor="end" className="strip__label">last</text>
          {finished.map((r) => {
            const p = fieldPercentile(r.position, r.finishers)
            return <circle key={`${r.race}-${r.season}`} cx={20 + p * 560} cy={35} r="7" className={`strip__dot strip__dot--${r.season}`} />
          })}
        </svg>
        <figcaption>
          <span className="key key--2024">2024</span> <span className="key key--2025">2025</span> <span className="key key--2026">2026</span>
        </figcaption>
      </figure>

      <h2>Results</h2>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Race history">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Season</th>
              <th scope="col">Race</th>
              <th scope="col">Cat</th>
              <th scope="col" className="num">Position</th>
              <th scope="col" className="num">Time</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={`${r.race}-${r.season}`} className={r.status === 'dnf' ? 'is-dnf' : undefined}>
                <td className="num">{r.season}</td>
                <th scope="row"><Link to={`/races/${r.race}`}>{r.race_name}</Link></th>
                <td>{r.category}</td>
                <td className="num">{r.position ? `${ordinal(r.position)} of ${r.finishers}` : 'DNF'}</td>
                <td className="num time">
                  {formatTime(r.time_s)}
                  {r.time_s && pbs[r.race] === r.time_s && <span className="pb" title="Personal best"> PB</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
