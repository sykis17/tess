#!/usr/bin/env bash
# P2 artifact archive — the second rung of the artifact-durability rule
# (docs/P2_OPENER.md §(a): first rung = fleet artifacts copy to node1; this
# rung = the evidence survives the fleet). Tars node1:/root/p2-artifacts/ and
# pulls it to the laptop archive. Run after each major battery.
#
# Usage: bash deploy/p2/pull-artifacts.sh
# Env:   MESH_SSH_KEY     SSH key (default ~/.ssh/tess_p2_harness)
#        P2_ARCHIVE_DIR   destination (default ~/tess-p2-artifacts)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source <(tr -d '\r' <"${SCRIPT_DIR}/mesh-inventory.env")

SSH_KEY="${MESH_SSH_KEY:-${HOME}/.ssh/tess_p2_harness}"
DEST="${P2_ARCHIVE_DIR:-${HOME}/tess-p2-artifacts}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${DEST}/p2-artifacts-${STAMP}.tar.gz"

mkdir -p "${DEST}"
ssh -i "${SSH_KEY}" -o BatchMode=yes "root@${NODE1_PUBLIC_IP}" \
  'tar -czf - -C /root p2-artifacts' > "${OUT}"
ls -l "${OUT}"
tar -tzf "${OUT}" | wc -l | xargs echo "entries:"
echo "archived: ${OUT}"
