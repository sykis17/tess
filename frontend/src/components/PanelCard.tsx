import type { AgentTrace, ContentType, PanelSegment } from "../types/panel";
import { formatAgentDisplayName } from "../types/panel";
import { formatProductModeDisplayName } from "./ModeSelector";
import { formatChainProfileDisplayName } from "./ChainProfileSelector";
import { PanelContent } from "./PanelContent";
import { PanelSegments } from "./PanelSegments";

interface PanelCardProps {
  folderPath: string;
  status: string;
  contentType: ContentType;
  content: string;
  contentFormat?: string | null;
  followUpOptions: string[];
  followUpKinds?: string[];
  agentsInvolved?: string[];
  agentTraces?: AgentTrace[];
  povSources?: string[];
  povSegments?: PanelSegment[];
  productMode?: string;
  outputLevel?: string;
  isComparePanel?: boolean;
  isStreaming?: boolean;
  onFollowUp: (option: string) => void;
  onSegmentClick?: (title: string, segment: PanelSegment) => void;
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
  contentFormat,
  followUpOptions,
  followUpKinds = [],
  agentsInvolved = [],
  agentTraces = [],
  povSources = [],
  povSegments = [],
  productMode,
  outputLevel,
  isComparePanel = false,
  isStreaming = false,
  onFollowUp,
  onSegmentClick,
}: PanelCardProps) {
  const isProcessing = status === "processing";
  const isCompleted = status === "completed";
  const pipeline = formatPipeline(agentsInvolved);

  return (
    <article
      className={`panel-card${isProcessing ? " panel-card--processing" : ""}${
        isStreaming ? " panel-card--streaming" : ""
      }${isComparePanel ? " panel-card--compare" : ""}`}
    >
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

      {(productMode && productMode !== "auto") || outputLevel ? (
        <div className="panel-card__mode">
          {outputLevel && (
            <span className="panel-card__level-badge" title="Output level">
              {outputLevel}
              {formatChainProfileDisplayName(outputLevel) !== outputLevel
                ? ` — ${formatChainProfileDisplayName(outputLevel)}`
                : ""}
            </span>
          )}
          {productMode && productMode !== "auto" && (
            <span className="panel-card__mode-badge">
              {formatProductModeDisplayName(productMode)}
            </span>
          )}
        </div>
      ) : null}

      {povSources.length > 0 && (
        <div className="panel-card__pov-sources">
          {povSources.map((pov) => (
            <span key={pov} className="panel-card__pov-badge">
              {pov}
            </span>
          ))}
        </div>
      )}

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
        {povSegments.length > 0 ? (
          <PanelSegments
            segments={povSegments}
            contentType={contentType}
            contentFormat={contentFormat}
            onSegmentClick={onSegmentClick}
          />
        ) : (
          <PanelContent
            contentType={contentType}
            content={content}
            contentFormat={contentFormat}
          />
        )}
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
          {followUpOptions.map((option, index) => {
            const kind = followUpKinds[index];
            const kindClass = kind
              ? ` panel-card__follow-up--${kind}`
              : "";
            return (
              <button
                key={option}
                type="button"
                className={`panel-card__follow-up${kindClass}`}
                onClick={() => onFollowUp(option)}
              >
                {option}
              </button>
            );
          })}
        </footer>
      )}
    </article>
  );
}
