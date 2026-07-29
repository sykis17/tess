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

interface RoutingNotice {
  ws_base_url?: string | null;
  last_failover_at?: string | null;
}

// Disconnect classification mirrored in tests/test_ws_disconnect_classify.py
// (the frontend has no test runner) — change BOTH together. A disconnect is a
// provider failover ONLY when the server-authored last_failover_at CHANGED
// between socket open and close, compared as an opaque string (never parsed,
// never compared to the client clock). undefined = unknown (fetch failed or
// never ran); null = server says no failover ever recorded. Every unknown
// resolves to "connection_lost": this classifier may under-count, it must
// never fabricate a failover — fabrication was the P0.2 defect.
export function classifyDisconnect(
  baseline: string | null | undefined,
  current: string | null | undefined,
): "provider_changed" | "connection_lost" {
  if (baseline === undefined || current === undefined) {
    return "connection_lost";
  }
  if (current === null) {
    return "connection_lost";
  }
  if (baseline === null) {
    return "provider_changed";
  }
  return current !== baseline ? "provider_changed" : "connection_lost";
}

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

// Merge semantics mirrored in tests/test_panel_stream_dedup.py (the frontend
// has no test runner) — change BOTH together. The non-streaming wholesale
// REPLACE below is also the resume reset affordance: every streaming producer
// publishes a content:"" opener before (re-)streaming, which is what keeps a
// resumed stream from appending onto stale partial content.
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
  // Baseline for classifyDisconnect: last_failover_at snapshotted at socket
  // open (advanced in-band on provider_changed). undefined = unknown.
  const lastFailoverAtRef = useRef<string | null | undefined>(undefined);

  const decrementPending = useCallback(() => {
    pendingCountRef.current = Math.max(0, pendingCountRef.current - 1);
    if (pendingCountRef.current === 0) {
      setIsProcessing(false);
    }
  }, []);

  useEffect(() => {
    const url = `${WS_BASE_URL}/ws/${sessionId}`;
    setConnectionState("connecting");
    // Reset to unknown per socket: the effect re-runs on remount / sessionId
    // change (StrictMode double-invokes too) — a stale baseline from a
    // previous socket must never classify this one.
    lastFailoverAtRef.current = undefined;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionState("connected");
      void (async () => {
        try {
          const res = await fetch(
            `${httpBaseFromWs(WS_BASE_URL)}/ops/routing/notice`,
            { cache: "no-store" },
          );
          if (res.ok) {
            const payload = (await res.json()) as RoutingNotice;
            lastFailoverAtRef.current = payload.last_failover_at;
          }
        } catch {
          // Baseline stays unknown — onclose classifies conservatively.
        }
      })();
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
          // In-band baseline advance: this switch is now reported; a LATER
          // plain disconnect must not re-report it (opener row 14). Absent
          // stamp -> unknown, which classifies conservatively.
          lastFailoverAtRef.current = data.last_failover_at
            ? data.last_failover_at
            : undefined;
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
        const baseline = lastFailoverAtRef.current;
        void (async () => {
          let current: string | null | undefined = undefined;
          let activeWs: string | null | undefined = undefined;
          try {
            const res = await fetch(
              `${httpBaseFromWs(WS_BASE_URL)}/ops/routing/notice`,
              { cache: "no-store" },
            );
            if (res.ok) {
              const payload = (await res.json()) as RoutingNotice;
              current = payload.last_failover_at;
              activeWs = payload.ws_base_url;
            }
          } catch {
            // current stays unknown — classified conservatively below.
          }
          if (classifyDisconnect(baseline, current) === "provider_changed") {
            const endpoint =
              activeWs && activeWs !== WS_BASE_URL
                ? ` New endpoint: ${activeWs}`
                : "";
            setProviderNotice(
              `Provider changed — in-flight answer was interrupted. Reconnect and resubmit if needed.${endpoint}`,
            );
          } else {
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

  const sendResume = useCallback(() => {
    // Explicit resume-from-checkpoint (W3). The backend refuses while a task
    // is in flight, so this is safe to expose next to the cancel notice.
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      pendingCountRef.current += 1;
      setIsProcessing(true);
      setLastError(null);
      setCancelNotice(null);
      ws.send(JSON.stringify({ type: "resume" }));
    }
  }, []);

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
    sendResume,
    clearError,
    clearCancelNotice,
    clearProviderNotice,
  };
}

