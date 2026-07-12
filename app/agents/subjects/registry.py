import re
from dataclasses import dataclass


@dataclass(frozen=True)
class POVDefinition:
    """Metadata for a disciplinary point-of-view agent."""

    pov_key: str
    pov: str
    folder_path: str
    keywords: tuple[str, ...]


POV_DEFINITIONS: tuple[POVDefinition, ...] = (
    POVDefinition(
        pov_key="chemistry",
        pov="Chemistry",
        folder_path="Science/Chemistry",
        keywords=(
            "ionic",
            "bonding",
            "molecule",
            "chemical",
            "chemistry",
            "reaction",
            "compound",
            "periodic",
            "acid",
            "base",
            "stoichiometry",
        ),
    ),
    POVDefinition(
        pov_key="biology",
        pov="Biology",
        folder_path="Science/Biology",
        keywords=(
            "photosynthesis",
            "cell",
            "organism",
            "biology",
            "dna",
            "gene",
            "ecosystem",
            "evolution",
            "mitosis",
            "protein",
        ),
    ),
    POVDefinition(
        pov_key="economics",
        pov="Economics",
        folder_path="Social Studies/Economics",
        keywords=(
            "supply",
            "demand",
            "gdp",
            "market",
            "economics",
            "inflation",
            "trade",
            "microeconomics",
            "macroeconomics",
            "elasticity",
        ),
    ),
    POVDefinition(
        pov_key="art",
        pov="Art",
        folder_path="Arts/Visual",
        keywords=(
            "aesthetic",
            "aesthetics",
            "composition",
            "color",
            "colour",
            "visual",
            "artistic",
            "style",
            "typography",
            "illustration",
            "look and feel",
            "visual hierarchy",
            "poster design",
            "cover look",
            "look",
            "cover",
        ),
    ),
    POVDefinition(
        pov_key="ui_design",
        pov="UI Design",
        folder_path="Design/UI",
        keywords=(
            "ui design",
            "user interface",
            "usability",
            "ux",
            "layout",
            "wireframe",
            "navigation",
            "accessibility",
            "interaction design",
            "interface pattern",
            "user experience",
            "app ui",
        ),
    ),
)

_POV_AGENT_KEYS: frozenset[str] = frozenset(definition.pov_key for definition in POV_DEFINITIONS)


def get_pov_agent_names() -> list[str]:
    """Return all registered POV agent keys."""
    return list(_POV_AGENT_KEYS)


def is_pov_agent(name: str) -> bool:
    """Return True when the agent key is a disciplinary POV agent."""
    return name in _POV_AGENT_KEYS


def get_pov_definition_for_agent(agent_name: str) -> POVDefinition | None:
    """Return the POV definition that owns an agent key."""
    for definition in POV_DEFINITIONS:
        if agent_name == definition.pov_key:
            return definition
    return None


_WORD_BOUNDARY_KEYWORDS: frozenset[str] = frozenset({
    "acid",
    "base",
    "cell",
    "gene",
    "gdp",
    "look",
    "cover",
    "market",
    "trade",
    "ux",
})


def _keyword_matches(text: str, keyword: str) -> bool:
    """Match keywords with word boundaries for short tokens that cause false positives."""
    if keyword in _WORD_BOUNDARY_KEYWORDS or len(keyword) <= 4:
        return bool(re.search(rf"\b{re.escape(keyword)}\b", text))
    return keyword in text


def _matched_povs(text: str) -> list[POVDefinition]:
    """Return POV definitions whose keywords appear in the text."""
    matched: list[POVDefinition] = []
    for definition in POV_DEFINITIONS:
        if any(_keyword_matches(text, keyword) for keyword in definition.keywords):
            matched.append(definition)
    return matched


def infer_pov_agents_from_keywords(text: str) -> list[str]:
    """Infer POV agent keys from disciplinary keywords."""
    normalized = text.lower().strip()
    if not normalized:
        return []

    return [definition.pov_key for definition in _matched_povs(normalized)]


def build_pov_routing_rules() -> str:
    """Generate WR routing rules for listed POV agents."""
    lines: list[str] = []
    for definition in POV_DEFINITIONS:
        lines.append(
            f'- Route {definition.pov.lower()} questions to "{definition.pov_key}" '
            f"({definition.pov} POV — {definition.folder_path})."
        )
    return "\n".join(lines)


def collect_pov_sources(agent_names: list[str]) -> list[str]:
    """Return display lens names for routed POV agents."""
    sources: list[str] = []
    for name in agent_names:
        definition = get_pov_definition_for_agent(name)
        if definition and definition.pov not in sources:
            sources.append(definition.pov)
    return sources
