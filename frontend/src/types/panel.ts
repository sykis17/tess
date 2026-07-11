export type PanelStatus = "processing" | "review_passed" | "completed";
export type ContentType = "markdown" | "code" | "image";

export interface Panel {
  panel_id: string;
  folder_path: string;
  status: PanelStatus;
  content_type: ContentType;
  content: string;
  follow_up_options: string[];
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
