"""Local driver: docker compose on the harness host — today's behavior, unchanged.

Every method delegates to ``docker_util``, which the seam change leaves byte-identical.
This module is also the package's only sanctioned place to shell out directly: the three
one-shot absorbers use ``docker_util._run`` and ``stream_exec`` owns the one ``Popen``.
Enforced by tests/test_splitbrain_driver_seam.py, so a future fault primitive cannot
quietly reintroduce a bypass that a remote driver would fail to intercept.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from typing import Any, Iterator

from .. import docker_util as dk
from ..config import HarnessConfig
from .base import DriverError


class _PopenStream:
    """StreamHandle over a live ``docker exec``."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc

    def readline(self) -> str:
        assert self._proc.stdout is not None
        return self._proc.stdout.readline()

    def kill(self) -> None:
        self._proc.kill()


class LocalComposeDriver:
    """Fault injection against compose services on this host.

    Deliberately does NOT inherit ``FaultDriver``. Inheriting a Protocol would give every
    un-overridden method a ``...`` body that silently returns ``None``, so a primitive
    added for the remote driver and forgotten here would satisfy every conformance check
    and fail at runtime instead. Structural conformance only.
    """

    def __init__(self, cfg: HarnessConfig) -> None:
        self._assert_single_node(cfg)
        self.cfg = cfg

    @staticmethod
    def _assert_single_node(cfg: HarnessConfig) -> None:
        """Refuse a topology this driver cannot actually reach.

        Every service resolves to a node, and this driver only ever talks to the local
        docker daemon. Accepting a remote node here would run the whole suite against
        localhost while reporting on a cluster — faults injected nowhere, assertions
        passing, and no signal that anything was wrong. Fail closed instead.
        """
        services = (
            *(m.service for m in cfg.etcd_members),
            cfg.web_service,
            cfg.standby_service,
            cfg.redis_service,
            cfg.worker_service,
            cfg.collector_service,
        )
        remote = sorted(
            {s: cfg.node_for(s) for s in services if cfg.node_for(s) != cfg.default_node}.items()
        )
        if remote:
            detail = ", ".join(f"{svc} on node {node!r}" for svc, node in remote)
            raise ValueError(
                f"LocalComposeDriver cannot reach a non-default node ({detail}); "
                f"default_node={cfg.default_node!r}. Use OPS_HA_DRIVER=remote (P2 Step 5b)."
            )

    # --- compose / lifecycle ---
    def compose(self, *compose_cmd: str, check: bool = True) -> str:
        return dk.compose(self.cfg, *compose_cmd, check=check)

    def compose_up(self) -> None:
        dk.compose_up(self.cfg)

    def compose_recreate(self, *services: str) -> None:
        dk.compose_recreate(self.cfg, *services)

    def container_id(self, service: str) -> str:
        return dk.container_id(self.cfg, service)

    def container_name(self, service: str) -> str:
        return dk.container_name(self.cfg, service)

    def docker_stop(self, name: str) -> None:
        dk.docker_stop(name)

    def docker_kill(self, name: str) -> None:
        dk.docker_kill(name)

    def docker_start(self, name: str) -> None:
        dk.docker_start(name)

    def docker_pause(self, name: str) -> None:
        dk.docker_pause(name)

    def docker_unpause(self, name: str) -> None:
        dk.docker_unpause(name)

    # --- network ---
    def docker_inspect_networks(self, name: str) -> dict[str, Any]:
        return dk.docker_inspect_networks(name)

    def default_compose_network(self, service: str) -> str:
        return dk.default_compose_network(self.cfg, service)

    def network_connect(self, network: str, container: str) -> None:
        dk.network_connect(network, container)

    def network_disconnect(self, network: str, container: str) -> None:
        dk.network_disconnect(network, container)

    def ensure_network(self, network: str) -> None:
        dk.ensure_network(network)

    # --- in-container commands ---
    def redis_cli(self, *redis_args: str) -> str:
        return dk.redis_cli(self.cfg, *redis_args)

    def etcdctl(self, service: str, *etcd_args: str) -> str:
        return dk.etcdctl(self.cfg, service, *etcd_args)

    def heal_all(self) -> None:
        dk.heal_all(self.cfg)

    # --- absorbed seam leaks ---
    def inspect_state(self, name: str) -> dict[str, Any]:
        result = dk._run(["docker", "inspect", "-f", "{{json .State}}", name], check=True)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DriverError(f"unparseable state for {name}: {result.stdout!r}") from exc

    def exec_in(self, service: str, args: list[str], *, check: bool = False) -> str:
        cid = self.container_id(service)
        result = dk._run(["docker", "exec", cid, *args], check=check)
        return (result.stdout or "").strip()

    def copy_out(self, service: str, remote_path: str, local_path: str) -> bool:
        cid = self.container_id(service)
        result = dk._run(["docker", "cp", f"{cid}:{remote_path}", local_path], check=False)
        return result.returncode == 0

    @contextmanager
    def stream_exec(self, service: str, args: list[str]) -> Iterator[_PopenStream]:
        # Resolve the container BEFORE the process starts, so entering this context is
        # what costs the compose-ps round trip rather than the caller's listen window.
        cid = self.container_id(service)
        proc = subprocess.Popen(
            ["docker", "exec", "-i", cid, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            yield _PopenStream(proc)
        finally:
            proc.kill()
