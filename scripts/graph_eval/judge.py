"""Pinned LLM judge with a versioned prompt and a strict, loud parser.

Judge identity (provider + model + prompt version) is part of the measurement
and is recorded in every history row. The judge is pinned at temperature 0.0;
its token counts come from LLMResponse (the plain generate path) and are
recorded as separate judge-cost columns — never mixed into the graph's own
metric deltas.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.graph.model_costs import cost_usd
from app.llm.factory import create_llm
from app.llm.types import LLMConfig, LLMMessage, LLMRequest

from scripts.graph_eval.config import EvalConfig

# Bump on any wording change: a different judge prompt is a different measurement.
JUDGE_PROMPT_VERSION = "v1"

_SYSTEM_PROMPT = (
    "You are a strict evaluation judge for a multi-agent answer engine. "
    "Score the ANSWER for how well it addresses the USER PROMPT: relevance, "
    "correctness, completeness, and coverage of the requested perspectives. "
    "Respond with ONLY a JSON object, no other text, exactly of the form: "
    '{"score": <integer 0 to 10>, "verdict": "<one short sentence>"}'
)


class JudgeParseError(Exception):
    """The judge's output was not a valid score — never silently pass this."""


@dataclass(frozen=True)
class JudgeResult:
    score: float
    verdict: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float


def parse_judge_output(raw: str) -> tuple[float, str]:
    """Strict parse of the judge's JSON; raises JudgeParseError on any deviation.

    Tolerates only markdown code fences and surrounding prose around a single
    JSON object — the object itself must have exactly {"score", "verdict"}.
    """
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise JudgeParseError(f"no JSON object in judge output: {raw[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"judge output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"score", "verdict"}:
        raise JudgeParseError(f"judge JSON keys must be exactly score+verdict: {parsed!r}")
    score = parsed["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise JudgeParseError(f"judge score is not numeric: {score!r}")
    if not 0 <= score <= 10:
        raise JudgeParseError(f"judge score out of range 0-10: {score!r}")
    verdict = parsed["verdict"]
    if not isinstance(verdict, str) or not verdict.strip():
        raise JudgeParseError(f"judge verdict is not a non-empty string: {verdict!r}")
    return float(score), verdict.strip()


def build_judge_messages(prompt_text: str, answer: str, expected_povs: list[str]) -> list[LLMMessage]:
    povs = ", ".join(expected_povs) if expected_povs else "none specified"
    user = (
        f"USER PROMPT:\n{prompt_text}\n\n"
        f"REQUESTED PERSPECTIVES: {povs}\n\n"
        f"ANSWER:\n{answer}\n\n"
        'Return ONLY: {"score": <integer 0 to 10>, "verdict": "<one short sentence>"}'
    )
    return [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user),
    ]


async def judge_answer(
    cfg: EvalConfig,
    prompt_text: str,
    answer: str,
    expected_povs: list[str],
) -> JudgeResult:
    llm = create_llm(
        provider=cfg.judge_provider,
        config=LLMConfig(model=cfg.judge_model, temperature=cfg.judge_temperature),
    )
    response = await llm.generate(
        LLMRequest(messages=build_judge_messages(prompt_text, answer, expected_povs))
    )
    score, verdict = parse_judge_output(response.content)
    return JudgeResult(
        score=score,
        verdict=verdict,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        cost_usd=cost_usd(
            response.model, response.prompt_tokens or 0, response.completion_tokens or 0
        ),
    )
