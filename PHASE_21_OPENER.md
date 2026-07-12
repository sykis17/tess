# TESS Engine — Phase 21 Session Opening Message

## Context

Phases 1–20 are complete and deployed to **http://5.78.186.223** (CPX11, `llama3.2:1b`, 15-minute pipeline timeout).

**Phase 20 shipped:** token streaming for L0 + POV specialists; progress heartbeats for WR / combiners / defense; mid-chain steer; status wall stage workers.

Architecture docs: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md), [SCHEMA.md](SCHEMA.md), [PHASE_20_OPENER.md](PHASE_20_OPENER.md).

---

## Production incident (2026-07-12)

User ran **Research mode**, **L4 Full chain**, multi-POV request. Observed timeline:

| Elapsed | Stage (status wall) | Panel / subtitle |
|---------|---------------------|------------------|
| ~8m 17s | Combining (then Defense) | Combiner heartbeats worked (Phase 20) |
| 12m 35s+ | **Defense** (stuck) | `Quality checks passed (2/2) — formatting final answer…` |
| — | Presenting never highlighted | No completed Panel; input still blocked |

Status wall showed **Defense Delegator / Defense Review** badges while subtitle froze on the defense pass message. User perception: *"got stuck here"* after quality checks — not during combining.

**Session:** `7a480f12…` (partial ID from UI).

---

## Root cause analysis

### 1. `review_passed` is a visibility dead-end

Defense Review emits a Panel with `status: review_passed` and content from [`format_review_passed_content`](app/graph/defense_utils.py):

```python
return f"Quality checks passed ({passed}/{total}) — formatting final answer…"
```

The graph then routes to **presenter** ([`builder.py`](app/graph/builder.py): `defense_review` → `route_after_defense` → `presenter`).

Until presenter finishes, the frontend keeps the **last** in-flight Panel — the `review_passed` one ([`usePipelineStatus.ts`](frontend/src/hooks/usePipelineStatus.ts): `isInFlight` includes `review_passed`).

That Panel sets `pipeline_stage=defense`, so the status wall **never advances to Presenting** even though work moved on.

### 2. Presenter is silent during its heaviest step

[`presenter_node`](app/graph/nodes/presenter.py) does:

1. Deterministic formatting (`apply_list_format`, `build_pov_segments`) — fast
2. **`await generate_follow_up_options(...)`** — **blocking LLM call**, no `publish_panel`, no heartbeat
3. Returns single `status: completed` Panel

Phase 20 added heartbeats to combiners and defense **inside** their LLM calls. Presenter was **not** updated. The follow-up generator ([`follow_up_utils.py`](app/graph/follow_up_utils.py)) still uses `llm.generate()` with up to **3000 chars** of completed answer in the prompt.

On CPX11 this can be **another 2–5+ minute** Ollama call — completely invisible after the defense pass message.

### 3. Cumulative LLM budget on L4 multi-POV

Typical L4 Research run (2–3 POVs + search optional):

| # | Node | LLM? | Phase 20 visibility |
|---|------|------|---------------------|
| 1 | Wide Receiver | yes | heartbeat |
| 2–4 | POV specialists (serialized on Ollama lock) | yes | token stream |
| 5 | Combiner Mayor | yes | heartbeat |
| 6 | Combiner Micro | yes | heartbeat |
| 7 | Defense Review | yes | heartbeat |
| 8 | **Presenter follow-ups** | **yes** | **none** |
| 9 | Presenter formatting | no | — |

The **8th** sequential inference happens **after** the UI claims formatting is underway — user waits on defense copy while presenter blocks on chip generation.

### 4. Timeout math

- Worker soft limit: **900s** (15 min) — configurable via `PIPELINE_SOFT_TIME_LIMIT_SECONDS`
- Frontend client timeout: **900s** — [`useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts)
- Per-call Ollama timeout: **300s** — `OLLAMA_REQUEST_TIMEOUT_SECONDS`

8+ LLM calls × ~2–4 min each can still exceed 15 minutes on heavy prompts. The **presenter follow-up** is the last straw when combiners already consumed most of the budget.

---

## Phase 21 goal

**Close the presenter gap** — users must see **Presenting** stage activity and receive the **final answer** without a silent multi-minute wait after defense passes.

| Phase 20 baseline | Phase 21 adds |
|-------------------|---------------|
| Heartbeats on WR / combiners / defense | **Presenter progress** during follow-up LLM (or split delivery) |
| Status wall stage workers per `pipeline_stage` | **`review_passed` → Presenting** in UI; Presenter badge active |
| Completed Panel only after follow-ups finish | **Answer first**, chips second (recommended) |
| 15 min pipeline timeout | Optional **presenter time budget** / skip-LLM-follow-ups on CPX11 |

---

## Recommended deliverables

### Deliverable 1 — Two-phase presenter (preferred)

Split [`presenter_node`](app/graph/nodes/presenter.py):

1. **Phase A (immediate):** Publish `status: completed` Panel with final `content`, `pov_segments`, `content_format`, `pipeline_stage: done`, and **`DEFAULT_FOLLOW_UP_OPTIONS`** (static chips).
2. **Phase B (best-effort):** Run `generate_follow_up_options`; publish **Panel update** (same `panel_id`) with LLM chips + `follow_up_kinds`, or skip if interrupt/timeout.

**Why:** User reads the answer while chips generate; matches ChatGPT-style "response then suggestions."

**Celery / conversation:** `append_conversation_turn` after Phase A content is ready (worker already extracts from completed Panel).

### Deliverable 2 — Presenting-stage progress (if keeping single-phase)

If not splitting presenter:

- Publish `status: processing` Panel at `pipeline_stage=presenting` before follow-up LLM
- Wrap `generate_follow_up_options` with [`generate_with_progress_heartbeat`](app/graph/progress_utils.py) and label `**Presenter** — generating follow-up suggestions`

### Deliverable 3 — Status wall fix for `review_passed`

Frontend ([`usePipelineStatus.ts`](frontend/src/hooks/usePipelineStatus.ts)):

- When `status === "review_passed"`, treat `currentStage` as **`presenting`** (not `defense`)
- Show **Presenter** in `activeAgents`
- Subtitle: `Formatting final answer…` or heartbeat text, not stale defense pass string

Optional backend: defense `review_passed` Panel sets `pipeline_stage=presenting` instead of `defense`.

### Deliverable 4 — CPX11 fast path (env flag)

Add `SKIP_LLM_FOLLOW_UPS=true` (or auto when `OLLAMA_MODEL` contains `:1b`) to use [`build_fallback_follow_ups`](app/graph/follow_up_utils.py) only — no extra inference on small hardware.

Document in [`.env.prod.example`](.env.prod.example) and [deploy/SERVER_CHECKLIST.md](deploy/SERVER_CHECKLIST.md).

### Deliverable 5 — Timeout / observability

- Log presenter sub-phase timings: `format_ms`, `follow_up_llm_ms`, `total_presenter_ms`
- Worker warning when cumulative pipeline time &gt; 12 min before presenter starts
- Consider bumping soft limit to **1080s** (18 min) only if two-phase presenter is insufficient

---

## Out of scope for Phase 21

- Token streaming combiner JSON output
- Parallel Ollama (hardware limit)
- Moving follow-ups to a separate user-triggered action ("Suggest next steps" button)
- Cross-session presenter cache

---

## Test matrix (Phase 21)

| Scenario | Input / setup | Expect |
|----------|---------------|--------|
| L4 multi-POV happy path | Canonical UI design + Research + L4 | After defense pass, status wall → **Presenting** within 1s; **completed** Panel with answer within 5s; chips may arrive later |
| Two-phase chips | Mock slow follow-up LLM (5s delay) | `completed` Panel visible before chips; chips update same `panel_id` |
| `SKIP_LLM_FOLLOW_UPS` | Env true on worker | Presenter completes without extra LLM; fallback chips |
| Heartbeat-only path | If single-phase chosen | Subtitle updates every 10s during follow-up generation |
| `review_passed` UI | Defense emits review_passed | Status wall stage = Presenting, not Defense |
| Steer during presenter | Send new message during follow-up LLM | Cancelled; no conversation append |
| Phase 20 regression | L0 stream, combiner heartbeats, steer | Unchanged |
| Phase 19 regression | Drill-down, ranked list | Unchanged |

```bash
pytest tests/
# New:
pytest tests/test_presenter_delivery.py tests/test_follow_up_options.py -v
```

---

## Key files

| Area | Path |
|------|------|
| Presenter (main change) | [`app/graph/nodes/presenter.py`](app/graph/nodes/presenter.py) |
| Follow-up LLM | [`app/graph/follow_up_utils.py`](app/graph/follow_up_utils.py) |
| Defense pass message | [`app/graph/defense_utils.py`](app/graph/defense_utils.py) (`format_review_passed_content`) |
| Progress heartbeat | [`app/graph/progress_utils.py`](app/graph/progress_utils.py) |
| Panel stream | [`app/graph/panel_stream.py`](app/graph/panel_stream.py) |
| Status wall | [`frontend/src/hooks/usePipelineStatus.ts`](frontend/src/hooks/usePipelineStatus.ts) |
| In-flight / merge | [`frontend/src/hooks/useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts) |
| Worker / timeout | [`app/worker.py`](app/worker.py), [`app/core/config.py`](app/core/config.py) |
| Graph routing | [`app/graph/builder.py`](app/graph/builder.py), [`app/graph/routing.py`](app/graph/routing.py) |

**New files (expected):**

| Area | Path |
|------|------|
| Presenter delivery tests | `tests/test_presenter_delivery.py` |
| Optional env docs | `.env.prod.example`, `deploy/SERVER_CHECKLIST.md` |

---

## Constraints

- Follow `.cursorrules` (async, Pydantic, Celery for heavy work).
- **Backward compatible:** `follow_up_options` remains `list[str]`; late chip update is optional client enhancement.
- Completed Panel content must not regress Phase 18 `pov_segments` or Phase 19 list format.
- Do not block `completed` on follow-up LLM failure — always ship answer with fallback chips.
- English for user-facing strings.
- Never return `{}` from graph nodes.

---

## Verify on production

After deploy to `5.78.186.223`:

1. Hard refresh (`Ctrl+Shift+R`).
2. Research + L4 + multi-POV prompt (same class as incident).
3. Confirm status wall moves **Defense → Presenting → Done** without 2+ minute freeze on defense subtitle.
4. Confirm **completed** answer appears before or with chips (per chosen deliverable).
5. `docker compose ... logs -f worker` — look for `presenter` timing logs; no 15-minute soft limit during presenter-only work.

---

## Quick win (optional before full Phase 21)

If a hotfix is needed before the full phase: set `SKIP_LLM_FOLLOW_UPS=true` in `.env.prod` and redeploy — presenter becomes deterministic-only and should complete in seconds after defense. Trade-off: static follow-up chips instead of LLM-generated ones.
