"""Fault-driver seam guards for the split-brain harness (P2 Step 5a).

The harness drives fault injection through a ``FaultDriver`` so a later step can swap
the local-compose driver for a remote one without touching scenario logic. Two classes
of guard live here, both no-docker:

**The seam holds.** ``docker_util`` is the ONLY module allowed to shell out, and
``drivers/local.py`` is the only sanctioned consumer of its private ``_run``. Before the
seam, four call sites bypassed ``docker_util`` entirely with raw ``subprocess``
(harness inline ``docker inspect``, an observables SUBSCRIBE ``Popen``, an observables
``docker cp``, an s10 ``docker exec``) — each of those is a primitive the remote driver
would silently fail to intercept. The guard is AST-based on purpose: a substring scan
reds on the word "subprocess" in a docstring and greens on a mis-anchored path.

**The config generalizations behave.** Node addressing, etcd-member majority selection,
and Raft-leader endpoint matching are pure functions here so they can be proven against
topologies (5-member, remote IP endpoints) that no local docker run will ever exercise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.ops_cp_splitbrain.config import EtcdMember, load_config
from scripts.ops_cp_splitbrain.drivers import get_driver
from scripts.ops_cp_splitbrain.drivers.base import FaultDriver
from scripts.ops_cp_splitbrain.drivers.local import LocalComposeDriver
from scripts.ops_cp_splitbrain.observables import match_leader_member

_PKG = Path(__file__).resolve().parents[1] / "scripts" / "ops_cp_splitbrain"

# Modules permitted to shell out. docker_util owns the only subprocess.run in the
# package; drivers/local.py owns the Popen behind stream_exec and is the single
# sanctioned caller of docker_util._run (the three absorbed one-shot leaks).
_SHELL_ALLOWED = {"docker_util.py", "local.py"}


# --- t2: the seam holds -------------------------------------------------------------


def _package_modules() -> list[Path]:
    return sorted(p for p in _PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _shell_out_violations(source: str, label: str) -> list[str]:
    """AST scan: `import subprocess` / `subprocess.X` / `<docker_util alias>._run`.

    Comments and docstrings are invisible to the parser, which is the point — the
    refactor rewrites several comment blocks that mention subprocess by name.
    """
    tree = ast.parse(source)
    # Local aliases bound to the docker_util module, e.g. `from .. import docker_util as dk`.
    dk_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "docker_util":
                    dk_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("docker_util"):
                    dk_aliases.add(alias.asname or alias.name.split(".")[-1])

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    found.append(f"{label}: import subprocess")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                found.append(f"{label}: from subprocess import ...")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "subprocess":
                found.append(f"{label}: subprocess.{node.attr}")
            elif node.value.id in dk_aliases and node.attr.startswith("_"):
                found.append(f"{label}: {node.value.id}.{node.attr}")
    return found


def test_only_docker_util_and_local_driver_shell_out() -> None:
    modules = _package_modules()
    # Non-vacuity floor: 4 package modules + 11 scenarios + 3 drivers + __init__s.
    # If discovery shrinks below this, the path anchor broke and the guard is blind.
    assert len(modules) >= 12, f"discovery went vacuous: {len(modules)} modules"
    violations: list[str] = []
    for path in modules:
        if path.name in _SHELL_ALLOWED:
            continue
        violations.extend(
            _shell_out_violations(path.read_text(encoding="utf-8"), str(path.relative_to(_PKG)))
        )
    assert not violations, "fault primitives must route through the driver seam: " + "; ".join(
        violations
    )


def test_shell_out_guard_trips_on_planted_violation() -> None:
    # Every shape the scan must catch, including the private-_run leak that looks
    # innocuous because it goes "through" docker_util.
    planted = (
        "from .. import docker_util as dk\n"
        "import subprocess\n"
        "def f():\n"
        "    subprocess.check_output(['docker', 'inspect'])\n"
        "    dk._run(['docker', 'cp'])\n"
    )
    found = _shell_out_violations(planted, "planted")
    assert any("import subprocess" in v for v in found)
    assert any("subprocess.check_output" in v for v in found)
    assert any("dk._run" in v for v in found)


def test_docstring_mentioning_subprocess_is_not_a_violation() -> None:
    # The substring guard this replaced would red here; several rewritten comment
    # blocks in observables.py name subprocess explicitly.
    clean = '"""Was a subprocess.Popen SUBSCRIBE before the seam."""\nX = 1\n'
    assert _shell_out_violations(clean, "clean") == []


def test_scenarios_never_reference_ctx_outside_a_ctx_taking_function() -> None:
    """A NameError here costs a full harness run to find.

    Scenarios reach the driver through `ctx.drv`, and scenario helpers take `cfg`, not
    `ctx` — so a mechanical swap of `dk.X(cfg, ...)` to `ctx.drv.X(...)` lands broken
    inside any helper. Nothing at unit level exercises a scenario body, so the only
    other detector is the 25-minute docker gate: s10 failed there with
    "name 'ctx' is not defined" while the other ten scenarios passed, which is precisely
    the kind of narrow, late signal a static check should be catching instead.
    """
    offenders: list[str] = []
    scenarios = sorted((_PKG / "scenarios").glob("s*.py"))
    assert len(scenarios) >= 11, f"discovery went vacuous: {len(scenarios)} scenarios"
    for path in scenarios:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if "ctx" in {a.arg for a in fn.args.args}:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and node.id == "ctx":
                    offenders.append(f"{path.name}:{node.lineno} in {fn.name}()")
    assert not offenders, "ctx referenced where it is not a parameter: " + "; ".join(offenders)


# --- t6: protocol conformance (forward guard for the remote driver) -----------------


def _protocol_members() -> set[str]:
    attrs = getattr(FaultDriver, "__protocol_attrs__", None) or vars(FaultDriver)
    return {name for name in attrs if not name.startswith("_")}


def test_local_driver_defines_every_protocol_member() -> None:
    """Green by construction today — a forward guard, not a regression proof.

    It earns its place in Step 5b: LocalComposeDriver deliberately does NOT inherit
    FaultDriver, so a method added to the protocol and implemented only remotely shows
    up here as an omission instead of as an inherited `...` stub returning None.
    """
    missing = sorted(_protocol_members() - set(vars(LocalComposeDriver)))
    assert not missing, f"LocalComposeDriver is missing protocol members: {missing}"


def test_conformance_check_trips_on_incomplete_driver() -> None:
    class HalfDriver:
        def compose_up(self) -> None:  # one member, everything else absent
            ...

    missing = sorted(_protocol_members() - set(vars(HalfDriver)))
    assert missing, "the conformance check must flag an incomplete driver"


def test_local_driver_does_not_inherit_the_protocol() -> None:
    # Inheriting Protocol would make every un-overridden member a `...` stub that
    # returns None at runtime and satisfies the conformance check forever.
    assert FaultDriver not in LocalComposeDriver.__mro__


# --- t7: config stays hashable (the lru_cache on get_driver depends on it) ----------


def test_harness_config_is_hashable() -> None:
    # get_driver is lru_cached on cfg. An unhashable field (a plain dataclass member,
    # a dict of node overrides) would raise inside the first fault primitive — twenty
    # minutes into a harness run, not at import.
    assert isinstance(hash(load_config()), int)


# --- t3: node addressing is fail-closed under the local driver ----------------------


def test_local_driver_accepts_the_default_node(monkeypatch) -> None:
    monkeypatch.delenv("OPS_HA_DRIVER", raising=False)
    cfg = load_config()
    assert isinstance(get_driver(cfg), LocalComposeDriver)


def test_local_driver_refuses_a_remote_etcd_member(monkeypatch) -> None:
    """etcd is the fault target in 5 of 11 scenarios — the node check must cover it.

    A node_for() that only knew web/standby/redis/worker/collector would exempt every
    etcd service, which is exactly the path Step 5a exists to de-risk.
    """
    monkeypatch.setenv("OPS_HA_ETCD_SERVICES", "node1:etcd-1,etcd-2,etcd-3")
    cfg = load_config()
    with pytest.raises(ValueError, match="node"):
        LocalComposeDriver(cfg)


def test_local_driver_refuses_a_remote_web_node(monkeypatch) -> None:
    monkeypatch.setenv("OPS_HA_WEB_NODE", "node1")
    cfg = load_config()
    with pytest.raises(ValueError, match="node"):
        LocalComposeDriver(cfg)


def test_node_for_resolves_etcd_members_before_the_named_services(monkeypatch) -> None:
    monkeypatch.setenv("OPS_HA_ETCD_SERVICES", "node2:etcd-1,etcd-2")
    cfg = load_config()
    assert cfg.node_for("etcd-1") == "node2"
    assert cfg.node_for("etcd-2") == cfg.default_node
    assert cfg.node_for(cfg.web_service) == cfg.default_node


# --- t5: etcd majority selection ----------------------------------------------------


def _members(n: int) -> tuple[EtcdMember, ...]:
    return tuple(EtcdMember(node="local", service=f"etcd-{i}") for i in range(1, n + 1))


def test_majority_of_three_is_the_first_two(monkeypatch) -> None:
    # Local-identity pin: this must keep picking exactly what etcd_services[:2] picked.
    monkeypatch.setenv("OPS_HA_ETCD_SERVICES", "etcd-1,etcd-2,etcd-3")
    cfg = load_config()
    assert [m.service for m in cfg.etcd_majority_members()] == ["etcd-1", "etcd-2"]


def test_majority_of_five_is_three(monkeypatch) -> None:
    # The case that makes the pin above non-vacuous: [:2] leaves 3 of 5 alive, so
    # quorum survives and s06's "primary must demote" premise silently evaporates.
    monkeypatch.setenv("OPS_HA_ETCD_SERVICES", "etcd-1,etcd-2,etcd-3,etcd-4,etcd-5")
    cfg = load_config()
    assert len(cfg.etcd_majority_members()) == 3


def test_majority_of_one_is_one(monkeypatch) -> None:
    # The offline topology. s11 skips there, but reset/heal paths still enumerate.
    monkeypatch.setenv("OPS_HA_ETCD_SERVICES", "etcd")
    cfg = load_config()
    assert len(cfg.etcd_majority_members()) == 1


# --- t4: Raft-leader endpoint matching ----------------------------------------------


def test_leader_matches_compose_service_endpoint() -> None:
    # The dev shape: endpoints advertise the compose service name.
    members = _members(3)
    assert match_leader_member("http://etcd-2:2379", members) == members[1]


def test_leader_matches_ip_endpoint_via_member_node() -> None:
    """The latent remote break, proven at unit level.

    Real members advertise WG IPs, not compose service names. Matching only on service
    name returns None there, and s11 raises "could not identify etcd raft leader"
    before it ever injects its fault — a scenario that fails for a topology reason
    rather than a product reason.
    """
    members = (
        EtcdMember(node="10.8.0.1", service="etcd-1"),
        EtcdMember(node="10.8.0.2", service="etcd-2"),
        EtcdMember(node="10.8.0.3", service="etcd-3"),
    )
    assert match_leader_member("http://10.8.0.2:2379", members) == members[1]


def test_leader_substring_fallback_still_applies() -> None:
    # Preserved from the pre-seam matcher: a prefixed container endpoint.
    members = _members(3)
    assert match_leader_member("http://tess-engine-etcd-3-1:2379", members) == members[2]


def test_leader_returns_none_for_an_unknown_endpoint() -> None:
    assert match_leader_member("http://192.0.2.99:2379", _members(3)) is None
