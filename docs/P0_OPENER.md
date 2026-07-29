# P0.2 — WS disconnect mislabeled as provider failover — Opener (resume here)

Cold-start doc for the second half of the **Proof Program's P0 correctness gate**
([PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P0 — *nothing is measured before this closes*).
The frontend labels **any** WebSocket disconnect with work in flight as "Provider
changed", via two unsound proxies: a build-time-baked WS URL compared for exact equality
against a server-advertised one (never equal in shipped prod config), and a never-reset
`sessions_dropped_last` counter that survives restarts in the durable control-plane
blob. This fabricates failover events in exactly the dataset the P3–P4 soaks exist to
collect. The honest signal — the fenced-switch-only pubsub `provider_changed` message —
structurally cannot reach a socket that is already closed; this session gives the
closed-socket path a sound signal instead: a snapshot of the server-authored
`last_failover_at`, compared for **change**, never against the client clock. P0.1
(ollama lock) is DONE (PR #16 C7); this opener closes P0.2 and with it the gate.

Filing: [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P0 item 2. Design ratified by Jesse
2026-07-29 (notice shape, IP hygiene, packaging). File:line references verified
2026-07-29 at PR #18's merge (`56a235d`).

---

## Start state (verify first)

1. **This opener's docs-only PR is merged** — the merge is the ratification act.
   `git checkout main && git pull`, confirm, then
   `git switch -c fix/p0-ws-disconnect-mislabel`.
2. Baselines: `python -m pytest tests/ -q` → **433 passed, 2 skipped** (re-baseline
   inline if main moved); `python -m scripts.check_doc_links` → **0 broken**.
3. **Diagnosis still holds** — each grep must hit, else STOP and re-diagnose:
   - `dropped > 0 ||` in `frontend/src/hooks/useWebSocket.ts` (~:217, the unsound
     predicate);
   - `"sessions_dropped_last": routing.sessions_dropped_last` in `app/api/ops.py`
     (~:365, the notice payload);
   - `last_failover_at = utc_now()` at **exactly two** sites:
     `app/ops/failover.py` ~:182 and `app/ops/routing_modes.py` ~:276;
   - `if ws_base_url is not None` in `app/ops/store.py` (~:752,
     `ensure_default_hetzner`'s clear-on-empty footgun).
4. **Switch-path closure still holds** (the design rests on it):
   `grep -rn "active_provider_id" app/ | grep "="` → the known writers are exactly:
   the two **session-dropping** switch paths, which both stamp `last_failover_at`
   (`_switch`, failover.py ~:180 — def :156, call sites failover.py:104/143/239 +
   routing_modes.py:150/395/435 — and `evaluate_dual_homes`, routing_modes.py ~:273),
   plus store.py's **non-dropping bookkeeping** writers (`upsert_provider` ~:104,
   first-enabled-becomes-active; `delete_provider` ~:120-122, re-point or None), which
   clear no assignments and therefore can only under-count, never fabricate.
   **The invariant is: no session-dropping switch path mutates `active_provider_id`
   without stamping `last_failover_at`.** If a new writer appeared, classify it against
   that invariant; a new session-dropping, non-stamping writer = STOP, design unsound.
5. **Sole-consumer check** (precondition for removing `sessions_dropped_last` from the
   notice): `grep -rn "routing/notice" app/ frontend/ tests/` (frontend/ wholesale, so
   `frontend/public/` is covered mechanically, not by separate assertion) → exactly the
   handler (`app/api/ops.py` ~:353), the onclose fetch (`useWebSocket.ts` ~:203), and
   `tests/test_ops_admin_auth.py` (~:119) — no other hits. ops-status / ops-ui read
   admin `GET /ops/routing`, not the notice.
6. **Battery infra available** (Step 2 needs it): docker up; a real etcd reachable for
   `pytest tests/test_fence_store_parity.py -v` — **confirm it runs, not skips**; the
   split-brain harness runnable (`python -m scripts.ops_cp_splitbrain run-all`).
7. Frontend baseline: `cd frontend && npm run build && npm run lint` green pre-change.

---

## Settled decisions + attached requirements

1. **900 s stance — DECIDED (2026-07-29, Jesse), restated here, never re-opened:** the
   900 s `session:{sid}:active_task` stale-TTL resume-refusal window **counts against
   availability** in published numbers until the W4 liveness-checked refusal removes it
   ([PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P0).
2. **Classification primitive** = change in the server-authored `last_failover_at`,
   compared as an **opaque string**; every unknown resolves to the conservative
   "connection lost" label. Error bias by construction: may under-count failovers
   (dominant for stack-killing faults — see the catch-asymmetry paragraph below), and
   **never fabricates one through the classification rule itself** — fabrication was
   the P0 defect. One accepted residual: the in-band baseline advance rides best-effort
   pub/sub (`notify.py` swallows publish failures ~:33-38); a socket that misses the
   in-band message keeps a stale baseline for its remaining lifetime (row 14 without
   the advance). Bounded by pub/sub delivery, same family as row 9's gap; accepted.
3. **Notice payload becomes `{ws_base_url, last_failover_at}`** —
   `sessions_dropped_last` is removed from the public notice (decided 2026-07-29: its
   only repo consumer is the buggy path being deleted; a sticky never-reset counter in
   a public payload is a loaded footgun for the next consumer). The field **stays** in
   `RoutingState` and admin `GET /ops/routing`, where "sessions dropped at last switch"
   is honest historical framing.
4. **The notice stays public** — never move it behind auth (pinned by
   [tests/test_ops_admin_auth.py](../tests/test_ops_admin_auth.py) ~:111-127; that
   test's exact-key-set pin goes red on the shape change and is updated deliberately —
   the red run is the shape-change evidence).
5. **IP hygiene (extends PR #18's trim):** tracked example files carry placeholders
   (`ws://<server-ip>`), never the real prod IP; real values live only in the untracked
   `.env.prod` on the box.
6. **Defect C is fixed at the config boundary** (`""` → `None`), with a belt-and-braces
   truthy guard in `ensure_default_hetzner` — the env path was never a sane
   clear-channel; clearing stays possible via the admin `ProviderUpdate` API.
7. **The fix touches `app/api/ops.py` → the full ops battery applies** before Step 2's
   commit (CLAUDE.md invariant): `tests/test_ops_fencing.py` + live-etcd parity
   (must run, not skip) + split-brain `run-all` (11 scenarios, etcd authority default).
8. Red-first per house rule: every guard is shown failing before the fix, failure
   output recorded in the PR; non-vacuous (activity advances, not just bad-outcome==0).

---

## Resolved design — the classification primitive (grounded in code)

**Why `last_failover_at`:** both real-switch paths already stamp it —
[app/ops/failover.py](../app/ops/failover.py) `_switch` at ~:182 (used by
`evaluate_failover`, `force_active_provider`, and the performance-chase/dual call
sites) and [app/ops/routing_modes.py](../app/ops/routing_modes.py)
`evaluate_dual_homes` at ~:276 — and it persists in the durable blob
([app/ops/store.py](../app/ops/store.py) `to_redis_payload` ~:254 → restore ~:278).
In `_switch` the stamp cannot survive a failed commit (on `FenceError` the store is
restored, failover.py ~:188/:213); a doomed stamp is briefly visible between
`set_routing` and the restore — coinciding with a close-fetch, a vanishing-probability
corner, accepted. **Freshness caveat:** the notice serves the serving process's
in-memory store — a switch committed by another process (the Celery-task path) or an
HA standby pre-promotion is invisible to it → under-count, conservative; the default
single-writer topology (probe loop in the web process) is fresh. **The backend change
is additive/read-path-only**: no fenced write semantics change, no new durable field,
no blob migration.

```
classify(baseline, current) -> "provider_changed" | "connection_lost"
  baseline unknown (open-fetch failed/never ran)  -> connection_lost   (conservative)
  current  unknown (close-fetch failed / !res.ok) -> connection_lost   (as today)
  current == null                                 -> connection_lost   (no failover ever)
  baseline == null, current != null               -> provider_changed  (first failover, mid-session)
  otherwise                    -> current != baseline ? provider_changed : connection_lost
```

Baseline lives in a ref with three states — `unknown` / `null` (server: no failover
ever) / ISO string — and is **reset to unknown at the top of each connect effect**
(the effect re-runs on remount / `sessionId` change, and StrictMode double-invokes; a
stale baseline from a previous socket must not classify the next one). `onopen`
fetches the notice once per socket (`cache: "no-store"` on both fetches — a cached
response could only under-count, but it's free robustness). An
onclose-before-onopen-fetch-resolves race lands on `baseline unknown` → conservative,
correct by construction. `ws_base_url` stays in the payload as **banner decoration
only** ("New endpoint: …"), exactly like the pubsub handler (useWebSocket.ts ~:153-157).

**In-band baseline advance (closes the stale-baseline fabrication — cold-review F2):**
a failover that does *not* kill the socket arrives in-band (`isProviderChangedMessage`,
useWebSocket.ts ~:146-159) and is bannered correctly — but without action the `onopen`
baseline goes stale, and **any later plain disconnect would re-report that switch** as
a second, fabricated failover for the rest of the socket's lifetime. Therefore
`ProviderChangedMessage` ([app/ops/models.py](../app/ops/models.py) ~:259-270) gains
an optional `last_failover_at`, populated at both publish sites, and the in-band
handler **advances the baseline ref** from it (absent/null → reset to unknown, which
is conservative). Row 14 below; mirrored in the Python test.
**Format identity is load-bearing (cold-review N1):** the two carriers must ship the
*same string* for the same instant — `datetime.isoformat()` yields `…+00:00` while
pydantic v2 `model_dump_json()` yields `…Z`, and under opaque-string compare that
mismatch would silently re-open row 14. Therefore the message field is typed as the
**already-serialized string** (`last_failover_at: str | None`), populated with the
same `.isoformat()` value the notice serves; a red-first cross-path identity test
pins it (Step 2).

| # | Case | Baseline | Close fetch | Result |
|---|---|---|---|---|
| 1 | First-ever run, no failover in history | null | null | disconnect ✓ |
| 2 | **The P0 bug**: plain disconnect, historical failover exists | T1 | T1 | disconnect ✓ (fixed) |
| 3 | Real failover kills the socket | T1 | T2 | failover ✓ |
| 4 | First-ever failover, mid-session | null | T1 | failover ✓ |
| 5 | Failback A→B→A within one session | T1 | T3 | failover ✓ (provider-id compare would miss) |
| 6 | Dual peer lost, survivor == active | T1 | T2 | failover ✓ (sessions on the failed peer really dropped) |
| 7 | Baseline fetch failed at open | unknown | any | disconnect (under-labels, never fabricates) |
| 8 | Close fetch fails | T1 | unknown | disconnect (same as today's catch branch) |
| 9 | Switch lands between close and the onclose fetch | T1 | T2 | failover (real switch; with row 14's advance the exposure is only the close→fetch gap) |
| 10 | Server restart mid-session, no switch | T1 | T1 (durable) | disconnect ✓ (restarts stop fabricating) |
| 11 | Durable blob lost between open and close | T1 | null | disconnect (conservative) |
| 12 | Clock step backward between switches | T1 | T0′ ≠ T1 | failover ✓ (change, not ordering) |
| 13 | Two switches in the same µs, baseline captured between | T1 | T1 | disconnect (miss — µs-resolution, vanishing probability, accepted) |
| 14 | Failover mid-session arrives in-band (socket stays open), then a later plain disconnect | T2 (advanced by the in-band handler) | T2 | disconnect ✓ (without the advance: fabricated failover — the F2 hole) |

**Catch-asymmetry (honest scope):** when a fault kills the stack holding the socket,
the onclose fetch targets that same dead stack (`httpBaseFromWs(WS_BASE_URL)`), fails,
and lands in row 8's conservative branch — the classifier under-reports exactly the
big faults; conversely, same-class provider failovers that leave the web process alive
don't close the socket at all and are handled in-band, never reaching the classifier.
The onclose classifier's real value is the **negative direction**: plain disconnects
stop fabricating failovers, which is the P0 poison. Server-side events/metrics
(`/ops/events`, `tess_ops_failovers`) were never fabricated — the defect was purely
the client-side label — so Step 4 amends [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P0's
fix-shape wording from "in the emitted event/metric" to "in the user-facing signal".
P3 re-verifies the classifier live under real node-kill (Follow-ups).

**Rejected alternatives (recorded so they aren't re-litigated):**

- **`switch_seq` monotonic counter in `RoutingState`** — closes only row 13, at the
  cost of a new durable field written in both fenced switch paths and a wider
  battery-relevant diff. Not materially sounder for banner classification. Revisit
  **only if** P3–P4's measurement pipeline wants a switch *counter* anyway — then
  classification inherits it for free.
- **Compare `active_provider_id` at open vs close** — misses failback A→B→A (row 5)
  and dual-peer loss where survivor == active (row 6, routing_modes.py ~:264-276).
  Both drop sessions for real.
- **Baseline via the existing `session_assigned` WS message**
  ([app/api/ws.py](../app/api/ws.py) ~:107-119) — that block is best-effort inside
  `try/except` and skipped on any balancer/store error; baseline availability would be
  strictly worse than a plain GET. Filed as a follow-up optimization only.
- **Write-side reset of `sessions_dropped_last`** — touches fenced write paths for a
  field the decision no longer reads; Defect B is neutralized by deleting its only
  fabrication-capable consumer instead.

---

## Steps (proposed commits)

### Step 1 — Defect C + IP hygiene (config boundary)

- [app/core/config.py](../app/core/config.py) ~:40 — field validator on
  `ops_public_ws_base_url`: `""`/whitespace → `None` (pydantic-settings turns
  `OPS_PUBLIC_WS_BASE_URL=` — exactly what `.env.example` ships — into `""`, which then
  masquerades as an intentional clear).
- [app/ops/store.py](../app/ops/store.py) ~:752 — `ensure_default_hetzner` guard
  `if ws_base_url is not None:` → truthy `if ws_base_url:`.
- `.env.prod.example` — add `OPS_PUBLIC_WS_BASE_URL=ws://<server-ip>` with the
  derivation comment (unset ⇒ derived from `OPS_LOCAL_BASE_URL` ⇒ prod would advertise
  `ws://web:8000`); same sweep replaces the existing hardcoded-IP `VITE_WS_BASE_URL`
  line and `.env.example`'s commented IP example with placeholders.
- **Red-first:** (a) new test in
  [tests/test_ops_providers.py](../tests/test_ops_providers.py): provider seeded with
  a real `ws_base_url`, then `ensure_default_hetzner(..., ws_base_url="")` →
  `ws_base_url` **preserved** — RED against current code (it clears); (b) new Settings
  test: env `OPS_PUBLIC_WS_BASE_URL=""` → `ops_public_ws_base_url is None` — RED.
  The settings test must set the empty var **in-process**
  (`monkeypatch.setenv(..., "")`): PS 5.1 cannot express an empty env var —
  `$env:OPS_PUBLIC_WS_BASE_URL=''` *deletes* it, and a shell spot-check would wrongly
  conclude the defect is already fixed.
- **Verify:** red→green runs recorded; `pytest tests/ -q` green.

### Step 2 — Notice payload serves `last_failover_at` (THE battery commit)

- [app/api/ops.py](../app/api/ops.py) ~:353-366 — payload becomes
  `{"ws_base_url": ..., "last_failover_at": routing.last_failover_at.isoformat() if
  routing.last_failover_at else None}`; `sessions_dropped_last` removed (decision 3).
- `ProviderChangedMessage` ([app/ops/models.py](../app/ops/models.py) ~:259-270) gains
  optional `last_failover_at: str | None = None` — the **already-serialized** string
  (N1: a `datetime` field would `model_dump_json()` to `…Z` while the notice serves
  `.isoformat()`'s `…+00:00`, silently re-opening row 14 under opaque-string compare).
  Populated where the message is constructed
  ([app/ops/failover.py](../app/ops/failover.py) ~:191-196,
  [app/ops/routing_modes.py](../app/ops/routing_modes.py) ~:316-325) with the same
  `.isoformat()` value the notice serves — the in-band baseline advance's carrier
  (row 14). Red-first: (a) extend `tests/test_ops_provider_notify.py`'s serialization
  assertions to require the field — RED against the current model; (b) cross-path
  **format-identity test**: after a switch, the notice's `last_failover_at` string ==
  the string carried in that switch's published message — RED against any
  dual-format implementation.
- [tests/test_ops_admin_auth.py](../tests/test_ops_admin_auth.py) ~:111-127 — pinned
  key set → `{"ws_base_url", "last_failover_at"}`; seed/assert `last_failover_at`.
- New red-first test (fixture idiom of
  [tests/test_ops_failover.py](../tests/test_ops_failover.py), muted publish): notice
  `last_failover_at` is `null` pre-switch → a changed ISO string after
  `force_active_provider` → changes again after a second switch.
- **Red-first:** run the pinned key-set test against modified `ops.py` **before**
  updating it (deliberate-shape-change evidence); run the new test against unmodified
  `ops.py` (red on the missing key).
- **Battery, before this commit** (over the final backend state = Steps 1+2):
  1. `pytest tests/test_ops_fencing.py -q`
  2. `pytest tests/test_fence_store_parity.py -v` against a real etcd — **a skip is
     not a pass**;
  3. `python -m scripts.ops_cp_splitbrain run-all` — 11 scenarios, etcd authority
     default; any failure is a product bug — fix the product, never soften.
- **Verify:** `pytest tests/ -q` green. Step 2 lands **before** Step 3 so the frontend
  never reads a field the backend doesn't serve.

### Step 3 — Frontend classification + Python mirror (Defects A and B die here)

- [frontend/src/hooks/useWebSocket.ts](../frontend/src/hooks/useWebSocket.ts) —
  exported pure `classifyDisconnect(baseline, current)` per the design; baseline ref
  reset per socket + `onopen` notice fetch; **in-band handler advances the baseline**
  from `ProviderChangedMessage.last_failover_at` (row 14; absent/null → unknown);
  `onclose` (pending-work gate unchanged) fetches and classifies; both fetches
  `cache: "no-store"`; **delete** the
  `dropped > 0 || (activeWs && activeWs !== WS_BASE_URL)` predicate and every
  `sessions_dropped_last` read/typing; keep today's conservative `catch`/`!res.ok`
  copy and the `ws_base_url` decoration. `frontend/src/types/panel.ts` mirrors the new
  optional message field (Panel/message additions optional with defaults — CLAUDE.md
  convention). Reciprocal comment (idiom of useWebSocket.ts ~:52-56): "mirrored in
  tests/test_ws_disconnect_classify.py — change BOTH together."
- New `tests/test_ws_disconnect_classify.py` (idiom:
  [tests/test_panel_stream_dedup.py](../tests/test_panel_stream_dedup.py)):
  - Python mirror of `classifyDisconnect` + **every row of the decision table above,
    including row 14's baseline-advance sequence** (unknown vs null expressed
    distinctly, e.g. a sentinel for unknown);
  - **discovery-based source guard** on the frontend file: `classifyDisconnect`
    exists and is called in `onclose`; `last_failover_at` present; tokens
    `sessions_dropped_last` and `dropped > 0` **absent file-wide** — mechanically RED
    against current source;
  - a planted-source **trip test** (source containing the forbidden predicate → guard
    raises) proving the guard non-vacuous.
- **Red-first:** run the new test file against the untouched frontend source → source
  guard RED; apply the frontend change → green. (Mirror rows are green from birth;
  their non-vacuity is the trip test.)
- **Verify:** `cd frontend && npm run build && npm run lint`; `pytest tests/ -q`.

### Step 4 — Docs flip

- [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P0 item 2 `⬜ OPEN` → `✅ DONE`, one-line
  mechanism + commit refs (mirror the P0.1 entry's format); amend its fix-shape wording
  "in the emitted event/metric" → "in the user-facing signal" (server events/metrics
  were never fabricated — the defect was the client label; see Catch-asymmetry).
- [deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md) — update the notice payload shape
  where documented.
- [CLAUDE.md](../CLAUDE.md) — add the new mirror test to the change-both-together
  convention and the file-pointer table.
- **Verify:** `python -m scripts.check_doc_links` → 0 broken; `pytest tests/ -q`;
  PR into main, merge left to Jesse.

---

## House rules (unchanged)

Every guard gets a red-first proof with the failure output recorded in the PR; the ops
battery runs **once, at Step 2, over the final backend state**; a harness failure is a
product bug until proven otherwise; tallies/pins are executable claims with the house
inline re-baseline comment; suite + doc-links green per commit; PR into main, merge
left to Jesse. Backend shape change lands before its frontend consumer (Step 2 → 3).
Out of scope this arc: all `app/ops/` behavior except the named touches — the
store.py:752 truthy guard and the additive `ProviderChangedMessage` field + its two
publish-site one-liners (the config validator is `app/core/`); no `app/graph/**` or
chain-touching changes (no eval-harness gate triggered).

## Environment notes

- Frontend has **no test runner** — the Python mirror is the only executable pin;
  change both sides together, always.
- Plain `pytest tests/` **skips** the etcd parity suite — a skip is not a pass; check
  the parity run's collected/skipped counts explicitly.
- PS 5.1 quote-mangling: commit/PR bodies via `git commit -F` / `--body-file`. `gh` at
  `C:\Program Files\GitHub CLI\gh.exe`.

## Follow-ups filed

- `switch_seq` durable counter — only if P3–P4 measurement wants a switch counter;
  classification then inherits row 13's fix for free.
- Carry `last_failover_at` on the `session_assigned` WS message to skip the `onopen`
  fetch — only if the extra GET proves noisy.
- **P2 known-interaction** ([PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P2): re-verify this
  classification live under real node-kill during P3 chaos.
- [CLAUDE.md](../CLAUDE.md) §Deployment still carries the prod IP — decide whether
  PR #18's trim extends there (Jesse's call; not this arc's scope).
- ops-status UI could label `sessions_dropped_last` as "at last switch" for clarity
  (cosmetic; admin-only surface).
