"""Host CPU / memory / network metrics for self-reported /health payloads."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def collect_host_metrics() -> dict[str, Any]:
    """
    Return host metrics for GET /health.

    Uses psutil when available. On ImportError or any collection failure,
    returns {} so /health still succeeds with status/redis only.
    """
    try:
        import psutil
    except ImportError:
        return {}

    try:
        # interval=0 is non-blocking (uses last sample / immediate estimate).
        cpu_percent = float(psutil.cpu_percent(interval=0))
        mem_percent = float(psutil.virtual_memory().percent)
        out: dict[str, Any] = {
            "cpu_percent": round(cpu_percent, 1),
            "mem_percent": round(mem_percent, 1),
        }
        try:
            net = psutil.net_io_counters()
            if net is not None:
                out["network"] = {
                    "bytes_sent": int(net.bytes_sent),
                    "bytes_recv": int(net.bytes_recv),
                }
        except Exception:
            pass
        return out
    except Exception:
        logger.debug("host metrics collection failed", exc_info=True)
        return {}
