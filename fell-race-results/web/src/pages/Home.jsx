import { paths, useApi } from '../api.js'
import ElevationProfile, { Sparkline } from '../components/ElevationProfile.jsx'
import { ErrorState, Loading } from '../components/Layout.jsx'
import { formatDate, formatTime } from '../lib/format.js'
import { Link } from '../router.jsx'

export const SEASON = 2026

function Leaders({ sex, label }) {
  const { data, error, retry } = useApi(paths.standings({ season: SEASON, sex }))
  if (error) return <ErrorState error={error} retry={retry} />
  if (!data) return <Loading label={`Loading ${label.toLowerCase()} table`} />
  return (
    <section className="leaders" aria-labelledby={`leaders-${sex}`}>
      <h3 id={`leaders-${sex}`}>{label}</h3>
      <ol>
        {data.rows.slice(0, 3).map((r) => (
          <li key={r.runner_id}>
            <Link to={`/runners/${r.runner_id}`}>{r.name}</Link>
            <span className="leaders__club">{r.club}</span>
            <span className="num">{r.total.toFixed(1)}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function Home({ headingRef }) {
  const races = useApi(paths.races(SEASON))
  const showcase = races.data?.find((r) => r.slug === 'scar-edge-horseshoe')

  return (
    <>
      <section className="hero">
        <div className="hero__text">
          <p className="eyebrow">Fell running since 1978 · {SEASON} season complete</p>
          <h1 ref={headingRef} tabIndex={-1}>
            Up the gill, over the tops, <em>down through the bracken</em>
          </h1>
          <p className="lede">
            Results, records and the club championship for eight races on the Hollinbeck fells.
            Pick any two runners and watch them race each other again, checkpoint by checkpoint.
          </p>
          <div className="hero__actions">
            <Link className="button" to="/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084">
              Watch a ghost race
            </Link>
            <Link className="button button--quiet" to="/championship">
              {SEASON} championship
            </Link>
          </div>
        </div>
        <div className="hero__art">
          {showcase ? (
            <>
              <ElevationProfile
                profile={showcase.profile}
                checkpoints={[]}
                title={`${showcase.name} profile`}
              />
              <p className="caption">
                {showcase.name}: {showcase.distance_km} km and {showcase.climb_m} m of climb. Won in{' '}
                {formatTime(showcase.winning_time_m)} and {formatTime(showcase.winning_time_f)}.
              </p>
            </>
          ) : (
            races.error && <ErrorState error={races.error} retry={races.retry} />
          )}
        </div>
      </section>

      <section className="band" aria-labelledby="fixtures">
        <div className="band__head">
          <h2 id="fixtures">The {SEASON} championship races</h2>
          <Link to="/races">All race details</Link>
        </div>
        {races.loading && <Loading label="Loading fixtures" />}
        {races.data && (
          <ol className="fixtures">
            {races.data.map((r, i) => (
              <li key={r.slug} className="fixture">
                <span className="fixture__round num">{i + 1}</span>
                <span className="fixture__date">{formatDate(r.date)}</span>
                <Link className="fixture__name" to={`/races/${r.slug}`}>
                  {r.name}
                </Link>
                <span className="fixture__meta">
                  <abbr title={`Fell Runners Association category ${r.fra_category}`}>{r.fra_category}</abbr> ·{' '}
                  {r.distance_km} km · {r.climb_m} m
                </span>
                <Sparkline profile={r.profile} />
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="band band--split" aria-labelledby="leaders">
        <div>
          <h2 id="leaders">Championship leaders</h2>
          <p>
            Every finisher scores the winner&rsquo;s time divided by theirs, times 100. The best five
            scores from eight races make the total, so nobody has to run them all.
          </p>
          <Link to="/championship">Full tables and categories</Link>
        </div>
        <Leaders sex="F" label="Women" />
        <Leaders sex="M" label="Men" />
      </section>
    </>
  )
}
