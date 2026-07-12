import type { RefObject } from "react";

import type { ChainProfile } from "./ChainProfileSelector";
import type { Panel, PanelSegment } from "../types/panel";
import { filterWallPanels, panelMatchesFolder } from "../utils/panelFilters";
import { CompareSummary } from "./CompareSummary";
import { PanelCard } from "./PanelCard";

interface ResultsWallProps {
  panels: Panel[];
  selectedFolder: string | null;
  activeCompareLevels: ChainProfile[];
  compareLevelSet: Set<ChainProfile>;
  isProcessing: boolean;
  onFollowUp: (text: string) => void;
  onSegmentClick?: (title: string, segment: PanelSegment) => void;
  panelsEndRef: RefObject<HTMLDivElement | null>;
}

export function ResultsWall({
  panels,
  selectedFolder,
  activeCompareLevels,
  compareLevelSet,
  isProcessing,
  onFollowUp,
  onSegmentClick,
  panelsEndRef,
}: ResultsWallProps) {
  const wallPanels = filterWallPanels(panels).filter((panel) =>
    panelMatchesFolder(panel, selectedFolder),
  );

  return (
    <div className="results-wall">
      {activeCompareLevels.length >= 2 && (
        <CompareSummary panels={panels} levels={activeCompareLevels} />
      )}

      {wallPanels.length === 0 && !isProcessing ? (
        <p className="results-wall__empty">
          {selectedFolder
            ? "No panels in this folder yet."
            : "No panels yet. Send a message to start processing."}
        </p>
      ) : (
        <div className="panel-list">
          {wallPanels.map((panel) => (
            <PanelCard
              key={panel.panel_id}
              folderPath={panel.folder_path}
              status={panel.status}
              contentType={panel.content_type}
              content={panel.content}
              contentFormat={panel.content_format}
              followUpOptions={panel.follow_up_options}
              followUpKinds={panel.follow_up_kinds}
              agentsInvolved={panel.agents_involved}
              agentTraces={panel.agent_traces}
              povSources={panel.pov_sources}
              povSegments={panel.pov_segments}
              productMode={panel.product_mode}
              outputLevel={panel.output_level}
              isComparePanel={
                panel.output_level !== undefined &&
                compareLevelSet.has(panel.output_level as ChainProfile)
              }
              isStreaming={panel.is_streaming === true && panel.status === "processing"}
              onFollowUp={onFollowUp}
              onSegmentClick={onSegmentClick}
            />
          ))}
          <div ref={panelsEndRef} />
        </div>
      )}
    </div>
  );
}
