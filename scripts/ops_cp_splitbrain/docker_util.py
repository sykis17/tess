"""Docker / compose helpers for fault injection."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .config import HarnessConfig


class DockerError(RuntimeError):
    pass


def _run(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: float | None = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        check=False,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise DockerError(
            f"cmd failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    return result


def compose(cfg: HarnessConfig, *compose_cmd: str, check: bool = True) -> str:
    args = ["docker", "compose", *cfg.compose_args, *compose_cmd]
    result = _run(args, check=check)
    return (result.stdout or "").strip()


def compose_up(cfg: HarnessConfig) -> None:
    compose(cfg, "up", "--build", "-d", check=True)


def compose_recreate(cfg: HarnessConfig, *services: str) -> None:
    targets = list(services) if services else []
    args = ["up", "-d", "--force-recreate", "--no-deps"]
    if targets:
        args.extend(targets)
    else:
        args = ["up", "-d", "--force-recreate"]
    compose(cfg, *args, check=True)


def container_id(cfg: HarnessConfig, service: str) -> str:
    out = compose(cfg, "ps", "-q", service, check=True)
    if not out:
        raise DockerError(f"no container for service={service!r}")
    return out.splitlines()[0].strip()


def container_name(cfg: HarnessConfig, service: str) -> str:
    """Resolve a compose service to its docker CONTAINER NAME.

    The harness addresses nodes by container name rather than the compose
    service alias on purpose: a partition-heal ``docker network connect``
    (s03/s05, see ``heal_all`` below) restores the container name but NOT the
    service alias, so ``web:8000`` can stop resolving after a heal while
    ``tess-engine-web-1:8000`` keeps working. Offline runs (internal networks,
    no published ports) depend on this — see deploy/MULTI_CLOUD.md
    §Offline packaging.
    """
    cid = container_id(cfg, service)
    result = _run(["docker", "inspect", "-f", "{{.Name}}", cid], check=True)
    name = (result.stdout or "").strip().lstrip("/")
    if not name:
        raise DockerError(f"empty name for service={service}")
    return name


def docker_stop(name: str) -> None:
    _run(["docker", "stop", name], check=False)


def docker_kill(name: str) -> None:
    """SIGKILL (ungraceful). For etcd, this is deliberately harsher than ``docker_stop``:
    SIGTERM lets etcd transfer leadership before dying (near-zero gap), so killing the
    RAFT LEADER ungracefully is what actually forces a re-election gap the survivors must
    ride through (see s11)."""
    _run(["docker", "kill", name], check=False)


def docker_start(name: str) -> None:
    _run(["docker", "start", name], check=True)


def docker_pause(name: str) -> None:
    _run(["docker", "pause", name], check=True)


def docker_unpause(name: str) -> None:
    _run(["docker", "unpause", name], check=True)


def docker_inspect_networks(name: str) -> dict[str, Any]:
    result = _run(["docker", "inspect", name], check=True)
    data = json.loads(result.stdout)[0]
    return data.get("NetworkSettings", {}).get("Networks", {}) or {}


def default_compose_network(cfg: HarnessConfig, service: str) -> str:
    """Discover the primary compose network attached to a service container."""
    name = container_name(cfg, service)
    nets = docker_inspect_networks(name)
    if not nets:
        raise DockerError(f"no networks on {name}")
    # Prefer project-prefixed default network.
    preferred = f"{cfg.project_name}_default"
    if preferred in nets:
        return preferred
    for net_name in nets:
        if net_name.endswith("_default") or "default" in net_name:
            return net_name
    return next(iter(nets))


def network_disconnect(network: str, container: str) -> None:
    _run(["docker", "network", "disconnect", "-f", network, container], check=False)


def network_connect(network: str, container: str) -> None:
    _run(["docker", "network", "connect", network, container], check=False)


def ensure_network(network: str) -> None:
    listed = _run(["docker", "network", "ls", "--format", "{{.Name}}"], check=True)
    names = set((listed.stdout or "").split())
    if network not in names:
        _run(["docker", "network", "create", network], check=True)


def redis_cli(cfg: HarnessConfig, *redis_args: str) -> str:
    cid = container_id(cfg, cfg.redis_service)
    result = _run(["docker", "exec", cid, "redis-cli", *redis_args], check=True)
    return (result.stdout or "").strip()


def etcdctl(cfg: HarnessConfig, service: str, *etcd_args: str) -> str:
    """Run etcdctl (v3 API) inside an etcd member container."""
    cid = container_id(cfg, service)
    result = _run(
        ["docker", "exec", "-e", "ETCDCTL_API=3", cid, "etcdctl", *etcd_args],
        check=True,
    )
    return (result.stdout or "").strip()


def heal_all(cfg: HarnessConfig) -> None:
    """Best-effort: unpause/start CP services, reconnect networks, start etcd/redis."""
    for service in (
        *cfg.etcd_services,
        cfg.redis_service,
        cfg.web_service,
        cfg.standby_service,
    ):
        try:
            name = container_name(cfg, service)
        except DockerError:
            continue
        _run(["docker", "unpause", name], check=False)
        _run(["docker", "start", name], check=False)
        # Reconnect to default compose network if missing.
        try:
            net = default_compose_network(cfg, service)
        except DockerError:
            continue
        nets = docker_inspect_networks(name)
        if net not in nets:
            network_connect(net, name)
        # Redis-only network for web/redis if defined.
        if service in (cfg.web_service, cfg.standby_service, cfg.redis_service):
            if cfg.redis_only_network not in docker_inspect_networks(name):
                try:
                    ensure_network(cfg.redis_only_network)
                    network_connect(cfg.redis_only_network, name)
                except DockerError:
                    pass
