import type { ConnectionState } from "../hooks/useWebSocket";

interface ConnectionStatusProps {
  state: ConnectionState;
}

const LABELS: Record<ConnectionState, string> = {
  connecting: "Connecting",
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error",
};

export function ConnectionStatus({ state }: ConnectionStatusProps) {
  return (
    <span className={`connection-status connection-status--${state}`}>
      {LABELS[state]}
    </span>
  );
}
