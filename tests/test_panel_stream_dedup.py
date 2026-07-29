"""W3 resumed-stream panel dedup — the settled edge (plan tests 26-28, 30).

Investigation result (the reviewer-required first step of C4): more than one
node streams per turn — EVERY specialist streams when session_id is set
(app/agents/base.py), all sharing one panel_id — so the originally planned
consume-once ContextVar reset would corrupt: the first delta after a resume
can belong to a different stream than the one interrupted, and a blind reset
would wipe the wrong content.

But the protocol already carries the reset affordance: every streaming
producer publishes a non-streaming OPENER panel (content="") immediately
before its stream, and the frontend merges non-streaming panels as a
wholesale REPLACE. On resume, the re-executed node's opener resets the row
before its re-stream — identical semantics to a normal run, where each
opener already wipes the previous streamer's text (the row always shows the
CURRENT streamer; cross-specialist content reaches the user via the
presenter's pov_segments, not the streaming row). Completed nodes never
re-stream on resume: the loop re-emits their rehydrated writes without
executing them (pinned in tests/test_checkpoint_resume.py), and specialists
carry no panels in state, so nothing re-publishes their streams.

Therefore: no wire change, no stream_reset field, no contextvar. What must
stay true forever, made durable here:
1. mergePanelUpdate's content rule — streaming deltas APPEND, non-streaming
   panels REPLACE (Python mirror below; reciprocal comment at the TS site);
2. every streaming producer publishes its opener BEFORE the stream starts
   (discovery-based static guard — new producers are bound automatically);
3. the trip legs: without the opener, resume visibly doubles text — the
   mirror and the guard both have teeth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Python mirror of the frontend merge rule.
# Merge semantics mirrored from frontend/src/hooks/useWebSocket.ts
# mergePanelUpdate — the frontend has no test runner, so this mirror is the
# only executable pin. CHANGE BOTH TOGETHER.
# ---------------------------------------------------------------------------


def _merge_content(previous: str, incoming: str, is_streaming: bool) -> str:
    return previous + incoming if is_streaming else incoming


def _visible_after(events: list[tuple[str, bool]]) -> str:
    row = ""
    for content, is_streaming in events:
        row = _merge_content(row, content, is_streaming)
    return row


OPENER = ("", False)  # what base.py:78 / direct_responder.py:58 publish
A_TEXT = "alpha specialist full answer"
B_TEXT = "bravo specialist full answer"


def _stream(text: str, chunk: int = 5) -> list[tuple[str, bool]]:
    return [(text[i : i + chunk], True) for i in range(0, len(text), chunk)]


# --- 26/28. normal-run semantics the settlement rests on ----------------------


def test_normal_run_row_shows_current_streamer() -> None:
    events = [OPENER, *_stream(A_TEXT), OPENER, *_stream(B_TEXT)]
    assert _visible_after(events) == B_TEXT


# --- 27/30. THE settlement: resume never doubles, never regresses --------------


def test_resume_no_doubled_text_matches_uninterrupted_run() -> None:
    # Turn interrupted mid-B (A completed and streamed; B partial).
    interrupted = [OPENER, *_stream(A_TEXT), OPENER, *_stream(B_TEXT)[:2]]
    # Resume: only B re-executes; its opener resets the row, then full re-stream.
    # (A's rehydrated writes re-emit WITHOUT execution — no panels, no stream.)
    resumed = [OPENER, *_stream(B_TEXT)]

    visible = _visible_after(interrupted + resumed)
    uninterrupted = _visible_after([OPENER, *_stream(A_TEXT), OPENER, *_stream(B_TEXT)])

    assert visible == uninterrupted, "resume must reproduce the normal visible state"
    assert visible.count(B_TEXT) == 1, "doubled visible text after resume"


def test_resume_of_sole_streamer_no_doubled_text() -> None:
    # L0 / single-specialist case: interrupted mid-stream, nothing completed.
    interrupted = [OPENER, *_stream(A_TEXT)[:3]]
    resumed = [OPENER, *_stream(A_TEXT)]
    assert _visible_after(interrupted + resumed) == A_TEXT


def test_trip_resume_without_opener_doubles_text() -> None:
    """The corruption that returns if an opener is ever removed — and the
    proof the mirror assertion has teeth."""
    interrupted = [OPENER, *_stream(B_TEXT)[:2]]
    resumed_without_opener = _stream(B_TEXT)
    visible = _visible_after(interrupted + resumed_without_opener)
    assert visible != B_TEXT
    assert B_TEXT in visible  # partial + full concatenated = doubled fragment


# --- static guard: opener BEFORE stream, for every producer, forever -----------


def _assert_opener_precedes_stream(source: str, origin: str) -> None:
    opener = source.find("publish_panel(streaming_panel")
    stream = source.find("generate_with_panel_stream(")
    assert stream != -1, f"{origin}: streaming call not found"
    assert opener != -1, (
        f"{origin}: no opener publish — resumed re-streams would APPEND onto "
        "stale partial content (doubled visible text)"
    )
    assert opener < stream, f"{origin}: opener must be published BEFORE the stream"


def _discover_streaming_producers() -> list[tuple[Path, str]]:
    producers: list[tuple[Path, str]] = []
    for path in Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if (
            "generate_with_panel_stream(" in text
            and "def generate_with_panel_stream" not in text
        ):
            producers.append((path, text))
    return producers


def test_every_streaming_producer_opens_with_reset_panel() -> None:
    producers = _discover_streaming_producers()
    # base.py (specialists) + direct_responder today — if this shrinks, the
    # discovery went vacuous; a NEW producer is bound automatically.
    assert len(producers) >= 2, f"expected >=2 producers, found {len(producers)}"
    for path, text in producers:
        _assert_opener_precedes_stream(text, str(path))


def test_opener_guard_trips_on_reordered_source() -> None:
    planted = (
        "text = await generate_with_panel_stream(llm=llm)\n"
        "publish_panel(streaming_panel, session_id)\n"
    )
    with pytest.raises(AssertionError):
        _assert_opener_precedes_stream(planted, "planted")


def test_streaming_deltas_marked_streaming_in_stream_utils() -> None:
    # Both delta publishes must stay is_streaming=True (append semantics);
    # the openers rely on the default False (replace semantics).
    source = Path("app/graph/stream_utils.py").read_text(encoding="utf-8")
    assert source.count('"is_streaming": True') >= 2