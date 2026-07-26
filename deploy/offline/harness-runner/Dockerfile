# Offline split-brain harness RUNNER.
#
# Under the offline stack both networks are `internal: true`, which (on Docker
# Desktop) blocks container egress but ALSO removes host-loopback published-port
# reachability. So the harness cannot run from the host — it runs from this
# container, attached to `tess-engine_default`, and is driven with CONTAINER
# NAMES, not the compose service alias: verify-egress-blocked.sh injects
# OPS_HA_SMOKE_A/B + OPS_HA_WORKER_METRICS as e.g. `tess-engine-web-1:8000`.
# The `web:8000 / web-standby:8000 / worker:9109` form is illustrative only —
# a post-heal `docker network connect` (s03/s05) restores the container name
# but NOT the service alias, so `web:8000` would stop resolving after a heal.
# The runner drives the daemon through the mounted docker socket.
#
# docker:cli already ships the compose plugin (v2); it only lacks python3, which
# the pure-stdlib harness needs. Nothing here reaches the network at build time
# except the one `apk add` (done on the connected build machine).
#
# Build:  docker build -f deploy/offline/harness-runner/Dockerfile -t tess-engine-harness-runner:offline .
# Run:    see deploy/offline/verify-egress-blocked.sh
FROM docker:cli
RUN apk add --no-cache python3
WORKDIR /work
ENTRYPOINT []
