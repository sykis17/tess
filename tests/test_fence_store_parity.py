"""Parity: RedisFenceStore and EtcdFenceStore honor one FenceStore contract.

The Redis side runs against the faithful Lua fake (real Lua is covered by the
split-brain harness scenario s07). The etcd side runs against a live single-node
etcd and skips when none is reachable — set ``OPS_TEST_ETCD_ENDPOINT`` (or
``OPS_ETCD_ENDPOINTS``) to a host-reachable gateway, e.g.::

    OPS_TEST_ETCD_ENDPOINT=http://127.0.0.1:12379 pytest tests/test_fence_store_parity.py

Both backends are driven through the *same* ``_assert_fence_store_contract`` — that
shared assertion is the parity guarantee.
"""

from __future__ import annotations

import os

import pytest

from app.ops.consensus import _b64, etcd_post
from app.ops.store import EtcdFenceStore, RedisFenceStore
from tests.fence_fakes import _FakeRedis


def _assert_fence_store_contract(store) -> None:
    """Backend-agnostic FenceStore contract. ``store`` must start empty."""
    # 1. Fresh: no term, no blob.
    assert store.read_term() == 0
    assert store.read_blob() is None

    # 2. Promote onto a fresh store installs the term.
    assert store.promote_term(5) is True
    assert store.read_term() == 5

    # 3. Re-promoting the same term is an idempotent success (no self-demote).
    assert store.promote_term(5) is True
    assert store.read_term() == 5

    # 4. Promoting a strictly lower term is rejected; stored term unchanged.
    assert store.promote_term(3) is False
    assert store.read_term() == 5

    # 5. Promoting a higher term installs it.
    assert store.promote_term(7) is True
    assert store.read_term() == 7

    # 6. CAS persist with the matching term writes the blob.
    assert store.cas_persist(7, '{"v": "A"}') is True
    assert store.read_blob() == '{"v": "A"}'

    # 7. CAS persist with a stale term is rejected; blob unchanged.
    assert store.cas_persist(6, '{"v": "B"}') is False
    assert store.read_blob() == '{"v": "A"}'

    # 8. Unconditional write_blob overwrites regardless of term.
    store.write_blob('{"v": "C"}')
    assert store.read_blob() == '{"v": "C"}'


def test_redis_fence_store_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr("app.ops.store._redis_client", lambda: fake)
    _assert_fence_store_contract(RedisFenceStore())


# --- etcd side (skips without a reachable gateway) ---------------------------

def _test_etcd_endpoint() -> str | None:
    ep = (os.environ.get("OPS_TEST_ETCD_ENDPOINT") or "").strip()
    if not ep:
        raw = (os.environ.get("OPS_ETCD_ENDPOINTS") or "").strip()
        ep = raw.split(",")[0].strip() if raw else ""
    if ep and not ep.startswith("http"):
        ep = f"http://{ep}"
    return ep or None


_ETCD_ENDPOINT = _test_etcd_endpoint()
_TEST_TERM_KEY = "/tess/ops/parity_test/fence_term"
_TEST_BLOB_KEY = "/tess/ops/parity_test/blob"

etcd_required = pytest.mark.skipif(
    _ETCD_ENDPOINT is None,
    reason="no etcd endpoint (set OPS_TEST_ETCD_ENDPOINT=http://host:port)",
)


def _etcd_clear(endpoint: str) -> None:
    for key in (_TEST_TERM_KEY, _TEST_BLOB_KEY):
        etcd_post(endpoint, "/v3/kv/deleterange", {"key": _b64(key)})


@etcd_required
def test_etcd_fence_store_contract() -> None:
    endpoint = _ETCD_ENDPOINT
    assert endpoint is not None
    _etcd_clear(endpoint)
    try:
        store = EtcdFenceStore(
            endpoint, term_key=_TEST_TERM_KEY, blob_key=_TEST_BLOB_KEY
        )
        _assert_fence_store_contract(store)
    finally:
        _etcd_clear(endpoint)


@etcd_required
def test_etcd_promote_retry_exhaustion_raises() -> None:
    """A key stuck below the target that never accepts the CAS surfaces as a
    (non-fence) PersistError, not a silent stale-term reject."""
    from app.ops.fencing import PersistError

    endpoint = _ETCD_ENDPOINT
    assert endpoint is not None
    _etcd_clear(endpoint)
    try:
        # max_promote_retries=1: force exhaustion by seeding a lower term and
        # racing it back down on every read via a custom store whose read always
        # returns a value below target while the CAS can never land.
        store = EtcdFenceStore(
            endpoint,
            term_key=_TEST_TERM_KEY,
            blob_key=_TEST_BLOB_KEY,
            max_promote_retries=1,
        )
        # Seed term=2 directly, then monkeypatch read_term to always report 1
        # (< target 5) so the VALUE==1 CAS never matches the real stored 2.
        etcd_post(endpoint, "/v3/kv/put",
                  {"key": _b64(_TEST_TERM_KEY), "value": _b64("2")})
        store.read_term = lambda: 1  # type: ignore[method-assign]
        with pytest.raises(PersistError):
            store.promote_term(5)
    finally:
        _etcd_clear(endpoint)


# --- payload-size guard (no network needed) ----------------------------------

def test_etcd_payload_size_guard_rejects_oversize() -> None:
    from app.ops.fencing import PersistError

    store = EtcdFenceStore("http://etcd.invalid:2379")  # never contacted
    huge = "x" * (EtcdFenceStore._MAX_BLOB_BYTES + 1)
    with pytest.raises(PersistError):
        store.write_blob(huge)
    with pytest.raises(PersistError):
        store.cas_persist(1, huge)
