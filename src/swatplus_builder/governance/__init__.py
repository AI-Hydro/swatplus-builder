"""swatplus_builder.governance — domain-agnostic claim governance core.

Zero hydrology imports. SWAT+-specific gate implementations in
``swatplus_builder.workflows.usgs_e2e`` call these and supply
domain-specific parameter lists (e.g. for sensitivity_gate).
"""
from .gates import (
    benchmark_lock_gate,
    calibration_improvement_gate,
    fresh_engine_gate,
    outlet_provenance_gate,
    research_metric_gate,
    sensitivity_gate,
    soil_fidelity_gate,
)
from .tiers import CLAIM_TIERS, higher_tier, tier_rank

__all__ = [
    "CLAIM_TIERS",
    "tier_rank",
    "higher_tier",
    "fresh_engine_gate",
    "benchmark_lock_gate",
    "outlet_provenance_gate",
    "research_metric_gate",
    "soil_fidelity_gate",
    "calibration_improvement_gate",
    "sensitivity_gate",
]
