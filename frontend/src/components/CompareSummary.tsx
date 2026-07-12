import type { Panel } from "../types/panel";
import type { ChainProfile } from "./ChainProfileSelector";

interface CompareSummaryProps {
  panels: Panel[];
  levels: ChainProfile[];
}

export function CompareSummary({ panels, levels }: CompareSummaryProps) {
  const completed = panels.filter(
    (panel) =>
      panel.status === "completed" &&
      panel.output_level &&
      levels.includes(panel.output_level as ChainProfile),
  );

  if (completed.length < 2) {
    return null;
  }

  return (
    <details className="compare-summary">
      <summary className="compare-summary__title">
        Compare summary ({completed.length} levels)
      </summary>
      <ul className="compare-summary__list">
        {completed.map((panel) => (
          <li key={panel.panel_id} className="compare-summary__item">
            <strong>{panel.output_level}</strong>
            {" — "}
            {panel.agents_involved?.length ?? 0} pipeline steps,{" "}
            {panel.agent_traces?.length ?? 0} agent traces,{" "}
            {panel.content.length} chars
          </li>
        ))}
      </ul>
    </details>
  );
}
