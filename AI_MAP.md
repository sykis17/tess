# TESS Engine — AI Architecture Map

## Core Concept

TESS is an event-driven, continuously processing AI engine. It does not rely on a traditional request-response model. Instead, it uses an open WebSocket connection, allowing the AI to stream data (Panels) asynchronously while the user can interrupt, steer, or modify the process on the fly.

## Tech Stack

| Layer | Technology |
|-------|------------|
| API & WebSockets | FastAPI (Python 3.11) |
| Background jobs | Celery + Redis |
| Orchestration | LangGraph |
| LLMs | Gemini (cloud) & Ollama (local) |
| Frontend | React + Vite |

## Data Flow (Transport)

```
User (Frontend)
  → WebSocket → FastAPI
  → Celery task dispatch
  → LangGraph (worker)
  → Redis Pub/Sub
  → WebSocket → Frontend renders Panels
```

---

## Target AI Chain (Full Vision)

The long-term orchestration model is a layered pipeline. Agents produce progressively refined data; combiners aggregate it; defense reviews it; the presenter packages the final output.

```mermaid
flowchart TB
    subgraph intake [Intake]
        WR[Wide Receiver]
    end

    subgraph agents [Agent Layer]
        POV[POV Agents\ndisciplinary lenses\nchemistry art ui_design]
        SA[Specialist Agents\nphoto video audio]
        SR[Search\nresource finder\nresource reader]
    end

    subgraph pipeline [Data Pipeline]
        CM[Combiner Mayor\nmayor data → micro data]
        Cm[Combiner Micro\nmicro data → usable answers]
        COL[Collector\nsort usable answers]
    end

    subgraph qa [Quality]
        DEF[Defense\ndelegator review\nbig picture detail implication]
    end

    subgraph output [Output]
        PRE[Presenter\nPanel JSON]
    end

    WR --> POV
    WR --> SA
    WR --> SR
    POV --> CM
    SA --> CM
    SR --> CM
    CM --> Cm
    Cm --> COL
    COL --> DEF
    DEF --> PRE
```

### Layer Responsibilities

| Layer | Role | Output |
|-------|------|--------|
| **Wide Receiver** | Reads the user message, interprets intent, alarms the required agents | Routing plan (`active_agents`, tasks, search triggers) |
| **POV Agents** | One per field of study / discipline (chemistry, art, ui_design, …); each answers from that lens | **Mayor data** — raw output tagged with `pov` |
| **Specialist Agents** | Media and tool specialists (photo, video, audio, coder) | **Mayor data** — processed artifacts |
| **Search** | Resource finder locates sources; resource reader extracts content | **Mayor data** — grounded excerpts and citations |
| **Combiner Mayor** | Gathers all mayor data from parallel agents + search | **Micro data** — structured, cross-topic synthesis |
| **Combiner Micro** | Refines micro data into coherent answer units | **Usable answers** — ranked, actionable segments |
| **Collector** | Collects usable answers and sorts them logically | Ordered answer set for presentation |
| **Defense** | QA layer: delegator, review, big-picture check, detail check, implication check | Pass / revise / reject per segment |
| **Presenter** | Formats collector output into typed Panel JSON for the frontend | `Panel` stream |

### Data Tiers

```
Mayor data  →  raw agent output (per topic / search / specialist)
Micro data  →  cross-agent synthesis (Combiner Mayor)
Usable answers  →  refined segments ready for review (Combiner Micro)
Panel  →  user-facing payload (Presenter, after Defense)
```

### Complex Question Example

User asks a multi-perspective question (e.g. *"Design a school app UI — cover aesthetics and implementation"*).

1. **WR** alarms e.g. `art` + `ui_design` + optional `coder` POV agents (+ `photo` for diagram plan).
2. Each POV agent produces mayor data from its disciplinary lens.
3. **Combiner Mayor** weaves perspectives into micro data (Art: visual hierarchy… / UI Design: patterns…).
4. **Combiner Micro** → **Collector** → **Defense** (keep length reasonable, safe, aligned) → **Presenter**.

Legacy example (multi-subject factual): *"Compare renewable energy economics and chemistry"* → `economics` + `chemistry` POVs + optional search.

### Main Product Functions (Modes)

These are user-facing capabilities that WR routes into — not separate graphs, but intent profiles:

| Mode | Purpose |
|------|---------|
| **Research** | Deep factual exploration, citations, multi-source synthesis |
| **Planner** | Task breakdown, timelines, structured plans |
| **Coding platform** | Code generation, debugging, project scaffolding |
| **Builder** | Assembly of artifacts (docs, configs, multi-step outputs) |

Each mode influences WR routing (which topic/specialist agents to alarm) and which combiner depth is needed.

---

## Current Implementation (Phase 15B — live)

The deployed graph uses **POV agents** — one disciplinary lens per agent (chemistry, art, ui_design, …). WR routes 1–3 relevant perspectives; combiners weave cross-POV answers; defense reviews before presentation.

```
START → wide_receiver → [parallel: POV agents | coder | researcher | general_assistant | photo | video | audio] + [optional: resource_finder → resource_reader]
      → post_fan_in → [bypass → defense | combiners → defense] → presenter → END
```

Combiner chain (when not bypassed):

```
post_fan_in → combiner_mayor → combiner_micro → collector → defense_delegator → defense_review → presenter
```

Defense chain (all paths):

```
defense_delegator → defense_review → [pass → presenter | revise → combiner_micro or specialist (bounded retries)]
```

| Node | Status | Notes |
|------|--------|-------|
| Wide Receiver | ✅ Live | Routes to 1–3 specialists; POV keyword override corrects wrong-discipline misroutes |
| POV Agents | ✅ Live | Chemistry, Biology, Economics, Art, UI Design — one lens per discipline; `researcher` fallback for off-matrix topics |
| Specialist Agents (media) | ✅ Live | Photo, Video, Audio — diagram plans, scripts, outlines (text-first; URL when provided) |
| Search | ✅ Live | Resource finder (DuckDuckGo / Tavily) → resource reader; feeds `mayor_data` with citations |
| Combiner Mayor | ✅ Live | Aggregates `mayor_data` → `micro_data` (cross-POV synthesis) |
| Combiner Micro | ✅ Live | Refines `micro_data` → `usable_answers` (3–5 segments with POV attribution) |
| Collector | ✅ Live | Deterministic sort by `order_hint` |
| Defense Delegator | ✅ Live | Normalizes segments for review (wraps bypass `mayor_data` when needed) |
| Defense Review | ✅ Live | Single LLM call returns all three checks per segment; length cap guidance; emits `review_passed` Panel |
| Presenter | ✅ Live | Reads approved `usable_answers`; emits `completed` Panel with `pov_sources` |

**Bypass rule:** Skip combiners when `len(active_agents) <= 1` and no `resource_reader` entry — single-agent prompts stay fast. Defense always runs (lightweight single-check review on all paths).

**Defense retry:** On `revise`, loops back to `combiner_micro` (synthesis path) or originating specialist (bypass path); capped at `MAX_DEFENSE_RETRIES=2`. Fan-in join waits for all parallel branches; refusal auto-revise; WR routes listed POV topics to POV agents, off-matrix factual topics to researcher.

**Fan-in join (13.1):** `post_fan_in` waits until all expected branches (`active_agents` + optional `resource_reader`) report done before routing downstream.

### Live POV Agents (Phase 15B)

| Agent | `folder_path` | Lens | Routes when |
|-------|---------------|------|-------------|
| `chemistry` | `Science/Chemistry` | Chemistry | Bonding, reactions, materials, stoichiometry |
| `biology` | `Science/Biology` | Biology | Cells, ecosystems, physiology, genetics |
| `economics` | `Social Studies/Economics` | Economics | Supply, demand, markets, trade-offs |
| `art` | `Arts/Visual` | Art | Composition, color, aesthetics, visual hierarchy |
| `ui_design` | `Design/UI` | UI Design | Layout, usability, patterns, accessibility |

### Live Tool & Media Agents

| Agent | `folder_path` | Routes when |
|-------|---------------|-------------|
| `coder` | `Coding/Projects` | Code generation, debugging, refactoring |
| `researcher` | `Research/Topics` | Factual research for off-matrix topics (Kubernetes, history, etc.) |
| `general_assistant` | `Assistant/General` | Casual chat and general tasks |
| `photo` | `Media/Photo` | Diagram plans, image descriptions, visual layouts |
| `video` | `Media/Video` | Video scripts, storyboards, edit plans |
| `audio` | `Media/Audio` | Voiceover scripts, podcast outlines, audio plans |

Config pattern: `app/agents/<name>/config.py` + `prompt.py`, registered in `app/agents/registry.py`.

### Agent Visibility (Phase 9–11)

- **`AgentTrace`** — per-node record (`agent_name`, `inputs_seen`, `task_summary`, `output_preview`)
- **`agents_involved`** — human-readable pipeline on each Panel (all parallel agents + search when active)
- **`MayorData`** — per-specialist raw output in graph state before combiner stages; POV agents set `pov`; `resource_reader` populates `citations`
- **`pov_sources`** — disciplinary lenses on processing/completed Panels (Phase 15B)
- **`MicroData`** / **`UsableAnswer`** — combiner pipeline types; Presenter reads ordered `usable_answers` on synthesis path
- **Processing Panel** — WR streams `status: processing` immediately with all alarmed agent badges (including combiners when predicted); combiner nodes may emit intermediate Panels with `data_tier`
- Worker uses `astream(stream_mode="updates")` for incremental Redis publish
- Parallel fan-out via LangGraph `Send` API; fan-in at Presenter (max 3 agents + optional search)
- Search provider: DuckDuckGo default; Tavily when `TAVILY_API_KEY` is set

---

## Research: Output Levels (Proposed)

A high-value research feature: let the user **select an output level** and compare results from different chain depths on the same question.

| Level | Name | Chain | Use case |
|-------|------|-------|----------|
| **L0** | Direct | Single Ollama/Gemini call, no graph | Baseline speed and quality |
| **L1** | Routed | WR → one specialist → Presenter | Single-domain default |
| **L1+** | Parallel routed | WR → parallel specialists → Presenter | **Current Phase 10** (1–3 agents) |
| **L2** | Reviewed | L1 + Defense pass before Panel | QA comparison |
| **L3** | Grounded | L2 + Search (finder + reader) | Citation and source quality |
| **L4** | Multi-agent | WR → parallel topic agents → Mayor → Micro → Collector → Defense → Presenter | Full TESS chain |

### Why this is a strong direction

1. **Measurable quality ladder** — Same prompt, different levels; `agent_traces` already show what each agent saw, so diffs are inspectable.
2. **Cost / latency tradeoffs** — L0 is fast; L4 is thorough. Users (and researchers) pick consciously.
3. **Incremental delivery** — Each level reuses the previous graph as a subgraph; ROADMAP can add levels without rewriting.
4. **UI fit** — A level selector in the frontend maps to a `chain_profile` field on the request; Panels can include `output_level` in metadata for side-by-side comparison views.

### Suggested implementation path

1. Add `chain_profile: Literal["L0", "L1", …]` to session or per-message request (see `SCHEMA.md`).
2. Build L0 as a bypass graph (no WR) for baseline.
3. Keep L1 as default (current graph).
4. Add L2–L4 as new LangGraph branches/subgraphs as combiners and defense land.

---

## Key Files

| Area | Path |
|------|------|
| Graph definition | `app/graph/builder.py` |
| Combiner nodes | `app/graph/nodes/combiner_mayor.py`, `combiner_micro.py`, `collector.py`, `post_fan_in.py` |
| Defense nodes | `app/graph/nodes/defense_delegator.py`, `defense_review.py` |
| Defense utilities | `app/graph/defense_utils.py` |
| Fan-in utilities | `app/graph/fan_in_utils.py` |
| Combiner utilities | `app/graph/combiner_utils.py` |
| WR routing | `app/graph/nodes/wide_receiver.py`, `app/graph/routing.py` |
| Search nodes | `app/graph/nodes/resource_finder.py`, `app/graph/nodes/resource_reader.py` |
| Search utilities | `app/search/provider.py`, `app/search/fetcher.py`, `app/search/extractor.py` |
| Specialist nodes | `app/graph/nodes/<name>.py` |
| Agent registry | `app/agents/registry.py`, `app/agents/subjects/registry.py` |
| Phase 15B brief | `PHASE_15B_OPENER.md` |
| Shared specialist runner | `app/agents/base.py` |
| Presenter | `app/graph/nodes/presenter.py` |
| Panel schema | `app/graph/schemas.py`, `SCHEMA.md` |
| Worker | `app/worker.py` |
| Frontend Panel UI | `frontend/src/components/PanelCard.tsx` |
