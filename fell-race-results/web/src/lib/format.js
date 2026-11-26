/** Formatting helpers shared by every page. Times are whole seconds. */

export function formatTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '–'
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

/** "+1:05" style gap; zero is "level". */
export function formatGap(seconds) {
  const s = Math.round(Math.abs(seconds))
  if (s === 0) return 'level'
  return s < 60 ? `${s} s` : formatTime(s)
}

export function formatPace(seconds, km) {
  if (!seconds || !km) return '–'
  return `${formatTime(seconds / km)} /km`
}

export function ordinal(n) {
  const rem100 = n % 100
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`
  return `${n}${{ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th'}`
}

const dateFormat = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'long' })

export function formatDate(iso) {
  return dateFormat.format(new Date(`${iso}T12:00:00`))
}

export const FRA = {
  A: 'at least 50 m of climb per km, mostly off path',
  B: 'at least 25 m of climb per km',
  C: 'at least 20 m of climb per km, mostly on paths',
  S: 'under 10 km',
  M: '10 to 20 km',
  L: 'over 20 km',
}

export function describeCategory(code) {
  return `Category ${code}: ${FRA[code[0]]}, ${FRA[code[1]]}`
}

/**
 * Parses "mm:ss", "h:mm:ss" or a bare number of seconds. Returns null if it is not a time.
 */
export function parseTime(text) {
  const t = String(text).trim()
  if (/^\d+$/.test(t)) return Number(t)
  const m = /^(?:(\d+):)?(\d{1,2}):(\d{2})$/.exec(t)
  if (!m) return null
  const [h, mins, secs] = [Number(m[1] ?? 0), Number(m[2]), Number(m[3])]
  if (secs > 59 || (m[1] !== undefined && mins > 59)) return null
  return h * 3600 + mins * 60 + secs
}
