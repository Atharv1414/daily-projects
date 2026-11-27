// Checks for the crew details form. Messages say what to do, not just what is wrong.

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

export function normalisePhone(text) {
  const digits = (text ?? '').replace(/[\s()-]/g, '')
  if (/^\+44\d{9,10}$/.test(digits)) return `0${digits.slice(3)}`
  return digits
}

export function validateCrew(form, boat) {
  const errors = {}
  if ((form.name ?? '').trim().length < 2) errors.name = 'Enter the lead name for the booking.'
  if (!EMAIL.test((form.email ?? '').trim())) errors.email = 'Enter an email address like name@example.com.'
  if (!/^0\d{9,10}$/.test(normalisePhone(form.phone))) {
    errors.phone = 'Enter a UK phone number, such as 07700 900123, so the wharf can reach you on the day.'
  }
  const crew = Number(form.crew)
  if (!Number.isInteger(crew) || crew < 1) errors.crew = 'Say how many people are coming.'
  else if (boat && crew > boat.berths) errors.crew = `${boat.name} sleeps ${boat.berths}. Choose a bigger boat or a smaller crew.`
  if (!form.experience) errors.experience = 'Tell us whether anyone has steered a narrowboat before.'
  if (!form.adultAtHelm) errors.adultAtHelm = 'An adult must be at the tiller whenever the boat is moving.'
  if (!form.terms) errors.terms = 'Please read and accept the hire terms.'
  return errors
}

/** A short reference made from the booking itself, so the same booking always shows the same one. */
export function bookingReference(parts) {
  let h = 2166136261
  for (const ch of JSON.stringify(parts)) {
    h ^= ch.charCodeAt(0)
    h = Math.imul(h, 16777619) >>> 0
  }
  return `KL-${h.toString(36).toUpperCase().padStart(7, '0').slice(0, 7)}`
}
