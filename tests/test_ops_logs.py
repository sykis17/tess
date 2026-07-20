"""Health logs and event log coverage."""

from app.ops.health_logs import combined_health_logs
from app.ops.models import CloudProvider, HealthSnapshot, OpsEvent, ProviderType
from app.ops.store import OpsStore


def test_combined_health_logs_merge_provider_metrics() -> None:
    store = OpsStore()
    store.upsert_provider(
        CloudProvider(
            id="p1",
            type=ProviderType.AWS,
            name="AWS",
            base_url="http://aws.example",
        )
    )
    store.append_snapshot(
        HealthSnapshot(
            provider_id="p1",
            http_ok=True,
            latency_ms=42.0,
            score=88.0,
            healthy=True,
            provider_metrics={"source": "cloudwatch", "cpu_utilization": 12},
        )
    )
    store.append_event(
        OpsEvent(event_type="probe", provider_id="p1", details={})
    )

    logs = combined_health_logs(provider_id="p1", store=store)
    assert len(logs) == 1
    assert logs[0]["own"]["latency_ms"] == 42.0
    assert logs[0]["provider_native"]["source"] == "cloudwatch"
    assert logs[0]["provider_type"] == "aws"

    events = store.list_events(provider_id="p1")
    assert len(events) == 1
