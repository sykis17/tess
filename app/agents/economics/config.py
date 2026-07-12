from app.agents.economics.prompt import ECONOMICS_POV_SYSTEM_PROMPT
from app.agents.schemas import AgentConfig

ECONOMICS_CONFIG = AgentConfig(
    name="economics",
    folder_path="Social Studies/Economics",
    description=(
        "Economics POV — supply, demand, markets, trade-offs, "
        "and systems reasoning from an economics lens."
    ),
    system_prompt=ECONOMICS_POV_SYSTEM_PROMPT,
    pov="Economics",
    agent_kind="pov",
)
