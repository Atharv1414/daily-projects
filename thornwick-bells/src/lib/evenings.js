/** The next practice evenings. Tuesdays, half past seven; none in Christmas week. */
export function nextEvenings(today, count = 6) {
  const evenings = []
  const day = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12)
  day.setDate(day.getDate() + ((2 - day.getDay() + 7) % 7 || 7))
  while (evenings.length < count) {
    const christmas = (day.getMonth() === 11 && day.getDate() >= 24) || (day.getMonth() === 0 && day.getDate() <= 1)
    if (!christmas) evenings.push(new Date(day))
    day.setDate(day.getDate() + 7)
  }
  return evenings
}

export const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export const longDate = (d) => d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })

/** Which ropes are already spoken for. Made up from the date, so it is steady between visits. */
export function takenRopes(date) {
  const seed = date.getDate() * 7 + date.getMonth() * 13
  return new Set([1 + (seed % 8), 1 + ((seed * 3 + 2) % 8), 1 + ((seed * 5 + 4) % 8)])
}

export function checkVisit({ name, email, date, rope, guardian, age }) {
  const errors = {}
  if (!date) errors.date = 'Choose an evening.'
  if (!rope) errors.rope = 'Choose a rope.'
  if (!name?.trim()) errors.name = 'Enter your name.'
  if (!/^\S+@\S+\.\S+$/.test(email ?? '')) errors.email = 'Enter an email address like name@example.org.'
  const years = Number(age)
  if (!age || !Number.isInteger(years) || years < 1 || years > 120) errors.age = 'Enter your age in years.'
  else if (years < 10) errors.age = 'Ringers need to be 10 or over, so that a rope can be held safely.'
  else if (years < 18 && !guardian?.trim()) errors.guardian = 'Enter the adult who will come with you.'
  return errors
}
