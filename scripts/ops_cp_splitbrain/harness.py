"""Scenario lifecycle: reset → clean baseline → seed → run → heal."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .config import HarnessConfig, load_config
from .drivers import DriverError, FaultDriver, get_driver
from . import observables as obs


@dataclass
class ScenarioContext:
    cfg: HarnessConfig
    topo: obs.Topology
    other_provider_id: str | None
    active_provider_id: str | None
    # Every fault a scenario injects goes through here, so the same scenario body runs
    # against local compose or a remote cluster without knowing which.
    drv: FaultDriver


ScenarioFn = Callable[[ScenarioContext], None]


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    passed: bool
    detail: str
    elapsed_s: float
    # Explicit topology skip (e.g. s11 on single-node etcd): neither PASS nor FAIL,
    # always reported with its reason in `detail` — never silently absent.
    skipped: bool = False


def reset_stack(cfg: HarnessConfig) -> None:
    """Restore known-clean state: heal faults, recreate CP+etcd, flush Redis keys."""
    drv = get_driver(cfg)
    drv.heal_all()
    # Recreate etcd members + webs so lease state is fresh; keep redis but wipe CP keys.
    try:
        drv.compose_recreate(
            *cfg.etcd_services,
            cfg.web_service,
            cfg.standby_service,
        )
        # A --no-deps recreate SUCCEEDS from a fully torn-down project while creating
        # only the CP+etcd services — worker/otel-collector then don't exist and s10
        # fails on worker-metrics reachability. Worker is the sentinel (it exists in
        # every compose file set and is never recreated above): no container -> fall
        # through to the full up.
        drv.container_name(cfg.worker_service)
    except DriverError:
        # Stack may not be up yet (or only partially, from a torn-down start).
        drv.compose_up()

    # Ensure redis is up and wipe fencing keys (scenario isolation).
    try:
        redis_name = drv.container_name(cfg.redis_service)
        drv.docker_start(redis_name)
    except DriverError:
        drv.compose("up", "-d", cfg.redis_service, check=False)

    time.sleep(2.0)
    try:
        obs.redis_del(cfg, obs.REDIS_FENCE_KEY, obs.REDIS_BLOB_KEY)
    except Exception:
        # Redis may still be starting; retry once after compose up.
        drv.compose_up()
        time.sleep(3.0)
        obs.redis_del(cfg, obs.REDIS_FENCE_KEY, obs.REDIS_BLOB_KEY)

    # Prepared for the etcd cutover (steps 4-5): drop the etcd durable blob so a
    # scenario starts clean, while the monotonic term persists in the etcd volumes
    # (wiping the volumes would reset the term to 0 and mask monotonicity checks).
    # No-op until EtcdFenceStore is authoritative — the key is unwritten today.
    try:
        obs.etcd_del_blob(cfg)
    except Exception:
        pass

    # Ensure redis-only network exists and webs/redis are attached (scenario 4).
    try:
        drv.ensure_network(cfg.redis_only_network)
        for service in (cfg.redis_service, cfg.web_service, cfg.standby_service):
            name = drv.container_name(service)
            if cfg.redis_only_network not in drv.docker_inspect_networks(name):
                drv.network_connect(cfg.redis_only_network, name)
    except DriverError:
        pass


def verify_clean_baseline(cfg: HarnessConfig) -> obs.Topology:
    """Assert single primary, redis fence+blob consistent, no leftover faults."""
    drv = get_driver(cfg)
    # No paused containers among CP services.
    for service in (cfg.web_service, cfg.standby_service, *cfg.etcd_services, cfg.redis_service):
        name = drv.container_name(service)
        state = drv.inspect_state(name)
        if state.get("Status") != "running" or state.get("Paused"):
            raise obs.AssertionError_(
                f"baseline unclean: {service} state={state}"
            )

    topo = obs.wait_single_primary(cfg)
    # After wipe, primary should re-promote and persist blob to the AUTHORITATIVE store
    # (etcd post-cutover; Redis otherwise). Watching the wrong backend would either hang
    # (etcd authority, empty Redis) or pass vacuously — so key off cfg.fence_authority.
    def _blob_ready() -> bool:
        fence = obs.durable_fence_term(cfg)
        blob = obs.durable_blob(cfg)
        return fence > 0 and blob is not None

    obs.wait_until(
        _blob_ready,
        timeout=cfg.convergence_timeout,
        poll=cfg.poll_interval,
        label=f"durable[{cfg.fence_authority}] fence+blob after election",
    )
    fence = obs.durable_fence_term(cfg)
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
        drv=get_driver(cfg),
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
        ctx.drv.heal_all()
        return ScenarioResult(
            scenario_id=scenario_id,
            title=title,
            passed=True,
            detail="PASS",
            elapsed_s=time.time() - t0,
        )
    except Exception as exc:
        try:
            get_driver(cfg).heal_all()
        except Exception:
            pass
        return ScenarioResult(
            scenario_id=scenario_id,
            title=title,
            passed=False,
            detail=f"FAIL: {exc}",
            elapsed_s=time.time() - t0,
        )
