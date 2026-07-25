# High-Availability Control Plane: Design and Verification

*An engineering report on the control plane that decides which cloud provider
serves TESS Engine's traffic — what it guards, how it was designed to fail
safely, and the layered verification that found six defects before any of them
could reach production. Written to be checked: every factual claim traces to a
commit, test, file, or captured artifact, and every claim about how a defect was
discovered is labeled either re-demonstrable from the repository or attested by
the author.*

---

## 1. Context and problem

TESS Engine can serve its workload from more than one place. The default is a
host on Hetzner; AWS, GCP, or a customer's own infrastructure can be registered
as alternates. Deciding which of these is *live* — which provider currently
receives traffic — is the job of a dedicated ops control plane. It holds three things
that matter: the routing decision (`active_provider_id`, the provider serving
right now), a registry of the known providers and their health, and the policy
that governs when to fail over. Operators change it through an `/ops/*` HTTP API,
and the decision is stored durably in Redis so that every web and worker process
reads the same answer.

Because that decision is load-bearing, the control plane itself is run for
availability: a primary and a standby, with leadership held through an etcd
lease. The failure that this design is really about is not a clean crash — a
process that dies releases its lease and its work stops, which is easy to handle.
The dangerous case is the *zombie*: a primary that has lost its lease — frozen,
garbage-collection-paused, or partitioned from etcd — but whose process is still
alive and still running code that writes to the shared Redis state. If that stale
primary writes the routing decision, it can point live traffic at the wrong
provider, or overwrite a decision that a newer, rightful primary has already
made. Two processes each believing they are primary, issuing conflicting routing
— split brain — is the specific catastrophe to prevent.

Concretely, the state a zombie must never write is one durable blob in Redis,
under the key `ops:control_plane`. It is the serialized control-plane store, and
its consequential contents are exactly the three things above: the active-provider
routing decision, the provider registry, and the failover policy. Anything that
could redirect traffic or contradict a newer primary lives in that blob. Guarding
it — ensuring only the one rightful primary can write it, and that a stale writer
is stopped and knows it has been stopped — is the whole problem.

Redis alone cannot solve this, because Redis has no concept of a rightful
primary. A plain last-writer-wins `SET` will faithfully accept a zombie's write.
Introducing an etcd lease gives an authority for *who should be primary*, but an
authority consulted only *before* writing is a check with a gap: between "etcd
says I am primary" and "I write to Redis," leadership can change. What the control
plane needs is both a monotonic notion of authority and enforcement at the moment
of the write itself. That pairing is the subject of the next section.

<!-- Sections below are drafted one at a time; see docs/CP_HA_REPORT_EVIDENCE.md. -->

## 2. Design

The control plane's authority is an etcd lease. One node holds the lease and is
primary; if it stops renewing, the lease expires and the standby can acquire it.
Leadership by itself does not order writes, so each time a node wins the lease it
also mints a *fence term*: an integer, held in etcd, that advances by one on every
acquisition. That ordering is constructed by the design, not handed down by etcd.
The increment is itself a compare-and-swap — etcd installs the next value only if
the stored one has not changed — so two nodes racing to promote cannot both claim
the same term, and the value only ever moves up; the term is then mirrored into
Redis under a promotion that accepts it only when it is strictly higher than the
one already stored. etcd supplies the lease and the atomic transaction; the fence
term's monotonicity is built on top of them. Because the term is ordered, a writer
can prove it is newer than another by holding a higher number — and a holder of a
lower number can be recognized, and rejected, as stale.

That ordering is what closes the gap §1 described. A primary does not check the
lease and then issue an unconditional write; it carries its fence term into the
write and conditions the write on that term still being current. The durable
write to `ops:control_plane` is a Redis Lua script that sets the blob only if the
fence term stored in Redis still equals the writer's term (`persist_store`
running the `_LUA_PERSIST_CAS` compare-and-swap). Inside that script the term
check and the blob write are one atomic step, with no window between them. The
etcd check and the Redis write, by contrast, stay two separate steps with a real
gap between them — but the commit is decided only at the second. etcd decides who
is *allowed* to attempt a write; the Redis compare-and-swap decides who actually
*commits* one. A zombie that clears the first lock — because it has not yet noticed
its lease is gone — is stopped at the second, by Redis itself, on the strength of a
term it can no longer match.

A rejected write is inert unless the rejected node does something about it. A
compare-and-swap failure here is not a transient error to retry; it is positive
evidence that another primary exists with a newer term — which means this node is
the zombie. The design therefore gives a Redis CAS rejection the same severity as
an etcd rejection: the in-memory mutation is rolled back, the node demotes itself,
and the error is raised, never downgraded to a warning (`FenceCasError`, handled
by restore-then-demote-then-raise). That parity is what makes the second lock
trustworthy. Rejecting the write protects the data; demoting the writer protects
the *system*, by ensuring a fenced node stops believing it is primary instead of
looping on a write it will never land.

Two locks and a stand-down rule cover a node that writes directly, but not every
writer is a request-handling web process. Heavy ops work runs on Celery workers,
and a task can be enqueued while its node is primary and executed moments after
that node has lost the lease. A cached role, correct at enqueue time, is exactly
the stale authority the design exists to reject. So worker ops tasks are required
to perform a fresh etcd leader-and-term check at the moment they run
(`check_fence_live`), never a cached role value — and this is enforced
structurally, not by convention: a test greps the worker source and fails if a
task reads the cached-role helpers at all. The fresh check is the same fence,
applied at the one place — deferred execution — where cached authority would
otherwise slip through.

The last enforcement point is the HTTP surface. Mutating `/ops/*` endpoints are
gated *before* per-endpoint admin authentication: on a standby, the request is
refused with a 503 and the fence body regardless of whether the caller's
credentials are valid. Ordering the fence ahead of auth guarantees that a stale
or standby node cannot mutate control-plane state even when presented with correct
admin tokens, and it keeps the refusal uniform across every mutation endpoint. The
order carries a deliberate cost, recorded as a contract rather than met as a
surprise: because the fence answers before auth, an unauthenticated caller can
learn which node is primary from a mutation endpoint's response. Reads and the
`/ops/ha` status endpoint stay available on both nodes; only mutations are fenced.

Each of these mechanisms — an ordered lease, a write-time compare-and-swap, a
stand-down rule of equal severity, a fresh authority check for deferred worker
execution, and a fence-before-auth HTTP gate — closes a gap the previous one
leaves open. What none of them provides is evidence that they hold under the
failures they are meant to survive: a frozen process rather than a clean crash, a
partition rather than a stop, deferred execution under a prefork worker, a
byte-encoded header, an air-gapped network. Producing that evidence is a separate
task from stating the design, and it is the subject of the rest of this report.

## 3. The verification layers

The design in §2 is a set of claims: the term is monotonic, the compare-and-swap
rejects a stale writer, a rejected writer stands down, a worker re-checks at
execution, a standby refuses mutations before it authenticates. Each claim was
tested. The useful thing to record is not that the tests passed — passing is the
expected case — but what each layer *could not* see, because those blind spots are
what made the next layer necessary, and they are where the defects this project
found were hiding.

**Design review** is the first layer and the cheapest to run. Before code exists,
a reader works through the plan and asks whether the mechanism is sound. A review
at this altitude can catch an ordering error — a check placed where a race can
slip between it and the write — because that is a property of the design, legible
on paper. What it cannot do is observe anything that exists only once the code
runs: a real Redis round-trip, a real process losing its lease, a header as it
actually arrives on the wire. It reasons about the machine; it does not run it.

**Unit tests with static guards** run the code, but against stand-ins — a fake
Redis, a fake etcd — and inside a single process. Within that scope they are
exact: they can force the precise interleaving of "etcd says yes, Redis says no"
and assert that the caller demotes and raises, and they can go past behavior by
reading the worker's own source and failing if it so much as references a
cached-role helper. That static guard is strong because it forecloses a class of
mistake instead of testing for its symptoms. But a single process never forks, so
anything that emerges only across processes is invisible here: a prefork worker
splitting into several children, a genuine network partition, the difference
between a header key that is a string and one that is bytes. The fakes behave the
way the test author expects the real thing to behave — which is the one assumption
a real dependency is free to violate.

**Live smoke** brings up the actual stack and drives one request through it end to
end. It proves the pieces are wired together: a real primary elects, writes, and
serves. Its blind spot is adversity — a happy-path smoke never freezes a process,
never partitions a network, never kills a primary mid-write. It shows the system
works when nothing is wrong, which is the one condition an HA design is not built
for.

**The chaos harness** injects the adversity. It kills, pauses, and partitions
nodes across ten scenarios and asserts on artifacts — the fence term and blob in
Redis, the messages on the pub/sub channel, the bodies of HTTP responses — never
on log strings, which can claim an outcome that did not occur. This is where the
fencing claims are earned under real faults. Two things it cannot see define the
layers that follow. First, it runs against a stack whose ports are published to
the host, a different network reality from the packaged product. Second, and more
subtly: it asserts that the *system* reached the right state, not that the
*observability* reporting that state is faithful. A harness reading the system's
own state can confirm a failover happened without noticing that the trace meant to
record it is broken.

**Automated cold review** re-reads the produced diff with no memory of writing it.
Its value is the missing context: an author knows what the stack is configured to
do and reads past the assumption, while a cold reader sees only what the code says
and asks why a correctness property depends on a setting that nothing in the
verified stack establishes. It is a review, not an execution — it yields a question
to answer rather than a passing assertion — but the questions it raises are the
ones the author's own context has hidden from view.

**Live artifact assertions** close the fidelity gap the chaos harness left. Here
the test asserts on what the observability pipeline actually emitted — the spans
the collector exported, the counter scraped from the real metrics port — rather
than on the system state those artifacts are meant to reflect. This is the only
layer that can catch instrumentation which reports success while lying about its
shape: two events that should share one trace and do not. It costs more to stand
up, because the observability overlay has to be running, and it is still reached
over host ports — which leaves one reality untested.

**The offline, packaged environment** is that reality, and the environment of
record for the sovereignty claim. The stack is assembled the way it ships: both
networks internal, no egress, no host-published ports, the harness itself running
from a container inside the network. This layer exists because some defects are
properties of the packaging and can appear nowhere else — a network mode that
removes the very port-publishing every earlier layer relied on; a name that
resolves under one addressing scheme but not another once a partition has healed.
Its own blind spot is what §5 is about: an environment pinned to one engine proves
what it proves *there*, and what it does not exercise — a genuinely cross-host
failover, a hardened non-root image — stays a claim for another day rather than a
result.

Seven layers, each built to see what the one before it could not. The next section
is the ledger: six defects, the layer that caught each, and — the part that earns
trust in the rest — which other layers had looked straight at the same defect and
not seen it.

## 4. Findings

Six defects, drawn from across the layers. Two of the catches come from the
chaos harness's ten scenarios — nine fencing scenarios, plus the
failover-visibility scenario (s10) added with the observability work — and the
rest from the design-review, unit-test, cold-review, and packaging layers. The
column that carries the argument is the fourth: for each defect, which *other*
layers had it in front of them and did not see it, and why. The last column marks
provenance — whether the catch can be re-demonstrated from the repository as it
stands today (**A**), or whether the fix and its pinning test live in the
repository while the discovery itself is the author's account of the process
(**B**). §5 and the process note return to that distinction.

| # | Finding — caught by | Root cause → fix or decision | Which other layers had it in front of them and missed it, and why | Prov. |
|---|---|---|---|---|
| 1 | **TOCTOU on the fenced write** — design review | An etcd check followed by a plain Redis `SET` leaves a gap in which leadership can change between the two. Closed by the `_LUA_PERSIST_CAS` compare-and-swap — write the blob only if the stored fence term still matches the writer's — with rollback-demote-raise on rejection; pinned by the "etcd says yes, Redis says no" unit test. | Unit tests confirm the fix but could not have found the gap: it lived in the design and was closed before code existed for a test to exercise. The chaos harness would catch a regression through s07/s08, but the defect never shipped to be caught there. | B |
| 2 | **Unelectable after an external fence bump** — chaos harness (s08) | `promote_redis_fence` installs a term only when the etcd term exceeds the stored Redis term, so a Redis fence bumped ahead of etcd out-of-band is un-promotable and the cluster cannot re-elect until state is reset. Kept as a documented known limitation — fencing working as designed, exposing a missing recovery path — rather than quietly patched. | A design review reasons about the intended path and would not predict it; unit tests assert that the compare-and-swap rejects a stale writer, but they do not model the follow-on state in which no writer can win. It appears only when the fence ordering is deliberately corrupted and the next election is then observed. | A |
| 3 | **Worker metrics silently depend on `--concurrency=1`** — cold review | The worker binds its metrics port once and assumes the single child is the one running the ops tasks; under prefork with more children the counters split across registries or the bind races, and the base worker command never set `--concurrency=1` (an environment override alone does not fix it). Corrected by overriding the worker command where metrics matter, and guarded at runtime by the s10 worker-exposition assertion. | Unit tests import the module in one process and never fork, so the prefork race is structurally invisible to them. Live smoke against the default command looks healthy — the endpoint answers — while the counters quietly never move. Only a reviewer reasoning about the prefork model, or the runtime exposition assertion, brings it to the surface. | B |
| 4 | **Failover traces silently did not link** — live artifact assertion (s10) | ASGI request headers are byte-keyed, but the W3C propagator looks up the string key `traceparent`, so context extraction found nothing and every request became its own root trace. Fixed by decoding the headers into a string-keyed carrier before extraction. | The unit tests passed throughout — they do not build a byte-keyed ASGI scope and assert on emitted span parentage — and the metrics were unaffected, because counters increment regardless of trace linkage. Only asserting on the collector's exported spans, and requiring two of them to share one trace id, could surface it. | A |
| 5 | **Internal networks remove host port-publishing** — offline environment | Marking both compose networks `internal: true` is the egress block, but the same setting also removes host-loopback reachability of published ports, so the host-based harness could not reach the nodes at all. Absorbed by a pre-designed fallback: publish no host ports and run the harness from a container inside the network, reaching nodes by container name. | Every earlier layer ran against host-published ports, so the constraint did not exist for any of them to encounter. It is a property of the packaged topology and can appear only once the stack is assembled the way it ships. | B |
| 6 | **Service alias lost after a heal** — offline environment | A partition-heal `docker network connect` restores a container's name in DNS but not its compose service alias, so `http://web:8000` stops resolving after a heal while the container name keeps working. Handled by addressing nodes by container name throughout the harness, a convention now documented at the source. | Invisible in every host-based run, where nodes are reached over published ports and never by alias. It surfaces only when the offline environment forces in-network addressing and a heal is actually exercised. | A |

Three of the six catches — 2, 4, and 6 — can be checked against the repository as
it stands: run s08 and the cluster stays unelectable; heal a partition under the
offline stack and `http://web:8000` stops resolving while the container name does
not; and s10's assertion that a failover's two spans share one trace id sits in
the tree, ready to fail the moment the header decode regresses. The other three —
1, 3, and 5 — leave their fix and its pinning test in the repository, while the
discovery itself (a design review, a cold review, a prediction confirmed by a
spike) is the author's account of how the work went, taken up again in the process
note. The distinction is worth preserving: a claim that can be re-run is a
different kind of evidence than a claim that must be believed.

## 5. What is and isn't proven

A verification result is only as trustworthy as the environment it ran in, so this
section states each claim together with the boundary of what was actually
exercised. The scoping is not a retreat from the claims — it is what makes them
worth stating.

The strongest single claim the evidence supports: on one WSL2 host, a two-node
control plane survives kill, pause, partition, and deliberate fence corruption
across ten scenarios with zero egress, and a failover is afterward visible in
exported metrics and one linked trace. Every word of that sentence is
load-bearing; the rest of this section shows where each one stops.

*On one host.* The primary and standby are two containers on a single machine, so
the harness exercises fencing under process-level and network-namespace faults — a
frozen process, a paused container, a severed network, a lease left to expire — but
not under what two physical hosts add: asymmetric latency, independent clocks, a
machine that dies outright. The fencing logic is proven correct against the faults
it was shown; its behavior across real hosts is not yet proven.

*With zero egress.* The offline run blocks all outbound traffic at the engine
through `internal: true` networks and checks the block within the same run — `web`,
`web-standby`, and `worker` each fail to reach `1.1.1.1:443` and `pypi.org` while
`redis` and `etcd` stay locally reachable and no image is pulled. The block that
was exercised is the engine's network mode; the iptables scripts in the offline
directory are an additional path for a Linux VPS, not the mechanism behind the
10/10.

*One linked trace.* The visible failover is real and it is same-box: the mutation
is rejected on the standby (`cp-b`), which is then promoted and serves the retry,
so the reject and the success land on the same node. That is precisely "rejected on
the standby, retried on the new primary," asserted on the exported spans and
scraped counters rather than on logs — and it is not a cross-node correlation.

Cross-node reject/success continuity is **not proven**. Demonstrating it would take
an etcd-only partition that cuts a node off from consensus while leaving it able to
serve, and that partition was deferred for the reason the harness pauses rather than
partitions elsewhere: multi-network fault injection is unreliable on this
single-host engine. The claim is left honest about its shape — one node, two roles
in sequence — rather than dressed as something larger.

The s08 recovery path **remains open**. When a Redis fence term is bumped ahead of
etcd out-of-band, the cluster refuses every stale writer and, by the same rule,
cannot elect a new primary until the Redis state is reset, because promotion
requires the etcd term to exceed the stored Redis term. That is the fencing
invariant working as designed, and the recovery gap it leaves was deferred as
future work, not closed.

Two harness adaptations belong in the record. The s04 scenario pauses Redis instead
of partitioning it, and s08 does not wait for a final re-election after its
deliberate fence bump. The file still named `s04_partition_primary_redis` records
what the scenario was before the adaptation — git history kept honest rather than
renamed to match. Each adaptation preserves the property its scenario tests; only
the method changed, for the same single-host reason.

Two further boundaries are settled contracts, not open questions. The observability
results are pinned to the `0.111.0` collector on this engine — a newer build will
not exec here, and re-testing on a Linux VPS is an explicit to-do — and the
fence-before-auth ordering knowingly lets an unauthenticated caller learn which node
is primary from a mutation endpoint, in exchange for a uniform standby refusal.
Non-root containers and a hash-pinned rebuild are deferred, and documented as
deferred, in the operations guide.

The numbers behind these claims are in §6, and three caveats travel with them: no
dated attestation artifact has been captured yet, only the text the verifier prints
on a pass; there is no hosted CI, so the link and cardinality checks are local
gates; and the bundle's sizes are unrecorded, only its hashes. Three of the six
findings, as §4 set out, are re-runnable from the repository and three rest on the
author's account.

## 6. Numbers appendix

The receipts behind the report. Every figure here is drawn from the repository at
commit `b9d2d12` (the Step 4 head) plus the Step 5 pre-work.

### 6.1 Commits

| Short | Date | Subject |
|-------|------|---------|
| `84b81f5` | 2026-07-24 | ops: CP HA v1 — etcd lease election + fence-term CAS (verified) |
| `e56be6c` | 2026-07-24 | ops: CP HA Step 2 split-brain harness (9/9 PASS) |
| `5dd7919` | 2026-07-25 | Step 3: Prometheus metrics + OpenTelemetry tracing for the ops/HA path |
| `b9d2d12` | 2026-07-25 | Step 4: offline / sovereign packaging — deploy + run fully offline, harness 10/10 under egress block |

The `9/9 PASS` in `e56be6c` is the nine fencing scenarios; the tenth
(failover-visibility) arrived with the observability work in `5dd7919`, making the
current total ten.

### 6.2 Tests

`pytest tests/` collects **271 tests**. Two suites are the fencing and
observability guards, and their names are the specification:

*`tests/test_ops_fencing.py` (8):* `test_promote_and_persist_cas_happy_path`,
`test_stale_persist_cas_rejected_hard`,
`test_toctou_etcd_yes_redis_cas_no_blocks_switch_and_publish`,
`test_etcd_reject_same_severity_as_cas`,
`test_celery_uses_only_fresh_live_election`,
`test_celery_task_bodies_do_not_read_cached_role`,
`test_worker_source_grep_no_stale_role_fields`,
`test_check_fence_live_ha_disabled_is_synthetic`.

*`tests/test_ops_metrics.py` (10):* `test_all_metrics_are_tess_ops_prefixed`,
`test_every_label_is_allowlisted_and_not_banned`, `test_no_metric_uses_provider_id`,
`test_provider_type_label_domain_matches_enum`,
`test_recorders_never_raise_when_disabled`, `test_recorders_never_raise_when_enabled`,
`test_fence_error_kind_maps_subclasses`,
`test_ops_task_observed_reraises_not_primary`,
`test_ops_task_observed_passes_return_value`, `test_classify_outcome_bounded`.

These run as part of `pytest`; there is no hosted CI, so this suite and the
doc-link and cardinality checks are local gates rather than a pipeline.

### 6.3 Scenario matrix

`python -m scripts.ops_cp_splitbrain run-all` runs all ten and prints `10/10 PASS`
when clean; the offline verifier asserts the same under an egress block.

| ID | Scenario |
|----|----------|
| s01 | Primary killed mid-idle |
| s02 | Primary paused (frozen process / stale lease) |
| s03 | Network partition: primary ↔ etcd |
| s04 | Primary loses Redis (paused, not partitioned) |
| s05 | Network partition: standby ↔ etcd (must not falsely promote) |
| s06 | etcd down — sitting primary demotes after lease TTL |
| s07 | Real-Redis CAS reject via `fence_term` bump |
| s08 | Empty-blob restore + stale wrong-term writer reject |
| s09 | Zombie write with a second dummy provider |
| s10 | Failover visible in metrics + one trace (needs the observability overlay) |

Scenarios s01–s09 are the fencing set; s10 is the failover-visibility scenario.

### 6.4 Metrics and queries

Thirteen `tess_ops_*` metrics (`app/ops/metrics.py`):
`role_transitions_total`, `is_primary`, `fence_term`, `fence_rejects_total`,
`lease_keepalive_total`, `lease_ttl_seconds`, `cas_total`, `mutations_total`,
`mutation_duration_seconds`, `probes_total`, `probe_duration_seconds`,
`failovers_total`, `worker_task_total`. Duration histograms use buckets
`(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)`. Label cardinality
is bounded by an allowlist — `provider_id` (an unbounded uuid) is banned as a label;
`provider_type` (four values) is used instead — and `tests/test_ops_metrics.py`
enforces it.

Example queries (from `deploy/MULTI_CLOUD.md`):

```promql
tess_ops_is_primary == 1                                             # who is primary
rate(tess_ops_role_transitions_total{transition="promote"}[5m])      # promotion rate
rate(tess_ops_fence_rejects_total[5m])                               # fence rejects by kind/surface
sum(rate(tess_ops_cas_total{result="reject"}[5m]))
  / sum(rate(tess_ops_cas_total[5m]))                                # CAS reject ratio
rate(tess_ops_mutations_total{outcome="fenced_503"}[5m])             # standby refusals
sum by (provider_type) (rate(tess_ops_probes_total{result="unhealthy"}[5m]))
rate(tess_ops_lease_keepalive_total{result="failed"}[5m])           # lease health
```

Traces nest `ops.http.mutation` → `ops.fence_gate` → `ops.persist_cas` →
`ops.publish_provider_changed` on the mutation path, and `ops.promotion` →
`ops.promote_redis_fence` / `ops.initial_persist` on promotion. The collector
(`deploy/otel-collector-config.yaml`) takes OTLP/HTTP on `:4318` and writes spans
to a file with a one-second flush.

### 6.5 Environment pins

The otel-collector is pinned to `otel/opentelemetry-collector-contrib:0.111.0` in
three places (`docker-compose.ops-obs.yml`, `deploy/offline/otel/Dockerfile`,
`deploy/MULTI_CLOUD.md`), because `0.116.0`'s distroless binary would not exec on
this Docker Desktop / WSL2 engine — with an explicit "re-test on a Linux VPS" to-do.
The Python OpenTelemetry libraries are unpinned in `requirements.txt`; their exact
versions are captured at build time in the bundle's `requirements.lock.txt`.

### 6.6 Offline bundle

`deploy/offline/build-bundle.sh` produces a single `docker save` archive of five
images by default — `tess-engine-app:offline`, `tess-engine-otel:offline`,
`tess-engine-harness-runner:offline`, `redis:7-alpine`,
`quay.io/coreos/etcd:v3.5.16` — plus two more with `--with-prod` (`caddy:2-alpine`
and a digest-pinned `ollama/ollama`). Alongside the images the archive carries a git
archive of the repository at HEAD, the built frontend, `requirements.lock.txt`, a
`bundle-lock.txt` (commit, build date, third-party digests), per-image IDs, the
installer / verifier / firewall scripts, `.env.offline.example`, a `VERSION`, and a
`MANIFEST.sha256`. The manifest records sha256 hashes and image IDs; the bundle's
byte sizes are not recorded, and none is cited here.

### 6.7 Attestation

The text below is what `deploy/offline/verify-egress-blocked.sh` prints to stdout on
a passing run — the verifier's on-pass output, not a captured dated artifact. No
dated attestation file has been produced yet; the `--report` flag added in Step 5
self-archives this block, with run metadata, on the next real run.

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

## 7. Process note

*(draft pending)*
