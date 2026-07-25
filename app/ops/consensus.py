"""etcd v3 lease campaign for ops control-plane primary election.

Talks to etcd via the embedded gRPC-JSON gateway (HTTP + base64 keys) using
httpx — no extra native dependency. Keys:

- ``/tess/ops/cp/leader`` — lease-bound; value = ``OPS_CP_INSTANCE_ID``
- ``/tess/ops/cp/fence_term`` — monotonic fencing token (decimal string)
"""

from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

LEADER_KEY = "/tess/ops/cp/leader"
FENCE_TERM_KEY = "/tess/ops/cp/fence_term"
# Durable control-plane blob key — etcd counterpart of Redis ``ops:control_plane``.
# Used by ``EtcdFenceStore`` (app/ops/store.py); consensus itself does not read it.
BLOB_KEY = "/tess/ops/cp/blob"


def _b64(raw: str | bytes) -> str:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _unb64(raw: str | None) -> str:
    if not raw:
        return ""
    return base64.b64decode(raw).decode("utf-8")


def etcd_post(endpoint: str, path: str, body: dict, *, timeout: float = 2.0) -> dict:
    """POST to an etcd v3 gRPC-JSON gateway endpoint and return the parsed JSON.

    Shared by ``EtcdHttpConsensus`` (election/term) and ``EtcdFenceStore`` (durable
    blob CAS) so both speak the gateway through one place.
    """
    url = f"{endpoint.rstrip('/')}{path}"
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()


def etcd_post_failover(
    endpoints: list[str], path: str, body: dict, *, timeout: float = 2.0
) -> dict:
    """Try each etcd endpoint in order; return the first success.

    A node that is down (transport error) or cannot serve the request (e.g. a
    linearizable read with no quorum -> 5xx) is skipped and the next endpoint is
    tried, so losing **one** of three etcd nodes does not fail the call. If **every**
    endpoint fails (quorum genuinely lost), the last error is raised — the caller
    (election / keepalive) then treats etcd as unreachable and demotes, which is the
    correct behavior once a majority is gone. etcd is Raft-replicated, so a lease or
    key created via one endpoint is visible through any other; calls need not stick
    to one node.
    """
    if not endpoints:
        raise RuntimeError("no etcd endpoints configured")
    last_exc: Exception | None = None
    for endpoint in endpoints:
        try:
            return etcd_post(endpoint, path, body, timeout=timeout)
        except httpx.HTTPError as exc:
            last_exc = exc
    assert last_exc is not None
    raise last_exc


@dataclass(frozen=True)
class LiveElection:
    """Fresh snapshot of etcd leader + fence term."""

    leader: str | None
    fence_term: int


class ConsensusBackend(Protocol):
    def read_election(self) -> LiveElection: ...

    def try_campaign(self, instance_id: str, lease_ttl_seconds: int) -> int | None:
        """Become leader if possible. Returns new fence term on win, else None."""

    def keepalive(self, lease_id: int) -> bool: ...

    def resign(self, lease_id: int | None) -> None: ...


class EtcdHttpConsensus:
    """etcd v3 JSON gateway client over one or more endpoints (comma string or list).

    With a 3-node cluster, all member client URLs are passed so a single node loss
    fails over to a surviving member (see ``etcd_post_failover``) instead of demoting
    the primary. A single endpoint still works (list of one).
    """

    def __init__(self, endpoints: str | list[str], *, timeout: float = 2.0) -> None:
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
        self._endpoints = normalized
        self._timeout = timeout
        self._lease_id: int | None = None

    def _post(self, path: str, body: dict) -> dict:
        return etcd_post_failover(self._endpoints, path, body, timeout=self._timeout)

    def read_election(self) -> LiveElection:
        leader_resp = self._post("/v3/kv/range", {"key": _b64(LEADER_KEY)})
        term_resp = self._post("/v3/kv/range", {"key": _b64(FENCE_TERM_KEY)})
        leader = None
        kvs = leader_resp.get("kvs") or []
        if kvs:
            leader = _unb64(kvs[0].get("value"))
        term = 0
        term_kvs = term_resp.get("kvs") or []
        if term_kvs:
            raw = _unb64(term_kvs[0].get("value"))
            term = int(raw) if raw else 0
        return LiveElection(leader=leader or None, fence_term=term)

    def try_campaign(self, instance_id: str, lease_ttl_seconds: int) -> int | None:
        grant = self._post(
            "/v3/lease/grant",
            {"TTL": str(int(lease_ttl_seconds)), "ID": "0"},
        )
        lease_id = int(grant["ID"])
        # Create-only put of leader key bound to lease.
        txn = self._post(
            "/v3/kv/txn",
            {
                "compare": [
                    {
                        "key": _b64(LEADER_KEY),
                        "target": "CREATE",
                        "create_revision": "0",
                    }
                ],
                "success": [
                    {
                        "request_put": {
                            "key": _b64(LEADER_KEY),
                            "value": _b64(instance_id),
                            "lease": str(lease_id),
                        }
                    }
                ],
                "failure": [
                    {
                        "request_range": {
                            "key": _b64(LEADER_KEY),
                        }
                    }
                ],
            },
        )
        if not txn.get("succeeded"):
            self._revoke(lease_id)
            return None

        self._lease_id = lease_id
        new_term = self._increment_fence_term()
        logger.info(
            "CP elected primary instance=%s fence_term=%s lease=%s",
            instance_id,
            new_term,
            lease_id,
        )
        return new_term

    def _increment_fence_term(self) -> int:
        current = self.read_election().fence_term
        nxt = current + 1
        # Compare-and-swap on value when present; otherwise create.
        if current == 0:
            # Key may be absent or explicitly 0.
            self._post(
                "/v3/kv/put",
                {"key": _b64(FENCE_TERM_KEY), "value": _b64(str(nxt))},
            )
            return nxt

        txn = self._post(
            "/v3/kv/txn",
            {
                "compare": [
                    {
                        "key": _b64(FENCE_TERM_KEY),
                        "target": "VALUE",
                        "value": _b64(str(current)),
                    }
                ],
                "success": [
                    {
                        "request_put": {
                            "key": _b64(FENCE_TERM_KEY),
                            "value": _b64(str(nxt)),
                        }
                    }
                ],
                "failure": [],
            },
        )
        if not txn.get("succeeded"):
            # Race: re-read (another primary may have advanced); still ours if we hold lease.
            live = self.read_election()
            if live.fence_term > current:
                return live.fence_term
            raise RuntimeError("failed to increment fence_term in etcd")
        return nxt

    def keepalive(self, lease_id: int) -> bool:
        try:
            resp = self._post(
                "/v3/lease/keepalive",
                {"ID": str(lease_id)},
            )
            result = resp.get("result") or resp
            ttl = result.get("TTL")
            return ttl is not None and int(ttl) > 0
        except Exception:
            logger.exception("etcd lease keepalive failed lease=%s", lease_id)
            return False

    def resign(self, lease_id: int | None) -> None:
        if lease_id is None:
            lease_id = self._lease_id
        if lease_id is not None:
            self._revoke(lease_id)
        self._lease_id = None

    def _revoke(self, lease_id: int) -> None:
        try:
            self._post("/v3/lease/revoke", {"ID": str(lease_id)})
        except Exception:
            logger.exception("etcd lease revoke failed lease=%s", lease_id)


class InMemoryConsensus:
    """Process-local fake for unit tests (not multi-process safe)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.leader: str | None = None
        self.fence_term: int = 0
        self._lease_id: int | None = None
        self._next_lease = 1
        self.keepalive_ok: bool = True

    def read_election(self) -> LiveElection:
        with self._lock:
            return LiveElection(leader=self.leader, fence_term=self.fence_term)

    def try_campaign(self, instance_id: str, lease_ttl_seconds: int) -> int | None:
        _ = lease_ttl_seconds
        with self._lock:
            if self.leader is not None and self.leader != instance_id:
                return None
            self.leader = instance_id
            self.fence_term += 1
            self._lease_id = self._next_lease
            self._next_lease += 1
            return self.fence_term

    def keepalive(self, lease_id: int) -> bool:
        _ = lease_id
        with self._lock:
            return self.keepalive_ok and self.leader is not None

    def resign(self, lease_id: int | None) -> None:
        _ = lease_id
        with self._lock:
            self.leader = None
            self._lease_id = None

    def force_leader(self, instance_id: str, term: int) -> None:
        with self._lock:
            self.leader = instance_id
            self.fence_term = term


_backend: ConsensusBackend | None = None
_backend_lock = threading.Lock()


def reset_consensus_backend() -> None:
    global _backend
    with _backend_lock:
        _backend = None


def set_consensus_backend(backend: ConsensusBackend | None) -> None:
    global _backend
    with _backend_lock:
        _backend = backend


def get_consensus_backend() -> ConsensusBackend:
    global _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        if not settings.ops_ha_active():
            raise RuntimeError("consensus backend requested while HA is disabled")
        # Pass all endpoints so the client fails over across the 3-node cluster.
        _backend = EtcdHttpConsensus(settings.ops_etcd_endpoints)
        return _backend


def first_etcd_endpoint() -> str | None:
    raw = settings.ops_etcd_endpoints.strip()
    if not raw:
        return None
    endpoint = raw.split(",")[0].strip()
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    return endpoint
