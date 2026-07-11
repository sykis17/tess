#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

ENV_FILE="${REPO_ROOT}/.env.prod"
ACTIVE_CADDY="${REPO_ROOT}/deploy/Caddyfile.active"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.prod.example to .env.prod and set your values."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ -z "${DOMAIN:-}" ]]; then
  echo "DOMAIN is required in .env.prod (use your hostname or server IP)"
  exit 1
fi

is_ip_address() {
  [[ "${1}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

if is_ip_address "${DOMAIN}"; then
  cp "${REPO_ROOT}/deploy/Caddyfile.ip" "${ACTIVE_CADDY}"
  DEFAULT_WS_URL="ws://${DOMAIN}"
  HEALTH_URL="http://${DOMAIN}/health"
  APP_URL="http://${DOMAIN}"
  echo "IP-only mode (no TLS): serving on http://${DOMAIN}"
else
  cp "${REPO_ROOT}/deploy/Caddyfile" "${ACTIVE_CADDY}"
  DEFAULT_WS_URL="wss://${DOMAIN}"
  HEALTH_URL="https://${DOMAIN}/health"
  APP_URL="https://${DOMAIN}"
  echo "Domain mode: serving on https://${DOMAIN}"
fi

if [[ -z "${VITE_WS_BASE_URL:-}" ]]; then
  export VITE_WS_BASE_URL="${DEFAULT_WS_URL}"
  echo "VITE_WS_BASE_URL not set; defaulting to ${VITE_WS_BASE_URL}"
fi

echo "Building frontend with VITE_WS_BASE_URL=${VITE_WS_BASE_URL}"
cd "${REPO_ROOT}/frontend"
npm ci
npm run build
cd "${REPO_ROOT}"

echo "Starting production stack..."
docker compose --env-file "${ENV_FILE}" -f docker-compose.prod.yml up -d --build

echo ""
echo "Waiting for services to become healthy..."
sleep 5
docker compose --env-file "${ENV_FILE}" -f docker-compose.prod.yml ps

echo ""
echo "Checking ${HEALTH_URL} ..."
if curl -fsS "${HEALTH_URL}"; then
  echo ""
  echo "Deploy complete. Open ${APP_URL}"
else
  echo ""
  echo "Health check failed. Inspect logs with:"
  echo "  docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f caddy web worker"
  exit 1
fi
