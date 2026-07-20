"""Customer BYO server registration with health gate."""

from __future__ import annotations

from app.ops.models import (
    ByoRegisterRequest,
    CloudProvider,
    OpsEvent,
    ProviderType,
    new_id,
)
from app.ops.prober import probe_provider
from app.ops.store import OpsStore, get_store, persist_store
from app.providers.cloud import get_adapter


async def register_customer_server(
    request: ByoRegisterRequest,
    *,
    store: OpsStore | None = None,
    require_healthy: bool = True,
) -> CloudProvider:
    """
    Register a customer-owned Tess-compatible endpoint.

    Health gate: must pass /health before joining the org pool.
    """
    ops = store or get_store()
    provider = CloudProvider(
        id=new_id("prov"),
        type=ProviderType.CUSTOMER,
        name=request.name,
        base_url=request.base_url.rstrip("/"),
        region=request.region,
        org_id=request.org_id,
        ws_base_url=request.ws_base_url,
        tags=["customer", "byo"],
        credentials_ref="BYO_API_KEY" if request.api_key else None,
    )

    validation = get_adapter(ProviderType.CUSTOMER).validate_connection(provider)
    if not validation.get("ok"):
        raise ValueError(validation.get("message") or "invalid customer provider")

    snapshot = await probe_provider(provider, store=ops)
    if require_healthy and not snapshot.healthy:
        ops.append_event(
            OpsEvent(
                event_type="byo_rejected",
                provider_id=provider.id,
                details={
                    "org_id": request.org_id,
                    "reason": snapshot.last_error or "unhealthy",
                    "score": snapshot.score,
                },
            )
        )
        raise ValueError(
            f"BYO health gate failed: {snapshot.last_error or 'unhealthy'} "
            f"(score={snapshot.score})"
        )

    ops.upsert_provider(provider)
    ops.append_event(
        OpsEvent(
            event_type="byo_registered",
            provider_id=provider.id,
            details={"org_id": request.org_id, "base_url": provider.base_url},
        )
    )
    persist_store()
    return provider
