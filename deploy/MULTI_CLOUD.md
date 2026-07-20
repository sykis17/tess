# Multi-cloud ops control plane

TESS can register multiple full stacks (Hetzner, AWS, Google Cloud, customer BYO)
and probe `/health` to drive failover, share, and balance policies.

## Architecture (failover v1)

- Each provider runs its **own** Caddy + web + worker + Redis stack (same as
  [`docker-compose.prod.yml`](../docker-compose.prod.yml)).
- One host runs the **ops control plane** (this repo’s `/ops/*` API + background prober).
- **Failover v1 does not migrate in-flight sessions.** On switchover, sessions are
  dropped; clients show a `provider_changed` / reconnect notice and may resubmit.
- Seamless mid-session migration is deferred (`GET /ops/seamless-migration`).

```
Client ──► active provider (WS)
Control plane ──probe──► Hetzner / AWS / GCP /customer /health
              ──failover──► update active_provider_id
```

## Provider registry

On startup the API bootstraps:

| Provider | Source |
|----------|--------|
| Hetzner | Always — `OPS_LOCAL_BASE_URL` (default `http://web:8000` in Docker) |
| AWS | When `OPS_AWS_BASE_URL` is set |
| GCP | When `OPS_GCP_BASE_URL` is set |
| Customer | `POST /ops/byo` after health gate |

Env keys: see [`.env.example`](../.env.example).

## REST surface (`/ops`)

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/ops/providers` | List / register providers |
| POST | `/ops/providers/{id}/connect` | Validate adapter + probe |
| POST | `/ops/probe` | Probe all + evaluate failover |
| GET | `/ops/health-logs` | Own probes + provider-native metrics |
| GET | `/ops/events` | Failover, chaos, BYO, policy events |
| GET/PUT | `/ops/routing`, `/ops/routing/policy` | Active provider + share/balance policy |
| POST | `/ops/routing/active/{id}` | Force switch (drops sessions) |
| POST | `/ops/sessions/{id}/assign` | Assign session (share/balance) |
| POST | `/ops/chaos/{id}?kind=...` | Simulate issues |
| POST | `/ops/providers/{id}/simulate-unhealthy` | Admin unhealthy flag |
| POST/GET | `/ops/compare` | Combination testing reports |
| POST | `/ops/byo` | Customer server connect |
| GET | `/ops/seamless-migration` | Explicit “not available” status |

Set `OPS_ADMIN_TOKEN` to a strong secret. **Mutating `/ops` routes fail closed**:
if the token is unset, they return `503`; missing/wrong Bearer → `401`/`403`.
This includes `POST /ops/routing/active/{id}` (force switch — drops in-flight sessions),
chaos injection, simulate-unhealthy, probe, provider CRUD, compare, and BYO.

### Routing policies (`PUT /ops/routing/policy`)

- `active_only` — all new sessions to active provider (failover mode)
- `share` — hash stickiness across healthy providers
- `balance` — prefer higher health scores among healthy providers

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
| Elastic IP | `18.227.172.81` (associated 2026-07-20 — stable across stop/start) |
| Region | `us-east-2` (Ohio) |
| Type | `t3.micro` |
| AMI | Ubuntu 26.04 (Docker pre-installed) |
| Root volume | **20 GB** (resized from default 8 GB — see [disk note](#disk-and-ollama)) |
| Name tag | `tess-aws-standby` |
| Key pair | `tess-aws-key` (local `.pem` — do not commit) |
| Security group | `launch-wizard-1` — SSH restricted to `186.99.129.21/32` (update if dev IP changes) |

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
| Verify frontend in browser | **Pending** | Open `http://18.227.172.81` — only `/health` checked so far |
| Hetzner `OPS_AWS_BASE_URL` + redeploy | **Pending** | See env block below |
| Control plane connect + probe | **Pending** | `POST .../prov_aws/connect` then `POST /ops/probe` |
| Stop instance | **Pending** | Still running since launch — use `python scripts/aws_standby.py sleep` |
| First `cycle` run + last verified | **Pending** | After instance is stopped-by-default |

**Deploy env on AWS** (`.env.prod` on the box — not committed):

```env
DOMAIN=18.227.172.81
VITE_WS_BASE_URL=ws://18.227.172.81
DEFAULT_LLM_PROVIDER=gemini
GEMINI_API_KEY=<set on host>
```

Verified: `curl http://18.227.172.81/health` → `{"status":"ok","redis":"ok"}`.

**Hetzner control plane** (`.env.prod` on `5.78.186.223` — pending):

```env
OPS_AWS_BASE_URL=http://18.227.172.81
OPS_AWS_REGION=us-east-2
OPS_ADMIN_TOKEN=<secret>
```

Redeploy Hetzner (`./deploy/deploy.sh`) so bootstrap registers `prov_aws`, then:

```bash
curl -X POST "https://5.78.186.223/ops/providers/prov_aws/connect" \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"
curl -X POST "https://5.78.186.223/ops/probe" \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"
```

**Stop the instance** (do this promptly — compute has been billing since launch):

```bash
python scripts/aws_standby.py sleep
```

Note: an EIP on a stopped instance may incur a small hourly charge.

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

### Last verified

_AWS deploy verified 2026-07-20 (`/health` OK). First `cycle` run pending — complete
remaining task 0 steps (Hetzner env, stop instance), then paste output here._

```
# AWS deploy (manual, 2026-07-20):
#   EIP 18.227.172.81 associated
#   deploy.sh completed; curl http://18.227.172.81/health → {"status":"ok","redis":"ok"}
#   Containers at deploy time: caddy, ollama, redis, web, worker (all Up/healthy)
#   Note: future gemini-only deploys skip Ollama via compose profile

# First cycle run (pending):
# Date:
# Command: python scripts/aws_standby.py cycle
# Timings:
# Exit code:
```

## Stand up Google Cloud

1. Create a Compute Engine VM (or GCE MIG) with Docker.
2. Same Tess prod compose as Hetzner/AWS; open 80/443; point DNS or use IP mode.
3. Set on control plane:

```env
OPS_GCP_BASE_URL=https://<gcp-host>
OPS_GCP_REGION=us-central1
OPS_GCP_CREDENTIALS_REF=GCP_SERVICE_ACCOUNT_JSON
```

4. Connect + probe as above (`prov_gcp`).

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

Chaos kinds: `none`, `high_latency`, `health_5xx`, `mark_unhealthy`, `worker_down`,
`redis_partition`, `cpu_burn`.

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
