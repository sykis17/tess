# Ops CP HA split-brain harness

## Prereq

```bash
docker compose -f docker-compose.yml -f docker-compose.ops-ha.yml -p tess-engine up --build -d
```

Overlay sets `OPS_ADMIN_TOKEN=ha-harness-token` for both CPs (override via env if needed).

**Token-drift trap:** compose interpolates `${OPS_ADMIN_TOKEN:-...}` from the repo's
`.env` file, but the harness client reads the host *shell* env. If your `.env` sets a
real `OPS_ADMIN_TOKEN` (e.g. for prod smoke scripts), the containers get that value
while the harness defaults to `ha-harness-token` → every scenario fails `403 Invalid
admin token`. Export the same value before running:
`export OPS_ADMIN_TOKEN=$(grep '^OPS_ADMIN_TOKEN=' .env | cut -d= -f2)`.

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

**Note:** under **redis authority**, bumping Redis `fence_term` ahead of etcd (s07/s08b) correctly rejects
stale writers, but `promote_fence` requires `etcd_term > redis_term`, so
the next scenario reset (key wipe) is what restores electability. That is
intentional isolation, not a silent pass.

## Timeouts

`CONVERGENCE_TIMEOUT = 3 × OPS_ETCD_LEASE_TTL_SECONDS` (default 30s). Override with
`OPS_HA_CONVERGENCE_TIMEOUT` (the offline verifier passes 6×TTL — single-node etcd-fault
recovery on small hosts measures ~35–60s).

## Topology skips

A scenario module may declare `skip_reason(cfg) -> str | None`. `s11` requires a surviving
quorum after the leader kill (≥3 members in `OPS_HA_ETCD_SERVICES`); on smaller topologies
(e.g. the offline stack's single `etcd`) it reports an explicit `[SKIP]` with its reason —
decided before any docker call, never silently absent. The summary tally separates skips:

```
10/10 PASS, 1 SKIPPED: s11_kill_etcd_leader_storm (topology: quorum-only scenario — ...)
```

Skips do not affect the exit code. To pin the expected tally as an exit-code artifact,
`run-all` takes `--expect-pass N` / `--expect-skip N` — the offline verifier passes
`--expect-pass 10 --expect-skip 1` (its certification baseline); the dev gate is
`--expect-pass 11 --expect-skip 0`, which proves s11 executes on the 3-node topology.

## Pass rule

Assertions use Redis keys, `GET /ops/ha`, and HTTP bodies — not log strings.
