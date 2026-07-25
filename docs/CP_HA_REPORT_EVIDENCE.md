# CP-HA Engineering Report — Evidence Pack

> **Working document.** This maps every claim the report will make to a
> commit / test / file:line / captured artifact, so the author can fact-check the
> prose against the repo, not against memory. It lives in `docs/` while the report
> is being written and **graduates to `docs/archive/ops/`** once the report ships
> and this pack becomes historical.
>
> **Provenance:** verified against `git` HEAD `b9d2d12` (plus the pre-work commit
> `002ea7d`) on 2026-07-25. Line numbers are current as of that HEAD and will
> drift — re-anchor by symbol name if they don't match.
>
> **Precision rule:** every row is either (a) repo-provable — a file:line, a
> passing test, a commit, or a captured artifact — or (b) explicitly labeled
> **author-attested** (a process fact the repo does not record). Nothing else
> goes in the report as fact. Section 6 lists the claims that must NOT be
> overstated.

---

## 1. Commit spine

| Short | Full SHA | Date (author) | Subject |
|-------|----------|---------------|---------|
| `84b81f5` | `84b81f58d72b33a4a5cda3940c80b53cd3a2d979` | 2026-07-24 | ops: CP HA v1 — etcd lease election + fence-term CAS (verified) |
| `e56be6c` | `e56be6c660120a0cae7ccb240ee09ac3177a1eb5` | 2026-07-24 | ops: CP HA Step 2 split-brain harness (9/9 PASS) |
| `5dd7919` | `5dd791960b6f2bc5d2dd8c3fa6abddc8e0bad87f` | 2026-07-25 | Step 3: Prometheus metrics + OpenTelemetry tracing for the ops/HA path |
| `b9d2d12` | `b9d2d12e3c088e123fcd8862ec78ed33e36c9c32` | 2026-07-25 | Step 4: offline / sovereign packaging — deploy + run fully offline, harness 10/10 under egress block |

Supporting doc commits: `0dae0e7` (CLAUDE.md ops HA critical-invariants), `a5fb00f`
(archive phase/ops briefs), `8b04c47` (archive host-metrics runbook), `002ea7d`
(Step 5 pre-work: `--report` flag + service-alias trap docs).

`b9d2d12`'s own commit body records verification: "pytest 271 passed; doc-links 0
broken." (Not CI — see §4.7.)

---

## 2. The verification layers (inventory)

The report's thesis is that these are *distinct* layers, each catching a class of
defect the others structurally cannot. For each: what it is, and the limit that
makes the next layer necessary.

| Layer | What it is | Structural blind spot (why the next layer exists) |
|-------|-----------|---------------------------------------------------|
| **L1 Design review** | Cold-context read of the plan before code | Can reason about the design; cannot observe runtime or ASGI/Docker specifics |
| **L2 Unit tests + static guards** | `tests/test_ops_fencing.py`, `tests/test_ops_metrics.py` — assert behavior + statically grep worker source for banned calls | Test the code as written against a fake Redis/etcd; can't see real-process concurrency, real headers, or real network topology |
| **L3 Live smoke** | Manual/automated single happy-path against a running stack | One node, no faults; can't exercise partition/kill/pause races |
| **L4 Chaos harness** | `scripts/ops_cp_splitbrain` — 10 scenarios asserting on artifacts (Redis term/blob, pubsub, HTTP bodies) | Runs on host-published ports; blind to the packaged/air-gapped network reality and to instrumentation correctness |
| **L5 Automated cold review** | Fresh-context reviewer over the produced diff (author-attested process; see §6.1) | A review; produces findings, not runtime proof |
| **L6 Live artifact assertions** | `s10_failover_visible` — asserts on the collector's *exported spans* and real `:9109` scrape | Requires the obs overlay; still host-based unless run offline |
| **L7 Offline / packaged env** | `docker-compose.offline.yml` + `deploy/offline/*` — internal networks, no egress, in-container runner | The environment of record; surfaces defects only the packaged topology creates |

---

## 3. The six findings

Each finding: the layer that caught it, symptom, root cause, the fix or documented
decision, the repo anchors, which other layers missed it and why, and a
**provenance class**:

- **Class A — re-demonstrable:** the catching mechanism is in the repo and
  re-runnable today (revert the fix / run the scenario and watch it catch).
  Findings **2, 4, 6**.
- **Class B — author-attested discovery:** the *fix* and its pinning
  test/scenario are repo-provable, but the *discovery* (design review, cold
  review, or a predictive spike) is session/plan history the repo does not
  record. Findings **1, 3, 5**.

See §6.1 for the general provenance note this feeds.

### Finding 1 — TOCTOU between etcd check and Redis write (caught: L1 design review → nailed by L2 test)

- **Symptom:** a stale primary could pass an etcd term prefilter, then write the
  `ops:control_plane` blob to Redis after a newer primary had already won —
  clobbering routing state.
- **Root cause:** etcd-check-*then*-Redis-`SET` is two steps with a gap; nothing
  made the Redis write conditional on the term still being current.
- **Fix:** a Redis Lua compare-and-swap. `_LUA_PERSIST_CAS`
  ([`app/ops/store.py:52`](../app/ops/store.py)) writes the blob only if the
  stored fence term still equals the writer's term; `persist_store()`
  ([`store.py:348`](../app/ops/store.py)) runs it and, on rejection, raises
  `FenceCasError` ([`app/ops/fencing.py:31`](../app/ops/fencing.py)), rolls back
  in-memory state, and demotes — **the same severity as an etcd rejection**.
  Keys: `REDIS_FENCE_TERM_KEY` (`store.py:35`), `REDIS_CONTROL_PLANE_KEY`
  (`store.py:34`).
- **The test that pins it:**
  `tests/test_ops_fencing.py::test_toctou_etcd_yes_redis_cas_no_blocks_switch_and_publish`
  ([`:155`](../tests/test_ops_fencing.py)) — etcd forced leader @term 5, Redis
  already @term 6 ("another primary won the TOCTOU window"); asserts
  `pytest.raises(FenceError)`, no `provider_changed` published, role demoted,
  in-memory flip rolled back. Severity-parity test:
  `test_etcd_reject_same_severity_as_cas` ([`:199`](../tests/test_ops_fencing.py)).
- **Commit:** `84b81f5` (CAS calls later instrumented in `5dd7919`).
- **Which layers missed it & why:** unit tests *confirm* the fix but did not
  *find* the gap — the gap was in the design, closed before implementation. Once
  code existed, only a design-level reviewer looking at the check/write ordering
  would have flagged it; the harness would also catch a regression (s07/s08), but
  the point is it never shipped to be caught there.
- **Provenance — Class B (author-attested discovery).** Repo-provable: the Lua
  CAS + `test_toctou_…` pinning it. Author-attested: that the gap was caught in
  design review *before* implementation (session history, not in the repo).

### Finding 2 — External Redis fence bump leaves the cluster unelectable (caught: L4 chaos harness)

- **Symptom:** if the Redis `fence_term` is bumped ahead of etcd out-of-band, the
  cluster correctly rejects stale writers but then **cannot re-elect** until Redis
  state is reset.
- **Root cause / by-design:** `promote_redis_fence()`
  ([`store.py:320`](../app/ops/store.py)) installs a term only if `etcd_term >
  stored_redis_term`. That is the fencing invariant working — but it also means an
  externally-inflated Redis term is un-promotable. This is fencing exposing a
  *missing recovery path*, not a fencing bug.
- **Decision (documented, deliberately not "fixed"):**
  [`CLAUDE.md`](../CLAUDE.md) "Known limitation" (§ Ops control-plane HA) and
  [`scripts/ops_cp_splitbrain/README.md`](../scripts/ops_cp_splitbrain/README.md).
  Recovery design is future work.
- **Scenario:** `s08_empty_blob.py` part (b)
  ([`scenarios/s08_empty_blob.py`](../scripts/ops_cp_splitbrain/scenarios/s08_empty_blob.py))
  sets Redis fence ahead of etcd and asserts the stale writer cannot flip
  `active_provider_id` or clobber the blob; the scenario itself skips the final
  re-election wait *because* the cluster is intentionally left unelectable (see
  §5.2).
- **Commits:** fn `84b81f5`, scenario `e56be6c`, CLAUDE note `0dae0e7`.
- **Which layers missed it & why:** a design review reasons about the happy path;
  this only surfaces when you *deliberately corrupt* the fence ordering and watch
  the cluster's next election — i.e. the chaos layer. Unit tests assert the CAS
  rejects; they don't model "and now nobody can win."
- **Precision:** documented in CLAUDE.md + harness README — **not** in
  MULTI_CLOUD.md (its `promote_redis_fence` mention there is tracing-only).
- **Provenance — Class A (re-demonstrable).** Run s08 today and watch the cluster
  reject the stale writer and stay unelectable; the catch is in the repo.

### Finding 3 — `--concurrency=1` silently load-bearing for worker metrics (caught: L5 automated cold review — see §6.1)

- **Symptom:** worker-side Prometheus counters would silently never increment (or
  split across per-child registries) under Celery prefork with concurrency > 1 —
  a "green but blind" instrumentation failure.
- **Root cause:** `start_worker_metrics_server()`
  ([`app/ops/metrics.py:422`](../app/ops/metrics.py)) binds `:9109` once and
  assumes it is the same single child that runs the ops tasks and increments
  counters. Prefork with N children would race the port / fork per-CPU. The
  correctness silently depended on `--concurrency=1`, which the base worker
  command did **not** set (env-only overlay is insufficient).
- **Fix / enforcement:** the worker command is *overridden* to set
  `--concurrency=1` where metrics matter —
  `docker-compose.ops-obs.yml` (the "counters silently never increment" trap
  comment + `command:` override) and `docker-compose.offline.yml`; prod sets it in
  `docker-compose.prod.yml`. Documented: `deploy/MULTI_CLOUD.md` §Observability
  ("Prefork assumption (matters)") and [`CLAUDE.md`](../CLAUDE.md). Runtime guard:
  `s10_failover_visible._assert_worker_exposition`
  ([`scenarios/s10_failover_visible.py:169`](../scripts/ops_cp_splitbrain/scenarios/s10_failover_visible.py))
  fails with "must … run the worker at --concurrency=1 (§3a)" if `:9109` is
  unreachable.
- **Commit:** `5dd7919` (propagated to offline in `b9d2d12`).
- **Which layers missed it & why:** unit tests import the module in one process —
  they never fork, so prefork racing is invisible to them. Live smoke with a
  default worker command would *look* healthy (the endpoint answers) while
  counters silently stagnate. It takes either a fresh reviewer reasoning about the
  prefork model, or the s10 worker-exposition assertion, to expose it.
- **PRECISION (must not overstate):** the repo documents the *dependency*
  thoroughly but contains **no text attributing its discovery to a cold review**.
  The "caught before code existed by a cold reviewer" narrative is
  **author-attested process** (§6.1), not repo-provable. The report states the
  *result* as fact and the *discovery mechanism* as the author's account.
- **Provenance — Class B (author-attested discovery).** Repo-provable: the
  enforced `--concurrency=1` dependency + s10's worker-exposition guard.
  Author-attested: that a cold review found it before code existed.

### Finding 4 — Bytes-keyed traceparent silently broke context extraction (caught: L6 live artifact assertion)

- **Symptom:** every ASGI request became its own **root** trace; failover looked
  like two unrelated traces instead of one. Unit tests passed throughout.
- **Root cause:** ASGI scope headers are a list of `(bytes, bytes)`; the W3C
  propagator looks up the **string** key `traceparent`, so a bytes-keyed carrier
  extracts nothing — silently.
- **Fix:** `extract_trace_context()`
  ([`app/ops/metrics.py:320`](../app/ops/metrics.py)) decodes into a `str→str`
  carrier before `propagate.extract(...)`; consumed by the ops mutation
  middleware as the parent context for the `ops.http.mutation` span.
- **The assertion that caught it:** `s10_failover_visible._trace_ok`
  ([`scenarios/s10_failover_visible.py:145`](../scripts/ops_cp_splitbrain/scenarios/s10_failover_visible.py))
  collects the two `ops.http.mutation` spans sharing `ops.request_id` and asserts
  `len({trace_id}) == 1` with outcomes `{fenced_503, success}`. A bytes-keyed
  carrier makes those two spans carry *different* trace_ids → assertion fails.
- **Commit:** `5dd7919`.
- **Which layers missed it & why:** the decode bug is invisible to unit tests
  (they don't build an ASGI scope with byte headers and assert on emitted span
  parentage) and to metrics (counters increment fine regardless of trace linkage).
  Only asserting on the *exported spans'* shared trace_id — a live artifact —
  surfaces it.
- **Provenance — Class A (re-demonstrable).** Revert the str-carrier decode in
  `extract_trace_context` and s10's `len({trace_id}) == 1` assertion fails; the
  catch is a live assertion in the repo.

### Finding 5 — Internal networks block host port-publishing (caught: L7 offline env; predicted in L1, confirmed by spike)

- **Symptom:** with both compose networks `internal: true`, host-loopback
  published ports stop being reachable — the host-based harness could not reach
  the nodes at all.
- **Root cause:** Docker `internal: true` is the egress block *and* removes
  host↔container published-port reachability (Docker Desktop / WSL2). The two are
  the same engine mechanism.
- **Fix (pre-designed fallback):** publish **no** host ports; run the harness from
  an **in-container runner** attached to `tess-engine_default`, reaching nodes by
  name. `docker-compose.offline.yml` (header comment; both nets `internal: true`;
  worker uses `expose:` not `ports:`), `deploy/offline/harness-runner/Dockerfile`,
  driver `deploy/offline/verify-egress-blocked.sh`.
- **Commit:** `b9d2d12`.
- **Which layers missed it & why:** every prior layer ran on host-published
  ports, so the constraint literally did not exist for them. It is a property of
  the packaged topology, visible only once the stack is assembled that way. The
  cold review *predicted* it; the spike *confirmed* it; the fallback *absorbed*
  it.
- **Provenance — Class B (author-attested prediction).** Repo-provable: the
  resulting design (internal networks, `expose:` not `ports:`, in-container
  runner). Author-attested: that L1 predicted it and a spike confirmed it — the
  prediction lives in scrollback / a plan file outside the tree, not the repo.

### Finding 6 — `docker network connect` restores the container name but not the service alias (caught: L7 offline env)

- **Symptom:** after a partition-heal reconnect, `http://web:8000` stops
  resolving while `http://tess-engine-web-1:8000` keeps working.
- **Root cause:** a manual `docker network connect` (harness s03/s05 heal) restores
  the container-name DNS record but **not** compose's service alias.
- **Fix / convention:** the harness addresses nodes by **container name**
  throughout; the offline driver injects container names into
  `OPS_HA_SMOKE_A/B`. Heal logic: `docker_util.network_connect()` /
  `heal_all()` (plain reconnect, no `--alias`)
  ([`scripts/ops_cp_splitbrain/docker_util.py`](../scripts/ops_cp_splitbrain/docker_util.py)).
  Documented: `verify-egress-blocked.sh` header, `MULTI_CLOUD.md` §Offline
  packaging, and — as of `002ea7d` — the `container_name()` docstring, the
  harness-runner Dockerfile, and the MULTI_CLOUD.md provider-table note.
- **Commit:** docs `b9d2d12`; heal logic `e56be6c`; source-level docs `002ea7d`.
- **Which layers missed it & why:** invisible in **all** host-based runs (nodes
  reached via published ports, never by alias). Surfaces only when the offline
  environment forces in-network addressing — the last layer.
- **Provenance — Class A (re-demonstrable).** Run the offline s03/s05 heal and
  `http://web:8000` fails to resolve while `http://tess-engine-web-1:8000` still
  works; the catch is reproducible in the packaged environment.

---

## 4. Numbers appendix — evidence

### 4.1 Test counts
- **271** tests total (`pytest tests/ --collect-only -q`), matching `5dd7919`'s
  body ("pytest tests/ -> 271 passed").
- `tests/test_ops_fencing.py` — **8**: `test_promote_and_persist_cas_happy_path`,
  `test_stale_persist_cas_rejected_hard`,
  `test_toctou_etcd_yes_redis_cas_no_blocks_switch_and_publish` (`:155`),
  `test_etcd_reject_same_severity_as_cas` (`:199`),
  `test_celery_uses_only_fresh_live_election` (`:211`),
  `test_celery_task_bodies_do_not_read_cached_role`,
  `test_worker_source_grep_no_stale_role_fields` (`:253`),
  `test_check_fence_live_ha_disabled_is_synthetic`.
- `tests/test_ops_metrics.py` — **10**: `test_all_metrics_are_tess_ops_prefixed`,
  `test_every_label_is_allowlisted_and_not_banned`,
  `test_no_metric_uses_provider_id`, `test_provider_type_label_domain_matches_enum`,
  `test_recorders_never_raise_when_disabled`,
  `test_recorders_never_raise_when_enabled`, `test_fence_error_kind_maps_subclasses`,
  `test_ops_task_observed_reraises_not_primary`,
  `test_ops_task_observed_passes_return_value`, `test_classify_outcome_bounded`.
- Re-run this session (fencing + metrics only): **18 passed**.

### 4.2 Scenario matrix — 10 scenarios (registry `scenarios/__init__.py`, `ORDER` = s01…s10)
`run-all` iterates `ORDER` and prints `{passed}/{total}` → **10/10 PASS** when clean.

| ID | Title | One-liner |
|----|-------|-----------|
| s01 | Primary killed mid-idle | automate live smoke |
| s02 | Primary paused (frozen lease) | artifacts > status codes |
| s03 | Partition primary ↔ etcd | full disconnect on single compose net |
| s04 | Primary loses Redis (pause) | pause Redis (portable), assert no durable clobber — *pause, not partition* (§5.1) |
| s05 | Partition standby ↔ etcd | must not falsely promote |
| s06 | etcd down | sitting primary demotes after lease TTL |
| s07 | Real-Redis CAS reject | bump fence_term while primary holds stale term |
| s08 | Empty-blob restore + stale writer reject | Redis-ahead bump; *skips final re-election wait* (§5.2) |
| s09 | Zombie write, 2nd dummy provider | non-no-op active-switch attempt |
| s10 | Failover visible in metrics + trace | needs obs overlay; the trace-continuity scenario |

**"9 vs 10":** s01–s09 are the fencing scenarios; **s10** is the
observability/trace-continuity scenario added in `5dd7919`. Report phrasing:
**"9 fencing scenarios + 1 failover-visibility scenario = 10"**, `run-all` = 10/10.
The `10/10 PASS, egress blocked` line is also asserted by
`verify-egress-blocked.sh`.

### 4.3 Metrics (13, `app/ops/metrics.py` `ALL_METRICS` @ `:144`)
`tess_ops_role_transitions_total`, `tess_ops_is_primary`, `tess_ops_fence_term`,
`tess_ops_fence_rejects_total`, `tess_ops_lease_keepalive_total`,
`tess_ops_lease_ttl_seconds`, `tess_ops_cas_total`, `tess_ops_mutations_total`,
`tess_ops_mutation_duration_seconds`, `tess_ops_probes_total`,
`tess_ops_probe_duration_seconds`, `tess_ops_failovers_total`,
`tess_ops_worker_task_total`. Histogram buckets `(0.005 … 10.0)`. Cardinality:
`provider_id` (unbounded uuid) **banned** as a label; `provider_type` (4 values)
used instead — enforced by `tests/test_ops_metrics.py`. Example PromQL set:
`MULTI_CLOUD.md:167-178` (7 queries).

### 4.4 Trace pipeline
Span names: `ops.http.mutation` → `ops.fence_gate` → `ops.persist_cas` →
`ops.publish_provider_changed`; promotion path `ops.promotion` →
`ops.promote_redis_fence` / `ops.initial_persist`. Collector
(`deploy/otel-collector-config.yaml`): OTLP/HTTP receiver `:4318`, single `file`
exporter → `/spans/spans.json`, `flush_interval: 1s`.

### 4.5 otel-collector pin
`otel/opentelemetry-collector-contrib:0.111.0` pinned in **3** places:
`docker-compose.ops-obs.yml`, `deploy/offline/otel/Dockerfile`,
`deploy/MULTI_CLOUD.md`. **Reason (`MULTI_CLOUD.md`):** `0.116.0`'s distroless
binary would not exec on this Docker Desktop / WSL2 engine — with an explicit
"TODO on a Linux VPS: re-test". **Python** OTel libs are **unpinned** in
`requirements.txt`; provenance captured at build time via `requirements.lock.txt`
(pip freeze).

### 4.6 Offline bundle contents (`deploy/offline/build-bundle.sh`)
`docker save` tar holds **5** images by default —
`tess-engine-app:offline`, `tess-engine-otel:offline`,
`tess-engine-harness-runner:offline`, `redis:7-alpine`,
`quay.io/coreos/etcd:v3.5.16` — plus (with `--with-prod`) `caddy:2-alpine` and a
digest-pinned `ollama/ollama`. Also bundled: `repo-snapshot.tar` (git archive of
HEAD), `frontend-dist.tar`, `requirements.lock.txt`, `bundle-lock.txt`
(commit + build_date + third-party digests), `images.ids`, installer/verifier/
firewall scripts, `.env.offline.example`, `VERSION`, `MANIFEST.sha256`.
**Sizes are recorded NOWHERE** — do not cite a bundle/image size unless measured
this step. The manifest records **sha256 + image IDs, not sizes**.

### 4.7 Doc-link + CI reality
Doc-link gate: `python -m scripts.check_doc_links` → "0 broken links (N local
links checked)". As of this session: **0 broken (423 checked)** after the pack was
added. There is **no `.github/workflows/`** — the checker and the "CI cardinality
test" are **local/pytest gates**, not a hosted CI pipeline. Do not imply CI
automation the repo doesn't have.

### 4.8 Attestation (verbatim)
The text `verify-egress-blocked.sh` prints to stdout on a PASS (source
`deploy/offline/verify-egress-blocked.sh`):

```
===============================================================================
 SOVEREIGNTY ATTESTATION
   - every project container attaches to internal networks only
   - web / web-standby / worker cannot reach 1.1.1.1:443 or pypi.org
   - redis / etcd reachable locally (stack fully functional)
   - no image pull/build occurred during the run
   - split-brain harness run-all: 10/10 PASS, egress blocked
===============================================================================
```

The block above is **verified byte-identical** to the script's `<<'EOF'` heredoc
this session (extract-and-diff, empty diff). As of `002ea7d`, `--report [DIR]`
self-archives this block plus run metadata (`date_utc`, `head_commit`,
`image_set_sha`, `harness_rc`) to `deploy/offline/out/attestation-<ts>.txt` on a
PASS. **No dated live-run artifact exists yet** — the report must present the block above as *the verifier's on-pass
output* (corroborated by `b9d2d12`'s recorded "10/10 under egress block"), not as
a captured dated attestation.

---

## 5. Honest record — adaptations, limitations, deferrals

### 5.1 Harness adaptation: s04 pauses Redis instead of partitioning it
`s04_partition_primary_redis` **pauses** Redis rather than doing a multi-network
partition ("Prefer pause over multi-network juggling on single-compose setups").
Reason: multi-network partition is flaky on the single-compose / WSL2 setup; the
pause still proves the target property (no durable clobber while Redis is
unreachable). Source: `scenarios/s04_partition_primary_redis.py` docstring.
**The filename is historical** — `s04_partition_primary_redis` predates the
adaptation (it *was* a partition); the report should note this so the name isn't
read as contradicting the "pause" title/docstring.

### 5.2 Harness adaptation: s08 skips the final re-election wait
Because s08 part (b) deliberately bumps Redis ahead of etcd, the cluster is
intentionally left unelectable (Finding 2), so the scenario does not wait for a
final re-election. Reason recorded in `e56be6c` body + the scenario comment.

### 5.3 s10 continuity is same-box, not cross-node
`s10_failover_visible` docstring (`scenarios/s10_failover_visible.py:10-13`),
verbatim: *"The reject and the success land on the same physical box (cp-b as
standby, then as the new primary) — precisely 'rejected on the standby, retried on
the new primary'. True cross-node reject/success correlation needs an etcd-only
partition and is deferred (WSL2 multi-network flakiness; see the s04/s08
precedent)."* The report's "what's proven" section must state continuity is proven
**across a role change on one box (cp-b)**, not across two hosts.

### 5.4 Deferred hardening (documented, referenced not re-litigated)
Non-root containers and a hash-pinned requirements rebuild are **deliberately
deferred**, documented in `deploy/MULTI_CLOUD.md` §Deferred hardening + `CLAUDE.md`
§Offline. The report references this; it does not re-argue it.

### 5.5 Fence-before-auth ordering (deliberate contract + its tradeoff)
The router-level `_gate_ops_mutations` dependency
([`app/api/ops.py:56`](../app/api/ops.py)) runs **before** per-endpoint
`require_admin`, returning a 503 with the fence body on standby. Tradeoff
(documented): topology info (who is primary) is visible to unauthenticated callers
on mutation endpoints. Reads (GET/HEAD/OPTIONS) and `/ops/ha` stay available.
Worker-side rule: ops tasks use `check_fence_live()`
([`app/ops/fencing.py:132`](../app/ops/fencing.py)) only — never cached role;
`require_primary_cached` (`:150`) is banned in `app/worker.py`, statically
asserted by `test_worker_source_grep_no_stale_role_fields`.

---

## 6. Precision flags — claims NOT to overstate

1. **All discovery-layer attributions are author-attested; the fixes are not.**
   The report's "which layer caught it" story describes *process* the repo does
   not record — design reviews, cold reviews, and predictive spikes live in
   session scrollback and plan files outside the tree. What the repo **does**
   prove is (a) each fix and its pinning test/scenario, and (b) for the **Class
   A** findings (2, 4, 6), that the catching mechanism *demonstrably catches the
   defect class today* — revert the traceparent fix and s10's assertion fails;
   run s08 and watch the unelectability. The **Class B** findings (1, 3, 5) have
   a repo-provable fix but an author-attested discovery. State it plainly:
   **three of the six catches are mechanically re-demonstrable from the repo; the
   other three are the author's process account, with the results verifiable.**
   That sentence is stronger than six uniform claims — write it, don't smooth it
   over. (Extends Decision C to all findings.)
2. **"9 scenarios" → "9 fencing + 1 failover-visibility = 10."** `run-all` runs
   all 10; 10/10 is the offline number.
3. **Finding 2 doc location:** CLAUDE.md + harness README, not MULTI_CLOUD.md.
4. **Bundle sizes are unrecorded** — measure or omit; never cite a remembered
   number.
5. **Environment scope is WSL2 / Docker Desktop.** 10/10 offline is proven *there*
   via engine-enforced `internal: true` networks + an egress self-check. The otel
   `0.111.0` pin is WSL2-specific (0.116.0 won't exec there) with a Linux-VPS TODO.
   The firewall scripts (`firewall-egress-block.sh`) are the additional Linux-VPS
   path, not what the 10/10 was run under.
6. **Trace continuity is same-box (cp-b), not cross-node** (§5.3).
7. **No hosted CI.** The checker and cardinality test are local/pytest gates
   (§4.7).
8. **No captured dated attestation exists yet** (§4.8) — the block is the
   verifier's on-pass output.

---

## 7. Open item carried into the report

- **s08 recovery path** (Finding 2) is an **open design question**, not a solved
  problem: after an external Redis fence bump the cluster is unelectable until
  state reset. The report presents it as open and deliberately deferred, with the
  fencing invariant that makes it so.
