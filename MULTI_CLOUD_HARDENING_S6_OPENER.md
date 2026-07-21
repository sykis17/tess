# TESS Engine — Multi-cloud ops hardening (session 6 opener)

## Context

Control plane on Hetzner (`5.78.186.223`). AWS standby (`i-0360ab28632a3c4a0`,
EIP `18.227.172.81`, `us-east-2`) is stopped-by-default.

**Session 1–4 shipped (2026-07-21):** SSH/EIP/chaos; UptimeRobot `803559917`;
drift-check; per-operator admin tokens + hard GET gating;
`/ops/routing/notice`.

**Session 5 shipped (2026-07-21):**


| #   | Item                         | Outcome                                                                 |
| --- | ---------------------------- | ----------------------------------------------------------------------- |
| 8   | `provider_changed` WS push   | Redis `ops:provider_changed` → open sockets; banner on failover         |
| 9   | Take-offline admin UI        | Static `/ops-ui/` (Bearer `localStorage`); Caddy handle + recreate fix  |


Prior openers: [MULTI_CLOUD_HARDENING_S5_OPENER.md](MULTI_CLOUD_HARDENING_S5_OPENER.md),
[MULTI_CLOUD_HARDENING_S4_OPENER.md](MULTI_CLOUD_HARDENING_S4_OPENER.md),
[MULTI_CLOUD_HARDENING_S3_OPENER.md](MULTI_CLOUD_HARDENING_S3_OPENER.md),
[MULTI_CLOUD_HARDENING_S2_OPENER.md](MULTI_CLOUD_HARDENING_S2_OPENER.md),
[MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md),
[app/api/ops.py](app/api/ops.py),
[frontend/public/ops-ui/index.html](frontend/public/ops-ui/index.html).

Architecture / product chain: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md).
This session is **ops hardening / operator visibility**, not LangGraph/POV work.

---

## Known gaps (carry forward)

### A. No read-only ops status surface

Operators can **act** via `/ops-ui/` (take offline / force active / probe) but
cannot **see** at a glance:

- which providers exist and which is active
- latest health **scores** / latency / healthy flags
- recent **events** (failover, chaos, probe_manual, …)
- external **uptime** status without leaving Tess

Today that is curl against gated GETs, or the UptimeRobot dashboard in another
tab.

### B. Secrets manager still deferred

Tokens remain in `.env.prod` (`OPS_ADMIN_TOKENS` / legacy). AWS Secrets Manager
/ Vault after the demo path is credible.

### C. Seamless mid-session migration

Still deferred (`GET /ops/seamless-migration`). Failover v1 drops sessions;
`provider_changed` banner + resubmit is the product story.

---

## This session goal

Backlog **item 10:** a read-oriented **ops status page** so a meeting can show
fleet health without curl or a third-party console as the primary view.

Keep `/ops-ui/` as the **action** hammer (take offline). Status is the
**visibility** surface — do not merge them into one overloaded page unless it
stays clearly two sections.

### 10. Ops status page (providers, scores, events, uptime link)

**Placement (concrete):** static page at `/ops-status/` under
`frontend/public/ops-status/index.html` (same pattern as `/ops-ui/` — always
copied into `dist`, Caddy must serve it without SPA fallback). Link both pages
to each other (“Actions” ↔ “Status”).

**Auth:** same Bearer + `localStorage` key as `/ops-ui/`
(`tess_ops_admin_token`) — reuse, do not invent a second token store.

**Data (existing admin APIs only — no new backend unless a thin aggregator helps):**

| Section | Source |
|---------|--------|
| Active + policy summary | `GET /ops/routing` |
| Provider list (id, name, type, enabled, simulate/chaos flags) | `GET /ops/providers` |
| Latest scores / latency / healthy | Latest rows from `GET /ops/health-logs?limit=…` (or per-provider latest snapshot if already easy from store) |
| Recent events | `GET /ops/events?limit=50` (failover, chaos, probe_manual, …) |
| External uptime | Link out to UptimeRobot monitor `803559917` (documented URL in MULTI_CLOUD.md) — **do not** scrape UptimeRobot |

**UI rules (keep thin):**

- One page, utilitarian styling (match `/ops-ui/` light cards — not a design-system console).
- Tables or simple lists — **no** charts, graphs, or live WebSocket status bus this session.
- Show `active_provider_id`, last failover from/to + `sessions_dropped_last` when present.
- Refresh button (+ optional auto-refresh every ~30s, off by default).
- Empty / error states for 401/403/503 same as ops-ui (clear token on auth fail).

**Caddy / deploy:**

- Add `handle /ops-status*` (mirror `/ops-ui*`) in `Caddyfile` + `Caddyfile.ip`.
- `deploy.sh` already force-recreates Caddy; add a build check that
  `dist/ops-status/index.html` exists (same as ops-ui).

**Docs:** note `/ops-status/` in [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md);
UptimeRobot link in the page footer/header.

**Verify:** open `/ops-status/` with token → see providers + scores + recent
events; click uptime link → UptimeRobot monitor. From `/ops-ui/` take offline +
probe → refresh status → new event / score change visible.

Unit tests: only if a small pure helper is introduced (e.g. “pick latest
snapshot per provider”); otherwise manual + docs is enough — no live UptimeRobot
API tests.

---

## Definition of done (this session)

- [ ] `/ops-status/` page with Bearer auth (shared token with `/ops-ui/`)
- [ ] Shows providers, active routing, latest scores/health, recent events
- [ ] UptimeRobot monitor link (803559917) visible on the page
- [ ] Caddy serves `/ops-status/` without falling through to chat SPA
- [ ] Cross-links between `/ops-ui/` and `/ops-status/`
- [ ] Docs note in MULTI_CLOUD.md; ROADMAP points here when started
- [ ] No Secrets Manager; no seamless migration; no charts / full monitoring suite

---

## Ordered backlog (later sessions)

| #   | Item                                              | Notes                       |
| --- | ------------------------------------------------- | --------------------------- |
| 1–9 | SSH / chaos / uptime / drift / tokens / WS / take-offline UI | **Done** (S1–S5) |
| 10  | Ops status page (providers, scores, events, uptime link) | **This session**     |
| —   | Secrets manager for admin tokens                  | After demo path is credible |
| —   | Seamless mid-session migration                    | Still deferred              |
| —   | Charts / SLO burn / multi-window ops console      | After status page proves out |

---

## Out of scope this session

- Phase 21 presenter / follow-up work
- AWS Secrets Manager / Vault
- Auto-stop on drift
- Seamless session migration
- Time-series charts, Grafana, or Prometheus
- Embedding take-offline controls into the status page as a second full admin UI
  (link to `/ops-ui/` instead)
- Polished design-system ops console

---

## Quick pointers

| Concern              | Location |
| -------------------- | -------- |
| Providers / routing  | [`app/api/ops.py`](app/api/ops.py) `GET /ops/providers`, `GET /ops/routing` |
| Scores / probes      | `GET /ops/health-logs` + [`HealthSnapshot`](app/ops/models.py) |
| Events               | `GET /ops/events` + [`OpsEvent`](app/ops/models.py) |
| Take-offline UI      | [`frontend/public/ops-ui/index.html`](frontend/public/ops-ui/index.html) |
| Admin auth           | [`app/ops/admin_auth.py`](app/ops/admin_auth.py) |
| Caddy static + SPA   | [`deploy/Caddyfile.ip`](deploy/Caddyfile.ip) (`/ops-ui*` pattern) |
| UptimeRobot          | monitor `803559917` — see [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md) External uptime |
| Control plane        | `http://5.78.186.223` |
| Deploy gotcha        | Dirty server files block `git pull`; `chmod +x deploy/deploy.sh`; force-recreate Caddy |
