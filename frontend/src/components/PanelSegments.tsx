import type { ContentType, PanelSegment } from "../types/panel";
import { PanelContent } from "./PanelContent";

interface PanelSegmentsProps {
  segments: PanelSegment[];
  contentType: ContentType;
  contentFormat?: string | null;
  onSegmentClick?: (title: string, segment: PanelSegment) => void;
}

export function PanelSegments({
  segments,
  contentType,
  contentFormat,
  onSegmentClick,
}: PanelSegmentsProps) {
  return (
    <div className="panel-segments">
      {segments.map((segment, index) => (
        <section
          key={`${segment.title}-${index}`}
          className="panel-segments__segment"
        >
          <header className="panel-segments__header">
            {onSegmentClick ? (
              <button
                type="button"
                className="panel-segments__title-btn"
                onClick={() => onSegmentClick(segment.title, segment)}
                title={`Tell me more about ${segment.title}`}
              >
                {segment.title}
              </button>
            ) : (
              <h3 className="panel-segments__title">{segment.title}</h3>
            )}
            {segment.pov && (
              <span className="panel-segments__pov-badge">{segment.pov}</span>
            )}
          </header>
          <div className="panel-segments__content">
            <PanelContent
              contentType={contentType}
              content={segment.content}
              contentFormat={contentFormat}
            />
          </div>
        </section>
      ))}
    </div>
  );
}
