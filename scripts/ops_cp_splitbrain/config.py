"""Central harness config — timeouts derived from lease TTL, not magic numbers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import NamedTuple


class EtcdMember(NamedTuple):
    """One etcd member: which node it runs on, and its compose service name.

    A NamedTuple (not a plain dataclass) on purpose — ``HarnessConfig`` is frozen and
    hashable, and ``drivers.get_driver`` is ``lru_cache``d on it. A mutable member type
    would set ``__hash__ = None`` on the tuple field and blow up inside the first fault
    primitive of a run rather than at import.
    """

    node: str
    service: str


@dataclass(frozen=True)
class HarnessConfig:
    cp_a: str
    cp_b: str
    admin_token: str
    lease_ttl_seconds: int
    convergence_timeout: float
    poll_interval: float
    compose_files: tuple[str, ...]
    project_name: str
    redis_service: str
    etcd_members: tuple[EtcdMember, ...]
    web_service: str
    standby_service: str
    redis_only_network: str
    second_provider_name: str
    second_provider_base_url: str
    # Which backend is authoritative for durable CP writes in the running stack. Mirrors
    # the web container's OPS_FENCE_AUTHORITY (compose interpolates the same harness-shell
    # env), so the durable observables read the store that actually holds the truth. See
    # deploy/MULTI_CLOUD.md §Control-plane HA and the step-5 env gotchas.
    fence_authority: str
    # Observability (s10 only; requires the opt-in docker-compose.ops-obs.yml overlay).
    worker_service: str
    worker_metrics_url: str
    collector_service: str
    spans_file: str
    # Fault-injection backend: "local" (docker compose on this host) or "remote"
    # (P2 Step 5b). Validated at load time — see drivers.resolve_driver_name.
    driver_name: str
    # Node addressing. Every service resolves to a node; the local driver refuses any
    # node that is not `default_node`, so a half-configured remote topology fails closed
    # instead of silently driving localhost. etcd nodes live on the members above.
    default_node: str
    web_node: str
    standby_node: str
    redis_node: str
    worker_node: str
    collector_node: str

    @property
    def compose_args(self) -> list[str]:
        args: list[str] = []
        for path in self.compose_files:
            args.extend(["-f", path])
        if self.project_name:
            args.extend(["-p", self.project_name])
        return args

    @property
    def etcd_services(self) -> tuple[str, ...]:
        """Compose service names of the etcd members, in configured order.

        Derived, not stored: ``docker_util.heal_all`` and the observables' etcd helpers
        read this attribute, and ``docker_util.py`` is deliberately untouched by the
        driver seam (byte-identical is the merge proof).
        """
        return tuple(member.service for member in self.etcd_members)

    def node_for(self, service: str) -> str:
        """Which node a compose service runs on.

        etcd members are consulted FIRST: etcd is the fault target in five of the eleven
        scenarios, so a lookup that only knew the named services would silently exempt
        exactly the path the driver seam exists to make explicit.
        """
        for member in self.etcd_members:
            if member.service == service:
                return member.node
        named = {
            self.web_service: self.web_node,
            self.standby_service: self.standby_node,
            self.redis_service: self.redis_node,
            self.worker_service: self.worker_node,
            self.collector_service: self.collector_node,
        }
        return named.get(service, self.default_node)

    def etcd_majority_members(self) -> tuple[EtcdMember, ...]:
        """The members whose loss costs the cluster quorum (s06 stops exactly these)."""
        return self.etcd_members[:2]


def _parse_etcd_members(raw: str, default_node: str) -> tuple[EtcdMember, ...]:
    """Parse ``OPS_HA_ETCD_SERVICES``.

    Accepts today's plain ``etcd-1,etcd-2,etcd-3`` (every member on the default node)
    and the ``node:service`` form a multi-node topology needs.
    """
    members: list[EtcdMember] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            node, _, service = entry.partition(":")
            members.append(EtcdMember(node=node.strip() or default_node, service=service.strip()))
        else:
            members.append(EtcdMember(node=default_node, service=entry))
    return tuple(members)


def load_config() -> HarnessConfig:
    # Deferred import: drivers -> docker_util -> config would close an import cycle at
    # module scope. By call time every module is initialized.
    from .drivers.base import resolve_driver_name

    ttl = max(5, int(os.environ.get("OPS_ETCD_LEASE_TTL_SECONDS", "10")))
    # Plan: CONVERGENCE_TIMEOUT = 3 × lease_TTL (WSL2 jitter included).
    convergence = float(os.environ.get("OPS_HA_CONVERGENCE_TIMEOUT", str(3 * ttl)))
    # ops-obs.yml is opt-in (default empty) so the existing 2-file stack is unchanged;
    # the s10 verification sets OPS_HA_COMPOSE_OBS=docker-compose.ops-obs.yml.
    compose_files = tuple(
        f
        for f in (
            os.environ.get("OPS_HA_COMPOSE_BASE", "docker-compose.yml"),
            os.environ.get("OPS_HA_COMPOSE_OVERLAY", "docker-compose.ops-ha.yml"),
            os.environ.get("OPS_HA_COMPOSE_OBS", ""),
        )
        if f
    )
    # `or` rather than a get() default: verify-egress-blocked.sh clears harness env with
    # the `-e VAR=` idiom, and an empty value must mean "default", not "fail closed".
    default_node = (os.environ.get("OPS_HA_DEFAULT_NODE") or "local").strip()
    return HarnessConfig(
        cp_a=os.environ.get("OPS_HA_SMOKE_A", "http://127.0.0.1:8000"),
        cp_b=os.environ.get("OPS_HA_SMOKE_B", "http://127.0.0.1:8001"),
        admin_token=os.environ.get("OPS_ADMIN_TOKEN", "ha-harness-token"),
        lease_ttl_seconds=ttl,
        convergence_timeout=convergence,
        poll_interval=float(os.environ.get("OPS_HA_POLL_INTERVAL", "1.0")),
        compose_files=compose_files,
        project_name=os.environ.get("OPS_HA_COMPOSE_PROJECT", "tess-engine"),
        redis_service=os.environ.get("OPS_HA_REDIS_SERVICE", "redis"),
        etcd_members=_parse_etcd_members(
            os.environ.get("OPS_HA_ETCD_SERVICES", "etcd-1,etcd-2,etcd-3"), default_node
        ),
        web_service=os.environ.get("OPS_HA_WEB_SERVICE", "web"),
        standby_service=os.environ.get("OPS_HA_STANDBY_SERVICE", "web-standby"),
        redis_only_network=os.environ.get("OPS_HA_REDIS_NETWORK", "ops-ha-redis"),
        second_provider_name="ha-harness-secondary",
        second_provider_base_url=os.environ.get(
            "OPS_HA_SECOND_PROVIDER_BASE_URL", "http://127.0.0.1:18099"
        ),
        fence_authority=os.environ.get("OPS_FENCE_AUTHORITY", "etcd").strip().lower(),
        worker_service=os.environ.get("OPS_HA_WORKER_SERVICE", "worker"),
        worker_metrics_url=os.environ.get("OPS_HA_WORKER_METRICS", "http://127.0.0.1:9109"),
        collector_service=os.environ.get("OPS_HA_COLLECTOR_SERVICE", "otel-collector"),
        spans_file=os.environ.get("OPS_HA_SPANS_FILE", "/spans/spans.json"),
        driver_name=resolve_driver_name(os.environ.get("OPS_HA_DRIVER")),
        default_node=default_node,
        web_node=(os.environ.get("OPS_HA_WEB_NODE") or default_node).strip(),
        standby_node=(os.environ.get("OPS_HA_STANDBY_NODE") or default_node).strip(),
        redis_node=(os.environ.get("OPS_HA_REDIS_NODE") or default_node).strip(),
        worker_node=(os.environ.get("OPS_HA_WORKER_NODE") or default_node).strip(),
        collector_node=(os.environ.get("OPS_HA_COLLECTOR_NODE") or default_node).strip(),
    )
