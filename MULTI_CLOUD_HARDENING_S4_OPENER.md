# TESS Engine — Multi-cloud ops hardening (session 4 opener)

## Context

Control plane on Hetzner (`5.78.186.223`). AWS standby (`i-0360ab28632a3c4a0`,
EIP `18.227.172.81`, `us-east-2`) is stopped-by-default.

**Session 1–2 shipped (2026-07-21):** SSH/EIP/chaos; mid-session failover
(silent continue); `high_latency` score-only.

**Session 3 shipped (2026-07-21):**


| #   | Item                    | Outcome                                                                 |
| --- | ----------------------- | ----------------------------------------------------------------------- |
| 5   | External uptime         | UptimeRobot monitor `803559917` **live**; alert `jesse.malma@gmail.com` |
| 6   | Daily drift check       | `aws_standby.py drift-check` + unit tests; docs; dry-run stopped → 0    |


Prior openers: [MULTI_CLOUD_HARDENING_S3_OPENER.md](MULTI_CLOUD_HARDENING_S3_OPENER.md),
[MULTI_CLOUD_HARDENING_S2_OPENER.md](MULTI_CLOUD_HARDENING_S2_OPENER.md),
[MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md),
[app/api/ops.py](app/api/ops.py).

Architecture / product chain: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md).
This session is **ops hardening**, not LangGraph/POV work.

---

## Known gaps (carry forward)

### A. Mid-session `provider_changed` never reaches the browser (confirmed S2)

Failover does not push `type: "provider_changed"` onto open WebSockets.
**Not in this session** — next after item 7.

### B. Secrets manager still deferred

Tokens remain in `.env.prod` (multi-operator env map). AWS Secrets Manager /
Vault is a later hardening step.

---

## This session goal

Backlog **item 7 (hard):** per-operator admin tokens + gate sensitive GETs.

Decisions: **1A** env multi-token (no Secrets Manager); **2C** require admin on
sensitive reads (not only mutations).

### 7. Per-operator admin tokens (env) + hard ops surface

1. `OPS_ADMIN_TOKENS` JSON `{"jesse":"<secret>",...}` plus legacy
   `OPS_ADMIN_TOKEN` → operator id `legacy`.
2. `require_admin` FastAPI dependency returns `operator_id`; fail closed when
   both env vars empty.
3. Gate sensitive GETs (`/ops/providers`, events, health-logs, full routing,
   compare list, seamless-migration) and `POST /ops/sessions/{id}/assign`.
4. Attach `operator_id` on mutation/assign OpsEvents.
5. Public **`GET /ops/routing/notice`** `{ws_base_url, sessions_dropped_last}`
   for the frontend reconnect banner; update `useWebSocket.ts`.

**Do not** implement Secrets Manager or `provider_changed` WS push this session.

---

## Definition of done (this session)

- [x] Multi-operator env tokens + legacy fallback; unit tests green
- [x] Sensitive GETs + session assign require admin; audit `operator_id`
- [x] `/ops/routing/notice` public; frontend uses it
- [x] Docs/examples/checklist + this opener; ROADMAP points here
- [x] No Secrets Manager; no `provider_changed` WS

---

## Ordered backlog (later sessions)

| #   | Item                                           | Notes                                      |
| --- | ---------------------------------------------- | ------------------------------------------ |
| 1–6 | SSH / EIP / chaos / failover / uptime / drift  | **Done** (S1–S3)                           |
| 7   | Per-operator admin tokens + hard GET gating    | **This session**                           |
| —   | Push `provider_changed` to open WS on failover | Next after 7                               |
| —   | Secrets manager for admin tokens               | After env multi-token ships                |

---

## Out of scope this session

- Phase 21 presenter / follow-up work
- `provider_changed` WS push
- AWS Secrets Manager / Vault / hashed token store
- Per-role RBAC (read-only vs chaos)
- Frontend ops admin UI

---

## Quick pointers

| Concern              | Location                                                       |
| -------------------- | -------------------------------------------------------------- |
| Ops routes           | [`app/api/ops.py`](app/api/ops.py)                             |
| Admin auth           | [`app/ops/admin_auth.py`](app/ops/admin_auth.py)               |
| Frontend notice      | [`frontend/src/hooks/useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts) |
| Control plane        | `http://5.78.186.223` (`/health`, `/ops`)                      |
