"""In-memory ops store with optional Redis persistence."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.ops.models import (
    CloudProvider,
    ComparisonReport,
    HealthSnapshot,
    OpsEvent,
    ProviderType,
    RoutingPolicySettings,
    RoutingState,
    SessionAssignment,
    utc_now,
)

# OpsEvent imported above for ensure_default_hetzner.

logger = logging.getLogger(__name__)

REDIS_PROVIDERS_KEY = "ops:providers"
REDIS_ROUTING_KEY = "ops:routing"
REDIS_POLICY_KEY = "ops:policy"
REDIS_EVENTS_KEY = "ops:events"
REDIS_SNAPSHOTS_KEY = "ops:snapshots"
REDIS_ASSIGNMENTS_KEY = "ops:assignments"
REDIS_REPORTS_KEY = "ops:reports"

MAX_EVENTS = 2000
MAX_SNAPSHOTS = 2000


class OpsStore:
    """Thread-safe in-process registry for providers, health, events, and routing."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.providers: dict[str, CloudProvider] = {}
        self.snapshots: list[HealthSnapshot] = []
        self.events: list[OpsEvent] = []
        self.routing = RoutingState()
        self.policy = RoutingPolicySettings()
        self.assignments: dict[str, SessionAssignment] = {}
        self.reports: dict[str, ComparisonReport] = {}
        self._rr_index = 0

    def clear(self) -> None:
        with self._lock:
            self.providers.clear()
            self.snapshots.clear()
            self.events.clear()
            self.routing = RoutingState()
            self.policy = RoutingPolicySettings()
            self.assignments.clear()
            self.reports.clear()
            self._rr_index = 0

    def upsert_provider(self, provider: CloudProvider) -> CloudProvider:
        with self._lock:
            self.providers[provider.id] = provider
            if self.routing.active_provider_id is None and provider.enabled:
                self.routing.active_provider_id = provider.id
            return provider

    def get_provider(self, provider_id: str) -> CloudProvider | None:
        with self._lock:
            return self.providers.get(provider_id)

    def list_providers(self) -> list[CloudProvider]:
        with self._lock:
            return list(self.providers.values())

    def delete_provider(self, provider_id: str) -> bool:
        with self._lock:
            if provider_id not in self.providers:
                return False
            del self.providers[provider_id]
            if self.routing.active_provider_id == provider_id:
                enabled = [p for p in self.providers.values() if p.enabled]
                self.routing.active_provider_id = enabled[0].id if enabled else None
            return True

    def append_snapshot(self, snapshot: HealthSnapshot) -> HealthSnapshot:
        with self._lock:
            self.snapshots.append(snapshot)
            if len(self.snapshots) > MAX_SNAPSHOTS:
                self.snapshots = self.snapshots[-MAX_SNAPSHOTS:]
            return snapshot

    def latest_snapshot(self, provider_id: str) -> HealthSnapshot | None:
        with self._lock:
            for snap in reversed(self.snapshots):
                if snap.provider_id == provider_id:
                    return snap
            return None

    def latest_healthy_snapshot(
        self,
        provider_id: str,
        *,
        min_score: float = 0.0,
    ) -> HealthSnapshot | None:
        """Most recent snapshot that was healthy and at/above ``min_score``."""
        with self._lock:
            for snap in reversed(self.snapshots):
                if snap.provider_id != provider_id:
                    continue
                if snap.healthy and snap.score >= min_score:
                    return snap
            return None

    def list_snapshots(
        self,
        provider_id: str | None = None,
        limit: int = 100,
    ) -> list[HealthSnapshot]:
        with self._lock:
            items = self.snapshots
            if provider_id:
                items = [s for s in items if s.provider_id == provider_id]
            return items[-limit:]

    def append_event(self, event: OpsEvent) -> OpsEvent:
        with self._lock:
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                self.events = self.events[-MAX_EVENTS:]
            return event

    def list_events(
        self,
        provider_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[OpsEvent]:
        with self._lock:
            items = self.events
            if provider_id:
                items = [e for e in items if e.provider_id == provider_id]
            if event_type:
                items = [e for e in items if e.event_type == event_type]
            return items[-limit:]

    def set_policy(self, policy: RoutingPolicySettings) -> RoutingPolicySettings:
        with self._lock:
            self.policy = policy
            return self.policy

    def get_policy(self) -> RoutingPolicySettings:
        with self._lock:
            return self.policy.model_copy(deep=True)

    def get_routing(self) -> RoutingState:
        with self._lock:
            return self.routing.model_copy(deep=True)

    def set_routing(self, routing: RoutingState) -> RoutingState:
        with self._lock:
            self.routing = routing
            return self.routing

    def set_assignment(self, assignment: SessionAssignment) -> SessionAssignment:
        with self._lock:
            self.assignments[assignment.session_id] = assignment
            return assignment

    def clear_assignments(self) -> int:
        with self._lock:
            count = len(self.assignments)
            self.assignments.clear()
            return count

    def clear_assignments_for_provider(self, provider_id: str) -> int:
        """Drop sticky sessions assigned to a single provider (Dual home loss)."""
        with self._lock:
            to_drop = [
                sid
                for sid, a in self.assignments.items()
                if a.provider_id == provider_id
            ]
            for sid in to_drop:
                del self.assignments[sid]
            return len(to_drop)

    def get_assignment(self, session_id: str) -> SessionAssignment | None:
        with self._lock:
            return self.assignments.get(session_id)

    def next_round_robin(self, provider_ids: list[str]) -> str | None:
        with self._lock:
            if not provider_ids:
                return None
            idx = self._rr_index % len(provider_ids)
            self._rr_index += 1
            return provider_ids[idx]

    def add_report(self, report: ComparisonReport) -> ComparisonReport:
        with self._lock:
            self.reports[report.id] = report
            return report

    def list_reports(self) -> list[ComparisonReport]:
        with self._lock:
            return list(self.reports.values())

    def to_redis_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "providers": {
                    pid: p.model_dump(mode="json") for pid, p in self.providers.items()
                },
                "routing": self.routing.model_dump(mode="json"),
                "policy": self.policy.model_dump(mode="json"),
                "events": [e.model_dump(mode="json") for e in self.events[-500:]],
                "snapshots": [s.model_dump(mode="json") for s in self.snapshots[-500:]],
                "assignments": {
                    sid: a.model_dump(mode="json")
                    for sid, a in self.assignments.items()
                },
                "reports": {
                    rid: r.model_dump(mode="json") for rid, r in self.reports.items()
                },
                "rr_index": self._rr_index,
                "saved_at": utc_now().isoformat(),
            }

    def load_redis_payload(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.providers = {
                pid: CloudProvider.model_validate(data)
                for pid, data in payload.get("providers", {}).items()
            }
            if "routing" in payload:
                self.routing = RoutingState.model_validate(payload["routing"])
            if "policy" in payload:
                self.policy = RoutingPolicySettings.model_validate(payload["policy"])
            self.events = [
                OpsEvent.model_validate(e) for e in payload.get("events", [])
            ]
            self.snapshots = [
                HealthSnapshot.model_validate(s) for s in payload.get("snapshots", [])
            ]
            self.assignments = {
                sid: SessionAssignment.model_validate(data)
                for sid, data in payload.get("assignments", {}).items()
            }
            self.reports = {
                rid: ComparisonReport.model_validate(data)
                for rid, data in payload.get("reports", {}).items()
            }
            self._rr_index = int(payload.get("rr_index", 0))


_store: OpsStore | None = None
_store_lock = threading.Lock()


def get_store() -> OpsStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = OpsStore()
        return _store


def reset_store() -> OpsStore:
    """Replace the singleton (tests)."""
    global _store
    with _store_lock:
        _store = OpsStore()
        return _store


def persist_store() -> None:
    """Best-effort Redis snapshot of the ops control plane."""
    from app.core.config import settings

    if not settings.ops_persist_enabled:
        return
    try:
        import redis as redis_lib

        client = redis_lib.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        try:
            payload = json.dumps(get_store().to_redis_payload())
            client.set("ops:control_plane", payload)
        finally:
            client.close()
    except Exception:
        logger.debug("ops persist skipped", exc_info=True)


def restore_store() -> bool:
    """Load control plane from Redis if present."""
    from app.core.config import settings

    if not settings.ops_persist_enabled:
        return False
    try:
        import redis as redis_lib

        client = redis_lib.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        try:
            raw = client.get("ops:control_plane")
            if not raw:
                return False
            get_store().load_redis_payload(json.loads(raw))
            return True
        finally:
            client.close()
    except Exception:
        logger.debug("ops restore skipped", exc_info=True)
        return False


def ensure_default_hetzner(
    base_url: str,
    region: str | None = None,
    *,
    ws_base_url: str | None = None,
) -> CloudProvider:
    """Register or refresh the local/Hetzner stack as the primary provider."""
    store = get_store()
    existing = [
        p for p in store.list_providers() if p.type == ProviderType.HETZNER
    ]
    if existing:
        provider = existing[0]
        updates: dict[str, Any] = {}
        if base_url and provider.base_url != base_url.rstrip("/"):
            updates["base_url"] = base_url.rstrip("/")
        if ws_base_url is not None:
            updates["ws_base_url"] = ws_base_url.rstrip("/") if ws_base_url else None
        if region and provider.region != region:
            updates["region"] = region
        if updates:
            provider = store.upsert_provider(provider.model_copy(update=updates))
        return provider

    provider = CloudProvider(
        id="prov_hetzner_local",
        type=ProviderType.HETZNER,
        name="Hetzner (primary)",
        base_url=base_url,
        region=region or "fsn1",
        ws_base_url=ws_base_url.rstrip("/") if ws_base_url else None,
        tags=["primary", "local"],
    )
    store.upsert_provider(provider)
    store.append_event(
        OpsEvent(
            event_type="provider_registered",
            provider_id=provider.id,
            details={"type": provider.type.value, "base_url": provider.base_url},
        )
    )
    return provider
