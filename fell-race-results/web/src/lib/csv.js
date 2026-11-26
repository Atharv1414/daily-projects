import { parseTime } from './format.js'

/**
 * Parses an organiser's paste: one runner per line, "R0123, 14:47, 29:12" or
 * "R0123, 14:47, DNF". Blank lines and lines starting with # are skipped. Returns the rows
 * the API will accept plus a list of problems, each tied to a line number, so the form can
 * show them before anything is sent.
 */
export function parseResults(text, expectedSplits) {
  const rows = []
  const problems = []
  const seen = new Set()
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1
    const trimmed = raw.trim()
    if (!trimmed || trimmed.startsWith('#')) return
    const cells = trimmed.split(/[,\t]/).map((c) => c.trim()).filter(Boolean)
    const [id, ...times] = cells
    const runnerId = (id ?? '').toUpperCase()
    if (!/^R\d{4}$/.test(runnerId)) {
      problems.push({ line, message: `"${id}" is not a runner number like R0123` })
      return
    }
    if (seen.has(runnerId)) {
      problems.push({ line, message: `${runnerId} is on more than one line` })
      return
    }
    seen.add(runnerId)
    const dnf = times.length > 0 && times[times.length - 1].toUpperCase() === 'DNF'
    const timeCells = dnf ? times.slice(0, -1) : times
    const splits = timeCells.map(parseTime)
    const bad = timeCells.find((_, i) => splits[i] === null)
    if (bad !== undefined) {
      problems.push({ line, message: `"${bad}" is not a time (use mm:ss or h:mm:ss)` })
      return
    }
    if (splits.length === 0) {
      problems.push({ line, message: `${runnerId} has no times` })
      return
    }
    if (splits.some((s, i) => i > 0 && s <= splits[i - 1])) {
      problems.push({ line, message: `${runnerId}'s times must go up at every checkpoint` })
      return
    }
    if (!dnf && splits.length !== expectedSplits) {
      problems.push({ line, message: `${runnerId} needs ${expectedSplits} times for a finish, or end the line with DNF` })
      return
    }
    if (dnf && splits.length >= expectedSplits) {
      problems.push({ line, message: `${runnerId} is marked DNF but has a finish time` })
      return
    }
    rows.push({ runner_id: runnerId, status: dnf ? 'dnf' : 'finished', splits, version: 1 })
  })
  return { rows, problems }
}

/** A readable, unique-enough idempotency key for an upload. */
export function suggestUploadId(slug, season, now = new Date()) {
  const stamp = now.toISOString().slice(0, 16).replace(/[-:T]/g, '')
  return `${slug.slice(0, 24)}-${season}-${stamp}`
}
