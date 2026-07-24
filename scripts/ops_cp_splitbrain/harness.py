"""Scenario lifecycle: reset → clean baseline → seed → run → heal."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .config import HarnessConfig, load_config
from . import docker_util as dk
from . import observables as obs


@dataclass
class ScenarioContext:
    cfg: HarnessConfig
    topo: obs.Topology
    other_provider_id: str | None
    active_provider_id: str | None


ScenarioFn = Callable[[ScenarioContext], None]


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    passed: bool
    detail: str
    elapsed_s: float


def reset_stack(cfg: HarnessConfig) -> None:
    """Restore known-clean state: heal faults, recreate CP+etcd, flush Redis keys."""
    dk.heal_all(cfg)
    # Recreate etcd + webs so lease state is fresh; keep redis but wipe CP keys.
    try:
        dk.compose_recreate(
            cfg,
            cfg.etcd_service,
            cfg.web_service,
            cfg.standby_service,
        )
    except dk.DockerError:
        # Stack may not be up yet.
        dk.compose_up(cfg)

    # Ensure redis is up and wipe fencing keys (scenario isolation).
    try:
        redis_name = dk.container_name(cfg, cfg.redis_service)
        dk.docker_start(redis_name)
    except dk.DockerError:
        dk.compose(cfg, "up", "-d", cfg.redis_service, check=False)

    time.sleep(2.0)
    try:
        obs.redis_del(cfg, obs.REDIS_FENCE_KEY, obs.REDIS_BLOB_KEY)
    except Exception:
        # Redis may still be starting; retry once after compose up.
        dk.compose_up(cfg)
        time.sleep(3.0)
        obs.redis_del(cfg, obs.REDIS_FENCE_KEY, obs.REDIS_BLOB_KEY)

    # Ensure redis-only network exists and webs/redis are attached (scenario 4).
    try:
        dk.ensure_network(cfg.redis_only_network)
        for service in (cfg.redis_service, cfg.web_service, cfg.standby_service):
            name = dk.container_name(cfg, service)
            if cfg.redis_only_network not in dk.docker_inspect_networks(name):
                dk.network_connect(cfg.redis_only_network, name)
    except dk.DockerError:
        pass


def verify_clean_baseline(cfg: HarnessConfig) -> obs.Topology:
    """Assert single primary, redis fence+blob consistent, no leftover faults."""
    # No paused containers among CP services.
    for service in (cfg.web_service, cfg.standby_service, cfg.etcd_service, cfg.redis_service):
        name = dk.container_name(cfg, service)
        # Status via inspect State.Status
        import json
        import subprocess

        raw = subprocess.check_output(
            ["docker", "inspect", "-f", "{{json .State}}", name],
            text=True,
        )
        state = json.loads(raw)
        if state.get("Status") != "running" or state.get("Paused"):
            raise obs.AssertionError_(
                f"baseline unclean: {service} state={state}"
            )

    topo = obs.wait_single_primary(cfg)
    # After wipe, primary should re-promote and persist blob.
    def _blob_ready() -> bool:
        fence = obs.redis_fence_term(cfg)
        blob = obs.redis_blob(cfg)
        return fence > 0 and blob is not None

    obs.wait_until(
        _blob_ready,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label="redis fence+blob after election",
    )
    fence = obs.redis_fence_term(cfg)
    # Primary reported term should match redis (allow cached lag of 0 on first poll).
    a, b = obs.ha_both(cfg)
    reported = max(
        int(a.get("fence_term") or 0),
        int(b.get("fence_term") or 0),
        int(a.get("etcd_fence_term") or 0),
        int(b.get("etcd_fence_term") or 0),
    )
    if reported and fence and reported > fence + 1:
        raise obs.AssertionError_(
            f"baseline term skew reported={reported} redis={fence} a={a} b={b}"
        )
    n, a, b = obs.count_primaries(cfg)
    if n != 1:
        raise obs.AssertionError_(f"baseline dual/zero primary a={a} b={b}")
    return topo


def seed_second_provider(cfg: HarnessConfig, topo: obs.Topology) -> tuple[str | None, str]:
    """Ensure two providers exist; return (other_id, active_id)."""
    providers = obs.list_providers(topo.primary_base, token=cfg.admin_token)
    active = obs.active_provider_id(cfg)
    if active is None and providers:
        active = providers[0]["id"]

    harness_providers = [p for p in providers if "ha-harness" in (p.get("tags") or [])]
    other = None
    for p in providers:
        if p["id"] != active:
            other = p["id"]
            break
    if other is None:
        created = obs.create_provider(
            topo.primary_base,
            token=cfg.admin_token,
            name=cfg.second_provider_name,
            base_url=cfg.second_provider_base_url,
        )
        other = created["id"]
        # Re-read active after persist
        active = obs.active_provider_id(cfg) or active
    elif not harness_providers and other == active:
        created = obs.create_provider(
            topo.primary_base,
            token=cfg.admin_token,
            name=cfg.second_provider_name,
            base_url=cfg.second_provider_base_url,
        )
        other = created["id"]

    if not other or not active or other == active:
        # Force create distinct other
        created = obs.create_provider(
            topo.primary_base,
            token=cfg.admin_token,
            name=f"{cfg.second_provider_name}-{int(time.time())}",
            base_url=cfg.second_provider_base_url,
        )
        other = created["id"]
        active = obs.active_provider_id(cfg) or active

    if other == active:
        raise obs.AssertionError_(
            f"failed to seed distinct second provider active={active} other={other}"
        )
    return other, str(active)


def prepare_scenario(cfg: HarnessConfig) -> ScenarioContext:
    reset_stack(cfg)
    topo = verify_clean_baseline(cfg)
    other, active = seed_second_provider(cfg, topo)
    # Refresh topo after seed (term may bump on persist).
    topo = obs.wait_single_primary(cfg)
    return ScenarioContext(
        cfg=cfg,
        topo=topo,
        other_provider_id=other,
        active_provider_id=active,
    )


def run_scenario(
    scenario_id: str,
    title: str,
    fn: ScenarioFn,
    *,
    cfg: HarnessConfig | None = None,
) -> ScenarioResult:
    cfg = cfg or load_config()
    t0 = time.time()
    try:
        ctx = prepare_scenario(cfg)
        fn(ctx)
        # Heal leftovers so next scenario's reset is cheaper / safer.
        dk.heal_all(cfg)
        return ScenarioResult(
            scenario_id=scenario_id,
            title=title,
            passed=True,
            detail="PASS",
            elapsed_s=time.time() - t0,
        )
    except Exception as exc:
        try:
            dk.heal_all(cfg)
        except Exception:
            pass
        return ScenarioResult(
            scenario_id=scenario_id,
            title=title,
            passed=False,
            detail=f"FAIL: {exc}",
            elapsed_s=time.time() - t0,
        )
