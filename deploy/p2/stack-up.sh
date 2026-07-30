#!/usr/bin/env bash
# P2 Step 3 — full-stack bring-up for a serving node. Mirrors deploy.sh's
# IP-mode steps (Caddyfile selection, frontend build with the node's public
# ws URL baked in, dist assertions, model pull) against the p2 compose.
#
# Run ON the node from the repo root:
#   bash deploy/p2/stack-up.sh deploy/p2/env/nodeN.env
# Requires .env.prod with DOMAIN=<node public IP> and OLLAMA_MODEL pinned.
set -euo pipefail

NODE_ENV="${1:?usage: stack-up.sh deploy/p2/env/nodeN.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

ENV_FILE="${REPO_ROOT}/.env.prod"
[ -f "${ENV_FILE}" ] || { echo "Missing ${ENV_FILE}"; exit 1; }
# Read ONLY the values this script needs — never `set -a; source` the whole
# file: exported vars beat --env-file in compose interpolation, so sourcing
# .env.prod here silently overrode the node env file's HA block and disabled
# HA on both CPs (found live, Step 3 phase A). Compose gets its values from
# the --env-file flags alone.
env_get() { sed -n "s/^$1=//p" "${ENV_FILE}" | tail -1 | tr -d '\r'; }
DOMAIN="$(env_get DOMAIN)"
OLLAMA_MODEL="$(env_get OLLAMA_MODEL)"
VITE_FROM_FILE="$(env_get VITE_WS_BASE_URL)"

[ -n "${DOMAIN:-}" ] || { echo "DOMAIN required in .env.prod (node public IP)"; exit 1; }
if ! [[ "${DOMAIN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "P2 stacks are IP-mode only (DOMAIN=${DOMAIN})"
  exit 1
fi

cp "${REPO_ROOT}/deploy/Caddyfile.ip" "${REPO_ROOT}/deploy/Caddyfile.active"
export VITE_WS_BASE_URL="${VITE_WS_BASE_URL:-${VITE_FROM_FILE:-ws://${DOMAIN}}}"
echo "Building frontend with VITE_WS_BASE_URL=${VITE_WS_BASE_URL}"
cd "${REPO_ROOT}/frontend"
npm ci
npm run build
cd "${REPO_ROOT}"
for entry in ops-ui/index.html ops-status/index.html architecture/index.html; do
  [ -f "frontend/dist/${entry}" ] || { echo "ERROR: frontend/dist/${entry} missing after build"; exit 1; }
done

COMPOSE=(docker compose --env-file .env.prod --env-file "${NODE_ENV}"
  -f deploy/p2/docker-compose.p2-cp.yml --profile cp --profile stack)
"${COMPOSE[@]}" up -d --build

MODEL="${OLLAMA_MODEL:-llama3.2}"
echo "Pulling Ollama model ${MODEL} (first run may take minutes)..."
# </dev/null is load-bearing: a stdin-attached exec inside an ssh-fed script
# eats the script's own tail (P2 Step 1, CR-11 materialized).
"${COMPOSE[@]}" exec -T ollama ollama pull "${MODEL}" </dev/null 2>&1 | tail -1

"${COMPOSE[@]}" ps
echo "STACK-UP-DONE $(hostname)"
