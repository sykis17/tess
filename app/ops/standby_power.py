"""Wake/sleep standby stacks (AWS/GCP) via existing operator scripts.

Runs ``scripts/aws_standby.py`` / ``scripts/gcp_standby.py`` as subprocesses so
budget guards, IP patching, and health waits stay in one place. Intended for
Celery (or admin API enqueue) — never block the FastAPI request thread on wake.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.ops.models import (
    CloudProvider,
    OpsEvent,
    PowerFailureClass,
    PowerPhase,
    ProviderPowerStatus,
    ProviderType,
    utc_now,
)
from app.ops.store import OpsStore, get_store, persist_store

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_AWS_SCRIPT = _REPO_ROOT / "scripts" / "aws_standby.py"
_GCP_SCRIPT = _REPO_ROOT / "scripts" / "gcp_standby.py"

# Soft clear of inflight wake lock if the Celery task never reports back.
# This is NOT an auto-sleep timer — running standbys stay up until Sleep / sleep-all.
AUTO_WAKE_INFLIGHT_TTL_S = 15 * 60

# Soft timeout for power lifecycle stuck in queued/waking/sleeping without a
# terminal event (worker never picked up the task, or crashed before append).
POWER_ACTION_SOFT_TIMEOUT_S = 15 * 60

_CREDS_MARKERS = (
    "unable to locate credentials",
    "nocredentialserror",
    "accessdenied",
    "unauthorized",
    "authentication failed",
    "invalidclienttokenid",
    "expiredtoken",
    "could not load credentials",
    "google.auth.exceptions",
    "default credentials were not found",
    "aws_access_key",
    "credentials",
)


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


def classify_power_failure(
    *,
    stderr: str = "",
    stdout: str = "",
    returncode: int | None = None,
    exc: BaseException | None = None,
) -> PowerFailureClass:
    """Map script/exception output to a coarse failure class for ops-ui."""
    if isinstance(exc, FileNotFoundError):
        return PowerFailureClass.SCRIPT
    if isinstance(exc, subprocess.TimeoutExpired):
        return PowerFailureClass.TIMEOUT
    blob = f"{stderr}\n{stdout}\n{exc or ''}".lower()
    if "timeout" in blob or returncode == -9:
        return PowerFailureClass.TIMEOUT
    if "not found" in blob and "script" in blob:
        return PowerFailureClass.SCRIPT
    if any(marker in blob for marker in _CREDS_MARKERS):
        return PowerFailureClass.CREDS
    return PowerFailureClass.UNKNOWN


def set_provider_power_status(
    provider_id: str,
    *,
    phase: PowerPhase,
    action: str | None = None,
    task_id: str | None = None,
    last_error: str | None = None,
    failure_class: PowerFailureClass | None = None,
    store: OpsStore | None = None,
    clear_error: bool = False,
) -> ProviderPowerStatus:
    """Persist per-provider power lifecycle for ops-ui badges."""
    ops = store or get_store()
    routing = ops.get_routing()
    prev = routing.power_by_provider.get(provider_id)
    if clear_error:
        err = last_error
        fclass = failure_class
    else:
        err = last_error if last_error is not None else (prev.last_error if prev else None)
        fclass = (
            failure_class
            if failure_class is not None
            else (prev.failure_class if prev else None)
        )
    status = ProviderPowerStatus(
        phase=phase,
        action=action if action is not None else (prev.action if prev else None),
        task_id=task_id if task_id is not None else (prev.task_id if prev else None),
        last_error=err,
        failure_class=fclass,
        updated_at=utc_now(),
    )
    routing.power_by_provider[provider_id] = status
    ops.set_routing(routing)
    return status


def mark_power_queued(
    provider_id: str,
    action: str,
    *,
    task_id: str | None,
    store: OpsStore | None = None,
) -> ProviderPowerStatus:
    return set_provider_power_status(
        provider_id,
        phase=PowerPhase.QUEUED,
        action=action,
        task_id=task_id,
        store=store,
        clear_error=True,
    )


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


def _force_probe_after_wake(
    provider_id: str,
    *,
    store: OpsStore,
) -> dict[str, Any]:
    """Run an immediate /health probe so Dual's healthy gate can pass."""
    from app.ops.prober import probe_provider

    provider = store.get_provider(provider_id)
    if provider is None:
        return {"ok": False, "error": "provider_missing"}
    try:
        snap = asyncio.run(probe_provider(provider, store=store))
    except Exception as exc:
        logger.exception("post-wake probe failed for %s", provider_id)
        return {"ok": False, "error": str(exc)}
    return {
        "ok": bool(snap.healthy),
        "healthy": snap.healthy,
        "score": snap.score,
        "last_error": snap.last_error,
    }


def power_action_for_provider(
    provider_id: str,
    action: str,
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Synchronous wake/sleep for one provider (Celery worker entry).

    Always emits a terminal ``standby_*`` / ``standby_*_failed`` event — even on
    missing script, timeout, or unexpected exceptions — so the trail never stops
    at ``*_enqueued`` alone.
    """
    ops = store or get_store()
    provider = ops.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"unknown provider: {provider_id}")
    script = script_for_provider(provider)
    if script is None:
        raise ValueError(
            f"provider {provider_id} type={provider.type.value} is not a wakeable standby"
        )

    running_phase = PowerPhase.WAKING if action == "wake" else PowerPhase.SLEEPING
    set_provider_power_status(
        provider_id,
        phase=running_phase,
        action=action,
        store=ops,
        clear_error=True,
    )
    persist_store()

    failure_class: PowerFailureClass | None = None
    caught_exc: BaseException | None = None
    try:
        result = run_standby_script(script, action, timeout_s=timeout_s)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        caught_exc = exc
        failure_class = classify_power_failure(exc=exc)
        result = {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "action": action,
            "script": script.name if script else "",
        }
    except Exception as exc:  # noqa: BLE001 — must always reach terminal event
        caught_exc = exc
        failure_class = PowerFailureClass.UNKNOWN
        logger.exception("standby power action crashed: %s %s", action, provider_id)
        result = {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "action": action,
            "script": script.name if script else "",
        }

    if not result["ok"] and failure_class is None:
        failure_class = classify_power_failure(
            stderr=str(result.get("stderr") or ""),
            stdout=str(result.get("stdout") or ""),
            returncode=result.get("returncode"),
            exc=caught_exc,
        )

    details: dict[str, Any] = {
        "action": action,
        "ok": result["ok"],
        "returncode": result["returncode"],
        "stdout_tail": result["stdout"][-500:] if result["stdout"] else "",
        "stderr_tail": result["stderr"][-500:] if result["stderr"] else "",
    }
    if failure_class is not None:
        details["failure_class"] = failure_class.value
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

    probe_meta: dict[str, Any] | None = None
    if action == "wake" and result["ok"]:
        probe_meta = _force_probe_after_wake(provider_id, store=ops)
        details["post_wake_probe"] = probe_meta
        if not probe_meta.get("ok"):
            failure_class = PowerFailureClass.HEALTH
            err = probe_meta.get("error") or probe_meta.get("last_error") or "not healthy"
            set_provider_power_status(
                provider_id,
                phase=PowerPhase.FAILED,
                action=action,
                last_error=f"wake script ok but /health not green: {err}",
                failure_class=failure_class,
                store=ops,
                clear_error=True,
            )
            ops.append_event(
                OpsEvent(
                    event_type="standby_wake_health_failed",
                    provider_id=provider_id,
                    details={
                        "failure_class": failure_class.value,
                        "probe": probe_meta,
                        "note": "EC2/GCP started but Dual gate still blocked until healthy",
                    },
                )
            )
        else:
            set_provider_power_status(
                provider_id,
                phase=PowerPhase.HEALTHY,
                action=action,
                store=ops,
                clear_error=True,
            )
    elif result["ok"] and action == "sleep":
        set_provider_power_status(
            provider_id,
            phase=PowerPhase.IDLE,
            action=action,
            store=ops,
            clear_error=True,
        )
    else:
        err_tail = (result.get("stderr") or result.get("stdout") or "failed")[-300:]
        set_provider_power_status(
            provider_id,
            phase=PowerPhase.FAILED,
            action=action,
            last_error=err_tail,
            failure_class=failure_class or PowerFailureClass.UNKNOWN,
            store=ops,
            clear_error=True,
        )

    routing = ops.get_routing()
    if action == "wake" and routing.auto_wake_inflight_provider_id == provider_id:
        # Always clear inflight on completion — success or failure (no stuck "waking")
        routing.auto_wake_inflight_provider_id = None
        routing.auto_wake_inflight_at = None
        routing.auto_wake_inflight_task_id = None
        if not result["ok"] or (
            probe_meta is not None and not probe_meta.get("ok")
        ):
            policy = ops.get_policy()
            until = utc_now() + timedelta(seconds=policy.auto_wake_failure_cooldown_s)
            routing.auto_wake_cooldown_until[provider_id] = until
            fc = (failure_class or PowerFailureClass.UNKNOWN).value
            decision = (
                f"Wake FAILED for {provider_id} "
                f"(class={fc}, rc={result['returncode']}); "
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
                        "failure_class": fc,
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
    elif action == "wake" and (
        not result["ok"] or (probe_meta is not None and not probe_meta.get("ok"))
    ):
        # Manual wake failure (not necessarily inflight auto-wake)
        policy = ops.get_policy()
        until = utc_now() + timedelta(seconds=policy.auto_wake_failure_cooldown_s)
        routing.auto_wake_cooldown_until[provider_id] = until
        if routing.auto_wake_inflight_provider_id == provider_id:
            routing.auto_wake_inflight_provider_id = None
            routing.auto_wake_inflight_at = None
            routing.auto_wake_inflight_task_id = None
        fc = (failure_class or PowerFailureClass.UNKNOWN).value
        routing.auto_wake_last_decision = (
            f"Wake FAILED for {provider_id} (class={fc}, "
            f"rc={result['returncode']}) — not an intentional sleep"
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
            fc = (failure_class or PowerFailureClass.UNKNOWN).value
            routing.auto_wake_last_decision = (
                f"Sleep FAILED for {provider_id} (class={fc}, "
                f"rc={result['returncode']}) — "
                "box may still be running; retry Sleep or Sleep all"
            )
            routing.auto_wake_last_decision_at = utc_now()
        ops.set_routing(routing)

    persist_store()
    out: dict[str, Any] = {"provider_id": provider_id, **result}
    if failure_class is not None:
        out["failure_class"] = failure_class.value
    if probe_meta is not None:
        out["post_wake_probe"] = probe_meta
    return out


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
    # Also mark power lifecycle failed so UI leaves "queued/waking"
    set_provider_power_status(
        pid,
        phase=PowerPhase.FAILED,
        last_error=f"inflight wake lock expired after {int(age)}s (worker never finished)",
        failure_class=PowerFailureClass.TIMEOUT,
        store=ops,
        clear_error=True,
    )
    persist_store()
    return True


def expire_stale_power_actions(store: OpsStore | None = None) -> list[str]:
    """
    Terminal-fail power rows stuck in queued/waking/sleeping past soft timeout.

    Covers the case where Celery never consumes the task (trail would otherwise
    sit forever on ``standby_wake_enqueued``).
    """
    ops = store or get_store()
    routing = ops.get_routing()
    now = utc_now()
    expired: list[str] = []
    for pid, status in list(routing.power_by_provider.items()):
        if status.phase not in (
            PowerPhase.QUEUED,
            PowerPhase.WAKING,
            PowerPhase.SLEEPING,
        ):
            continue
        age = (now - status.updated_at).total_seconds()
        if age < POWER_ACTION_SOFT_TIMEOUT_S:
            continue
        action = status.action or "wake"
        set_provider_power_status(
            pid,
            phase=PowerPhase.FAILED,
            action=action,
            last_error=(
                f"{action} soft-timeout after {int(age)}s — "
                "worker never reported terminal status (check Celery + worker creds)"
            ),
            failure_class=PowerFailureClass.TIMEOUT,
            store=ops,
            clear_error=True,
        )
        event_type = (
            f"standby_{action}_failed"
            if action in ("wake", "sleep")
            else "standby_wake_failed"
        )
        ops.append_event(
            OpsEvent(
                event_type=event_type,
                provider_id=pid,
                details={
                    "failure_class": PowerFailureClass.TIMEOUT.value,
                    "age_s": age,
                    "ttl_s": POWER_ACTION_SOFT_TIMEOUT_S,
                    "reason": "power_action_soft_timeout",
                    "note": "Enqueue alone is not completion — worker must finish",
                    "recovery": "Verify Celery worker + AWS/GCP creds; Sleep all to reset",
                },
            )
        )
        if action == "wake":
            routing = ops.get_routing()
            routing.auto_wake_last_decision = (
                f"Wake FAILED for {pid} (class=timeout) — soft-timeout, "
                "worker never finished"
            )
            routing.auto_wake_last_decision_at = utc_now()
            if routing.auto_wake_inflight_provider_id == pid:
                routing.auto_wake_inflight_provider_id = None
                routing.auto_wake_inflight_at = None
                routing.auto_wake_inflight_task_id = None
            ops.set_routing(routing)
        expired.append(pid)
    if expired:
        persist_store()
    return expired


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
    Choose an offline standby whose *last healthy* score (fresh enough) beats
    incumbent + margin.

    After Sleep all, probes keep appending unhealthy low-score snaps. Auto-wake
    therefore uses the most recent **healthy** snapshot within
    ``auto_wake_max_score_age_s``, not the latest failed probe. Missing/stale
    healthy history → refuse (no blind wake). One candidate only.
    """
    ops = store or get_store()
    policy = ops.get_policy()
    routing = ops.get_routing()
    max_age = policy.auto_wake_max_score_age_s
    floor = policy.min_score_for_healthy
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

        latest = ops.latest_snapshot(provider.id)
        if (
            latest is not None
            and latest.healthy
            and latest.score >= floor
        ):
            skipped.append({"provider_id": provider.id, "reason": "already_healthy"})
            continue

        # Competitive history: last time this standby was actually healthy
        snap = ops.latest_healthy_snapshot(provider.id, min_score=floor)
        if snap is None:
            skipped.append(
                {
                    "provider_id": provider.id,
                    "reason": "no_healthy_history_refuse_blind_wake",
                    "latest_score": latest.score if latest else None,
                    "latest_healthy": latest.healthy if latest else None,
                }
            )
            continue

        age_s = (now - snap.checked_at).total_seconds()
        if age_s > max_age:
            skipped.append(
                {
                    "provider_id": provider.id,
                    "reason": "stale_healthy_score",
                    "age_s": round(age_s, 1),
                    "max_age_s": max_age,
                    "last_healthy_score": snap.score,
                    "hint": "Wake manually once to refresh score, then Sleep, then retry auto-wake within the age window",
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
                    "last_healthy_score": snap.score,
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
                    "score_source": "last_healthy_snapshot",
                },
            )
        )

    if not scored:
        # Human-readable trail line: why each standby was skipped
        parts = [
            f"{s['provider_id']}:{s['reason']}"
            for s in skipped
            if s.get("provider_id")
        ]
        detail = "; ".join(parts) if parts else "no standbys"
        return None, {
            "picked": None,
            "incumbent_score": incumbent_score,
            "skipped": skipped,
            "reason": f"no_fresh_candidate ({detail})",
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
        "score_source": meta["score_source"],
        "skipped": skipped,
        "reason": (
            f"{best_id} last_healthy={best_score:.1f} beat active "
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
    store: OpsStore | None = None,
) -> str | None:
    """Fire Celery task; return task id (or None if sync fallback used)."""
    ops = store or get_store()
    try:
        from app.worker import ops_standby_wake

        async_result = ops_standby_wake.delay(provider_id, operator_id=operator_id)
        task_id = str(async_result.id)
        mark_power_queued(provider_id, "wake", task_id=task_id, store=ops)
        persist_store()
        return task_id
    except Exception:
        logger.exception("enqueue wake failed; running inline (tests/dev)")
        power_action_for_provider(
            provider_id, "wake", operator_id=operator_id, store=ops
        )
        return None


def enqueue_standby_sleep(
    provider_id: str,
    *,
    operator_id: str | None = None,
    store: OpsStore | None = None,
) -> str | None:
    ops = store or get_store()
    try:
        from app.worker import ops_standby_sleep

        async_result = ops_standby_sleep.delay(provider_id, operator_id=operator_id)
        task_id = str(async_result.id)
        mark_power_queued(provider_id, "sleep", task_id=task_id, store=ops)
        persist_store()
        return task_id
    except Exception:
        logger.exception("enqueue sleep failed; running inline (tests/dev)")
        power_action_for_provider(
            provider_id, "sleep", operator_id=operator_id, store=ops
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
