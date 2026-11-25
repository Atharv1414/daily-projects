import { applyChange, parseNotation, rounds, rowToString } from './notation.js'

const MAX_LEADS = 240

/**
 * Rings a method. `calls` is one letter per lead: "p" plain, "b" bob, "s" single.
 * With no calls it rings plain leads until the bells come back into order ("come round").
 * The first row is rounds; every later row is one change after it.
 */
export function ring(method, calls = '') {
  const plain = parseNotation(method.notation, method.stage)
  const callChanges = {
    p: plain.at(-1),
    b: method.calls && parseNotation(method.calls.bob, method.stage)[0],
    s: method.calls?.single && parseNotation(method.calls.single, method.stage)[0],
  }
  const start = rowToString(rounds(method.stage))
  const rows = [rounds(method.stage)]
  const leadHeads = []
  const wanted = calls || null
  let cameRound = false
  for (let lead = 0; lead < (wanted ? wanted.length : MAX_LEADS); lead++) {
    const letter = wanted ? wanted[lead] : 'p'
    const call = callChanges[letter]
    if (!call) throw new RangeError(`${method.name} has no call "${letter}".`)
    for (let i = 0; i < plain.length; i++) {
      rows.push(applyChange(rows.at(-1), i === plain.length - 1 ? call : plain[i]))
    }
    leadHeads.push({ row: rows.length - 1, call: letter, head: rowToString(rows.at(-1)) })
    if (rowToString(rows.at(-1)) === start) {
      cameRound = true
      if (!wanted) break
    }
  }
  return { rows, leadHeads, leadLength: plain.length, cameRound, ...prove(rows) }
}

/** A touch is true when no row repeats, apart from the rounds at each end. */
export function prove(rows) {
  const seen = new Map()
  const repeats = []
  rows.slice(1).forEach((row, i) => {
    const key = rowToString(row)
    if (seen.has(key)) repeats.push({ row: key, first: seen.get(key), again: i + 1 })
    else seen.set(key, i + 1)
  })
  return { changes: rows.length - 1, isTrue: repeats.length === 0, repeats }
}

export function factorial(n) {
  return n < 2 ? 1 : n * factorial(n - 1)
}

/** Where one bell is in each row, counting places from 1. */
export function pathOf(rows, bell) {
  return rows.map((row) => row.indexOf(bell) + 1)
}

/** Ringers describe their work in words. This turns a path into the ones they would use. */
export function describe(path, i) {
  const here = path[i]
  const before = path[i - 1]
  const after = path[i + 1]
  if (before === undefined || after === undefined) return 'start or finish'
  if (before === here && after === here) return 'staying put'
  if (before === here || after === here) return here === 1 ? 'leading' : 'making a place'
  if (before < here && after > here) return 'hunting up'
  if (before > here && after < here) return 'hunting down'
  return 'dodging'
}
