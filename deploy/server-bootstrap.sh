#!/usr/bin/env bash
# Run once on a fresh Ubuntu 24.04 Hetzner VPS (as root or with sudo).
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/server-bootstrap.sh"
  exit 1
fi

echo "==> Updating packages..."
apt-get update
apt-get install -y ca-certificates curl git ufw

echo "==> Configuring firewall (SSH, HTTP, HTTPS)..."
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status

echo "==> Installing Docker..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "==> Installing Node.js 20..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "==> Creating /opt/tess-engine..."
mkdir -p /opt/tess-engine

echo ""
echo "Bootstrap complete."
echo "  Docker: $(docker --version)"
echo "  Node:   $(node --version)"
echo "  npm:    $(npm --version)"
echo ""
echo "Next steps:"
echo "  1. Clone: git clone https://github.com/sykis17/tess.git /opt/tess-engine"
echo "  2. Config: cp /opt/tess-engine/.env.prod.example /opt/tess-engine/.env.prod"
echo "  3. Deploy: cd /opt/tess-engine && chmod +x deploy/deploy.sh && ./deploy/deploy.sh"
