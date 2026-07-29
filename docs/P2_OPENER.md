# P2 — Multi-node build-out — Opener (resume here)

Cold-start doc for the **Proof Program's P2 phase** ([PROOF_PROGRAM.md](PROOF_PROGRAM.md)
§P2) — *the deployment the claim is about*: 3 TESS nodes across Hetzner locations, a
private encrypted inter-node network, same-class Ollama failover, sovereign-strict vs
availability-first mode flags, an observer node outside the cluster, and a committed
traffic generator. P2's output is not data (that's P3–P4); it is the **instrument** the
data will be collected on, built so that every later number is traceable to an artifact.

**Medium shift — read this first.** P0/P1 ran on this laptop and GitHub runners; P2 is
**consoles and SSH**. A chunk of the work can only be clicked by Jesse (Hetzner console,
payment, firewall rules, external-pinger account). Every such step below is marked
**[JESSE]** and batched where possible (Step 0), so an execution session never blocks
mid-flight discovering one. Everything not marked [JESSE] is engine work over SSH from
this laptop.

Filing: [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P2 (topology, gates, cost) and
§Decisions to confirm before P2 (all six now DECIDED — recorded below). Authoring
provenance: the session plan behind this opener was cold-reviewed (5 findings folded)
and reviewed by Jesse 2026-07-30 (3 findings folded: the exposure posture → decision
7; the network-encryption facts → §(b); the third — closing a stale cross-channel GCP
thread — lives in the session handover memory, not this doc); the five pre-P2 gut
calls were ratified by Jesse on the record 2026-07-29. This draft then received its
own cold-context review — 1 blocking + 3 should-fix + 4 notes, all folded, marked
**(cold-review F*n*)** at their fold sites; the full ledger is in the PR body.
**Merge of this PR is the ratification act** for every PROPOSED item below.
File:line references verified 2026-07-30 at `4ed691a`.

---

## Start state (verify first)

1. **This opener's docs-only PR is merged** — the merge is the ratification act.
   `git checkout main && git pull`, confirm, then branch per step.
2. Baselines: `python -m pytest tests/ -q` → **460 passed, 6 skipped** (re-baseline
   inline if main moved); `python -m scripts.check_doc_links` → **0 broken**.
3. **Nightly is green and schedule-proven** — `gh run list --workflow=nightly.yml`
   shows a green streak including at least one `--event=schedule` run; the
   "schedule proven" line is recorded in [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P1
   (if still pending, record it first — it is §P1's last soft claim, and P2's soaks
   lean on the nightly as the "frozen and still healthy" checker).
4. **PR #23 (x-bit class closure) is merged** — the deploy scripts P2 runs on real
   nodes (`deploy/server-bootstrap.sh`, `deploy/deploy.sh`) should carry `100755`
   before they're shipped to hardware. If still open, get it merged first
   (one-click, already all-green).
5. **Prod (`5.78.186.223`, CPX11) is untouched by P2.** The cluster is new, parallel
   infrastructure; nothing in this phase redeploys, reconfigures, or reuses prod.
   Prod's UptimeRobot monitor (`803559917`) stays pointed at prod.
6. Local gates remain available (docker stack, host Ollama) — pre-push discipline
   (split-brain harness, eval smoke where chain-adjacent) still runs locally.

---

## Settled decisions (items 1–6 DECIDED on the record; item 7 PROPOSED, ratified by this merge)

1. **Availability target — DECIDED (2026-07-29, Jesse): 99.9% publicly held.**
   "Same nines a single VPS claims, but demonstrated through node death and
   datacenter faults." A measured 99.95%+ against a 99.9% target reads as
   overdelivery; scraping past an aggressive target engineered to be barely
   survivable by our own chaos design does not. The multi-node claim is *proof
   under faults*, not a bigger number.
2. **The 900 s resume-refusal window — DECIDED (2026-07-29, Jesse, §P0): counts
   against availability** in published numbers until the W4 liveness-checked
   refusal removes it. Restated here because it shapes the methodology text the
   observer's data feeds (PROOF_PROGRAM §Decisions item 2).
3. **Chaos schedule — DECIDED (2026-07-29, Jesse): full schedule including
   partition drills in P4.** Partitions are the reason consensus-backed HA exists;
   a soak that never partitions benchmarks the feature everyone has and asserts
   the one nobody else has. An ugly partition window is a publishable finding
   under the asymmetric-honesty rule, not a failed study. (Schedule *frequencies*
   are P3's calibration output, not fixed here.)
4. **Observer — DECIDED (2026-07-29, Jesse): both.** A 4th tiny Hetzner node runs
   the real black-box probe; a free-tier external pinger watches **only the
   observer node, never TESS** — the third party never enters the measurement
   path, it answers "was the witness awake." Without it, an observer outage is
   indistinguishable after the fact from a service outage: a hole in the
   availability data. €4–5/month plus a free pinger buys a measurement chain with
   no unwatched link.
5. **Comparison stack — DECIDED (2026-07-29, Jesse): LiteLLM only.** One
   identical-footprint stand-up keeps P5 bounded; two stacks run fairly is a
   methodology burden that risks doing both shallowly. A Portkey comparison is
   filed as future work in the report — it signals the harness generalizes, which
   is itself part of the reproducibility claim.
6. **Budget ceiling — DECIDED (2026-07-29, Jesse): €100–120/month for the P4+P5
   peak window.** Rationale (Jesse): P1's probe measured CPU-only llama3.2 ~7×
   slower than the laptop on one nightly smoke; P2's nodes serve it under
   sustained traffic. A mid-program node-class resize re-baselines every latency
   number measured before it — a clock-reset by construction. €100–120 converts
   that risk into "start with comfortable node classes and never have the
   conversation." Peak is temporary: steady-state drops to ~€25–30/month after P5
   teardown.
7. **Exposure posture — PROPOSED (2026-07-30, Jesse, plan review; ratified by this
   PR's merge): scoped IPs only through P2–P4.** The cluster is reachable only
   from Jesse's IP(s), the observer node, and inter-node traffic; public exposure
   is deferred as a **P6 demo decision**. This extends the current prod firewall
   posture to the new nodes, turns the WS resume trust-model note (client-held
   `session_id` can steer — [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P2
   known-interaction) into a documented-but-unexposed limitation during the soak,
   and keeps TLS/auth design off P2's critical path. Stated here so execution
   never improvises firewall scope per node.
8. **Authority unchanged:** consoles and payment are Jesse's; PRs are opened,
   merged by Jesse; decisions originated by the engine are PROPOSED until
   ratified.

---

## Resolved questions (design proposals — PROPOSED, ratified by this PR's merge)

### (a) Locations, node classes, and price against the ceiling

| Node | Location | Class (shared AMD) | Role | ~€/mo |
|---|---|---|---|---|
| node-1 | `fsn1` Falkenstein | CPX41 (8 vCPU / 16 GB) | etcd-1 · CP-A (web+ops) · worker · redis · **ollama-1** · TESS stack `hetzner-1` | ~25 |
| node-2 | `nbg1` Nuremberg | CPX41 (8 vCPU / 16 GB) | etcd-2 · CP-B (standby) · worker · redis · **ollama-2** · TESS stack `hetzner-2` | ~25 |
| node-3 | `hel1` Helsinki | CPX21 (3 vCPU / 4 GB) | etcd-3 (quorum member; no LLM serving) | ~8 |
| observer | `ash` Ashburn | CPX11 (2 vCPU / 2 GB) | black-box probe · traffic generator · raw-data spool | ~5 |

≈ €63/month + IPv4/traffic ≈ **€65–70 for P2–P4**; P5 adds the LiteLLM comparison
sized to the **serving footprint** (2× CPX41 ≈ €50 — each stack carries its own
control-plane overhead as part of its own cost: TESS's etcd witness is TESS's
architecture cost, not replicated on the comparison; recorded as a PROPOSED
amendment to PROOF_PROGRAM §P5's "identical footprint" wording in the companion
edit, ratified with this PR, and binding on P5's pre-registration — cold-review F3)
→ peak ≈ **€115–120, at the ceiling's top edge**. If Step 0's
console pricing pushes the total past €120, the resize happens at Step 0 (or the
P5 opener for the comparison window) — never mid-soak. Three cluster locations
(not two) puts every etcd member
in a different datacenter — any single-location fault is a 1-of-3 loss, which is the
datacenter-correlation claim in its strongest testable form. **Prices are from
training-data memory — [JESSE] verifies current console pricing at Step 0 before
creating anything; if the total exceeds the ceiling, resize at the console, never
mid-soak.** Serving-node sizing is deliberately comfortable (decision 6); the
measure-before-pin rule still applies — Step 1 measures on-node inference walls
before any traffic rate or timeout is pinned.

**Gate-wording amendment (PROPOSED, cold-review F1 — ratified by this PR's merge,
companion-edited into PROOF_PROGRAM §P2, never silently reinterpreted):** §P2's gate
says "full stack green on all 3 nodes"; this topology's node-3 is a **quorum witness
by design**, so the gate reads: **full stacks green on both serving nodes + witness
(etcd member) green on node-3.** The alternative — a third full stack on node-3 with
its LLM served from a peer's Ollama over WG — was considered and **rejected as a
failover trap**: `/health` scores Redis + host load, not inference
([deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md) §`/health` contract ~:535), so a
stack whose Ollama lives on a dead peer reports healthy while unable to answer, and
failing over *to* it would be exactly the wrong move. Two honest serving stacks plus
one honest witness beats three stacks, one of which lies.

### (b) Private network: WireGuard over Hetzner Cloud Network

Hetzner Cloud Networks span locations within a network zone — `fsn1`, `nbg1`, `hel1`
are all `eu-central`, so the planned topology fits — but Hetzner documents that
private-network traffic is **not encrypted** on their fabric. For a
sovereignty-branded report with a threat-model section, "inter-node traffic is
encrypted via WireGuard over the provider's private network" is a one-sentence claim
that preempts an obvious reviewer question; "we assumed the private network was
private" is not a sentence to write in the report. **Proposal: WireGuard mesh among
the 3 cluster nodes, tunneled over the Cloud Network private IPs (belt: private
fabric; braces: encryption).** etcd peering, CP↔stack probes, and any inter-node
Redis traffic bind to WG addresses. The observer is deliberately **not** on the
private network or the mesh — it probes the same scoped public path a user would.
Setup is a committed script (`deploy/p2/wireguard-mesh.sh`, new) + per-node config;
keys generated on-node over SSH, private keys never leave their node. Server-to-server
traffic between owned nodes does not breach sovereignty (PROOF_PROGRAM §Terminology).

### (c) Same-class Ollama failover rides the existing provider registry

Failover machinery exists and is live-verified — do **not** redesign it:
`evaluate_failover` / `_switch` / `force_active_provider`
([app/ops/failover.py](../app/ops/failover.py) ~:22/:156/:226), the provider
registry and `/health` prober ([deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md)
§Provider registry ~:556, §`/health` contract ~:535), `provider_changed` WS notice
(§Frontend notice ~:576). P2's new thing is only the *shape* of the fleet: two
same-class providers (`hetzner-1` on node-1, `hetzner-2` on node-2, both full TESS
stacks serving llama3.2 via their local Ollama). An Ollama or node fault on the
active stack fails over to the peer — **failover, not fallback** (PROOF_PROGRAM
§Terminology): the sovereign claim survives the switch. Registration mechanics
(cold-review F2): the registry today bootstraps Hetzner from `OPS_LOCAL_BASE_URL`
plus AWS/GCP env slots ([app/core/config.py](../app/core/config.py) ~:37-57).
**Do not register the peer via `POST /ops/byo`** — the BYO path hard-codes
`type=ProviderType.CUSTOMER` ([app/ops/byo.py](../app/ops/byo.py) ~:32), which would
label every failover event hetzner→customer in exactly the dimension this phase
publishes. `POST /ops/providers` accepts an explicit `type`
([app/api/ops.py](../app/api/ops.py) ~:200) — `hetzner-2` registers there with the
correct type; if env-driven bootstrap proves cleaner at execution, an
`OPS_PEER_BASE_URL` slot is a small config addition with the house inline comment.
`provider_type` (bounded enum) labels metrics, never `provider_id` — the cardinality
discipline is unchanged.

### (d) Mode flags + in-process egress verification (the product work)

**Nothing exists today** — no sovereign/strict/egress flag anywhere in `app/`
(grep-verified at authoring); egress blocking is compose-level only
(`docker-compose.offline.yml` `internal:` networks +
[deploy/offline/verify-egress-blocked.sh](../deploy/offline/verify-egress-blocked.sh)).
Design:

- A settings enum in [app/core/config.py](../app/core/config.py), e.g.
  `tess_runtime_posture: "sovereign-strict" | "availability-first"` (exact name at
  execution; distinct from `product_modes.py`, which is routing behavior, not
  posture). Availability-first is today's behavior, unchanged.
- **Strict mode blocks third-party egress in-process**: the LLM factory
  ([app/llm/factory.py](../app/llm/factory.py)) refuses non-local providers, and
  the search provider layer ([app/search/provider.py](../app/search/provider.py))
  refuses third-party search (DuckDuckGo/Tavily are third parties) — enforcement at
  the provider/factory seam, **not** in `app/graph/**`, keeping the chain-change
  eval gate out of the blast radius where possible.
- **Verification is in-process, never container-env** (the arc's recurring-failure
  countermeasure, twice bitten): the process itself proves its posture — startup
  (and on-demand via an admin endpoint) it attempts a canary connection to a known
  third-party host and **asserts the attempt is refused by its own guard**,
  reporting posture + canary result in an ops-readable artifact (e.g. a
  `/ops/posture` read or a `/health` field — artifact, not log line). The
  split-brain-harness assertion style applies: assert on artifacts.
- **Red-first before trusted:** with the guard deliberately disabled (or posture
  availability-first), the canary must succeed and the strict-mode assertion must
  fail loudly — the planted-violation idiom from P1, applied to the flag.
- All published numbers are labeled by posture; the sovereign-strict chart is the
  one competitors can't match (PROOF_PROGRAM §P2).

Scope note: this touches `app/core/config.py`, `app/llm/`, `app/search/`, `app/ops/`
— unit-first with red-first tests. If anything chain-adjacent moves
(`app/graph/**`, `app/agents/**`, prompts, routing), the graph eval smoke gate runs
per CLAUDE.md; the design above avoids that path deliberately.

### (e) Split-brain harness against the real cluster — the fault-driver seam

The P2 gate says the harness passes **against the real cluster**, and today it
cannot: HTTP endpoints are already env-overridable
([scripts/ops_cp_splitbrain/config.py](../scripts/ops_cp_splitbrain/config.py)
~:63-64 `OPS_HA_SMOKE_A/B`, ~:86 worker-metrics URL), but **fault injection drives
local docker** ([scripts/ops_cp_splitbrain/docker_util.py](../scripts/ops_cp_splitbrain/docker_util.py);
container-name resolution ~:71-72), and partition scenarios manipulate docker
networks that don't exist between real VMs. **Proposal: a fault-driver seam** —
the local-compose driver is today's `docker_util` unchanged (the 11-scenario dev
gate stays byte-identical); a remote driver maps each fault primitive to the
cluster: container pause/kill/restart via docker over SSH
(`DOCKER_HOST=ssh://…` per node, driven from the laptop), inter-location partition
via on-node firewall rules cutting the WireGuard/private path between chosen nodes
(applied and reverted by the driver, artifact-asserted like everything else).
Per-scenario semantics get an explicit mapping review — **any scenario whose
semantics cannot honestly map to the real topology is a finding brought to Jesse,
never a silent skip** (the `s11` topology-SKIP precedent shows what an *explicit*
skip looks like). Harness-change discipline applies in full (local dev `run-all`
11/11 + offline verifier chain green before any harness commit — CLAUDE.md).
**Threat-model line (stated, not hidden):** the laptop harness holds SSH keys to
all cluster nodes for fault injection; key provisioning is a **[JESSE]** step, keys
are cluster-scoped only, and the report's threat model says so explicitly.

### (f) Observer probe + external pinger

The observer (Ashburn, outside the cluster and off the private network) runs a
committed probe (`scripts/observer/`, new): a cheap `GET /health` per stack **plus a
periodic end-to-end request through the real product path** (WS in, panel out — an
L0-profile round-trip; request success + latency from the user's perspective is the
availability datum, per PROOF_PROGRAM §P4 "source of truth"). Results spool locally
as append-only JSONL — the raw data that lands in the repo. Location trade-off,
stated honestly: Ashburn is geographically independent of all three cluster
locations (a `eu-central` location fault can never take a cluster node *and* the
witness), at the cost of measuring trans-Atlantic internet as part of the path; the
alternative (observer in `hel1`) shares a location with node-3. **Proposal: Ashburn,
with the adjudication rule pre-registered in the methodology** — a window where the
observer sees failure but internal metrics + the second vantage show the service
healthy is logged with provenance and adjudicated by the pre-registered rule, never
reclassified after the fact. The external pinger (UptimeRobot free tier — prior art:
prod monitor `803559917`, [deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md)
§External uptime ~:905) watches **only the observer node** — decision 4's
sovereign-clean boundary. Pinger account/monitor setup is **[JESSE]**.
Co-residency caveat (cold-review F7): the traffic generator shares the observer's
2 vCPUs with the probe — generation never competes with *serving*, but it can skew
the probe's own latency samples. Burst windows are logged in the same JSONL, so
probe samples taken during bursts are identifiable at analysis; if Step 7's smoke
shows material skew, the observer upsizes one class (~+€2/mo) before P4 — never
mid-soak.

### (g) Traffic generator — committed, measured, honest about rates

New `scripts/traffic_gen/` (nothing load-shaped exists in `scripts/` today —
confirmed at authoring): an async WS client driving the real product interface with
a committed request-profile config — mixed chain profiles and request sizes,
streaming and non-streaming, burst windows, and injected provider timeouts (the
gateway-realistic profile PROOF_PROGRAM §P2 names). Per-request outcome + latency
spool to JSONL. Runs on the observer node (outside the cluster, so generation load
never competes with serving). **Rates are pinned from Step 1's on-node inference
measurements, never guessed** (measure-before-pin) — CPU-only llama3.2 sustains
low-single-digit concurrent sessions per serving node; the profile is sized to
realistic sustained load with headroom, and the pinned numbers carry the house
inline re-baseline comment citing the measurement.

### (h) What P2 explicitly does not include

The chaos *schedule* (frequencies, calendar) — P3's calibration; TLS/public
exposure — deferred to P6 by decision 7; the comparison stack stand-up — P5 (only
its footprint is priced here); W4 seamless migration — branches only, per
PROOF_PROGRAM §Relationship; automating the manual interrupt→resume live smoke —
P3-adjacent follow-up from P1, unchanged.

---

## Steps (proposed sessions — each gated, each with its red-first where applicable)

### Step 0 — Console batch **[JESSE, one sitting]**

Create in the Hetzner console: the 4 servers per table (a) (Ubuntu 24.04 — the
image [deploy/server-bootstrap.sh](../deploy/server-bootstrap.sh) ~:2 targets);
one Cloud Network (`eu-central`) attaching node-1/2/3 (observer excluded); Cloud
Firewall rules per decision 7, **enumerated so nothing is improvised (cold-review
F4)**: SSH (22) → Jesse's IP(s) (the laptop doubles as the harness vantage);
web + CP ports (80/443, :8000, :8001) → Jesse's IP(s) + the observer's IP;
worker-metrics (:9109) → Jesse's IP(s) only (the harness asserts on it —
`OPS_HA_WORKER_METRICS`,
[scripts/ops_cp_splitbrain/config.py](../scripts/ops_cp_splitbrain/config.py) ~:86);
everything else closed; inter-node traffic rides the private network/WG only (cloud
firewalls filter the public interface — see Environment notes). Upload the engine's
fault-injection SSH public key to the 3 cluster nodes (threat-model line in (e));
verify console pricing against table (a) and the ceiling. Also: UptimeRobot monitor
for the observer's own liveness endpoint (or defer to Step 6 when the observer
exists). **Deliverable to the execution session: 4 IPs + confirmation the firewall
posture matches the enumeration above.**

- **Verify:** engine can SSH to all 4 nodes; **red-first from a named vantage
  (cold-review F4):** prod (`5.78.186.223`) is deliberately NOT allowlisted and is
  the non-allowlisted probe source — from prod, web/:8000/:9109 must all refuse;
  run the probe *before and after* the rules land, both results recorded.

### Step 1 — Bootstrap + WireGuard mesh + measurement probe

- `server-bootstrap.sh` per node (over SSH); commit `deploy/p2/wireguard-mesh.sh` +
  per-node config; bring up the 3-node WG mesh over Cloud Network IPs; observer
  bootstraps without WG.
- **Measurement (measure-before-pin, P1 precedent):** on-node llama3.2 inference
  walls on a serving node (eval-smoke-style prompts), disk, and inter-node WG
  latency — these numbers pin Step 2's etcd tuning sanity-check, (g)'s traffic
  rates, and every timeout this phase writes. Mechanism (cold-review F8): the prod
  compose's `ollama` service started alone via its profile
  ([deploy/deploy.sh](../deploy/deploy.sh) ~:69-86 precedent — `--profile ollama
  … up -d ollama`, model pull per ~:83-86, pinned `llama3.2`), two steps before
  any full stack lands in Step 3.
- **Verify:** WG mesh pings all pairs; ufw/cloud-firewall posture re-probed;
  measured numbers recorded in the PR/step log.

### Step 2 — etcd quorum + CP HA pair across real nodes

- Adapt the HA topology (dev prior art: 3×etcd + web/web-standby on one host,
  [docker-compose.ops-ha.yml](../docker-compose.ops-ha.yml) ~:50-70/:85/:107) into
  per-node compose/env: etcd-1/2/3 peering over WG, CP-A on node-1, CP-B on node-2,
  `ops_fence_authority=etcd` default untouched.
- `OPS_ADMIN_TOKEN`: generated **once**, single-sourced into every node's `.env`
  over SSH (never committed) — CP-A, CP-B, and the harness read the same value.
  The P1 token-drift lesson (the 403 storm), institutionalized (cold-review F4).
- **Verify (artifact-asserted):** etcd cluster healthy across locations; CP-A
  primary / CP-B standby with the fence term monotonic; **red-first quorum proof:**
  stop one etcd member → durable ops writes continue; stop a second → writes block
  with the fence body (the s11-family behavior, now on real hardware); restart →
  recovery within bound.

### Step 3 — Provider stacks + same-class failover live

- Deploy full TESS stacks on node-1/2 (`hetzner-1`, `hetzner-2`); register per (c);
  prober scoring both.
- **Verify:** kill ollama-1 (then the whole node-1 stack) → `active_provider_id`
  flips to `hetzner-2`, `provider_changed` published, `/ops/events` +
  `last_failover_at` artifacts recorded; failover time measured (the local 2.1 s
  question — PROOF_PROGRAM §P4 — gets its first real-VPS number here, informally).

### Step 4 — Mode flags + in-process egress guard (product work, red-first)

- Implement (d): posture enum, factory/search guards, in-process canary
  verification, unit tests red-first (guard absent → canary succeeds → assertion
  fails loudly; guard present → refused).
- **Verify:** strict posture on node-1/2 stacks blocks the canary in-process and
  reports it in the ops artifact; availability-first unchanged; unit suite green at
  the (re-baselined, inline-commented) tally; eval smoke run if anything
  chain-adjacent moved.

### Step 5 — Harness fault-driver seam + run against the cluster

- Implement (e); local dev gate stays 11/11 byte-identical before the remote driver
  lands (harness-change discipline: dev `run-all` + offline chain green
  pre-commit).
- **Verify (the phase's headline gate):** `run-all` against the real cluster passes
  with every scenario either PASS or an explicit, Jesse-reviewed mapping decision —
  no silent skips; partition scenarios cut real inter-location links and heal them;
  all assertions on artifacts (Redis/etcd term, HTTP bodies, pubsub), per house
  rule.

### Step 6 — Observer + external pinger + witness-survival proof

- Deploy (f) on the observer; **[JESSE]** creates the UptimeRobot monitor watching
  the observer (if not done in Step 0).
- **Verify:** kill each cluster node in turn → the observer's JSONL shows the
  window (or clean failover) for each — **the observer demonstrably survives any
  single node's death** (P2 gate); kill the observer → the external pinger alerts
  (witness watched); restore everything.

### Step 7 — Traffic generator + sustained smoke

- Commit (g); run a multi-hour sustained profile against the cluster at the pinned
  rates.
- **Verify:** spooled JSONL shows the profile ran as configured; injected provider
  timeouts are recorded as what they are (no silent success — red-first: an
  injected timeout must appear as a failure record); serving nodes stay inside
  their measured envelopes.

### Step 8 — Docs flip + phase gate checklist

- [PROOF_PROGRAM.md](PROOF_PROGRAM.md) §P2 `⬜ → ✅` with the gate evidence
  pointers (harness-vs-cluster run, witness-survival proof, in-process egress
  artifact, both serving stacks + witness green per the amended gate — F1);
  [deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md)
  gains the P2 cluster runbook section; CLAUDE.md file-pointer table gains the new
  scripts; handover memory updated.
- **Verify:** `python -m scripts.check_doc_links` → 0 broken; suite green at the
  final tally; PR into main, merge left to Jesse.

**Sizing:** ~2–3 engine sessions + Jesse's Step 0 sitting, matching PROOF_PROGRAM
§P2's estimate. Severability: Steps 4 and 7 are severable to a follow-up session
without blocking Steps 5–6 (the harness gate needs only Steps 0–3); Step 8 lands
only when every gate above it has.

---

## House rules (unchanged, restated for the new medium)

Every gate is proven **non-vacuous** before its green is trusted (red-first probes:
firewall refused-from-outside, quorum-loss write-block, guard-disabled canary,
injected-timeout visibility); assertions target **artifacts** (etcd/Redis state,
HTTP bodies, JSONL spools), never log strings; a harness failure against the real
cluster is a **product bug until proven otherwise** — fix the product, never soften
the assertion; tallies and pins are executable claims with the house inline
re-baseline comment citing their measurement; suite + doc-links green per commit;
PRs into main, **merge left to Jesse**; review-trail counts travel with the content.
Scope fence: `app/**` changes only within Step 4's stated seam (config/llm/search/
ops) — anything chain-adjacent triggers the eval gate; `scripts/ops_cp_splitbrain/**`
changes carry the harness-change discipline; golden-set composition and judge
identity are untouched this phase.

## Environment notes

- **WireGuard over Cloud Network:** clamp MTU (~1400) on WG interfaces — fragment
  storms over tunnels are a classic silent-latency source; verify with a
  full-size-payload ping before etcd rides it.
- **Hetzner Cloud Firewalls filter the public interface** — private-network/WG
  traffic needs its own posture (ufw on WG/private interfaces); the Step 0/1
  red-first probe covers both layers.
- **etcd across ~25 ms links (fsn↔hel):** defaults tolerate this easily
  (lease TTL 10 s, campaign 2 s — [app/core/config.py](../app/core/config.py)
  ~:73-74), but record the measured inter-node RTT in Step 1 anyway; if any
  etcd timeout is ever tuned, the inline comment cites that measurement.
- **`OPS_LOCAL_BASE_URL` loopback lesson** ([deploy/MULTI_CLOUD.md](../deploy/MULTI_CLOUD.md)
  §Provider registry note ~:567-572): compose service aliases don't survive
  network heals — on the real cluster, registry base URLs use WG IPs or loopback,
  never compose aliases.
- **PS 5.1 quote-mangling** (laptop side): commit/PR bodies via `git commit -F` /
  `--body-file`; `gh` at `C:\Program Files\GitHub CLI\gh.exe`.
- **SSH-driven docker (`DOCKER_HOST=ssh://`)** needs a docker CLI on the laptop
  side and dockerd on nodes only — no docker API exposed on any public interface,
  ever (the scoped-IP posture covers SSH only).
- **Ashburn observer probes over the public path** — its source IP must be in the
  cluster's firewall allowlist (Step 0) and the WS base URL it probes is the
  scoped public one, not a WG address.

## Follow-ups filed (not P2 blockers)

- **P1 carry-overs, unchanged owners:** s11 single-node variant; full-20 eval
  nightly; manual interrupt→resume smoke automation (P3-adjacent — the chaos
  schedule will want it); nightly heartbeat visibility (60-day auto-disable).
- **`redis-parity` → required checks** — Jesse console step after a few days green
  (~2026-08-01+).
- **Chaos schedule authoring** — P3 opener's first act, using Step 1's measured
  envelopes.
- **LiteLLM comparison methodology pre-registration** — written before P5 runs
  (PROOF_PROGRAM §P5 gate), not during.
- **Steady-state teardown plan** — post-P5 downsizing to the ~€25–30/month posture
  (decision 6's tail).
