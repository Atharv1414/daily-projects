// A narrowboat side-on, drawn to scale from its length, in its own livery.
// 1 ft = 10 units, so a 69 ft boat is 690 units long and every boat on a page lines up.

export default function Boat({ boat, scale = 'fleet', decorative = false }) {
  const length = boat.length * 10
  const width = scale === 'fleet' ? 720 : length + 40
  const cabinStart = 70
  const cabinEnd = length - 70
  const portholes = Math.floor((cabinEnd - cabinStart - 40) / 55)
  const label = `${boat.name}, a ${boat.length} ft narrowboat`
  const svgProps = decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': label }
  return (
    <svg viewBox={`0 0 ${width} 130`} className="boat" {...svgProps}>
      <line x1="0" x2={width} y1="104" y2="104" className="boat__waterline" />
      <g transform="translate(20 0)">
        {/* Hull with a raked bow on the right and a counter stern on the left. */}
        <path
          d={`M0,62 L${length - 40},62 Q${length},62 ${length + 6},72 L${length - 6},110 L18,110 Q4,108 0,96 Z`}
          fill={boat.livery.hull}
          className="boat__hull"
        />
        <rect x="0" y="64" width={length - 30} height="6" fill={boat.livery.band} />
        {/* Cabin and roof. */}
        <rect x={cabinStart} y="30" width={cabinEnd - cabinStart} height="34" fill={boat.livery.hull} className="boat__cabin" />
        <rect x={cabinStart - 4} y="24" width={cabinEnd - cabinStart + 8} height="8" rx="3" fill={boat.livery.roof} />
        <rect x={cabinStart + 8} y="34" width={cabinEnd - cabinStart - 16} height="4" fill={boat.livery.band} />
        {Array.from({ length: portholes }, (_, i) => (
          <circle key={i} cx={cabinStart + 50 + i * 55} cy="48" r="8" className="boat__porthole" stroke={boat.livery.band} />
        ))}
        {/* Chimney, tiller and the name on the cabin side. */}
        <rect x={cabinStart + 26} y="8" width="8" height="18" className="boat__metal" />
        <path d="M30,62 L30,40 L-6,30" className="boat__tiller" />
        <text x={cabinEnd - 16} y="60" textAnchor="end" className="boat__name" fill={boat.livery.band}>
          {boat.name}
        </text>
      </g>
    </svg>
  )
}
