import type { ContentType } from "../types/panel";
import { PanelContent } from "./PanelContent";

interface PanelCardProps {
  folderPath: string;
  status: string;
  contentType: ContentType;
  content: string;
  followUpOptions: string[];
  onFollowUp: (option: string) => void;
}

export function PanelCard({
  folderPath,
  status,
  contentType,
  content,
  followUpOptions,
  onFollowUp,
}: PanelCardProps) {
  return (
    <article className="panel-card">
      <header className="panel-card__header">
        <span className="panel-card__folder">{folderPath}</span>
        <span className={`panel-card__status panel-card__status--${status}`}>
          {status.replace("_", " ")}
        </span>
      </header>

      <div className="panel-card__content">
        <PanelContent contentType={contentType} content={content} />
      </div>

      {followUpOptions.length > 0 && (
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
