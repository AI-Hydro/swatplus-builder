"""Water-balance visualization from SWAT+ basin output tables."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from .style import apply_style
from .utils import build_figure_title, save_publication_figure

SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class WaterBalanceValues:
    """Annual-average water-balance terms in millimeters."""

    precip: float
    et: float
    surq_gen: float
    latq: float
    perc: float
    wateryld: float
    residual: float
    source_file: str
    years: tuple[int, ...]
    observed_runoff_mm: float | None = None
    observed_runoff_ratio: float | None = None

    @property
    def wateryld_ratio(self) -> float:
        return self.wateryld / self.precip if self.precip else 0.0


def plot_water_balance(
    run_dir: Path | str,
    outpath: Path | str,
    *,
    metadata: dict | None = None,
) -> WaterBalanceValues:
    """Plot annual-average basin water balance for a completed run.

    The figure intentionally separates two ideas:

    * a precipitation partition that closes exactly as ``ET + water yield +
      residual``; and
    * diagnostic component bars for surface runoff, lateral flow, and
      percolation, which should not be stacked as an independent closure
      because SWAT+ ``wateryld`` already aggregates multiple pathways.
    """

    run_dir = Path(run_dir)
    values = summarize_water_balance(run_dir)

    apply_style()
    fig, axes = plt.subplots(
        1,
        2,
        figsize=(11.5, 5.6),
        gridspec_kw={"width_ratios": [1.05, 1.0]},
    )
    ax0, ax1 = axes

    colors = {
        "et": "#3A7D44",
        "wateryld": "#2F6FA5",
        "residual": "#C78A2C",
        "surq": "#5AA9E6",
        "latq": "#4A90A4",
        "perc": "#B8792A",
    }

    bottom = 0.0
    closure_terms = [
        ("ET", values.et, colors["et"]),
        ("Water yield", values.wateryld, colors["wateryld"]),
        ("Other storage/deep partition", values.residual, colors["residual"]),
    ]
    for label, amount, color in closure_terms:
        ax0.bar([0], [amount], bottom=[bottom], color=color, width=0.48, label=label)
        if amount > values.precip * 0.06:
            ax0.text(
                0,
                bottom + amount / 2.0,
                f"{label}\n{amount:.0f} mm",
                ha="center",
                va="center",
                color="white" if label != "Other storage/deep partition" else "#1D2630",
                fontsize=10,
                fontweight="bold",
            )
        bottom += amount
    ax0.axhline(values.precip, color="#1D2630", linewidth=1.2)
    ax0.text(
        0.33,
        values.precip,
        f"P = {values.precip:.0f} mm",
        va="center",
        fontsize=10,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1.5},
    )
    if values.observed_runoff_mm is not None:
        band = values.observed_runoff_mm * 0.05
        ax0.axhspan(
            values.observed_runoff_mm - band,
            values.observed_runoff_mm + band,
            color="#6B4C9A",
            alpha=0.14,
            label="Observed runoff depth +/-5%",
        )
        ax0.axhline(values.observed_runoff_mm, color="#6B4C9A", linewidth=1.6)
        ax0.text(
            -0.52,
            values.observed_runoff_mm,
            f"Observed Q depth\n~{values.observed_runoff_mm:.0f} mm",
            va="center",
            ha="left",
            fontsize=8.5,
            color="#4C3575",
            bbox={"facecolor": "white", "edgecolor": "#B7A7D6", "alpha": 0.92, "pad": 2.0},
        )
    ax0.set_xlim(-0.55, 0.75)
    ax0.set_xticks([0])
    ax0.set_xticklabels(["Annual average"])
    ax0.set_ylabel("Water depth (mm/yr)")
    ax0.set_title("Precipitation partition")

    comp_labels = ["Surface runoff", "Lateral flow", "Percolation", "Water yield"]
    comp_vals = [values.surq_gen, values.latq, values.perc, values.wateryld]
    comp_colors = [colors["surq"], colors["latq"], colors["perc"], colors["wateryld"]]
    bars = ax1.barh(comp_labels, comp_vals, color=comp_colors)
    ax1.invert_yaxis()
    ax1.set_xlabel("Water depth (mm/yr)")
    ax1.set_title("Diagnostic flow components")
    for bar, val in zip(bars, comp_vals):
        ax1.text(
            bar.get_width() + max(values.precip * 0.015, 5.0),
            bar.get_y() + bar.get_height() / 2.0,
            f"{val:.0f} mm",
            va="center",
            fontsize=10,
        )
    ax1.set_xlim(0, max(values.precip * 0.58, max(comp_vals) * 1.22))

    title = build_figure_title("Basin Water Balance", None, metadata)
    fig.suptitle(title, y=1.02, fontsize=14, fontweight="bold")
    subtitle = (
        f"WYLD/P = {values.wateryld_ratio:.2f}"
        + (
            f"; observed Q/P ~ {values.observed_runoff_ratio:.2f}"
            if values.observed_runoff_ratio is not None
            else ""
        )
        + f" | source: {values.source_file}"
    )
    fig.text(0.5, 0.935, subtitle, ha="center", fontsize=10, color="#3D4852")
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
    return values


def summarize_water_balance(run_dir: Path | str) -> WaterBalanceValues:
    """Return water-balance values from a run directory."""

    run_dir = Path(run_dir)
    txt = _txtinout_dir(run_dir)
    rows, source_file = _read_basin_water_balance_rows(txt)
    eval_years = _alignment_years(run_dir)
    if eval_years:
        selected = [row for row in rows if int(row.get("yr", -9999)) in eval_years]
        if selected:
            rows = selected

    required = ["precip", "et", "surq_gen", "latq", "perc", "wateryld"]
    means: dict[str, float] = {}
    for key in required:
        vals = [float(row[key]) for row in rows if key in row]
        if not vals:
            raise ValueError(f"{source_file} does not contain numeric {key!r} rows")
        means[key] = sum(vals) / len(vals)

    residual = means["precip"] - means["et"] - means["wateryld"]
    obs_mm, obs_ratio = _observed_runoff_depth(run_dir, means["precip"])

    return WaterBalanceValues(
        precip=means["precip"],
        et=means["et"],
        surq_gen=means["surq_gen"],
        latq=means["latq"],
        perc=means["perc"],
        wateryld=means["wateryld"],
        residual=residual,
        source_file=source_file,
        years=tuple(sorted({int(row["yr"]) for row in rows if "yr" in row and int(row["yr"]) > 0})),
        observed_runoff_mm=obs_mm,
        observed_runoff_ratio=obs_ratio,
    )


def _txtinout_dir(run_dir: Path) -> Path:
    candidates = [
        run_dir / "project" / "Scenarios" / "Default" / "TxtInOut",
        run_dir / "TxtInOut",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"Could not locate TxtInOut under {run_dir}")


def _read_basin_water_balance_rows(txt: Path) -> tuple[list[dict[str, Any]], str]:
    for name in ("basin_wb_yr.txt", "basin_wb_aa.txt"):
        path = txt / name
        if not path.is_file():
            continue
        rows = _read_numeric_rows_tolerant(path)
        if rows:
            return rows, name
    raise FileNotFoundError(f"basin_wb_yr.txt or basin_wb_aa.txt not found under {txt}")


def _read_numeric_rows_tolerant(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    header_idx = next((i for i, line in enumerate(lines) if {"jday", "precip"}.issubset(set(line.split()))), None)
    if header_idx is None:
        raise ValueError(f"Could not find SWAT+ basin water-balance header in {path}")
    columns = lines[header_idx].split()
    required_last_idx = max(columns.index(k) for k in ("yr", "precip", "et", "surq_gen", "latq", "perc", "wateryld"))
    rows: list[dict[str, Any]] = []
    for line in lines[header_idx + 1 :]:
        tokens = line.split()
        if len(tokens) <= required_last_idx:
            continue
        try:
            # Units rows contain strings at numeric positions.
            float(tokens[columns.index("precip")])
        except ValueError:
            continue
        row: dict[str, Any] = {}
        for idx, col in enumerate(columns[: len(tokens)]):
            if idx > required_last_idx and col == "mgt_ops":
                break
            tok = tokens[idx]
            if col in {"name", "mgt_ops"}:
                row[col] = tok
            elif col in {"jday", "mon", "day", "yr", "unit", "gis_id"}:
                row[col] = int(float(tok))
            else:
                row[col] = float(tok)
        rows.append(row)
    return rows


def _alignment_years(run_dir: Path) -> set[int]:
    alignment = run_dir / "outputs" / "alignment.csv"
    if not alignment.is_file():
        return set()
    years: set[int] = set()
    for line in alignment.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        if not line.strip():
            continue
        first = line.split(",", 1)[0].strip()
        if len(first) >= 4 and first[:4].isdigit():
            years.add(int(first[:4]))
    return years


def _observed_runoff_depth(run_dir: Path, precip_mm: float) -> tuple[float | None, float | None]:
    alignment = run_dir / "outputs" / "alignment.csv"
    validation = run_dir / "delin" / "validation_result.json"
    if not alignment.is_file() or not validation.is_file():
        return None, None
    area = json.loads(validation.read_text(encoding="utf-8")).get("delineated_area_km2")
    if not isinstance(area, (int, float)) or area <= 0:
        return None, None
    obs_values: list[float] = []
    for line in alignment.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            obs_values.append(float(parts[1]))
        except ValueError:
            continue
    if not obs_values:
        return None, None
    # alignment.csv stores daily mean discharge in m3/s.
    total_m3 = sum(obs_values) * SECONDS_PER_DAY
    depth_mm = total_m3 / (float(area) * 1_000_000.0) * 1000.0
    years = max(len(obs_values) / 365.25, 1e-9)
    annual_depth = depth_mm / years
    ratio = annual_depth / precip_mm if precip_mm else None
    return annual_depth, ratio
