import { formatStageLabel, type PipelineStatus } from "../hooks/usePipelineStatus";
interface StatusWallProps {
  status: PipelineStatus;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

export function StatusWall({ status }: StatusWallProps) {
  if (!status.visible) {
    return null;
  }

  const currentIndex = status.currentStage
    ? status.predictedSteps.indexOf(
        status.currentStage as (typeof status.predictedSteps)[number],
      )
    : -1;

  return (
    <div className="status-wall" role="status" aria-live="polite">
      <div className="status-wall__steps">
        {status.predictedSteps.map((step, index) => {
          const isCurrent = step === status.currentStage;
          const isPast = currentIndex >= 0 && index < currentIndex;
          return (
            <span
              key={step}
              className={`status-wall__step${
                isCurrent ? " status-wall__step--current" : ""
              }${isPast ? " status-wall__step--past" : ""}`}
            >
              {formatStageLabel(step)}
            </span>
          );
        })}
      </div>

      {status.activeAgents.length > 0 && (
        <div className="status-wall__agents">
          {status.activeAgents.map((agent) => (
            <span key={agent} className="status-wall__agent-badge">
              {agent}
            </span>
          ))}
        </div>
      )}

      <div className="status-wall__meta">
        <span className="status-wall__elapsed">{formatElapsed(status.elapsedMs)}</span>
        {status.subtitle && (
          <span className="status-wall__subtitle">{status.subtitle}</span>
        )}
      </div>
    </div>
  );
}
