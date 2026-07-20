"""Provider adapter + bootstrap tests."""

from app.ops.bootstrap import bootstrap_ops_control_plane
from app.ops.models import ProviderType
from app.ops.store import reset_store
from app.providers.cloud import get_adapter
from unittest.mock import patch


def test_adapters_validate() -> None:
    from app.ops.models import CloudProvider

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

    gcp_metrics = get_adapter(ProviderType.GCP).fetch_metrics(
        CloudProvider(
            id="g",
            type=ProviderType.GCP,
            name="GCP",
            base_url="http://gcp.example",
        )
    )
    assert gcp_metrics["source"] == "gcp_monitoring"


def test_bootstrap_seeds_hetzner_and_cloud_env() -> None:
    reset_store()
    with patch("app.ops.bootstrap.restore_store", return_value=False):
        with patch("app.ops.bootstrap.persist_store"):
            with patch("app.ops.bootstrap.settings") as mock_settings:
                mock_settings.ops_local_base_url = "http://127.0.0.1:8000"
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
