import { D } from './palette'

/** Registry → thin adapters (enrichment only); prober owns /health. */
export function AdapterDiagram() {
  return (
    <svg
      viewBox="0 0 720 300"
      role="img"
      aria-label="Cloud adapter registry enriches metadata while the prober owns health"
    >
      <g className="arch-draw">
        <rect
          x="40"
          y="20"
          width="160"
          height="48"
          rx="4"
          fill={D.surface}
          stroke={D.accent}
          strokeWidth="1.5"
        />
        <text
          x="120"
          y="48"
          textAnchor="middle"
          fill={D.ink}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="13"
          fontWeight="600"
        >
          get_adapter()
        </text>
      </g>

      {/* Adapters */}
      {[
        { y: 20, label: 'HetznerAdapter' },
        { y: 80, label: 'AwsAdapter' },
        { y: 140, label: 'GcpAdapter' },
        { y: 200, label: 'CustomerAdapter' },
      ].map((a, i) => (
        <g key={a.label} className={`arch-draw arch-draw-delay-${Math.min(i + 1, 3)}`}>
          <line
            x1="200"
            y1="44"
            x2="280"
            y2={a.y + 24}
            stroke={D.rule}
            strokeWidth="1.5"
          />
          <rect
            x="280"
            y={a.y}
            width="180"
            height="48"
            rx="4"
            fill={D.bg}
            stroke={D.rule}
            strokeWidth="1.5"
          />
          <text
            x="370"
            y={a.y + 22}
            textAnchor="middle"
            fill={D.ink}
            fontFamily="IBM Plex Mono, monospace"
            fontSize="11"
          >
            {a.label}
          </text>
          <text
            x="370"
            y={a.y + 38}
            textAnchor="middle"
            fill={D.faint}
            fontFamily="IBM Plex Sans, sans-serif"
            fontSize="10"
          >
            enrichment stub
          </text>
        </g>
      ))}

      {/* Prober owns health */}
      <g className="arch-draw arch-draw-delay-2">
        <rect
          x="520"
          y="80"
          width="160"
          height="100"
          rx="4"
          fill={D.surface}
          stroke={D.ok}
          strokeWidth="2"
        />
        <text
          x="600"
          y="115"
          textAnchor="middle"
          fill={D.ok}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="13"
          fontWeight="600"
        >
          Prober
        </text>
        <text
          x="600"
          y="138"
          textAnchor="middle"
          fill={D.muted}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="11"
        >
          GET /health
        </text>
        <text
          x="600"
          y="160"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="10"
        >
          source of truth
        </text>
      </g>

      <g className="arch-draw arch-draw-delay-3">
        <line
          x1="460"
          y1="130"
          x2="520"
          y2="130"
          stroke={D.ok}
          strokeWidth="2"
        />
        <polygon points="520,130 510,125 510,135" fill={D.ok} />
        <text
          x="490"
          y="270"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="11"
        >
          Adapters do not score health
        </text>
      </g>
    </svg>
  )
}
