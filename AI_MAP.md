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

## Phase 8 Graph (Current)

The graph routes through a specialist agent instead of answering directly in the Wide Receiver:

```
START -> wide_receiver -> general_assistant -> presenter -> END
```

### Node Responsibilities

| Node | Role | State written |
|------|------|---------------|
| **wide_receiver** | Analyzes intent; outputs routing JSON (`active_agents`, `current_task`) | `active_agents`, `current_task` |
| **general_assistant** | First specialist agent; calls LLM with its own system prompt | `collected_data` |
| **presenter** | Formats specialist output into a Panel JSON payload | `panels` |

### Specialist Agent Config

Each specialist lives under `app/agents/<name>/` with:
- `prompt.py` — system prompt
- `config.py` — `AgentConfig` (name, folder_path, description)
- Registered in `app/agents/registry.py`

The Presenter resolves `folder_path` from the active agent (e.g. `Assistant/General`).

### State Passing

- WR reads `user_input` and `conversation_history`; does not produce user-facing content.
- Specialist reads `current_task`, `user_input`, and `conversation_history`.
- Presenter reads `collected_data` and `active_agents`.

### Future (not yet implemented)

- Parallel topic agents (Coder, Researcher, etc.)
- Mayor/Micro combiners and Collector
- Defense QA layer before Panel dispatch
