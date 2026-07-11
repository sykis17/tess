import { useCallback, useEffect, useRef, useState } from "react";

import { isPanel, isWorkerError, type Panel } from "../types/panel";

export type ConnectionState =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ?? "ws://127.0.0.1:8000";

const PROCESSING_TIMEOUT_MS = 420_000;

export function useWebSocket(sessionId: string) {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("connecting");
  const [panels, setPanels] = useState<Panel[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const url = `${WS_BASE_URL}/ws/${sessionId}`;
    setConnectionState("connecting");

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionState("connected");
    };

    ws.onmessage = (event) => {
      try {
        const data: unknown = JSON.parse(event.data as string);

        if (isWorkerError(data)) {
          setLastError(data.message);
          setIsProcessing(false);
          return;
        }

        if (isPanel(data)) {
          if (data.status === "completed") {
            setIsProcessing(false);
          }

          setPanels((previous) => {
            const existingIndex = previous.findIndex(
              (panel) => panel.panel_id === data.panel_id,
            );

            if (existingIndex >= 0) {
              const updated = [...previous];
              updated[existingIndex] = data;
              return updated;
            }

            return [...previous, data];
          });
        }
      } catch {
        setLastError("Received invalid JSON from server.");
      }
    };

    ws.onerror = () => {
      setConnectionState("error");
    };

    ws.onclose = () => {
      setConnectionState((current) =>
        current === "error" ? "error" : "disconnected",
      );
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!isProcessing) {
      return;
    }

    const timer = window.setTimeout(() => {
      setIsProcessing(false);
      setLastError(
        "No response received after 5 minutes. The server may be out of memory or still loading the model.",
      );
    }, PROCESSING_TIMEOUT_MS);

    return () => window.clearTimeout(timer);
  }, [isProcessing]);

  const sendMessage = useCallback((text: string) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      setIsProcessing(true);
      setLastError(null);
      ws.send(text);
    }
  }, []);

  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  return {
    connectionState,
    panels,
    lastError,
    isProcessing,
    sendMessage,
    clearError,
  };
}
