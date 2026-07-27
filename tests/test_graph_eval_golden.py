"""Composition guards for the golden set — editing the set can never be silent.

Tallies here are executable claims about set_v1.json: an edit that changes
composition fails these tests until the numbers are consciously re-baselined
(bump set_version, update the constants, note the event in the commit).
"""

from scripts.graph_eval.golden import VALID_MODES, VALID_PROFILES, load_set

# Re-baseline: v1 = 20 prompts, smoke subset of 5 (Step-0 budget: warm L4 = 71s,
# smoke targets <= ~20 min, full stays under ~1h on the dev laptop).
EXPECTED_FULL_COUNT = 20
EXPECTED_SMOKE_COUNT = 5
# Re-baseline: v1 tags 4 prompts escalation-required (opener minimum is 3).
EXPECTED_ESCALATION_COUNT = 4

_MEDIA_AGENTS = {"photo", "video", "audio"}


def _golden():
    return load_set()


def test_set_version_present():
    assert _golden().set_version == "v1"


def test_exact_membership_counts():
    golden = _golden()
    assert len(golden.subset("full")) == EXPECTED_FULL_COUNT
    assert len(golden.subset("smoke")) == EXPECTED_SMOKE_COUNT
    # Loader construction guarantees smoke <= full; assert it stays true.
    smoke_ids = {p.id for p in golden.subset("smoke")}
    full_ids = {p.id for p in golden.subset("full")}
    assert smoke_ids <= full_ids


def test_every_chain_profile_present():
    profiles = {p.chain_profile for p in _golden().prompts}
    assert profiles == VALID_PROFILES  # L0, L1, L1+, L2, L3, L4 — all of them


def test_every_product_mode_present():
    modes = {p.product_mode for p in _golden().prompts}
    assert modes == VALID_MODES  # auto, research, planner, coding, builder


def test_escalation_tags():
    tagged = [p for p in _golden().prompts if "escalation-required" in p.tags]
    assert len(tagged) >= 3  # W5's escalation gate depends on these existing
    assert len(tagged) == EXPECTED_ESCALATION_COUNT


def test_smoke_subset_composition():
    smoke = _golden().subset("smoke")
    profiles = {p.chain_profile for p in smoke}
    assert "L0" in profiles
    assert "L4" in profiles
    assert any("escalation-required" in p.tags for p in smoke)


def test_media_agents_excluded_from_v1():
    golden = _golden()
    assert "media" in golden.notes.lower()  # the exclusion must stay documented
    for prompt in golden.prompts:
        expected = set(prompt.rubric.get("expect_agents_all", [])) | set(
            prompt.rubric.get("expect_agents_any", [])
        )
        assert not (expected & _MEDIA_AGENTS), prompt.id


def test_every_rubric_has_ceilings_and_content_floor():
    for prompt in _golden().prompts:
        assert "max_wall_s" in prompt.rubric, prompt.id
        assert "max_total_tokens" in prompt.rubric, prompt.id
        assert prompt.rubric.get("min_content_chars", 0) >= 10, prompt.id


def test_specialist_prompts_expect_agents():
    # Every non-L0 prompt must pin at least one expected agent — otherwise the
    # sabotage proof (wrong routing must fail the set) has nothing to bite on.
    for prompt in _golden().prompts:
        if prompt.chain_profile == "L0":
            continue
        rubric = prompt.rubric
        assert rubric.get("expect_agents_all") or rubric.get("expect_agents_any"), prompt.id
