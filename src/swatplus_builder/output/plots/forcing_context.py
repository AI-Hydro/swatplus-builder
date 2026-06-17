"""Weather-forcing context visualization from retained SWAT+ inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from ..weather_forcing import _find_txtinout, _read_pcp_station, _station_files_from_cli
from .style import apply_style
from .utils import build_figure_title, save_publication_figure
from .water_balance import _read_basin_water_balance_rows


@dataclass(frozen=True)
class ForcingContextValues:
    """Summary values used in the forcing-context figure."""

    precip_start: str
    precip_end: str
    precip_station_count: int
    total_precip_mm: float
    mean_temp_c: float | None
    temp_station_count: int
    annual_precip_mm: float | None
    annual_pet_mm: float | None
    annual_et_mm: float | None


def plot_forcing_context(
    run_dir: Path | str,
    outpath: Path | str,
    *,
    metadata: dict | None = None,
) -> ForcingContextValues:
    """Plot precipitation, temperature, and PET/ET forcing context."""

    run = Path(run_dir)
    txt = _find_txtinout(run, {})
    if txt is None:
        raise FileNotFoundError(f"Could not locate TxtInOut weather files under {run}")

    precip_daily = _daily_mean_precip(txt)
    temp_daily = _daily_mean_temperature(txt)
    annual = _annual_basin_climate(txt)
    values = ForcingContextValues(
        precip_start=str(precip_daily.index.min().date()),
        precip_end=str(precip_daily.index.max().date()),
        precip_station_count=int(precip_daily.attrs.get("station_count", 0)),
        total_precip_mm=float(precip_daily.sum()),
        mean_temp_c=float(temp_daily.mean()) if temp_daily is not None and not temp_daily.empty else None,
        temp_station_count=int(temp_daily.attrs.get("station_count", 0)) if temp_daily is not None else 0,
        annual_precip_mm=annual.get("precip"),
        annual_pet_mm=annual.get("pet"),
        annual_et_mm=annual.get("et"),
    )

    monthly_precip = precip_daily.resample("MS").sum()
    monthly_temp = temp_daily.resample("MS").mean() if temp_daily is not None else None

    apply_style()
    fig, axes = plt.subplots(
        1,
        3,
        figsize=(13.2, 4.8),
        gridspec_kw={"width_ratios": [1.45, 1.45, 0.9]},
    )
    ax0, ax1, ax2 = axes

    ax0.bar(monthly_precip.index, monthly_precip.values, width=24, color="#2F6FA5")
    ax0.set_title("Monthly precipitation")
    ax0.set_ylabel("mm/month")
    ax0.set_xlabel("Date")
    ax0.tick_params(axis="x", rotation=35)

    if monthly_temp is not None and not monthly_temp.empty:
        ax1.plot(monthly_temp.index, monthly_temp.values, color="#B75D2A", linewidth=2.2)
        ax1.axhline(0, color="#5A6570", linewidth=0.9, alpha=0.7)
        ax1.set_title("Monthly mean temperature")
        ax1.set_ylabel("deg C")
        ax1.set_xlabel("Date")
        ax1.tick_params(axis="x", rotation=35)
    else:
        ax1.text(0.5, 0.5, "Temperature files not available", ha="center", va="center")
        ax1.set_axis_off()

    bars = [
        ("P", values.annual_precip_mm),
        ("PET", values.annual_pet_mm),
        ("ET", values.annual_et_mm),
    ]
    labels = [label for label, value in bars if value is not None]
    amounts = [float(value) for _label, value in bars if value is not None]
    colors = ["#2F6FA5", "#C78A2C", "#3A7D44"][: len(amounts)]
    if amounts:
        rects = ax2.bar(labels, amounts, color=colors, width=0.58)
        ax2.set_title("Annual context")
        ax2.set_ylabel("mm/yr")
        for rect, amount in zip(rects, amounts):
            ax2.text(
                rect.get_x() + rect.get_width() / 2,
                rect.get_height() + max(amounts) * 0.03,
                f"{amount:.0f}",
                ha="center",
                va="bottom",
                fontsize=9.5,
            )
        ax2.set_ylim(0, max(amounts) * 1.18)
    else:
        ax2.text(0.5, 0.5, "Basin water-balance\nPET/ET unavailable", ha="center", va="center")
        ax2.set_axis_off()

    title = build_figure_title("Forcing Context", None, metadata)
    fig.suptitle(title, y=1.02, fontsize=14, fontweight="bold")
    subtitle = (
        f"Precip stations={values.precip_station_count}; "
        f"temperature stations={values.temp_station_count}; "
        f"period={values.precip_start} to {values.precip_end}"
    )
    fig.text(0.5, 0.915, subtitle, ha="center", fontsize=9.8, color="#3D4852")
    fig.text(
        0.5,
        0.01,
        "Diagnostic forcing context only; this figure does not certify model performance.",
        ha="center",
        fontsize=9,
        color="#4A5568",
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.88])
    save_publication_figure(fig, outpath, metadata=metadata)
    plt.close(fig)
    return values


def _daily_mean_precip(txt: Path) -> pd.Series:
    series = []
    for name in _station_files_from_cli(txt / "pcp.cli"):
        parsed = _read_pcp_station(txt / name)
        if isinstance(parsed, pd.Series):
            series.append(parsed)
    if not series:
        raise ValueError(f"No readable precipitation station files under {txt}")
    daily = pd.concat(series, axis=1).sort_index().mean(axis=1, skipna=True)
    daily.attrs["station_count"] = len(series)
    return daily


def _daily_mean_temperature(txt: Path) -> pd.Series | None:
    series = []
    for name in _station_files_from_cli(txt / "tmp.cli"):
        parsed = _read_tmp_station(txt / name)
        if isinstance(parsed, pd.Series):
            series.append(parsed)
    if not series:
        return None
    daily = pd.concat(series, axis=1).sort_index().mean(axis=1, skipna=True)
    daily.attrs["station_count"] = len(series)
    return daily


def _read_tmp_station(path: Path) -> pd.Series | str:
    if not path.is_file():
        return "missing"
    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[3:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            year = int(parts[0])
            doy = int(parts[1])
            tmax = float(parts[2])
            tmin = float(parts[3])
            date = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=doy - 1)
        except Exception:
            continue
        dates.append(date)
        values.append((tmax + tmin) / 2.0)
    if not dates:
        return "no_daily_rows"
    return pd.Series(values, index=pd.DatetimeIndex(dates), name=path.name).sort_index()


def _annual_basin_climate(txt: Path) -> dict[str, float | None]:
    try:
        rows, _source = _read_basin_water_balance_rows(txt)
    except Exception:
        return {"precip": None, "pet": None, "et": None}
    out: dict[str, float | None] = {}
    for key in ("precip", "pet", "et"):
        vals = [float(row[key]) for row in rows if key in row]
        out[key] = sum(vals) / len(vals) if vals else None
    return out
