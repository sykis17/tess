import { D } from './palette'

/** Vendor metrics pull (rejected) vs self-report probe (chosen). */
export function SelfReportDiagram() {
  return (
    <svg
      viewBox="0 0 720 260"
      role="img"
      aria-label="Rejected vendor metrics pull versus chosen self-report health probe"
    >
      {/* Rejected path */}
      <g className="arch-draw">
        <text
          x="170"
          y="28"
          textAnchor="middle"
          fill={D.bad}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="11"
          fontWeight="500"
        >
          REJECTED
        </text>
        <rect
          x="40"
          y="44"
          width="260"
          height="180"
          rx="4"
          fill={D.bg}
          stroke={D.bad}
          strokeWidth="1.5"
          strokeDasharray="5 4"
          opacity="0.9"
        />
        <text
          x="170"
          y="78"
          textAnchor="middle"
          fill={D.muted}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="13"
          fontWeight="600"
        >
          Vendor metrics pull
        </text>
        <text
          x="170"
          y="108"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="10"
        >
          CloudWatch · GCP Mon · …
        </text>
        <text
          x="170"
          y="140"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="11"
        >
          credentials per cloud
        </text>
        <text
          x="170"
          y="162"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="11"
        >
          inconsistent semantics
        </text>
        <line x1="70" y1="50" x2="230" y2="210" stroke={D.bad} strokeWidth="2" opacity="0.5" />
      </g>

      {/* Chosen path */}
      <g className="arch-draw arch-draw-delay-1">
        <text
          x="530"
          y="28"
          textAnchor="middle"
          fill={D.ok}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="11"
          fontWeight="500"
        >
          CHOSEN
        </text>
        <rect
          x="400"
          y="44"
          width="280"
          height="180"
          rx="4"
          fill={D.surface}
          stroke={D.ok}
          strokeWidth="1.5"
        />
        <text
          x="540"
          y="78"
          textAnchor="middle"
          fill={D.ink}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="13"
          fontWeight="600"
        >
          Self-report probe
        </text>
        <rect
          x="455"
          y="100"
          width="170"
          height="28"
          rx="3"
          fill={D.bg}
          stroke={D.accent}
          strokeWidth="1"
        />
        <text
          x="540"
          y="118"
          textAnchor="middle"
          fill={D.accent}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="12"
        >
          GET /health
        </text>
        <text
          x="540"
          y="158"
          textAnchor="middle"
          fill={D.muted}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="10"
        >
          status · redis · cpu · mem
        </text>
        <text
          x="540"
          y="188"
          textAnchor="middle"
          fill={D.faint}
          fontFamily="IBM Plex Sans, sans-serif"
          fontSize="11"
        >
          same contract on every stack
        </text>
      </g>
    </svg>
  )
}
