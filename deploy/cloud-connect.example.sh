# Example: register AWS + GCP stacks after they are online

# On the control-plane host (.env.prod):
# OPS_AWS_BASE_URL=https://tess-aws.example.com
# OPS_GCP_BASE_URL=https://tess-gcp.example.com
# OPS_ADMIN_TOKEN=change-me

# Force a probe + failover evaluation:
# curl -X POST https://YOUR_CONTROL_PLANE/ops/probe \
#   -H "Authorization: Bearer change-me"

# Comparison run with simulated AWS outage:
# curl -X POST https://YOUR_CONTROL_PLANE/ops/compare \
#   -H "Authorization: Bearer change-me" \
#   -H "Content-Type: application/json" \
#   -d '{"name":"aws-down","inject_chaos":{"prov_aws":"mark_unhealthy"}}'
