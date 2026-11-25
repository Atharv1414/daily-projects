export const pounds = (n) =>
  new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', minimumFractionDigits: Number.isInteger(n) ? 0 : 2 }).format(n)

/** Gift Aid adds 25p to each £1. Higher rate taxpayers can claim back part of the difference themselves. */
export function giftAid(amount, { eligible, band }) {
  const extra = eligible ? Math.round(amount * 25) / 100 : 0
  const relief = { basic: 0, higher: 0.2, additional: 0.25 }[band] ?? 0
  const reclaim = eligible ? Math.round((amount + extra) * relief * 100) / 100 : 0
  return { received: amount + extra, extra, reclaim, cost: Math.round((amount - reclaim) * 100) / 100 }
}

export function totals(bells) {
  const cost = bells.reduce((s, b) => s + b.cost, 0)
  const raised = bells.reduce((s, b) => s + b.raised, 0)
  return { cost, raised, left: cost - raised, share: raised / cost }
}

export function checkPledge({ amount, name, email }) {
  const errors = {}
  const value = Number(amount)
  if (!amount) errors.amount = 'Enter how much you would like to give.'
  else if (!Number.isFinite(value) || value < 1) errors.amount = 'Enter £1 or more, in numbers.'
  else if (value > 25000) errors.amount = 'For gifts over £25,000, please talk to our treasurer first.'
  else if (Math.round(value * 100) !== Number((value * 100).toFixed(6))) errors.amount = 'Use pounds and pence, such as 25.50.'
  if (!name?.trim()) errors.name = 'Enter the name for the donors’ board.'
  if (!/^\S+@\S+\.\S+$/.test(email ?? '')) errors.email = 'Enter an email address like name@example.org.'
  return errors
}
