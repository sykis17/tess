"""Pipeline stage constants and gate-aware stage prediction for the status wall."""

from app.core.chain_profiles import ChainProfile
from app.graph.chain_gates import allows_combiners, allows_defense, allows_wide_receiver

# Display names mapped to stage groups (for agents_involved → predicted steps).
_ROUTING_NAMES = frozenset({"Wide Receiver"})
_COMBINING_NAMES = frozenset({"Combiner Mayor", "Combiner Micro", "Collector"})
_DEFENSE_NAMES = frozenset({"Defense Delegator", "Defense Review"})
_PRESENTING_NAMES = frozenset({"Presenter", "Direct Responder"})


class PipelineStage:
    ROUTING = "routing"
    AGENTS = "agents"
    COMBINING = "combining"
    DEFENSE = "defense"
    PRESENTING = "presenting"
    DONE = "done"


_NODE_STAGE: dict[str, str] = {
    "wide_receiver": PipelineStage.ROUTING,
    "direct_responder": PipelineStage.PRESENTING,
    "combiner_mayor": PipelineStage.COMBINING,
    "combiner_micro": PipelineStage.COMBINING,
    "collector": PipelineStage.COMBINING,
    "defense_delegator": PipelineStage.DEFENSE,
    "defense_review": PipelineStage.DEFENSE,
    "presenter": PipelineStage.DONE,
}

_ORDERED_STAGES = [
    PipelineStage.ROUTING,
    PipelineStage.AGENTS,
    PipelineStage.COMBINING,
    PipelineStage.DEFENSE,
    PipelineStage.PRESENTING,
    PipelineStage.DONE,
]


def stage_for_node(node_name: str) -> str | None:
    """Map a graph node name to its pipeline stage."""
    return _NODE_STAGE.get(node_name)


def _stage_for_agent_display_name(name: str) -> str | None:
    if name in _ROUTING_NAMES:
        return PipelineStage.ROUTING
    if name in _COMBINING_NAMES:
        return PipelineStage.COMBINING
    if name in _DEFENSE_NAMES:
        return PipelineStage.DEFENSE
    if name in _PRESENTING_NAMES:
        return PipelineStage.PRESENTING
    return PipelineStage.AGENTS


def predicted_stages(chain_profile: str, agents_involved: list[str]) -> list[str]:
    """Build gate-aware predicted pipeline steps for the status wall."""
    profile = chain_profile or ChainProfile.L4.value

    if not allows_wide_receiver(profile):
        return [PipelineStage.PRESENTING, PipelineStage.DONE]

    stages: list[str] = []
    seen: set[str] = set()

    for name in agents_involved:
        stage = _stage_for_agent_display_name(name)
        if stage and stage not in seen:
            stages.append(stage)
            seen.add(stage)

    if not allows_combiners(profile):
        stages = [s for s in stages if s != PipelineStage.COMBINING]

    if not allows_defense(profile):
        stages = [s for s in stages if s != PipelineStage.DEFENSE]

    if PipelineStage.PRESENTING not in seen:
        stages.append(PipelineStage.PRESENTING)

    stages.append(PipelineStage.DONE)

    return [s for s in _ORDERED_STAGES if s in set(stages)]
