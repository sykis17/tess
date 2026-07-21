"""Cloud provider adapters (Hetzner / AWS / GCP / customer)."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

import httpx

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


def _probe_http_health(
    provider: CloudProvider,
    *,
    source: str,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """
    HTTP /health probe for remote cloud adapters (latency + redis when present).

    Used by GcpAdapter today; native Monitoring APIs remain deferred. Do not call
    this from the local control-plane provider adapter — a sync self-GET can
    deadlock a single uvicorn worker during /ops/probe.
    """
    base: dict[str, Any] = {
        "source": source,
        "available": bool(provider.base_url),
        "region": provider.region,
        "credentials_ref_configured": bool(provider.credentials_ref),
        "http_ok": False,
        "latency_ms": None,
        "redis_ok": None,
        "status": None,
    }
    if not provider.base_url:
        base["note"] = "missing base_url; cannot probe /health"
        return base

    url = f"{provider.base_url.rstrip('/')}/health"
    parsed = urlparse(provider.base_url)
    verify = True
    if parsed.scheme == "https" and parsed.hostname:
        try:
            import ipaddress

            ipaddress.ip_address(parsed.hostname)
            verify = False
        except ValueError:
            verify = True

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds, verify=verify) as client:
            response = client.get(url)
        latency_ms = (time.perf_counter() - start) * 1000.0
        base["latency_ms"] = round(latency_ms, 2)
        base["http_ok"] = response.status_code == 200
        if response.status_code != 200:
            base["note"] = f"health returned http_{response.status_code}"
            return base
        try:
            body = response.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            base["status"] = body.get("status")
            redis_status = body.get("redis")
            if redis_status is not None:
                base["redis_ok"] = redis_status == "ok"
        base["note"] = "HTTP /health probe; native cloud monitoring deferred"
        return base
    except Exception as exc:
        base["latency_ms"] = round((time.perf_counter() - start) * 1000.0, 2)
        base["note"] = f"health probe failed: {exc}"
        return base


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
        Live HTTP /health + latency (+ redis when present) against the remote
        GCP Tess stack. Safe because GCP is not the control-plane process.

        GCP Monitoring API integration is deferred; stop/start uses Compute API
        from scripts/gcp_standby.py with the ops service account / ADC.
        """
        metrics = _probe_http_health(provider, source="gcp_http_health")
        metrics["region"] = provider.region or "us-central1"
        metrics["cpu_utilization"] = None
        metrics["instance_status"] = None
        if metrics.get("http_ok"):
            metrics["note"] = (
                "HTTP /health probe; GCP Monitoring API deferred. "
                "Wake/sleep via scripts/gcp_standby.py (Compute stop/start)."
            )
        return metrics


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
