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
- [x] **Phase 13:** Defense layer — Defense Delegator + Defense Review (single LLM, three checks per segment); `review_passed` Panel before `completed`; bounded revise loops to combiner_micro or specialist; `DefenseReview` live in schemas.
- [x] **Phase 13.1:** Fan-in join fix; WR routes factual/explore topics to researcher; GA prompt anti-refusal; defense auto-revise on refusal phrases.
- [x] **Phase 14:** Media specialist agents — Photo, Video, Audio; Panel `content_type` audio/video; WR routes media alongside topic agents; text-first plans/scripts (Option A).
- [x] **Phase 15:** Subject agent scaffolding — Chemistry, Biology, Economics registry; interim `*_major`/`*_minor` depth tiers (superseded by 15B).
- [x] **Phase 15B:** POV agent matrix — five disciplinary lenses (`chemistry`, `biology`, `economics`, `art`, `ui_design`); `MayorData.pov`; WR routes perspectives not depth; POV keyword override fixes wrong-discipline misroutes; cross-POV combiner prompts; defense length guidance; `pov_sources` on Panels; frontend POV badges.
- [x] **Phase 15C:** Combiner role split — Mayor curates/sorts inventory with `overlap_notes` and per-segment `source_agents`; Micro deduplicates into consensus-style `usable_answers`.
- [x] **Phase 16:** Product modes — mode selector in frontend; `product_mode` in GraphState and Panels; JSON WebSocket envelope with plain-text fallback; WR mode rules and routing nudges; combiner/defense mode hints.

---

## Next — Full AI Chain

Phases below map to the [target architecture](AI_MAP.md#target-ai-chain-full-vision). Each phase should keep backward-compatible Panels and deployable increments.

### Phase 17 — Output levels (research feature)

- User-selectable **chain profile** (L0–L4): direct LLM → full chain.
- Same question, compare Panels side-by-side with `output_level` metadata.
- L0 bypass graph for baseline benchmarking.
- Research UI: diff view using `agent_traces` across levels.

### Phase 18 — Pipeline status wall & results wall

- **Status wall / info bar** — persistent UI from WR through Presenter showing what will happen and what is happening (agent badges, stage, ETA hints).
- **Results wall** — folder-tree navigation opens a wall of Panels/results per virtual folder (e.g. `Science/Chemistry`, `Design/UI`).
- POV segments visible in completed Panels (which lens contributed what).

### Phase 19 — Interactive learning UX

- **Click title → drill down** — clicking a segment title auto-sends "tell me more about this" in context.
- **Context-related questions** — WR or post-presenter suggestions to clarify user needs and improve accuracy.
- **Context-deviating questions** — adjacent-topic suggestions to broaden exploration.
- **Structured list formats** — "10 best beaches", "top careers", ranked/itemized output templates.
- **Choice themes** — present 4 options/themes for user to steer next step.
- LLM-generated `follow_up_options` replace static mock buttons where possible.

### Phase 20 — Streaming & polish

- Token streaming to frontend (partial Panel content).
- Interrupt / steer mid-chain via `interruption_flag`.
- Performance tuning for CPX11 (4 GB RAM) production constraints.

### Future (post–Phase 20)

- Expand POV catalog (physics, history, psychology, …).
- Raise 3-agent parallel cap when CPX11 or cloud budget allows.
- Full K–12 / professional discipline matrix (100+ POV agents with grouped WR routing).

---

## Principles

1. **One deployable phase at a time** — each phase ships to production before the next.
2. **Panels stay backward-compatible** — new fields optional; frontend degrades gracefully.
3. **Visibility first** — every new node writes `AgentTrace`; users see the chain grow.
4. **Ollama for dev, Gemini when ready** — chain profiles testable locally on small models.
5. **POV over depth** — agents represent disciplinary lenses on a question, not brief vs deep variants of one subject.
