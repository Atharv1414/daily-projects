import { useMemo } from 'react'
import { Link, useQuery } from '../lib/router.jsx'
import { METHODS, STAGE_NAMES } from '../ringing/methods.js'
import { ring } from '../ringing/touch.js'
import BlueLine from '../components/BlueLine.jsx'

const LEVELS = ['First steps', 'Getting harder', 'A long winter']

export default function Methods() {
  const [query, setQuery] = useQuery()
  const bells = query.get('bells') ?? ''
  const level = query.get('level') ?? ''
  const shown = METHODS.filter((m) => (!bells || String(m.stage) === bells) && (!level || m.level === level))
  return (
    <div className="page">
      <header className="page__head">
        <h1>The method book</h1>
        <p className="lead">Thirteen ways to put bells in order and back again. Open one to see its line, hear it rung, or change what the conductor calls.</p>
      </header>
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>Bells
          <select value={bells} onChange={(e) => setQuery({ bells: e.target.value })}>
            <option value="">Any number</option>
            {Object.entries(STAGE_NAMES).map(([n, name]) => <option key={n} value={n}>{name}</option>)}
          </select>
        </label>
        <label>How hard
          <select value={level} onChange={(e) => setQuery({ level: e.target.value })}>
            <option value="">Any</option>
            {LEVELS.map((l) => <option key={l}>{l}</option>)}
          </select>
        </label>
        <p role="status">{shown.length === 1 ? '1 method' : `${shown.length} methods`}</p>
      </form>
      {shown.length === 0 ? (
        <p className="empty">Nothing in the book matches both. <button className="plain" onClick={() => setQuery({ bells: null, level: null })}>Show every method</button></p>
      ) : (
        <ul className="book">{shown.map((m) => <Entry key={m.id} method={m} />)}</ul>
      )}
    </div>
  )
}

function Entry({ method }) {
  const rows = useMemo(() => {
    const t = ring(method)
    return t.rows.slice(0, Math.min(t.leadLength, 32) + 1)
  }, [method])
  return (
    <li className="entry">
      <div className="entry__line"><BlueLine rows={rows} bell={2} label={`First lead of ${method.name}, bell 2`} /></div>
      <div>
        <h2><Link to={`/methods/${method.id}`}>{method.name}</Link></h2>
        <p className="entry__facts">{STAGE_NAMES[method.stage]}, {method.course} changes. {method.level}.</p>
        <p>{method.story}</p>
      </div>
    </li>
  )
}
