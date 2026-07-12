from dataclasses import dataclass

from app.agents.schemas import AgentDepth


@dataclass(frozen=True)
class SubjectDefinition:
    """Metadata for a school-subject topic agent pair."""

    subject: str
    major_key: str
    minor_key: str
    folder_path: str
    keywords: tuple[str, ...]


SUBJECT_DEFINITIONS: tuple[SubjectDefinition, ...] = (
    SubjectDefinition(
        subject="Chemistry",
        major_key="chemistry_major",
        minor_key="chemistry_minor",
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
    SubjectDefinition(
        subject="Biology",
        major_key="biology_major",
        minor_key="biology_minor",
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
    SubjectDefinition(
        subject="Economics",
        major_key="economics_major",
        minor_key="economics_minor",
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
)

_MINOR_DEPTH_SIGNALS = (
    "brief",
    "overview",
    "what is",
    "simple",
    "quick",
    "short",
    "introduce",
    "basics",
    "summary",
)

_MAJOR_DEPTH_SIGNALS = (
    "lab",
    "in depth",
    "in-depth",
    "detailed",
    "high school lab",
    "deep dive",
    "thorough",
    "comprehensive",
    "step by step",
    "step-by-step",
)

_TOPIC_AGENT_KEYS: frozenset[str] = frozenset(
    key for definition in SUBJECT_DEFINITIONS for key in (definition.major_key, definition.minor_key)
)


def get_subject_agent_names() -> list[str]:
    """Return all registered topic agent keys."""
    return list(_TOPIC_AGENT_KEYS)


def is_topic_agent(name: str) -> bool:
    """Return True when the agent key is a school-subject topic agent."""
    return name in _TOPIC_AGENT_KEYS


def get_subject_definition_for_agent(agent_name: str) -> SubjectDefinition | None:
    """Return the subject definition that owns a topic agent key."""
    for definition in SUBJECT_DEFINITIONS:
        if agent_name in (definition.major_key, definition.minor_key):
            return definition
    return None


def _infer_depth(text: str) -> AgentDepth:
    """Pick major or minor depth from keyword heuristics."""
    if any(signal in text for signal in _MAJOR_DEPTH_SIGNALS):
        return "major"
    if any(signal in text for signal in _MINOR_DEPTH_SIGNALS):
        return "minor"
    return "minor"


def _matched_subjects(text: str) -> list[SubjectDefinition]:
    """Return subject definitions whose keywords appear in the text."""
    matched: list[SubjectDefinition] = []
    for definition in SUBJECT_DEFINITIONS:
        if any(keyword in text for keyword in definition.keywords):
            matched.append(definition)
    return matched


def infer_subject_agents_from_keywords(text: str) -> list[str]:
    """Infer topic agent keys from subject keywords and depth heuristics."""
    normalized = text.lower().strip()
    if not normalized:
        return []

    depth = _infer_depth(normalized)
    agents: list[str] = []
    for definition in _matched_subjects(normalized):
        agent_key = definition.major_key if depth == "major" else definition.minor_key
        agents.append(agent_key)
    return agents


def build_subject_routing_rules() -> str:
    """Generate WR routing rules for listed school subjects."""
    lines: list[str] = []
    for definition in SUBJECT_DEFINITIONS:
        lines.append(
            f'- Route {definition.subject.lower()} questions to '
            f'"{definition.major_key}" (deep/lab/detailed) or '
            f'"{definition.minor_key}" (brief/overview/"what is").'
        )
    return "\n".join(lines)
