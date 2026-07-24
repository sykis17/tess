# Host metrics rollout (Hetzner + AWS + GCP)

Commit `0615303` on **`main`** adds self-reported `cpu_percent` / `mem_percent` to
**GET** `/health` on every Tess stack via `app/core/host_metrics.py` (psutil).
There is no provider-specific code path — rollout is **deploy that commit to each
server** and verify the health contract.

## Code vs docs (branch workflow)

| What | Where | Action |
|------|-------|--------|
| Host metrics collector + `/health` wiring | `main` (`0615303`) | **Deploy to servers** — `git pull origin main` on each host |
| This rollout guide | `cursor/host-metrics-hetzner-aws-rollout` (draft PR #1) | **Review/merge via PR** — docs only, not required to deploy metrics |

**Deploying already-merged `main` to servers is not the same as committing new code
to `main`.** New application changes still go: feature branch → draft PR → merge →
then `git pull origin main` on hosts. This rollout only pulls existing merged code.

## Prerequisites

- `main` includes commit `0615303` or later (`psutil` in `requirements.txt`).
- `./deploy/deploy.sh` rebuilds the `web` image (`pip install -r requirements.txt`).

## Suggested order

1. **Hetzner** (control plane, always on — lowest risk)
2. **AWS** (wake → deploy → verify → optional sleep)
3. **GCP** (wake → deploy → verify — partial validation may already exist)

## 1. Hetzner (control plane — always on)

SSH to the control plane:

```bash
ssh root@5.78.186.223
```

Confirm the clone path before `cd` (docs assume `/opt/tess-engine`):

```bash
ls -la /opt/tess-engine/.git 2>/dev/null && echo "OK: /opt/tess-engine" || echo "Not here — find your clone:"
find /opt /root /home -maxdepth 3 -name tess-engine -type d 2>/dev/null
```

Then deploy from the confirmed path:

```bash
cd /opt/tess-engine   # adjust if your clone lives elsewhere
git pull origin main
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

Verify host metrics:

```bash
curl -s http://5.78.186.223/health | python3 -m json.tool
```

Expected (values will vary):

```json
{
  "status": "ok",
  "redis": "ok",
  "cpu_percent": 12.4,
  "mem_percent": 58.1,
  "network": { "bytes_sent": 12345, "bytes_recv": 67890 }
}
```

`network` is optional. If `cpu_percent` / `mem_percent` are missing, the `web`
container may be running an old image — rerun `./deploy/deploy.sh` (forces
`--build`).

Ops UI check (Bearer token required):

1. Open `http://5.78.186.223/ops-status/`
2. Click **Probe now** (or wait for the 30s background prober)
3. Confirm `prov_hetzner_local` snapshot shows non-null `cpu_percent` / `mem_percent`

## 2. AWS (standby — wake first)

AWS is stopped-by-default. Wake from your laptop:

```powershell
$env:OPS_AWS_BASE_URL = "http://18.227.172.81"
python scripts/aws_standby.py wake
```

SSH and deploy (confirm clone path first, same as Hetzner):

```bash
ssh -i ~/path/to/tess-aws-key.pem ubuntu@18.227.172.81
ls -la /opt/tess-engine/.git 2>/dev/null || find /opt /home/ubuntu -maxdepth 3 -name tess-engine -type d 2>/dev/null
cd /opt/tess-engine   # adjust if your clone lives elsewhere
git pull origin main
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

Verify:

```bash
curl -s http://18.227.172.81/health | python3 -m json.tool
```

From the control plane (or laptop with `OPS_ADMIN_TOKEN`):

```bash
curl -s -X POST "http://5.78.186.223/ops/probe" \
  -H "Authorization: Bearer $OPS_ADMIN_TOKEN"
```

Check `GET /ops/health-logs` — `prov_aws` should show `cpu_percent` / `mem_percent`
in the latest snapshot.

Stop AWS when done (optional):

```powershell
python scripts/aws_standby.py sleep
```

## 3. GCP (standby — wake first, do last)

Same pattern as AWS. Partial validation may already exist from earlier GCP work;
still worth a full deploy + verify after Hetzner and AWS are green.

```powershell
$env:OPS_GCP_BASE_URL = "http://34.46.222.191"
python scripts/gcp_standby.py wake
```

SSH, `git pull`, `./deploy/deploy.sh`, then:

```bash
curl -s http://34.46.222.191/health | python3 -m json.tool
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `/health` returns only `status` + `redis` | Old `web` image | `./deploy/deploy.sh` (rebuild) |
| `cpu_percent` always `0.0` | First psutil sample (interval=0) | Normal on first read; prober will see real values on next probe |
| Metrics in `/health` but not in ops score | Prober not run yet | `POST /ops/probe` or wait 30s |
| AWS/GCP unreachable | Instance stopped | `aws_standby.py wake` / `gcp_standby.py wake` |
| AWS SSH timeout after wake | SG `launch-wizard-1` locked to stale laptop IP | Allow current public IP on TCP/22 (`aws_standby.py` wake prints IP preflight) |
| AWS hung during `npm`/`docker` build | t3.micro ~1GB RAM, no swap | Add 1GB swapfile + `/etc/fstab`; consider upsizing if failover load OOMs |
| GCP `git pull` / docker permission denied | Clone owned by `tessops` | `chown -R jesse_malma:… /opt/tess-engine`; add user to `docker` group |
| GCP wake auth fails | `GOOGLE_APPLICATION_CREDENTIALS` unset in this shell | New terminal after User env set; path `~\.ssh\tess-gcp-ops-key.json` |

## Rollout checklist

- [ ] Hetzner: `git pull` + `./deploy/deploy.sh`
- [ ] Hetzner: `curl /health` shows `cpu_percent` + `mem_percent`
- [ ] Hetzner: `/ops-status/` probe shows metrics on `prov_hetzner_local`
- [ ] AWS: wake → deploy → `curl /health` shows metrics
- [ ] AWS: ops probe shows metrics on `prov_aws`
- [ ] GCP: wake → deploy → `curl /health` shows metrics (if not already done)
- [ ] GCP: ops probe shows metrics on `prov_gcp`
