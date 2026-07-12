import { useEffect, useRef } from "react";

import { ConnectionStatus } from "./components/ConnectionStatus";
import { ErrorBanner } from "./components/ErrorBanner";
import { MessageInput } from "./components/MessageInput";
import { PanelCard } from "./components/PanelCard";
import { useSessionId } from "./hooks/useSessionId";
import { useWebSocket } from "./hooks/useWebSocket";
import "./App.css";

function truncateSessionId(sessionId: string): string {
  return `${sessionId.slice(0, 8)}...`;
}

function App() {
  const sessionId = useSessionId();
  const {
    connectionState,
    panels,
    lastError,
    isProcessing,
    sendMessage,
    clearError,
  } = useWebSocket(sessionId);
  const panelsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [panels]);

  const isConnected = connectionState === "connected";

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__title">
          <h1>TESS Engine</h1>
          <span className="app-header__session" title={sessionId}>
            Session: {truncateSessionId(sessionId)}
          </span>
        </div>
        <ConnectionStatus state={connectionState} />
      </header>

      <main className="app-main">
        {isProcessing && (
          <p className="app-main__processing">
            TESS is thinking… (first Ollama response can take up to a minute)
          </p>
        )}
        {panels.length === 0 && !isProcessing ? (
          <p className="app-main__empty">
            No panels yet. Send a message to start processing.
          </p>
        ) : (
          <div className="panel-list">
            {panels.map((panel) => (
              <PanelCard
                key={panel.panel_id}
                folderPath={panel.folder_path}
                status={panel.status}
                contentType={panel.content_type}
                content={panel.content}
                followUpOptions={panel.follow_up_options}
                agentsInvolved={panel.agents_involved}
                agentTraces={panel.agent_traces}
                povSources={panel.pov_sources}
                onFollowUp={sendMessage}
              />
            ))}
            <div ref={panelsEndRef} />
          </div>
        )}
      </main>

      <footer className="app-footer">
        {lastError && (
          <ErrorBanner message={lastError} onDismiss={clearError} />
        )}
        <MessageInput
          disabled={!isConnected || isProcessing}
          onSend={sendMessage}
        />
      </footer>
    </div>
  );
}

export default App;
