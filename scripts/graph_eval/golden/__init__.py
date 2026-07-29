"""Golden-set loader with strict validation — malformed data fails loudly.

The data file carries a set_version; editing the set is a deliberate
re-baseline event (bump the version, note it inline). Every prompt belongs to
"full"; "smoke" is an opt-in subset, so smoke ⊆ full holds by construction.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.chain_profiles import ChainProfile
from app.core.product_modes import ProductMode

from scripts.graph_eval.rubrics import KNOWN_RUBRIC_KEYS

VALID_PROFILES = frozenset(p.value for p in ChainProfile)
VALID_MODES = frozenset(m.value for m in ProductMode)
VALID_SETS = frozenset({"smoke", "full"})

_PROMPT_KEYS = frozenset(
    {"id", "prompt", "chain_profile", "product_mode", "tags", "sets", "rubric"}
)
_TOP_KEYS = frozenset({"set_version", "notes", "prompts"})

DEFAULT_SET_PATH = Path(__file__).resolve().parent / "set_v1.json"

# Wall-profile calibration (P1 Step 4, conscious — never a silent multiplier).
# The set's max_wall_s ceilings are LAPTOP-calibrated (warm llama3.2, sequential
# behind the Ollama lock). A 4-vCPU CPU-only GH runner is a different instrument:
# probe run 30445817123 measured smoke walls 42.2/151.7/276.7/265.0/779.1 s
# (L0-L4) vs ~3.5 min laptop smoke total — l4 landed at 779 s against its 900 s
# laptop ceiling, and walls vary 2x run to run. "ci" scales every ceiling x3
# (l4: 2700 s), keeping the runaway-chain guard bounded while never tripping on
# honest CPU variance. Selected via GRAPH_EVAL_WALL_PROFILE; unknown names fail
# loud. Judge identity, thresholds, and set composition are NOT touched here.
_WALL_PROFILES: dict[str, int] = {"local": 1, "ci": 3}


def _wall_profile_factor() -> int:
    name = (os.environ.get("GRAPH_EVAL_WALL_PROFILE") or "local").strip() or "local"
    if name not in _WALL_PROFILES:
        raise ValueError(
            f"unknown GRAPH_EVAL_WALL_PROFILE {name!r} — "
            f"known profiles: {sorted(_WALL_PROFILES)}"
        )
    return _WALL_PROFILES[name]


@dataclass(frozen=True)
class GoldenPrompt:
    id: str
    prompt: str
    chain_profile: str
    product_mode: str
    tags: tuple[str, ...]
    sets: tuple[str, ...]
    rubric: dict[str, Any]


@dataclass(frozen=True)
class GoldenSet:
    set_version: str
    notes: str
    prompts: tuple[GoldenPrompt, ...]

    def subset(self, set_name: str) -> tuple[GoldenPrompt, ...]:
        if set_name not in VALID_SETS:
            raise ValueError(f"unknown set name: {set_name!r}")
        return tuple(p for p in self.prompts if set_name in p.sets)


def _fail(prompt_id: str, message: str) -> ValueError:
    return ValueError(f"golden set invalid at {prompt_id!r}: {message}")


def load_set(path: Path | None = None) -> GoldenSet:
    src = path or DEFAULT_SET_PATH
    wall_factor = _wall_profile_factor()
    raw = json.loads(src.read_text(encoding="utf-8"))

    unknown_top = set(raw) - _TOP_KEYS
    if unknown_top:
        raise ValueError(f"golden set invalid: unknown top-level keys {sorted(unknown_top)}")
    set_version = raw.get("set_version")
    if not isinstance(set_version, str) or not set_version:
        raise ValueError("golden set invalid: set_version missing or empty")
    prompts_raw = raw.get("prompts")
    if not isinstance(prompts_raw, list) or not prompts_raw:
        raise ValueError("golden set invalid: prompts missing or empty")

    prompts: list[GoldenPrompt] = []
    seen_ids: set[str] = set()
    for entry in prompts_raw:
        pid = entry.get("id", "<missing id>")
        unknown = set(entry) - _PROMPT_KEYS
        if unknown:
            raise _fail(pid, f"unknown keys {sorted(unknown)}")
        missing = _PROMPT_KEYS - set(entry)
        if missing:
            raise _fail(pid, f"missing keys {sorted(missing)}")
        if pid in seen_ids:
            raise _fail(pid, "duplicate id")
        seen_ids.add(pid)
        if not entry["prompt"].strip():
            raise _fail(pid, "empty prompt")
        if entry["chain_profile"] not in VALID_PROFILES:
            raise _fail(pid, f"invalid chain_profile {entry['chain_profile']!r}")
        if entry["product_mode"] not in VALID_MODES:
            raise _fail(pid, f"invalid product_mode {entry['product_mode']!r}")
        sets = entry["sets"]
        if not sets or not set(sets) <= VALID_SETS:
            raise _fail(pid, f"invalid sets {sets!r}")
        if "full" not in sets:
            raise _fail(pid, 'every prompt must belong to "full" (smoke is a subset)')
        rubric = entry["rubric"]
        unknown_rubric = set(rubric) - KNOWN_RUBRIC_KEYS
        if unknown_rubric:
            raise _fail(pid, f"unknown rubric keys {sorted(unknown_rubric)}")
        if wall_factor != 1 and rubric.get("max_wall_s") is not None:
            # single application site: the runaway-guard timeout and the
            # structural wall check both read the loaded rubric.
            rubric = dict(rubric, max_wall_s=rubric["max_wall_s"] * wall_factor)
        prompts.append(
            GoldenPrompt(
                id=pid,
                prompt=entry["prompt"],
                chain_profile=entry["chain_profile"],
                product_mode=entry["product_mode"],
                tags=tuple(entry["tags"]),
                sets=tuple(sets),
                rubric=dict(rubric),
            )
        )

    return GoldenSet(
        set_version=set_version,
        notes=str(raw.get("notes", "")),
        prompts=tuple(prompts),
    )
