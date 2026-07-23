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

### Phase 21 — Presenter gap & final-answer delivery

Production issue (2026-07-12): after defense passes, UI freezes on *"Quality checks passed — formatting final answer…"* for many minutes. Root cause: presenter blocks on **`generate_follow_up_options` LLM** with no progress Panel; status wall stays on **Defense** because `review_passed` Panel sets `pipeline_stage=defense`.

See [PHASE_21_OPENER.md](PHASE_21_OPENER.md) for full brief, deliverables (two-phase presenter recommended), and test matrix.

### Future (post–Phase 21)

- Expand POV catalog (physics, history, psychology, …).
- Raise 3-agent parallel cap when CPX11 or cloud budget allows.
- Full K–12 / professional discipline matrix (100+ POV agents with grouped WR routing).

### Multi-cloud ops hardening (parallel track)

Session 1 (2026-07-21): SSH lockout + EIP cost docs; chaos kinds live
(`health_5xx` / `worker_down` / `redis_partition` / `cpu_burn` failover).

Session 2 (2026-07-21): Mid-session browser failover observed (silent continue —
no `provider_changed` banner under simulate-unhealthy); `high_latency` decided
**score-only** (option 1); External uptime subsection + UptimeRobot target on
`/health` (monitor create pending).

Session 3 (2026-07-21): UptimeRobot monitor live (`803559917`, alert
`jesse.malma@gmail.com`); `aws_standby.py drift-check` + unit tests + docs.
HEAD fix for UptimeRobot (GET+HEAD `/health`) deployed.

Session 4 (2026-07-21): Per-operator admin tokens (`OPS_ADMIN_TOKENS`) + hard
GET gating; public `/ops/routing/notice`.

Session 5 (2026-07-21): `provider_changed` Redis → WebSocket fan-out; minimal
`/ops-ui/` take-offline admin page (Bearer).

Session 6 (2026-07-21): Read-only `/ops-status/` (providers, scores, events,
UptimeRobot link); Caddy + cross-links with `/ops-ui/`.

Session 7 (2026-07-22): Three-way chaos failover validated (Hetzner→AWS and
Hetzner→GCP auto-switch at probe #3); standby wake preflight; host metrics
self-report scoring live on all three stacks. Resting: Hetzner active, AWS/GCP
stopped.

Post–Session 7 decisions:

- **Step 4 skipped** — keep `/health` self-report as scoring source of truth;
  no GcpAdapter Cloud Monitoring / CloudWatch / Hetzner Cloud API pulls.
- **Step 5** — stakeholder demo runbook + `scripts/ops_three_way_demo.py`
  (see [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md#stakeholder-three-way-chaos-demo-step-5)).
- **AWS sizing parked** — `t3.micro` + 1GB swap OK for control-plane smoke;
  resize only if AWS must stay active under real LangGraph/LLM load.

**Session 8 (merged):** Dual two-home XOR Performance (anti-flap + optional
auto-wake), Sleep-all resting cost, power trail. See
[MULTI_CLOUD_HARDENING_S8_OPENER.md](MULTI_CLOUD_HARDENING_S8_OPENER.md).

**Next — Session 9 (in progress):** Wake observability/reliability (enqueue ≠
done), Dual demo path (≥2 healthy gate + UX). Shared Redis / seamless is
**Track C → Session 10** (deferred until A+B pass on Hetzner).
See [MULTI_CLOUD_HARDENING_S9_OPENER.md](MULTI_CLOUD_HARDENING_S9_OPENER.md).

See [MULTI_CLOUD_HARDENING_S7_OPENER.md](MULTI_CLOUD_HARDENING_S7_OPENER.md)
(prior: [MULTI_CLOUD_HARDENING_S6_OPENER.md](MULTI_CLOUD_HARDENING_S6_OPENER.md),
[MULTI_CLOUD_HARDENING_S5_OPENER.md](MULTI_CLOUD_HARDENING_S5_OPENER.md),
[MULTI_CLOUD_HARDENING_S4_OPENER.md](MULTI_CLOUD_HARDENING_S4_OPENER.md),
[MULTI_CLOUD_HARDENING_S3_OPENER.md](MULTI_CLOUD_HARDENING_S3_OPENER.md),
[MULTI_CLOUD_HARDENING_S2_OPENER.md](MULTI_CLOUD_HARDENING_S2_OPENER.md),
[MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md)).

---

## Principles

1. **One deployable phase at a time** — each phase ships to production before the next.
2. **Panels stay backward-compatible** — new fields optional; frontend degrades gracefully.
3. **Visibility first** — every new node writes `AgentTrace`; users see the chain grow.
4. **Ollama for dev, Gemini when ready** — chain profiles testable locally on small models.
5. **POV over depth** — agents represent disciplinary lenses on a question, not brief vs deep variants of one subject.
