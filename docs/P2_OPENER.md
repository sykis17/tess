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

**As-built record (2026-07-30, Step 0 + Step 1 measurement — supersedes the
price/class arithmetic above, which was training-vintage):** the April 2026
Hetzner repricing made the ratified classes unaffordable at the ratified ceiling
(console: CPX42 = €87.21/mo gross), so the class question was resolved by the
house's own doctrine — measure before pin:

| Node | Location | As-built class | Public IP | Console net €/mo |
|---|---|---|---|---|
| tess-p2-node1 | `fsn1` | **CPX32** (4 vCPU/8 GB) | 78.47.69.162 (`10.0.0.2`) | 35.49 + 0.50 IP |
| tess-p2-node2 | `nbg1` | **CPX32** | 5.75.186.164 (`10.0.0.3`) | 35.49 + 0.50 |
| tess-p2-node3 | `hel1` | **CPX12** (1 vCPU/2 GB, witness) | 77.42.71.248 (`10.0.0.4`) | 11.49 + 0.50 |
| tess-p2-observer | `ash` | **CPX11** (2 vCPU/2 GB) | 5.161.245.44 (no private net) | 17.49 + 0.50 |

- **Step 1 inference probe on the as-built CPX32** (node1; ollama via the compose
  profile, pinned llama3.2; raw JSONs at node1:`/root/p2-artifacts/step1-probe/`):
  generation **31–34 t/s stable** across 94–645-token answers; prompt eval
  ~180 t/s; warm load 0.2 s (cold 3.0 s); 2-concurrent serializes at full
  per-request rate (Ollama default, matching the product's own request lock).
- **Class — DECIDED (2026-07-30, Jesse): keep CPX32, measured acceptance.**
  33 t/s serves the gateway traffic profile; the program's headline claim is
  availability behavior, not throughput; the hardware class is published with
  every number. (The 7×-slow figure came from a different instrument — a GH
  runner; this is the number on *this* instrument.)
- **Ceiling — AMENDED, DECIDED (2026-07-30, Jesse):** P2–P4 fleet =
  **€101.96 net ≈ €128/mo gross** (source: Hetzner usage preview, 2026-07-30 —
  per-row "max €/month" × 25.5 % VAT). The P5 comparison serving footprint
  (2× CPX32 + IPs ≈ €72 net ≈ €90 gross at current prices → peak ≈ €218/mo
  gross) **files to the P5 opener**, per this opener's pre-authorization.
- **Step 0 gate evidence banked:** fence red/green pair (before: `:22` OPEN ×4
  from prod; after: 12/12 refused from prod, laptop SSH ×4 admitted); x-bit
  full-circle (fresh clone on node1: all three deploy scripts `-rwxr-xr-x`).

**Step 1 as-built (2026-07-30, this PR — closes opener Step 1):**

- **Bootstrap:** node2/node3/observer bootstrapped with the committed
  `server-bootstrap.sh` (scp'd + run as root over SSH; Docker 29.6.2 +
  Node 20.20.2 on each); fresh clones at `/opt/tess-engine` show all three
  deploy scripts `-rwxr-xr-x` — x-bit full circle now proven on all 4 nodes.
  Disk as measured (`df -h /`): node1 150 GB (12 GB used), node2 150 GB
  (2.1 GB), node3 38 GB (2.1 GB), observer 38 GB (2.2 GB).
- **WireGuard mesh (parameters PROPOSED here, ratified by this PR's merge —
  §(b) fixed none):** committed `deploy/p2/wireguard-mesh.sh` +
  `deploy/p2/mesh-inventory.env` (no secrets: keys generated on-node, private
  keys never left their node). `wg0` on `10.8.0.0/24` — node1 `10.8.0.1`,
  node2 `10.8.0.2`, node3 `10.8.0.3` — port `51820/udp`, keepalive 25 s;
  observer excluded per §(b). **MTU 1370, measured** (parent `enp7s0`
  MTU 1450 − 80 WG overhead; the opener's "~1400" was an estimate), proven
  two-color on all three pairs: DF payload 1342 passes, 1343 refused —
  boundary-sharp. Public keys: node1
  `BaJwtu3qG9IvCIdgoF9b1MZp5qXRV6c1Oe+DQZ7SLEo=`, node2
  `meFFelSf0uldgB66Y/Q52CmQBT24mBwZIEavONAt01A=`, node3
  `Ulnb/BB8zgJ4hrIfrQFMTORbP4jk9PFddmyXXxi8+wU=`. Reachability stated
  honestly: WG's `ListenPort` binds all interfaces (no listen-address option
  exists) — 51820's non-reachability from outside rests on the Cloud Firewall
  ("everything else closed", Step 0) plus ufw default-deny with
  `allow from 10.0.0.0/16` (subnet derived from `ip route`; the address
  itself is assigned /32) and `allow in on wg0` (Step 2 etcd
  pre-provisioning — its own PROPOSED line in the PR body). Verify
  transcript: node1:`/root/p2-artifacts/step1-mesh/mesh-verify-20260730T030415Z.txt`.
- **Inter-node WG RTT (measure-before-pin; pins Step 2's etcd sanity
  check):** fsn↔nbg **3.3–3.4 ms** · fsn↔hel **25.6–26.0 ms** · nbg↔hel
  **24.4–24.6 ms** (`ping -c 4` avg, both directions) — fsn↔hel lands on the
  opener's ~25 ms expectation; etcd defaults (lease TTL 10 s, campaign 2 s)
  untouched.
- **Fence re-probed post-change, all 4 nodes:** from prod (the named
  non-allowlisted vantage), `22/8000/9109` ×4 = **12/12 refused** — re-proven
  after this step's firewall deltas (ufw newly enabled on the three
  bootstrapped nodes; WG ufw rules landed on all three cluster nodes
  including node1, whose Step 0 result predated them).
- **Reboot persistence, proven by an actual reboot:** node3 rebooted (boot
  epoch 1785380977); `wg-quick@wg0` active on return, pings to both peers
  green, both peer handshakes fresh post-boot (epoch 1785380988) — **PASS**.
- **Node2 inference probe (instrument parity — an addition beyond the Step 1
  bullet, which required only one serving node) — FINDING, brought to Jesse,
  not silently accepted:** mechanism identical to node1's (compose `ollama`
  profile started alone, `--env-file .env.prod`, pinned `llama3.2`,
  API-based; raw JSONs at node2:`/root/p2-artifacts/step1-probe/`; prompt
  text reconstructed to the same seven shapes — the originals were not
  preserved on-node, and response JSONs carry no prompt field). Result:
  generation **20.0–24.3 t/s** across the seven shapes vs node1's
  31–34 t/s — **~32% slower on the same CPX32 class**. Qualified, not noise:
  simultaneous same-prompt rerun on both nodes = node1 **34.4 t/s** vs node2
  **23.3 t/s** (`probe-medium-rerun.json` on each), `vmstat` steal 0.0%
  during generation on both, identical advertised silicon (AMD EPYC-Genoa,
  4 vCPU) — host-level variance between same-class shared instances.
  Cache-hit prompt eval (1135 t/s) and 2-concurrent serialization (pair
  wall 76 s) behave like node1's. Disposition is a console decision (accept
  and publish per-node envelopes · recreate node2 to land a different host,
  cheap while nothing rides on it · escalate to Hetzner); **no traffic rate
  or timeout is pinned from node2's numbers until decided** — (g)'s rates
  pin from the slowest accepted serving node.
- **Node2 disposition — RESOLVED (2026-07-30, Jesse's ladder, PR #26 review):
  recreated to a nominal host.** The pre-registered ladder: (1) console
  power-cycle (~03:37 UTC) → **no movement**, mean 23.4 t/s (20.1–27.1) —
  host retained across stop/start; (2) delete + recreate, same
  name/class/location, same IPs re-landed (public 5.75.186.164, private
  10.0.0.3 — inventory unchanged) → bootstrap + mesh + probe re-run entirely
  from the committed scripts (**the idempotency claim, field-proven**:
  node1/node3 kept their keys, node2 rekeyed, all confs re-rendered, VERIFY
  OK, MTU 1370 again, RTTs consistent — transcript
  node1:`/root/p2-artifacts/step1-mesh/mesh-verify-20260730T040204Z.txt`).
  New draw: **32.1–36.9 t/s, mean 34.4** — inside node1's band; class
  homogeneity restored. One retry used per the one-retry rule. Fence
  re-probed post-recreate from prod: **12/12 refused**. Node2's WG public
  key is now `T0YmAhGfTjk78IBDqdd3uJfEF8ySZYJFw0RFoRLLB0I=` (supersedes the
  `meFF…t01A=` key above — the old server is gone). The two-draw variance
  observation (34 / 23 / 34 t/s on one class) is filed in
  [IDEAS.md](IDEAS.md) as the per-node-probe admission-gate entry.
- **Artifact-durability lesson (recorded, not hidden):** the old node2's
  on-node artifacts (`step1-probe/` incl. the rerun pair,
  `ladder-rung1-probe/`) were destroyed with the server; their summaries are
  preserved at node1:`/root/p2-artifacts/ladder/old-node2-summaries.txt` and
  in PR #26/#27 bodies. Fleet artifacts now copy to node1 (the durable
  artifact home) — a node's own disk is not provenance storage.
- **Probe instrument committed (from the reconstruction lesson):**
  `deploy/p2/inference-probe.sh` — the seven shapes with every request JSON
  saved alongside its response (`probe-*.request.json`); no future probe can
  need prompt reconstruction. New node2's nominal probe ran with it
  (node2:`/root/p2-artifacts/step1-probe/`, requests included).

**Step 2 as-built (2026-07-30, this PR — closes opener Step 2; artifacts at
node1:`/root/p2-artifacts/step2-cp/`, 26 files incl. full battery transcript):**

- **Topology live:** etcd-1/2/3 across fsn1/nbg1/hel1 peering over wg0
  (`10.8.0.1/.2/.3:2380`), CP-A on node1 (:8000, + redis + worker
  `--concurrency=1`), CP-B on node2 (:8001→8000); `ops_fence_authority=etcd`
  untouched. Committed: `deploy/p2/docker-compose.p2-cp.yml` (one file,
  identity via `deploy/p2/env/node{1,2,3}.env`, roles via profiles) +
  `deploy/p2/cp-env-sync.sh`. First campaign went to CP-B (build-order
  artifact — roles are symmetric by design; the battery ran role-aware).
- **Timing vs geography (checklist §1, arithmetic in the compose comments):**
  heartbeat 100 ms = 3.9× worst measured RTT (25.7 ms fsn↔hel), election
  1000 ms = 10× heartbeat — stock values hold, set explicitly, never
  inherited. App layer verified live: ladder worst case 6 s < TTL 10 s;
  re-election after quorum restore took **≤ 8 s**; CP takeover within bound.
  Harness convergence budgets (3× TTL) survive geography unchanged; the
  real-cluster harness profile decision travels to Step 5.
- **Hairpin finding (live, own bullet — it revises the plan's CR2-4):** a
  container reaching its *own* host's wg0-published IP ingresses on the
  docker bridge, not wg0 — ufw default-deny dropped it, which would have
  burned the consensus ladder's 2 s timeout on every local-first call. Fix:
  bridge subnet pinned (`172.30.90.0/24`) + scoped ufw allow
  (2379/2380/6379 from that subnet only) = **the Step 2 firewall delta,
  zero public exposure**. Honesty per the ListenPort precedent: 8000/8001
  are docker-published and docker bypasses ufw's FORWARD path — their
  non-reachability rests on the **Cloud Firewall alone**.
- **Token single-sourcing (checklist §5):** `cp-env-sync.sh` generated once,
  synced over SSH, never printed; fingerprints equal on both CP nodes
  (`sha256:810de315b84e59e5`); battery driver acquired it over SSH at drive
  time, fingerprint-only in transcripts.
- **Battery — all green, artifact-asserted** (`battery-transcript.txt`; every
  proof's HTTP bodies + `/ops/ha` + `etcdctl` JSON banked): **(a)** primary
  mutation 200 · standby **503 with fence body** · unauthenticated-on-standby
  503 not 401 (**fence-before-auth proven**) · bogus-token-on-primary 403 ·
  worker resolved-env artifact (HA vars present — the silent-unfence hole
  closed); **(b)** witness-kill boring-green: primary unaffected, writes
  continue, etcd-3 rejoins 3/3; **(b′)** the primary's *own local-first*
  member killed → keepalive failed over across the ladder, primary retained,
  writes continued — the endpoint-failover ladder proven on real geography;
  **(c)** quorum loss (both non-local members stopped) → primary **demoted
  within TTL** ("authority is the lease") → mutation 503 with fence body;
  **(d)** one member restarted → re-elect ≤ 8 s, fence term **3 → 4 strictly
  monotonic**, mutation 200; full 3/3 restore with raft indexes converged
  (1007/1007/1007 — catch-up artifact). Recovery-delay attribution: etcd
  refreshes lease TTLs on leader re-election, so up to a full TTL of leader-key
  persistence after quorum restore is lease-refresh behavior, not a campaign
  miss; **(e)** CP failover: primary web stopped → standby took over within
  bound, mutation 200, term **4 → 5**, restarted web stands by — exactly one
  leader; **(f)** node3 actually rebooted → etcd-3 back via restart policy
  (the wg0-bind boot race resolves as designed), 3/3, CPs undisturbed;
  **(g)** extended fence probe from prod: **0 open of 28**
  (22/8000/8001/9109/2379/2380/6379 × 4 nodes — the three new listener
  classes join the enumeration, 6379 included per review).
- **Witness 2 GB reality (checklist §4):** etcd RSS measured **17–37 MiB**
  of 1.87 GiB (docker stats, baseline + storm windows) — two orders below
  the RAM; quota-backend 2 GB is disk (38 GB available). Swap recipe
  (`deploy/SERVER_CHECKLIST.md` §Fix OOM) remains the named contingency —
  not applied, no pressure observed.
- **Battery scope, stated so evidence never implies more than it proved:**
  service-level faults only (containers stopped/started; one witness
  reboot). **Node-level kill drills are deferred to the post-Step-3
  topology / P3 chaos schedule**, where the Step 2 shared-Redis-on-node1
  shape (CP-B reads `redis://10.8.0.1:6379/0` over WG — caches + pub/sub
  only under etcd authority) is restructured per-node.
- **etcd speaks HTTP inside the WG tunnel** — the encryption claim is
  WireGuard's (§(b) belt-and-braces), stated here so the reviewer question
  is preempted. A driver defect during the first battery run (uppercase
  enum → 422 on the mutation payload) was fixed and the battery re-run
  clean end-to-end — fence checks were unaffected either way (the 503/demote
  legs never depended on the payload).
- **Follow-up, P3-BLOCKING (Jesse, 2026-07-30):** etcd snapshot/backup
  cadence is an open gap — `deploy/MULTI_CLOUD.md` has no etcd durability
  doctrine, and a soak without etcd backups means a corrupted quorum loses
  the durable CP blob with no recovery story. Files to the P3 opener as a
  blocker, not a nicety.

**Step 3 as-built (2026-07-30, this PR — closes opener Step 3; artifacts at
node1:`/root/p2-artifacts/step3-stacks/`, 20 files incl. full battery
transcript + driver; laptop archive `p2-artifacts-20260730T082658Z.tar.gz`,
63 entries):**

- **Stacks live:** full TESS stacks (redis + worker + ollama + caddy) joined
  the CP compose as the `stack` profile — still one file
  (`deploy/p2/docker-compose.p2-cp.yml`), brought up by
  `deploy/p2/stack-up.sh` (mirrors deploy.sh's IP-mode steps: Caddyfile
  selection, frontend build with the node's public ws URL baked in, dist
  assertions, pinned model pull). **Found live (phase A):** `set -a; source
  .env.prod` in the bring-up wrapper silently disabled HA on both CPs —
  exported vars beat `--env-file` in compose interpolation, so the node
  env's HA block lost — fixed as the script's read-only `env_get` rule
  (never source `.env.prod` into compose's namespace; comment in the
  script cites this incident).
- **Shared-redis shape retired (phase C):** node2's stack cut to its own
  redis (`redis://10.8.0.2:6379/0` over wg0) — hetzner-2 now survives
  node1's death, the restructure Step 2's battery-scope bullet deferred
  here. The CP pair rode through the cutover undisturbed (fence term 7 both
  sides, roles unchanged); post-cutover WS smoke green on both stacks
  (completed panel 6.2 s node2 / 8.5 s node1).
- **Registry per (c):** `hetzner-1` = `prov_hetzner_local`
  (`http://10.8.0.1:8000`, ws `ws://78.47.69.162`, fsn1); `hetzner-2` =
  `prov_07ddcf4f7064` (`http://10.8.0.2:8001`, ws `ws://5.75.186.164`,
  nbg1). Base URLs are WG IPs, ws URLs public IPs — the
  `OPS_LOCAL_BASE_URL` loopback lesson honored, not re-learned. Prober
  scoring both at 30 s cadence (h-1 at 100 banked snapshots, both healthy
  score 95 pre-battery).
- **Battery — 15 checks PASS, 0 failed** (`battery-transcript.txt` +
  `battery-driver.sh` banked; baseline policy: `active_only`, preferred
  h-1, auto_failover on, failure_threshold 3 / recovery_threshold 2):
  **(a)** baseline: full-body policy PUT 200, force-active h-1 200,
  active=h-1; **(b)** blind-spot proven red-first — ollama stopped on the
  active stack → **no flip**, `/health` 200, and **4 consecutive healthy
  score-95 snapshots inside the stop window** (prober demonstrably alive;
  timestamps banked) — finding bullet below; **(c)** stack-kill flip:
  pub/sub subscriber **fire-drilled before the kill** (positive signal
  proven, per the monitors house rule); node1 stack killed 07:58:31Z
  (etcd-1 left running — witness quorum intact) → CP failover cp-a→cp-b
  (fence term **7 → 8**) and provider flip to h-2 with measured
  kill→`last_failover_at` = **76.0 s** — inside the policy arithmetic's
  60–90 s detection window (failure_threshold 3 × 30 s cadence), and the
  kill took the CP primary with it, so cp-b's lease takeover sits inside
  the same 76 s; **the P4 "local 2.1 s" question's first real-VPS number,
  informally.** Failover event banked from `/ops/events`
  (`prov_hetzner_local → prov_07ddcf4f7064`, `sessions_dropped: 0`); the
  public notice stayed the two-field body (`ws_base_url` flipped to node2,
  stamp advanced); **(d)** failback: node1 stack restarted → preferred
  failback to h-1 in **44.2 s** (inside recovery_threshold 2 × 30 s);
  `provider_changed` captured live for **both** transitions on the
  subscriber (capture banked — `ws_base_url` swaps
  `5.75.186.164` ↔ `78.47.69.162` across the two payloads); **(e)** CP
  handover + registry-refresh guard: cp-b (CP primary since the kill) web
  restarted → cp-a promoted, term **8 → 9**, exactly one leader; the
  provider registry rode both handovers blob-durable (h-2 base_url
  unchanged, h-1 name/URL intact); **(f)** fence sweep from prod grew to
  **0 open of 40** (80/443/11434 join the enumeration — the full stacks
  added caddy and ollama listener classes; all-refused).
- **Finding — prober inference blind spot (disposition = Jesse):**
  same-class failover triggers on `/health` scoring only, and `/health`
  never exercises inference — a provider with dead ollama keeps scoring 95
  and is never failed away from (proven live in (b), not inferred).
  Candidate dispositions: a deep probe that exercises inference on a
  cadence, scoring folded from Step 7's traffic-generator error rate, or
  accepted-as-scoped for this phase. No pin from here; files to the Step 7
  / P3 boundary alongside the etcd-backup blocker above.
- **Registry-refresh guard, structural evidence (added 2026-07-30 with the
  verify-amendment micro-PR):** `OPS_LOCAL_BASE_URL` has exactly one registry
  consumer — the bootstrap seam `app/ops/bootstrap.py:24-28` →
  `ensure_default_hetzner()` (`app/ops/store.py:736`; refresh branch
  :744-760), whose refresh is scoped to `existing[0]` of the HETZNER-type
  filter, i.e. the bootstrap-created `prov_hetzner_local` — plus the setting's
  definition at `app/core/config.py:37`. No code path exists for a web
  restart to rewrite hetzner-2's URLs from env; battery check (e) proved the
  same live (base_url unchanged through the cp-b restart). This is the
  structural "why" behind the refresh guard, recorded so the next reader
  doesn't re-derive it.
- **Blind-spot disposition (DECIDED — Jesse, 2026-07-30; recorded with the
  verify-amendment micro-PR):** accept-as-scoped for the P2 remainder.
  Designed fix: Step 7's traffic-generator error rate folds into provider
  scoring, so failover keys on real traffic outcomes, not `/health` alone —
  lands with Step 7. Fallback: a lightweight inference-exercising deep probe
  on a cadence, if Step 7 slips. **P3 shakedown gate:** one ollama-kill drill
  must prove the flip before P3's measurement clock starts.

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
- **Verify (AMENDED 2026-07-30 — see note):** kill the whole node-1 stack →
  `active_provider_id` flips to `hetzner-2`, `provider_changed` published,
  `/ops/events` + `last_failover_at` artifacts recorded; failover time measured
  (the local 2.1 s question — PROOF_PROGRAM §P4 — gets its first real-VPS number
  here, informally).
  *AMENDED 2026-07-30: the original criterion read "kill ollama-1 (then the
  whole node-1 stack) → flips". The ollama-kill half cannot flip through the
  current `/health` contract — proven live in the Step 3 battery (blind-spot
  artifact: no flip, `/health` 200, four healthy score-95 snapshots with
  inference dead); ratified retroactively with PR #31's merge, formalized here
  per the witness-gate amendment precedent (cold-review F1). Stack-kill remains
  the met criterion; the ollama-kill half's disposition is recorded in the
  Step 3 as-built (§(a)).*

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

- **etcd snapshot/backup cadence — P3-BLOCKING (Jesse, 2026-07-30, Step 2
  review):** no etcd durability doctrine exists; a soak without backups
  risks the durable CP blob on a corrupted quorum with no recovery story.
  First act of the P3 opener alongside the chaos schedule.
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
