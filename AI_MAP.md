# TESS Engine - AI Architecture Map

## Core Concept

TESS is an event-driven, continuously processing AI engine. It does not rely on a traditional request-response model. Instead, it uses an open WebSocket connection, allowing the AI to stream data (Panels) asynchronously, while the user can interrupt, steer, or modify the process on the fly.

## Tech Stack

- **API & Routing:** FastAPI (Python 3.11) + WebSockets

- **Background Jobs & Message Broker:** Celery + Redis

- **Orchestration:** LangGraph

- **LLMs:** Gemini (Cloud) & Ollama (Local)

## Agent Roles (LangGraph Nodes)

1. **Wide Receiver (WR):** The "brain" and entry point. Analyzes the user's input and triggers the required topic or specialist agents.

2. **Topic Agents / Specialist Agents:** Execute parallel tasks (e.g., writing code, fetching web resources, analyzing media). They produce raw "Mayor data".

3. **Combiners (Mayor & Micro) & Collector:** Aggregate the raw data from agents, refine it, and sort it into a logical sequence.

4. **Presenter:** Formats the final curated data and packages it into structured visual Panels (JSON).

5. **Defense:** Acts as the quality assurance layer. Reviews outputs (e.g., checking code logic or schema requirements) before they are dispatched to the user.

## Data Flow

User (Frontend) -> WebSocket -> FastAPI -> Redis -> Celery Worker (LangGraph runs here) -> Presenter sends JSON Panel via FastAPI -> Frontend renders the Panel.

## Phase 9 Graph (Current)

The graph routes through one specialist agent per message and streams agent visibility metadata to the frontend:

```
START -> wide_receiver -> [coder | researcher | general_assistant] -> presenter -> END
```

### Node Responsibilities

| Node | Role | State written |
|------|------|---------------|
| **wide_receiver** | Analyzes intent; outputs routing JSON (`active_agents`, `current_task`); emits a `processing` Panel | `active_agents`, `current_task`, `agent_traces`, `panels` |
| **coder** | Code generation, debugging, refactoring | `collected_data`, `agent_traces` |
| **researcher** | Factual research, explanations, summaries | `collected_data`, `agent_traces` |
| **general_assistant** | Casual conversation and general tasks | `collected_data`, `agent_traces` |
| **presenter** | Formats specialist output into a completed Panel with full trace | `panels`, `agent_traces` |

### Specialist Agent Config

Each specialist lives under `app/agents/<name>/` with:
- `prompt.py` — system prompt
- `config.py` — `AgentConfig` (name, folder_path, description)
- Registered in `app/agents/registry.py`

| Agent | folder_path | Routes when |
|-------|-------------|-------------|
| `coder` | `Coding/Projects` | Code generation, debugging, refactoring |
| `researcher` | `Research/Topics` | Factual research, explanations, "what is / how does" |
| `general_assistant` | `Assistant/General` | Casual chat and general tasks |

The Presenter resolves `folder_path` from the active agent and attaches `agents_involved` plus `agent_traces` to each Panel.

### Agent Visibility (Phase 9)

- **`AgentTrace`** — per-node record of `agent_name`, `inputs_seen`, `task_summary`, `output_preview`
- **`agents_involved`** — human-readable pipeline on each Panel (e.g. Wide Receiver → Coder → Presenter)
- **Processing Panel** — WR emits a `status: processing` Panel immediately after routing; Presenter updates the same `panel_id` with the final answer
- Worker uses `astream(stream_mode="updates")` to publish Panels incrementally via Redis

### State Passing

- WR reads `user_input` and `conversation_history`; does not produce user-facing content.
- Specialist reads `current_task`, `user_input`, and `conversation_history`.
- Presenter reads `collected_data`, `active_agents`, and accumulated `agent_traces`.

### Future (not yet implemented)

- Parallel topic agents running simultaneously
- Mayor/Micro combiners and Collector
- Defense QA layer before Panel dispatch
- Token streaming to frontend
