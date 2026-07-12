# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TESS Engine is an event-driven AI orchestration engine. Users connect over a WebSocket; a Celery worker runs a LangGraph pipeline that streams "Panels" (status + content) back through Redis Pub/Sub. The graph fans out to **POV (point-of-view) agents** — one disciplinary lens per agent (chemistry, biology, economics, art, ui_design) — and optionally search. Combiners deduplicate and weave multi-POV output; Defense Review runs a QA pass before the Presenter packages a final Panel.

Detailed reference: `AI_MAP.md` (architecture), `SCHEMA.md` (data types), `ROADMAP.md` (phase history), `PHASE_*_OPENER.md` (per-phase briefs).

## Build, Lint, Test

```bash
# install Python deps
pip install -r requirements.txt

# run the full test suite (focused on logic, no live LLM)
pytest tests/

# run a single test file
pytest tests/test_pov_routing.py -v

# run a single test function
pytest tests/test_pov_routing.py::test_ionic_bonding_replaces_wrong_biology_pov -v

# quick smoke script (runs 3 routing tests)
python scripts/test_pov_routing.py

# frontend
cd frontend
npm install
npm run dev       # Vite dev server
npm run build     # tsc + vite build
npm run lint      # oxlint
```

## Local stack (Docker Compose)

```bash
cp .env.example .env
docker compose up --build    # web (FastAPI :8000), worker (Celery), redis
cd frontend && npm run dev   # Vite :5173 (or :5175)
```

Ollama must be running on the host (default `llama3.2`); Docker containers reach it via `host.docker.internal:11434` (already set in `docker-compose.yml`). See `LOCAL_DEV.md` for full setup including switching to Gemini.

## Deployment

Production server: `5.78.186.223` (Hetzner CPX11). Update via `ssh root@<server> "cd /opt/tess-engine && git pull && ./deploy/deploy.sh"`. See `deploy/DEPLOY.md` and `deploy/SERVER_CHECKLIST.md`.

## Architecture

### Data flow

```
WebSocket (frontend) → FastAPI (app/api/ws.py) → Celery (app/worker.py)
  → compiled_graph.astream() (app/graph/builder.py)
  → Panels published to Redis channel_<session_id>
  → WebSocket forwards JSON to frontend
```

The frontend sends text or JSON envelope `{text, product_mode, chain_profile}` over `ws://<host>/ws/<session_id>`. Workers serialize each LangGraph node update into a `Panel` Pydantic model (see `app/graph/schemas.py`) and publish it. Frontend updates Panels in place by `panel_id`; intermediate "processing" panels share the same `panel_id` as the final "completed" panel.

### LangGraph nodes (app/graph/nodes/)

```
START
  ├─ L0  → direct_responder → presenter → END
  └─ L1+ → wide_receiver → fan_out (Send) ──┐
                                           ├─ <agent> (specialist) ──┐
                                           └─ resource_finder → resource_reader ──┤
                                                                                    ↓
                                                                       post_fan_in (waits for all branches)
                                                                                    ↓
                                                              ┌─ L1/L1+: presenter
                                                              ├─ L2/L3:   defense_delegator → defense_review → presenter
                                                              └─ L4:      combiner_mayor → combiner_micro → collector
                                                                          → defense_delegator → defense_review → presenter
```

- **wide_receiver**: LLM call returns JSON `{active_agents, current_task, search_queries}`. Routing post-processing in `app/graph/routing.py` (keyword override for wrong POVs, product-mode rules, chain-profile gates).
- **direct_responder**: L0 path — single LLM call, no specialists.
- **<agent> specialists**: `app/agents/base.py::run_specialist` runs an LLM call with the agent's system prompt + conversation history; produces a `MayorData` entry.
- **resource_finder → resource_reader**: DuckDuckGo / Tavily search, then page fetch + extract (`app/search/`).
- **combiner_mayor / combiner_micro / collector**: synthesize parallel `mayor_data` into ordered `UsableAnswer` segments.
- **defense_delegator / defense_review**: single LLM call evaluates each segment (big_picture / detail / implication); retries loop back to `combiner_micro` (or the originating specialist on bypass path); capped via `max_defense_retries(chain_profile)`.
- **presenter**: formats final Panel; runs follow-up chip generation (`follow_up_utils.py`), list-format post-processing (`list_format_utils.py`), and POV segment building (`pov_segments.py`).

### Chain profiles (L0–L4) and product modes

- `app/core/chain_profiles.py` — registry + validators + mode-to-profile defaults. Plain-text WebSocket input always resolves to L4.
- `app/graph/chain_gates.py` — pure gate functions (`allows_search`, `allows_defense`, `max_routed_agents`, etc.) keyed by chain profile. These are unit-tested directly.
- `app/core/product_modes.py` — `auto | research | planner | coding | builder`. Each mode injects routing rules into the WR system prompt and combiner/defense hints.
- WebSocket payload parsed in `app/core/ws_payload.py`.

### Specialist agent registry

`app/agents/registry.py::AGENT_REGISTRY` — dict of `AgentConfig` (name, folder_path, description, system_prompt, pov, agent_kind). Adding an agent: create `app/agents/<name>/{config.py,prompt.py}` and register the config. `app/agents/subjects/registry.py` holds POV definitions and keyword lists — keep `app/core/folder_tree.py` in sync with registry paths (`validate_tree_matches_registry()` is used in tests).

### LLM provider abstraction

`app/llm/factory.create_llm()` returns a `BaseLLM` (Gemini or Ollama). Selection via `DEFAULT_LLM_PROVIDER` env var. The Ollama wrapper (`app/llm/ollama.py`) serializes requests through an `asyncio.Lock` to prevent concurrent model calls on small hardware.

### Streaming and timing

- `app/worker.py::_run_graph_with_streaming` uses `astream(stream_mode="updates")` to publish Panels as each node completes. Soft time limit 720s, hard 730s (Celery).
- `app/graph/stream_utils.py::generate_with_panel_stream` — token-level streaming for L0 `direct_responder` and POV specialists; publishes `is_streaming` Panel deltas via Redis (throttled by `stream_throttle_ms`, default 75 ms).
- `app/core/session_control.py` — Redis-backed active task id + interrupt flag; WebSocket steer revokes in-flight Celery tasks when user sends while processing.
- `app/graph/panel_stream.py::publish_panel` — synchronous Redis publish from within async nodes (best-effort).
- Fan-in join via `expected_fan_in_branches` / `fan_in_branches_done` in `GraphState` (reducer-appended). `post_fan_in` waits until all branches complete; `fan_in_wait` is a no-op sink for early branches.

## Key Conventions

- **All new graph state** must be declared in `app/graph/state.py::GraphState` and added to `_REDUCER_KEYS` in `app/worker.py` if it should append-merge from parallel branches.
- **All Panel additions** are optional with sensible defaults — frontend `frontend/src/types/panel.ts` should mirror them.
- **POV agents** are disciplinary lenses, not depth variants. New POV: add to `POV_DEFINITIONS` in `app/agents/subjects/registry.py`, create `app/agents/<key>/`, register in `app/agents/registry.py`, mirror in `app/core/folder_tree.py` and `frontend/src/data/folderTree.ts`.
- **Linter** on frontend: `oxlint`; type-check via `tsc -b` (run as part of `npm run build`).
- **No Cursor rules** (`.cursor/` absent) — `.cursorrules` contains a short set: production-ready typed/Pydantic code, async-first FastAPI, modular layout, Celery delegation for heavy AI work, English-only docs and user-facing strings.
- **Tests are unit-level** — they exercise routing/parsing/serialization utilities directly, not the live graph. Live integration testing is via the local Docker stack (see `LOCAL_DEV.md`).

## Common file pointers

| Concern | File |
|---|---|
| Graph wiring | `app/graph/builder.py` |
| Chain profile gates | `app/graph/chain_gates.py` |
| Routing + keyword overrides | `app/graph/routing.py` |
| Presenter / final Panel | `app/graph/nodes/presenter.py` |
| Worker + Redis publish | `app/worker.py` |
| WebSocket endpoint | `app/api/ws.py` |
| Frontend WebSocket hook | `frontend/src/hooks/useWebSocket.ts` |
| Frontend Panel type | `frontend/src/types/panel.ts` |
| Status wall logic | `app/graph/pipeline_stages.py` + `frontend/src/hooks/usePipelineStatus.ts` |
| Folder tree | `app/core/folder_tree.py` + `frontend/src/data/folderTree.ts` |
| POV segment builder | `app/graph/pov_segments.py` |
| Follow-up generator | `app/graph/follow_up_utils.py` |
| List format | `app/graph/list_format_utils.py` |
| Search | `app/search/provider.py` + `app/graph/nodes/resource_*.py` |
