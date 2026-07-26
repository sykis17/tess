"""s10 — Failover visible end-to-end in metrics + a trace.

Requires the opt-in observability overlay (docker-compose.ops-obs.yml). Deterministic:
reject a mutation on the standby (while it is standby), kill the primary so the standby
is promoted, retry the SAME traceparent + request id on the new primary. Then assert on
ARTIFACTS: the promoted node's Prometheus scrape, the worker's :9109 scrape (proves the
prefork exposition of §3a), and the collector's exported spans (one trace_id, two
ops.http.mutation spans sharing ops.request_id, outcomes {fenced_503, success}).

The reject and the success land on the same physical box (cp-b as standby, then as the new
primary) — precisely "rejected on the standby, retried on the new primary". True cross-node
reject/success correlation needs an etcd-only partition and is deferred (WSL2 multi-network
flakiness; see the s04/s08 precedent).
"""

from __future__ import annotations

from .. import docker_util as dk
from .. import observables as obs
from ..harness import ScenarioContext

ID = "s10_failover_visible"
TITLE = "Failover visible in metrics + trace"


def _require_obs(base: str) -> None:
    try:
        obs.scrape_metrics(base)
    except Exception as exc:  # noqa: BLE001
        raise obs.AssertionError_(
            "s10 requires the observability overlay. Bring the stack up with "
            "`-f docker-compose.yml -f docker-compose.ops-ha.yml -f docker-compose.ops-obs.yml` "
            "and export OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml "
            f"(scrape {base}/metrics failed: {exc})"
        )


def run(ctx: ScenarioContext) -> None:
    cfg = ctx.cfg
    topo = ctx.topo
    old_term = topo.pre_fault_term
    primary_name = dk.container_name(cfg, topo.primary_service)
    standby_base = topo.standby_base

    _require_obs(standby_base)
    _require_obs(topo.primary_base)

    # The standby becomes the new primary after we kill the old one.
    standby_id = str(obs.ha(cfg, standby_base).get("instance_id"))

    base_samples = obs.scrape_metrics(standby_base)
    promotes_before = obs.metric_sum(
        base_samples, "tess_ops_role_transitions_total",
        transition="promote", instance_id=standby_id,
    )
    gate_rejects_before = obs.metric_sum(
        base_samples, "tess_ops_fence_rejects_total",
        surface="http_gate", kind="not_primary", instance_id=standby_id,
    )
    fenced_before = obs.metric_sum(
        base_samples, "tess_ops_mutations_total",
        outcome="fenced_503", instance_id=standby_id,
    )
    success_before = obs.metric_sum(
        base_samples, "tess_ops_mutations_total",
        outcome="success", instance_id=standby_id,
    )

    # (a) Worker-exposition proof (§3a): a worker-executed ops task increments a counter
    #     that is scraped on the localhost-published :9109 target.
    _assert_worker_exposition(cfg)

    # (b) Reject on the standby, carrying traceparent T + request id R.
    headers, _trace_id, req_id = obs.gen_trace_headers("s10")
    code, body = obs.mutate_probe(standby_base, token=cfg.admin_token, headers=headers)
    if not obs.is_fence_reject_response(code, body):
        raise obs.AssertionError_(
            f"standby mutate expected fence 503, got {code} body={body}"
        )

    # (c) Kill the primary; wait for the standby to promote.
    dk.docker_stop(primary_name)

    def _promoted():
        try:
            h = obs.ha(cfg, standby_base)
        except Exception:
            return None
        if h.get("role") != "primary":
            return None
        new_term = int(h.get("etcd_fence_term") or h.get("fence_term") or 0)
        return h if new_term > old_term else None

    obs.wait_until(
        _promoted,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="standby promote after kill",
    )

    # (d) Retry the SAME traceparent + request id on the new primary; expect 2xx.
    def _retry_ok():
        code2, body2 = obs.mutate_probe(standby_base, token=cfg.admin_token, headers=headers)
        return (code2, body2) if 200 <= code2 < 300 else None

    obs.wait_until(
        _retry_ok,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="retry succeeds on new primary",
    )

    # (e) Metric assertions on the promoted node.
    def _metrics_ready():
        s = obs.scrape_metrics(standby_base)
        if obs.metric_sum(s, "tess_ops_is_primary", instance_id=standby_id) != 1.0:
            return None
        if obs.metric_sum(s, "tess_ops_fence_term", instance_id=standby_id) <= old_term:
            return None
        if obs.metric_sum(s, "tess_ops_role_transitions_total",
                          transition="promote", instance_id=standby_id) <= promotes_before:
            return None
        if obs.metric_sum(s, "tess_ops_fence_rejects_total",
                          surface="http_gate", kind="not_primary",
                          instance_id=standby_id) <= gate_rejects_before:
            return None
        if obs.metric_sum(s, "tess_ops_mutations_total",
                          outcome="fenced_503", instance_id=standby_id) <= fenced_before:
            return None
        if obs.metric_sum(s, "tess_ops_mutations_total",
                          outcome="success", instance_id=standby_id) <= success_before:
            return None
        return True

    obs.wait_until(
        _metrics_ready,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="failover visible in metrics",
    )

    # (f) Trace continuity: two ops.http.mutation spans sharing request id R + one trace_id,
    #     outcomes {fenced_503, success}. Matched by the unique request id (robust to the
    #     collector's trace_id encoding); the file grows across run-all, so we filter.
    def _trace_ok():
        mutation = [
            sp for sp in obs.read_exported_spans(cfg)
            if sp["name"] == "ops.http.mutation"
            and sp["attrs"].get("ops.request_id") == req_id
        ]
        if len(mutation) < 2:
            return None
        if len({sp["trace_id"] for sp in mutation}) != 1:
            return None
        outcomes = {sp["attrs"].get("ops.outcome") for sp in mutation}
        return mutation if {"fenced_503", "success"} <= outcomes else None

    obs.wait_until(
        _trace_ok,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="failover visible in one trace",
    )

    # (g) Heal: restart the old primary (heal_all also does this best-effort).
    dk.docker_start(primary_name)


def _assert_worker_exposition(cfg) -> None:
    """Enqueue a worker-run ops task; assert the :9109 counter increments (proves §3a).

    worker_task_total increments regardless of which node is primary (the decorator records
    even a NotPrimaryError outcome), so this robustly proves the prefork exposition.
    """
    try:
        before = obs.metric_sum(
            obs.scrape_metrics(cfg.worker_metrics_url),
            "tess_ops_worker_task_total", task="probe",
        )
    except Exception as exc:  # noqa: BLE001
        raise obs.AssertionError_(
            f"worker metrics not reachable at {cfg.worker_metrics_url} — the obs overlay "
            f"must publish it and run the worker at --concurrency=1 (§3a): {exc}"
        )

    worker_cid = dk.container_id(cfg, cfg.worker_service)
    dk._run(
        [
            "docker", "exec", worker_cid, "python", "-c",
            "from app.worker import ops_probe_providers; ops_probe_providers.delay()",
        ],
        check=False,
    )

    def _worker_metric():
        after = obs.metric_sum(
            obs.scrape_metrics(cfg.worker_metrics_url),
            "tess_ops_worker_task_total", task="probe",
        )
        return True if after > before else None

    obs.wait_until(
        _worker_metric,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="worker task metric increment on :9109",
    )
