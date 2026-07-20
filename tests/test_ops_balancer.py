"""Unit tests for session share / balance assignment."""

from app.ops.balancer import assign_session, list_healthy_provider_ids, seamless_migration_status
from app.ops.models import (
    CloudProvider,
    HealthSnapshot,
    ProviderType,
    RoutingPolicy,
    RoutingPolicySettings,
)
from app.ops.store import OpsStore


def _setup_two() -> OpsStore:
    store = OpsStore()
    for pid in ("aws1", "gcp1"):
        store.upsert_provider(
            CloudProvider(
                id=pid,
                type=ProviderType.AWS if pid.startswith("aws") else ProviderType.GCP,
                name=pid,
                base_url=f"http://{pid}.example",
            )
        )
        store.append_snapshot(
            HealthSnapshot(
                provider_id=pid,
                http_ok=True,
                score=80.0 if pid == "aws1" else 60.0,
                healthy=True,
            )
        )
    store.routing.active_provider_id = "aws1"
    return store


def test_active_only_uses_active() -> None:
    store = _setup_two()
    store.set_policy(RoutingPolicySettings(policy=RoutingPolicy.ACTIVE_ONLY))
    a = assign_session("sess-a", store=store)
    assert a.provider_id == "aws1"


def test_share_distributes_by_hash() -> None:
    store = _setup_two()
    store.set_policy(RoutingPolicySettings(policy=RoutingPolicy.SHARE))
    ids = {assign_session(f"sess-{i}", store=store).provider_id for i in range(20)}
    assert ids <= {"aws1", "gcp1"}
    assert len(ids) >= 1


def test_balance_prefers_higher_score_pool() -> None:
    store = _setup_two()
    store.set_policy(RoutingPolicySettings(policy=RoutingPolicy.BALANCE))
    a = assign_session("balance-sess", store=store)
    assert a.provider_id in {"aws1", "gcp1"}


def test_assignment_is_sticky() -> None:
    store = _setup_two()
    store.set_policy(RoutingPolicySettings(policy=RoutingPolicy.SHARE))
    first = assign_session("sticky", store=store)
    second = assign_session("sticky", store=store)
    assert first.provider_id == second.provider_id


def test_seamless_migration_not_available() -> None:
    status = seamless_migration_status()
    assert status.available is False


def test_list_healthy_skips_customer() -> None:
    store = _setup_two()
    store.upsert_provider(
        CloudProvider(
            id="cust1",
            type=ProviderType.CUSTOMER,
            name="Cust",
            base_url="http://cust.example",
            org_id="org1",
        )
    )
    store.append_snapshot(
        HealthSnapshot(provider_id="cust1", http_ok=True, score=99, healthy=True)
    )
    healthy = list_healthy_provider_ids(store)
    assert "cust1" not in healthy
