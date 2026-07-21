"""Combination testing and provider comparison reports."""

from __future__ import annotations

import time
from typing import Any

from app.ops.chaos import clear_chaos, set_chaos
from app.ops.failover import evaluate_failover
from app.ops.models import (
    ChaosKind,
    ComparisonReport,
    ComparisonRunRequest,
    OpsEvent,
)
from app.ops.prober import probe_all_providers
from app.ops.store import OpsStore, get_store, persist_store


async def run_comparison(
    request: ComparisonRunRequest,
    *,
    store: OpsStore | None = None,
    operator_id: str | None = None,
) -> ComparisonReport:
    """
    Probe providers (optionally with injected chaos), evaluate failover,
    and store a comparison report.
    """
    ops = store or get_store()
    notes: list[str] = []
    injected: list[str] = []

    for provider_id, kind in request.inject_chaos.items():
        if kind == ChaosKind.NONE:
            continue
        set_chaos(provider_id, kind, store=ops, operator_id=operator_id)
        injected.append(provider_id)
        notes.append(f"injected {kind.value} on {provider_id}")

    start = time.perf_counter()
    snapshots = await probe_all_providers(store=ops)
    failover_msg = evaluate_failover(snapshots, store=ops)
    failover_ms = (time.perf_counter() - start) * 1000.0

    provider_ids = request.provider_ids or [p.id for p in ops.list_providers()]
    scores: dict[str, float] = {}
    healthy_count = 0
    for pid in provider_ids:
        snap = ops.latest_snapshot(pid)
        if snap:
            scores[pid] = snap.score
            if snap.healthy:
                healthy_count += 1
        else:
            scores[pid] = 0.0

    success_rate = (
        healthy_count / len(provider_ids) if provider_ids else None
    )

    details: dict[str, Any] = {
        "failover": failover_msg.model_dump(mode="json") if failover_msg else None,
        "snapshots": {
            s.provider_id: s.model_dump(mode="json") for s in snapshots
        },
    }

    if failover_msg:
        notes.append(
            f"failover {failover_msg.from_provider_id} -> "
            f"{failover_msg.to_provider_id} dropped={failover_msg.sessions_dropped}"
        )
    else:
        notes.append("no failover triggered")

    report = ComparisonReport(
        name=request.name,
        provider_scores=scores,
        failover_ms=failover_ms,
        session_success_rate=success_rate,
        notes=notes,
        details=details,
    )
    ops.add_report(report)
    event_details: dict[str, Any] = {"report_id": report.id, "name": report.name}
    if operator_id:
        event_details["operator_id"] = operator_id
    ops.append_event(
        OpsEvent(
            event_type="comparison_run",
            details=event_details,
        )
    )

    for provider_id in injected:
        clear_chaos(provider_id, store=ops, operator_id=operator_id)

    persist_store()
    return report
