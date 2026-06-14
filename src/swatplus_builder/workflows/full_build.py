"""Package-owned full-mode basin build handoff.

The current production build implementation still lives in
``examples/usgs_basin_workflow.py``. This module is the canonical package boundary:
workflow code calls this wrapper, receives typed success/blocker metadata, and
never shells out to ad hoc scripts or derives claim policy from them.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class FullModelBuildResult:
    success: bool
    status: str
    outdir: str
    txtinout_dir: str | None = None
    blocker_class: str | None = None
    message: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    diagnostics_tail: str | None = None
    diagnostic_artifacts: dict[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_full_model(
    *,
    usgs_id: str,
    outdir: Path | str,
    start_date: str,
    end_date: str,
    warmup_years: int,
    allow_diagnostic_fallbacks: bool = False,
) -> FullModelBuildResult:
    """Build and initially execute a full SWAT+ model for one USGS basin.

    The wrapper intentionally runs the example builder with engine execution
    enabled because the builder's publishing stage evaluates simulated output.
    The canonical workflow still performs a second clean solver run before
    locking/calibration, so stale outputs from the builder are not final
    evidence.
    """
    out = Path(outdir).expanduser().resolve()
    try:
        env_overrides = (
            {
                "SWATPLUS_ALLOW_SYNTHETIC_SOILS": "1",
                "SWATPLUS_MAX_SOIL_FALLBACK_RATIO": "1.0",
            }
            if allow_diagnostic_fallbacks
            else {}
        )
        with _temporary_usgs_id(usgs_id), _temporary_env(env_overrides):
            module = _load_example_builder()
            # usgs_basin_workflow.main reads a CLI-created global args object
            # for model_family in two locations. Provide the minimum object
            # needed to keep the package wrapper deterministic.
            module.STATION_ID = usgs_id
            module.log = logging.getLogger(f"swat_build_{usgs_id}")
            module.args = SimpleNamespace(model_family="full")
            module.main(
                out,
                run_engine=True,
                sim_start=start_date,
                sim_end=end_date,
                warmup_years=int(warmup_years),
            )
    except Exception as exc:
        blocker = _classify_build_error(exc)
        if blocker == "soil_realism_gate_failed":
            _write_soil_realism_diagnostics(out, exc, usgs_id=usgs_id)
        return FullModelBuildResult(
            success=False,
            status="BLOCKED",
            outdir=str(out),
            blocker_class=blocker,
            message=str(exc),
            stdout_tail=_context_tail(exc, "stdout_tail"),
            stderr_tail=_context_tail(exc, "stderr_tail"),
            diagnostics_tail=_context_tail(exc, "diagnostics_tail"),
            diagnostic_artifacts=_build_diagnostic_artifacts(out),
        )

    txt = out / "project" / "Scenarios" / "Default" / "TxtInOut"
    if not (txt.is_dir() and (txt / "file.cio").exists()):
        return FullModelBuildResult(
            success=False,
            status="BLOCKED",
            outdir=str(out),
            blocker_class="full_model_build_missing_txtinout",
            message="Full model build completed without project/Scenarios/Default/TxtInOut.",
            diagnostic_artifacts=_build_diagnostic_artifacts(out),
        )
    return FullModelBuildResult(
        success=True,
        status="SUCCESS",
        outdir=str(out),
        txtinout_dir=str(txt),
        diagnostic_artifacts=_build_diagnostic_artifacts(out),
    )


def _load_example_builder():
    # Resolve relative to the package so this works after `pip install`
    # (the script is bundled at swatplus_builder/examples/usgs_basin_workflow.py).
    # Fall back to the repo examples/ directory for editable installs.
    pkg_path = Path(__file__).resolve().parent.parent / "examples" / "usgs_basin_workflow.py"
    repo_path = Path(__file__).resolve().parents[3] / "examples" / "usgs_basin_workflow.py"
    path = pkg_path if pkg_path.exists() else repo_path
    if not path.exists():
        raise FileNotFoundError(
            f"Full model builder not found at {pkg_path} or {repo_path}. "
            "Re-install the package: pip install --upgrade swatplus-builder"
        )
    spec = importlib.util.spec_from_file_location(
        "swatplus_builder_package_usgs_basin_workflow",
        path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load full model builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _temporary_usgs_id(usgs_id: str) -> Iterator[None]:
    old = os.environ.get("USGS_ID")
    os.environ["USGS_ID"] = usgs_id
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("USGS_ID", None)
        else:
            os.environ["USGS_ID"] = old


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    old = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _classify_build_error(exc: Exception) -> str:
    text = _error_text(exc)
    if any(
        token in text
        for token in (
            "dns",
            "name resolution",
            "temporary failure",
            "connection",
            "urlopen error",
            "nodename nor servname",
            "timed out",
            "timeout",
            "could not resolve host",
            "could not contact dns servers",
            "failed to establish a new connection",
            "network is unreachable",
            "planetary computer",
            "stac query failed",
            "maximum allowed time",
        )
    ):
        return "external_data_provider_unreachable"
    if any(token in text for token in (
        "gridmet", "server may have clamped", "date range",
        "daymet", "too_many", "too_few", "date-range argument was likely ignored",
        "thredds server may have clamped",
    )):
        return "weather_provider_data_gap"
    if "hru realism gate failed" in text:
        return "hru_overlay_realism_failed"
    if "soil realism gate failed" in text or "soil acquisition failed" in text:
        return "soil_realism_gate_failed"
    if "hyd_connect" in text or "ru_read_elements" in text:
        return "engine_hyd_connect_failed_during_build"
    if any(token in text for token in ("swat+ engine", "simulation.out", "channel_sd_day", "binary")):
        return "engine_run_failed_during_build"
    if any(
        token in text
        for token in ("delineation", "subbasin", "outlet", "topology", "d8flowaccumulation", "d8_flow_acc", "flow_acc")
    ):
        return "full_model_build_topology_failed"
    return "full_model_build_failed"


def _error_text(exc: Exception) -> str:
    parts = [str(exc)]
    context = getattr(exc, "context", None)
    if isinstance(context, dict):
        for key in ("stderr_tail", "stdout_tail", "diagnostics_tail"):
            value = context.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts).lower()


def _context_tail(exc: Exception, key: str) -> str | None:
    context = getattr(exc, "context", None)
    if not isinstance(context, dict):
        return None
    value = context.get(key)
    return str(value) if value is not None else None


def _build_diagnostic_artifacts(outdir: Path) -> dict[str, str] | None:
    candidates = {
        "overlay_repair_report": outdir / "reports" / "overlay_repair" / "overlay_repair_report.json",
        "soil_acquisition_report": outdir / "reports" / "soil_acquisition_report.json",
        "soil_realism_diagnostics": outdir / "reports" / "soil_realism_diagnostics.json",
        "soil_report": outdir / "reports" / "soil_report.json",
        "watershed_result": outdir / "delin" / "watershed_result.json",
        "delineation_validation": outdir / "delin" / "validation_result.json",
        "threshold_selection": outdir / "delin" / "threshold_selection.json",
    }
    found = {key: str(path) for key, path in candidates.items() if path.is_file()}
    return found or None


def _write_soil_realism_diagnostics(outdir: Path, exc: Exception, *, usgs_id: str) -> Path:
    path = outdir / "reports" / "soil_realism_diagnostics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "usgs_id": usgs_id,
        "blocker_class": "soil_realism_gate_failed",
        "message": str(exc),
        "stdout_tail": _context_tail(exc, "stdout_tail"),
        "stderr_tail": _context_tail(exc, "stderr_tail"),
        "diagnostics_tail": _context_tail(exc, "diagnostics_tail"),
        "source_priority": _soil_source_priority_manifest(),
        "source_backed_alternatives": _soil_source_backed_alternatives(),
        "recommended_probe_order": _soil_recommended_probe_order(),
        "next_actions": [
            "Inspect soil acquisition provenance and fallback ratio before accepting research-grade claims.",
            "Prefer authoritative gNATSGO/Soil Data Access coverage or an explicit external soils JSON before rerunning.",
            "Use synthetic or constant representative soils only for diagnostic runs with claim downgrade.",
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _soil_source_priority_manifest() -> list[dict[str, object]]:
    return [
        {
            "tier": 1,
            "source": "gNATSGO_raster_plus_SDA_horizons",
            "authority": "USDA_NRCS_high_fidelity",
            "research_grade_eligible": True,
            "reason": "Preserves spatial map-unit heterogeneity and uses USDA horizon data.",
        },
        {
            "tier": 2,
            "source": "SDA_spatial_representative_mukey",
            "authority": "USDA_NRCS_degraded_representative",
            "research_grade_eligible": False,
            "reason": "Uses real USDA mukey/horizon data but collapses spatial heterogeneity to one representative soil.",
        },
        {
            "tier": 3,
            "source": "SoilGrids_v2_coarse",
            "authority": "ISRIC_global_coarse_fallback",
            "research_grade_eligible": False,
            "reason": "Uses global 250 m predicted properties and is lower authority than USDA NRCS soil survey data.",
        },
        {
            "tier": 4,
            "source": "synthetic_minimal_soils",
            "authority": "diagnostic_only",
            "research_grade_eligible": False,
            "reason": "Allows engine diagnostics only and cannot support soil-fidelity claims.",
        },
    ]


def _soil_source_backed_alternatives() -> list[dict[str, object]]:
    return [
        {
            "rank": 1,
            "option": "recover_gnatsgo_raster_plus_sda_horizons",
            "source": "USDA NRCS gNATSGO provides gridded best-available U.S. soil survey data; SDA provides tabular horizon attributes by MUKEY.",
            "required_artifacts": ["raw/mukey.tif", "gnatsgo_cache/sda_cache.json", "reports/soil_report.json"],
            "fresh_output_required": True,
            "claim_impact": "research_grade_eligible_if_soil_fidelity_and_downstream_gates_pass",
            "rationale": "This preserves spatial map-unit heterogeneity and uses USDA horizon data.",
        },
        {
            "rank": 2,
            "option": "query_usda_sda_spatial_representative_mukey",
            "source": "USDA SDA spatial functions can return MUKEYs intersecting a WGS84 WKT geometry.",
            "required_artifacts": ["raw/basin_boundary.gpkg", "reports/soil_acquisition_report.json"],
            "fresh_output_required": True,
            "claim_impact": "degraded_diagnostic_until_spatial_soil_heterogeneity_is_restored",
            "rationale": "Useful when the gNATSGO raster path fails, but representative-mukey collapse is not high-fidelity.",
        },
        {
            "rank": 3,
            "option": "use_soilgrids_v2_coarse_gap_fill",
            "source": "ISRIC SoilGrids v2 provides global machine-learning soil property predictions at 250 m resolution.",
            "required_artifacts": ["reports/soil_acquisition_report.json", "reports/soil_report.json"],
            "fresh_output_required": True,
            "claim_impact": "diagnostic_or_degraded_only_not_soil_fidelity_research_grade",
            "rationale": "SoilGrids can fill missing profiles, but it is coarser and lower authority than USDA survey data for U.S. basins.",
        },
        {
            "rank": 4,
            "option": "allow_synthetic_or_constant_soils_for_engine_diagnostics_only",
            "source": "Project claim policy: synthetic or constant representative soils can keep SWAT+ executable but block soil-fidelity claims.",
            "required_artifacts": ["metadata.json", "reports/soil_realism_diagnostics.json"],
            "fresh_output_required": True,
            "claim_impact": "exploratory_only_soil_fidelity_gate_blocks_research_grade",
            "rationale": "Diagnostic fallback can expose routing/weather/calibration blockers without pretending soil provenance is authoritative.",
        },
    ]


def _soil_recommended_probe_order() -> list[dict[str, object]]:
    return [
        {
            "rank": row["rank"],
            "diagnostic": row["option"],
            "required_artifacts": row["required_artifacts"],
            "fresh_output_required": row["fresh_output_required"],
            "claim_impact": row["claim_impact"],
        }
        for row in _soil_source_backed_alternatives()
    ]
