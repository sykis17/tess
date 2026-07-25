#!/usr/bin/env bash
# =============================================================================
# Offline / sovereign ACCEPTANCE verifier (Step 4). Runs on the AIR-GAPPED host
# AFTER install-offline.sh. Proves the sovereignty claim as ARTIFACTS, not logs:
#   1. structural: every project container is on internal networks only
#   2. active egress probes from each interpreter-capable service MUST FAIL
#   3. local reachability (redis/etcd) MUST succeed (don't over-block)
#   4. split-brain harness run-all == 10/10, run from an in-container runner
#   5. no image pull occurred during the run
#
# The egress block is the engine-enforced `internal: true` networks (correct for
# Docker Desktop, where host iptables would not reach the engine VM). On a Linux
# VPS you may additionally apply deploy/offline/firewall-egress-block.sh.
#
# Because internal networks also remove host-loopback published-port reachability,
# the harness runs INSIDE a container on tess-engine_default and reaches the CP
# nodes by CONTAINER NAME (a manual `docker network connect` during s03/s05 does
# NOT restore compose's service alias, but the container name always resolves).
#
# Usage: ./verify-egress-blocked.sh [--target DIR] [--report [DIR]]
#   --target  install dir to verify (default /opt/tess-engine)
#   --report  on a PASS, self-archive the attestation to DIR (default
#             deploy/offline/out/, relative to --target). Best-effort and
#             guarded: it NEVER changes the pass/fail verdict or exit code.
# =============================================================================
set -euo pipefail

TARGET="/opt/tess-engine"
PROJECT="tess-engine"
COMPOSE_FILE="docker-compose.offline.yml"
RUNNER_IMAGE="tess-engine-harness-runner:offline"
DEFAULT_REPORT_DIR="deploy/offline/out"
REPORT_DIR=""   # empty = stdout only (unchanged default behavior)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift ;;
    --report)
      # optional DIR; bare `--report` uses the default. Enables self-archiving
      # only — it can never alter the verifier's verdict (see the tail).
      if [[ -n "${2:-}" && "${2:-}" != --* ]]; then REPORT_DIR="$2"; shift
      else REPORT_DIR="$DEFAULT_REPORT_DIR"; fi ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "[verify-egress] $*"; }

cd "$TARGET" || die "target $TARGET not found (run install-offline.sh first)"
dc() { docker compose -f "$COMPOSE_FILE" -p "$PROJECT" "$@"; }

dc ps -q >/dev/null 2>&1 || die "stack not found for project $PROJECT — run install-offline.sh first"
[[ -n "$(dc ps -q)" ]] || die "no running containers for project $PROJECT"

# --- 1. Structural: every attached network of every project container is internal
say "structural check: all project networks internal:true"
for cid in $(dc ps -q); do
  cname="$(docker inspect -f '{{.Name}}' "$cid" | sed 's#^/##')"
  nets="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$cid")"
  [[ -n "$nets" ]] || die "$cname has no networks?"
  for net in $nets; do
    internal="$(docker network inspect -f '{{.Internal}}' "$net" 2>/dev/null || echo unknown)"
    [[ "$internal" == "true" ]] || die "$cname is on NON-internal network '$net' — egress not contained"
  done
done

# --- 2. Active egress probes: MUST FAIL (per-stack, not just web) ---------------
say "active egress probes (each MUST fail)"
for svc in web web-standby worker; do
  if dc exec -T "$svc" python -c "import socket; socket.create_connection(('1.1.1.1',443),4)" >/dev/null 2>&1; then
    die "EGRESS NOT BLOCKED: $svc reached 1.1.1.1:443 (IP layer) — refusing to trust harness"
  fi
  if dc exec -T "$svc" python -c "import urllib.request; urllib.request.urlopen('https://pypi.org',timeout=4)" >/dev/null 2>&1; then
    die "EGRESS NOT BLOCKED: $svc reached pypi.org (DNS/pip path) — refusing to trust harness"
  fi
  say "  $svc: egress blocked (IP + DNS)"
done

# --- 3. Must-succeed local reachability (don't over-block) ----------------------
say "local reachability (MUST succeed)"
dc exec -T web python -c "import socket; socket.create_connection(('redis',6379),4)" >/dev/null 2>&1 || die "web cannot reach redis:6379"
dc exec -T web python -c "import socket; socket.create_connection(('etcd',2379),4)"  >/dev/null 2>&1 || die "web cannot reach etcd:2379"

# --- 4. No-pull assertion: snapshot the local image set around the run ----------
IMAGES_BEFORE="$(docker images -q | LC_ALL=C sort -u | sha256sum | cut -d' ' -f1)"

# --- 5. Harness run-all via an in-container runner (by CONTAINER NAME) -----------
web_name="$(docker inspect -f '{{.Name}}' "$(dc ps -q web)"         | sed 's#^/##')"
standby_name="$(docker inspect -f '{{.Name}}' "$(dc ps -q web-standby)" | sed 's#^/##')"
worker_name="$(docker inspect -f '{{.Name}}' "$(dc ps -q worker)"      | sed 's#^/##')"

# Git-Bash / MSYS on Windows mangles -v paths and the socket arg; neutralize it.
sock="/var/run/docker.sock"
mount_src="$TARGET"
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1; mount_src="$(cygpath -w "$TARGET" 2>/dev/null || echo "$TARGET")" ;;
esac

say "running split-brain harness run-all (in-container; internal network)"
set +e
docker run --rm --network "${PROJECT}_default" \
  -v "${sock}:/var/run/docker.sock" \
  -v "${mount_src}:/work" -w /work \
  -e OPS_HA_SMOKE_A="http://${web_name}:8000" \
  -e OPS_HA_SMOKE_B="http://${standby_name}:8000" \
  -e OPS_HA_WORKER_METRICS="http://${worker_name}:9109" \
  -e OPS_HA_COMPOSE_BASE="$COMPOSE_FILE" \
  -e OPS_HA_COMPOSE_OVERLAY= \
  -e OPS_HA_COMPOSE_OBS= \
  -e OPS_ADMIN_TOKEN="${OPS_ADMIN_TOKEN:-ha-harness-token}" \
  "$RUNNER_IMAGE" \
  python3 -m scripts.ops_cp_splitbrain run-all
RC=$?
set -e

# --- 6. No-pull check + verdict ------------------------------------------------
IMAGES_AFTER="$(docker images -q | LC_ALL=C sort -u | sha256sum | cut -d' ' -f1)"
[[ "$IMAGES_BEFORE" == "$IMAGES_AFTER" ]] || die "local image set changed during the run — a pull or build occurred"

[[ $RC -eq 0 ]] || die "split-brain harness run-all FAILED (exit $RC)"

# --- 7. Attestation --------------------------------------------------------------
# The verdict is already decided above (any failure exited via die(); reaching
# here means RC==0). Build the attestation ONCE, always print it to stdout, and
# — only with --report — best-effort self-archive it. The archive is fully
# guarded (&&/|| so `set -e` cannot trip on it) and we exit "$RC" explicitly, so
# a failed or partial report write can never flip a real failure to green.
ATTESTATION="$(cat <<'EOF'
===============================================================================
 SOVEREIGNTY ATTESTATION
   - every project container attaches to internal networks only
   - web / web-standby / worker cannot reach 1.1.1.1:443 or pypi.org
   - redis / etcd reachable locally (stack fully functional)
   - no image pull/build occurred during the run
   - split-brain harness run-all: 10/10 PASS, egress blocked
===============================================================================
EOF
)"

echo
printf '%s\n' "$ATTESTATION"

if [[ -n "$REPORT_DIR" ]]; then
  ts="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo undated)"
  head_commit="$(git -C "$TARGET" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  report_file="${REPORT_DIR}/attestation-${ts}.txt"
  case "$report_file" in /*) report_disp="$report_file" ;; *) report_disp="$PWD/$report_file" ;; esac
  if mkdir -p "$REPORT_DIR" 2>/dev/null; then
    {
      echo "date_utc:      $(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
      echo "head_commit:   $head_commit"
      echo "image_set_sha: $IMAGES_AFTER"
      echo "harness_rc:    $RC"
      echo
      printf '%s\n' "$ATTESTATION"
    } >"$report_file" 2>/dev/null \
      && say "attestation self-archived -> ${report_disp}" \
      || say "WARN: attestation report write failed (verifier verdict unaffected)"
  else
    say "WARN: could not create report dir '$REPORT_DIR' (verifier verdict unaffected)"
  fi
fi

# Explicit: the exit code is the harness verdict (RC==0 here), never the report write.
exit "$RC"
