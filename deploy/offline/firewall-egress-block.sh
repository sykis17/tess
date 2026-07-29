#!/usr/bin/env bash
# =============================================================================
# LINUX-VPS egress block via the DOCKER-USER chain. OPTIONAL / alternative path.
#
# NOT for Docker Desktop / WSL2 — there the engine runs in a separate utility VM,
# so iptables in your distro does not touch container networking; use the
# `internal: true` networks in docker-compose.offline.yml instead (that is the
# mechanism this step's acceptance uses).
#
# On a real Linux host this blocks container -> public-internet traffic while
# preserving inter-container comms AND host-published ports (so, unlike the
# internal-network approach, the harness could also be run from the host). It is
# the more comprehensive block for a production sovereign deploy.
#
# Container egress is FORWARDed (not host-OUTPUT), so it must be filtered in
# DOCKER-USER — a host OUTPUT drop would be a false-green. Run as root. Revert
# with firewall-restore.sh. Verify with verify-egress-blocked.sh.
# =============================================================================
set -euo pipefail

[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }
command -v iptables >/dev/null || { echo "iptables required" >&2; exit 1; }

# Rebuild DOCKER-USER deterministically (the default chain is a single RETURN,
# which would let everything through before any DROP we append).
iptables -N DOCKER-USER 2>/dev/null || true
iptables -F DOCKER-USER
iptables -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
# Allow inter-container / host / private-range destinations.
iptables -A DOCKER-USER -d 10.0.0.0/8     -j RETURN
iptables -A DOCKER-USER -d 172.16.0.0/12  -j RETURN
iptables -A DOCKER-USER -d 192.168.0.0/16 -j RETURN
# Everything else originating from containers (i.e. the public internet) is dropped.
iptables -A DOCKER-USER -j DROP
# Restore the default tail so non-matching traffic returns to the FORWARD chain.
iptables -A DOCKER-USER -j RETURN

echo "DOCKER-USER egress block installed. Verify: deploy/offline/verify-egress-blocked.sh"
