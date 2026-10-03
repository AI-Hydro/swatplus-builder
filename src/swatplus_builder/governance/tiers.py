"""Claim tier hierarchy — zero hydrology imports."""
from __future__ import annotations

CLAIM_TIERS: tuple[str, ...] = (
    "blocked",
    "exploratory",
    "diagnostic",
    "publication_grade",
    "research_grade",
)

_TIER_RANK: dict[str, int] = {t: i for i, t in enumerate(CLAIM_TIERS)}

TIER_LABELS: dict[str, str] = {
    "blocked": "Blocked",
    "exploratory": "Exploratory",
    "diagnostic": "Diagnostic",
    "publication_grade": "Calibration verified",
    "research_grade": "Gate-verified",
}


def tier_label(tier: str | None) -> str:
    """Public workflow label; stored identifiers and gate policy are unchanged.

    Neither verification label is a journal approval or a Moriasi rating.
    """
    return TIER_LABELS.get(tier or "", "Not evaluated")


def tier_rank(tier: str) -> int:
    """Return a sortable rank (higher = better) for a tier string."""
    return _TIER_RANK.get(tier, 0)


def higher_tier(a: str, b: str) -> str:
    """Return whichever tier is higher in the hierarchy."""
    return a if tier_rank(a) >= tier_rank(b) else b
