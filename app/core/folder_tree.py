"""Virtual folder tree derived from agent registry folder_path values.

Keep in sync with frontend/src/data/folderTree.ts
"""

from __future__ import annotations

from app.agents.registry import AGENT_REGISTRY

# Canonical tree structure — branch label → full leaf paths.
_FOLDER_TREE_SPEC: list[tuple[str, list[str]]] = [
    ("Science", ["Science/Chemistry", "Science/Biology"]),
    ("Social Studies", ["Social Studies/Economics"]),
    ("Arts", ["Arts/Visual"]),
    ("Design", ["Design/UI"]),
    ("Coding", ["Coding/Projects"]),
    ("Research", ["Research/Topics"]),
    ("Assistant", ["Assistant/General"]),
    ("Media", ["Media/Photo", "Media/Video", "Media/Audio"]),
]

FOLDER_TREE: list[dict[str, str | list[str]]] = [
    {"label": label, "children": children}
    for label, children in _FOLDER_TREE_SPEC
]


def all_folder_paths() -> list[str]:
    """Return all leaf folder paths from the registry (deduplicated, sorted)."""
    paths = {agent.folder_path for agent in AGENT_REGISTRY.values()}
    return sorted(paths)


def validate_tree_matches_registry() -> None:
    """Assert folder tree leaves match registry paths (for tests)."""
    tree_paths = {child for _label, children in _FOLDER_TREE_SPEC for child in children}
    registry_paths = set(all_folder_paths())
    assert tree_paths == registry_paths, (
        f"folder_tree drift: tree={tree_paths - registry_paths} "
        f"registry={registry_paths - tree_paths}"
    )
