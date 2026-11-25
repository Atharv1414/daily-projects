/*
 * Place notation is how ringers write a method down. Each change lists the places where
 * a bell stays put; everyone else swaps with their neighbour. "x" means nobody stays.
 * "&" marks a block that is rung forwards and then backwards around its last change.
 */

export const BELL_NAMES = '1234567890ET'

export class NotationError extends Error {}

export function rounds(stage) {
  return Array.from({ length: stage }, (_, i) => i + 1)
}

export function rowToString(row) {
  return row.map((bell) => BELL_NAMES[bell - 1]).join('')
}

function parseChange(text, stage) {
  const places = [...text].map((c) => BELL_NAMES.indexOf(c) + 1)
  if (places.some((p) => p < 1 || p > stage)) {
    throw new NotationError(`"${text}" names a place that ${stage} bells do not have.`)
  }
  const sorted = [...new Set(places)].sort((a, b) => a - b)
  // The bells between two stated places must pair off, so outside places are often left unsaid.
  if (sorted.length > 0 && sorted[0] % 2 === 0) sorted.unshift(1)
  if (sorted.length > 0 && (stage - sorted.at(-1)) % 2 === 1) sorted.push(stage)
  for (let i = 1; i < sorted.length; i++) {
    if ((sorted[i] - sorted[i - 1]) % 2 === 0) {
      throw new NotationError(`"${text}" leaves a bell with nobody to swap with.`)
    }
  }
  if (sorted.length === 0 && stage % 2 === 1) {
    throw new NotationError('With an odd number of bells somebody has to stay still.')
  }
  return sorted
}

function parseBlock(block, stage) {
  const symmetric = block.startsWith('&')
  const body = block.replace(/^[&+]/, '')
  const tokens = body.match(/[x-]|[0-9ET]+|\S/gi) ?? []
  const changes = tokens
    .filter((t) => t !== '.')
    .map((t) => {
      if (/^[x-]$/i.test(t)) return parseChange('', stage)
      if (!/^[0-9ET]+$/i.test(t)) throw new NotationError(`"${t}" is not place notation.`)
      return parseChange(t.toUpperCase(), stage)
    })
  if (changes.length === 0) throw new NotationError('The notation is empty.')
  return symmetric ? [...changes, ...changes.slice(0, -1).reverse()] : changes
}

export function parseNotation(text, stage) {
  return text
    .replace(/\s+/g, '')
    .split(',')
    .flatMap((block) => parseBlock(block, stage))
}

export function applyChange(row, places) {
  const next = [...row]
  for (let i = 0; i < row.length; ) {
    if (places.includes(i + 1) || i === row.length - 1) {
      i += 1
    } else {
      next[i] = row[i + 1]
      next[i + 1] = row[i]
      i += 2
    }
  }
  return next
}
