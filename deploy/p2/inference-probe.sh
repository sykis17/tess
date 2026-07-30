#!/usr/bin/env bash
# P2 per-node inference probe — the committed instrument behind every serving
# node's published t/s number (docs/P2_OPENER.md §(a) as-built; never assume
# class = performance, probe every node individually).
#
# Runs ON the node (ship via scp or run from the node's /opt/tess-engine
# clone). Starts the prod compose ollama service alone via its profile
# (deploy/deploy.sh precedent), then runs seven fixed shapes and a
# 2-concurrent pair. Every request JSON is saved alongside its response
# (probe-<name>.request.json / probe-<name>.json) so no probe ever needs
# prompt reconstruction again — the Step 1 node2 lesson.
#
# Usage: bash deploy/p2/inference-probe.sh [outdir]
#   outdir default: /root/p2-artifacts/step1-probe
set -euo pipefail

OUTDIR="${1:-/root/p2-artifacts/step1-probe}"
cd /opt/tess-engine
[ -f .env.prod ] || cp .env.prod.example .env.prod
docker compose --profile ollama --env-file .env.prod -f docker-compose.prod.yml up -d ollama </dev/null 2>&1 | tail -1
echo "== ensuring llama3.2 present (pinned)"
# </dev/null is load-bearing: a stdin-attached exec inside an ssh-fed script
# eats the script's own tail (P2 Step 1, CR-11 materialized).
docker compose --profile ollama --env-file .env.prod -f docker-compose.prod.yml exec -T ollama ollama pull llama3.2 </dev/null 2>&1 | tail -1
CIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tess-engine-ollama-1)
echo "ollama container IP: ${CIP}"
for i in $(seq 1 30); do
  curl -sf "http://${CIP}:11434/api/tags" >/dev/null && break
  sleep 2
done
mkdir -p "${OUTDIR}"

gen() { # gen <name> <request-json>  — saves request AND response
  printf '%s' "$2" > "${OUTDIR}/$1.request.json"
  curl -s "http://${CIP}:11434/api/generate" -d "$2" > "${OUTDIR}/$1.json"
}

P_SHORT='{"model":"llama3.2","prompt":"What is the chemical formula of table salt, and why does it dissolve in water? Answer briefly in a few sentences.","stream":false}'
P_MED='{"model":"llama3.2","prompt":"Explain ionic bonding: how it forms between atoms, what holds the ions together, and give one everyday example. About two paragraphs.","stream":false}'
P_LONG='{"model":"llama3.2","prompt":"Explain in detail how consensus algorithms such as Raft prevent split-brain scenarios in distributed systems, covering leader election, quorum, and log replication.","stream":false}'
P_CODE='{"model":"llama3.2","prompt":"Write a Python function calculate_median(data) with a docstring that computes the median of a list of numbers.","stream":false}'
P_CONCA='{"model":"llama3.2","prompt":"Explain how etcd lease-based leader election works, including lease TTLs and what happens when the current leader fails.","stream":false}'
P_CONCB='{"model":"llama3.2","prompt":"Describe WebSocket reconnection strategies for a web client, including exponential backoff and resuming interrupted sessions.","stream":false}'

echo "== sequential probes (first request captures cold load)"
gen probe-short-factual "$P_SHORT"
gen probe-medium-explainer "$P_MED"
gen probe-long-explainer "$P_LONG"
gen probe-long-repeat "$P_LONG"
gen probe-code "$P_CODE"

echo "== concurrent pair"
t0=$(date +%s)
gen probe-conc-A "$P_CONCA" &
pidA=$!
gen probe-conc-B "$P_CONCB" &
pidB=$!
wait $pidA $pidB
t1=$(date +%s)
echo "concurrent pair wall: $((t1-t0))s"

echo "== metrics summary ($(hostname), outdir ${OUTDIR})"
OUTDIR="${OUTDIR}" python3 - <<'PYEOF'
import json, glob, os
outdir = os.environ["OUTDIR"]
for f in sorted(glob.glob(outdir + "/probe-*.json")):
    if f.endswith(".request.json"):
        continue
    d = json.load(open(f))
    ec, ed = d.get("eval_count", 0), d.get("eval_duration", 1)
    pc, pd = d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 1)
    name = f.rsplit("/", 1)[-1]
    print(f"{name}: gen {ec} tok @ {ec/ed*1e9:.1f} t/s | prompt {pc} tok @ {pc/pd*1e9:.0f} t/s | total {d.get('total_duration',0)/1e9:.1f}s | load {d.get('load_duration',0)/1e9:.1f}s")
PYEOF
echo "PROBE-DONE $(hostname)"
