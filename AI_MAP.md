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

