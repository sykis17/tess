# Offline split-brain harness RUNNER.
#
# Under the offline stack both networks are `internal: true`, which (on Docker
# Desktop) blocks container egress but ALSO removes host-loopback published-port
# reachability. So the harness cannot run from the host — it runs from this
# container, attached to `tess-engine_default`, reaching services by name
# (web:8000 / web-standby:8000 / worker:9109 via OPS_HA_SMOKE_A/B +
# OPS_HA_WORKER_METRICS) and driving the daemon through the mounted docker socket.
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
