"""Autoresearch loop primitives (Phase 3D)."""

from .loop import (
    LoopIterationResult,
    LoopRequest,
    LoopResult,
    LoopStoppingCriteria,
    SurrogatePrediction,
    run_autoresearch_loop,
)
from .surrogate import (
    HoldoutEvaluationCase,
    HoldoutEvaluationReport,
    HoldoutEvaluationRequest,
    RoutingDecision,
    SurrogateEnsemble,
    SurrogateMember,
    SurrogatePredictionEstimate,
    SurrogateTrainingRequest,
    decide_routing_path,
    evaluate_surrogate_holdout,
    make_loop_surrogate_predictor,
    predict_with_surrogate,
    train_surrogate_ensemble,
)

__all__ = [
    "LoopIterationResult",
    "LoopRequest",
    "LoopResult",
    "LoopStoppingCriteria",
    "SurrogatePrediction",
    "run_autoresearch_loop",
    "HoldoutEvaluationCase",
    "HoldoutEvaluationReport",
    "HoldoutEvaluationRequest",
    "RoutingDecision",
    "SurrogateEnsemble",
    "SurrogateMember",
    "SurrogatePredictionEstimate",
    "SurrogateTrainingRequest",
    "decide_routing_path",
    "evaluate_surrogate_holdout",
    "make_loop_surrogate_predictor",
    "predict_with_surrogate",
    "train_surrogate_ensemble",
]
