#!/usr/bin/env bash
# =============================================================================
# Offline / sovereign bundle BUILDER (Step 4). Runs on a CONNECTED machine.
#
# Produces a single self-contained tarball that install-offline.sh deploys on an
# air-gapped host with zero outbound network. Building still needs the network
# (image pulls, pip, npm) — only the DEPLOY must be offline (non-goal: air-gapped
# build).
#
# Usage:
#   deploy/offline/build-bundle.sh [--allow-dirty] [--out DIR] [--with-prod]
#     --allow-dirty  stamp from a dirty tree (TEST bundles only; loud warning,
#                    commit is suffixed -dirty, commit-binding guard is advisory)
#     --out DIR      output directory (default: deploy/offline/dist)
#     --with-prod    also save caddy + ollama images (full prod-capable bundle;
#                    NOT needed for the harness-only offline acceptance)
#
# Every gate fails loud (set -e). See deploy/MULTI_CLOUD.md §Offline Packaging.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

OUT="deploy/offline/dist"
ALLOW_DIRTY=0
WITH_PROD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    --with-prod)   WITH_PROD=1 ;;
    --out)         OUT="$2"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "[build-bundle] $*"; }

command -v docker >/dev/null || die "docker not found"

# --- 1. Commit binding: clean tree required (closes bind-mount code-vs-image gap) ---
GIT_COMMIT="$(git rev-parse HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
  if [[ $ALLOW_DIRTY -eq 1 ]]; then
    say "WARNING: working tree is DIRTY — this is a TEST bundle, not for release."
    GIT_COMMIT="${GIT_COMMIT}-dirty"
  else
    die "working tree is dirty. Commit first, or pass --allow-dirty for a test bundle."
  fi
fi
say "git commit: $GIT_COMMIT"

BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- 2. Third-party images: pull + record digests (integrity + audit) ----------
THIRD_PARTY=( "redis:7-alpine" "quay.io/coreos/etcd:v3.5.16" )
if [[ $WITH_PROD -eq 1 ]]; then
  THIRD_PARTY+=( "caddy:2-alpine" \
    "ollama/ollama@sha256:f040603c11a11f125660eaf848170780e43b68973fc270e26f168536031ac258" )
fi

rm -rf "$OUT"
mkdir -p "$OUT/images" "$OUT/repo"
LOCK="$OUT/bundle-lock.txt"
{
  echo "# tess-engine offline bundle lock"
  echo "git_commit=$GIT_COMMIT"
  echo "build_date=$BUILD_DATE"
} > "$LOCK"

for ref in "${THIRD_PARTY[@]}"; do
  say "pull $ref"
  docker pull "$ref" >/dev/null
  digest="$(docker inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' "$ref" 2>/dev/null || true)"
  echo "thirdparty ${ref} ${digest:-<none>}" >> "$LOCK"
done

# --- 3. Build the offline images (names must match docker-compose.offline.yml) --
say "build tess-engine-app:offline"
docker build -t tess-engine-app:offline --build-arg GIT_COMMIT="$GIT_COMMIT" . >/dev/null
say "build tess-engine-otel:offline (deploy/ context — repo-root .dockerignore hides deploy/)"
docker build -f deploy/offline/otel/Dockerfile -t tess-engine-otel:offline deploy >/dev/null
say "build tess-engine-harness-runner:offline"
docker build -f deploy/offline/harness-runner/Dockerfile -t tess-engine-harness-runner:offline . >/dev/null

# --- 4. Provenance for the unpinned requirements.txt (records what was built) ---
say "capture requirements.lock.txt (pip freeze from the built image)"
docker run --rm tess-engine-app:offline pip freeze > "$OUT/requirements.lock.txt"

# --- 5. Frontend: build CDN-free, guard, tar dist (dist is gitignored) ---------
say "build frontend (must be CDN-free after font vendoring)"
( cd frontend && npm ci --silent && npm run build >/dev/null )
if grep -rqE 'fonts\.googleapis|fonts\.gstatic' frontend/dist; then
  die "Google Fonts CDN refs survive in frontend/dist — font vendoring incomplete."
fi
tar -C frontend -cf "$OUT/repo/frontend-dist.tar" dist

# --- 6. Repo snapshot at the exact commit (bind mounts need matching code) ------
say "git archive repo snapshot"
git archive --format=tar HEAD -o "$OUT/repo/repo-snapshot.tar"
echo "$GIT_COMMIT" > "$OUT/repo/COMMIT"

# --- 7. docker save ALL images in ONE call (layer dedup) + record image IDs -----
SAVE=( tess-engine-app:offline tess-engine-otel:offline tess-engine-harness-runner:offline \
       redis:7-alpine quay.io/coreos/etcd:v3.5.16 )
if [[ $WITH_PROD -eq 1 ]]; then
  SAVE+=( caddy:2-alpine \
    ollama/ollama@sha256:f040603c11a11f125660eaf848170780e43b68973fc270e26f168536031ac258 )
fi
say "docker save ${#SAVE[@]} images -> images/all-images.tar"
docker save -o "$OUT/images/all-images.tar" "${SAVE[@]}"
: > "$OUT/images/images.ids"
for ref in "${SAVE[@]}"; do
  id="$(docker inspect --format '{{.Id}}' "$ref")"
  printf '%s\t%s\n' "$ref" "$id" >> "$OUT/images/images.ids"
done

# --- 8. Stage installer + verifier + config into the bundle --------------------
cp deploy/offline/install-offline.sh       "$OUT/"
cp deploy/offline/verify-egress-blocked.sh "$OUT/"
cp deploy/offline/firewall-egress-block.sh "$OUT/"
cp deploy/offline/firewall-restore.sh      "$OUT/"
cp .env.offline.example                    "$OUT/"
chmod +x "$OUT/"*.sh
{ echo "commit=$GIT_COMMIT"; echo "build_date=$BUILD_DATE"; } > "$OUT/VERSION"

# --- 9. Integrity manifest over everything (except the manifest itself) ---------
say "write MANIFEST.sha256"
( cd "$OUT" && find . -type f ! -name MANIFEST.sha256 -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum > MANIFEST.sha256 )

# --- 10. Final bundle tarball + its own checksum -------------------------------
BUNDLE="tess-offline-bundle-${GIT_COMMIT}.tar.gz"
say "tar bundle -> $BUNDLE"
tar -C "$OUT" -czf "$BUNDLE" .
sha256sum "$BUNDLE" > "$BUNDLE.sha256"

say "DONE"
echo
echo "  bundle:   $BUNDLE"
echo "  checksum: $BUNDLE.sha256"
echo "  commit:   $GIT_COMMIT"
echo
echo "Transfer both files to the offline host, then:"
echo "  sha256sum -c $BUNDLE.sha256   # verify in transit"
echo "  mkdir tess-offline && tar -C tess-offline -xzf $BUNDLE && cd tess-offline"
echo "  ./install-offline.sh --target /opt/tess-engine"
echo "  ./verify-egress-blocked.sh --target /opt/tess-engine   # harness run-all 10/10"
