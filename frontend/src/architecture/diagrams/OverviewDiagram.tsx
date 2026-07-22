import { D } from './palette'

/** Control plane probes /health on each cloud stack → score → failover. */
export function OverviewDiagram() {
  return (
    <svg
      viewBox="0 0 720 280"
      role="img"
      aria-label="Control plane probing health endpoints on Hetzner, AWS, and GCP"
    >
      <rect
        className="arch-draw"
        x="250"
        y="16"
        width="220"
        height="64"
        rx="4"
        fill={D.surface}
        stroke={D.accent}
        strokeWidth="1.5"
      />
      <text
        className="arch-draw"
        x="360"
        y="42"
        textAnchor="middle"
        fill={D.ink}
        fontFamily="IBM Plex Sans, sans-serif"
        fontSize="13"
        fontWeight="600"
      >
        Control plane
      </text>
      <text
        className="arch-draw"
        x="360"
        y="60"
        textAnchor="middle"
        fill={D.muted}
        fontFamily="IBM Plex Mono, monospace"
        fontSize="10"
      >
        prober · score · failover
      </text>

      {/* Stack boxes */}
      {[
        { x: 40, label: 'Hetzner', sub: 'active' },
        { x: 260, label: 'AWS', sub: 'standby' },
        { x: 480, label: 'GCP', sub: 'standby' },
      ].map((s, i) => (
        <g key={s.label} className={`arch-draw arch-draw-delay-${i + 1}`}>
          <rect
            x={s.x}
            y="160"
            width="200"
            height="88"
            rx="4"
            fill={D.bg}
            stroke={D.rule}
            strokeWidth="1.5"
          />
          <text
            x={s.x + 100}
            y="188"
            textAnchor="middle"
            fill={D.ink}
            fontFamily="IBM Plex Sans, sans-serif"
            fontSize="14"
            fontWeight="600"
          >
            {s.label}
          </text>
          <text
            x={s.x + 100}
            y="208"
            textAnchor="middle"
            fill={D.faint}
            fontFamily="IBM Plex Mono, monospace"
            fontSize="10"
          >
            {s.sub}
          </text>
          <rect
            x={s.x + 36}
            y="220"
            width="128"
            height="18"
            rx="2"
            fill={D.surface}
            stroke={D.ok}
            strokeWidth="1"
          />
          <text
            x={s.x + 100}
            y="233"
            textAnchor="middle"
            fill={D.ok}
            fontFamily="IBM Plex Mono, monospace"
            fontSize="9"
          >
            GET /health
          </text>
        </g>
      ))}

      {/* Probe arrows down */}
      {[140, 360, 580].map((x, i) => (
        <g key={x} className={`arch-draw arch-draw-delay-${i + 1}`}>
          <line
            x1={x}
            y1="80"
            x2={x}
            y2="155"
            stroke={D.accent}
            strokeWidth="1.5"
            strokeDasharray="4 3"
          />
          <polygon points={`${x},155 ${x - 5},146 ${x + 5},146`} fill={D.accent} />
        </g>
      ))}
    </svg>
  )
}
