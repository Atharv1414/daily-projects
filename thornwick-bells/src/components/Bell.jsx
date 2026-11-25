/** A bell in section, hung on its wheel. Size follows weight; the crack and the fill follow the facts. */
export default function Bell({ size = 1, filled = 1, cracked = false, swing = false }) {
  const level = 112 - filled * 84
  const id = `fill-${size}-${filled}`.replace(/\./g, '-')
  return (
    <svg className={swing ? 'bell bell--swing' : 'bell'} viewBox="0 0 120 130" style={{ '--size': size }} aria-hidden="true">
      <circle className="bell__wheel" cx="60" cy="24" r="21" />
      <path className="bell__wheel" d="M39 24H81M60 3V45" />
      <g className="bell__body">
        <clipPath id={id}><rect x="0" y={level} width="120" height="120" /></clipPath>
        <rect className="bell__stock" x="34" y="18" width="52" height="11" />
        <path className="bell__metal" d="M47 29h26c6 18 5 47 25 73 3 4 1 8-4 8H26c-5 0-7-4-4-8 20-26 19-55 25-73z" />
        <path className="bell__raised" clipPath={`url(#${id})`} d="M47 29h26c6 18 5 47 25 73 3 4 1 8-4 8H26c-5 0-7-4-4-8 20-26 19-55 25-73z" />
        <path className="bell__rim" d="M28 96h64M44 48h32" />
        <circle className="bell__clapper" cx="60" cy="114" r="8" />
        {cracked && <path className="bell__crack" d="M76 110l-4-14 7-12-6-13 5-10" />}
      </g>
    </svg>
  )
}
