"""HRU and land-use composition visualization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from ..landuse_fidelity import build_landuse_fidelity_block
from .style import apply_style
from .utils import build_figure_title, save_publication_figure


@dataclass(frozen=True)
class LanduseCompositionValues:
    """Land-use classes present in source raster and retained in model HRUs."""

    hru_mode: str
    n_present_classes: int
    n_retained_classes: int
    retention_fraction: float | None
    landuse_vintage_year: int | None
    sim_midpoint_year: int | None
    landuse_vintage_mismatch_years: int | None
    classes: tuple[str, ...]
    present_fraction: dict[str, float]
    retained_fraction: dict[str, float]


def plot_landuse_composition(
    run_dir: Path | str,
    outpath: Path | str,
    *,
    metadata: dict | None = None,
    sim_start: str | None = None,
    sim_end: str | None = None,
) -> LanduseCompositionValues:
    """Plot source NLCD classes against retained HRU land-use classes."""

    run_dir = Path(run_dir)
    values = summarize_landuse_composition(run_dir, sim_start=sim_start, sim_end=sim_end)

    classes = list(values.classes)
    present = [100.0 * values.present_fraction.get(cls, 0.0) for cls in classes]
    retained = [100.0 * values.retained_fraction.get(cls, 0.0) for cls in classes]
    y = list(range(len(classes)))

    apply_style()
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(12.2, max(5.8, 0.34 * len(classes) + 1.7)),
        gridspec_kw={"width_ratios": [1.45, 0.75]},
    )
    ax, ax_note = axes

    height = 0.36
    ax.barh([v - height / 2 for v in y], present, height=height, color="#8E99A4", label="Present in NLCD raster")
    ax.barh([v + height / 2 for v in y], retained, height=height, color="#2F6FA5", label="Retained in HRUs")
    ax.set_yticks(y)
    ax.set_yticklabels(classes)
    ax.invert_yaxis()
    ax.set_xlabel("Area share (%)")
    ax.set_title("Land-use area represented in the model")
    ax.set_xlim(0, max(max(present + retained + [1.0]) * 1.16, 12.0))
    ax.legend(loc="lower right", frameon=True)
    for idx, (p, r) in enumerate(zip(present, retained)):
        if p >= 2.0:
            ax.text(p + 0.35, idx - height / 2, f"{p:.1f}", va="center", fontsize=7.5, color="#4A5560")
        if r >= 2.0:
            ax.text(r + 0.35, idx + height / 2, f"{r:.1f}", va="center", fontsize=7.5, color="#1D4F7A")

    ax_note.axis("off")
    retention = (
        "n/a" if values.retention_fraction is None else f"{100.0 * values.retention_fraction:.0f}%"
    )
    mismatch = (
        "n/a"
        if values.landuse_vintage_mismatch_years is None
        else f"{values.landuse_vintage_mismatch_years:+d} yr"
    )
    summary_lines = [
        ("HRU mode", values.hru_mode),
        ("Classes present", str(values.n_present_classes)),
        ("Classes retained", str(values.n_retained_classes)),
        ("Class retention", retention),
        ("NLCD vintage", str(values.landuse_vintage_year or "n/a")),
        ("Sim midpoint", str(values.sim_midpoint_year or "n/a")),
        ("Vintage offset", mismatch),
    ]
    y0 = 0.94
    ax_note.text(0.0, y0, "Representation disclosure", fontsize=13, fontweight="bold", va="top")
    for i, (label, value) in enumerate(summary_lines):
        yy = y0 - 0.12 - i * 0.085
        ax_note.text(0.0, yy, label, fontsize=9.5, color="#4A5560", va="top")
        ax_note.text(0.66, yy, value, fontsize=9.5, fontweight="bold", color="#1D2630", va="top")
    ax_note.text(
        0.0,
        0.16,
        "No blue bar means the class was present in the source raster but absent from the emitted HRUs.",
        fontsize=8.5,
        color="#5C6670",
        wrap=True,
    )
    ax_note.text(
        0.0,
        0.07,
        "Diagnostic context only: representation fidelity, not model skill.",
        fontsize=8.5,
        color="#5C6670",
        wrap=True,
    )

    fig.suptitle(build_figure_title("HRU / Land-Use Composition", None, metadata), y=1.01, fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
    return values


def summarize_landuse_composition(
    run_dir: Path | str,
    *,
    sim_start: str | None = None,
    sim_end: str | None = None,
) -> LanduseCompositionValues:
    """Summarize land-use area shares from real run artifacts."""

    run_dir = Path(run_dir)
    block = build_landuse_fidelity_block(run_dir, sim_start=sim_start, sim_end=sim_end)
    if block.get("status") != "evaluated":
        raise ValueError(f"land-use fidelity is not evaluated: {block.get('reason', block.get('status'))}")

    present_details = block.get("landuse_present_details") or []
    if not isinstance(present_details, list) or not present_details:
        raise ValueError("landuse_present_details missing from fidelity block")

    present_counts: dict[str, int] = {}
    for item in present_details:
        if not isinstance(item, dict):
            continue
        cls = str(item.get("swatplus_landuse") or "")
        if not cls:
            continue
        present_counts[cls] = present_counts.get(cls, 0) + int(item.get("pixel_count") or 0)
    present_total = sum(present_counts.values())
    if present_total <= 0:
        raise ValueError("present land-use class pixel count is zero")
    present_fraction = {cls: count / present_total for cls, count in present_counts.items()}

    retained_area = _retained_landuse_area(run_dir)
    retained_total = sum(retained_area.values())
    retained_fraction = (
        {cls: area / retained_total for cls, area in retained_area.items()} if retained_total > 0 else {}
    )

    classes = tuple(
        sorted(
            set(present_fraction) | set(retained_fraction),
            key=lambda cls: (-present_fraction.get(cls, 0.0), cls),
        )
    )
    return LanduseCompositionValues(
        hru_mode=str(block.get("hru_mode") or "unknown"),
        n_present_classes=int(block.get("landuse_classes_present_count") or len(present_fraction)),
        n_retained_classes=int(block.get("landuse_classes_retained_count") or len(retained_fraction)),
        retention_fraction=_as_float(block.get("landuse_class_retention_fraction")),
        landuse_vintage_year=_as_int(block.get("landuse_vintage_year")),
        sim_midpoint_year=_as_int(block.get("sim_midpoint_year")),
        landuse_vintage_mismatch_years=_as_int(block.get("landuse_vintage_mismatch_years")),
        classes=classes,
        present_fraction=present_fraction,
        retained_fraction=retained_fraction,
    )


def _retained_landuse_area(run_dir: Path) -> dict[str, float]:
    catalog_path = run_dir / "delin" / "hrus" / "hru_catalog.json"
    if not catalog_path.is_file():
        return {}
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    hrus = catalog.get("hrus") if isinstance(catalog, dict) else []
    out: dict[str, float] = {}
    if not isinstance(hrus, list):
        return out
    for hru in hrus:
        if not isinstance(hru, dict):
            continue
        cls = str(hru.get("landuse") or "")
        if not cls:
            continue
        area = _as_float(hru.get("arland")) or _as_float(hru.get("arsub")) or 0.0
        out[cls] = out.get(cls, 0.0) + area
    return out


def _as_float(value: Any) -> float | None:
    try:
        if value is not None:
            return float(value)
    except Exception:
        return None
    return None


def _as_int(value: Any) -> int | None:
    try:
        if value is not None:
            return int(value)
    except Exception:
        return None
    return None
