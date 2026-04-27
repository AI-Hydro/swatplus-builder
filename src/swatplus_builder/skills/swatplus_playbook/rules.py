"""Decision rules derived from project-validated SWAT+ evidence."""

from __future__ import annotations

from .schemas import PlaybookContext, PlaybookRecommendation


def recommend_next_action(context: PlaybookContext) -> PlaybookRecommendation:
    """Recommend the next safe action for autoresearch/calibration workflows.

    Failure modes:
    - No exception for ordinary incomplete context; defaults to conservative behavior.
    - Raises pydantic validation errors if malformed context payload is provided.
    """

    metric_source = context.metric_source.strip().lower()
    if metric_source != "evaluate_run":
        return PlaybookRecommendation(
            action="restore_metric_authority",
            rationale="Metric parity is invalid unless evaluate_run is the authoritative source.",
            status="validated",
            rejected_paths=["surrogate_only_calibration"],
            preferred_paths=["evaluate_run_metric_parity"],
            fallback_proposal_source="random",
        )

    if context.routing_mode == 1 and any("segmentation fault" in line.lower() for line in context.error_logs):
        return PlaybookRecommendation(
            action="stabilize_channel_routing_geometry",
            rationale="Muskingum routing segfault indicates channel geometry/runtime incompatibility.",
            status="validated",
            rejected_paths=["enable_rte_cha_without_geometry_audit"],
            preferred_paths=["routing_geometry_audit"],
            fallback_proposal_source="random",
        )

    if context.calibration_history_rows >= 3 and context.calibration_history_unique_nse <= 1:
        rejected = ["history"] if context.proposal_source == "history" else []
        return PlaybookRecommendation(
            action="investigate_calibration_bridge",
            rationale="Flat calibration history indicates parameter proposals are not reaching SWAT+ inputs.",
            status="validated",
            rejected_paths=rejected,
            preferred_paths=["cn2_injection_trace", "input_file_diff_diagnostics"],
            fallback_proposal_source="random" if rejected else None,
        )

    cn2_sensitivity = context.sensitivity.get("CN2")
    if cn2_sensitivity is not None and abs(cn2_sensitivity) < 1e-9:
        return PlaybookRecommendation(
            action="run_parameter_sensitivity_audit",
            rationale="CN2 appears insensitive; verify injection path before broader calibration search.",
            status="tentative",
            rejected_paths=["expand_parameter_search_space"],
            preferred_paths=["manual_cn2_perturbation"],
            fallback_proposal_source="random",
        )

    return PlaybookRecommendation(
        action="continue_parity_safe_experimentation",
        rationale="No structural blocker detected; continue with evaluate_run-backed experiments.",
        status="validated",
        preferred_paths=["evaluate_run_metric_parity", "artifact_native_autoresearch"],
    )
