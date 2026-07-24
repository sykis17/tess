# Ops CP HA split-brain harness

## Prereq

```bash
docker compose -f docker-compose.yml -f docker-compose.ops-ha.yml -p tess-engine up --build -d
```

Overlay sets `OPS_ADMIN_TOKEN=ha-harness-token` for both CPs (override via env if needed).

## Run

```bash
# from repo root
python -m scripts.ops_cp_splitbrain list
python -m scripts.ops_cp_splitbrain run-all
python -m scripts.ops_cp_splitbrain run s02_pause_primary
```

Each scenario **resets** the stack (recreate webs/etcd, wipe Redis fence+blob) and
verifies a clean baseline before inject. `run-all` therefore isolates s7/s8
corruption from later scenarios.

**s04** pauses Redis (not multi-network disconnect): on a single Compose network,
disconnecting the primary also cuts etcd; pause keeps election reachable while
blocking durable CAS.

**Note:** bumping Redis `fence_term` ahead of etcd (s07/s08b) correctly rejects
stale writers, but `promote_redis_fence` requires `etcd_term > redis_term`, so
the next scenario reset (key wipe) is what restores electability. That is
intentional isolation, not a silent pass.

## Timeouts

`CONVERGENCE_TIMEOUT = 3 × OPS_ETCD_LEASE_TTL_SECONDS` (default 30s). Override with
`OPS_HA_CONVERGENCE_TIMEOUT`.

## Pass rule

Assertions use Redis keys, `GET /ops/ha`, and HTTP bodies — not log strings.
