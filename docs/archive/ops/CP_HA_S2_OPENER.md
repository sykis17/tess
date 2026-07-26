# TESS Engine — Control-plane HA Step 2 opener (split-brain harness)

Paste this into a **new** Cursor session. Goal of that session: **produce a plan
only** (Plan mode). Do **not** implement until the plan is reviewed and approved.

---

## Step 1 — confirmed complete (do not re-plan)

Step 1 (etcd lease + Redis CAS fencing for the ops control plane) is **signed
off**. Live smoke passed end-to-end:

| Check | Result |
| --- | --- |
| Election | Exactly one primary among `cp-a` / `cp-b` |
| Kill primary → promote | Standby promotes; fence term bumps (etcd + Redis) |
| Resurrect old primary | Returns as standby (or single-primary after clean re-election) |
| Zombie mutate (authed + unauthed) | `503` / fence gate; Redis term untouched; no routing side effects |
| Unit suite | `tests/test_ops_fencing.py` including TOCTOU (etcd yes / Redis CAS no) |

**Baseline artifacts (do not regress):**

- [`app/ops/consensus.py`](../../../app/ops/consensus.py), [`app/ops/fencing.py`](../../../app/ops/fencing.py)
- Redis Lua CAS in [`app/ops/store.py`](../../../app/ops/store.py)
- Overlay [`docker-compose.ops-ha.yml`](../../../docker-compose.ops-ha.yml)
- Smoke [`scripts/ops_cp_ha_smoke.py`](../../../scripts/ops_cp_ha_smoke.py)
- Docs: [deploy/MULTI_CLOUD.md](../../../deploy/MULTI_CLOUD.md) § Control-plane HA v1

Default prod remains `OPS_HA_ENABLED=false` (single-writer). HA is opt-in overlay.

**Do not re-litigate Step 1 design.** Build the harness on this verified baseline.

---

## This session goal (Step 2 only)

**Deliverable:** a repeatable, automated **split-brain / degraded-consensus test
harness** runnable in CI (or clearly documented local Docker Compose), with
**clear pass/fail per scenario**.

This harness is both the correctness proof for Step 1 and a demoable artifact.

**Out of scope (do not start):**

- Step 3 — Prometheus / OpenTelemetry
- Step 4 — offline packaging verification
- Step 5 — full postmortem writeup (except the fence-vs-auth decision note if
  you choose to document rather than reorder in this step)
- Smart routing, semantic cache, OpenAI gateway surface, Option B (per-stack HA)

---

## Ground rules (re-invoke — long sessions drift)

1. **Plan first.** Explain approach and tradeoffs in a few sentences before any
   non-trivial design choice. Wait for go-ahead on those choices.
2. **One deliverable.** The harness (+ minimal glue). No scope creep into
   metrics/dashboards “while we’re here.”
3. **No silent failure handling.** Harness and product code under test must
   surface fence/CAS/election failures loudly.
4. **Every scenario independently verifiable** with clear pass/fail.
5. **Flag unstated assumptions** rather than guessing (esp. WSL2 / Docker quirks).

---

## Required design decision up front (before code)

**Partition-injection mechanism** — state which you will use and **why**, given
development on **Windows / WSL2**:

| Mechanism | Fidelity | Notes |
| --- | --- | --- |
| `docker network disconnect` | Network partition | Portable; good for primary↔etcd / primary↔Redis |
| `docker pause` | Frozen process (GC-pause / stale lease) | Distinct from network cut; often **more dangerous** for fencing; portable |
| iptables in-container | Fine-grained drops | Can be finicky on WSL2 |
| toxiproxy sidecar | Latency/drop with control plane | Higher setup cost; optional later |

**Default preference unless you justify otherwise:** `docker pause` +
`docker network disconnect` (no toxiproxy / iptables required for v1 matrix).

The plan must name the chosen mechanism(s) explicitly before implementation.

---

## Pass criteria (harness terms — observable artifacts only)

Assert on **artifacts**, not log strings:

1. **No dual primary** acting as writer for longer than **one lease TTL** after
   partition heal (observe via `GET /ops/ha` on both nodes + etcd leader key /
   Redis `ops:control_plane:fence_term`).
2. **No fenced write ever lands** from a zombie / stale term:
   - Redis `ops:control_plane` blob / `fence_term` unchanged by rejected writer
   - No `provider_changed` publish attributable to the zombie
   - Mutating HTTP from non-primary → `503` (or documented auth-first behavior)
3. After heal: exactly one primary; term monotonic non-decreasing.

---

## Scenario matrix (must appear in the plan — not discovered while coding)

Minimum set:

| # | Scenario | Intent |
| --- | --- | --- |
| 1 | Primary killed mid-idle | Automate what live smoke already proved |
| 2 | Primary **paused** (frozen, not dead) | Resurrect-with-stale-lease / fencing under pause |
| 3 | Network partition primary ↔ etcd | Lost election / cannot keepalive |
| 4 | Network partition primary ↔ Redis | Cannot CAS; must not act on stale authority silently |
| 5 | Network partition standby ↔ etcd | Standby must not falsely promote without lease |
| 6 | etcd down | Both degrade loudly; **neither** claims primary |
| 7 | **Real-Redis CAS reject** | Manually/script bump `ops:control_plane:fence_term` mid-run; primary must demote — FakeRedis unit tests do **not** count |
| 8 | **Empty-blob restore** | CAS fail when `ops:control_plane` blob absent (first persist racing takeover) |
| 9 | Zombie write with **second dummy provider** | Force a real `active_provider_id` change attempt (not no-op switch to already-active) |

Optional stretch (only if matrix above is green): delay/drop heartbeats without
full disconnect; primary killed mid-request.

---

## Carried-over findings — **requirements**, not suggestions

### A. Second dummy provider in the harness

Register a second dummy provider so zombie-write attempts a **real** state
change (e.g. `POST /ops/routing/active/{other}`), not a no-op to the already
active provider. Assert Redis blob / active id unchanged on reject.

### B. Fence-before-auth ordering

Today, unauthenticated mutate may return **401** before the HA gate returns
**503**, so topology/fence info is not always visible on the error path.

**Decide deliberately** (pick one in the plan):

1. **Reorder** — fence/role check before admin auth on mutating `/ops/*`, so
   standbys always return `503` with `{role, fence_term, ...}` even without a
   token; **or**
2. **Keep auth-first** — treat fence detail as non-public; document that
   unauthed clients see `401` and only authed probes see `503` fence bodies.

Either fits Step 2 (test it) or a short note toward Step 5 — **must not be
silently forgotten**. Plan must state the choice and add an explicit harness
assertion for both authed and unauthed mutate against standby.

### C. Real-Redis CAS rejection

Unit `_FakeRedis` matches Lua by substring — correct failure direction if Lua
is reworded, but it does **not** prove real Lua. Harness must include at least
one **real Redis** CAS-reject scenario (bump `ops:control_plane:fence_term`
while primary holds a stale term; assert demotion + no blob clobber).

### D. Empty-blob restore edge

TOCTOU unit test pre-seeds a clean blob. Harness must cover CAS fail when
**no** `ops:control_plane` key exists yet.

---

## Known unit-test weaknesses (fix in harness or small follow-ups — do not block matrix)

- `_FakeRedis` ≠ real Lua; Step 2 real-Redis CAS covers the gap.
- `test_celery_task_bodies…` 800-char source window is brittle — prefer
  `inspect.getsource` per function or AST extraction when touching that test.
- `text.count("check_fence_live") == 6` is a loud guard (import+call × 3); if
  touched, comment the expected breakdown.

---

## Suggested plan shape (for Cursor Plan mode)

1. Partition mechanism choice + WSL2 rationale  
2. Scenario matrix table (above) with pass/fail observables per row  
3. Harness layout (e.g. `tests/ha/` or `scripts/ops_cp_splitbrain/`) + CI hook  
4. Fence-vs-auth decision  
5. Explicit non-goals (no OTel)  
6. Independently testable deliverable command(s)

---

## Practical (operator — before kicking off implementation)

Commit the verified Step 1 working tree to git **before** harness churn begins,
so you can diff/roll back to this baseline. If that commit is not done yet, do
it in a short agent turn with an explicit “create commit” ask.

---

## Opening ask for Cursor (copy below)

```text
Step 1 (CP etcd lease + Redis CAS fencing) is signed off — live smoke verified
election, promotion+term bump, resurrect-as-standby, authed/unauthed zombie
503s, Redis term untouched. Do not re-plan Step 1.

This session is Step 2 only: plan the split-brain / degraded-consensus test
harness. Plan mode first — no code until I approve.

Ground rules: explain approach/tradeoffs before non-trivial choices; one
deliverable (the harness); no Step 3 OTel/Prometheus; no silent failures;
assert on Redis/etcd/HTTP observables, not log strings.

Required in the plan before any implementation:
1. Partition-injection mechanism choice (prefer docker pause + network
   disconnect on WSL2) with rationale.
2. Full scenario matrix (kill, pause, primary↔etcd, primary↔Redis,
   standby↔etcd, etcd-down, real-Redis CAS bump, empty-blob restore,
   zombie write with second dummy provider) with pass/fail artifacts per row.
3. Fence-before-auth vs auth-first decision + how the harness tests both
   authed and unauthed mutate on standby.
4. Second dummy provider so zombie writes are non-no-op.
5. At least one real-Redis CAS-rejection scenario (not FakeRedis).

Read: deploy/MULTI_CLOUD.md § Control-plane HA v1, docker-compose.ops-ha.yml,
scripts/ops_cp_ha_smoke.py, tests/test_ops_fencing.py, app/ops/{consensus,fencing,store}.py
Opener: CP_HA_S2_OPENER.md
```
