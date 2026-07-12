export type PanelStatus = "processing" | "review_passed" | "completed";
export type ContentType = "markdown" | "code" | "image" | "audio" | "video";
export type ContentFormat = "markdown" | "ranked_list";
export type DataTier = "mayor" | "micro" | "usable" | "final";

export interface AgentTrace {
  agent_name: string;
  inputs_seen: string[];
  task_summary?: string | null;
  output_preview?: string | null;
}

export interface PanelSegment {
  title: string;
  content: string;
  source_agents?: string[];
  pov?: string | null;
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
  pov_sources?: string[];
  product_mode?: string;
  output_level?: string;
  pipeline_stage?: string;
  pov_segments?: PanelSegment[];
  content_format?: ContentFormat | null;
  follow_up_kinds?: string[];
  is_streaming?: boolean;
}

export interface WorkerError {
  type: "error";
  message: string;
}

export interface CancelledMessage {
  type: "cancelled";
  message: string;
}

export type WebSocketMessage = Panel | WorkerError | CancelledMessage;

export function isWorkerError(msg: unknown): msg is WorkerError {
  return (
    typeof msg === "object" &&
    msg !== null &&
    (msg as WorkerError).type === "error" &&
    typeof (msg as WorkerError).message === "string"
  );
}

export function isCancelledMessage(msg: unknown): msg is CancelledMessage {
  return (
    typeof msg === "object" &&
    msg !== null &&
    (msg as CancelledMessage).type === "cancelled" &&
    typeof (msg as CancelledMessage).message === "string"
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
    direct_responder: "Direct Responder",
    presenter: "Presenter",
    resource_finder: "Resource Finder",
    resource_reader: "Resource Reader",
    combiner_mayor: "Combiner Mayor",
    combiner_micro: "Combiner Micro",
    collector: "Collector",
    defense_delegator: "Defense Delegator",
    defense_review: "Defense Review",
    photo: "Photo",
    video: "Video",
    audio: "Audio",
    chemistry: "Chemistry",
    biology: "Biology",
    economics: "Economics",
    art: "Art",
    ui_design: "UI Design",
  };
  if (overrides[registryKey]) {
    return overrides[registryKey];
  }
  return registryKey
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
