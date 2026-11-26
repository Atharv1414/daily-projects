import { paths, useApi } from '../api.js'
import { Empty, ErrorState, Loading } from '../components/Layout.jsx'
import { Link, useQueryParam } from '../router.jsx'
import { SEASON } from './Home.jsx'

const CATEGORIES = ['', 'Open', 'V40', 'V50', 'V60', 'V70']
const RACE_ORDER = [
  ['hollin-pike-dash', 'Hollin Pike'],
  ['beckside-round', 'Beckside'],
  ['scar-edge-horseshoe', 'Scar Edge'],
  ['thrang-moss-trot', 'Thrang Moss'],
  ['raven-crag-race', 'Raven Crag'],
  ['three-tarns-traverse', 'Three Tarns'],
  ['gill-head-gallop', 'Gill Head'],
  ['long-stile-fell-race', 'Long Stile'],
]

/** Filters rows by category on the client: the API returns the whole table for a sex. */
export function filterRows(rows, category) {
  return category ? rows.filter((r) => r.category === category) : rows
}

export default function Championship({ headingRef }) {
  const [sex, setSex] = useQueryParam('sex', 'F')
  const [category, setCategory] = useQueryParam('category')
  const { data, error, retry } = useApi(paths.standings({ season: SEASON, sex }))
  const rows = data ? filterRows(data.rows, category) : []

  return (
    <section className="page">
      <h1 ref={headingRef} tabIndex={-1}>{SEASON} club championship</h1>
      <p className="lede">
        Best five scores count. Scores in <strong>bold</strong> are counted; the rest are shown
        for interest. A score of 100 means the runner won that race.
      </p>
      <div className="toolbar">
        <fieldset className="segmented">
          <legend>Table</legend>
          {[['F', 'Women'], ['M', 'Men']].map(([value, label]) => (
            <label key={value}>
              <input type="radio" name="table" value={value} checked={sex === value} onChange={() => setSex(value)} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <label className="field field--inline">
          <span>Age category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c || 'all'} value={c}>{c || 'All ages'}</option>
            ))}
          </select>
        </label>
      </div>
      {error && <ErrorState error={error} retry={retry} />}
      {!data && !error && <Loading label="Working out the table" />}
      {data && rows.length === 0 && <Empty>Nobody in this category has finished a race yet.</Empty>}
      {rows.length > 0 && (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Championship table">
          <table className="table table--standings">
            <caption className="visually-hidden">
              {sex === 'F' ? 'Women' : 'Men'}{category ? `, ${category}` : ''}: championship standings
            </caption>
            <thead>
              <tr>
                <th scope="col" className="num">{category ? `${category} pos` : 'Pos'}</th>
                <th scope="col">Runner</th>
                <th scope="col" className="hide-sm">Cat</th>
                {RACE_ORDER.map(([slug, short]) => (
                  <th scope="col" key={slug} className="num hide-md">{short}</th>
                ))}
                <th scope="col" className="num">Races</th>
                <th scope="col" className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const byRace = Object.fromEntries(r.races.map((x) => [x.race, x]))
                return (
                  <tr key={r.runner_id}>
                    <td className="num">{category ? r.category_rank : r.rank}</td>
                    <th scope="row">
                      <Link to={`/runners/${r.runner_id}`}>{r.name}</Link>
                      <span className="sub">{r.club}</span>
                    </th>
                    <td className="hide-sm">{r.category}</td>
                    {RACE_ORDER.map(([slug]) => {
                      const x = byRace[slug]
                      return (
                        <td key={slug} className={`num hide-md${x?.counted ? ' is-counted' : ''}`}>
                          {x ? x.points.toFixed(1) : ''}
                        </td>
                      )
                    })}
                    <td className="num">{r.races_run}</td>
                    <td className="num total">{r.total.toFixed(1)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
