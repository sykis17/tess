import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

import type { ContentType } from "../types/panel";

interface PanelContentProps {
  contentType: ContentType;
  content: string;
}

function isMediaUrl(content: string): boolean {
  return content.startsWith("http://") || content.startsWith("https://");
}

function isImageSource(content: string): boolean {
  return (
    content.startsWith("http://") ||
    content.startsWith("https://") ||
    content.startsWith("data:")
  );
}

function MarkdownFallback({ content }: { content: string }) {
  return (
    <div className="panel-content panel-content--markdown">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}

export function PanelContent({ contentType, content }: PanelContentProps) {
  switch (contentType) {
    case "markdown":
      return <MarkdownFallback content={content} />;

    case "code":
      return (
        <div className="panel-content panel-content--code">
          <SyntaxHighlighter language="text" style={oneDark}>
            {content}
          </SyntaxHighlighter>
        </div>
      );

    case "image":
      if (isImageSource(content)) {
        return (
          <div className="panel-content panel-content--image">
            <img src={content} alt="Panel content" />
          </div>
        );
      }

      return (
        <div className="panel-content panel-content--image-placeholder">
          <p>Image content is not a valid URL or data URI.</p>
        </div>
      );

    case "video":
      if (isMediaUrl(content)) {
        return (
          <div className="panel-content panel-content--video">
            <video controls src={content}>
              Your browser does not support the video tag.
            </video>
          </div>
        );
      }
      return <MarkdownFallback content={content} />;

    case "audio":
      if (isMediaUrl(content)) {
        return (
          <div className="panel-content panel-content--audio">
            <audio controls src={content}>
              Your browser does not support the audio tag.
            </audio>
          </div>
        );
      }
      return <MarkdownFallback content={content} />;

    default:
      return (
        <div className="panel-content">
          <p>{content}</p>
        </div>
      );
  }
}
