import { useCallback, useEffect, useRef, useState } from 'react'
import { createBells } from './audio.js'

const AHEAD = 0.15 // seconds of sound queued in advance, so a busy page cannot stumble the rhythm

/** Plays blows in time and reports which one is sounding. */
export function useRinging() {
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(-1)
  const bells = useRef(null)
  const timer = useRef(0)
  const startedAt = useRef(0)

  const stop = useCallback(() => {
    clearInterval(timer.current)
    setPlaying(false)
  }, [])

  const play = useCallback(async (blows, total, { silent = null, onEnd } = {}) => {
    clearInterval(timer.current)
    bells.current ??= createBells()
    await bells.current.resume()
    let next = 0
    let shown = -1
    const zero = bells.current.now() + 0.4
    startedAt.current = zero
    setCurrent(-1)
    setPlaying(true)
    timer.current = setInterval(() => {
      const t = bells.current.now() - zero
      while (next < blows.length && blows[next].at < t + AHEAD) {
        if (blows[next].bell !== silent) bells.current.strike(blows[next].bell, total, zero + blows[next].at)
        next += 1
      }
      let i = shown
      while (i + 1 < blows.length && blows[i + 1].at <= t) i += 1
      if (i !== shown) {
        shown = i
        setCurrent(i)
      }
      if (t > blows.at(-1).at + 1.2) {
        clearInterval(timer.current)
        setPlaying(false)
        onEnd?.()
      }
    }, 25)
  }, [])

  const strikeNow = useCallback(async (bell, total) => {
    bells.current ??= createBells()
    const elapsed = bells.current.now() - startedAt.current
    await bells.current.resume()
    bells.current.strike(bell, total)
    return elapsed
  }, [])

  useEffect(() => () => {
    clearInterval(timer.current)
    bells.current?.close()
    bells.current = null
  }, [])

  return { playing, current, play, stop, strikeNow }
}
