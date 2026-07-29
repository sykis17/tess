"""P0.2 disconnect classification — Python mirror + source guard (docs/P0_OPENER.md).

The frontend labels a WS disconnect "provider changed" ONLY when the
server-authored last_failover_at CHANGED between socket open and close —
an opaque-string compare of two /ops/routing/notice reads (plus the in-band
baseline advance carried on ProviderChangedMessage). The old predicate
(`dropped > 0 || activeWs !== WS_BASE_URL`) fabricated a failover banner on
every plain disconnect in shipped prod config — the P0.2 defect.

The frontend has no test runner, so this mirror is the only executable pin of
classifyDisconnect in frontend/src/hooks/useWebSocket.ts — CHANGE BOTH
TOGETHER. The decision table below is the opener's, rows 1-14 verbatim.

Value states: UNKNOWN (fetch failed / never ran) is distinct from None
(server says "no failover ever recorded"); mirrored in TS as undefined vs null.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Python mirror of classifyDisconnect (useWebSocket.ts). CHANGE BOTH TOGETHER.
# ---------------------------------------------------------------------------

UNKNOWN = object()  # TS: undefined — fetch failed or never ran

T0_PRIME = "2026-07-28T23:59:59.000001+00:00"
T1 = "2026-07-29T10:00:00.000001+00:00"
T2 = "2026-07-29T10:05:00.000002+00:00"
T3 = "2026-07-29T10:10:00.000003+00:00"


def _classify(baseline: object, current: object) -> str:
    if baseline is UNKNOWN or current is UNKNOWN:
        return "connection_lost"  # conservative: never fabricate on missing data
    if current is None:
        return "connection_lost"  # no failover ever recorded
    if baseline is None:
        return "provider_changed"  # first-ever failover landed mid-session
    return "provider_changed" if current != baseline else "connection_lost"


def _advance_baseline(message_value: object) -> object:
    """In-band ProviderChangedMessage handler: advance the baseline from the
    message's pre-serialized last_failover_at; absent/empty -> UNKNOWN
    (conservative). Mirrors the assignment in the isProviderChangedMessage
    branch of useWebSocket.ts."""
    return message_value if message_value else UNKNOWN


# --- decision table rows 1-13 (docs/P0_OPENER.md §Resolved design) -----------


@pytest.mark.parametrize(
    ("row", "baseline", "current", "expected"),
    [
        (1, None, None, "connection_lost"),  # first-ever run, no history
        (2, T1, T1, "connection_lost"),  # THE P0 bug row: plain disconnect
        (3, T1, T2, "provider_changed"),  # real failover killed the socket
        (4, None, T1, "provider_changed"),  # first-ever failover, mid-session
        (5, T1, T3, "provider_changed"),  # failback A->B->A (id-compare misses)
        (6, T1, T2, "provider_changed"),  # dual peer lost, survivor == active
        (7, UNKNOWN, T2, "connection_lost"),  # baseline fetch failed at open
        (8, T1, UNKNOWN, "connection_lost"),  # close fetch failed
        (9, T1, T2, "provider_changed"),  # switch landed in close->fetch gap
        (10, T1, T1, "connection_lost"),  # server restart, no switch (durable)
        (11, T1, None, "connection_lost"),  # durable blob lost mid-session
        (12, T1, T0_PRIME, "provider_changed"),  # clock step back: change, not order
        (13, T1, T1, "connection_lost"),  # micro-second-identical double switch (accepted miss)
    ],
)
def test_decision_table_row(row: int, baseline: object, current: object, expected: str) -> None:
    assert _classify(baseline, current) == expected, f"row {row}"


# --- row 14: the in-band baseline advance (cold-review F2) -------------------


def test_row14_inband_failover_then_later_plain_disconnect() -> None:
    # Failover arrives in-band (socket stays open, banner shown); the handler
    # advances the baseline to the message's stamp. A LATER plain disconnect
    # must NOT re-report that switch.
    baseline = T1
    baseline = _advance_baseline(T2)  # ProviderChangedMessage.last_failover_at
    assert _classify(baseline, T2) == "connection_lost"


def test_row14_without_advance_is_the_fabrication() -> None:
    # The hole the advance exists to close: stale baseline + later plain
    # disconnect would fabricate a second failover from one real switch.
    stale_baseline = T1
    assert _classify(stale_baseline, T2) == "provider_changed"


def test_advance_with_absent_field_resets_to_unknown() -> None:
    # Message without the stamp (or empty) -> baseline unknown -> conservative.
    assert _classify(_advance_baseline(None), T2) == "connection_lost"
    assert _classify(_advance_baseline(""), T2) == "connection_lost"


# --- source guard: the hook must decide via classifyDisconnect, never the ----
# --- forbidden proxies (discovery-based; red against the pre-fix source) -----

_HOOK_PATH = Path("frontend/src/hooks/useWebSocket.ts")
_PANEL_TYPES_PATH = Path("frontend/src/types/panel.ts")


def _assert_sound_classifier_source(source: str, origin: str) -> None:
    assert "classifyDisconnect" in source, f"{origin}: classifyDisconnect missing"
    onclose = source.find("ws.onclose")
    assert onclose != -1, f"{origin}: onclose handler not found"
    assert source.find("classifyDisconnect(", onclose) != -1, (
        f"{origin}: onclose must decide via classifyDisconnect"
    )
    assert "last_failover_at" in source, f"{origin}: notice snapshot field missing"
    assert "sessions_dropped_last" not in source, (
        f"{origin}: forbidden token — the sticky never-reset counter must not "
        "re-enter the disconnect decision (P0.2 Defect B)"
    )
    assert "dropped > 0" not in source, (
        f"{origin}: forbidden predicate — any-disconnect-with-history was the "
        "P0.2 fabrication (Defect A gate)"
    )


def test_hook_source_uses_sound_classifier() -> None:
    _assert_sound_classifier_source(
        _HOOK_PATH.read_text(encoding="utf-8"), str(_HOOK_PATH)
    )


def test_panel_types_carry_message_stamp() -> None:
    # ProviderChangedMessage's TS mirror must carry the pre-serialized stamp
    # the in-band advance reads (optional with default — CLAUDE.md convention).
    assert "last_failover_at" in _PANEL_TYPES_PATH.read_text(encoding="utf-8")


def test_guard_trips_on_planted_unsound_source() -> None:
    # Planted source satisfies every OTHER assertion (classifier present and
    # called in onclose, stamp present) so only the forbidden predicate trips —
    # proof the guard is non-vacuous.
    planted = (
        "const c = classifyDisconnect(baseline, notice.last_failover_at);\n"
        "ws.onclose = () => { void classifyDisconnect(a, b); };\n"
        "if (dropped > 0 || (activeWs && activeWs !== WS_BASE_URL)) { banner(); }\n"
    )
    with pytest.raises(AssertionError):
        _assert_sound_classifier_source(planted, "planted")
