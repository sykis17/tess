# TESS Engine — Multi-cloud Session 9 opener

## Wake reliability, Dual demo path & seamless stretch

## Context

Session 8 shipped Dual XOR Performance, optional auto-wake, Sleep-all resting
cost, and a power trail on `/ops-ui/`. Merged as PR #6 + #7 (last-healthy
score for auto-wake). Deployed on Hetzner control plane `5.78.186.223`.

**Live demo findings (2026-07-23) that set this session’s priority:**

| Observation | Likely cause |
|-------------|--------------|
| **Enable Dual** did not work with only Hetzner healthy | Dual requires ≥2 **healthy online** providers. AWS/GCP slept → no peer. |
| **Wake AWS** showed `standby_wake_enqueued` only | API returns after Celery `.delay()`; success/fail is async. No clear “waking… / healthy / failed” UI state. |
| No Dual after waiting on Wake | If wake never reaches `standby_wake` (ok) or provider never probes healthy, Dual still cannot enable. |
| Trail: `no_healthy_history_refuse_blind_wake` | Auto-wake correctly refused; standbys had no fresh **healthy** history after long sleep/failed probes. Manual Wake must complete first. |
| WS line `ws://127.0.0.1:8000` on ops-ui | Hetzner provider `ws_base_url` / bootstrap still points at loopback for chat clients — confusing mid-demo (separate from Dual gate). |

Prior: [MULTI_CLOUD_HARDENING_S8_OPENER.md](MULTI_CLOUD_HARDENING_S8_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).

This session is **ops reliability + demo UX first**; shared Redis / seamless is
Track C (may slip to S10 if wake/Dual path is still broken).

### Workflow (mandatory)

1. Branch **before** commits (e.g. `cursor/s9-wake-dual-seamless`)
2. Draft PR via `gh` → review → merge
3. Deploy already-merged `main` to Hetzner with:
   ```powershell
   ssh -i $env:USERPROFILE\.ssh\hetzner_tess -o IdentitiesOnly=yes root@5.78.186.223 "cd /opt/tess-engine && git pull && ./deploy/deploy.sh"
   ```

---

## Honest baseline (do not paper over)

| Fact | Implication |
|------|-------------|
| Dual enable = hard gate on ≥2 healthy online | Sleep all → Dual is **disabled by design** until a standby is awake **and** `/health` green. |
| Wake is Celery → `scripts/aws_standby.py` on the **worker** host | Enqueue ≠ EC2 started. Missing AWS creds / script failure → only `_failed` events if the task runs at all. |
| OpsStore + trail are CP-local | Trail can show `enqueued` forever if the worker never processes the task. |
| Per-stack Redis | Even with Dual working, losing a home still drops that home’s sessions until shared Redis. |
| CP still single-home on Hetzner | Session 9 does **not** HA the control plane. |

---

## Product intent

### Track A — Wake/sleep observability + reliability (core)

**Goal:** Mid-demo, “Wake AWS” has an unambiguous lifecycle: queued → running →
healthy | failed, with the same FAILED vs intentional-sleep distinction.

| Deliverable | Detail |
|-------------|--------|
| Status model | Persist per-provider power state: `idle \| queued \| waking \| sleeping \| healthy \| failed` (+ last error, task id, updated_at). |
| Events | Always emit terminal `standby_wake` / `standby_wake_failed` (and sleep equivalents); trail must not stop at `_enqueued`. |
| Ops UI | Per-row status badge; disable Dual until ≥2 healthy; surface last wake error inline (not only JSON “Last action”). |
| Worker health | Document + verify Celery worker has AWS/GCP creds + `AWS_STANDBY_*` / `GCP_STANDBY_*` on Hetzner; fail loud in trail if script missing/creds refuse. |
| Probe after wake | On wake success, force connect/probe so Dual’s healthy gate can pass without waiting for the next interval alone. |
| Tests | Unit tests for state transitions; no live cloud required. |

**Pass criteria (Track A):**

- [ ] After Wake, trail shows terminal success or **Wake FAILED** within soft timeout (not stuck on enqueued)
- [ ] Ops-ui row shows waking/healthy/failed without reading raw JSON
- [ ] Documented worker-creds checklist; failed wake names the failure class (creds / script / timeout / health)

### Track B — Dual demo path (same session if A is green)

**Goal:** Operator can go Sleep → Wake one standby → Enable Dual without guessing.

| Deliverable | Detail |
|-------------|--------|
| Enable Dual UX | If &lt;2 healthy: button disabled or 400 detail becomes a visible banner: “Wake AWS or GCP first (need 2 healthy homes).” |
| Optional helper | “Prepare Dual” = wake chosen peer → wait healthy → `POST /ops/routing/dual`. |
| Bootstrap WS | Fix or label Hetzner `ws_base_url` so ops-ui does not advertise `ws://127.0.0.1:8000` as the public chat home. |
| Demo script | Written steps: Sleep all → Wake AWS → wait healthy → Enable Dual → open two chats → confirm Home A/B. |

**Pass criteria (Track B):**

- [ ] With AWS healthy + Hetzner healthy, Enable Dual succeeds and badges show both homes
- [ ] With only Hetzner healthy, UI explains why Dual is blocked
- [ ] Dual home-loss behavior from S8 remains (failed-home-only clear)

### Track C — Seamless-as-possible (deferred to S10)

**Status:** Explicitly deferred until Tracks A+B demo-pass on Hetzner. Do not
start shared Redis work in the same PR as wake/Dual UX.

**Goal:** Same as S8 Track C — make `GET /ops/seamless-migration` honest.

1. Shared session Redis (or replicated conversation keys) reachable from primary
   and secondary stacks — **not** “Hetzner Redis only” if Hetzner is the failure
   domain (managed Redis or neutral VM).
2. On home loss / promote: client reconnects WS with same `session_id`.
3. Secondary loads history from shared store; in-flight Celery/LangGraph migrate
   remains out of scope (revoke + resubmit OK).
4. Flip `seamless_migration_status()` when (1)+(2)+(3) are real.

**Pass criteria (Track C, if started):**

- [ ] Topology + budget/provider chosen and documented in MULTI_CLOUD.md
- [ ] Mid-chat lose Dual home → reconnect → history present
- [ ] `/ops/seamless-migration` reflects reality

If Track C slips: Dual/wake ship with copy still saying reconnect until shared Redis.

---

## Locked decisions to confirm at session start

1. **S9 priority order:** Track A (wake truth) → Track B (Dual demo) → Track C
   (seamless). Do not start C until A demo passes on Hetzner.
2. **Wake from ops-ui stays Celery-on-worker** (not laptop SSH). Fix creds/path
   on the CP worker; do not silently fall back to “enqueue and hope.”
3. **Shared Redis host for Track C** — pick managed (Upstash / ElastiCache /
   Memorystore) or a small neutral VM; not Hetzner-app-Redis alone.
4. **Dual still requires two healthy online homes** — no “Dual with sleeping peer.”

---

## Out of scope (Session 9)

- Control-plane HA / moving OpsStore off Hetzner
- Vendor Monitoring APIs (Step 4 stays skipped)
- Secrets manager / Vault (worker env remains `.env.prod` for now)
- In-flight LangGraph graph migration between brokers
- Auto-sleep of a healthy Performance winner (Sleep / Sleep all stay explicit)

---

## Suggested implementation pointers

| Concern | Location |
|---------|----------|
| Dual enable gate | [`app/ops/routing_modes.py`](app/ops/routing_modes.py) `enable_dual` |
| Wake/sleep scripts | [`app/ops/standby_power.py`](app/ops/standby_power.py), [`scripts/aws_standby.py`](scripts/aws_standby.py) |
| Celery tasks | [`app/worker.py`](app/worker.py) `ops_standby_wake` / `ops_standby_sleep` |
| Ops UI trail | [`frontend/public/ops-ui/index.html`](frontend/public/ops-ui/index.html) |
| Provider WS URL | bootstrap / `CloudProvider.ws_base_url` for `prov_hetzner_local` |
| Seamless stub | [`app/ops/balancer.py`](app/ops/balancer.py) `seamless_migration_status` |
| Conversation Redis | [`app/core/conversation.py`](app/core/conversation.py) |

---

## Demo script (when Tracks A+B done)

1. Sleep all → confirm intentional sleep in trail; Dual disabled/explained.
2. Wake AWS → trail: enqueued → **standby_wake** (ok) → row badge healthy.
3. Enable Dual → Home A Hetzner / Home B AWS; open two chats; confirm split.
4. (Optional) Performance + auto-wake within 1h of a healthy score.
5. Sleep all → resting cost; clear chaos.

---

## Open questions for the human

- Shared Redis budget/provider preference if Track C starts this session?
- Keep button labels Dual / Performance, or rename before more public demos?
- Is worker AWS access already on Hetzner `.env.prod`, or still laptop-only?
