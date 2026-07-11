# TESS Engine — Roadmap

## Completed

- [x] **Phase 1:** Local Docker infrastructure (FastAPI, Redis, Celery).
- [x] **Phase 2:** LLM interfaces (async Gemini & Ollama wrappers).
- [x] **Phase 3:** Core LangGraph structure (Wide Receiver & Presenter nodes).
- [x] **Phase 4:** Celery worker executes LangGraph; Panels stream via Redis/WebSockets.
- [x] **Phase 5:** React frontend prototype — dynamic Panel rendering.
- [x] **Phase 6:** Hetzner production deployment.
- [x] **Phase 7:** Ollama/Gemini in LangGraph; Redis conversation history for follow-ups.
- [x] **Phase 8:** WR routes to General Assistant specialist; per-agent config in `app/agents/`.
- [x] **Phase 9:** Agent visibility (`agents_involved`, `agent_traces`, processing Panel); Coder + Researcher specialists; dynamic WR routing.
- [x] **Phase 10:** Parallel topic agents — WR alarms 1–3 specialists; LangGraph `Send` fan-out/fan-in; `MayorData` in graph state; multi-agent processing Panel.
- [x] **Phase 11:** Search layer — resource finder (DuckDuckGo / Tavily) + resource reader; `search_queries` on WR routing; grounded excerpts in `mayor_data` with citations; optional Redis search cache.
- [x] **Phase 12:** Combiners + Collector — Combiner Mayor/Micro LLM synthesis; deterministic Collector; bypass for single-agent fast path; `MicroData` / `UsableAnswer` live; optional `data_tier` on intermediate Panels.

---

## Next — Full AI Chain

Phases below map to the [target architecture](AI_MAP.md#target-ai-chain-full-vision). Each phase should keep backward-compatible Panels and deployable increments.

### Phase 13 — Defense layer

- Defense nodes: delegator, review, big-picture, detail, implication.
- `Panel.status: review_passed` before `completed`.
- Failed review loops back to relevant agent or combiner (bounded retries).

### Phase 14 — Media specialist agents

- Photo, video, audio specialist agents.
- Panel `content_type` for image/audio/video payloads.
- WR routes media tasks alongside topic agents.

### Phase 15 — Topic agent matrix

- School-subject topic agents (major + minor depth variants).
- Subject registry mirroring `app/agents/` pattern.
- WR prompt auto-generated from full subject list.
- Folder paths per subject (e.g. `Science/Chemistry`, `Math/Algebra`).

### Phase 16 — Product modes

- **Research** — deep synthesis, citations, L3+ chain default.
- **Planner** — structured plans and timelines.
- **Coding platform** — project-scoped coding workflows.
- **Builder** — multi-artifact assembly.
- Mode selector in frontend; WR receives `product_mode` in state.

### Phase 17 — Output levels (research feature)

- User-selectable **chain profile** (L0–L4): direct LLM → full chain.
- Same question, compare Panels side-by-side with `output_level` metadata.
- L0 bypass graph for baseline benchmarking.
- Research UI: diff view using `agent_traces` across levels.

### Phase 18 — Streaming & polish

- Token streaming to frontend (partial Panel content).
- LLM-generated follow-up options.
- Interrupt / steer mid-chain via `interruption_flag`.
- Performance tuning for CPX11 (4 GB RAM) production constraints.

---

## Principles

1. **One deployable phase at a time** — each phase ships to production before the next.
2. **Panels stay backward-compatible** — new fields optional; frontend degrades gracefully.
3. **Visibility first** — every new node writes `AgentTrace`; users see the chain grow.
4. **Ollama for dev, Gemini when ready** — chain profiles testable locally on small models.
