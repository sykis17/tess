"""Runtime posture + in-process egress guard tests (P2 Step 4).

Red-first record: the seam tests (factory / search_urls / fetch_page_text
refuse under sovereign-strict) were observed RED before the guards landed.
The planted-violation tests encode the red permanently: with the guard
disabled the canary SUCCEEDS (fake transport) and the strict startup
assertion fails loudly — proof the canary can see a violation, so its green
is non-vacuous.

Counting rule under test (subclass-leak guard): only ``EgressRefusedError``
counts as "refused by our own guard" — never a bare ``ValueError`` (which it
subclasses for the factory's refusal shape) and never a network failure (an
egress-blocked network must not impersonate the guard).
"""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

import app.search.provider as search_provider
from app.core import egress_guard
from app.core.config import Settings, settings
from app.core.egress_guard import (
    CANARY_TARGET_URL,
    OUTCOME_GUARD_MISSING,
    OUTCOME_NOT_APPLICABLE,
    OUTCOME_REFUSED,
    get_cached_result,
    run_canary,
    verify_posture_or_raise,
)
from app.api.ops import get_posture, rerun_posture_canary
from app.core.posture import (
    EgressRefusedError,
    RuntimePosture,
    is_internal_base_url,
    resolve_posture,
)
from app.llm.factory import create_llm
from app.llm.ollama import OllamaLLM
from app.search.fetcher import fetch_page_text
from app.search.provider import search_urls

STRICT = RuntimePosture.SOVEREIGN_STRICT.value
AVAIL = RuntimePosture.AVAILABILITY_FIRST.value


@pytest.fixture(autouse=True)
def _reset_canary_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(egress_guard, "_last_result", None)


def _set_posture(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(settings, "tess_runtime_posture", value)


def _ban_dial(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any client construction in the canary path fails the test (zero-socket)."""

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("canary constructed an HTTP client (socket path entered)")

    monkeypatch.setattr(egress_guard.httpx, "Client", _explode)


def _fake_dial(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route the canary's sync client through a MockTransport."""
    real_client = httpx.Client

    def _client(*_args: object, **_kwargs: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(egress_guard.httpx, "Client", _client)


# --- posture resolution (fail-closed, both ways) ---------------------------


def test_resolve_posture_known_values() -> None:
    assert resolve_posture("sovereign-strict") is RuntimePosture.SOVEREIGN_STRICT
    assert resolve_posture("availability-first") is RuntimePosture.AVAILABILITY_FIRST


def test_resolve_posture_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown TESS_RUNTIME_POSTURE"):
        resolve_posture("sovereign")


def test_settings_unknown_posture_raises_at_construction() -> None:
    # The field_validator runs at Settings() construction, so BOTH web and
    # worker processes fail closed on a typo'd posture — unlike the
    # fold-permissive product-mode/chain-profile validators.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tess_runtime_posture="strict")


def test_settings_default_posture_is_availability_first() -> None:
    assert Settings(_env_file=None).tess_runtime_posture == AVAIL


def test_posture_predicates_both_ways(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_posture(monkeypatch, STRICT)
    assert settings.posture_is_strict() is True
    assert settings.runtime_posture() is RuntimePosture.SOVEREIGN_STRICT
    _set_posture(monkeypatch, AVAIL)
    assert settings.posture_is_strict() is False
    assert settings.runtime_posture() is RuntimePosture.AVAILABILITY_FIRST


# --- B2 base-URL matrix (shipped defaults pass; public hosts refused) ------


@pytest.mark.parametrize(
    "url",
    [
        "http://ollama:11434",  # docker service name (single-label) — prod/offline/p2
        "http://host.docker.internal:11434",  # dev compose allowlist
        "http://localhost:11434",  # bare-dev default, allowlist
        "http://127.0.0.1:11434",
        "http://10.8.0.1:8000",  # WireGuard mesh peer (RFC 1918)
        "http://192.168.1.50:11434",
        "http://[::1]:11434",
    ],
)
def test_internal_base_urls_pass(url: str) -> None:
    assert is_internal_base_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8:11434",
        "https://api.example.com/v1",
        "https://ollama.example.com:11434",
        "",
        "not-a-url",
    ],
)
def test_external_base_urls_refused(url: str) -> None:
    assert is_internal_base_url(url) is False


# --- LLM factory seam ------------------------------------------------------


def test_factory_refuses_gemini_under_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_posture(monkeypatch, STRICT)
    with pytest.raises(EgressRefusedError):
        create_llm("gemini")


def test_factory_availability_first_error_shape_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Availability-first must be bit-identical to today: a missing Gemini key
    # still raises the plain config ValueError, never the guard's subclass.
    _set_posture(monkeypatch, AVAIL)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(ValueError) as exc_info:
        create_llm("gemini")
    assert not isinstance(exc_info.value, EgressRefusedError)


def test_factory_allows_ollama_internal_under_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, STRICT)
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    assert isinstance(create_llm("ollama"), OllamaLLM)


def test_factory_refuses_ollama_public_base_url_under_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, STRICT)
    monkeypatch.setattr(settings, "ollama_base_url", "https://ollama.example.com:11434")
    with pytest.raises(EgressRefusedError):
        create_llm("ollama")


def test_factory_allows_ollama_public_base_url_under_availability_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, AVAIL)
    monkeypatch.setattr(settings, "ollama_base_url", "https://ollama.example.com:11434")
    assert isinstance(create_llm("ollama"), OllamaLLM)


# --- search seams (both: finder path AND the cached-hit fetcher path) ------


def test_search_urls_refused_under_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_posture(monkeypatch, STRICT)
    with pytest.raises(EgressRefusedError):
        asyncio.run(search_urls("weather tomorrow"))


def test_fetch_page_text_refused_under_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    # Load-bearing second seam: resource_finder short-circuits search_urls on a
    # Redis cache hit, so cached hits reach the fetcher directly (live egress).
    _set_posture(monkeypatch, STRICT)
    with pytest.raises(EgressRefusedError):
        asyncio.run(fetch_page_text("https://example.com/article"))


def test_search_urls_availability_first_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, AVAIL)
    monkeypatch.setattr(settings, "tavily_api_key", None)

    async def _fake_ddgs(query: str, limit: int) -> list:
        return []

    monkeypatch.setattr(search_provider, "_search_ddgs", _fake_ddgs)
    assert asyncio.run(search_urls("anything")) == []


def test_fetch_page_text_availability_first_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, AVAIL)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>ok</html>"
        )
    )

    def _client(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    assert asyncio.run(fetch_page_text("https://example.com")) == "<html>ok</html>"


# --- canary: strict proves refusal BEFORE any socket -----------------------


def test_canary_target_is_rfc2606_inert() -> None:
    # The pinned target must stay on the reserved .invalid TLD: never
    # resolvable, so no real host is contacted even on guard regression.
    assert httpx.URL(CANARY_TARGET_URL).host.endswith(".invalid")


def test_canary_strict_refused_before_any_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, STRICT)
    _ban_dial(monkeypatch)  # zero-socket: client construction = test failure
    result = run_canary()
    assert result.outcome == OUTCOME_REFUSED
    assert result.posture == STRICT
    assert get_cached_result() is result


def test_canary_not_applicable_never_dials(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_posture(monkeypatch, AVAIL)
    _ban_dial(monkeypatch)  # no phone-home-shaped boot connection, ever
    result = run_canary()
    assert result.outcome == OUTCOME_NOT_APPLICABLE
    assert verify_posture_or_raise().outcome == OUTCOME_NOT_APPLICABLE


# --- planted violation (the red the guard must beat) -----------------------


def test_canary_planted_guard_off_succeeds_and_strict_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Guard disabled -> canary fetch SUCCEEDS -> guard-missing -> the strict
    # startup assertion raises. Proof the canary can see a violation.
    _set_posture(monkeypatch, STRICT)
    monkeypatch.setattr(egress_guard, "ensure_egress_allowed", lambda *a, **k: None)
    _fake_dial(monkeypatch, lambda request: httpx.Response(200))
    result = run_canary()
    assert result.outcome == OUTCOME_GUARD_MISSING
    with pytest.raises(RuntimeError, match="UNPROVEN"):
        verify_posture_or_raise()


def test_canary_network_failure_is_not_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An egress-blocked network (offline bundle) kills the dial with a
    # transport error — that must classify guard-missing, never refusal.
    _set_posture(monkeypatch, STRICT)
    monkeypatch.setattr(egress_guard, "ensure_egress_allowed", lambda *a, **k: None)

    def _dns_dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    _fake_dial(monkeypatch, _dns_dead)
    assert run_canary().outcome == OUTCOME_GUARD_MISSING


def test_canary_wrong_valueerror_is_not_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Subclass-leak guard: EgressRefusedError subclasses ValueError, so the
    # canary must count the exact guard type — a malformed-config ValueError
    # from the guarded call is NOT a refusal.
    _set_posture(monkeypatch, STRICT)

    def _config_error(*_args: object, **_kwargs: object) -> None:
        raise ValueError("malformed config")

    monkeypatch.setattr(egress_guard, "ensure_egress_allowed", _config_error)
    assert run_canary().outcome == OUTCOME_GUARD_MISSING


# --- ops artifact endpoints ------------------------------------------------


def test_ops_posture_artifact_reports_cached_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, STRICT)
    _ban_dial(monkeypatch)
    run_canary()
    body = asyncio.run(get_posture())
    assert body["posture"] == STRICT
    assert body["canary"]["outcome"] == OUTCOME_REFUSED
    assert body["instance_id"] == settings.ops_cp_instance_id


def test_ops_posture_artifact_before_any_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, AVAIL)
    body = asyncio.run(get_posture())
    assert body["posture"] == AVAIL
    assert body["canary"] is None


def test_ops_posture_canary_post_reruns_without_dialing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_posture(monkeypatch, AVAIL)
    _ban_dial(monkeypatch)
    body = asyncio.run(rerun_posture_canary("operator-test"))
    assert body["canary"]["outcome"] == OUTCOME_NOT_APPLICABLE
    assert get_cached_result() is not None
