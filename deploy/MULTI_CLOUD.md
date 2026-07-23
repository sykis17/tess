# Multi-cloud ops control plane

TESS can register multiple full stacks (Hetzner, AWS, Google Cloud, customer BYO)
and probe `/health` to drive failover, share, and balance policies.

## Architecture (failover v1)

- Each provider runs its **own** Caddy + web + worker + Redis stack (same as
  [`docker-compose.prod.yml`](../docker-compose.prod.yml)).
- One host runs the **ops control plane** (this repo’s `/ops/*` API + background prober).
- **Failover v1 does not migrate in-flight sessions.** On switchover, routing
  assignments are cleared and `active_provider_id` flips. The control plane
  publishes `type: "provider_changed"` on Redis channel `ops:provider_changed`;
  every open WebSocket on this host forwards it so the browser can show a
  reconnect banner (see [Frontend notice](#frontend-notice--ops-ui)). With
  control-plane-only chaos (`simulate-unhealthy`), the old stack may still
  finish work, but the notice is no longer silent-only.
- Seamless mid-session migration is deferred (`GET /ops/seamless-migration`).
  Session 8 Dual/Performance ship without shared Redis — reconnect / resubmit
  remains the honest story until Session 9 (Track C).

```
Client ──► active provider (WS)  [or Dual: sticky assign across two homes]
Control plane ──probe──► Hetzner / AWS / GCP /customer /health
              ──failover──► update active_provider_id
```

## Session 8 locked decisions (Dual XOR Performance)

1. **Dual = two concurrent chat homes** — not primary/secondary roles-only.
   Pool is **current active + next-best** healthy *online* provider. New
   sessions sticky-hash across those two (same stickiness as `share` over a
   2-id pool). Existing sessions stay on their assigned provider until that
   provider fails past `failure_threshold`.
2. **Dual XOR Performance** — enabling one clears the other. They are separate
   operator modes, not stacked.
3. **Track C / shared Redis deferred to Session 9** — `seamless_migration`
   stays `available: false`. Losing a Dual home still drops that home's
   in-flight sessions and emits `provider_changed`.
4. **Performance wake** — default **online-only** (`auto_wake=false`). Optional
   **auto-wake** may enqueue one Celery wake when a *fresh* offline score (≤
   `auto_wake_max_score_age_s`, default 1h) beats the incumbent by the effective
   margin (per-provider `auto_wake_score_margin` or global). Manual Wake/Sleep
   and **Sleep all** restore resting cost; Sleep all is also the stuck-wake reset.

### Dual behavior

- Enable: `POST /ops/routing/dual` (optional `?peer_id=`). Requires ≥2 healthy
  online providers. Sets `policy=dual` and `routing.dual_peer_id`.
- Exit: `DELETE /ops/routing/dual` → `active_only` on current active.
- **Home loss (locked):** clear **only** sessions on the failed home
  (`OpsStore.clear_assignments_for_provider`). Do **not** clear the full Dual
  assignment map. Survivor sticky sessions are **not** re-hashed when the peer
  is backfilled — `{survivor, next_best}` affects **new** assignments only.
  If no tertiary healthy online exists, Dual exits to `active_only` on the
  survivor. `provider_changed` targets clients of the failed home.

### Performance behavior

- Enable: `POST /ops/routing/performance` — clears Dual; may immediately switch
  active to the current best online score (drops all sticky assignments).
  Query `?auto_wake=true` enables chase-wake (default off = online-only).
- While on: each probe cycle may switch if a challenger leads by
  `performance_score_margin` (**default 10**) for
  `performance_streak_required` (**N = default 2**) consecutive probes, or if
  the incumbent is unhealthy past `failure_threshold`. These defaults are the
  unit-test targets; operators may tune via `PUT /ops/routing/policy`.
- Auto-wake (optional): offline AWS/GCP with a **fresh** last score (age ≤
  `auto_wake_max_score_age_s`, default **3600s**) that beats incumbent by the
  effective margin (`CloudProvider.auto_wake_score_margin` or global) → enqueue
  **one** Celery wake. Single inflight lock prevents stampede. **15 min TTL =
  lock only** (not auto-sleep). Wake failure clears inflight + per-provider
  cooldown (`auto_wake_failure_cooldown_s`, default 600s).
- Exit: `DELETE /ops/routing/performance` → freeze current active as
  `active_only` and clear `auto_wake`. Explicitly does **not** snap back to
  `preferred_provider_id` (not a bug).

### Celery worker credentials (easy to forget)

Ops UI Wake / Performance auto-wake run as **Celery tasks on the worker host**,
not inside FastAPI `web`. AWS/GCP credentials and `AWS_STANDBY_*` /
`GCP_STANDBY_*` must live where the **Celery worker** runs. Moving workers
without copying those secrets breaks wake/sleep while `/ops` still looks fine.

### Standby power (cost control)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/ops/providers/{id}/wake` | Enqueue wake AWS/GCP (**admin**) |
| POST | `/ops/providers/{id}/sleep` | Enqueue intentional sleep (**admin**) |
| POST | `/ops/standbys/sleep-all` | Hard reset: clear inflight/cooldowns, Hetzner, sleep all |

**Sleep all** recovers stuck/failed wakes (bad creds, outage). Ops UI badges:
**Wake FAILED** (error) vs **Intentional sleep / resting cost** (ok) — not the
same signal.

### Resting cost posture

After Dual/Performance demos: use **Sleep all standbys** on `/ops-ui/` (or
`POST /ops/standbys/sleep-all`). Leaving Dual/Performance/auto-wake on with
awake boxes burns standby cost.

## `/health` contract

Each Tess stack self-reports host load on **GET** `/health` (psutil). The
control-plane prober uses these fields in the 0–100 health score alongside
HTTP latency and Redis status.

| Field | Type | Notes |
|-------|------|-------|
| `status` | string | `"ok"` when Redis is reachable |
| `redis` | string | `"ok"` or absent on failure (503) |
| `cpu_percent` | float | 0–100; optional if psutil unavailable |
| `mem_percent` | float | 0–100; optional if psutil unavailable |
| `network` | object | Optional `{bytes_sent, bytes_recv}` (display only; not scored) |

**HEAD** `/health` stays empty-body and cheap (UptimeRobot). **Step 4 skipped:**
GCP Cloud Monitoring / CloudWatch / Hetzner Cloud API pulls are **not** used for
scoring. Self-report remains the source of truth so all three providers stay
apples-to-apples (no double penalty). Adapters return metadata only; the prober
owns the single HTTP probe. If Monitoring is revisited later, use
enrichment-only fields under `provider_metrics` — never a second scored probe.

## Provider registry

On startup the API bootstraps:

| Provider | Source |
|----------|--------|
| Hetzner | Always — `OPS_LOCAL_BASE_URL` (default `http://web:8000` in Docker) |
| AWS | When `OPS_AWS_BASE_URL` is set |
| GCP | When `OPS_GCP_BASE_URL` is set |
| Customer | `POST /ops/byo` after health gate |

Env keys: see [`.env.example`](../.env.example).

## Frontend notice + ops UI

On failover / force-active, [`app/ops/failover.py`](../app/ops/failover.py)
`_switch` calls [`publish_provider_changed`](../app/ops/notify.py), which
publishes JSON to Redis `ops:provider_changed`. Each WebSocket in
[`app/api/ws.py`](../app/api/ws.py) subscribes to that channel alongside the
session panel channel and forwards the payload. The chat UI already handles
`provider_changed` ([`useWebSocket.ts`](../frontend/src/hooks/useWebSocket.ts)).

**Take-offline admin page:** open `/ops-ui/` on the control plane (static page
from `frontend/public/ops-ui/index.html`, copied into `frontend/dist/ops-ui/` on
build). Enter a Bearer token from
`OPS_ADMIN_TOKEN` or `OPS_ADMIN_TOKENS` once per browser (`localStorage` key
`tess_ops_admin_token` — never bake secrets into the SPA build). Controls wrap:

| Button | API |
|--------|-----|
| Take offline (active) | `POST /ops/providers/{id}/simulate-unhealthy?enabled=true` |
| Bring online | `POST ...?enabled=false` + `DELETE /ops/chaos/{id}` |
| Force active | `POST /ops/routing/active/{id}` |
| Dual mode | `POST /ops/routing/dual` · `DELETE /ops/routing/dual` |
| Performance | `POST /ops/routing/performance?auto_wake=` · `DELETE …/performance` |
| Wake / Sleep standby | `POST /ops/providers/{id}/wake` · `…/sleep` |
| Sleep all (resting cost) | `POST /ops/standbys/sleep-all` |
| Probe now | `POST /ops/probe` |

**Ops status page (read-only):** open `/ops-status/` (static
`frontend/public/ops-status/index.html` → `dist/ops-status/`). Same Bearer /
`localStorage` key as `/ops-ui/`. Shows active routing, providers, latest scores
from `GET /ops/health-logs`, recent `GET /ops/events`, and a link to the
[UptimeRobot monitor](https://dashboard.uptimerobot.com/monitors/803559917)
(`803559917`). Cross-linked with `/ops-ui/` (Actions ↔ Status). Caddy serves
`/ops-status*` without SPA fallback (same pattern as `/ops-ui*`).

## REST surface (`/ops`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/ops/providers` | List / register providers (**admin**) |
| POST | `/ops/providers/{id}/connect` | Validate adapter + probe (**admin**) |
| POST | `/ops/probe` | Probe all + evaluate failover (**admin**) |
| GET | `/ops/health-logs` | Own probes + provider-native metrics (**admin**) |
| GET | `/ops/events` | Failover, chaos, BYO, policy events (**admin**) |
| GET | `/ops/routing/notice` | Public: `ws_base_url` + `sessions_dropped_last` only |
| GET/PUT | `/ops/routing`, `/ops/routing/policy` | Active provider + policy (**admin**) |
| POST | `/ops/routing/active/{id}` | Force switch — drops sessions (**admin**) |
| POST/DELETE | `/ops/routing/dual` | Dual two-home mode (**admin**; XOR Performance) |
| POST/DELETE | `/ops/routing/performance` | Performance score-chase; `?auto_wake=` (**admin**) |
| POST | `/ops/providers/{id}/wake` | Enqueue AWS/GCP wake (**admin**) |
| POST | `/ops/providers/{id}/sleep` | Enqueue AWS/GCP sleep (**admin**) |
| POST | `/ops/standbys/sleep-all` | Resting cost: Hetzner + sleep standbys (**admin**) |
| POST | `/ops/sessions/{id}/assign` | Assign session (**admin**) |
| POST | `/ops/chaos/{id}?kind=...` | Simulate issues (**admin**) |
| POST | `/ops/providers/{id}/simulate-unhealthy` | Admin unhealthy flag |
| POST/GET | `/ops/compare` | Combination testing reports (**admin**) |
| POST | `/ops/byo` | Customer server connect (**admin**) |
| GET | `/ops/seamless-migration` | Explicit “not available” status (**admin**) |

Set `OPS_ADMIN_TOKENS` (preferred) and/or `OPS_ADMIN_TOKEN` (legacy).
**Gated `/ops` routes fail closed**: if both are unset, they return `503`;
missing/wrong Bearer → `401`/`403`.

| Env | Format | Operator id |
|-----|--------|-------------|
| `OPS_ADMIN_TOKENS` | JSON `{"jesse":"<secret>","alice":"<secret>"}` | keys |
| `OPS_ADMIN_TOKEN` | single shared secret | `legacy` |

Gated surface includes: provider CRUD/connect, probe, force switch, chaos,
simulate-unhealthy, compare, BYO, session assign, and **sensitive GETs**
(`/ops/providers`, `/ops/events`, `/ops/health-logs`, `/ops/routing`,
`/ops/compare`, `/ops/seamless-migration`). Successful mutations record
`operator_id` on `OpsEvent.details`.

**Public (no auth):** `GET /ops/routing/notice` →
`{ "ws_base_url", "sessions_dropped_last" }` for the frontend reconnect banner.
Secrets Manager / Vault for token storage is **later** — tokens live in
`.env.prod` for now.

### Routing policies (`PUT /ops/routing/policy`)

- `active_only` — all new sessions to active provider (failover mode)
- `share` — hash stickiness across healthy providers
- `balance` — prefer higher health scores among healthy providers
- `dual` — prefer `POST /ops/routing/dual` (requires `dual_peer_id` set)
- `performance` — prefer `POST /ops/routing/performance` (score chase)
## Live failover verification (not covered by unit tests)

Unit tests prove internal consistency. Against a **real second provider** (even a
cheap throwaway AWS Tess stack), run:

```bash
export OPS_SMOKE_BASE_URL=https://YOUR_CONTROL_PLANE
export OPS_ADMIN_TOKEN=...
export OPS_SMOKE_PRIMARY=prov_hetzner_local
export OPS_SMOKE_STANDBY=prov_aws
python scripts/ops_failover_live_smoke.py
```

That script: force primary active → `simulate-unhealthy` → probe until flap
threshold trips and standby becomes active → clear chaos → force recover.
Watch flap timing and any DNS/proxy lag yourself while it runs.

## Stand up AWS (manual first slice)

See **[AWS standby (stopped-by-default)](#aws-standby-stopped-by-default)** below for the live
instance (`18.227.172.81`) and full runbook. Summary for any new EC2/GCP host:

1. Launch a VM with **≥ 20 GB root volume** if using Ollama, or **≥ 10 GB** with
   `DEFAULT_LLM_PROVIDER=gemini` (deploy skips the Ollama container — see
   [`docker-compose.prod.yml`](../docker-compose.prod.yml) `ollama` profile).
2. Install **Docker** and **Node.js LTS** — `deploy.sh` runs `npm ci` / `npm run build` on the
   host before containerizing the frontend.
3. Clone Tess, copy `.env.prod.example` → `.env.prod`, set `DOMAIN` / `VITE_WS_BASE_URL`
   to the public hostname or Elastic IP; prefer `DEFAULT_LLM_PROVIDER=gemini` on cloud standby.
4. Run `./deploy/deploy.sh`.
5. Confirm `http://<aws-host>/health` returns `{"status":"ok","redis":"ok"}` (HTTP for IP-only).
6. On the control-plane host set `OPS_AWS_BASE_URL`, `OPS_AWS_REGION`, redeploy, then
   `POST /ops/providers/prov_aws/connect` and `POST /ops/probe`.

Credentials stay as **refs** (env/secret names), not raw keys in the registry.

## AWS standby (stopped-by-default)

Hetzner stays always-on; AWS runs as a **stopped-by-default** standby to avoid idle
compute cost. Wake it only for controlled failover smoke tests.

### Instance metadata

| Field | Value |
|-------|-------|
| Instance ID | `i-0360ab28632a3c4a0` |
| Elastic IP | `18.227.172.81` (associated 2026-07-20 — stable across stop/start; see [cost note](#elastic-ip--public-ipv4-cost)) |
| Region | `us-east-2` (Ohio) |
| Type | `t3.micro` |
| AMI | Ubuntu 26.04 (Docker pre-installed) |
| Root volume | **20 GB** (resized from default 8 GB — see [disk note](#disk-and-ollama)) |
| Name tag | `tess-aws-standby` |
| Key pair | `tess-aws-key` (local `.pem` — do not commit; Hetzner uses separate `hetzner_tess`) |
| Security group | `launch-wizard-1` — SSH restricted to `186.99.129.21/32` (see [If you're locked out](#if-youre-locked-out)) |

### If you're locked out

SSH to the standby fails silently (hang / timeout) when your public IP is no longer
`186.99.129.21/32` — the launch-time rule on SG `launch-wizard-1`. Use path B for
laptop SSH, or path A for console access while the instance is **running**.

**Path B — update security group (fastest for laptop SSH)**

1. EC2 → Security Groups → `launch-wizard-1`
2. Edit inbound rules → SSH (port 22) → Source **My IP** (or your new CIDR)
3. Save

Manual only — no IP-drift automation.

**Path A — EC2 Instance Connect (console)**

1. AWS Console → EC2 → select `i-0360ab28632a3c4a0` (must be **running**)
2. **Connect** → **EC2 Instance Connect** → Connect

Instance Connect does **not** bypass the security group. Console Connect still
requires inbound SSH from the EC2 Instance Connect service. For `us-east-2`, add
a one-time inbound SSH rule with source prefix list:

`com.amazonaws.us-east-2.ec2-instance-connect`

Keep the "My IP" rule for laptop SSH alongside that prefix-list rule. Prefer the
managed prefix list over opening `0.0.0.0/0`. If Instance Connect is not set up,
fallbacks are **EC2 Serial Console** (if enabled for the account) or a temporary
SG open — still prefer the prefix list.

### Elastic IP / public IPv4 cost

Since **2024-02-01**, AWS bills **all** public IPv4 addresses — including an EIP
associated with a **running or stopped** instance, and idle unassociated EIPs.
See [Elastic IP addresses](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html)
and the Public IPv4 Address tab on [Amazon VPC pricing](https://aws.amazon.com/vpc/pricing/).
**Do not hardcode a $/hour here** — rates change; check that page when reviewing cost.

EIP `18.227.172.81` stays associated while the instance is stopped most of the time,
so expect a **small ongoing** public IPv4 charge even with no compute.

| Choice | Pros | Cons |
|--------|------|------|
| **Keep EIP** (current) | Stable `OPS_AWS_BASE_URL` / `DOMAIN` | Ongoing public IPv4 charge |
| **Release EIP** | Avoid idle IPv4 charge | Public IP changes on wake; patch `prov_aws` + env (wake already supports IP drift via `PATCH /ops/providers/prov_aws` in [`scripts/aws_standby.py`](../scripts/aws_standby.py)) |

**Verify on the bill (laptop, `tess-ops-laptop` creds):**

```powershell
# Confirm association while stopped
aws ec2 describe-addresses --region us-east-2 `
  --filters "Name=public-ip,Values=18.227.172.81" `
  --query "Addresses[].{PublicIp:PublicIp,InstanceId:InstanceId,AssociationId:AssociationId}"

# Cost Explorer — look for PublicIPv4 / ElasticIP usage types
aws ce get-cost-and-usage `
  --time-period Start=2026-07-01,End=2026-07-22 `
  --granularity MONTHLY `
  --metrics UnblendedCost `
  --group-by Type=DIMENSION,Key=USAGE_TYPE `
  --query "ResultsByTime[].Groups[?contains(Keys[0], 'PublicIPv4') || contains(Keys[0], 'ElasticIP')]"
```

`tess-ops-laptop` currently lacks `ec2:DescribeAddresses` and `ce:GetCostAndUsage`
(AccessDenied 2026-07-21). Until those are granted, use console Cost Explorer / Public
IP insights, or confirm association via `ec2:DescribeInstances` (allowed): a **stopped**
instance that still shows `PublicIpAddress=18.227.172.81` means the EIP remains attached.

Console fallback: Billing → **Cost Explorer** (filter EC2 - Other and/or VPC; group by
Usage type — look for `PublicIPv4:InUseAddress`, `PublicIPv4:IdleAddress`, or legacy
`ElasticIP:*`). Optional: VPC → **Public IP insights** for inventory + estimated cost.

**Decision (2026-07-21):** **Keep EIP** for stable `OPS_AWS_BASE_URL`. Docs confirm a
small ongoing public IPv4 charge while allocated (running or stopped); exact $/hr not
recorded here — re-check VPC pricing + Cost Explorer after IAM/`ce:GetCostAndUsage`
is granted (or via console).

### Host prerequisites (discovered 2026-07-20)

**Node.js** — not on the stock Ubuntu 26.04 AMI. Required because `deploy.sh` builds the
frontend on-host (`npm ci` / `npm run build`) before `docker compose up`:

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version && npm --version
```

**Docker** — was already present on this AMI. If missing: `curl -fsSL https://get.docker.com | sh`,
then `sudo usermod -aG docker ubuntu` and re-login.

### Disk and Ollama

The default **8 GB** root volume (~6.9 GB usable) ran out of space mid-deploy while pulling
`ollama/ollama:latest` (~3 GB) alongside app images. Fix applied: EBS resized **8 → 20 GB**,
then on-host:

```bash
sudo growpart /dev/nvme0n1 1
sudo resize2fs /dev/nvme0n1p1
```

**Recommendations for future hosts:**

| Deploy mode | Min root volume | Notes |
|-------------|-----------------|-------|
| `DEFAULT_LLM_PROVIDER=gemini` | **10 GB** | `deploy.sh` skips the Ollama compose profile — no `ollama/ollama` image pull |
| `DEFAULT_LLM_PROVIDER=ollama` | **20 GB** | Full stack including Ollama image + model weights |

When `DEFAULT_LLM_PROVIDER` is not `ollama`, [`deploy/deploy.sh`](deploy.sh) omits
`--profile ollama` so only **caddy, redis, web, worker** start (four containers).

### Task 0 — one-time setup (before automation)

| Step | Status | Notes |
|------|--------|-------|
| Attach Elastic IP | **Done** | `18.227.172.81` → `i-0360ab28632a3c4a0` |
| Install Node.js on AWS host | **Done** | See [host prerequisites](#host-prerequisites-discovered-2026-07-20) |
| Resize root volume (if 8 GB) | **Done** | 20 GB — only needed because first deploy pulled Ollama |
| Deploy Tess on AWS | **Done** | `./deploy/deploy.sh` clean; `/health` OK |
| Verify frontend in browser | Optional | Open `http://18.227.172.81` when instance is awake |
| Hetzner `OPS_AWS_BASE_URL` + redeploy | **Done** | `http://18.227.172.81`, region `us-east-2`; web recreated |
| Control plane connect + probe | **Done** | `prov_aws` registered; connect `http_ok=True` |
| Stop instance | **Done** | Stopped-by-default; `cycle` always stops in `finally` |
| First `cycle` run + last verified | **Done** | 2026-07-21 — see below |

**Deploy env on AWS** (`.env.prod` on the box — not committed):

```env
DOMAIN=18.227.172.81
VITE_WS_BASE_URL=ws://18.227.172.81
DEFAULT_LLM_PROVIDER=gemini
GEMINI_API_KEY=<set on host>
```

Verified: `curl http://18.227.172.81/health` → `{"status":"ok","redis":"ok"}`.

**Hetzner control plane** (`.env.prod` on `5.78.186.223`):

```env
OPS_AWS_BASE_URL=http://18.227.172.81
OPS_AWS_REGION=us-east-2
OPS_ADMIN_TOKEN=<secret>
```

Use `OPS_SMOKE_BASE_URL=http://5.78.186.223` on the laptop (IP-only deploy — no TLS on :443).

### Deploy commands (reference)

```bash
ssh -i ~/path/to/tess-aws-key.pem ubuntu@18.227.172.81
git clone <repo> && cd tess-engine
cp .env.prod.example .env.prod
# edit .env.prod — DOMAIN, VITE_WS_BASE_URL, DEFAULT_LLM_PROVIDER=gemini, GEMINI_API_KEY
./deploy/deploy.sh
curl http://18.227.172.81/health
```

### Wake / sleep / cycle

Run from your **local machine** with AWS credentials (`aws configure` or env vars).

Required IAM: `ec2:StartInstances`, `ec2:StopInstances`, `ec2:DescribeInstances`,
`budgets:ViewBudget`, `sts:GetCallerIdentity`.

```bash
export OPS_AWS_BASE_URL=http://18.227.172.81
export OPS_SMOKE_BASE_URL=https://5.78.186.223
export OPS_ADMIN_TOKEN=...
export AWS_BUDGET_NAME=tess-monthly
export AWS_BUDGET_ALERT_THRESHOLD=0.80

python scripts/aws_standby.py wake    # start + wait for /health
python scripts/aws_standby.py cycle   # wake → smoke → sleep (one command)
python scripts/aws_standby.py sleep   # stop (idempotent)
```

`cycle` runs [`scripts/ops_failover_live_smoke.py`](../scripts/ops_failover_live_smoke.py)
against Hetzner (primary) + AWS (standby), then **always stops AWS** in a `finally`
block — even when the smoke test fails.

If Elastic IP is not attached (or drifts), the wake step patches `prov_aws` on the
control plane via `PATCH /ops/providers/prov_aws` before probing.

Env reference: [`.env.example`](../.env.example) (`AWS_STANDBY_*`, `OPS_SMOKE_BASE_URL`).

### External uptime

Something **outside Hetzner** must watch the control plane so a total box death
is visible even when the in-process prober cannot run.

| Field | Value |
|-------|-------|
| Product | [UptimeRobot](https://uptimerobot.com/) (free HTTP(S) monitor) |
| Dashboard | https://dashboard.uptimerobot.com/ |
| Monitor | [5.78.186.223/health](https://dashboard.uptimerobot.com/monitors/803559917) (ID `803559917`) |
| Monitor type | HTTP(S) |
| Monitor URL | `http://5.78.186.223/health` |
| Interval | 5 minutes |
| Expected | HTTP **200** on **GET or HEAD** (UptimeRobot often uses HEAD; Tess accepts both) |
| Expected body (GET) | `{"status":"ok","redis":"ok"}` |
| Alert | `jesse.malma@gmail.com` |

**Create (done Session 3):** monitor live; use **Test Notification** on the
monitor page to confirm the alert channel. If the dashboard briefly shows
**Down** while `/health` returns 200 from elsewhere, open **Edit** and ensure
the URL is `http://` (not `https://`) and any keyword is exactly `"status":"ok"`
(or disable keyword and rely on HTTP 200).

No in-repo watcher this session. Optional later: GitHub Actions cron or AWS
Lambda from the standby account if the free ping product is unacceptable.

**Endpoint check (2026-07-21):** `GET http://5.78.186.223/health` →
`200 {"status":"ok","redis":"ok"}` (re-verified Session 3).

**Status (2026-07-21):** **live** — monitor `5.78.186.223/health` ID
`803559917`; alert `jesse.malma@gmail.com`. Early Down incident was **405 on
HEAD** (UptimeRobot probes HEAD; `/health` was GET-only) — fixed by accepting
HEAD+GET (deploy required for NA checks to go green).

### Drift check

Catch a forgotten `wake` / `cycle` that died before `finally`, leaving
`i-0360ab28632a3c4a0` running and burning compute. **Alert only** — the checker
never calls stop/start.

| Field | Value |
|-------|-------|
| Command | `python scripts/aws_standby.py drift-check` |
| AWS call | `DescribeInstances` only (Describe-only IAM is enough) |
| Exit 0 | State is `stopped` or `stopping` |
| Exit non-zero | State is `running` or `pending` (drift) |
| Override | `AWS_STANDBY_ALLOW_RUNNING=1` → exit 0 even when running (intentional wake) |
| Schedule | Once daily on the **operator laptop** (Task Scheduler / cron). Talks to the **AWS API**, not the Hetzner box. |
| Alerts | Non-zero exit → cron mail, Task Scheduler failure email, or pipe stderr to the same Telegram/email channel used for ops |

**Windows Task Scheduler (example):** daily trigger → action
`python C:\Users\jesse\tess-engine\scripts\aws_standby.py drift-check` with
working directory the repo root and AWS credentials available (same profile as
wake/sleep). On failure (exit ≠ 0), notify via your usual ops channel.

**Linux/macOS cron (example):**

```cron
0 9 * * * cd /path/to/tess-engine && python scripts/aws_standby.py drift-check
```

Dry-run when standby should be idle: expect `stopped` → exit 0. Do not auto-stop
from this job in v1.

### Last verified

**2026-07-21 (Session 6 ops status page)** — Read-only `/ops-status/` static
MPA (shared Bearer with `/ops-ui/`): routing, providers, latest health scores,
recent events, UptimeRobot link. Caddy `handle /ops-status*` + deploy build
check. Secrets Manager and seamless migration still deferred.

**2026-07-21 (Session 5 provider_changed WS + take-offline UI)** — Failover /
force-active publish `ProviderChangedMessage` on Redis `ops:provider_changed`;
WebSocket clients subscribe and forward to the browser banner. Minimal admin
page at `/ops-ui/` (Bearer via `localStorage`). Unit tests in
`tests/test_ops_provider_notify.py`.

**2026-07-21 (Session 4 admin tokens)** — `OPS_ADMIN_TOKENS` JSON + legacy
`OPS_ADMIN_TOKEN`; sensitive GETs + session assign gated; public
`GET /ops/routing/notice`; frontend reconnect fetch updated. Unit tests in
`tests/test_ops_admin_auth.py`.

**2026-07-21 (Session 3 drift-check dry-run)** — `python scripts/aws_standby.py
drift-check` against `i-0360ab28632a3c4a0` → `state=stopped`, exit 0. Unit tests
in `tests/test_aws_standby.py` cover stopped/stopping → 0 and running/pending → 1
(plus `AWS_STANDBY_ALLOW_RUNNING`). Alert-only; no auto-stop.

**2026-07-21 (mid-session browser failover)** — AWS already running / woken;
`prov_aws` connected; browser opened `http://5.78.186.223` (WS **Connected**);
Research + L4 long prompt sent; `simulate-unhealthy` on `prov_hetzner_local` →
failover to `prov_aws` after 3 probes (`sessions_dropped=3`). **Browser UX:**
status stayed **Connected**; **no** dismissible `provider_changed` banner; panel
kept updating (**Wide Receiver** still processing on Hetzner ~1m+ after routing
flipped). Matches the known gap at the time: control-plane failover did not close the
Hetzner WS or push `provider_changed`. **Superseded by Session 5** (Redis
`ops:provider_changed` fan-out + `/ops-ui/`). Cleared simulate,
forced Hetzner active, AWS stopped.

**2026-07-21 (chaos kinds live)** — AWS woken; each kind injected on
`prov_hetzner_local` via `POST /ops/chaos/...`; manual `POST /ops/probe` until
failover or 12 probes; chaos cleared; forced back to Hetzner; AWS stopped after.

| Kind | Failover? | Probe cycles | Notes |
|------|-----------|--------------|-------|
| `high_latency` | **No** (score-only by design) | 12 / no trip | Mild pressure: default `latency_ms=2500` → measured ~2512 ms; score 45 ≥ 40; `healthy=True`; failures stayed 0. Prober caps injected sleep at 3 s, so default chaos cannot cross `OPS_LATENCY_THRESHOLD_MS=5000`. Failover is reserved for hard failures / latency **above** the 5 s SLO. |
| `health_5xx` | Yes → `prov_aws` | 3 | Same flap pattern as `mark_unhealthy` |
| `worker_down` | Yes → `prov_aws` | 3 | Forces `http_ok=False` in prober (does not stop real worker) |
| `redis_partition` | Yes → `prov_aws` | 2 | Prober forces `redis_ok=False` (app `/health` still ok); flipped in 2 operator probes — background prober likely added a failure between them (failures jumped 1→3) |
| `cpu_burn` | Yes → `prov_aws` | 3 | Prober sets `cpu_percent=99` → score 35 (below min 40) → unhealthy |

**Decision (2026-07-21, option 1):** `high_latency` is **score-only** mild
pressure — it does not need to trip failover at default settings. Keep
`OPS_LATENCY_THRESHOLD_MS=5000` and the prober 3 s sleep cap; do not raise
chaos `latency_ms` solely to make the kind flap.

**2026-07-21 (EIP / SSH docs)** — Instance `i-0360ab28632a3c4a0` **stopped** but still
shows `PublicIpAddress=18.227.172.81` (`DescribeInstances`) → EIP remains associated
while stopped. Cost Explorer CLI blocked (`ce:GetCostAndUsage` AccessDenied on
`tess-ops-laptop`); `DescribeAddresses` also denied. Per AWS public IPv4 billing
(since 2024-02-01), expect a small ongoing charge — **keep EIP** (stable URL). See
[Elastic IP / public IPv4 cost](#elastic-ip--public-ipv4-cost) and
[If you're locked out](#if-youre-locked-out).

**2026-07-21** — `python scripts/aws_standby.py cycle` (Windows laptop → Hetzner control plane + AWS standby)

```
AWS budget 'tess-monthly-ops': spent $0.00 / $20.00 (0.0%, threshold 80%)
Starting instance i-0360ab28632a3c4a0 in us-east-2...
AWS instance running at 18.227.172.81 (base_url=http://18.227.172.81)
AWS stack healthy at http://18.227.172.81/health
connect prov_aws: connected=True http_ok=True
probe completed after standby wake
Running ops_failover_live_smoke.py...
Smoke against http://5.78.186.223 primary=prov_hetzner_local standby=prov_aws
initial active=prov_hetzner_local
simulate-unhealthy enabled on prov_hetzner_local
  probe#1 active=prov_hetzner_local failover=False failures={'prov_hetzner_local': 1, 'prov_aws': 0}
  probe#2 active=prov_hetzner_local failover=False failures={'prov_hetzner_local': 2, 'prov_aws': 0}
  probe#3 active=prov_aws failover=True failures={'prov_hetzner_local': 3, 'prov_aws': 0}
OK: failed over to prov_aws after 3 probes
cleared simulate-unhealthy on prov_hetzner_local
forced active back to prov_hetzner_local
PASS: live simulate → probe → failover → recover sequence completed
Stopping instance i-0360ab28632a3c4a0...
# Exit: smoke PASS; AWS stopped in finally
```

## Three-way chaos failover (2026-07-22, Session 7)

Host metrics self-report already live on all three stacks. Re-validated
`simulate-unhealthy` → consecutive failure streak → automatic switch for
**both** standbys (not Force active).

| Run | Standby | Failover? | Probe cycles | Notes |
|-----|---------|-----------|--------------|-------|
| A | `prov_aws` | Yes | 3 | `aws_standby.py cycle` PASS. Preflight prints laptop public IP for SG `launch-wizard-1`. |
| B | `prov_gcp` | Yes | 3 | `gcp_standby.py cycle` with `OPS_SMOKE_STANDBY=prov_gcp` PASS. ADC preflight confirms `GOOGLE_APPLICATION_CREDENTIALS`. Hetzner failures jumped 2→4 on the switch probe (background prober race) — still selected `prov_gcp`. |

### t3.micro under failover load

AWS `t3.micro` previously hung during vite/Docker build (2026-07-22) until a
1GB swapfile was added. During Session 7 Run A smoke (AWS became **active**
briefly under probe load):

- No OOM / SSH hang observed from the operator laptop
- Healthy AWS snapshots showed `mem_percent` ~61%, score ~87
- **Verdict:** adequate for control-plane failover smoke; still undersized for
  sustained LangGraph/LLM traffic if AWS must remain the active provider
- **Sizing follow-up: parked.** Do **not** resize now. Revisit only if AWS must
  stay active under real LangGraph/LLM load (OOM risk).

Resting state after both runs: Hetzner active, AWS stopped, GCP stopped.

Standby wake preflight (same PR): AWS prints public IP + SG reminder; GCP fails
fast / warns on missing `GOOGLE_APPLICATION_CREDENTIALS`.

## Stand up Google Cloud

1. Create a Compute Engine VM (or GCE MIG) with Docker.
2. Same Tess prod compose as Hetzner/AWS; open 80/443; point DNS or use IP mode.
3. Set on control plane:

```env
OPS_GCP_BASE_URL=http://34.46.222.191
OPS_GCP_REGION=us-central1
OPS_GCP_CREDENTIALS_REF=GCP_SERVICE_ACCOUNT_JSON
```

4. Connect + probe as above (`prov_gcp`).

## GCP standby (stopped-by-default)

Hetzner stays always-on; GCP can run as a **stopped-by-default** standby (same
pattern as AWS). Wake it for controlled failover smoke; stop when idle.

### Instance metadata

| Field | Value |
|-------|-------|
| Instance name | `tess-gcp-primary` |
| Static external IP | `34.46.222.191` (reserved — stable across stop/start) |
| Project | `tess-503119` |
| Zone | `us-central1-a` |
| Region | `us-central1` |
| SSH | `ssh -i ~/.ssh/tess_gcp_ops tessops@34.46.222.191` (key not committed) |
| Ops provider id | `prov_gcp` |
| Credentials ref | `GCP_SERVICE_ACCOUNT_JSON` (env name on control plane; key lives on operator laptop / secret store — never commit) |

### serviceAccountUser / stop-start IAM

Wake/sleep uses the **ops** service account (or ADC) against the Compute Engine
API (`instances.start` / `instances.stop`). The VM does **not** need an attached
service account for Tess to run.

| Situation | What you need |
|-----------|----------------|
| VM has **no** service account | Ops SA needs `compute.instances.start` / `stop` (e.g. `roles/compute.instanceAdmin.v1` scoped to the instance). **No** `serviceAccountUser` required. |
| VM runs **as** a Compute SA | Ops SA **also** needs `roles/iam.serviceAccountUser` on that VM SA, or start returns 403. |
| Workaround if you cannot grant `serviceAccountUser` | Detach the VM service account (Console → VM → Edit → Identity → None), then stop/start with Compute permissions only. |

`scripts/gcp_standby.py` surfaces a clear error hint when a 403 mentions
`serviceAccountUser`.

### Operator commands (laptop)

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "$env:USERPROFILE\Downloads\<sa-key>.json"
$env:OPS_GCP_BASE_URL = "http://34.46.222.191"
$env:OPS_SMOKE_BASE_URL = "http://5.78.186.223"
$env:OPS_ADMIN_TOKEN = "<from Hetzner .env.prod>"
$env:OPS_SMOKE_PRIMARY = "prov_hetzner_local"
$env:OPS_SMOKE_STANDBY = "prov_gcp"

python scripts/gcp_standby.py wake         # start + wait for /health
python scripts/gcp_standby.py drift-check  # expect TERMINATED when idle
python scripts/gcp_standby.py cycle        # wake → smoke → sleep
python scripts/gcp_standby.py sleep        # stop (idempotent)
```

Or run smoke alone while the GCP stack is already awake:

```powershell
$env:OPS_SMOKE_STANDBY = "prov_gcp"
python scripts/ops_failover_live_smoke.py
```

Host metrics (CPU / memory) are self-reported in `/health` via psutil; the
prober scores them on the same 30s cadence. `GcpAdapter` is metadata-only
(no duplicate HTTP probe). GCP Cloud Monitoring API is **skipped** (Step 4);
self-report stays the scoring source of truth.

## Stakeholder three-way chaos demo (Step 5)

Ops walkthrough for stakeholders — not new engine features. Session 7 already
proved the mechanical path for both standbys; this section is the polished
script. Prefer waking **one** standby (cost/time pick). Multi-standby race is
optional/later.

### One-shot (laptop)

```powershell
$env:OPS_SMOKE_BASE_URL = "http://5.78.186.223"
$env:OPS_ADMIN_TOKEN = "<from Hetzner .env.prod>"
# AWS path (needs AWS credentials + SG allows laptop IP):
python scripts/ops_three_way_demo.py aws
# Or GCP path (needs GOOGLE_APPLICATION_CREDENTIALS):
python scripts/ops_three_way_demo.py gcp
# Guided: pause between wake / smoke / sleep so you can show the UI
python scripts/ops_three_way_demo.py aws --guided
# Print steps only (no cloud calls):
python scripts/ops_three_way_demo.py --print-runbook
```

### Manual checklist

1. **Wake** one standby: `python scripts/aws_standby.py wake` or
   `python scripts/gcp_standby.py wake` (preflight warns on SG IP /
   missing ADC).
2. **Show proof** — open `http://5.78.186.223/ops-status/` (and optionally
   `/ops-ui/`) so host metrics + providers are visible.
3. **Induce failover** — take Hetzner offline via `/ops-ui/` or
   `simulate-unhealthy`; watch consecutive failures 1→2→3; active flips to the
   woken standby. Automated: `OPS_SMOKE_STANDBY=prov_aws|prov_gcp` +
   `python scripts/ops_failover_live_smoke.py`.
4. **Recover** — clear chaos → force Hetzner active →
   `python scripts/aws_standby.py sleep` or `python scripts/gcp_standby.py sleep`.

Expected smoke excerpt (threshold 3):

```text
  probe#1 active=prov_hetzner_local failover=False failures={...: 1, ...}
  probe#2 active=prov_hetzner_local failover=False failures={...: 2, ...}
  probe#3 active=prov_aws|prov_gcp failover=True failures={...: 3, ...}
PASS: live simulate → probe → failover → recover sequence completed
```

Resting state after the demo: Hetzner active; AWS stopped; GCP stopped.

## Simulate failover (manual curl)

```bash
# Mark Hetzner unhealthy (requires OPS_ADMIN_TOKEN)
curl -X POST "$HOST/ops/providers/prov_hetzner_local/simulate-unhealthy?enabled=true" \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"

# Probe until failure_threshold trips and standby becomes active
curl -X POST "$HOST/ops/probe" -H "Authorization: Bearer $OPS_ADMIN_TOKEN"

# Clear chaos
curl -X DELETE "$HOST/ops/chaos/prov_hetzner_local" \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"
```

Chaos kinds: `none`, `high_latency` (score-only mild pressure at default
`latency_ms=2500` — does not cross the 5 s latency SLO), `health_5xx`,
`mark_unhealthy`, `worker_down`, `redis_partition`, `cpu_burn`.

## Customer BYO

```bash
curl -X POST "$HOST/ops/byo" \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme edge","base_url":"https://tess.acme.example","org_id":"acme"}'
```

Health gate must pass. Org sessions can be assigned via
`POST /ops/sessions/{session_id}/assign?org_id=acme`.

## Caddy

Production Caddyfiles proxy `/ops/*` to the web service (in addition to `/ws/*` and `/health`).

## Celery

Optional scheduled probe: task name `ops_probe_providers` in `app/worker.py`
(call from Celery Beat or cron if you disable the FastAPI lifespan loop via
`OPS_PROBE_ENABLED=false`).

Standby power tasks: `ops_standby_wake`, `ops_standby_sleep`. These invoke
`scripts/aws_standby.py` / `scripts/gcp_standby.py` **on the worker host**.
Cloud credentials therefore belong on the Celery worker environment — not only
on a laptop that talks to `/ops`, and not only on the FastAPI `web` container.

## Changelog notes

**2026-07-23 (Session 8 Dual XOR Performance)** — `RoutingPolicy.DUAL` /
`PERFORMANCE`; `POST/DELETE /ops/routing/dual` and `/ops/routing/performance`
(mutually exclusive). Dual sticky-hashes new sessions across active + next-best
online homes; home loss drops that home's assignments and backfills peer or
degrades to `active_only`. Performance score-chases among online healthy
providers with margin/streak anti-flap. Optional `auto_wake` enqueues Celery
wake via `scripts/*_standby.py` when a slept standby's last score would beat
the incumbent; default remains online-only. Admin wake/sleep per standby plus
`POST /ops/standbys/sleep-all` for resting cost posture. Shared Redis /
seamless migration remains deferred (`available: false`).
