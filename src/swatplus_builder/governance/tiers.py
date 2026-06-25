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


def tier_rank(tier: str) -> int:
    """Return a sortable rank (higher = better) for a tier string."""
    return _TIER_RANK.get(tier, 0)


def higher_tier(a: str, b: str) -> str:
    """Return whichever tier is higher in the hierarchy."""
    return a if tier_rank(a) >= tier_rank(b) else b
