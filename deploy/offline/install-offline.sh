#!/usr/bin/env bash
# =============================================================================
# Offline / sovereign INSTALLER (Step 4). Runs on the AIR-GAPPED host, from inside
# the extracted bundle directory. Every gate fails loud — never a silent
# half-deploy.
#
# Usage (after `tar -xzf tess-offline-bundle-<sha>.tar.gz` into a dir and cd'ing in):
#   ./install-offline.sh [--target DIR] [--prod]
#     --target DIR  where to lay down the repo snapshot + run from (default /opt/tess-engine)
#     --prod        require a strong OPS_ADMIN_TOKEN (reject empty / ha-harness-token)
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

TARGET="/opt/tess-engine"
PROD=0
PROJECT="tess-engine"
COMPOSE_FILE="docker-compose.offline.yml"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift ;;
    --prod)   PROD=1 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "[install-offline] $*"; }

command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not found"

# --- 1. Integrity: verify the manifest before trusting anything ----------------
say "verify MANIFEST.sha256"
sha256sum -c MANIFEST.sha256 >/dev/null || die "MANIFEST checksum mismatch — bundle corrupt or tampered"

# --- 2. Load images (docker load, not pull) ------------------------------------
say "docker load images/all-images.tar"
docker load -i images/all-images.tar >/dev/null

# --- 3. Image-ID guard: each loaded image must match the recorded ID -----------
say "verify loaded image IDs"
while IFS=$'\t' read -r ref id; do
  [[ -n "$ref" ]] || continue
  got="$(docker inspect --format '{{.Id}}' "$ref" 2>/dev/null || true)"
  [[ "$got" == "$id" ]] || die "image ID mismatch for $ref (expected $id, got ${got:-<missing>})"
done < images/images.ids

# --- 4. Lay down the repo snapshot + built frontend dist -----------------------
say "extract repo snapshot -> $TARGET"
mkdir -p "$TARGET"
tar -C "$TARGET" -xf repo/repo-snapshot.tar
mkdir -p "$TARGET/frontend"
tar -C "$TARGET/frontend" -xf repo/frontend-dist.tar
cp bundle-lock.txt VERSION "$TARGET/" 2>/dev/null || true

# --- 5. Commit-binding guard: image == snapshot == lock ------------------------
# Closes the "bind-mounted code vs. baked image" gap. (A -dirty test bundle will
# legitimately differ from the clean HEAD snapshot; warn instead of aborting.)
LABEL_COMMIT="$(docker inspect --format '{{index .Config.Labels "org.tess.commit"}}' tess-engine-app:offline)"
SNAP_COMMIT="$(cat repo/COMMIT)"
LOCK_COMMIT="$(sed -n 's/^git_commit=//p' bundle-lock.txt | head -1)"
if [[ "$LABEL_COMMIT" == *-dirty || "$SNAP_COMMIT" == *-dirty ]]; then
  say "WARNING: -dirty bundle; commit-binding is advisory (image=$LABEL_COMMIT snapshot=$SNAP_COMMIT)"
elif [[ "$LABEL_COMMIT" == "$SNAP_COMMIT" && "$SNAP_COMMIT" == "$LOCK_COMMIT" ]]; then
  say "commit-binding verified ($LABEL_COMMIT)"
else
  die "commit-binding mismatch: image=$LABEL_COMMIT snapshot=$SNAP_COMMIT lock=$LOCK_COMMIT"
fi

# --- 6. Env file: seed + validate ----------------------------------------------
ENVF="$TARGET/.env.offline"
if [[ ! -f "$ENVF" ]]; then
  cp .env.offline.example "$ENVF"
  say "wrote $ENVF — set OPS_ADMIN_TOKEN before a real deploy"
fi
if [[ $PROD -eq 1 ]]; then
  tok="$(sed -n 's/^OPS_ADMIN_TOKEN=//p' "$ENVF" | head -1)"
  [[ -n "$tok" && "$tok" != "ha-harness-token" ]] \
    || die "--prod requires a strong OPS_ADMIN_TOKEN in $ENVF (not empty, not ha-harness-token). Generate: openssl rand -hex 32"
fi

# --- 7. Bring up: NO build, NO pull (proves every image is present locally) -----
cd "$TARGET"
say "docker compose up -d --no-build --wait (pull_policy: never; internal networks)"
docker compose -f "$COMPOSE_FILE" -p "$PROJECT" --env-file "$ENVF" up -d --no-build --wait --wait-timeout 180

# --- 8. Smoke — container-side ONLY (internal networks: the host cannot reach the
#        stack; every check runs inside a container). ---------------------------
dc() { docker compose -f "$COMPOSE_FILE" -p "$PROJECT" "$@"; }
wait_health() {  # $1=service — poll /health (readiness can lag `up` even with --wait)
  local svc="$1" i
  for i in $(seq 1 30); do
    dc exec -T "$svc" curl -sf http://localhost:8000/health >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}
say "smoke: /health on both CP nodes"
wait_health web         || die "web /health failed"
wait_health web-standby || die "web-standby /health failed"
say "smoke: /ops/ha reports a role"
dc exec -T web curl -s http://localhost:8000/ops/ha | grep -q '"role"' || die "/ops/ha missing role"
say "smoke: worker Prometheus exposition on :9109 (scraped container-to-container)"
worker_metrics_ok() {
  local i
  for i in $(seq 1 15); do
    dc exec -T web python -c \
      "import urllib.request,sys; sys.exit(0 if b'tess_ops_' in urllib.request.urlopen('http://worker:9109/metrics',timeout=5).read() else 1)" \
      >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}
worker_metrics_ok || die "worker /metrics scrape failed"

say "INSTALL OK."
echo
echo "  target:  $TARGET"
echo "  next:    ./verify-egress-blocked.sh --target $TARGET   # egress self-check + harness run-all 10/10"
