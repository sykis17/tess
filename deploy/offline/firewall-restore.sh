#!/usr/bin/env bash
# Revert deploy/offline/firewall-egress-block.sh: restore DOCKER-USER to its
# default (a single RETURN). Run as root. Linux-VPS only.
set -euo pipefail
[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }
command -v iptables >/dev/null || { echo "iptables required" >&2; exit 1; }
iptables -F DOCKER-USER
iptables -A DOCKER-USER -j RETURN
echo "DOCKER-USER restored to default (single RETURN)."
