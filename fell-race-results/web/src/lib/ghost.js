/**
 * Ghost-race geometry. Runners are only timed at checkpoints, so between two checkpoints we
 * assume an even pace along the course. Everything here is pure so it is easy to test.
 */

/** Kilometres covered after `t` seconds, given checkpoint distances and cumulative splits. */
export function distanceAt(checkpointKm, splits, t) {
  if (t <= 0 || splits.length === 0) return 0
  let prevT = 0
  let prevKm = 0
  for (let i = 0; i < splits.length; i += 1) {
    if (t <= splits[i]) {
      const f = (t - prevT) / (splits[i] - prevT)
      return prevKm + f * (checkpointKm[i] - prevKm)
    }
    prevT = splits[i]
    prevKm = checkpointKm[i]
  }
  return prevKm // finished, or stopped at the last checkpoint reached (DNF)
}

/** Seconds taken to reach `km`, or null if the runner never got there. */
export function timeAtDistance(checkpointKm, splits, km) {
  if (km <= 0) return 0
  let prevT = 0
  let prevKm = 0
  for (let i = 0; i < splits.length; i += 1) {
    if (km <= checkpointKm[i] + 1e-9) {
      const f = (km - prevKm) / (checkpointKm[i] - prevKm)
      return prevT + f * (splits[i] - prevT)
    }
    prevT = splits[i]
    prevKm = checkpointKm[i]
  }
  return null
}

/** Height in metres at `km`, interpolated between profile points. */
export function elevationAt(profile, km) {
  if (km <= profile[0][0]) return profile[0][1]
  for (let i = 1; i < profile.length; i += 1) {
    const [x1, y1] = profile[i]
    if (km <= x1) {
      const [x0, y0] = profile[i - 1]
      return y0 + ((km - x0) / (x1 - x0)) * (y1 - y0)
    }
  }
  return profile[profile.length - 1][1]
}

/**
 * Who leads at time `t`, and by how much. The time gap is measured at the trailing runner's
 * position: how long ago the leader passed the spot the trailer is at now.
 */
export function gapAt(checkpointKm, a, b, t) {
  const kmA = distanceAt(checkpointKm, a.splits, t)
  const kmB = distanceAt(checkpointKm, b.splits, t)
  if (Math.abs(kmA - kmB) < 1e-6) return { leader: null, metres: 0, seconds: 0 }
  const [lead, trail, trailKm] = kmA > kmB ? [a, b, kmB] : [b, a, kmA]
  const leaderPassed = timeAtDistance(checkpointKm, lead.splits, trailKm) ?? t
  return {
    leader: lead.runner_id,
    metres: Math.round(Math.abs(kmA - kmB) * 1000),
    seconds: Math.max(0, Math.round(t - leaderPassed)),
    trailer: trail.runner_id,
  }
}

/** Per-checkpoint comparison: leg times, the leader and the change in gap on each leg. */
export function legTable(checkpoints, a, b) {
  return checkpoints.map((cp, i) => {
    const at = a.splits[i]
    const bt = b.splits[i]
    const legA = at == null ? null : at - (i === 0 ? 0 : a.splits[i - 1])
    const legB = bt == null ? null : bt - (i === 0 ? 0 : b.splits[i - 1])
    return {
      name: cp.name,
      km: cp.km,
      a: at ?? null,
      b: bt ?? null,
      legA,
      legB,
      gap: at != null && bt != null ? bt - at : null, // positive: a is ahead
      legDelta: legA != null && legB != null ? legB - legA : null, // positive: a gained
    }
  })
}

/** Plain-English summary of a two-runner race, e.g. for the caption under the chart. */
export function storyline(checkpoints, a, b) {
  const first = (name) => name.split(' ')[0]
  const rows = legTable(checkpoints, a, b)
  const lines = []
  let leader = null
  for (const row of rows) {
    if (row.gap == null) break
    const now = row.gap > 0 ? a : row.gap < 0 ? b : null
    const where = row.name === 'Finish' ? 'at the finish' : `at ${row.name}`
    if (now === null) {
      lines.push(`Level ${where}.`)
    } else if (leader === null || now.runner_id !== leader.runner_id) {
      const verb = leader === null ? 'leads' : 'takes the lead'
      lines.push(`${first(now.name)} ${verb} by ${formatSeconds(row.gap)} ${where}.`)
    } else if (row.name === 'Finish') {
      lines.push(`${first(now.name)} holds on by ${formatSeconds(row.gap)}.`)
    }
    leader = now ?? leader
  }
  for (const r of [a, b]) {
    if (r.status === 'dnf') lines.push(`${first(r.name)} retired after ${checkpoints[r.splits.length - 1].name}.`)
  }
  return lines
}

function formatSeconds(gap) {
  const s = Math.abs(gap)
  if (s < 60) return `${s} s`
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`
}
