from app.agents.economics_minor.prompt import ECONOMICS_MINOR_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

ECONOMICS_MINOR_CONFIG = AgentConfig(
    name="economics_minor",
    folder_path="Social Studies/Economics",
    description=(
        "Economics — brief overviews and simple explanations of markets, supply and "
        "demand, and economic concepts."
    ),
    system_prompt=ECONOMICS_MINOR_SYSTEM_PROMPT,
    subject="Economics",
    depth="minor",
    agent_kind="topic",
)
