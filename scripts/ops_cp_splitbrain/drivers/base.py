"""The fault-injection seam: what a driver must provide, and how one is named.

Every fault the harness injects goes through a ``FaultDriver``. The local driver
delegates to ``docker_util`` (compose on this host); Step 5b adds a remote driver that
reaches each cluster node's dockerd over SSH and cuts links with firewall rules.

Two shape decisions worth knowing before implementing another driver:

**Methods take no ``cfg``.** ``docker_util`` today splits its calling convention — some
functions take the config, the lifecycle and network verbs take a bare container name.
That cannot survive a multi-node topology, where *every* primitive must know which
node's dockerd to reach. Drivers bind the config at construction instead.

**The four absorbers exist because the seam leaked.** Before Step 5a, four call sites
shelled out directly (an inline ``docker inspect`` for container state, a SUBSCRIBE
``Popen``, a ``docker cp``, and a ``docker exec``). Each is a real primitive a remote
driver has to intercept, so each became a protocol method rather than a special case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ContextManager, Protocol, runtime_checkable

from .. import docker_util

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import HarnessConfig


# The error every driver raises for a failed primitive. Deliberately an ALIAS of
# docker_util.DockerError rather than a new base class with DockerError re-parented
# under it: docker_util.py stays byte-identical through the seam change (that diff being
# empty is the merge proof), so it cannot be edited to inherit from anything new. Remote
# drivers raise this same class, which keeps every `except DriverError` site honest.
DriverError = docker_util.DockerError


class UnknownDriverError(ValueError):
    """Raised for an unrecognized OPS_HA_DRIVER value — never a silent fallback."""


#: Driver names accepted by ``OPS_HA_DRIVER``. ``remote`` is accepted as a NAME here and
#: refused at construction until Step 5b lands it — rejecting the name outright would
#: make the documented ``local|remote`` value set a lie, while accepting it silently as
#: local would drive this laptop's docker while the operator believes they are driving
#: the cluster. That second failure is the one this whole seam exists to prevent.
DRIVER_NAMES = ("local", "remote")


def resolve_driver_name(raw: str | None) -> str:
    """Normalize and validate an ``OPS_HA_DRIVER`` value.

    Absent, empty, or whitespace folds to ``local``: verify-egress-blocked.sh clears
    harness env with the ``-e VAR=`` idiom, and an empty value there means "default",
    not "fail the certification chain".
    """
    # Strip BEFORE folding: a whitespace-only value is an empty value, and `-e VAR=` in
    # a shell heredoc has been known to arrive as " ".
    name = (raw or "").strip().lower() or "local"
    if name not in DRIVER_NAMES:
        raise UnknownDriverError(
            f"unknown OPS_HA_DRIVER={raw!r} (resolved {name!r}); expected one of "
            f"{', '.join(DRIVER_NAMES)}"
        )
    return name


class StreamHandle(Protocol):
    """A live output stream from a long-running in-container command."""

    def readline(self) -> str: ...

    def kill(self) -> None: ...


@runtime_checkable
class FaultDriver(Protocol):
    """Every fault primitive the harness can inject, bound to one topology."""

    # --- compose / lifecycle ---
    def compose(self, *compose_cmd: str, check: bool = True) -> str: ...

    def compose_up(self) -> None: ...

    def compose_recreate(self, *services: str) -> None: ...

    def container_id(self, service: str) -> str: ...

    def container_name(self, service: str) -> str: ...

    def docker_stop(self, name: str) -> None: ...

    def docker_kill(self, name: str) -> None: ...

    def docker_start(self, name: str) -> None: ...

    def docker_pause(self, name: str) -> None: ...

    def docker_unpause(self, name: str) -> None: ...

    # --- network ---
    def docker_inspect_networks(self, name: str) -> dict[str, Any]: ...

    def default_compose_network(self, service: str) -> str: ...

    def network_connect(self, network: str, container: str) -> None: ...

    def network_disconnect(self, network: str, container: str) -> None: ...

    def ensure_network(self, network: str) -> None: ...

    # --- in-container commands ---
    def redis_cli(self, *redis_args: str) -> str: ...

    def etcdctl(self, service: str, *etcd_args: str) -> str: ...

    def heal_all(self) -> None: ...

    # --- absorbed seam leaks ---
    def inspect_state(self, name: str) -> dict[str, Any]:
        """Container ``State`` (Status/Paused/…) — the baseline-cleanliness check."""
        ...

    def exec_in(self, service: str, args: list[str], *, check: bool = False) -> str:
        """One-shot command inside a service's container; returns stdout."""
        ...

    def copy_out(self, service: str, remote_path: str, local_path: str) -> bool:
        """Copy a file out of a container to the harness host. False if unavailable."""
        ...

    def stream_exec(self, service: str, args: list[str]) -> ContextManager[StreamHandle]:
        """Long-running command whose output is read line by line while it runs.

        Enter the context in the caller's main thread: the container resolution it
        performs can take a second or more, and callers time their actions against the
        stream being live (see observables.peek_provider_changed).
        """
        ...
