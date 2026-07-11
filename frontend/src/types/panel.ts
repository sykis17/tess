export type PanelStatus = "processing" | "review_passed" | "completed";
export type ContentType = "markdown" | "code" | "image";
export type DataTier = "mayor" | "micro" | "usable" | "final";

export interface AgentTrace {
  agent_name: string;
  inputs_seen: string[];
  task_summary?: string | null;
  output_preview?: string | null;
}

export interface Panel {
  panel_id: string;
  folder_path: string;
  status: PanelStatus;
  content_type: ContentType;
  content: string;
  follow_up_options: string[];
  agents_involved?: string[];
  agent_traces?: AgentTrace[];
  data_tier?: DataTier;
}

export interface WorkerError {
  type: "error";
  message: string;
}

export type WebSocketMessage = Panel | WorkerError;

export function isWorkerError(msg: unknown): msg is WorkerError {
  return (
    typeof msg === "object" &&
    msg !== null &&
    (msg as WorkerError).type === "error" &&
    typeof (msg as WorkerError).message === "string"
  );
}

export function isPanel(msg: unknown): msg is Panel {
  return (
    typeof msg === "object" &&
    msg !== null &&
    "panel_id" in msg &&
    "content_type" in msg
  );
}

export function formatAgentDisplayName(registryKey: string): string {
  const overrides: Record<string, string> = {
    wide_receiver: "Wide Receiver",
    presenter: "Presenter",
    resource_finder: "Resource Finder",
    resource_reader: "Resource Reader",
    combiner_mayor: "Combiner Mayor",
    combiner_micro: "Combiner Micro",
    collector: "Collector",
  };
  if (overrides[registryKey]) {
    return overrides[registryKey];
  }
  return registryKey
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
