import { useState } from 'react'

// Working a lock uphill, one step at a time. The water level, gates and paddles all follow the step,
// and the instruction is announced to screen readers as it changes.

export const LOCK_STEPS = [
  { title: 'Moor below the lock', text: 'Stop on the lock landing below the bottom gates. One crew member walks up with the windlass. The chamber is full, so the bottom gates stay shut.', water: 'high', bottomGate: 'shut', topGate: 'shut', bottomPaddles: false, topPaddles: false, boat: 'below' },
  { title: 'Empty the chamber', text: 'Check the top gates and their paddles are shut. Wind up the bottom paddles and watch the water fall to the level of the boat.', water: 'falling', bottomGate: 'shut', topGate: 'shut', bottomPaddles: true, topPaddles: false, boat: 'below' },
  { title: 'Open the bottom gates', text: 'When the levels match, the gates swing easily. Lean on the balance beam and walk it round. Never force a gate against water.', water: 'low', bottomGate: 'open', topGate: 'shut', bottomPaddles: true, topPaddles: false, boat: 'below' },
  { title: 'Bring the boat in', text: 'Steer in slowly and keep the boat towards the front of the chamber, but well clear of the cill under the top gates.', water: 'low', bottomGate: 'open', topGate: 'shut', bottomPaddles: true, topPaddles: false, boat: 'in-low' },
  { title: 'Close up behind', text: 'Close the bottom gates and wind the bottom paddles down. Lower them with the windlass; never let them spin free.', water: 'low', bottomGate: 'shut', topGate: 'shut', bottomPaddles: false, topPaddles: false, boat: 'in-low' },
  { title: 'Fill the chamber', text: 'Open the top ground paddles first and gate paddles only once the boat is covered. Use a little forward gear to hold the boat steady as it rises.', water: 'rising', bottomGate: 'shut', topGate: 'shut', bottomPaddles: false, topPaddles: true, boat: 'in-high' },
  { title: 'Open the top gates and go', text: 'Open the top gates, take the boat out, then close the gates and lower the paddles behind you. Leave the lock as you would want to find it.', water: 'high', bottomGate: 'shut', topGate: 'open', bottomPaddles: false, topPaddles: false, boat: 'above' },
]

const LEVEL = { high: 60, falling: 85, rising: 85, low: 112 }
const BOAT_X = { below: 30, 'in-low': 200, 'in-high': 200, above: 470 }

export default function LockDiagram() {
  const [index, setIndex] = useState(0)
  const step = LOCK_STEPS[index]
  const level = LEVEL[step.water]
  const boatY = step.boat === 'below' || step.boat === 'in-low' ? 112 : 60

  return (
    <section className="lock" aria-labelledby="lock-heading">
      <h2 id="lock-heading">Working a lock, going up</h2>
      <svg viewBox="0 0 640 180" className="lock__svg" aria-hidden="true">
        {/* Lower pound, chamber and upper pound. */}
        <rect x="0" y="112" width="170" height="58" className="lock__water" />
        <rect x="170" y={level} width="290" height={170 - level} className={`lock__water lock__water--${step.water}`} />
        <rect x="460" y="60" width="180" height="110" className="lock__water" />
        <path d="M0,170 L170,170 L170,180 L640,180 L640,170 L460,170 L460,60" className="lock__wall" />
        <rect x="166" y="40" width="8" height="140" className="lock__wall-fill" />
        <rect x="456" y="20" width="8" height="40" className="lock__wall-fill" />
        <line x1="0" x2="170" y1="40" y2="40" className="lock__bank" />
        <line x1="170" x2="640" y1="20" y2="20" className="lock__bank" />
        {/* Gates: drawn as a beam on the bank and a leaf in the water; open leaves swing aside. */}
        <g className={`lock__gate lock__gate--${step.bottomGate}`}>
          <rect x={step.bottomGate === 'open' ? 150 : 166} y="50" width="10" height="122" />
          <line x1="120" x2="176" y1="40" y2="40" className="lock__beam" />
        </g>
        <g className={`lock__gate lock__gate--${step.topGate}`}>
          <rect x={step.topGate === 'open' ? 470 : 456} y="20" width="10" height="44" />
          <line x1="456" x2="512" y1="20" y2="20" className="lock__beam" />
        </g>
        <circle cx="186" cy="30" r="7" className={`lock__paddle${step.bottomPaddles ? ' lock__paddle--open' : ''}`} />
        <circle cx="440" cy="12" r="7" className={`lock__paddle${step.topPaddles ? ' lock__paddle--open' : ''}`} />
        <g className="lock__boat" style={{ transform: `translate(${BOAT_X[step.boat]}px, ${step.water === 'rising' ? 86 : boatY}px)` }}>
          <path d="M0,0 L120,0 Q134,0 138,6 L132,18 L6,18 Q0,16 0,10 Z" />
          <rect x="22" y="-14" width="80" height="14" />
        </g>
      </svg>
      <div className="lock__step" aria-live="polite">
        <p className="lock__count">Step {index + 1} of {LOCK_STEPS.length}</p>
        <h3>{step.title}</h3>
        <p>{step.text}</p>
      </div>
      <div className="lock__controls">
        <button type="button" className="button button--quiet" onClick={() => setIndex((i) => i - 1)} disabled={index === 0}>
          Previous step
        </button>
        <button type="button" className="button" onClick={() => setIndex((i) => i + 1)} disabled={index === LOCK_STEPS.length - 1}>
          Next step
        </button>
      </div>
    </section>
  )
}
