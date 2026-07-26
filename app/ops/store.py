"""In-memory ops store with optional Redis persistence."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Protocol

from app.ops import metrics
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

# Reused etcd gateway helpers for the etcd-backed FenceStore. No circular import:
# app.ops.consensus imports only app.core.config.
from app.ops.consensus import (
    BLOB_KEY,
    FENCE_TERM_KEY,
    _b64,
    _unb64,
    etcd_post_failover,
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
REDIS_CONTROL_PLANE_KEY = "ops:control_plane"
REDIS_FENCE_TERM_KEY = "ops:control_plane:fence_term"

MAX_EVENTS = 2000
MAX_SNAPSHOTS = 2000

# Promote: idempotent monotonic install — install if stored term <= new (write
# when strictly lower; no-op rewrite when equal so re-promoting the same term
# succeeds instead of self-demoting; reject only when stored term is higher).
_LUA_PROMOTE_FENCE = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local nxt = tonumber(ARGV[1])
if cur <= nxt then
  redis.call('SET', KEYS[1], ARGV[1])
  return 1
end
return 0
"""

# Persist: write blob only when fence term matches exactly.
_LUA_PERSIST_CAS = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local term = tonumber(ARGV[1])
if cur == term then
  redis.call('SET', KEYS[2], ARGV[2])
  return 1
end
return 0
"""


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

    def to_redis_payload(self, *, fence_term: int | None = None) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
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
            if fence_term is not None:
                payload["fence_term"] = fence_term
            return payload

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


def _redis_client():
    import redis as redis_lib

    from app.core.config import settings

    return redis_lib.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )


class FenceStore(Protocol):
    """Durable fence store seam: mirrored CAS-guard term + control-plane blob.

    Pure storage. Backend implementations do the atomic term/blob operations and
    nothing else — severity handling (restore + demote + raise) and metrics live
    in the module-level wrappers below, so every backend inherits identical
    semantics. See ``deploy/MULTI_CLOUD.md`` for the fence contract.
    """

    def read_term(self) -> int:
        """Return the stored fence term (0 if absent)."""
        ...

    def promote_term(self, term: int) -> bool:
        """Idempotent monotonic install: succeed iff stored term <= ``term``
        (write when strictly lower, no-op when equal), reject iff stored > term.
        Accept -> True."""
        ...

    def cas_persist(self, term: int, payload: str) -> bool:
        """Write the blob iff stored term == ``term`` (atomic). Accept -> True."""
        ...

    def write_blob(self, payload: str) -> None:
        """Unconditional blob write (HA-off single-writer path)."""
        ...

    def read_blob(self) -> str | None:
        """Return the raw control-plane blob (None if absent)."""
        ...


class RedisFenceStore:
    """Redis-backed ``FenceStore`` — the two Lua CAS scripts + blob get/set.

    Each operation opens and closes its own client via the module-level
    ``_redis_client`` factory (kept as a module symbol so tests that
    ``monkeypatch`` it continue to inject their fake).
    """

    def read_term(self) -> int:
        client = _redis_client()
        try:
            raw = client.get(REDIS_FENCE_TERM_KEY)
            return int(raw) if raw is not None else 0
        finally:
            client.close()

    def promote_term(self, term: int) -> bool:
        client = _redis_client()
        try:
            ok = client.eval(
                _LUA_PROMOTE_FENCE,
                1,
                REDIS_FENCE_TERM_KEY,
                str(int(term)),
            )
            return int(ok) == 1
        finally:
            client.close()

    def cas_persist(self, term: int, payload: str) -> bool:
        client = _redis_client()
        try:
            ok = client.eval(
                _LUA_PERSIST_CAS,
                2,
                REDIS_FENCE_TERM_KEY,
                REDIS_CONTROL_PLANE_KEY,
                str(int(term)),
                payload,
            )
            return int(ok) == 1
        finally:
            client.close()

    def write_blob(self, payload: str) -> None:
        client = _redis_client()
        try:
            client.set(REDIS_CONTROL_PLANE_KEY, payload)
        finally:
            client.close()

    def read_blob(self) -> str | None:
        client = _redis_client()
        try:
            return client.get(REDIS_CONTROL_PLANE_KEY)
        finally:
            client.close()


class EtcdFenceStore:
    """etcd-backed ``FenceStore`` — authoritative term + durable blob in one
    linearizable store, via the etcd v3 gRPC-JSON gateway.

    Reuses the gateway helpers from :mod:`app.ops.consensus`. The term key is the
    same monotonic token consensus mints (``/tess/ops/cp/fence_term``); the blob
    key (``/tess/ops/cp/blob``) is the etcd counterpart of ``ops:control_plane``.
    Keys are overridable so tests can run the parity contract in an isolated
    namespace without touching live election state. Authoritative when
    ``ops_fence_authority == "etcd"`` (all endpoints, failover). The legacy
    ``redis`` authority uses ``RedisFenceStore`` instead.
    """

    # etcd's default --max-request-bytes is ~1.5 MiB; stay under it and fail with a
    # distinct (non-fence) error rather than letting an oversize blob surface as a
    # gateway 4xx mid-CAS. The blob grows with providers, so this is a real bound.
    _MAX_BLOB_BYTES = 1_500_000

    def __init__(
        self,
        endpoints: str | list[str],
        *,
        term_key: str = FENCE_TERM_KEY,
        blob_key: str = BLOB_KEY,
        timeout: float = 2.0,
        max_promote_retries: int = 5,
    ) -> None:
        if isinstance(endpoints, str):
            endpoints = endpoints.split(",")
        normalized: list[str] = []
        for raw in endpoints:
            e = raw.strip().rstrip("/")
            if not e:
                continue
            if not e.startswith("http"):
                e = f"http://{e}"
            normalized.append(e)
        # One endpoint -> single attempt (e.g. the parity tests' throwaway etcd);
        # many -> try-in-order failover so an authoritative durable write survives
        # a single-node loss.
        self._endpoints = normalized
        self._term_key = term_key
        self._blob_key = blob_key
        self._timeout = timeout
        self._max_promote_retries = max_promote_retries

    def _post(self, path: str, body: dict) -> dict:
        return etcd_post_failover(self._endpoints, path, body, timeout=self._timeout)

    def _guard_size(self, payload: str) -> None:
        size = len(payload.encode("utf-8"))
        if size > self._MAX_BLOB_BYTES:
            from app.ops.fencing import PersistError

            raise PersistError(
                f"ops control-plane blob {size}B exceeds etcd request budget "
                f"{self._MAX_BLOB_BYTES}B"
            )

    def read_term(self) -> int:
        resp = self._post("/v3/kv/range", {"key": _b64(self._term_key)})
        kvs = resp.get("kvs") or []
        if not kvs:
            return 0
        raw = _unb64(kvs[0].get("value"))
        return int(raw) if raw else 0

    def read_blob(self) -> str | None:
        resp = self._post("/v3/kv/range", {"key": _b64(self._blob_key)})
        kvs = resp.get("kvs") or []
        if not kvs:
            return None
        return _unb64(kvs[0].get("value")) or None

    def write_blob(self, payload: str) -> None:
        self._guard_size(payload)
        self._post(
            "/v3/kv/put",
            {"key": _b64(self._blob_key), "value": _b64(payload)},
        )

    def cas_persist(self, term: int, payload: str) -> bool:
        """Write the blob iff the etcd term == ``term`` (single linearizable txn)."""
        self._guard_size(payload)
        txn = self._post(
            "/v3/kv/txn",
            {
                "compare": [
                    {
                        "key": _b64(self._term_key),
                        "target": "VALUE",
                        "value": _b64(str(int(term))),
                    }
                ],
                "success": [
                    {
                        "request_put": {
                            "key": _b64(self._blob_key),
                            "value": _b64(payload),
                        }
                    }
                ],
                "failure": [],
            },
        )
        return bool(txn.get("succeeded"))

    def promote_term(self, term: int) -> bool:
        """Idempotent monotonic install. Returns False iff a higher term is stored.

        etcd VALUE compares are lexicographic on bytes, so ``stored < term`` is not
        expressible as one txn on decimal strings ("9" > "10"). Read-then-CAS with a
        bounded retry loop instead (mirrors ``_increment_fence_term``): a concurrent
        writer that changes the term between read and CAS just retries; retry
        exhaustion raises (contention, not a stale-term reject).
        """
        target = int(term)
        for _ in range(self._max_promote_retries):
            current = self.read_term()
            if current > target:
                return False
            if current == target:
                return True
            if self._cas_install_term(current, target):
                return True
        from app.ops.fencing import PersistError

        raise PersistError(
            f"etcd promote fence term={target} exhausted retries under contention"
        )

    def _cas_install_term(self, expected: int, new: int) -> bool:
        """CAS the term key from ``expected`` to ``new``. Accept -> True.

        ``expected == 0`` means the key is absent (consensus mints terms starting
        at 1), so use a create-only compare; otherwise compare on the stored value.
        """
        if expected == 0:
            compare = {
                "key": _b64(self._term_key),
                "target": "CREATE",
                "create_revision": "0",
            }
        else:
            compare = {
                "key": _b64(self._term_key),
                "target": "VALUE",
                "value": _b64(str(expected)),
            }
        txn = self._post(
            "/v3/kv/txn",
            {
                "compare": [compare],
                "success": [
                    {
                        "request_put": {
                            "key": _b64(self._term_key),
                            "value": _b64(str(new)),
                        }
                    }
                ],
                "failure": [],
            },
        )
        return bool(txn.get("succeeded"))


_fence_store: FenceStore | None = None
_fence_store_lock = threading.Lock()


def _build_authoritative_store() -> FenceStore:
    """The durable store selected by ops_fence_authority (HA-active only)."""
    from app.core.config import settings

    if settings.ops_ha_active() and settings.ops_fence_authority == "etcd":
        # All endpoints -> failover so an authoritative durable write survives a
        # single-node loss. The failover ladder is bounded and, on the mutation
        # path, runs in the handler's offloaded thread (see app/api/ops.py).
        return EtcdFenceStore(settings.ops_etcd_endpoints, timeout=2.0)
    return RedisFenceStore()


def get_fence_store() -> FenceStore:
    """Return the authoritative fence store (Redis unless ops_fence_authority=etcd)."""
    global _fence_store
    with _fence_store_lock:
        if _fence_store is None:
            _fence_store = _build_authoritative_store()
        return _fence_store


def set_fence_store(store: FenceStore | None) -> None:
    """Override the active fence store (tests / backend selection)."""
    global _fence_store
    with _fence_store_lock:
        _fence_store = store


def reset_fence_store() -> FenceStore:
    """Reset to a fresh authoritative store per current ops_fence_authority."""
    global _fence_store
    with _fence_store_lock:
        _fence_store = _build_authoritative_store()
        return _fence_store


def promote_redis_fence(fence_term: int) -> None:
    """Install fence term on promote (idempotent CAS: stored term <= fence_term)."""
    from app.ops.fencing import FenceCasError, PersistError

    store = get_fence_store()
    try:
        auth_accept = store.promote_term(fence_term)
        if not auth_accept:
            metrics.record_cas("promote", "reject")
            raise FenceCasError(
                f"promote fence rejected term={fence_term} (stored={store.read_term()!r})"
            )
        metrics.record_cas("promote", "accept")
    except FenceCasError:
        raise
    except Exception as exc:
        logger.exception("promote fence failed term=%s", fence_term)
        raise PersistError(f"promote fence failed: {exc}") from exc


def persist_store(*, fence_term: int | None = None) -> None:
    """Persist ops control plane to Redis.

    When HA is active, uses Lua CAS on ``ops:control_plane:fence_term`` so a
    stale writer cannot clobber a newer primary (etcd-check-then-SET is not enough).
    When HA is off, uses unconditional SET (single-writer mode).
    """
    from app.core.config import settings
    from app.ops.fencing import FenceCasError, PersistError, resolve_write_fence_term

    if not settings.ops_persist_enabled:
        return

    store = get_fence_store()
    try:
        if settings.ops_ha_active():
            term = resolve_write_fence_term(fence_term=fence_term)
            payload = json.dumps(get_store().to_redis_payload(fence_term=term))
            # start_as_current_span re-raises on exception, so the CAS reject still
            # propagates to the FenceCasError handler below (restore + demote + raise).
            with metrics.get_tracer().start_as_current_span("ops.persist_cas") as _sp:
                _sp.set_attribute("ops.op", "persist")
                _sp.set_attribute("ops.fence_term", int(term))
                auth_accept = store.cas_persist(term, payload)
                if not auth_accept:
                    # Record before the existing restore/demote/raise; do not alter it.
                    _sp.set_attribute("ops.cas_result", "reject")
                    metrics.record_cas("persist", "reject")
                    metrics.record_fence_reject("cas_stale", "persist")
                    stored = store.read_term()
                    raise FenceCasError(
                        f"redis CAS persist rejected term={term} stored={stored!r}"
                    )
                _sp.set_attribute("ops.cas_result", "accept")
                metrics.record_cas("persist", "accept")
            return

        payload = json.dumps(get_store().to_redis_payload(fence_term=fence_term))
        store.write_blob(payload)
    except FenceCasError as exc:
        logger.error("ops persist CAS rejected: %s", exc)
        # Roll back in-memory mutations and demote — same severity as etcd reject.
        try:
            restore_store(raise_on_error=False)
        except Exception:
            logger.exception("restore after CAS reject failed")
        from app.ops.fencing import demote

        demote("redis_cas_rejected")
        raise
    except PersistError:
        raise
    except Exception as exc:
        logger.exception("ops persist failed")
        raise PersistError(f"ops persist failed: {exc}") from exc


def restore_store(*, raise_on_error: bool = False) -> bool:
    """Load control plane from Redis if present."""
    from app.core.config import settings

    if not settings.ops_persist_enabled:
        return False
    try:
        raw = get_fence_store().read_blob()
        if not raw:
            if settings.ops_ha_active() and settings.ops_fence_authority == "etcd":
                # Post-cutover there is no Redis fallback: an absent etcd durable blob is
                # either a fresh cluster (the primary re-persists on first election) or a
                # data-loss event needing explicit recovery. Log loudly; never silently
                # resurrect a stale Redis blob — that fossil is exactly what this step retired.
                logger.warning(
                    "durable etcd blob absent at restore; starting empty. Fresh cluster: the "
                    "primary persists on first election. Otherwise recover the durable blob "
                    "explicitly — there is no Redis fallback after the etcd cutover."
                )
            return False
        get_store().load_redis_payload(json.loads(raw))
        return True
    except Exception:
        logger.exception("ops restore failed")
        if raise_on_error:
            raise
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
