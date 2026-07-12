from app.agents.economics_major.prompt import ECONOMICS_MAJOR_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

ECONOMICS_MAJOR_CONFIG = AgentConfig(
    name="economics_major",
    folder_path="Social Studies/Economics",
    description=(
        "Economics — in-depth explanations of markets, supply and demand, GDP, trade, "
        "and detailed economic reasoning."
    ),
    system_prompt=ECONOMICS_MAJOR_SYSTEM_PROMPT,
    subject="Economics",
    depth="major",
    agent_kind="topic",
)
