# TESS Engine — Multi-cloud ops hardening (session 5 opener)

## Context

Control plane on Hetzner (`5.78.186.223`). AWS standby (`i-0360ab28632a3c4a0`,
EIP `18.227.172.81`, `us-east-2`) is stopped-by-default.

**Session 1–2 shipped (2026-07-21):** SSH/EIP/chaos; mid-session failover
observed as **silent continue** (no `provider_changed` banner); `high_latency`
score-only.

**Session 3 shipped (2026-07-21):**


| #   | Item              | Outcome                                                                 |
| --- | ----------------- | ----------------------------------------------------------------------- |
| 5   | External uptime   | UptimeRobot `803559917` **Up**; HEAD+GET `/health` (405 fix deployed)   |
| 6   | Daily drift check | `aws_standby.py drift-check` + tests + docs                             |


**Session 4 shipped (2026-07-21):**


| #   | Item                         | Outcome                                                              |
| --- | ---------------------------- | -------------------------------------------------------------------- |
| 7   | Per-operator admin tokens    | `OPS_ADMIN_TOKENS` + legacy; hard GET gating; `/ops/routing/notice`  |


Prior openers: [MULTI_CLOUD_HARDENING_S4_OPENER.md](MULTI_CLOUD_HARDENING_S4_OPENER.md),
[MULTI_CLOUD_HARDENING_S3_OPENER.md](MULTI_CLOUD_HARDENING_S3_OPENER.md),
[MULTI_CLOUD_HARDENING_S2_OPENER.md](MULTI_CLOUD_HARDENING_S2_OPENER.md),
[MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md),
[app/ops/failover.py](app/ops/failover.py),
[frontend/src/hooks/useWebSocket.ts](frontend/src/hooks/useWebSocket.ts).

Architecture / product chain: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md).
This session is **ops hardening / demo UX**, not LangGraph/POV work.

---

## Known gaps (carry forward)

### A. Mid-session `provider_changed` never reaches the browser (confirmed S2)

Failover clears assignments and switches `active_provider_id`, but
[`app/main.py`](app/main.py) `_ops_probe_loop` only **logs** — it does **not**
push `type: "provider_changed"` onto open WebSockets. Frontend already handles
the message ([`useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts) + banner in
[`App.tsx`](frontend/src/App.tsx)). Schema exists:
[`ProviderChangedMessage`](app/ops/models.py).

**This session — primary goal.**

### B. No operator UI for take-offline / force-active

Take-offline today is curl (`simulate-unhealthy`, `POST /ops/routing/active/{id}`).
Need a **minimal admin surface** so a meeting demo is one click, not a terminal.

### C. Secrets manager / full ops status page

Deferred: Secrets Manager after env tokens prove out; **ops status page**
(providers, scores, events, uptime link) is **Session 6**.

---

## This session goal

Make failover **visible to users** and **clickable for operators**.

### 8. Push `provider_changed` on open WebSockets when routing flips

When `_switch` / `force_active_provider` / probe-loop failover succeeds:

1. Build `ProviderChangedMessage` (already returned by failover helpers).
2. Deliver JSON to **all open browser WebSockets** on the control plane
   (or all sessions still connected to this host).

**Preferred approach (keep small):**

- Publish the message on a Redis channel (e.g. `ops:provider_changed`) from
  failover / force-active / simulate path after switch.
- In [`app/api/ws.py`](app/api/ws.py), each accepted connection also subscribes
  to that channel (alongside the session Pub/Sub) and `send_json`s the payload.

Avoid a process-local connection set unless Redis fan-out is awkward on CPX11 —
Redis is already the panel bus.

**Verify (browser):** open Tess → start L4 job → Take offline / simulate on
active provider → within a few probes, banner shows (not silent continue).
Confirm with AWS woken if testing real standby; `simulate-unhealthy` alone is
enough to prove the **push** even if the job keeps finishing on Hetzner.

Unit-test: publish → mock websocket receive, or pure helper that serializes
`ProviderChangedMessage` + channel name (same style as other ops unit tests).

### 9. Minimal “take offline” admin UI

A **small** operator page (not a full dashboard — that is Session 6):

| Control | Wraps |
|---------|--------|
| Take offline (active) | `POST /ops/providers/{id}/simulate-unhealthy?enabled=true` |
| Bring online | clear simulate / chaos |
| Force active (standby) | `POST /ops/routing/active/{id}` |

**Auth:** Bearer from `OPS_ADMIN_TOKEN` or a named token in `OPS_ADMIN_TOKENS`
entered once per browser session (localStorage or prompt) — **no** embed of
secrets in the SPA build. Gate all calls with `Authorization: Bearer …`.

**Placement (pick one, keep thin):**

- Route `/ops-ui` served as a tiny React page or static HTML under Caddy, **or**
- A collapsible “Ops” panel behind a query flag / separate Vite entry —

Prefer **one dedicated lightweight page** over cluttering the main Tess chat UI.

Show current `active_provider_id` (from gated `GET /ops/routing` with the token)
and last action result. No charts, no event history dump (Session 6).

---

## Definition of done (this session)

- [ ] On failover / force-active, open WS clients receive `provider_changed`
- [ ] Browser demo: banner appears (no longer silent-only under simulate)
- [ ] Minimal take-offline / bring-online / force-active UI with Bearer auth
- [ ] Unit test(s) for publish/serialize path; docs note in MULTI_CLOUD.md
- [ ] No full ops status page; no Secrets Manager; no seamless migration

---

## Ordered backlog (later sessions)

| #   | Item                                              | Notes                          |
| --- | ------------------------------------------------- | ------------------------------ |
| 1–7 | SSH / chaos / failover / uptime / drift / tokens  | **Done** (S1–S4)               |
| 8–9 | `provider_changed` WS + take-offline admin UI     | **This session**               |
| 10  | Ops status page (providers, scores, events, uptime link) | **Session 6**            |
| —   | Secrets manager for admin tokens                  | After demo path is credible    |
| —   | Seamless mid-session migration                    | Still deferred                 |

---

## Out of scope this session

- Phase 21 presenter / follow-up work
- Full monitoring dashboard / graphs (Session 6)
- AWS Secrets Manager / Vault
- Auto-stop on drift
- Seamless session migration
- Polished design-system ops console

---

## Quick pointers

| Concern                 | Location |
| ----------------------- | -------- |
| Failover / force-active | [`app/ops/failover.py`](app/ops/failover.py) |
| Probe loop              | [`app/main.py`](app/main.py) `_ops_probe_loop` |
| WebSocket endpoint      | [`app/api/ws.py`](app/api/ws.py) |
| Message schema          | [`app/ops/models.py`](app/ops/models.py) `ProviderChangedMessage` |
| Frontend handler        | [`frontend/src/hooks/useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts) |
| Simulate / chaos APIs   | [`app/api/ops.py`](app/api/ops.py) |
| Admin auth              | [`app/ops/admin_auth.py`](app/ops/admin_auth.py) |
| Control plane           | `http://5.78.186.223` |
| UptimeRobot             | monitor `803559917` (Up) |
