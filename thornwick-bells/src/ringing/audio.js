/*
 * A church bell is five tuned partials over a hum. Ours are made here rather than recorded,
 * so nothing is downloaded and each bell can be tuned to the real ring's key.
 */
const PARTIALS = [
  { ratio: 0.5, gain: 0.35, decay: 4.2 }, // hum
  { ratio: 1, gain: 0.5, decay: 2.6 }, // prime
  { ratio: 1.2, gain: 0.4, decay: 2 }, // tierce: the minor third that makes a bell sound like a bell
  { ratio: 1.5, gain: 0.18, decay: 1.2 }, // quint
  { ratio: 2, gain: 0.55, decay: 1 }, // nominal
  { ratio: 2.66, gain: 0.2, decay: 0.6 },
  { ratio: 4.1, gain: 0.12, decay: 0.3 },
]
const SCALE = [0, 2, 4, 5, 7, 9, 11, 12] // semitones above the tenor
const TENOR_HZ = 174.6 // F

/** Bell 1 is the highest. Fewer bells means the lightest ones stay silent, as in a tower. */
export function frequency(bell, total) {
  return TENOR_HZ * 2 ** (SCALE[total - bell] / 12)
}

export function createBells(Context = globalThis.AudioContext) {
  if (!Context) return { now: () => performance.now() / 1000, strike() {}, close() {}, async resume() {} }
  const context = new Context()
  const master = context.createGain()
  master.gain.value = 0.16
  master.connect(context.destination)
  return {
    now: () => context.currentTime,
    resume: () => context.resume(),
    close: () => context.close(),
    strike(bell, total, at = context.currentTime) {
      for (const p of PARTIALS) {
        const oscillator = context.createOscillator()
        const envelope = context.createGain()
        oscillator.frequency.value = frequency(bell, total) * p.ratio
        envelope.gain.setValueAtTime(0.0001, at)
        envelope.gain.exponentialRampToValueAtTime(p.gain, at + 0.004)
        envelope.gain.exponentialRampToValueAtTime(0.0001, at + p.decay)
        oscillator.connect(envelope).connect(master)
        oscillator.start(at)
        oscillator.stop(at + p.decay)
      }
    },
  }
}
