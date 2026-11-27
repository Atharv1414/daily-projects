// Today's date as a UTC midnight, so every date sum works in whole days.
export function today(now = new Date()) {
  return new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()))
}
