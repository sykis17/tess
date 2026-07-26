# Offline OpenTelemetry collector: the verification-only collector with its config
# BAKED IN, so the offline stack needs no host-path bind mount for the config.
#
# Build context is `deploy/` (the repo-root .dockerignore excludes deploy/, so the
# config would be invisible from a repo-root context):
#   docker build -f deploy/offline/otel/Dockerfile -t tess-engine-otel:offline deploy
#
# Pinned to 0.111.0: 0.116.0's distroless binary would not exec on Docker Desktop
# during Step 3. Re-test the newer image on a Linux host and either unpin or keep
# the pin with a verified reason (see deploy/MULTI_CLOUD.md §Observability).
FROM otel/opentelemetry-collector-contrib:0.111.0
COPY otel-collector-config.yaml /etc/otelcol-contrib/config.yaml
