import { useEffect, useRef, useState } from "react";

import {
  ChainProfileSelector,
  type ChainProfile,
  type ChainProfileSelection,
} from "./components/ChainProfileSelector";
import { CompareLevelsToggle } from "./components/CompareLevelsToggle";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { ErrorBanner } from "./components/ErrorBanner";
import { FolderTree } from "./components/FolderTree";
import { MessageInput } from "./components/MessageInput";
import { ModeSelector, type ProductMode } from "./components/ModeSelector";
import { ResultsWall } from "./components/ResultsWall";
import { StatusWall } from "./components/StatusWall";
import { usePipelineStatus } from "./hooks/usePipelineStatus";
import { useSessionId } from "./hooks/useSessionId";
import { useWebSocket } from "./hooks/useWebSocket";
import { buildDrillDownMessage } from "./utils/drillDown";
import "./App.css";

function truncateSessionId(sessionId: string): string {
  return `${sessionId.slice(0, 8)}...`;
}

function App() {
  const sessionId = useSessionId();
  const [selectedMode, setSelectedMode] = useState<ProductMode>("auto");
  const [selectedChainProfile, setSelectedChainProfile] =
    useState<ChainProfileSelection>("default");
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [compareLevels, setCompareLevels] = useState<ChainProfile[]>([
    "L0",
    "L4",
  ]);
  const [activeCompareLevels, setActiveCompareLevels] = useState<
    ChainProfile[]
  >([]);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const {
    connectionState,
    panels,
    lastError,
    cancelNotice,
    isProcessing,
    sendMessage,
    clearError,
    clearCancelNotice,
  } = useWebSocket(sessionId);
  const pipelineStatus = usePipelineStatus(panels, isProcessing);
  const panelsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [panels, selectedFolder]);

  const isConnected = connectionState === "connected";

  const handleSend = (text: string) => {
    if (compareEnabled && compareLevels.length >= 2) {
      setActiveCompareLevels([...compareLevels]);
      for (const level of compareLevels) {
        sendMessage(text, selectedMode, level);
      }
      return;
    }

    const profile =
      selectedChainProfile === "default" ? undefined : selectedChainProfile;
    setActiveCompareLevels([]);
    sendMessage(text, selectedMode, profile);
  };

  const handleSegmentClick = (title: string) => {
    handleSend(buildDrillDownMessage(title));
  };

  const compareLevelSet = new Set(activeCompareLevels);

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__title">
          <h1>TESS Engine</h1>
          <span className="app-header__session" title={sessionId}>
            Session: {truncateSessionId(sessionId)}
          </span>
        </div>
        <div className="app-header__controls">
          <ModeSelector value={selectedMode} onChange={setSelectedMode} />
          <ChainProfileSelector
            value={selectedChainProfile}
            onChange={setSelectedChainProfile}
          />
          <ConnectionStatus state={connectionState} />
        </div>
      </header>

      <div className="app-header__compare">
        <CompareLevelsToggle
          enabled={compareEnabled}
          selectedLevels={compareLevels}
          onEnabledChange={setCompareEnabled}
          onLevelsChange={setCompareLevels}
        />
      </div>

      <StatusWall status={pipelineStatus} />

      <div className="app-body">
        <aside className="app-sidebar">
          <FolderTree
            panels={panels}
            selectedFolder={selectedFolder}
            onSelectFolder={setSelectedFolder}
          />
        </aside>

        <main className="app-main">
          <ResultsWall
            panels={panels}
            selectedFolder={selectedFolder}
            activeCompareLevels={activeCompareLevels}
            compareLevelSet={compareLevelSet}
            isProcessing={isProcessing}
            onFollowUp={handleSend}
            onSegmentClick={handleSegmentClick}
            panelsEndRef={panelsEndRef}
          />
        </main>
      </div>

      <footer className="app-footer">
        {lastError && (
          <ErrorBanner message={lastError} onDismiss={clearError} />
        )}
        {cancelNotice && (
          <div className="cancel-notice" role="status">
            <span>{cancelNotice}</span>
            <button type="button" onClick={clearCancelNotice}>
              Dismiss
            </button>
          </div>
        )}
        <p className="app-footer__hint">
          Sending a new message while processing will cancel the current run.
        </p>
        <MessageInput disabled={!isConnected} onSend={handleSend} />
      </footer>
    </div>
  );
}

export default App;
