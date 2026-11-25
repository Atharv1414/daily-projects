import { useState } from 'react'
import Bell from '../components/Bell.jsx'
import Spine from '../components/Spine.jsx'
import { BELLS } from '../content/bells.js'
import { pounds, totals } from '../lib/giving.js'
import { Link } from '../lib/router.jsx'
import { useRinging } from '../ringing/useRinging.js'

export default function Home() {
  const { strikeNow } = useRinging()
  const [last, setLast] = useState(null)
  const [nudge, setNudge] = useState(0)
  const sum = totals(BELLS)
  const pull = (bell) => {
    setLast(bell)
    setNudge((n) => n + 1)
    if (bell.number !== 5) strikeNow(bell.number, 8)
  }
  return (
    <div className="home">
      <Spine />
      <div className="home__read">
        <section className="hero">
          <h1>Eight bells,<br />one of them silent.</h1>
          <p className="lead">The bells of St Osyth’s have rung over Thornwick since 1602. In the cold spring of 2018 the fifth cracked, and the ring has had a hole in it ever since. We are putting it right, and teaching the town to ring it.</p>
          <div className="ropes" role="group" aria-label="Ring a bell">
            {BELLS.map((b) => (
              <button key={b.number} className={b.number === 5 ? 'rope rope--silent' : 'rope'} onClick={() => pull(b)} aria-label={`Ring bell ${b.number}, ${b.name}`}>
                <span key={last === b ? nudge : 0} className={last === b ? 'rope__line rope__line--pulled' : 'rope__line'}><i /></span>
                <b>{b.number}</b>
              </button>
            ))}
          </div>
          <p className="ropes__said" role="status">
            {last === null && 'Pull a rope. Sound on.'}
            {last?.number === 5 && 'That was Mercy, and that was all she does. Cracked from the lip to the shoulder.'}
            {last && last.number !== 5 && `${last.name}, ${last.weight.replace(/-/g, '–')} in ${last.note}, cast in ${last.cast}. “${last.words}”`}
          </p>
        </section>

        <section className="band">
          <h2>What you are looking at</h2>
          <p>English ringers do not play tunes. A bell this size cannot be hurried, so each one can only swap places with its neighbour, one row at a time. The figures beside this page are a real course called Plain Bob Major: 112 rows, no row repeated, and nobody reads it from a sheet. <span className="is-treble">Red</span> is the lightest bell. <span className="is-bell">Blue</span> is the heaviest.</p>
          <p>By the time you reach the foot of the page it will be back where it began. Ringers call that coming round.</p>
          <Link className="go" to="/methods">Draw another method</Link>
        </section>

        <section className="band band--board">
          <p className="board__top">St Osyth, Thornwick</p>
          <h2 className="board__title">The repair fund</h2>
          <p className="board__sum"><b>{pounds(sum.raised)}</b> raised of {pounds(sum.cost)}</p>
          <ol className="board__bells">
            {BELLS.map((b) => (
              <li key={b.number}><span>{b.name}</span><span className="board__dots" aria-hidden="true" /><span>{b.raised >= b.cost ? 'Paid for' : `${pounds(b.cost - b.raised)} to find`}</span></li>
            ))}
          </ol>
          <Link className="go" to="/appeal">Choose a bell to mend</Link>
        </section>

        <section className="band band--split">
          <div>
            <h2>Try it before you climb the stairs</h2>
            <p>Take one rope in a band of six. We ring the other five, you press a key when it is your turn, and the tower captain tells you the truth about it.</p>
            <Link className="go" to="/practice">Ring with us now</Link>
          </div>
          <div>
            <h2>Tuesdays, half past seven</h2>
            <p>You need no music, no strength and no faith. You need an hour, flat shoes and the ability to count to eight. There are 41 steps and tea at the top.</p>
            <Link className="go" to="/visit">Book a rope</Link>
          </div>
        </section>

        <section className="band">
          <h2>Mercy, in section</h2>
          <div className="mercy">
            <Bell size={1} filled={BELLS[4].raised / BELLS[4].cost} cracked />
            <div>
              <p>Seven hundredweight, cast in 1664 by somebody who did not sign their work. A welder in Lowgate thinks she can be saved. If the weld holds she keeps her voice. If not, the metal is melted and poured again, and the new bell carries the old words.</p>
              <p>{pounds(BELLS[4].raised)} has been given so far, filled in gold.</p>
            </div>
          </div>
        </section>
        <p className="round">12345678<span>That’s all. Stand.</span></p>
      </div>
    </div>
  )
}
