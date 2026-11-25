import { useEffect, useMemo, useRef, useState } from 'react'
import { findMethod } from '../ringing/methods.js'
import { rowToString } from '../ringing/notation.js'
import { pathOf, ring } from '../ringing/touch.js'

const WINDOW = 31

/** The front page is rung as you read it: scrolling moves through one course, and the bottom comes round. */
export default function Spine() {
  const { rows } = useMemo(() => ring(findMethod('plain-bob-major')), [])
  const [at, setAt] = useState(0)
  const frame = useRef(0)
  useEffect(() => {
    const update = () => {
      frame.current = 0
      const room = document.documentElement.scrollHeight - window.innerHeight
      const share = room > 0 ? Math.min(1, window.scrollY / room) : 0
      setAt(Math.round(share * (rows.length - 1)))
    }
    const onScroll = () => {
      frame.current ||= requestAnimationFrame(update)
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      cancelAnimationFrame(frame.current)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [rows])
  const first = Math.max(0, Math.min(rows.length - WINDOW, at - 15))
  const shown = rows.slice(first, first + WINDOW)
  const path = (bell) => pathOf(shown, bell).map((p, i) => `${i ? 'L' : 'M'}${p * 24 - 4} ${i * 24 + 18}`).join('')
  const done = at === rows.length - 1
  return (
    <aside className="spine" aria-label="Plain Bob Major, rung as you scroll">
      <svg className="spine__grid" viewBox={`0 0 206 ${WINDOW * 24 + 12}`} aria-hidden="true">
        <path className="line__treble" d={path(1)} />
        <path className="line__bell" d={path(8)} />
        {shown.map((row, i) => (
          <text key={first + i} className={first + i === at ? 'spine__row spine__row--here' : first + i < at ? 'spine__row spine__row--rung' : 'spine__row'} y={i * 24 + 24}>
            {row.map((b, p) => (first + i !== at && (b === 1 || b === 8) ? null : <tspan key={b} x={p * 24 + 20} className={b === 1 ? 'is-treble' : b === 8 ? 'is-bell' : undefined}>{b}</tspan>))}
          </text>
        ))}
      </svg>
      <p className="spine__note"><b>{rowToString(rows[at])}</b><span>{done ? 'That’s all. The bells have come round.' : at === 0 ? 'Scroll to ring 112 changes.' : `Change ${at} of ${rows.length - 1}`}</span></p>
    </aside>
  )
}
