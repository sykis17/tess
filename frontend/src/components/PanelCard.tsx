import type { AgentTrace, ContentType } from "../types/panel";
import { formatAgentDisplayName } from "../types/panel";
import { PanelContent } from "./PanelContent";

interface PanelCardProps {
  folderPath: string;
  status: string;
  contentType: ContentType;
  content: string;
  followUpOptions: string[];
  agentsInvolved?: string[];
  agentTraces?: AgentTrace[];
  onFollowUp: (option: string) => void;
}

function formatPipeline(agentsInvolved: string[]): string {
  if (agentsInvolved.length === 0) {
    return "";
  }
  return `via ${agentsInvolved.join(" → ")}`;
}

export function PanelCard({
  folderPath,
  status,
  contentType,
  content,
  followUpOptions,
  agentsInvolved = [],
  agentTraces = [],
  onFollowUp,
}: PanelCardProps) {
  const isProcessing = status === "processing";
  const isCompleted = status === "completed";
  const pipeline = formatPipeline(agentsInvolved);

  return (
    <article className={`panel-card${isProcessing ? " panel-card--processing" : ""}`}>
      <header className="panel-card__header">
        <div className="panel-card__header-main">
          <span className="panel-card__folder">{folderPath}</span>
          {pipeline && (
            <span className="panel-card__pipeline">{pipeline}</span>
          )}
        </div>
        <span className={`panel-card__status panel-card__status--${status}`}>
          {status.replace("_", " ")}
        </span>
      </header>

      {agentsInvolved.length > 0 && (
        <div className="panel-card__agents">
          {agentsInvolved.map((agent) => (
            <span key={agent} className="panel-card__agent-badge">
              {agent}
            </span>
          ))}
        </div>
      )}

      <div className="panel-card__content">
        <PanelContent contentType={contentType} content={content} />
      </div>

      {agentTraces.length > 0 && (
        <details className="panel-card__details">
          <summary className="panel-card__details-summary">Agent details</summary>
          <ul className="panel-card__trace-list">
            {agentTraces.map((trace) => (
              <li key={trace.agent_name} className="panel-card__trace">
                <strong className="panel-card__trace-name">
                  {formatAgentDisplayName(trace.agent_name)}
                </strong>
                <div className="panel-card__trace-inputs">
                  {trace.inputs_seen.map((input) => (
                    <span key={input} className="panel-card__trace-chip">
                      {input}
                    </span>
                  ))}
                </div>
                {trace.task_summary && (
                  <p className="panel-card__trace-task">
                    Task: {trace.task_summary}
                  </p>
                )}
                {trace.output_preview && (
                  <p className="panel-card__trace-preview">
                    {trace.output_preview}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {!isProcessing && isCompleted && followUpOptions.length > 0 && (
        <footer className="panel-card__footer">
          {followUpOptions.map((option) => (
            <button
              key={option}
              type="button"
              className="panel-card__follow-up"
              onClick={() => onFollowUp(option)}
            >
              {option}
            </button>
          ))}
        </footer>
      )}
    </article>
  );
}
