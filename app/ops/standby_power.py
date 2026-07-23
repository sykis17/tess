"""Wake/sleep standby stacks (AWS/GCP) via existing operator scripts.

Runs ``scripts/aws_standby.py`` / ``scripts/gcp_standby.py`` as subprocesses so
budget guards, IP patching, and health waits stay in one place. Intended for
Celery (or admin API enqueue) — never block the FastAPI request thread on wake.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.ops.models import CloudProvider, OpsEvent, ProviderType, utc_now
from app.ops.store import OpsStore, get_store, persist_store

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_AWS_SCRIPT = _REPO_ROOT / "scripts" / "aws_standby.py"
_GCP_SCRIPT = _REPO_ROOT / "scripts" / "gcp_standby.py"

# Soft clear of inflight wake lock if the Celery task never reports back.
# This is NOT an auto-sleep timer — running standbys stay up until Sleep / sleep-all.
AUTO_WAKE_INFLIGHT_TTL_S = 15 * 60


def script_for_provider(provider: CloudProvider) -> Path | None:
    if provider.type == ProviderType.AWS:
        return _AWS_SCRIPT
    if provider.type == ProviderType.GCP:
        return _GCP_SCRIPT
    return None


def is_standby_provider(provider: CloudProvider) -> bool:
    return provider.type in (ProviderType.AWS, ProviderType.GCP) and not provider.org_id


def list_standby_providers(store: OpsStore | None = None) -> list[CloudProvider]:
    ops = store or get_store()
    return [p for p in ops.list_providers() if is_standby_provider(p) and p.enabled]


def run_standby_script(
    script: Path,
    action: str,
    *,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """
    Execute ``python scripts/{aws|gcp}_standby.py {wake|sleep|drift-check}``.

    Returns dict with ok, returncode, stdout, stderr. Raises on missing script.
    """
    if not script.is_file():
        raise FileNotFoundError(f"standby script not found: {script}")
    if action not in ("wake", "sleep", "drift-check"):
        raise ValueError(f"unsupported standby action: {action}")

    cmd = [sys.executable, str(script), action]
    logger.info("standby_power: running %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-4000:],
        "stderr": (completed.stderr or "")[-4000:],
        "action": action,
        "script": script.name,
    }


def power_action_for_provider(
    provider_id: str,
    action: str,
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Synchronous wake/sleep for one provider (Celery worker entry)."""
    ops = store or get_store()
    provider = ops.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"unknown provider: {provider_id}")
    script = script_for_provider(provider)
    if script is None:
        raise ValueError(
            f"provider {provider_id} type={provider.type.value} is not a wakeable standby"
        )

    result = run_standby_script(script, action, timeout_s=timeout_s)
    details: dict[str, Any] = {
        "action": action,
        "ok": result["ok"],
        "returncode": result["returncode"],
        "stdout_tail": result["stdout"][-500:] if result["stdout"] else "",
        "stderr_tail": result["stderr"][-500:] if result["stderr"] else "",
    }
    if operator_id:
        details["operator_id"] = operator_id

    event_type = f"standby_{action}"
    if not result["ok"]:
        event_type = f"standby_{action}_failed"
    elif action == "sleep":
        # Distinct from wake failures for ops-ui trail labeling
        event_type = "standby_sleep_intentional"
        details["intent"] = "resting_cost"
    ops.append_event(
        OpsEvent(
            event_type=event_type,
            provider_id=provider_id,
            details=details,
        )
    )

    routing = ops.get_routing()
    if action == "wake" and routing.auto_wake_inflight_provider_id == provider_id:
        # Always clear inflight on completion — success or failure (no stuck "waking")
        routing.auto_wake_inflight_provider_id = None
        routing.auto_wake_inflight_at = None
        routing.auto_wake_inflight_task_id = None
        if not result["ok"]:
            policy = ops.get_policy()
            until = utc_now() + timedelta(seconds=policy.auto_wake_failure_cooldown_s)
            routing.auto_wake_cooldown_until[provider_id] = until
            decision = (
                f"Wake FAILED for {provider_id} (rc={result['returncode']}); "
                f"cooldown until {until.isoformat()}; "
                "use Sleep all standbys to reset posture / clear stuck state"
            )
            routing.auto_wake_last_decision = decision
            routing.auto_wake_last_decision_at = utc_now()
            ops.append_event(
                OpsEvent(
                    event_type="auto_wake_failed_cooldown",
                    provider_id=provider_id,
                    details={
                        "cooldown_until": until.isoformat(),
                        "returncode": result["returncode"],
                        "recovery": "POST /ops/standbys/sleep-all",
                        "severity": "wake_failed",
                    },
                )
            )
        else:
            routing.auto_wake_cooldown_until.pop(provider_id, None)
            routing.auto_wake_last_decision = (
                f"Wake OK for {provider_id} — now competing online"
            )
            routing.auto_wake_last_decision_at = utc_now()
        ops.set_routing(routing)
    elif action == "wake" and not result["ok"]:
        # Manual wake failure (not necessarily inflight auto-wake)
        policy = ops.get_policy()
        until = utc_now() + timedelta(seconds=policy.auto_wake_failure_cooldown_s)
        routing.auto_wake_cooldown_until[provider_id] = until
        if routing.auto_wake_inflight_provider_id == provider_id:
            routing.auto_wake_inflight_provider_id = None
            routing.auto_wake_inflight_at = None
            routing.auto_wake_inflight_task_id = None
        routing.auto_wake_last_decision = (
            f"Wake FAILED for {provider_id} (rc={result['returncode']}) — "
            "not an intentional sleep"
        )
        routing.auto_wake_last_decision_at = utc_now()
        ops.set_routing(routing)
    if action == "sleep":
        if routing.auto_wake_inflight_provider_id == provider_id:
            routing.auto_wake_inflight_provider_id = None
            routing.auto_wake_inflight_at = None
            routing.auto_wake_inflight_task_id = None
        if result["ok"]:
            routing.auto_wake_cooldown_until.pop(provider_id, None)
            routing.auto_wake_last_decision = (
                f"Intentional sleep for {provider_id} (resting cost) — not a failure"
            )
            routing.auto_wake_last_decision_at = utc_now()
        else:
            routing.auto_wake_last_decision = (
                f"Sleep FAILED for {provider_id} (rc={result['returncode']}) — "
                "box may still be running; retry Sleep or Sleep all"
            )
            routing.auto_wake_last_decision_at = utc_now()
        ops.set_routing(routing)

    persist_store()
    return {"provider_id": provider_id, **result}


def clear_stale_auto_wake_inflight(store: OpsStore | None = None) -> bool:
    """Clear inflight lock if older than TTL (task hung / never reported)."""
    ops = store or get_store()
    routing = ops.get_routing()
    if not routing.auto_wake_inflight_provider_id or not routing.auto_wake_inflight_at:
        return False
    age = (utc_now() - routing.auto_wake_inflight_at).total_seconds()
    if age < AUTO_WAKE_INFLIGHT_TTL_S:
        return False
    pid = routing.auto_wake_inflight_provider_id
    ops.append_event(
        OpsEvent(
            event_type="auto_wake_inflight_expired",
            provider_id=pid,
            details={
                "age_s": age,
                "ttl_s": AUTO_WAKE_INFLIGHT_TTL_S,
                "note": "lock only — standby was NOT auto-slept",
                "recovery": "POST /ops/standbys/sleep-all if unsure",
            },
        )
    )
    routing.auto_wake_inflight_provider_id = None
    routing.auto_wake_inflight_at = None
    routing.auto_wake_inflight_task_id = None
    routing.auto_wake_last_decision = (
        f"Inflight wake lock for {pid} expired after {int(age)}s "
        "(not an auto-sleep). Use Sleep all if the box may still be running."
    )
    routing.auto_wake_last_decision_at = utc_now()
    ops.set_routing(routing)
    persist_store()
    return True


def _effective_margin(provider: CloudProvider, global_margin: float) -> float:
    if provider.auto_wake_score_margin is not None:
        return float(provider.auto_wake_score_margin)
    return float(global_margin)


def _in_cooldown(routing: Any, provider_id: str) -> bool:
    until = routing.auto_wake_cooldown_until.get(provider_id)
    if until is None:
        return False
    return utc_now() < until


def pick_auto_wake_candidate(
    store: OpsStore | None = None,
    *,
    incumbent_score: float,
    margin: float,
) -> tuple[str | None, dict[str, Any]]:
    """
    Choose an offline standby whose *fresh enough* last score beats incumbent + margin.

    Returns (provider_id | None, decision_details).
    Never wakes on missing/stale scores. Never picks Hetzner / customer / healthy.
    One candidate only — caller holds inflight lock to prevent stampede.
    """
    ops = store or get_store()
    policy = ops.get_policy()
    routing = ops.get_routing()
    max_age = policy.auto_wake_max_score_age_s
    now = utc_now()
    scored: list[tuple[float, str, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []

    for provider in list_standby_providers(ops):
        if _in_cooldown(routing, provider.id):
            skipped.append(
                {
                    "provider_id": provider.id,
                    "reason": "failure_cooldown",
                    "until": routing.auto_wake_cooldown_until[provider.id].isoformat(),
                }
            )
            continue
        snap = ops.latest_snapshot(provider.id)
        if snap is not None and snap.healthy and snap.score >= policy.min_score_for_healthy:
            skipped.append({"provider_id": provider.id, "reason": "already_healthy"})
            continue
        if snap is None:
            skipped.append(
                {
                    "provider_id": provider.id,
                    "reason": "no_snapshot_refuse_blind_wake",
                }
            )
            continue
        age_s = (now - snap.checked_at).total_seconds()
        if age_s > max_age:
            skipped.append(
                {
                    "provider_id": provider.id,
                    "reason": "stale_score",
                    "age_s": round(age_s, 1),
                    "max_age_s": max_age,
                    "last_score": snap.score,
                }
            )
            continue
        eff_margin = _effective_margin(provider, margin)
        need = incumbent_score + eff_margin
        if snap.score < need:
            skipped.append(
                {
                    "provider_id": provider.id,
                    "reason": "margin_not_met",
                    "last_score": snap.score,
                    "incumbent_score": incumbent_score,
                    "margin": eff_margin,
                    "need": need,
                }
            )
            continue
        scored.append(
            (
                snap.score,
                provider.id,
                {
                    "last_score": snap.score,
                    "incumbent_score": incumbent_score,
                    "margin": eff_margin,
                    "delta": snap.score - incumbent_score,
                    "age_s": round(age_s, 1),
                    "checked_at": snap.checked_at.isoformat(),
                },
            )
        )

    if not scored:
        return None, {
            "picked": None,
            "incumbent_score": incumbent_score,
            "skipped": skipped,
            "reason": "no_fresh_candidate",
        }

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_id, meta = scored[0]
    return best_id, {
        "picked": best_id,
        "challenger_score": best_score,
        "incumbent_score": incumbent_score,
        "margin": meta["margin"],
        "delta": meta["delta"],
        "score_age_s": meta["age_s"],
        "checked_at": meta["checked_at"],
        "skipped": skipped,
        "reason": (
            f"{best_id} last_score={best_score:.1f} beat active "
            f"{incumbent_score:.1f} by {meta['delta']:.1f} "
            f"(margin {meta['margin']:.1f}, age {meta['age_s']:.0f}s)"
        ),
    }


def maybe_enqueue_auto_wake(
    *,
    store: OpsStore | None = None,
    incumbent_score: float,
) -> str | None:
    """
    If Performance + auto_wake and no inflight wake, enqueue Celery wake for one candidate.

    Stampede guard: single inflight lock. Failure clears lock + per-provider cooldown.
    """
    ops = store or get_store()
    policy = ops.get_policy()
    if not policy.auto_wake:
        return None

    clear_stale_auto_wake_inflight(ops)
    routing = ops.get_routing()
    if routing.auto_wake_inflight_provider_id:
        return None

    candidate, decision = pick_auto_wake_candidate(
        ops,
        incumbent_score=incumbent_score,
        margin=policy.performance_score_margin,
    )
    routing = ops.get_routing()
    routing.auto_wake_last_decision = decision.get("reason") or str(decision)
    routing.auto_wake_last_decision_at = utc_now()
    ops.set_routing(routing)

    if not candidate:
        ops.append_event(
            OpsEvent(
                event_type="auto_wake_skipped",
                details=decision,
            )
        )
        persist_store()
        return None

    task_id = enqueue_standby_wake(candidate, operator_id="auto_wake")
    routing = ops.get_routing()
    routing.auto_wake_inflight_provider_id = candidate
    routing.auto_wake_inflight_at = utc_now()
    routing.auto_wake_inflight_task_id = task_id
    routing.auto_wake_last_decision = decision.get("reason")
    routing.auto_wake_last_decision_at = utc_now()
    ops.set_routing(routing)
    ops.append_event(
        OpsEvent(
            event_type="auto_wake_requested",
            provider_id=candidate,
            details={**decision, "task_id": task_id},
        )
    )
    persist_store()
    return candidate


def enqueue_standby_wake(
    provider_id: str,
    *,
    operator_id: str | None = None,
) -> str | None:
    """Fire Celery task; return task id (or None if sync fallback used)."""
    try:
        from app.worker import ops_standby_wake

        async_result = ops_standby_wake.delay(provider_id, operator_id=operator_id)
        return str(async_result.id)
    except Exception:
        logger.exception("enqueue wake failed; running inline (tests/dev)")
        power_action_for_provider(
            provider_id, "wake", operator_id=operator_id
        )
        return None


def enqueue_standby_sleep(
    provider_id: str,
    *,
    operator_id: str | None = None,
) -> str | None:
    try:
        from app.worker import ops_standby_sleep

        async_result = ops_standby_sleep.delay(provider_id, operator_id=operator_id)
        return str(async_result.id)
    except Exception:
        logger.exception("enqueue sleep failed; running inline (tests/dev)")
        power_action_for_provider(
            provider_id, "sleep", operator_id=operator_id
        )
        return None


def enqueue_sleep_all_standbys(
    *,
    operator_id: str | None = None,
    restore_active_only: bool = True,
) -> dict[str, Any]:
    """
    Resting cost posture: exit Dual/Performance, prefer Hetzner active, sleep standbys.

    Hard reset for stuck auto-wake: clears inflight lock + failure cooldowns.
    """
    from app.ops.failover import force_active_provider
    from app.ops.models import RoutingPolicy

    ops = get_store()
    policy = ops.get_policy()
    routing = ops.get_routing()

    # Always clear stuck wake state (recovery path for failed/hung wakes)
    routing.auto_wake_inflight_provider_id = None
    routing.auto_wake_inflight_at = None
    routing.auto_wake_inflight_task_id = None
    routing.auto_wake_cooldown_until = {}
    routing.auto_wake_last_decision = (
        "Intentional Sleep all (resting cost) — Dual/Performance off; "
        "not a wake failure"
    )
    routing.auto_wake_last_decision_at = utc_now()

    if restore_active_only and policy.policy in (
        RoutingPolicy.DUAL,
        RoutingPolicy.PERFORMANCE,
    ):
        routing.dual_peer_id = None
        routing.performance_challenger_id = None
        routing.performance_challenger_streak = 0
        ops.set_routing(routing)
        ops.set_policy(
            policy.model_copy(
                update={"policy": RoutingPolicy.ACTIVE_ONLY, "auto_wake": False}
            )
        )
        routing = ops.get_routing()
        policy = ops.get_policy()
    else:
        if policy.auto_wake:
            ops.set_policy(policy.model_copy(update={"auto_wake": False}))
            policy = ops.get_policy()
        ops.set_routing(routing)

    # Prefer Hetzner as active before sleeping peers
    hetzner = next(
        (p for p in ops.list_providers() if p.type == ProviderType.HETZNER and p.enabled),
        None,
    )
    if hetzner and routing.active_provider_id != hetzner.id:
        force_active_provider(hetzner.id, store=ops, operator_id=operator_id)
        routing = ops.get_routing()

    tasks: dict[str, str | None] = {}
    for provider in list_standby_providers(ops):
        tasks[provider.id] = enqueue_standby_sleep(
            provider.id, operator_id=operator_id
        )

    ops.append_event(
        OpsEvent(
            event_type="standbys_sleep_all",
            details={
                "tasks": tasks,
                "operator_id": operator_id,
                "active": ops.get_routing().active_provider_id,
                "severity": "intentional_resting_cost",
                "note": "Not a wake failure — voluntary cost control",
            },
        )
    )
    persist_store()
    return {
        "active_provider_id": ops.get_routing().active_provider_id,
        "policy": ops.get_policy().policy.value,
        "auto_wake": ops.get_policy().auto_wake,
        "sleep_tasks": tasks,
        "severity": "intentional_resting_cost",
    }
