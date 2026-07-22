import { D } from './palette'

/** Timeline of three onboarding incidents. */
export function SagaDiagram() {
  const beats = [
    { x: 60, tag: 'access', title: 'Stale SG IPs', cloud: 'AWS' },
    { x: 280, tag: 'capacity', title: 't3.micro OOM', cloud: 'AWS' },
    { x: 500, tag: 'identity', title: 'ADC + perms', cloud: 'GCP' },
  ]

  return (
    <svg
      viewBox="0 0 720 200"
      role="img"
      aria-label="Timeline of three onboarding incidents: security group, OOM, and GCP credentials"
    >
      <line
        className="arch-draw"
        x1="80"
        y1="100"
        x2="640"
        y2="100"
        stroke={D.rule}
        strokeWidth="2"
      />

      {beats.map((b, i) => (
        <g key={b.title} className={`arch-draw arch-draw-delay-${i + 1}`}>
          <circle cx={b.x + 80} cy="100" r="8" fill={D.bg} stroke={D.accent} strokeWidth="2" />
          <text
            x={b.x + 80}
            y="48"
            textAnchor="middle"
            fill={D.warn}
            fontFamily="IBM Plex Mono, monospace"
            fontSize="10"
            letterSpacing="0.06em"
          >
            {b.tag.toUpperCase()}
          </text>
          <text
            x={b.x + 80}
            y="72"
            textAnchor="middle"
            fill={D.ink}
            fontFamily="IBM Plex Sans, sans-serif"
            fontSize="13"
            fontWeight="600"
          >
            {b.title}
          </text>
          <text
            x={b.x + 80}
            y="140"
            textAnchor="middle"
            fill={D.muted}
            fontFamily="IBM Plex Mono, monospace"
            fontSize="11"
          >
            {b.cloud}
          </text>
        </g>
      ))}
    </svg>
  )
}
