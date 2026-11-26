import { useState } from 'react'
import { paths, useApi } from '../api.js'
import ElevationProfile, { Sparkline } from '../components/ElevationProfile.jsx'
import { Empty, ErrorState, Loading } from '../components/Layout.jsx'
import { describeCategory, formatDate, formatTime } from '../lib/format.js'
import { Link, navigate, useQueryParam } from '../router.jsx'
import { SEASON } from './Home.jsx'

export function RaceList({ headingRef }) {
  const { data, error, retry } = useApi(paths.races(SEASON))
  return (
    <section className="page">
      <h1 ref={headingRef} tabIndex={-1}>Races</h1>
      <p className="lede">Eight championship races from March to October. Click a race for its course, results and records.</p>
      {error && <ErrorState error={error} retry={retry} />}
      {!data && !error && <Loading />}
      {data && (
        <table className="table table--races">
          <caption className="visually-hidden">{SEASON} championship races</caption>
          <thead>
            <tr>
              <th scope="col">Race</th>
              <th scope="col">Date</th>
              <th scope="col">Course</th>
              <th scope="col" className="hide-sm">Profile</th>
              <th scope="col" className="num">Women&rsquo;s winner</th>
              <th scope="col" className="num">Men&rsquo;s winner</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.slug}>
                <th scope="row">
                  <Link to={`/races/${r.slug}`}>{r.name}</Link>
                </th>
                <td>{formatDate(r.date)}</td>
                <td>
                  <abbr title={describeCategory(r.fra_category)}>{r.fra_category}</abbr> {r.distance_km} km, {r.climb_m} m
                </td>
                <td className="hide-sm"><Sparkline profile={r.profile} /></td>
                <td className="num">{r.winner_f} <span className="time">{formatTime(r.winning_time_f)}</span></td>
                <td className="num">{r.winner_m} <span className="time">{formatTime(r.winning_time_m)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

const PAGE_SIZE = 50

export function RacePage({ slug, headingRef }) {
  const [sex, setSex] = useQueryParam('sex')
  const [pageText, setPage] = useQueryParam('page', '1')
  const page = Math.max(1, Number.parseInt(pageText, 10) || 1)
  const [picked, setPicked] = useState([])
  const race = useApi(paths.race(slug))
  const results = useApi(paths.results({ slug, season: SEASON, sex: sex || undefined, page, pageSize: PAGE_SIZE }))
  const records = useApi(paths.records())

  if (race.error) {
    return (
      <section className="page">
        <h1 ref={headingRef} tabIndex={-1}>Race not found</h1>
        <ErrorState error={race.error} />
        <Link to="/races">Back to all races</Link>
      </section>
    )
  }
  const r = race.data
  const pages = results.data ? Math.max(1, Math.ceil(results.data.total / PAGE_SIZE)) : 1
  const toggle = (id) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]))
  const raceRecords = records.data?.filter((x) => x.race === slug) ?? []

  return (
    <section className="page">
      <p className="eyebrow"><Link to="/races">Races</Link> / {SEASON}</p>
      <h1 ref={headingRef} tabIndex={-1}>{r?.name ?? 'Loading race'}</h1>
      {r && (
        <>
          <p className="lede">{r.blurb}</p>
          <dl className="facts">
            <div><dt>Distance</dt><dd className="num">{r.distance_km} km</dd></div>
            <div><dt>Climb</dt><dd className="num">{r.climb_m} m</dd></div>
            <div><dt>Category</dt><dd><abbr title={describeCategory(r.fra_category)}>{r.fra_category}</abbr></dd></div>
            <div><dt>Checkpoints</dt><dd className="num">{r.checkpoints.length - 1}</dd></div>
          </dl>
          <ElevationProfile profile={r.profile} checkpoints={r.checkpoints} title={`${r.name} profile`} />
          {raceRecords.length > 0 && (
            <p className="records">
              Course records:{' '}
              {raceRecords.map((rec) => (
                <span key={rec.sex}>
                  {rec.sex === 'F' ? 'women' : 'men'} {formatTime(rec.time_s)} by{' '}
                  <Link to={`/runners/${rec.runner_id}`}>{rec.name}</Link> ({rec.season}){rec.sex === 'F' ? '; ' : '.'}
                </span>
              ))}
            </p>
          )}
        </>
      )}

      <div className="toolbar" role="group" aria-label="Filter results">
        <fieldset className="segmented">
          <legend>Show</legend>
          {[['', 'Everyone'], ['F', 'Women'], ['M', 'Men']].map(([value, label]) => (
            <label key={label}>
              <input type="radio" name="sex" value={value} checked={sex === value} onChange={() => setSex(value, { page: '' })} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <div className="toolbar__compare" aria-live="polite">
          {picked.length === 2 ? (
            <button
              type="button"
              className="button"
              onClick={() => navigate(`/ghost?race=${slug}&season=${SEASON}&runners=${picked.join(',')}`)}
            >
              Ghost race the two ticked runners
            </button>
          ) : (
            <span className="hint">Tick two runners to race them against each other.</span>
          )}
        </div>
      </div>

      {results.error && <ErrorState error={results.error} retry={results.retry} />}
      {results.loading && <Loading />}
      {results.data && results.data.items.length === 0 && <Empty>No results match this filter.</Empty>}
      {results.data && results.data.items.length > 0 && (
        <>
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Results table">
            <table className="table table--results">
              <caption className="visually-hidden">{r?.name} {SEASON} results</caption>
              <thead>
                <tr>
                  <th scope="col"><span className="visually-hidden">Compare</span></th>
                  <th scope="col" className="num">Pos</th>
                  <th scope="col">Runner</th>
                  <th scope="col" className="hide-sm">Club</th>
                  <th scope="col">Cat</th>
                  {r?.checkpoints.slice(0, -1).map((cp) => (
                    <th scope="col" key={cp.name} className="num hide-sm">{cp.name}</th>
                  ))}
                  <th scope="col" className="num">Time</th>
                </tr>
              </thead>
              <tbody>
                {results.data.items.map((row) => (
                  <tr key={row.runner_id} className={row.status === 'dnf' ? 'is-dnf' : undefined}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Compare ${row.name}`}
                        checked={picked.includes(row.runner_id)}
                        onChange={() => toggle(row.runner_id)}
                      />
                    </td>
                    <td className="num">{row.position ?? 'DNF'}</td>
                    <th scope="row"><Link to={`/runners/${row.runner_id}`}>{row.name}</Link></th>
                    <td className="hide-sm">{row.club}</td>
                    <td>{row.sex}{row.category === 'Open' ? '' : ` ${row.category}`}</td>
                    {r?.checkpoints.slice(0, -1).map((cp, i) => (
                      <td key={cp.name} className="num hide-sm">{formatTime(row.splits[i])}</td>
                    ))}
                    <td className="num time">{row.status === 'dnf' ? 'retired' : formatTime(row.time_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pager" aria-label="Results pages">
            <button type="button" className="button button--quiet" disabled={page <= 1} onClick={() => setPage(String(page - 1))}>
              Previous
            </button>
            <span>
              Page {page} of {pages} · {results.data.total} runners
            </span>
            <button type="button" className="button button--quiet" disabled={page >= pages} onClick={() => setPage(String(page + 1))}>
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  )
}
