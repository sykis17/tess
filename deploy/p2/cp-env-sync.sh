#!/usr/bin/env bash
# P2 Step 2 — OPS_ADMIN_TOKEN single-sourcing (the P1 403-storm lesson,
# institutionalized as mechanism): ONE token, generated once, written into the
# CP nodes' .env.prod over SSH. The witness gets none (etcd only, no CP).
#
# The token is never printed and never committed — output is a sha256
# fingerprint per node; the battery asserts the fingerprints are equal.
# An empty `OPS_ADMIN_TOKEN=` line (the .env.prod.example form) counts as
# absent — an empty match must never be "synced" as a token.
#
# Usage: bash deploy/p2/cp-env-sync.sh
# Env:   MESH_SSH_KEY  SSH key for root@nodes (default ~/.ssh/tess_p2_harness)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source <(tr -d '\r' <"${SCRIPT_DIR}/mesh-inventory.env")

SSH_KEY="${MESH_SSH_KEY:-${HOME}/.ssh/tess_p2_harness}"
SSH_OPTS=(-i "${SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=10)

# Read from node1; the `..*` pattern requires a non-empty value.
TOKEN=$(ssh "${SSH_OPTS[@]}" "root@${NODE1_PUBLIC_IP}" \
  "sed -n 's/^OPS_ADMIN_TOKEN=\(..*\)$/\1/p' /opt/tess-engine/.env.prod 2>/dev/null | head -1" || true)

if [ -z "${TOKEN}" ]; then
  TOKEN=$(openssl rand -hex 32)
  echo "generated new OPS_ADMIN_TOKEN (value not shown)"
else
  echo "reusing existing OPS_ADMIN_TOKEN from node1 (value not shown)"
fi

for ip in "${NODE1_PUBLIC_IP}" "${NODE2_PUBLIC_IP}"; do
  ssh "${SSH_OPTS[@]}" "root@${ip}" "umask 077
    f=/opt/tess-engine/.env.prod
    touch \"\$f\"
    if grep -q '^OPS_ADMIN_TOKEN=' \"\$f\"; then
      sed -i 's|^OPS_ADMIN_TOKEN=.*|OPS_ADMIN_TOKEN=${TOKEN}|' \"\$f\"
    else
      echo 'OPS_ADMIN_TOKEN=${TOKEN}' >> \"\$f\"
    fi
    printf '%s fingerprint sha256:%s\n' \"\$(hostname)\" \
      \"\$(sed -n 's/^OPS_ADMIN_TOKEN=//p' \"\$f\" | head -1 | tr -d '\n' | sha256sum | cut -c1-16)\""
done
