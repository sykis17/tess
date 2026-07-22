# TESS Engine — Multi-cloud ops hardening (session 7 opener)

## Context

Control plane on Hetzner (`5.78.186.223`). Standbys stopped-by-default:

| Host | Provider id | Notes |
|------|-------------|-------|
| AWS EIP `18.227.172.81` | `prov_aws` | t3.micro + **1GB swap** (added 2026-07-22 after vite/Docker OOM hang) |
| GCP `34.46.222.191` | `prov_gcp` | e2-medium + 1GB swap (proactive) |

**Session 6 shipped:** `/ops-status/` read-only fleet view.

**Prior (2026-07-22):** Host metrics self-report (`cpu_percent` / `mem_percent`) on
all three stacks via [`app/core/host_metrics.py`](app/core/host_metrics.py);
rollout guide [`deploy/HOST_METRICS_ROLLOUT.md`](deploy/HOST_METRICS_ROLLOUT.md).

Prior openers: [MULTI_CLOUD_HARDENING_S6_OPENER.md](MULTI_CLOUD_HARDENING_S6_OPENER.md)
… [MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).

This session is **ops validation / runbook**, not LangGraph/POV work.

### Workflow (mandatory)

1. Branch **before** commits (e.g. `cursor/three-way-chaos-failover`)
2. Draft PR via `gh` → review → merge
3. Deploy already-merged `main` to servers as needed (≠ committing to `main`)

---

## This session goal — Step 3

Prove `consecutive_failures` → automatic failover using chaos / take-offline
(not only Force active). Cover **two standby targets** (AWS and GCP).

Policy defaults: `failure_threshold=3`, `min_score_for_healthy=40`,
`latency_p95_threshold_ms=5000`
([`app/ops/failover.py`](app/ops/failover.py)).

### Preflight

- [ ] Hetzner `GET /health` includes `cpu_percent` / `mem_percent`
- [ ] `echo $env:GOOGLE_APPLICATION_CREDENTIALS` →
  `C:\Users\jesse\.ssh\tess-gcp-ops-key.json` (new shell if unset)
- [ ] AWS SG `launch-wizard-1` allows current laptop public IP (SSH)
- [ ] `OPS_ADMIN_TOKEN` / `OPS_SMOKE_BASE_URL=http://5.78.186.223` set locally

### Run A — Hetzner → AWS

1. `python scripts/aws_standby.py wake` (or `cycle` for smoke + sleep)
2. Confirm `prov_aws` healthy with host metrics in `/ops-status/`
3. Chaos / `simulate-unhealthy` on `prov_hetzner_local` → probe until failover
4. **Watch AWS under failover load:** OOM, SSH hang, unhealthy probes on
   `prov_aws` after it becomes active (t3.micro + swap stress signal)
5. Clear chaos; force Hetzner; sleep AWS

| Kind | Expect failover? |
|------|------------------|
| `mark_unhealthy` / take-offline | Yes (~3 probes) |
| `worker_down` | Yes |
| `redis_partition` | Yes |
| `cpu_burn` | Yes (score &lt; 40) |
| `high_latency` (default 2500ms) | **No** (score-only) |

Smoke path: `OPS_SMOKE_STANDBY=prov_aws` +
[`scripts/ops_failover_live_smoke.py`](scripts/ops_failover_live_smoke.py)
(or `aws_standby.py cycle`).

### Run B — Hetzner → GCP

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\Users\jesse\.ssh\tess-gcp-ops-key.json"
$env:OPS_GCP_BASE_URL = "http://34.46.222.191"
$env:OPS_SMOKE_STANDBY = "prov_gcp"
python scripts/gcp_standby.py wake
# chaos / smoke → failover to prov_gcp → clear → force Hetzner
python scripts/gcp_standby.py sleep
```

Minimum: one hard-fail kind (`mark_unhealthy` or `cpu_burn`) + recover if AWS
matrix is green.

### Pass criteria

- [x] Failover only after `failure_threshold` consecutive unhealthy probes
- [x] Standby awake + healthy (score ≥ 40) to be selected
- [x] `/ops/events` / smoke output shows failover
- [x] Resting state restored: Hetzner active, AWS stopped, GCP stopped
- [x] Results table appended to [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md)

### t3.micro under failover load (record here)

| Observation | Result |
|-------------|--------|
| Swap held (no OOM / SSH hang) after AWS became active? | **Yes** (2026-07-22) — `aws_standby.py cycle` PASS; no SSH hang; probes stayed healthy while `prov_aws` was active |
| `prov_aws` stayed healthy while active? | **Yes** — connect `http_ok=True`; health-log samples showed score ~87 with `mem_percent` ~61% (t3.micro + 1GB swap) |
| Verdict: t3.micro OK as real failover target? | **OK for control-plane failover smoke** (simulate-unhealthy → 3 probes → switch → recover). Still thin for heavy LangGraph/LLM traffic — watch OOM if AWS remains active under real user load; consider upsizing if that path is required |

### Step 3 results (2026-07-22)

| Run | Standby | Result | Notes |
|-----|---------|--------|-------|
| A | `prov_aws` | PASS | Failover at probe #3; recovered to Hetzner; AWS stopped |
| B | `prov_gcp` | PASS | Failover by probe #3 (`active=prov_gcp`); recovered; GCP stopped. Hetzner failure count jumped 2→4 once (background prober race) |

Resting state restored: Hetzner active, AWS stopped, GCP stopped.
---

## Steps 4–5 (discuss only — do not implement this session)

### Step 4 — GcpAdapter Cloud Monitoring

**Deferred.** Self-report already feeds scoring apples-to-apples across providers.

- Keep `/health` self-report as source of truth for scoring
- If pursued later: enrichment-only fields in `provider_metrics` (no double penalty)
- Needs Monitoring IAM on `tess-gcp-ops` + SDK; credentials must live on control
  plane if FastAPI pulls Monitoring (not laptop-only JSON)

### Step 5 — Three-way chaos demo (stakeholder)

Ops/demo script, not engine features:

1. Wake one standby (time/cost pick)
2. `/ops-status/` shows host metrics
3. Take Hetzner offline → streak 1→2→3 → active flips
4. Clear + recover + sleep standby

Optional later: multi-standby selection in `ops_failover_live_smoke.py`.

---

## Infra polish (optional same PR)

| Issue | Fix |
|-------|-----|
| AWS SG stale laptop IP | Preflight on wake: print public IP + SG reminder |
| Missing `GOOGLE_APPLICATION_CREDENTIALS` | Fail fast in `gcp_standby.py` with path hint |
| AWS/GCP swap + GCP docker/`chown` | Notes in MULTI_CLOUD / HOST_METRICS_ROLLOUT |

---

## Out of scope

- Rewinding `main` / retroactive PR for host-metrics commit
- Seamless mid-session migration
- Secrets manager / Vault
- Hetzner Cloud API or AWS CloudWatch live pulls
- Implementing Cloud Monitoring SDK this session

---

## Quick pointers

| Concern | Location |
|---------|----------|
| Failover counters | [`app/ops/failover.py`](app/ops/failover.py) |
| Chaos kinds | [`app/ops/chaos.py`](app/ops/chaos.py), [`app/ops/prober.py`](app/ops/prober.py) |
| Live smoke | [`scripts/ops_failover_live_smoke.py`](scripts/ops_failover_live_smoke.py) |
| AWS wake/sleep | [`scripts/aws_standby.py`](scripts/aws_standby.py) |
| GCP wake/sleep | [`scripts/gcp_standby.py`](scripts/gcp_standby.py) |
| Control plane | `http://5.78.186.223` |
| Actions / Status | `/ops-ui/` · `/ops-status/` |
