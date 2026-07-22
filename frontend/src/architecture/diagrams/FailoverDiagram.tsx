import { D } from './palette'

/** Consecutive failure strip: OK → 1 → 2 → 3 → switch, with score floor. */
export function FailoverDiagram() {
  const steps = [
    { label: 'OK', sub: 'score ≥ 40', fill: D.ok },
    { label: '1 fail', sub: 'count++', fill: D.warn },
    { label: '2 fail', sub: 'count++', fill: D.warn },
    { label: '3 fail', sub: 'threshold', fill: D.bad },
    { label: 'Switch', sub: 'best standby', fill: D.accent },
  ]

  return (
    <svg
      viewBox="0 0 720 220"
      role="img"
      aria-label="Failover requires three consecutive failures before switching providers"
    >
      {steps.map((s, i) => {
        const x = 28 + i * 138
        return (
          <g key={s.label} className={`arch-draw${i > 0 ? ` arch-draw-delay-${Math.min(i, 3)}` : ''}`}>
            {i > 0 && (
              <line
                x1={x - 18}
                y1="90"
                x2={x + 2}
                y2="90"
                stroke={D.rule}
                strokeWidth="2"
              />
            )}
            <rect
              x={x}
              y="48"
              width="110"
              height="84"
              rx="4"
              fill={D.bg}
              stroke={s.fill}
              strokeWidth="1.5"
            />
            <text
              x={x + 55}
              y="82"
              textAnchor="middle"
              fill={D.ink}
              fontFamily="IBM Plex Sans, sans-serif"
              fontSize="14"
              fontWeight="600"
            >
              {s.label}
            </text>
            <text
              x={x + 55}
              y="106"
              textAnchor="middle"
              fill={D.muted}
              fontFamily="IBM Plex Mono, monospace"
              fontSize="10"
            >
              {s.sub}
            </text>
          </g>
        )
      })}

      <g className="arch-draw arch-draw-delay-2">
        <text
          x="360"
          y="180"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="12"
        >
          Single-probe flaps rejected — recovery needs 2 consecutive successes
        </text>
      </g>
    </svg>
  )
}
