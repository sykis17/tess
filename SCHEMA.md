# TESS Engine - Data Schemas

The system relies on strictly typed data. We use Pydantic models in Python to enforce these structures.

## 1. Panel (JSON payload via WebSocket)

When a background process completes a segment of the solution, it streams to the frontend as a `Panel` object.

```json
{
  "panel_id": "uuid4",
  "folder_path": "Coding/Project_A",
  "status": "processing | review_passed | completed",
  "content_type": "markdown | code | image",
  "content": "The actual payload (e.g., code block or text)",
  "follow_up_options": ["Continue with this", "Change style", "Discard"],
  "agents_involved": ["Wide Receiver", "Coder", "Presenter"],
  "agent_traces": [
    {
      "agent_name": "wide_receiver",
      "inputs_seen": ["user_input", "conversation_history (2 turns)"],
      "task_summary": "Write a Python sort function",
      "output_preview": "Routed to: coder — Write a Python sort function"
    }
  ]
}
```

### Optional fields (Phase 9)

| Field | Type | Description |
|-------|------|-------------|
| `agents_involved` | `list[str]` | Human-readable pipeline of agents that produced the Panel |
| `agent_traces` | `list[AgentTrace]` | Per-agent input/output summaries for the UI details section |

Clients should treat missing `agents_involved` and `agent_traces` as empty lists.

## 2. AgentTrace

Per-agent visibility record accumulated during graph execution.

| Field | Type | Description |
|-------|------|-------------|
| `agent_name` | `str` | Registry key (e.g. `wide_receiver`, `coder`) |
| `inputs_seen` | `list[str]` | Summary of context the agent received |
| `task_summary` | `str \| null` | Task string from WR routing (when applicable) |
| `output_preview` | `str \| null` | First ~200 chars of agent output |
