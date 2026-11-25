import { useMemo } from 'react'
import { BELL_NAMES, rowToString } from '../ringing/notation.js'
import { pathOf } from '../ringing/touch.js'

const COLUMN = 22
const ROW = 20

/** The diagram ringers learn from: every row as figures, with one bell's path drawn through them. */
export default function BlueLine({ rows, bell, treble = 1, from = 0, currentRow = -1, label }) {
  const stage = rows[0].length
  const width = stage * COLUMN + 16
  const height = rows.length * ROW + 12
  const x = (place) => place * COLUMN - COLUMN / 2 + 8
  const y = (i) => i * ROW + 16
  const line = useMemo(() => {
    const draw = (b) => pathOf(rows, b).map((p, i) => `${i ? 'L' : 'M'}${p * COLUMN - COLUMN / 2 + 8} ${i * ROW + 16}`).join('')
    return { bell: draw(bell), treble: draw(treble) }
  }, [rows, bell, treble])
  const here = currentRow - from
  return (
    <svg className="line" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
      {here >= 0 && here < rows.length && <rect className="line__here" x="0" y={y(here) - 13} width={width} height={ROW} />}
      <line className="line__lead" x1="0" x2={width} y1={y(rows.length - 1) - 14} y2={y(rows.length - 1) - 14} />
      {bell !== treble && <path className="line__treble" d={line.treble} />}
      <path className="line__bell" d={line.bell} />
      <g className="line__figures">
        {rows.map((row, i) => (
          <text key={i} x="0" y={y(i) + 5}>
            {row.map((b, p) => (b === bell || b === treble ? null : <tspan key={b} x={x(p + 1)}>{BELL_NAMES[b - 1]}</tspan>))}
          </text>
        ))}
      </g>
      {rows.map((row, i) => i % 8 === 0 && <circle key={rowToString(row) + i} className="line__dot" cx={x(row.indexOf(bell) + 1)} cy={y(i)} r="4" />)}
    </svg>
  )
}
