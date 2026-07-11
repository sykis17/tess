import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

import type { ContentType } from "../types/panel";

interface PanelContentProps {
  contentType: ContentType;
  content: string;
}

function isImageSource(content: string): boolean {
  return (
    content.startsWith("http://") ||
    content.startsWith("https://") ||
    content.startsWith("data:")
  );
}

export function PanelContent({ contentType, content }: PanelContentProps) {
  switch (contentType) {
    case "markdown":
      return (
        <div className="panel-content panel-content--markdown">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      );

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

    default:
      return (
        <div className="panel-content">
          <p>{content}</p>
        </div>
      );
  }
}
