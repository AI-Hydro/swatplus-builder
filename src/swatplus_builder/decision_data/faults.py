"""Controlled fault injection for decision-model training data.

A *fault* is a deliberate, documented perturbation of a working SWAT+
``TxtInOut`` whose cause is known to us but hidden from the model. Running the
governed workflow on the faulted copy yields evidence states whose correct
diagnosis is known, which is what supervised decision data needs (see the
SWAT-S1 vision document, §8.3).

Two fault kinds are supported:

* **Forcing faults** edit the observed-weather station files (``*.pcp`` /
  ``*.tmp``) row by row. Missing values (``-99``) are never touched.
* **Parameter faults** set a calibration parameter through the package's own
  validated full-mode parameter bridge, so a fault can only write what the
  calibration path itself can write.

:func:`inject_fault` never edits in place: it copies the base ``TxtInOut``,
applies the fault, and writes ``fault_manifest.json`` with the spec, the
latent cause label, and SHA-256 hashes of every file before and after.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

FAULT_MANIFEST_SCHEMA = "swatplus_builder.fault_manifest/v1"
FAULT_MANIFEST_FILENAME = "fault_manifest.json"
_MISSING = -99.0

FaultFamily = Literal[
    "forcing",
    "runoff",
    "soil_storage",
    "evapotranspiration",
    "subsurface",
    "routing",
    "snow",
]

# Outputs of a previous engine run are never part of the faulted input state.
_OUTPUT_SUFFIXES = ("_day.txt", "_mon.txt", "_yr.txt", "_aa.txt", ".csv")


@dataclass(frozen=True)
class FaultSpec:
    """A single, reproducible perturbation with a hidden cause label.

    Attributes:
        fault_id: Stable identifier (used in manifests and episode ids).
        family: Process family of the latent cause (the hidden label).
        kind: ``"precip_scale"``, ``"precip_storm_removal"``,
            ``"precip_time_shift"``, ``"temperature_shift"`` or ``"parameter"``.
        magnitude: Kind-specific amount (factor, fraction, days, °C, or the
            absolute parameter value for ``"parameter"``).
        parameter: Registry parameter name for ``kind == "parameter"``.
        quantile: Wet-day quantile above which storms are affected
            (``precip_storm_removal`` only).
        expected_symptoms: A modeller's *hypothesis* of the resulting symptoms,
            for dataset users only (never shown to the model). It is not a
            label: responses are basin-dependent (e.g. a PERCO fault has no
            effect where percolation is already zero), so verify each injected
            episode with :func:`fault_effect`.
    """

    fault_id: str
    family: FaultFamily
    kind: str
    magnitude: float
    parameter: str | None = None
    quantile: float = 0.95
    expected_symptoms: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fault_id": self.fault_id,
            "family": self.family,
            "kind": self.kind,
            "magnitude": self.magnitude,
            "parameter": self.parameter,
            "quantile": self.quantile,
            "expected_symptoms": self.expected_symptoms,
        }


# Initial catalogue. Magnitudes are deliberate starting points for a pilot,
# not calibrated values; extend or override per study design.
DEFAULT_FAULTS: tuple[FaultSpec, ...] = (
    FaultSpec("precip_minus_30pct", "forcing", "precip_scale", 0.7,
              expected_symptoms="volume deficit across all flows; negative PBIAS; low ET/P unchanged"),
    FaultSpec("precip_plus_30pct", "forcing", "precip_scale", 1.3,
              expected_symptoms="volume excess across all flows; positive PBIAS"),
    FaultSpec("storms_removed_p95", "forcing", "precip_storm_removal", 0.5, quantile=0.95,
              expected_symptoms="underpredicted peaks with near-normal baseflow; mimics runoff-generation faults"),
    FaultSpec("precip_lag_2d", "forcing", "precip_time_shift", 2.0,
              expected_symptoms="systematic peak timing error; correlation (r) loss with little volume error"),
    FaultSpec("temperature_plus_3c", "snow", "temperature_shift", 3.0,
              expected_symptoms="earlier/smaller snowmelt pulse; higher ET"),
    FaultSpec("cn2_high", "runoff", "parameter", 92.0, parameter="CN2",
              expected_symptoms="flashy hydrograph, overpredicted peaks, low baseflow index"),
    FaultSpec("esco_low", "evapotranspiration", "parameter", 0.05, parameter="ESCO",
              expected_symptoms="shifts soil-evaporation depth partitioning; sign of the water-yield "
                                "response is basin-dependent (raised yield on SWAT+ Ames_sub1)"),
    FaultSpec("perco_low", "soil_storage", "parameter", 0.02, parameter="PERCO",
              expected_symptoms="reduced recharge; low baseflow; more lateral/surface flow"),
    FaultSpec("alpha_bf_high", "subsurface", "parameter", 0.95, parameter="ALPHA_BF",
              expected_symptoms="fast recession; baseflow drops too quickly after events"),
    FaultSpec("ch_n2_high", "routing", "parameter", 0.3, parameter="CH_N2",
              expected_symptoms="attenuated, delayed peaks; volume largely preserved"),
    FaultSpec("smtmp_high", "snow", "parameter", 5.0, parameter="SMTMP",
              expected_symptoms="delayed snowmelt timing in snow-affected basins"),
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_output(name: str) -> bool:
    return name.endswith(_OUTPUT_SUFFIXES)


def _hash_inputs(txt: Path) -> dict[str, str]:
    return {
        p.name: _sha256(p)
        for p in sorted(txt.iterdir())
        if p.is_file() and not _is_output(p.name) and p.name != FAULT_MANIFEST_FILENAME
    }


# ---------------------------------------------------------------------------
# Weather-file editing
# ---------------------------------------------------------------------------


def _station_files(txt: Path, suffix: str) -> list[Path]:
    return sorted(p for p in txt.glob(f"*.{suffix}") if p.is_file())


def _split_station_file(path: Path) -> tuple[list[str], list[tuple[str, str, list[float]]]]:
    """Return (3 header lines, [(year, doy, values)])."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 3:
        return lines, []
    rows: list[tuple[str, str, list[float]]] = []
    for ln in lines[3:]:
        toks = ln.split()
        if len(toks) < 3:
            continue
        rows.append((toks[0], toks[1], [float(t) for t in toks[2:]]))
    return lines[:3], rows


def _format_row(year: str, doy: str, values: list[float]) -> str:
    # Same layout as weather.writer: YYYY + doy rjust(5) + " " + {:.5f} rjust(10) + 2 spaces.
    return f"{year}{doy.rjust(5)} " + "".join(f"{v:.5f}".rjust(10) + "  " for v in values)


def _write_station_file(path: Path, header: list[str], rows: list[tuple[str, str, list[float]]]) -> None:
    body = [_format_row(y, d, v) for y, d, v in rows]
    path.write_text("\n".join([*header, *body]) + "\n", encoding="utf-8")


def _edit_station_files(
    txt: Path, suffix: str, edit: Callable[[list[tuple[str, str, list[float]]]], list[tuple[str, str, list[float]]]]
) -> list[str]:
    files = _station_files(txt, suffix)
    if not files:
        raise FileNotFoundError(f"No *.{suffix} station files in {txt}")
    edited: list[str] = []
    for path in files:
        header, rows = _split_station_file(path)
        if not rows:
            continue
        _write_station_file(path, header, edit(rows))
        edited.append(path.name)
    if not edited:
        raise ValueError(
            f"No observed *.{suffix} data rows in {txt}; the model may be using the weather "
            "generator for this variable, so a forcing fault cannot be injected."
        )
    return edited


def _precip_scale(factor: float) -> Callable[[list[tuple[str, str, list[float]]]], list[tuple[str, str, list[float]]]]:
    if factor < 0:
        raise ValueError("precip_scale factor must be >= 0")

    def edit(rows: list[tuple[str, str, list[float]]]) -> list[tuple[str, str, list[float]]]:
        return [(y, d, [v * factor if v != _MISSING and v >= 0 else v for v in vals]) for y, d, vals in rows]

    return edit


def _precip_storm_removal(
    fraction: float, quantile: float
) -> Callable[[list[tuple[str, str, list[float]]]], list[tuple[str, str, list[float]]]]:
    if not 0.0 <= fraction <= 1.0 or not 0.0 < quantile < 1.0:
        raise ValueError("storm removal needs 0 <= fraction <= 1 and 0 < quantile < 1")

    def edit(rows: list[tuple[str, str, list[float]]]) -> list[tuple[str, str, list[float]]]:
        wet = sorted(vals[0] for _, _, vals in rows if vals and vals[0] > 0 and vals[0] != _MISSING)
        if not wet:
            return rows
        threshold = wet[min(len(wet) - 1, int(quantile * len(wet)))]
        out = []
        for y, d, vals in rows:
            v = vals[0]
            if v != _MISSING and v >= threshold and v > 0:
                vals = [v * (1.0 - fraction), *vals[1:]]
            out.append((y, d, vals))
        return out

    return edit


def _precip_time_shift(days: float) -> Callable[[list[tuple[str, str, list[float]]]], list[tuple[str, str, list[float]]]]:
    lag = int(round(days))
    if lag < 0:
        raise ValueError("precip_time_shift supports non-negative lags (delays) only")

    def edit(rows: list[tuple[str, str, list[float]]]) -> list[tuple[str, str, list[float]]]:
        if lag == 0:
            return rows
        values = [vals for _, _, vals in rows]
        # Delay: day t receives day t-lag; the first `lag` days get no rain.
        shifted = [[0.0] * len(values[0])] * lag + values[:-lag] if len(values) > lag else values
        return [(y, d, list(v)) for (y, d, _), v in zip(rows, shifted, strict=False)]

    return edit


def _temperature_shift(delta: float) -> Callable[[list[tuple[str, str, list[float]]]], list[tuple[str, str, list[float]]]]:
    def edit(rows: list[tuple[str, str, list[float]]]) -> list[tuple[str, str, list[float]]]:
        return [(y, d, [v + delta if v != _MISSING else v for v in vals]) for y, d, vals in rows]

    return edit


def _apply_fault_in_place(txt: Path, spec: FaultSpec) -> list[str]:
    """Apply ``spec`` to ``txt``; return the names of files it edited."""
    if spec.kind == "precip_scale":
        return _edit_station_files(txt, "pcp", _precip_scale(spec.magnitude))
    if spec.kind == "precip_storm_removal":
        return _edit_station_files(txt, "pcp", _precip_storm_removal(spec.magnitude, spec.quantile))
    if spec.kind == "precip_time_shift":
        return _edit_station_files(txt, "pcp", _precip_time_shift(spec.magnitude))
    if spec.kind == "temperature_shift":
        return _edit_station_files(txt, "tmp", _temperature_shift(spec.magnitude))
    if spec.kind == "parameter":
        if not spec.parameter:
            raise ValueError(f"fault {spec.fault_id!r}: kind='parameter' requires `parameter`")
        from ..full_mode.parameter_bridge import apply_parameters_to_full_swat_txtinout

        before = _hash_inputs(txt)
        apply_parameters_to_full_swat_txtinout(txt, {spec.parameter: float(spec.magnitude)})
        after = _hash_inputs(txt)
        return sorted(name for name in after if before.get(name) != after[name])
    raise ValueError(f"Unknown fault kind: {spec.kind!r}")


def inject_fault(base_txtinout: Path | str, out_dir: Path | str, spec: FaultSpec) -> Path:
    """Copy ``base_txtinout`` to ``out_dir/TxtInOut``, apply ``spec``, write a manifest.

    Returns the faulted ``TxtInOut`` path. Engine outputs from the base run are
    not copied. Raises if the fault edits no file, so a silently ineffective
    fault can never enter a dataset.
    """
    base = Path(base_txtinout).expanduser().resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"base TxtInOut not found: {base}")
    root = Path(out_dir).expanduser().resolve()
    txt = root / "TxtInOut"
    if txt.exists():
        raise FileExistsError(f"refusing to overwrite existing faulted TxtInOut: {txt}")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(base, txt, ignore=lambda _d, names: [n for n in names if _is_output(n)])

    try:
        before = _hash_inputs(txt)
        edited = _apply_fault_in_place(txt, spec)
        after = _hash_inputs(txt)
        changed = sorted(name for name in after if before.get(name) != after[name])
        if not changed:
            raise RuntimeError(f"fault {spec.fault_id!r} changed no input file; refusing to record it")
    except BaseException:
        # Never leave a half-built, manifest-less copy that could later be
        # mistaken for a valid faulted episode.
        shutil.rmtree(txt, ignore_errors=True)
        raise

    from .. import __version__

    manifest = {
        "schema": FAULT_MANIFEST_SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_version": __version__,
        "base_txtinout": str(base),
        "fault": spec.to_dict(),
        # Hidden label: training code must read it only as a target, never as input.
        "latent_fault_family": spec.family,
        "edited_files": edited,
        "changed_files": {name: {"before": before.get(name), "after": after[name]} for name in changed},
        "input_fingerprint_before": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "input_fingerprint_after": hashlib.sha256(json.dumps(after, sort_keys=True).encode("utf-8")).hexdigest(),
    }
    (root / FAULT_MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return txt


def load_fault_manifest(run_dir: Path | str) -> dict[str, Any] | None:
    """Return the fault manifest for a run directory, or ``None`` for natural runs."""
    path = Path(run_dir) / FAULT_MANIFEST_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_basin_wb_aa(txt: Path) -> dict[str, float]:
    path = txt / "basin_wb_aa.txt"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < 3:
        raise ValueError(f"{path} has no annual-average row")
    header = lines[1].split()
    values = lines[-1].split()
    out: dict[str, float] = {}
    for name, raw in zip(header, values, strict=False):
        try:
            out[name] = float(raw)
        except ValueError:
            continue
    return out


def fault_effect(
    base_txtinout: Path | str,
    faulted_txtinout: Path | str,
    *,
    variables: tuple[str, ...] = ("precip", "et", "wateryld", "surq_gen", "latq", "perc", "snomlt"),
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """Compare annual-average water balance of a faulted run against its base run.

    Both directories must already contain engine outputs (``basin_wb_aa.txt``).
    ``effective`` is False when no variable moved by more than ``tolerance``
    (relative), which marks a fault that changed files but not hydrology —
    such an episode would teach a wrong cause and must be excluded.
    """
    base = _read_basin_wb_aa(Path(base_txtinout))
    faulted = _read_basin_wb_aa(Path(faulted_txtinout))
    ratios: dict[str, float | None] = {}
    moved: list[str] = []
    for var in variables:
        b, f = base.get(var), faulted.get(var)
        if b is None or f is None:
            continue
        if abs(b) < 1e-9:
            ratios[var] = None
            if abs(f) > 1e-9:
                moved.append(var)
            continue
        ratios[var] = f / b
        if abs(f / b - 1.0) > tolerance:
            moved.append(var)
    return {"ratios": ratios, "moved_variables": moved, "effective": bool(moved), "tolerance": tolerance}
