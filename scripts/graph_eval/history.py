"""Sqlite history: one row per run, one per prompt result.

history.db is gitignored AND dockerignored (same commit as this writer).
The full schema — judge identity and separate judge-cost columns included —
lands here so the judge leg populates columns instead of migrating them;
judge fields stay NULL until a judge actually ran.
"""

from __future__ import annotations

import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version as _pkg_version
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    git_commit TEXT NOT NULL,
    git_dirty INTEGER NOT NULL,
    set_version TEXT NOT NULL,
    set_name TEXT NOT NULL,
    graph_provider TEXT NOT NULL,
    graph_model TEXT NOT NULL,
    judge_provider TEXT,
    judge_model TEXT,
    judge_prompt_version TEXT,
    prompts_total INTEGER NOT NULL,
    structural_passed INTEGER NOT NULL,
    judge_passed INTEGER,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    judge_prompt_tokens INTEGER,
    judge_completion_tokens INTEGER,
    judge_cost_usd REAL,
    wall_s REAL NOT NULL,
    result TEXT NOT NULL,
    langgraph_version TEXT,
    langchain_core_version TEXT
);
CREATE TABLE IF NOT EXISTS prompt_results (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    prompt_id TEXT NOT NULL,
    chain_profile TEXT NOT NULL,
    product_mode TEXT NOT NULL,
    structural_pass INTEGER NOT NULL,
    failures TEXT NOT NULL,
    judge_score REAL,
    judge_verdict TEXT,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    judge_prompt_tokens INTEGER,
    judge_completion_tokens INTEGER,
    judge_cost_usd REAL,
    latency_s REAL NOT NULL,
    outcome TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (run_id, prompt_id)
);
"""


@dataclass(frozen=True)
class RunRow:
    run_id: str
    ts_utc: str
    git_commit: str
    git_dirty: bool
    set_version: str
    set_name: str
    graph_provider: str
    graph_model: str
    judge_provider: str | None
    judge_model: str | None
    judge_prompt_version: str | None
    prompts_total: int
    structural_passed: int
    judge_passed: int | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    judge_prompt_tokens: int | None
    judge_completion_tokens: int | None
    judge_cost_usd: float | None
    wall_s: float
    result: str
    # W3: framework identity is part of the measurement identity, same class
    # as provider/model/judge — the venv drift the W3 handoff found would have
    # been visible in data with these columns.
    langgraph_version: str
    langchain_core_version: str


@dataclass(frozen=True)
class PromptRow:
    run_id: str
    prompt_id: str
    chain_profile: str
    product_mode: str
    structural_pass: bool
    failures: str  # json list
    judge_score: float | None
    judge_verdict: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    judge_prompt_tokens: int | None
    judge_completion_tokens: int | None
    judge_cost_usd: float | None
    latency_s: float
    outcome: str
    attempts: int


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def open_history(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    # The schema above only runs CREATE IF NOT EXISTS — a db created before
    # the W3 framework-version columns never gains them from it. Add them in
    # place; historical rows stay NULL, which is honest (their framework
    # identity was never recorded).
    _ensure_column(conn, "runs", "langgraph_version", "TEXT")
    _ensure_column(conn, "runs", "langchain_core_version", "TEXT")
    conn.commit()
    return conn


def framework_versions() -> tuple[str, str]:
    """(langgraph, langchain-core) versions of the environment running the eval."""
    return _pkg_version("langgraph"), _pkg_version("langchain-core")


def new_run_id() -> str:
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_identity(repo_root: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return commit, bool(porcelain)


def record_run(conn: sqlite3.Connection, row: RunRow) -> None:
    conn.execute(
        """INSERT INTO runs VALUES
           (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row.run_id,
            row.ts_utc,
            row.git_commit,
            int(row.git_dirty),
            row.set_version,
            row.set_name,
            row.graph_provider,
            row.graph_model,
            row.judge_provider,
            row.judge_model,
            row.judge_prompt_version,
            row.prompts_total,
            row.structural_passed,
            row.judge_passed,
            row.prompt_tokens,
            row.completion_tokens,
            row.cost_usd,
            row.judge_prompt_tokens,
            row.judge_completion_tokens,
            row.judge_cost_usd,
            row.wall_s,
            row.result,
            row.langgraph_version,
            row.langchain_core_version,
        ),
    )
    conn.commit()


def record_prompt_result(conn: sqlite3.Connection, row: PromptRow) -> None:
    conn.execute(
        """INSERT INTO prompt_results VALUES
           (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row.run_id,
            row.prompt_id,
            row.chain_profile,
            row.product_mode,
            int(row.structural_pass),
            row.failures,
            row.judge_score,
            row.judge_verdict,
            row.prompt_tokens,
            row.completion_tokens,
            row.cost_usd,
            row.judge_prompt_tokens,
            row.judge_completion_tokens,
            row.judge_cost_usd,
            row.latency_s,
            row.outcome,
            row.attempts,
        ),
    )
    conn.commit()
