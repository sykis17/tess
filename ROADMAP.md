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
- [x] **Phase 17:** Chain profiles — L0–L4 depth gates on single graph; `chain_profile` on request/state; `output_level` on Panels; L0 `direct_responder` path; frontend chain selector + compare UI; `tests/test_chain_profiles.py`.
- [x] **Phase 18:** Pipeline status wall & results wall — `pipeline_stage` on streamed Panels; sticky status bar; virtual folder tree from agent `folder_path`; results wall filter; structured `pov_segments` on completed Panels; `tests/test_pipeline_stages.py`, `tests/test_pov_segments.py`.
- [x] **Phase 19:** Interactive learning UX — clickable POV segment drill-down; LLM-generated `follow_up_options` with `follow_up_kinds`; structured `ranked_list` content format; WR list-intent and drill-down routing hints; `tests/test_follow_up_options.py`, `tests/test_list_format.py`.
- [x] **Phase 20:** Streaming & polish — token streaming for L0 direct responder and POV specialists (`is_streaming` Panel deltas); mid-chain steer via send-while-processing (`session_control` + Celery revoke); CPX11 stream throttle; `tests/test_stream_utils.py`, `tests/test_session_control.py`, `tests/test_interruption.py`.

---

## Next — Full AI Chain

Phases below map to the [target architecture](AI_MAP.md#target-ai-chain-full-vision). Each phase should keep backward-compatible Panels and deployable increments.

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
