// Hire prices. Everything is in whole pounds; dates are plain YYYY-MM-DD strings read as UK calendar days.

export const DURATIONS = {
  3: { label: 'Weekend break', factor: 0.62, starts: ['Fri'] },
  4: { label: 'Midweek break', factor: 0.7, starts: ['Mon'] },
  7: { label: 'One week', factor: 1, starts: ['Mon', 'Fri'] },
  10: { label: 'Ten nights', factor: 1.38, starts: ['Fri'] },
  14: { label: 'Two weeks', factor: 1.85, starts: ['Mon', 'Fri'] },
}

export const EXTRAS = {
  dog: { label: 'A dog (up to two)', price: 45, perStay: true, needsDogFriendly: true },
  bikes: { label: 'Bikes for the towpath', price: 35, max: 4, each: true },
  lesson: { label: 'An hour with an instructor at the first lock', price: 60, perStay: true },
  hamper: { label: 'Welcome hamper from the wharf shop', price: 38, perStay: true },
}

export const SECURITY_DEPOSIT = 250
export const BALANCE_DUE_DAYS = 56
export const DEPOSIT_SHARE = 0.25
export const MIN_LEAD_DAYS = 2

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function parseDay(text) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text ?? '')) return null
  const [y, m, d] = text.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d ? date : null
}

export function formatDay(date) {
  return date.toISOString().slice(0, 10)
}

export function addDays(date, days) {
  return new Date(date.getTime() + days * 86_400_000)
}

export function daysBetween(a, b) {
  return Math.round((b.getTime() - a.getTime()) / 86_400_000)
}

export const weekday = (date) => DAY_NAMES[date.getUTCDay()]

/** Low season November to March, shoulder April, May, September and October, peak June to August. */
export function seasonFor(date) {
  const month = date.getUTCMonth() + 1
  if (month >= 6 && month <= 8) return 'peak'
  if ([4, 5, 9, 10].includes(month)) return 'shoulder'
  return 'low'
}

/** Why a start date cannot be booked, or null if it can. */
export function startProblem(startText, nights, today) {
  const start = parseDay(startText)
  if (!start) return 'Choose a start date.'
  const duration = DURATIONS[nights]
  if (!duration) return 'Choose how many nights.'
  if (!duration.starts.includes(weekday(start))) {
    return `${duration.label}s start on a ${duration.starts.map((d) => ({ Mon: 'Monday', Fri: 'Friday' })[d]).join(' or ')}.`
  }
  const lead = daysBetween(today, start)
  if (lead < MIN_LEAD_DAYS) return 'We need at least two days to get the boat ready.'
  if (lead > 540) return 'We take bookings up to 18 months ahead.'
  return null
}

/** The next few start dates that work for a duration, for quick picking. */
export function nextStarts(nights, today, count = 6) {
  const out = []
  for (let day = addDays(today, MIN_LEAD_DAYS); out.length < count && daysBetween(today, day) < 540; day = addDays(day, 1)) {
    if (DURATIONS[nights].starts.includes(weekday(day))) out.push(formatDay(day))
  }
  return out
}

const roundTo5 = (n) => Math.round(n / 5) * 5

export function quote({ boat, nights, start, extras = {}, today }) {
  const date = parseDay(start)
  const problem = startProblem(start, nights, today)
  if (problem) return { ok: false, problem }
  const season = seasonFor(date)
  const hire = roundTo5(boat.weekly[season] * DURATIONS[nights].factor)
  const lines = [{ label: `${boat.name}, ${nights} nights (${season} season)`, amount: hire }]
  for (const [key, value] of Object.entries(extras)) {
    const extra = EXTRAS[key]
    if (!extra || !value) continue
    if (extra.needsDogFriendly && !boat.dogs) return { ok: false, problem: `${boat.name} is not a dog-friendly boat.` }
    const count = extra.each ? Math.min(Number(value), extra.max) : 1
    if (count > 0) lines.push({ label: extra.each ? `${extra.label} × ${count}` : extra.label, amount: extra.price * count })
  }
  const total = lines.reduce((s, l) => s + l.amount, 0)
  const lead = daysBetween(today, date)
  const payInFull = lead < BALANCE_DUE_DAYS
  const dueNow = payInFull ? total : Math.round(total * DEPOSIT_SHARE)
  return {
    ok: true,
    season,
    lines,
    total,
    dueNow,
    balance: total - dueNow,
    balanceDue: payInFull ? null : formatDay(addDays(date, -BALANCE_DUE_DAYS)),
    end: formatDay(addDays(date, nights)),
    securityDeposit: SECURITY_DEPOSIT,
  }
}

export function money(amount) {
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(amount)
}

export function longDate(text) {
  const date = parseDay(text)
  return date
    ? new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date)
    : ''
}

/** The cheapest stay on a boat: a low-season weekend. */
export const fromPrice = (boat) => roundTo5(boat.weekly.low * DURATIONS[3].factor)
