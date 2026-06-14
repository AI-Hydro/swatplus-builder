"""Calibration parameter governance shared by workflow, bridge, and docs."""

from __future__ import annotations

from dataclasses import dataclass

FULL_MODE_CORE_PARAMETERS: tuple[str, ...] = (
    "CN2",
    "PERCO",
    "LATQ_CO",
    "PET_CO",
    "ESCO",
    "EPCO",
    "SURLAG",
    "ALPHA_BF",
    "RCHG_DP",
    "GW_DELAY",
)

FULL_MODE_EXTENDED_PARAMETERS: tuple[str, ...] = (
    "SFTMP",
    "SMTMP",
    "LAT_TTIME",
    "CN3_SWF",
    "CH_N2",
    "CH_K2",
)


@dataclass(frozen=True)
class ParameterGovernance:
    name: str
    target_file: str
    target_column: str
    activity_class: str
    evidence_source: str
    model_family: str = "full"
    claim_tier_allowance: str = "exploratory unless basin-screened"


FULL_MODE_PARAMETER_GOVERNANCE: dict[str, ParameterGovernance] = {
    "CN2": ParameterGovernance(
        "CN2",
        "cntable.lum; urban.urb",
        "cn_a/cn_b/cn_c/cn_d for referenced landuse.lum cn2 rows; urb_cn for referenced urban rows",
        "active",
        "full-mode bridge tests, urban volume-bias evidence, and engine probe",
        claim_tier_allowance="diagnostic until basin-specific locked verification",
    ),
    "PERCO": ParameterGovernance(
        "PERCO",
        "hydrology.hyd",
        "perco",
        "active",
        "full-mode bridge implementation and registry alignment",
        claim_tier_allowance="diagnostic until basin-specific locked verification",
    ),
    "LATQ_CO": ParameterGovernance(
        "LATQ_CO",
        "hydrology.hyd",
        "latq_co",
        "active",
        "full-mode bridge implementation and registry alignment",
        claim_tier_allowance="diagnostic until basin-specific locked verification",
    ),
    "PET_CO": ParameterGovernance(
        "PET_CO",
        "hydrology.hyd",
        "pet_co",
        "not_tested",
        "bridge-supported but not engine-screened in full-mode suite",
    ),
    "ESCO": ParameterGovernance(
        "ESCO",
        "hydrology.hyd",
        "esco",
        "weak",
        "full-mode bridge tests",
        claim_tier_allowance="diagnostic only when retained after screen",
    ),
    "EPCO": ParameterGovernance(
        "EPCO",
        "hydrology.hyd",
        "epco",
        "not_tested",
        "full-mode bridge tests",
    ),
    "SURLAG": ParameterGovernance(
        "SURLAG",
        "parameters.bsn",
        "surq_lag",
        "not_tested",
        "full-mode bridge implementation",
    ),
    "ALPHA_BF": ParameterGovernance(
        "ALPHA_BF",
        "aquifer.aqu",
        "alpha_bf",
        "not_tested",
        "full-mode bridge tests",
    ),
    "RCHG_DP": ParameterGovernance(
        "RCHG_DP",
        "aquifer.aqu",
        "rchg_dp",
        "not_tested",
        "full-mode bridge tests and registry alignment",
    ),
    "GW_DELAY": ParameterGovernance(
        "GW_DELAY",
        "unsupported",
        "none in full-mode aquifer.aqu",
        "dead",
        "full-mode bridge fail-loud writer",
        claim_tier_allowance="blocked",
    ),
    "SFTMP": ParameterGovernance(
        "SFTMP",
        "snow.sno",
        "fall_tmp",
        "weak",
        "SWAT+ snow.sno documentation and full-mode bridge tests",
        claim_tier_allowance="diagnostic only when retained after basin-specific snow screen",
    ),
    "SMTMP": ParameterGovernance(
        "SMTMP",
        "snow.sno",
        "melt_tmp",
        "weak",
        "SWAT+ snow.sno documentation and full-mode bridge tests",
        claim_tier_allowance="diagnostic only when retained after basin-specific snow screen",
    ),
    "LAT_TTIME": ParameterGovernance(
        "LAT_TTIME",
        "hydrology.hyd",
        "lat_ttime",
        "not_tested",
        "SWAT+ lateral-flow lag documentation and full-mode source-code calibration path",
        claim_tier_allowance="diagnostic only when retained after basin-specific recession screen",
    ),
    "CN3_SWF": ParameterGovernance(
        "CN3_SWF",
        "hydrology.hyd",
        "cn3_swf",
        "not_tested",
        "SWAT+ soft-calibration documentation and 03353000 locked-objective probes",
        claim_tier_allowance="diagnostic only when retained after basin-specific volume screen",
    ),
    "CH_N2": ParameterGovernance(
        "CH_N2",
        "hyd-sed-lte.cha",
        "mann",
        "not_tested",
        "SWAT+ hyd-sed-lte.cha and channel-flow Manning equation documentation",
        claim_tier_allowance="diagnostic only when retained after basin-specific channel-routing screen",
    ),
    "CH_K2": ParameterGovernance(
        "CH_K2",
        "hyd-sed-lte.cha",
        "k",
        "not_tested",
        "SWAT+ hyd-sed-lte.cha channel alluvium conductivity documentation",
        claim_tier_allowance="diagnostic only when retained after basin-specific channel-routing screen",
    ),
}


def full_mode_screen_rows() -> list[dict[str, object]]:
    """Return machine-readable governance rows for the full-mode core set."""
    return [
        {
            "parameter": row.name,
            "activity_class": row.activity_class,
            "evidence": {
                "target_file": row.target_file,
                "target_column": row.target_column,
                "evidence_source": row.evidence_source,
                "model_family": row.model_family,
                "claim_tier_allowance": row.claim_tier_allowance,
            },
        }
        for name in FULL_MODE_CORE_PARAMETERS
        for row in [FULL_MODE_PARAMETER_GOVERNANCE[name]]
    ]


def full_mode_extended_screen_rows() -> list[dict[str, object]]:
    """Return governed process controls outside the required core set."""
    return [
        {
            "parameter": row.name,
            "activity_class": row.activity_class,
            "evidence": {
                "target_file": row.target_file,
                "target_column": row.target_column,
                "evidence_source": row.evidence_source,
                "model_family": row.model_family,
                "claim_tier_allowance": row.claim_tier_allowance,
            },
        }
        for name in FULL_MODE_EXTENDED_PARAMETERS
        for row in [FULL_MODE_PARAMETER_GOVERNANCE[name]]
    ]


def calibration_eligible_full_mode_parameters() -> list[str]:
    """Parameters eligible for canonical basin-specific screening.

    Governance-default ``not_tested`` means "must be screened before claim use",
    not "cannot be screened." Only controls that fail loud in full mode or are
    otherwise marked dead are excluded here; the locked sensitivity screen then
    decides which tested controls are retained for calibration.
    """
    return [
        name
        for name in FULL_MODE_CORE_PARAMETERS + FULL_MODE_EXTENDED_PARAMETERS
        if FULL_MODE_PARAMETER_GOVERNANCE[name].activity_class != "dead"
    ]
