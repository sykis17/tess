"""Fault-driver selection.

``OPS_HA_DRIVER`` picks the backend; ``get_driver(cfg)`` hands out the instance the
harness, observables, and scenarios inject their faults through.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .base import (
    DRIVER_NAMES,
    DriverError,
    FaultDriver,
    StreamHandle,
    UnknownDriverError,
    resolve_driver_name,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import HarnessConfig

__all__ = [
    "DRIVER_NAMES",
    "DriverError",
    "FaultDriver",
    "StreamHandle",
    "UnknownDriverError",
    "get_driver",
    "resolve_driver_name",
]


@lru_cache(maxsize=None)
def get_driver(cfg: "HarnessConfig") -> FaultDriver:
    """The driver for this config. Cached — a remote driver reuses SSH connections.

    Caching keys on the frozen config, so tests that build a fresh config per case get a
    fresh driver. ``HarnessConfig`` must stay hashable for this; a guard in
    tests/test_splitbrain_driver_seam.py pins that at unit level rather than letting an
    unhashable field surface twenty minutes into a harness run.
    """
    # Deferred: drivers.local -> docker_util -> config, and config imports this package
    # for name validation. Importing at call time keeps that cycle open.
    if cfg.driver_name == "local":
        from .local import LocalComposeDriver

        return LocalComposeDriver(cfg)
    if cfg.driver_name == "remote":
        raise NotImplementedError(
            "OPS_HA_DRIVER=remote: the remote fault driver lands in P2 Step 5b "
            "(scripts/ops_cp_splitbrain/drivers/remote.py); use local until then"
        )
    raise UnknownDriverError(f"unknown driver {cfg.driver_name!r}")
