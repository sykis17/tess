"""Bootstrap ops registry from settings and optional cloud env URLs."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.ops.models import CloudProvider, OpsEvent, ProviderType
from app.ops.store import (
    ensure_default_hetzner,
    get_store,
    persist_store,
    restore_store,
)

logger = logging.getLogger(__name__)


def bootstrap_ops_control_plane() -> None:
    """Restore Redis state or seed Hetzner + optional AWS/GCP endpoints."""
    restored = restore_store()
    store = get_store()

    ensure_default_hetzner(
        settings.ops_local_base_url,
        region=settings.ops_hetzner_region,
    )

    _ensure_cloud_from_env(
        provider_type=ProviderType.AWS,
        base_url=settings.ops_aws_base_url,
        name="AWS",
        region=settings.ops_aws_region,
        credentials_ref=settings.ops_aws_credentials_ref,
        stable_id="prov_aws",
    )
    _ensure_cloud_from_env(
        provider_type=ProviderType.GCP,
        base_url=settings.ops_gcp_base_url,
        name="Google Cloud",
        region=settings.ops_gcp_region,
        credentials_ref=settings.ops_gcp_credentials_ref,
        stable_id="prov_gcp",
    )

    if settings.ops_preferred_provider_id:
        policy = store.get_policy()
        policy.preferred_provider_id = settings.ops_preferred_provider_id
        store.set_policy(policy)

    policy = store.get_policy()
    policy.failure_threshold = settings.ops_failover_failure_threshold
    policy.recovery_threshold = settings.ops_failover_recovery_threshold
    policy.latency_p95_threshold_ms = settings.ops_latency_threshold_ms
    store.set_policy(policy)

    persist_store()
    logger.info(
        "Ops control plane ready (restored=%s, providers=%s)",
        restored,
        len(store.list_providers()),
    )


def _ensure_cloud_from_env(
    *,
    provider_type: ProviderType,
    base_url: str | None,
    name: str,
    region: str | None,
    credentials_ref: str | None,
    stable_id: str,
) -> None:
    if not base_url:
        return
    store = get_store()
    existing = store.get_provider(stable_id)
    if existing:
        updated = existing.model_copy(
            update={
                "base_url": base_url.rstrip("/"),
                "region": region,
                "credentials_ref": credentials_ref,
                "enabled": True,
            }
        )
        store.upsert_provider(updated)
        return

    provider = CloudProvider(
        id=stable_id,
        type=provider_type,
        name=name,
        base_url=base_url.rstrip("/"),
        region=region,
        credentials_ref=credentials_ref,
        tags=[provider_type.value],
    )
    store.upsert_provider(provider)
    store.append_event(
        OpsEvent(
            event_type="provider_registered",
            provider_id=provider.id,
            details={
                "type": provider.type.value,
                "base_url": provider.base_url,
                "source": "env",
            },
        )
    )
