"""Phase 19 structured list format tests."""

from app.graph.list_format_utils import (
    apply_list_format,
    detect_list_intent,
    format_as_ranked_list,
    has_numbered_list,
)


def test_detect_list_intent_top_n() -> None:
    assert detect_list_intent("What are the top 5 careers in cybersecurity?")
    assert detect_list_intent("Top 10 beaches in Greece")


def test_detect_list_intent_negative() -> None:
    assert not detect_list_intent("Explain photosynthesis")
    assert not detect_list_intent("Write a Python sort function")


def test_has_numbered_list() -> None:
    content = "## Careers\n\n1. Analyst\n2. Engineer"
    assert has_numbered_list(content)


def test_format_as_ranked_list() -> None:
    result = format_as_ranked_list(["Analyst", "Engineer"], "Top careers")
    assert "1. Analyst" in result
    assert "2. Engineer" in result
    assert result.startswith("## Top careers")


def test_apply_list_format_converts_bullets() -> None:
    content = (
        "## Cybersecurity careers\n\n"
        "- Security analyst\n"
        "- Penetration tester\n"
        "- Incident responder\n"
        "- Cloud security engineer\n"
        "- GRC specialist"
    )
    user_input = "What are the top 5 careers in cybersecurity?"
    formatted, fmt = apply_list_format(content, user_input)

    assert fmt == "ranked_list"
    assert "1. Security analyst" in formatted
    assert "5. GRC specialist" in formatted


def test_apply_list_format_preserves_existing_numbered() -> None:
    content = "## Beaches\n\n1. Navagio\n2. Elafonissi\n3. Myrtos"
    user_input = "Top 10 beaches in Greece"
    formatted, fmt = apply_list_format(content, user_input)

    assert fmt == "ranked_list"
    assert formatted == content


def test_apply_list_format_non_list_unchanged() -> None:
    content = "Photosynthesis converts light to chemical energy."
    formatted, fmt = apply_list_format(content, "Explain photosynthesis")

    assert fmt is None
    assert formatted == content
