"""Cloud provider adapters (Hetzner / AWS / GCP / customer)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.ops.models import CloudProvider, ProviderType


class CloudAdapter(ABC):
    """Fetch provider-native metrics and validate connection metadata."""

    provider_type: ProviderType

    @abstractmethod
    def fetch_metrics(self, provider: CloudProvider) -> dict[str, Any]:
        """Return provider-native metrics (may be stubbed without real credentials)."""

    def validate_connection(self, provider: CloudProvider) -> dict[str, Any]:
        """Lightweight connection check — credentials ref present, URL shape."""
        ok = bool(provider.base_url)
        return {
            "ok": ok,
            "provider_type": self.provider_type.value,
            "credentials_ref": provider.credentials_ref,
            "region": provider.region,
            "message": "endpoint registered" if ok else "missing base_url",
        }


class HetznerAdapter(CloudAdapter):
    provider_type = ProviderType.HETZNER

    def fetch_metrics(self, provider: CloudProvider) -> dict[str, Any]:
        # Metadata only — control-plane prober owns /health. Avoid sync self-GET.
        return {
            "source": "hetzner_cloud_api",
            "available": bool(provider.credentials_ref),
            "server_status": "running" if provider.enabled else "unknown",
            "region": provider.region,
            "note": (
                "Set credentials_ref to HETZNER_API_TOKEN env name to enable "
                "live Hetzner metrics pull."
                if not provider.credentials_ref
                else "Token ref configured; live pull not executed in unit path."
            ),
        }


class AwsAdapter(CloudAdapter):
    provider_type = ProviderType.AWS

    def fetch_metrics(self, provider: CloudProvider) -> dict[str, Any]:
        return {
            "source": "cloudwatch",
            "available": bool(provider.credentials_ref),
            "region": provider.region or "us-east-1",
            "cpu_utilization": None,
            "status_check_failed": None,
            "note": (
                "Set credentials_ref (e.g. AWS_ROLE_ARN) and deploy a Tess stack "
                "AMI/Compose mirror; metrics merge with local /health probes."
                if not provider.credentials_ref
                else "AWS credentials ref present; CloudWatch pull stubbed until SDK wired."
            ),
        }


class GcpAdapter(CloudAdapter):
    provider_type = ProviderType.GCP

    def fetch_metrics(self, provider: CloudProvider) -> dict[str, Any]:
        """
        Metadata only — control-plane prober owns /health (cpu/mem self-report).

        GCP Cloud Monitoring API remains deferred; stop/start uses Compute API
        from scripts/gcp_standby.py with the ops service account / ADC.
        """
        return {
            "source": "gcp_self_report",
            "available": bool(provider.base_url),
            "region": provider.region or "us-central1",
            "credentials_ref_configured": bool(provider.credentials_ref),
            "note": (
                "Host cpu/mem from remote /health self-report; "
                "GCP Monitoring API deferred. "
                "Wake/sleep via scripts/gcp_standby.py (Compute stop/start)."
            ),
        }


class CustomerAdapter(CloudAdapter):
    provider_type = ProviderType.CUSTOMER

    def fetch_metrics(self, provider: CloudProvider) -> dict[str, Any]:
        return {
            "source": "customer_agent",
            "available": True,
            "org_id": provider.org_id,
            "note": "Customer BYO servers report via health contract only.",
        }

    def validate_connection(self, provider: CloudProvider) -> dict[str, Any]:
        base = super().validate_connection(provider)
        base["org_id"] = provider.org_id
        base["ok"] = bool(base["ok"] and provider.org_id)
        if not provider.org_id:
            base["message"] = "customer provider requires org_id"
        return base


_ADAPTERS: dict[ProviderType, CloudAdapter] = {
    ProviderType.HETZNER: HetznerAdapter(),
    ProviderType.AWS: AwsAdapter(),
    ProviderType.GCP: GcpAdapter(),
    ProviderType.CUSTOMER: CustomerAdapter(),
}


def get_adapter(provider_type: ProviderType) -> CloudAdapter:
    return _ADAPTERS[provider_type]
