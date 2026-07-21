import { useCallback, useEffect, useRef, useState } from "react";

import {
  isCancelledMessage,
  isPanel,
  isProviderChangedMessage,
  isWorkerError,
  type Panel,
} from "../types/panel";

export type ConnectionState =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ?? "ws://127.0.0.1:8000";

function httpBaseFromWs(wsBase: string): string {
  if (wsBase.startsWith("wss://")) {
    return `https://${wsBase.slice("wss://".length)}`;
  }
  if (wsBase.startsWith("ws://")) {
    return `http://${wsBase.slice("ws://".length)}`;
  }
  return wsBase;
}

const PROCESSING_TIMEOUT_MS = 900_000;
const PROCESSING_TIMEOUT_MINUTES = PROCESSING_TIMEOUT_MS / 60_000;

function buildPayload(
  text: string,
  productMode: string,
  chainProfile?: string,
): string {
  const needsJson = productMode !== "auto" || chainProfile !== undefined;
  if (!needsJson) {
    return text;
  }
  const envelope: Record<string, string> = { text };
  if (productMode !== "auto") {
    envelope.product_mode = productMode;
  }
  if (chainProfile !== undefined) {
    envelope.chain_profile = chainProfile;
  }
  return JSON.stringify(envelope);
}

function mergePanelUpdate(previous: Panel, incoming: Panel): Panel {
  if (incoming.is_streaming) {
    return {
      ...incoming,
      content: previous.content + incoming.content,
      pov_sources:
        incoming.pov_sources && incoming.pov_sources.length > 0
          ? incoming.pov_sources
          : previous.pov_sources,
      product_mode: incoming.product_mode ?? previous.product_mode,
      output_level: incoming.output_level ?? previous.output_level,
      pipeline_stage: incoming.pipeline_stage ?? previous.pipeline_stage,
      pov_segments:
        incoming.pov_segments && incoming.pov_segments.length > 0
          ? incoming.pov_segments
          : previous.pov_segments,
      is_streaming: true,
    };
  }

  return {
    ...incoming,
    pov_sources:
      incoming.pov_sources && incoming.pov_sources.length > 0
        ? incoming.pov_sources
        : previous.pov_sources,
    product_mode: incoming.product_mode ?? previous.product_mode,
    output_level: incoming.output_level ?? previous.output_level,
    pipeline_stage: incoming.pipeline_stage ?? previous.pipeline_stage,
    pov_segments:
      incoming.pov_segments && incoming.pov_segments.length > 0
        ? incoming.pov_segments
        : previous.pov_segments,
    is_streaming: false,
  };
}

export function useWebSocket(sessionId: string) {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("connecting");
  const [panels, setPanels] = useState<Panel[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [cancelNotice, setCancelNotice] = useState<string | null>(null);
  const [providerNotice, setProviderNotice] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pendingCountRef = useRef(0);
  const wasProcessingOnCloseRef = useRef(false);

  const decrementPending = useCallback(() => {
    pendingCountRef.current = Math.max(0, pendingCountRef.current - 1);
    if (pendingCountRef.current === 0) {
      setIsProcessing(false);
    }
  }, []);

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
          setLastError(
            data.message?.trim() ||
              "An unexpected error occurred while processing your request.",
          );
          decrementPending();
          return;
        }

        if (isCancelledMessage(data)) {
          setCancelNotice(
            data.message?.trim() ||
              "Previous request cancelled — processing your new message.",
          );
          decrementPending();
          return;
        }

        if (isProviderChangedMessage(data)) {
          setProviderNotice(
            data.message?.trim() ||
              "Provider changed — in-flight answer was interrupted. Reconnect and resubmit if needed.",
          );
          pendingCountRef.current = 0;
          setIsProcessing(false);
          if (data.ws_base_url && data.ws_base_url !== WS_BASE_URL) {
            setProviderNotice(
              `${data.message} New endpoint: ${data.ws_base_url}`,
            );
          }
          return;
        }

        if (isPanel(data)) {
          if (data.status === "completed") {
            decrementPending();
          }

          setPanels((previous) => {
            const existingIndex = previous.findIndex(
              (panel) => panel.panel_id === data.panel_id,
            );

            if (existingIndex >= 0) {
              const updated = [...previous];
              updated[existingIndex] = mergePanelUpdate(
                previous[existingIndex],
                data,
              );
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
      wasProcessingOnCloseRef.current = pendingCountRef.current > 0;
      setConnectionState((current) =>
        current === "error" ? "error" : "disconnected",
      );
      if (wasProcessingOnCloseRef.current) {
        pendingCountRef.current = 0;
        setIsProcessing(false);
        void (async () => {
          try {
            const res = await fetch(
              `${httpBaseFromWs(WS_BASE_URL)}/ops/routing/notice`,
            );
            if (!res.ok) {
              setProviderNotice(
                "Connection lost while processing. The answer may have been interrupted — please resubmit.",
              );
              return;
            }
            const payload = (await res.json()) as {
              ws_base_url?: string | null;
              sessions_dropped_last?: number;
            };
            const activeWs = payload.ws_base_url;
            const dropped = payload.sessions_dropped_last ?? 0;
            if (dropped > 0 || (activeWs && activeWs !== WS_BASE_URL)) {
              setProviderNotice(
                "Provider changed — in-flight answer was interrupted. Reconnect and resubmit if needed.",
              );
            } else {
              setProviderNotice(
                "Connection lost while processing. Please resubmit if your answer did not finish.",
              );
            }
          } catch {
            setProviderNotice(
              "Connection lost while processing. Please resubmit if your answer did not finish.",
            );
          }
        })();
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [decrementPending, sessionId]);

  useEffect(() => {
    if (!isProcessing) {
      return;
    }

    const timer = window.setTimeout(() => {
      pendingCountRef.current = 0;
      setIsProcessing(false);
      setLastError(
        `No response received after ${PROCESSING_TIMEOUT_MINUTES} minutes. The server may still be processing a multi-agent request — please try again or use a simpler prompt.`,
      );
    }, PROCESSING_TIMEOUT_MS);

    return () => window.clearTimeout(timer);
  }, [isProcessing]);

  const sendMessage = useCallback(
    (text: string, productMode?: string, chainProfile?: string) => {
      const ws = wsRef.current;
      if (ws?.readyState === WebSocket.OPEN) {
        pendingCountRef.current += 1;
        setIsProcessing(true);
        setLastError(null);
        setCancelNotice(null);
        const mode = productMode ?? "auto";
        ws.send(buildPayload(text, mode, chainProfile));
      }
    },
    [],
  );

  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  const clearCancelNotice = useCallback(() => {
    setCancelNotice(null);
  }, []);

  const clearProviderNotice = useCallback(() => {
    setProviderNotice(null);
  }, []);

  return {
    connectionState,
    panels,
    lastError,
    cancelNotice,
    providerNotice,
    isProcessing,
    sendMessage,
    clearError,
    clearCancelNotice,
    clearProviderNotice,
  };
}

