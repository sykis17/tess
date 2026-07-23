# TESS Engine — Multi-cloud Session 8 opener

## Dual mode & Performance routing

**Status (branch `cursor/dual-mode-performance-routing`):** Tracks A+B
**implemented and unit-tested**, including optional Performance auto-wake,
wake/sleep ops API, Sleep-all resting cost, and distinct Wake FAILED vs
intentional-sleep UI. Track C (shared Redis / seamless) remains Session 9.
Authoritative ops behavior: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).

## Context

Control plane on Hetzner (`5.78.186.223`). Failover v1 is proven (Sessions 1–7):
one `active_provider_id`, consecutive-failure threshold, score floor from
`min_score_for_healthy`, three-way chaos validated. Standbys are
**stopped-by-default** for cost; they *can* all run at once as healthy
standbys, but only one is the active routing target under `active_only`.

**Shipped since Session 7 (not a substitute for this session):**

| Item | Notes |
|------|--------|
| `/architecture/` ADR page | Self-report, thin adapters, failover, onboarding saga |
| Score floor SoT | Prober uses `policy.min_score_for_healthy` (no hardcoded 40) |
| Landing at `/` | Links to `/chat`, `/architecture/`, ops pages |
| CP limitation documented | Ops state = in-process + Redis on the **CP host**; app failover ≠ CP HA |

Prior openers: [MULTI_CLOUD_HARDENING_S7_OPENER.md](MULTI_CLOUD_HARDENING_S7_OPENER.md)
… [MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).  
Public narrative: http://5.78.186.223/architecture/

This session is **routing-policy + ops-ui product work**, not LangGraph/POV.

### Workflow (mandatory)

1. Branch **before** commits (e.g. `cursor/dual-mode-performance-routing`)
2. Draft PR via `gh` → review → merge
3. Deploy already-merged `main` to Hetzner (wake AWS/GCP only when testing)

---

## Product intent (locked)

### Dual mode — two concurrent chat homes

1. Start with whatever is forced active (often Hetzner) as one home.
2. Operator enables **Dual mode** → second home = **next-best** healthy online
   server (or explicit `peer_id`).
3. New sessions sticky-hash across the two homes (not a single writer + promote
   target). Existing sessions stay put until their home fails.
4. **Home loss (locked):** clear **only** sessions assigned to the failed home
   (`clear_assignments_for_provider`). Survivor-home sessions are **not**
   reshuffled. Recompute Dual pool = `{survivor, next_best}` if a third healthy
   online exists (new peer is for **new** assignments only); else exit Dual →
   `active_only` on survivor. Emit `provider_changed` for the failed home’s
   clients.
5. Seamless continuation still requires shared Redis (**Session 9 / Track C**).

### Performance — either/or with Dual

Operator enables **Performance** → among live healthy **online** servers, the
best-scoring one becomes active; monitors and switches with anti-flap.
Enabling Performance clears Dual and vice versa.

Optional **auto-wake** (`?auto_wake=true`): may enqueue one Celery wake for an
offline AWS/GCP whose *fresh* last score beats the incumbent (see locked
defaults below). Default remains online-only.

---

## Honest baseline (do not paper over)

| Fact today | Implication |
|------------|-------------|
| Conversation history + Celery broker = **per-stack** Redis | Dual two-homes ≠ shared conversation store. |
| `GET /ops/seamless-migration` → `available: false` | Home loss still drops sessions on that home only. |
| Control plane lives on Hetzner | Dual/Performance route **app stacks**. They do **not** HA the CP. |
| Wake/sleep runs on **Celery worker** | Cloud creds must live on the worker host, not only `web` / laptop. |

**Seamless is a dependency, not a button.** Dual without shared session Redis
is still “reconnect + resubmit” for sessions on a lost home.

---

## Locked decisions

1. **Dual = two concurrent chat homes** (sticky hash over active + next-best).
2. **Dual XOR Performance** — separate functions; enabling one clears the other.
3. **Track C deferred (S9)** — no shared Redis this session.
4. **Dual home loss** — drop **failed home only**; **no** full Dual assignment
   clear; **no** reshuffle of survivor sticky sessions; peer backfill or degrade.
5. **Performance anti-flap defaults** (tunable on `RoutingPolicySettings`):
   - `performance_score_margin` = **10**
   - `performance_streak_required` (**N**) = **2** consecutive probes
   - or switch immediately if incumbent unhealthy past `failure_threshold`
6. **Exit Performance** — freeze current active as `ACTIVE_ONLY`; does **not**
   snap back to `preferred_provider_id` (document so it is not mistaken for a bug).
7. **Performance wake** — default **online-only** (`auto_wake=false`). Optional
   auto-wake is **in scope and implemented** (not a future flip): fresh-score
   gate (default 1h), one-at-a-time inflight lock (15 min = lock TTL, not
   auto-sleep), failure clears lock + cooldown, per-provider margin override,
   Sleep all = hard reset. Manual Wake/Sleep always available.

Written into [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).

---

## Session shape (implementation status)

### Track A — Dual two homes — **done**

| Deliverable | Detail |
|-------------|--------|
| Model | `RoutingPolicy.DUAL`, `routing.dual_peer_id` |
| API | `POST/DELETE /ops/routing/dual` · `dual_*` events |
| Assign | Sticky hash over the two homes only |
| Failover | Failed-home-only clear; backfill peer or degrade; no survivor reshuffle |
| Ops UI | Dual control + Home A / Home B badges |
| Tests | `tests/test_ops_routing_modes.py` |

### Track B — Performance (XOR Dual) — **done**

| Deliverable | Detail |
|-------------|--------|
| Policy | `RoutingPolicy.PERFORMANCE` |
| Selection | Max score among enabled + healthy + online + ≥ floor |
| Anti-flap | Margin **+10**, streak **N=2**; or incumbent unhealthy |
| Exit | Freeze active as `ACTIVE_ONLY` (no preferred snap-back) |
| Ops UI | Performance toggle; status shows active + score |
| Wake | Default online-only; optional `auto_wake=true` chase-wake |
| Power | Wake/Sleep per standby; Sleep all resting cost; distinct FAILED vs sleep UI |
| Tests | routing_modes + `tests/test_ops_standby_power.py` |

### Track C — Seamless (Session 9)

Shared session Redis + reconnect with same `session_id`. Out of scope for S8.

---

## Out of scope (Session 8)

- Control-plane HA / moving OpsStore off the Hetzner box
- Vendor Monitoring APIs (Step 4 stays skipped)
- Secrets manager / Vault
- Migrating in-flight LangGraph graphs between Celery brokers
- BYO customer pools in Dual/Performance
- Auto-**sleep** of a healthy Performance winner (Sleep remains operator / sleep-all)

---

## Pass criteria

- [x] Dual requires ≥2 online healthy; assigns only across the two homes
- [x] Home loss clears **failed home only**; survivor sessions stay sticky;
      third fills peer when available, else Dual → `active_only` on survivor
- [x] Performance and Dual cannot both be on
- [x] Anti-flap: margin 10 + streak N=2 covered by unit tests
- [x] Exit Performance freezes active (no preferred snap-back)
- [x] Default Performance does **not** auto-wake; with `auto_wake=true`, at most
      one fresh-score chase-wake (no stampede); wake failure ≠ intentional sleep in UI
- [x] `provider_changed` still honest; seamless endpoint unchanged until S9
- [x] Unit tests green; resting cost posture documented (Sleep all)

---

## Suggested implementation pointers

| Concern | Location |
|---------|----------|
| Routing state / policy | [`app/ops/models.py`](app/ops/models.py) |
| Dual / Performance modes | [`app/ops/routing_modes.py`](app/ops/routing_modes.py) |
| Standby wake/sleep / auto-wake | [`app/ops/standby_power.py`](app/ops/standby_power.py) |
| Failover / force active | [`app/ops/failover.py`](app/ops/failover.py) |
| Assignment | [`app/ops/balancer.py`](app/ops/balancer.py) |
| Ops admin UI | [`frontend/public/ops-ui/index.html`](frontend/public/ops-ui/index.html) |
| Ops status UI | [`frontend/public/ops-status/index.html`](frontend/public/ops-status/index.html) |
| Celery wake/sleep tasks | [`app/worker.py`](app/worker.py) |

---

## Demo script (Tracks A+B)

1. Wake AWS + GCP; confirm three healthy rows on `/ops-status/`.
2. Force Hetzner active → enable **Dual** → open chats; confirm split homes.
3. Take one Dual home offline → confirm only that home’s sessions drop;
   survivor chats stay; peer backfills or Dual degrades.
4. Disable Dual → enable **Performance** (optional auto-wake checkbox) →
   active tracks top score; brief blip does not flap; sustained margin switches.
5. **Sleep all standbys** (resting cost); confirm Wake FAILED vs intentional
   sleep look different if you inject a failed wake first.
