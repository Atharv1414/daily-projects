/* Timing. Bells strike one after another, with a short breath before each pair of rows ("handstroke gap"). */

export function schedule(rows, { gap = 0.25, handstrokeGap = 1, cover = false } = {}) {
  const blows = []
  let at = 0
  rows.forEach((row, r) => {
    if (r > 0 && r % 2 === 0) at += gap * handstrokeGap
    const bells = cover ? [...row, row.length + 1] : row
    bells.forEach((bell, place) => {
      blows.push({ row: r, place: place + 1, bell, at })
      at += gap
    })
  })
  return blows
}

export const PERFECT = 0.06
export const GOOD = 0.14

/**
 * Pairs each of the learner's blows with the nearest one they were due to make, in order.
 * A pull further away than half a row counts as an extra rather than as a very late blow.
 */
export function score(due, pulls, reach = 0.6) {
  const left = [...pulls].sort((a, b) => a - b)
  const results = due.map((at) => {
    let best = -1
    left.forEach((p, i) => {
      if (Math.abs(p - at) <= reach && (best < 0 || Math.abs(p - at) < Math.abs(left[best] - at))) best = i
    })
    if (best < 0) return { at, error: null, grade: 'missed' }
    const error = left.splice(best, 1)[0] - at
    const size = Math.abs(error)
    return { at, error, grade: size <= PERFECT ? 'struck' : size <= GOOD ? 'close' : 'clipped' }
  })
  const hits = results.filter((r) => r.error !== null)
  const mean = hits.length ? hits.reduce((s, r) => s + r.error, 0) / hits.length : 0
  const points = results.reduce((s, r) => s + { struck: 1, close: 0.6, clipped: 0.2, missed: 0 }[r.grade], 0)
  return {
    results,
    extras: left.length,
    mean,
    percent: due.length ? Math.max(0, Math.round((100 * (points - left.length * 0.5)) / due.length)) : 0,
  }
}

/** One sentence of advice, the way a tower captain would give it. */
export function advise({ results, mean, extras, percent }) {
  if (results.length && results.every((r) => r.grade === 'missed')) return 'We did not hear you. Press Space, or tap the bell, each time your number strikes.'
  const missed = results.filter((r) => r.grade === 'missed').length
  if (missed > results.length / 3) return 'You lost your place. Try counting your position aloud: first, second, third.'
  if (extras > 2) return 'You pulled more often than you needed to. One pull for each row.'
  if (mean > 0.08) return 'Good rhythm, but you are late. Start the pull as the bell before you strikes.'
  if (mean < -0.08) return 'Good rhythm, but you are early. Hold up a little longer.'
  if (percent >= 85) return 'Beautifully struck. Come on Tuesday: we are short of ringers.'
  return 'Nearly there. Listen for an even row rather than watching the numbers.'
}
