#!/usr/bin/env python3
"""Verify that every relative markdown link in tracked docs resolves to a real file.

Walks all git-tracked ``*.md`` files, extracts markdown links ``[text](target)``,
skips external (``http(s)://``, ``mailto:``, ``tel:``) and pure ``#anchor`` links,
strips any ``#anchor`` / link title, resolves the remaining relative path against the
containing file's directory (or the repo root for ``/``-rooted targets), and asserts
the target exists on disk.

Fenced code blocks (``` ... ```) are ignored so example links in code don't count.

Exit code 0 and "0 broken links" when clean; exit code 1 listing every broken link
otherwise. No third-party dependencies.

Usage:
    python -m scripts.check_doc_links
    python scripts/check_doc_links.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

# [text](target) — target captured lazily up to the first unescaped ')'.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "//")


def _repo_root() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _tracked_markdown(root: str) -> list[str]:
    # Staged renames/additions are included, so this reflects the tree as it will
    # be committed.
    out = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        check=True,
        capture_output=True,
        text=True,
        cwd=root,
    )
    return [line for line in out.stdout.splitlines() if line]


def _link_targets(text: str) -> list[tuple[int, str]]:
    """Yield (line_number, raw_target) for each markdown link outside code fences."""
    results: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in _LINK_RE.finditer(line):
            results.append((lineno, match.group(1).strip()))
    return results


def _resolve(target: str, md_path: str, root: str) -> str | None:
    """Return the on-disk path a link points to, or None if it isn't a local file link."""
    target = target.strip()
    if not target or target.startswith("#"):
        return None
    if target.lower().startswith(_EXTERNAL_PREFIXES):
        return None
    # Drop a link title:  (path "Title")  ->  path
    target = target.split()[0]
    # Drop an anchor:  path#section  ->  path
    target = target.split("#", 1)[0]
    if not target:
        return None
    if target.startswith("/"):
        return os.path.normpath(os.path.join(root, target.lstrip("/")))
    base = os.path.dirname(os.path.join(root, md_path))
    return os.path.normpath(os.path.join(base, target))


def main() -> int:
    root = _repo_root()
    broken: list[str] = []
    checked = 0
    for md_path in _tracked_markdown(root):
        abs_md = os.path.join(root, md_path)
        try:
            with open(abs_md, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            broken.append(f"{md_path}: could not read ({exc})")
            continue
        for lineno, raw in _link_targets(text):
            resolved = _resolve(raw, md_path, root)
            if resolved is None:
                continue
            checked += 1
            if not os.path.exists(resolved):
                rel = os.path.relpath(resolved, root)
                broken.append(f"{md_path}:{lineno}: broken link -> {raw}  (missing: {rel})")

    if broken:
        print(f"{len(broken)} broken link(s) found ({checked} local links checked):\n")
        for entry in broken:
            print(f"  {entry}")
        return 1
    print(f"0 broken links ({checked} local links checked across tracked *.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
