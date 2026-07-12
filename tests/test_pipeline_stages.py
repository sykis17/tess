"""Phase 18 pipeline stage tests."""

from app.core.folder_tree import FOLDER_TREE, all_folder_paths, validate_tree_matches_registry
from app.graph.pipeline_stages import (
    PipelineStage,
    predicted_stages,
    stage_for_node,
)


def test_stage_for_node_mappings() -> None:
    assert stage_for_node("wide_receiver") == PipelineStage.ROUTING
    assert stage_for_node("direct_responder") == PipelineStage.PRESENTING
    assert stage_for_node("combiner_mayor") == PipelineStage.COMBINING
    assert stage_for_node("combiner_micro") == PipelineStage.COMBINING
    assert stage_for_node("defense_review") == PipelineStage.DEFENSE
    assert stage_for_node("presenter") == PipelineStage.DONE
    assert stage_for_node("unknown_node") is None


def test_predicted_stages_l0_short_path() -> None:
    stages = predicted_stages("L0", ["Direct Responder", "Presenter"])
    assert stages == [PipelineStage.PRESENTING, PipelineStage.DONE]


def test_predicted_stages_l1_no_defense_or_combiners() -> None:
    agents = ["Wide Receiver", "Coder", "Presenter"]
    stages = predicted_stages("L1", agents)
    assert PipelineStage.ROUTING in stages
    assert PipelineStage.AGENTS in stages
    assert PipelineStage.COMBINING not in stages
    assert PipelineStage.DEFENSE not in stages
    assert stages[-1] == PipelineStage.DONE


def test_predicted_stages_l2_includes_defense() -> None:
    agents = [
        "Wide Receiver",
        "Coder",
        "Defense Delegator",
        "Defense Review",
        "Presenter",
    ]
    stages = predicted_stages("L2", agents)
    assert PipelineStage.DEFENSE in stages
    assert PipelineStage.COMBINING not in stages


def test_predicted_stages_l4_full_chain() -> None:
    agents = [
        "Wide Receiver",
        "Art",
        "UI Design",
        "Combiner Mayor",
        "Combiner Micro",
        "Collector",
        "Defense Delegator",
        "Defense Review",
        "Presenter",
    ]
    stages = predicted_stages("L4", agents)
    assert stages == [
        PipelineStage.ROUTING,
        PipelineStage.AGENTS,
        PipelineStage.COMBINING,
        PipelineStage.DEFENSE,
        PipelineStage.PRESENTING,
        PipelineStage.DONE,
    ]


def test_folder_tree_matches_registry() -> None:
    validate_tree_matches_registry()
    leaves = [child for branch in FOLDER_TREE for child in branch["children"]]
    assert len(leaves) == len(all_folder_paths())
    assert "Science/Chemistry" in leaves
    assert "Design/UI" in leaves
