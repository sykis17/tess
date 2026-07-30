#!/usr/bin/env bash
# P2 Step 1 — WireGuard mesh among the 3 cluster nodes, tunneled over the
# Hetzner Cloud Network (docs/P2_OPENER.md §(b): belt = private fabric,
# braces = encryption). Driven from the laptop over SSH; idempotent — every
# phase is safe to re-run.
#
# The observer is deliberately NOT in this mesh (opener §(b): it probes the
# scoped public path a user would). Private keys are generated on-node and
# never leave their node; only public keys travel back over SSH.
#
# Reachability of ${WG_PORT}/udp: WireGuard's ListenPort binds all interfaces
# (there is no listen-address option). Non-reachability from outside rests on
# the Hetzner Cloud Firewall ("everything else closed", Step 0) plus ufw
# default-deny with the source-scoped allow in the firewall phase — cloud
# firewalls filter only the public interface (opener Environment notes), so
# the ufw rule is the private-interface layer of the two-layer posture.
#
# MTU is measured, not assumed: WG MTU = parent private-NIC MTU − 80
# (worst-case WG overhead), verified by the two-color DF-ping in the verify
# phase (oversized must refuse — a clamp that can't fail red proves nothing).
#
# Usage:
#   bash deploy/p2/wireguard-mesh.sh [install|keygen|render|firewall|up|verify|all]
# Env:
#   MESH_SSH_KEY  SSH private key for root@nodes (default ~/.ssh/tess_p2_harness)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# CRLF-defensive source: Windows checkouts may add \r to unlisted extensions.
source <(tr -d '\r' <"${SCRIPT_DIR}/mesh-inventory.env")

SSH_KEY="${MESH_SSH_KEY:-${HOME}/.ssh/tess_p2_harness}"
SSH_OPTS=(-i "${SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=10)

PHASE="${1:-all}"

nvar() { # nvar node1 WG_IP -> value of NODE1_WG_IP
  local upper
  upper=$(echo "$1" | tr '[:lower:]' '[:upper:]')
  eval "echo \"\${${upper}_$2}\""
}

run() { # run <node> <remote command...>
  local ip
  ip=$(nvar "$1" PUBLIC_IP)
  shift
  ssh "${SSH_OPTS[@]}" "root@${ip}" "$@"
}

declare -A PUBKEY

collect_pubkeys() {
  local n
  for n in ${MESH_NODES}; do
    PUBKEY[$n]=$(run "$n" 'cat /etc/wireguard/publickey')
  done
}

phase_install() {
  local n
  for n in ${MESH_NODES}; do
    run "$n" 'command -v wg >/dev/null 2>&1 || {
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard
      }
      echo "$(hostname): $(wg --version)"'
  done
}

phase_keygen() {
  local n
  for n in ${MESH_NODES}; do
    run "$n" 'umask 077
      mkdir -p /etc/wireguard
      cd /etc/wireguard
      [ -s privatekey ] || wg genkey | tee privatekey | wg pubkey > publickey
      echo "$(hostname) pubkey: $(cat publickey)"'
  done
}

phase_render() {
  collect_pubkeys
  local n p cloud_ip wg_ip peerblocks
  for n in ${MESH_NODES}; do
    cloud_ip=$(nvar "$n" CLOUD_IP)
    wg_ip=$(nvar "$n" WG_IP)
    peerblocks=""
    for p in ${MESH_NODES}; do
      [ "$p" = "$n" ] && continue
      peerblocks+="
[Peer]
# ${p}
PublicKey = ${PUBKEY[$p]}
Endpoint = $(nvar "$p" CLOUD_IP):${WG_PORT}
AllowedIPs = $(nvar "$p" WG_IP)/32
PersistentKeepalive = 25
"
    done
    run "$n" "bash -s" <<REMOTE
set -euo pipefail
DEV=\$(ip -o -4 addr show | awk -v ip='${cloud_ip}/' 'index(\$4, ip)==1 {print \$2; exit}')
[ -n "\$DEV" ] || { echo "ERROR: no interface carries ${cloud_ip}" >&2; exit 1; }
PARENT_MTU=\$(cat "/sys/class/net/\${DEV}/mtu")
WG_MTU=\$(( PARENT_MTU - 80 ))
umask 077
cat > /etc/wireguard/${WG_IFACE}.conf <<CONF
[Interface]
Address = ${wg_ip}/24
ListenPort = ${WG_PORT}
PrivateKey = \$(cat /etc/wireguard/privatekey)
MTU = \${WG_MTU}
${peerblocks}
CONF
echo "\$(hostname): rendered ${WG_IFACE}.conf (parent \${DEV} mtu \${PARENT_MTU} -> wg mtu \${WG_MTU})"
REMOTE
  done
}

phase_firewall() {
  local n cloud_ip
  for n in ${MESH_NODES}; do
    cloud_ip=$(nvar "$n" CLOUD_IP)
    run "$n" "bash -s" <<REMOTE
set -euo pipefail
DEV=\$(ip -o -4 addr show | awk -v ip='${cloud_ip}/' 'index(\$4, ip)==1 {print \$2; exit}')
# Cloud subnet from the routing table, not the address prefix: Hetzner DHCP
# assigns the private IP as /32; the subnet lives in the via-route.
CLOUD_SUBNET=\$(ip -o route show dev "\$DEV" | awk '\$2 == "via" {print \$1; exit}')
[ -n "\$CLOUD_SUBNET" ] || { echo "ERROR: no via-route on \$DEV — cloud subnet underivable" >&2; exit 1; }
ufw allow from "\$CLOUD_SUBNET" to any port ${WG_PORT} proto udp >/dev/null
ufw allow in on ${WG_IFACE} >/dev/null
echo "\$(hostname): ufw ${WG_PORT}/udp from \${CLOUD_SUBNET} + allow in on ${WG_IFACE}"
REMOTE
  done
}

phase_up() {
  local n
  for n in ${MESH_NODES}; do
    run "$n" "systemctl enable wg-quick@${WG_IFACE} >/dev/null 2>&1
      systemctl restart wg-quick@${WG_IFACE}
      echo \"\$(hostname): ${WG_IFACE} up (enabled for boot)\""
  done
}

phase_verify() {
  local fails=0 n p src dst peer out wg_mtu green red
  echo "== all-pairs pings (also triggers fresh handshakes)"
  for n in ${MESH_NODES}; do
    for p in ${MESH_NODES}; do
      [ "$p" = "$n" ] && continue
      peer=$(nvar "$p" WG_IP)
      if out=$(run "$n" "ping -c 4 -q ${peer}" 2>&1); then
        echo "PING ${n}->${p} (${peer}): $(echo "${out}" | grep -E 'rtt|round-trip')"
      else
        echo "PING ${n}->${p} (${peer}): FAILED"
        fails=$((fails + 1))
      fi
    done
  done

  echo "== handshakes"
  for n in ${MESH_NODES}; do
    out=$(run "$n" "wg show ${WG_IFACE} latest-handshakes")
    echo "HANDSHAKES ${n}:"
    echo "${out}"
    if [ "$(echo "${out}" | awk '$2 > 0' | wc -l)" -ne 2 ]; then
      echo "HANDSHAKE-CHECK ${n}: FAILED (expected 2 peers with a handshake)"
      fails=$((fails + 1))
    fi
  done

  echo "== MTU two-color proof (green must pass, red must refuse)"
  for pair in "node1 node2" "node1 node3" "node2 node3"; do
    src=${pair% *}
    dst=${pair#* }
    peer=$(nvar "$dst" WG_IP)
    wg_mtu=$(run "$src" "sed -n 's/^MTU = //p' /etc/wireguard/${WG_IFACE}.conf" | tr -d '[:space:]')
    green=$((wg_mtu - 28))
    red=$((wg_mtu - 27))
    if run "$src" "ping -M do -s ${green} -c 2 -q ${peer}" >/dev/null 2>&1; then
      echo "MTU-GREEN ${src}->${dst}: DF payload ${green} (= wg mtu ${wg_mtu}) passed"
    else
      echo "MTU-GREEN ${src}->${dst}: FAILED (DF payload ${green} did not pass)"
      fails=$((fails + 1))
    fi
    # Red accepts either the sender's local EMSGSIZE or on-path frag-needed.
    if out=$(run "$src" "ping -M do -s ${red} -c 2 -q ${peer}" 2>&1); then
      echo "MTU-RED ${src}->${dst}: FAILED (oversized DF payload ${red} unexpectedly passed)"
      fails=$((fails + 1))
    else
      echo "MTU-RED ${src}->${dst}: oversized DF payload ${red} refused ($(echo "${out}" | grep -ioE 'message too long|frag needed|mtu[= ][0-9]+' | head -1))"
    fi
  done

  echo "== posture artifacts (the fence probe is TCP-only; this covers ${WG_PORT}/udp)"
  for n in ${MESH_NODES}; do
    echo "POSTURE ${n}: ufw status verbose"
    run "$n" "ufw status verbose"
    echo "POSTURE ${n}: ss -ulpn (:${WG_PORT})"
    run "$n" "ss -ulpn | grep ${WG_PORT} || true"
  done

  if [ "${fails}" -ne 0 ]; then
    echo "VERIFY FAILED: ${fails} check(s) red"
    return 1
  fi
  echo "VERIFY OK: all checks passed"
}

save_transcript() {
  local src_file="$1" dest="/root/p2-artifacts/step1-mesh" stamp
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  run node1 "mkdir -p ${dest}"
  scp "${SSH_OPTS[@]}" "${src_file}" \
    "root@$(nvar node1 PUBLIC_IP):${dest}/mesh-verify-${stamp}.txt" >/dev/null
  echo "transcript: node1:${dest}/mesh-verify-${stamp}.txt"
}

run_verify_with_transcript() {
  local tmp rc=0
  tmp=$(mktemp)
  phase_verify 2>&1 | tee "${tmp}" || rc=$?
  save_transcript "${tmp}"
  rm -f "${tmp}"
  return "${rc}"
}

case "${PHASE}" in
  install)  phase_install ;;
  keygen)   phase_keygen ;;
  render)   phase_render ;;
  firewall) phase_firewall ;;
  up)       phase_up ;;
  verify)   run_verify_with_transcript ;;
  all)
    phase_install
    phase_keygen
    phase_render
    phase_firewall
    phase_up
    run_verify_with_transcript
    ;;
  *)
    echo "unknown phase: ${PHASE} (install|keygen|render|firewall|up|verify|all)" >&2
    exit 2
    ;;
esac
