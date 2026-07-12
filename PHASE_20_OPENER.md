# TESS Engine — Phase 20 Session Opening Message

## Context

Phases 1–19 are complete. The live graph runs POV agents, combiners, defense, presenter, product modes, chain profiles (L0–L4), status wall, results wall, POV segments, and interactive follow-ups.

**Phase 20 goal:** Stream **token-level partial content** for L0 direct responses and POV specialists; allow **mid-chain steer** by sending a new message while processing; tune for **CPX11** (4 GB RAM) production constraints.

| Phase 19 baseline | Phase 20 adds |
|-------------------|---------------|
| Node-level Panel updates via `astream(updates)` | **Growing `content`** on `status: processing` via `is_streaming` deltas |
| `llm.generate()` everywhere | `llm.stream()` for **direct_responder** + **run_specialist** |
| Input disabled while `isProcessing` | **Send while processing** cancels in-flight task |
| `interruption_flag` in GraphState (unused) | Redis interrupt flag + Celery task revoke |
| Progress text only during combiners | Combiners/defense/WR unchanged (JSON nodes, no token stream) |

Architecture docs: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md), [SCHEMA.md](SCHEMA.md).

---

## Deliverables

| # | Feature | User experience |
|---|---------|-----------------|
| 1 | **Token streaming (L0)** | L0 chain profile — answer text grows token-by-token before `completed` |
| 2 | **Token streaming (specialists)** | During `agents` stage, POV specialist content grows in the processing Panel |
| 3 | **Mid-chain steer** | Send a new message while processing → previous run cancelled, new run starts |
| 4 | **CPX11 polish** | 75 ms stream throttle; `llama3.2:1b` default; worker concurrency 1 |

---

## Schema changes

| Field | Type | Description |
|-------|------|-------------|
| `is_streaming` | `bool` (default `false`) | When `true`, `content` is a **delta** appended client-side to the same `panel_id` |

New WebSocket envelope:

```json
{ "type": "cancelled", "message": "Previous request cancelled — processing your new message." }
```

---

## Key files

| Area | Path |
|------|------|
| Stream helper | `app/graph/stream_utils.py` |
| Session control | `app/core/session_control.py` |
| L0 streaming | `app/graph/nodes/direct_responder.py` |
| Specialist streaming | `app/agents/base.py` |
| Worker interrupt | `app/worker.py` |
| WS steer dispatch | `app/api/ws.py` |
| Frontend merge | `frontend/src/hooks/useWebSocket.ts` |
| Config | `app/core/config.py` (`stream_throttle_ms`) |
| Tests | `tests/test_stream_utils.py`, `tests/test_session_control.py`, `tests/test_interruption.py` |

---

## Test matrix (Phase 20)

| Scenario | Input / action | Expect |
|----------|----------------|--------|
| L0 stream | `chain_profile: L0`, any prompt | Processing Panel `content` grows; `is_streaming: true` deltas; final `completed` |
| Specialist stream | L4 multi-POV prompt | During `agents` stage, content grows on processing Panel |
| Steer | Send long L4 prompt, immediately send shorter prompt | `cancelled` envelope; second Panel completes |
| Combiner regression | L4 multi-POV | Combiner stages still show progress text (no token stream) |
| Phase 19 regression | Completed Panel | `follow_up_options`, drill-down, ranked lists |
| Backward compat | Panel without `is_streaming` | UI replaces content as before |

```bash
pytest tests/
```

---

## Constraints

- Follow `.cursorrules` (async, Pydantic, Celery for heavy work, modular structure).
- **Backward compatible:** `is_streaming` optional; clients without support replace Panel content.
- Do not stream JSON-producing nodes (WR, combiners, defense).
- Cancelled runs must **not** append conversation history.
- English for user-facing strings and code comments.
- Never return `{}` from graph nodes.

---

## Out of scope (post–Phase 20)

- Token streaming for combiners / defense / WR
- Explicit Stop button (send-to-steer is v1)
- Cross-session task persistence
- ETA prediction / animated graph visualization

---

## Verify on production

See [deploy/SERVER_CHECKLIST.md](deploy/SERVER_CHECKLIST.md). After deploy:

1. L0 streaming smoke test
2. L4 multi-POV specialist streaming during `agents` stage
3. Steer test (send while processing)
4. Phase 17–19 regression checks
5. `docker compose ... logs -f worker` — no OOM / revoke errors
