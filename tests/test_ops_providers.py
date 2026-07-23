"""Provider adapter + bootstrap tests."""

from unittest.mock import patch

from app.ops.bootstrap import bootstrap_ops_control_plane
from app.ops.models import CloudProvider, ProviderType
from app.ops.store import reset_store
from app.providers.cloud import GcpAdapter, get_adapter


def test_adapters_validate() -> None:
    aws = CloudProvider(
        id="a",
        type=ProviderType.AWS,
        name="AWS",
        base_url="http://aws.example",
        credentials_ref="AWS_ROLE_ARN",
        region="us-east-1",
    )
    result = get_adapter(ProviderType.AWS).validate_connection(aws)
    assert result["ok"] is True
    metrics = get_adapter(ProviderType.AWS).fetch_metrics(aws)
    assert metrics["source"] == "cloudwatch"


def test_gcp_adapter_metadata_only() -> None:
    gcp = CloudProvider(
        id="g",
        type=ProviderType.GCP,
        name="GCP",
        base_url="http://gcp.example:8000",
        credentials_ref="GCP_SERVICE_ACCOUNT_JSON",
        region="us-central1",
    )
    adapter = get_adapter(ProviderType.GCP)
    assert isinstance(adapter, GcpAdapter)

    metrics = adapter.fetch_metrics(gcp)

    assert metrics["source"] == "gcp_self_report"
    assert metrics["available"] is True
    assert metrics["region"] == "us-central1"
    assert metrics["credentials_ref_configured"] is True
    assert "self-report" in metrics["note"].lower() or "health" in metrics["note"].lower()


def test_gcp_adapter_missing_base_url() -> None:
    gcp = CloudProvider(
        id="g",
        type=ProviderType.GCP,
        name="GCP",
        base_url="",
    )
    metrics = get_adapter(ProviderType.GCP).fetch_metrics(gcp)
    assert metrics["available"] is False
    assert metrics["source"] == "gcp_self_report"


def test_bootstrap_seeds_hetzner_and_cloud_env() -> None:
    reset_store()
    with patch("app.ops.bootstrap.restore_store", return_value=False):
        with patch("app.ops.bootstrap.persist_store"):
            with patch("app.ops.bootstrap.settings") as mock_settings:
                mock_settings.ops_local_base_url = "http://127.0.0.1:8000"
                mock_settings.ops_public_ws_base_url = "ws://5.78.186.223"
                mock_settings.ops_hetzner_region = "fsn1"
                mock_settings.ops_aws_base_url = "http://aws.example:8000"
                mock_settings.ops_aws_region = "us-east-1"
                mock_settings.ops_aws_credentials_ref = "AWS_ROLE_ARN"
                mock_settings.ops_gcp_base_url = "http://gcp.example:8000"
                mock_settings.ops_gcp_region = "us-central1"
                mock_settings.ops_gcp_credentials_ref = "GCP_SA"
                mock_settings.ops_preferred_provider_id = None
                mock_settings.ops_failover_failure_threshold = 3
                mock_settings.ops_failover_recovery_threshold = 2
                mock_settings.ops_latency_threshold_ms = 5000.0
                bootstrap_ops_control_plane()

    from app.ops.store import get_store

    store = get_store()
    types = {p.type for p in store.list_providers()}
    assert ProviderType.HETZNER in types
    assert ProviderType.AWS in types
    assert ProviderType.GCP in types
    hetzner = next(p for p in store.list_providers() if p.type == ProviderType.HETZNER)
    assert hetzner.ws_base_url == "ws://5.78.186.223"
