"""Shared typed data models exchanged between stages.

These are pydantic models so they serialize to JSON automatically for MCP
and CLI use, and validate at the boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class Outlet(BaseModel):
    """A watershed outlet. Either (lon, lat) or a USGS gauge id."""

    lon: float | None = None
    lat: float | None = None
    usgs_id: str | None = None

    def as_tuple(self) -> tuple[float, float] | None:
        if self.lon is not None and self.lat is not None:
            return (self.lon, self.lat)
        return None


class WatershedResult(BaseModel):
    """Output of :func:`swatplus_builder.tools.build_watershed`.

    All paths are absolute. Geometry files are GeoPackage layers in the project CRS.
    """

    workdir: Path
    crs: str = Field(..., description="EPSG code of the project CRS, e.g. 'EPSG:5070'.")
    dem_conditioned: Path
    flow_dir: Path
    flow_acc: Path
    streams_raster: Path
    subbasins_vector: Path
    channels_vector: Path
    outlets_vector: Path
    routing_graph: Path = Field(..., description="GraphML of subbasin routing topology.")
    stats: dict[str, float] = Field(
        default_factory=dict,
        description="Summary: n_subbasins, n_channels, total_area_km2, mean_slope, …",
    )
    reports: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured stage reports (JSON-serializable), e.g. soil_report.",
    )


class HRUResult(BaseModel):
    """Output of :func:`swatplus_builder.tools.create_hrus`."""

    workdir: Path
    lsus_vector: Path = Field(..., description="Landscape units (floodplain + upslope).")
    hrus_vector: Path
    hru_raster: Path = Field(..., description="Raster where each pixel is labelled with its HRU id.")
    catalog_path: Path = Field(..., description="JSON catalog of HRU types and areas.")
    stats: dict[str, float] = Field(default_factory=dict)


class SwatPlusProject(BaseModel):
    """Output of :func:`swatplus_builder.tools.generate_swat_project`."""

    workdir: Path
    project_name: str
    project_db: Path = Field(..., description="Path to <project_name>.sqlite.")
    txtinout_dir: Path = Field(..., description="Scenarios/Default/TxtInOut.")
    reference_db: Path
    wgn_db: Path
    sim_start: str
    sim_end: str


class SwatPlusRun(BaseModel):
    """Output of :func:`swatplus_builder.tools.run_swat`.

    Also returned by :func:`swatplus_builder.run.swatplus.run` when called
    directly against a ``TxtInOut/`` directory (``project`` is then ``None``).
    """

    project: SwatPlusProject | None = Field(
        default=None,
        description="Originating project, if the runner was invoked via the "
        "agent tool. ``None`` when the runner was pointed at a bare "
        "``TxtInOut/`` directory.",
    )
    binary: Path = Field(..., description="Absolute path to the SWAT+ engine that was executed.")
    engine_version: str | None = Field(
        default=None,
        description="Engine revision parsed from the binary's own startup banner "
        "(e.g. '61.0.2.61'). This is the VERIFIED version that produced these "
        "outputs — read from the engine itself, never operator-asserted. ``None`` "
        "only if the banner could not be parsed.",
    )
    txtinout_dir: Path = Field(..., description="CWD the engine ran in.")
    command: list[str] = Field(
        default_factory=list,
        description="argv used to spawn the engine (first element is the binary).",
    )
    exit_code: int
    runtime_seconds: float
    success: bool = Field(..., description="``exit_code == 0``. Cached so JSON consumers don't recompute.")
    output_dir: Path = Field(..., description="Where outputs landed (usually == txtinout_dir).")
    output_files: list[Path] = Field(
        default_factory=list,
        description="All ``*.out`` / ``*.txt`` output files written during the run.",
    )
    diagnostics_tail: str = Field(
        default="",
        description="Last ~4 KB of ``diagnostics.out`` if it exists, else empty.",
    )
    stdout_tail: str = Field(default="")
    stderr_tail: str = Field(default="")
    paths: dict[str, Path] = Field(
        default_factory=dict,
        description="Convenience map: 'diagnostics', 'basin_wb_aa', 'channel_sd_aa', …",
    )
    summary: dict[str, float] = Field(
        default_factory=dict,
        description="Quick stats: mean_q_at_outlet, total_sediment, …",
    )


HydType = Literal["tot", "sur", "lat", "til", "aqu", "rhg"]
"""SWAT+ hydrograph types used in ``gis_routing.hyd_typ``.

Includes total, surface, lateral, tile, aquifer, and recharge hydrograph codes.
The SWAT+ Editor datasets contract defines ``rhg`` as recharge.
"""

ObjectCat = Literal[
    "HRU", "LSU", "CH", "SUB", "SBR", "RES", "PND", "WETL",
    "AQU", "DAQ", "PT", "X",
]
"""Object categories used in ``gis_routing.{source,sink}cat``.

Mirrors the case-sensitive strings used by QSWATPlus's
``DBUtils.addToRouting``. ``'X'`` is the reserved "watershed outlet / exit"
sink (``sinkid=0, sinkcat='X'``).
"""


# ---------------------------------------------------------------------------
# gis_* row models — the typed intermediate representation that
# :mod:`swatplus_builder.db.writer` consumes.
#
# These mirror the positional INSERT signatures in
# :mod:`swatplus_builder.db.schema`. Every field carries its unit in its
# description so ``model_dump_json()`` is self-describing for agent use.
#
# Units used by QSWATPlus (see ``docs/SCHEMA.md``):
#   * Areas in **hectares** (not m² or km²).
#   * Slopes in **percent** (0-100), NOT fractions 0-1.
#   * Lengths in **meters**.
#   * Elevations in **meters** above sea level.
#   * ``gis_routing.percent`` in **0-100** (not 0-1).
# ---------------------------------------------------------------------------


class SubbasinRow(BaseModel):
    """One row of ``gis_subbasins``. 1-indexed ids."""

    id: int = Field(..., ge=1)
    area: float = Field(..., ge=0.0, description="Subbasin area in hectares.")
    slo1: float = Field(..., description="Mean slope, percent (0-100).")
    len1: float = Field(..., ge=0.0, description="Longest flow path, meters.")
    sll: float = Field(..., ge=0.0, description="Slope length, meters.")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float = Field(..., description="Mean elevation, meters MSL.")
    elevmin: float
    elevmax: float
    waterid: int = Field(
        default=0,
        description="id of reservoir/pond at subbasin outlet, 0 if none.",
    )


class ChannelRow(BaseModel):
    """One row of ``gis_channels``. 1-indexed; ``subbasin`` is the parent id."""

    id: int = Field(..., ge=1)
    subbasin: int = Field(..., ge=1)
    areac: float = Field(..., ge=0.0, description="Drainage area at outlet, hectares.")
    strahler: int = Field(..., ge=1)
    len2: float = Field(..., ge=0.0, description="Channel length, meters.")
    slo2: float = Field(..., description="Channel slope, percent (0-100).")
    wid2: float = Field(..., ge=0.0, description="Channel width at bankfull, meters.")
    dep2: float = Field(..., ge=0.0, description="Channel depth at bankfull, meters.")
    elevmin: float
    elevmax: float
    midlat: float = Field(..., ge=-90.0, le=90.0)
    midlon: float = Field(..., ge=-180.0, le=180.0)


LsuCategory = Literal[0, 1, 2]
"""``gis_lsus.category`` — ``0`` = no-landscape, ``1`` = floodplain, ``2`` = upslope."""


class LsuRow(BaseModel):
    """One row of ``gis_lsus``. ``channel`` is the parent channel id."""

    id: int = Field(..., ge=1)
    category: LsuCategory
    channel: int = Field(..., ge=1)
    subbasin: int = Field(..., ge=1)
    area: float = Field(..., ge=0.0, description="LSU area, hectares.")
    slope: float = Field(..., description="Mean slope, percent (0-100).")
    len1: float = Field(..., ge=0.0, description="Tributary flow length, meters.")
    csl: float = Field(..., description="Channel slope along tributary, percent.")
    wid1: float = Field(..., ge=0.0, description="Tributary channel width, meters.")
    dep1: float = Field(..., ge=0.0, description="Tributary channel depth, meters.")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float


class HruRow(BaseModel):
    """One row of ``gis_hrus``. ``lsu`` is the parent LSU id.

    QSWATPlus semantics per ``hrus.py:3435``:

    * ``arsub`` — **parent subbasin's total area** (hectares), repeated for
      every HRU in the subbasin.
    * ``arlsu`` — **parent LSU's total area** (hectares), repeated for
      every HRU in the LSU.
    * ``arland`` — total area of this ``landuse`` within the parent LSU,
      hectares.
    * ``arso`` — total area of this (``landuse``, ``soil``) pair within the
      parent LSU, hectares.
    * ``arslp`` — **this HRU's own area**, hectares.
    * ``slope`` — this HRU's mean slope, percent (0-100).
    * ``slp`` — the slope band label, e.g. ``"0-5"``, ``"5-20"``.
    """

    id: int = Field(..., ge=1)
    lsu: int = Field(..., ge=1)
    arsub: float = Field(..., ge=0.0)
    arlsu: float = Field(..., ge=0.0)
    landuse: str
    arland: float = Field(..., ge=0.0)
    soil: str
    arso: float = Field(..., ge=0.0)
    slp: str
    arslp: float = Field(..., ge=0.0)
    slope: float
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float


WaterType = Literal["RES", "PND", "WETL"]


class WaterRow(BaseModel):
    """One row of ``gis_water``."""

    id: int = Field(..., ge=1)
    wtype: WaterType
    lsu: int = Field(..., ge=0, description="Host LSU id, or 0 if none.")
    subbasin: int = Field(..., ge=1)
    area: float = Field(..., ge=0.0, description="Surface area, hectares.")
    xpr: float = Field(..., description="Projected centroid x, project CRS units.")
    ypr: float = Field(..., description="Projected centroid y, project CRS units.")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float


PointType = Literal["O", "I", "P", "L", "W"]
"""``gis_points.ptype`` — O=outlet, I=inlet, P=point source, L=lake outflow, W=weather."""


class PointRow(BaseModel):
    """One row of ``gis_points``. QSWATPlus uses 1-indexed ids."""

    id: int = Field(..., ge=1)
    subbasin: int = Field(..., ge=0, description="Host subbasin id, 0 if global.")
    ptype: PointType
    xpr: float
    ypr: float
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float


class RoutingRow(BaseModel):
    """One row of ``gis_routing``.

    Multiple rows may share ``(sourceid, sourcecat)`` because a single source
    can split into several sinks (ADR-013). For each ``(source, hyd_typ)``
    group the sum of ``percent`` must equal 100 (±0.5). There must be at most
    one row per ``(sourceid, sourcecat, sinkid, sinkcat, hyd_typ)`` triple.

    ``hyd_typ`` is nullable in the DDL (used by certain aquifer rows).
    """

    sourceid: int = Field(..., ge=0)
    sourcecat: ObjectCat
    hyd_typ: HydType | None = None
    sinkid: int = Field(..., ge=0)
    sinkcat: ObjectCat
    percent: float = Field(..., ge=0.0, le=100.0)


class AquiferRow(BaseModel):
    """One row of ``gis_aquifers``. 1-indexed."""

    id: int = Field(..., ge=1)
    category: int = Field(..., description="1=floodplain aquifer, 2=upslope.")
    subbasin: int = Field(..., ge=1)
    deep_aquifer: int = Field(..., ge=1)
    area: float = Field(..., ge=0.0, description="Aquifer area, hectares.")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float


class DeepAquiferRow(BaseModel):
    """One row of ``gis_deep_aquifers``."""

    id: int = Field(..., ge=1)
    subbasin: int = Field(..., ge=1)
    area: float = Field(..., ge=0.0)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float


# ---------------------------------------------------------------------------
# Weather — daily timeseries typed representation.
#
# The SWAT+ engine reads plaintext per-station weather files
# (``.pcp / .tmp / .hmd / .wnd / .slr``) indexed via
# ``pcp.cli``, ``tmp.cli``, etc. Each station has its own file per variable;
# a single station may not have every variable. These types carry a daily
# timeseries that :mod:`swatplus_builder.weather.writer` serializes to that
# format.
# ---------------------------------------------------------------------------


WeatherVar = Literal["pcp", "tmp", "hmd", "wnd", "slr"]
"""Per-variable SWAT+ file extensions (matches the editor's ``WEATHER_DESC``
keys minus ``pet``, which is optional and derived)."""


class WeatherStation(BaseModel):
    """Metadata for one virtual weather station (no timeseries)."""

    name: str = Field(
        ...,
        description="Stable station id. Convention: ``s<lat*1000><n|s><lon*1000><e|w>``, "
        "e.g. ``s41100n77500w``. The editor derives this from lat/lon "
        "during import_weather; we match the convention up-front so the "
        "weather_sta_cli rows are predictable.",
    )
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    elev: float = Field(..., description="Meters MSL.")


class StationSeries(BaseModel):
    """One station's daily timeseries across any subset of the five SWAT+
    weather variables.

    All variable arrays, when present, MUST have the same length as the
    date range ``[start, start + N days)`` implied by :attr:`start` and
    :attr:`n_days`. This is asserted by the writer.

    Units:
        * ``pcp`` — millimeters / day
        * ``tmax``, ``tmin`` — degrees Celsius
        * ``hmd`` — relative humidity, **fraction 0-1** (not percent)
        * ``wnd`` — wind speed, meters / second, at 10 m
        * ``slr`` — solar radiation, MJ / m² / day
    """

    station: WeatherStation
    start: str = Field(
        ...,
        description="ISO date ``YYYY-MM-DD`` of the **first** day in every "
        "variable array.",
    )
    n_days: int = Field(..., ge=1)
    pcp: list[float] | None = None
    tmax: list[float] | None = None
    tmin: list[float] | None = None
    hmd: list[float] | None = None
    wnd: list[float] | None = None
    slr: list[float] | None = None

    def variables(self) -> list[WeatherVar]:
        """Return the weather variable codes this series carries data for."""
        present: list[WeatherVar] = []
        if self.pcp is not None:
            present.append("pcp")
        if self.tmax is not None and self.tmin is not None:
            present.append("tmp")
        if self.hmd is not None:
            present.append("hmd")
        if self.wnd is not None:
            present.append("wnd")
        if self.slr is not None:
            present.append("slr")
        return present


class WeatherBundle(BaseModel):
    """A complete per-basin weather dataset ready for SWAT+ ingestion.

    Produced by weather adapters (``weather/synthetic.py`` for tests,
    ``weather/gridmet.py`` for GridMET, user code for BYO data). Consumed
    by :func:`swatplus_builder.weather.writer.write_observed`.

    Invariants:
        * All :class:`StationSeries` share the same ``start`` and ``n_days``.
          (SWAT+ doesn't strictly require this, but the editor's validator
          emits warnings when dates disagree; we enforce uniformity to
          keep inputs simple.)
        * Every variable carried by ANY station must have at least one
          station providing it. (A ``pcp.cli`` with zero entries would
          break ``import_weather``.)
    """

    stations: list[StationSeries] = Field(..., min_length=1)
    start: str
    n_days: int = Field(..., ge=1)


HydGroup = Literal["A", "B", "C", "D"]
"""USDA-NRCS hydrological soil group. Dual codes (e.g. ``A/D``) collapse
to the worst drainage class (``D``) during ingestion; SWAT+ does not
understand the slash form."""


class SoilHorizon(BaseModel):
    """One soil horizon (layer) with SWAT+-ready parameters.

    All fields are in SWAT+ file units — conversions from SSURGO/gNATSGO
    native units are done in :mod:`swatplus_builder.soil.params`. This
    type is what the writer consumes, so downstream code (adapters,
    user BYO data) only needs to produce values in these units.

    Units:
        * ``dp``      — mm below land surface to the BOTTOM of this horizon.
        * ``bd``      — bulk density, g/cm³ (= Mg/m³).
        * ``awc``     — available water capacity, mm water / mm soil (fraction).
        * ``soil_k``  — saturated hydraulic conductivity, mm/hour.
        * ``carbon``  — organic carbon content, % of mass.
        * ``clay``, ``silt``, ``sand``, ``rock`` — % of mass.
        * ``alb``     — soil albedo, 0–1 fraction (bare soil, wet).
        * ``usle_k``  — soil erodibility factor, t·ha·h / (ha·MJ·mm).
        * ``ec``      — electrical conductivity of saturated extract, dS/m.
        * ``caco3``   — CaCO₃ content, % (null if unknown).
        * ``ph``      — 1:1 soil:water pH (null if unknown).
    """

    layer_num: int = Field(..., ge=1, description="1-based horizon index within the profile.")
    dp: float = Field(..., gt=0.0, description="Depth (mm) to bottom of horizon.")
    bd: float = Field(..., gt=0.0, le=3.0)
    awc: float = Field(..., ge=0.0, le=1.0)
    soil_k: float = Field(..., ge=0.0)
    carbon: float = Field(..., ge=0.0, le=100.0)
    clay: float = Field(..., ge=0.0, le=100.0)
    silt: float = Field(..., ge=0.0, le=100.0)
    sand: float = Field(..., ge=0.0, le=100.0)
    rock: float = Field(..., ge=0.0, le=100.0)
    alb: float = Field(..., ge=0.0, le=1.0)
    usle_k: float = Field(..., ge=0.0, le=1.0)
    ec: float = Field(..., ge=0.0)
    caco3: float | None = Field(default=None, ge=0.0, le=100.0)
    ph: float | None = Field(default=None, ge=0.0, le=14.0)


class SoilProfile(BaseModel):
    """A SWAT+ soil, i.e. one ``soils_sol`` row + its ``soils_sol_layer``s.

    ``name`` must match every ``gis_hrus.soil`` value that should use
    this profile — the editor cross-checks at ``import_gis`` time.

    Invariants:
        * :attr:`layers` is non-empty.
        * Layer ``layer_num`` values are strictly increasing from 1.
        * Layer ``dp`` values (bottom depths) are strictly increasing.
    """

    name: str = Field(..., min_length=1, max_length=255)
    hyd_grp: HydGroup
    anion_excl: float = Field(default=0.5, ge=0.0, le=1.0, description="Fraction; SWAT+ default 0.5.")
    perc_crk: float = Field(default=0.0, ge=0.0, le=1.0, description="Crack percolation; default 0.")
    texture: str | None = Field(default=None, max_length=255)
    description: str | None = None
    source: str | None = Field(default=None, description="Data origin (e.g., 'horizon_sda', 'aggregated_muaggatt').")
    layers: list[SoilHorizon] = Field(..., min_length=1)

    @property
    def dp_tot(self) -> float:
        """Total profile depth = deepest horizon's bottom (mm)."""
        return max(layer.dp for layer in self.layers)


class GisTables(BaseModel):
    """In-memory representation of everything that goes into the ``gis_*``
    tables for one project.

    Produced by the GIS stage (``gis.build_tables``) and consumed by
    :func:`swatplus_builder.db.writer.write_all`. Fully JSON-serializable so
    it can be persisted as an intermediate artifact and introspected by
    agents before the write is committed.
    """

    subbasins: list[SubbasinRow] = Field(default_factory=list)
    channels: list[ChannelRow] = Field(default_factory=list)
    lsus: list[LsuRow] = Field(default_factory=list)
    hrus: list[HruRow] = Field(default_factory=list)
    water: list[WaterRow] = Field(default_factory=list)
    points: list[PointRow] = Field(default_factory=list)
    routing: list[RoutingRow] = Field(default_factory=list)
    aquifers: list[AquiferRow] = Field(default_factory=list)
    deep_aquifers: list[DeepAquiferRow] = Field(default_factory=list)
