"""Write :class:`SoilProfile` objects to a project's soil tables.

Replaces the placeholder rows written by
:func:`swatplus_builder.db.seed.seed_minimal_soils` (ADR-017) with
real, layered soil data.

Schema contract is identical to ``db.seed``:

* ``soils_sol`` — one row per profile (UNIQUE on ``name``).
* ``soils_sol_layer`` — N rows per profile, FK to ``soils_sol.id``,
  ordered by ``layer_num``.

Idempotent:
    Calling ``write_soils`` twice with the same bundle produces the
    same DB state. Re-writes use ``DELETE FROM soils_sol WHERE name
    IN (...)`` (CASCADE drops layers) followed by fresh ``INSERT``s so
    there's no stale-column risk if a caller swaps in different horizon
    counts for a given name.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..db.seed import SOILS_SOL_DDL, SOILS_SOL_LAYER_DDL
from ..errors import SwatBuilderInputError, SwatBuilderPipelineError
from ..types import SoilProfile

__all__ = [
    "SoilsWriteResult",
    "write_soils",
]


@dataclass(frozen=True)
class SoilsWriteResult:
    """Summary of a :func:`write_soils` call."""

    project_db: Path
    profiles_written: int
    layers_written: int
    replaced_names: tuple[str, ...]
    """Names that already existed in ``soils_sol`` and got replaced.

    Useful for pipelines that first call ``seed_minimal_soils`` and
    then upgrade to real data — every entry here is a placeholder
    that got overwritten.
    """


def write_soils(
    profiles: Iterable[SoilProfile],
    project_db: Path | str,
    *,
    create_tables: bool = True,
) -> SoilsWriteResult:
    """Upsert soil profiles into a project's ``soils_sol`` + ``soils_sol_layer``.

    Args:
        profiles: Iterable of :class:`SoilProfile`. Duplicate ``name``
            values within the input are rejected (the editor's UNIQUE
            constraint would catch it at commit time anyway, but failing
            early gives a clearer error).
        project_db: Path to the project sqlite. Created tables are
            compatible with the editor's peewee models
            (:data:`db.seed.SOILS_SOL_DDL` / ``SOILS_SOL_LAYER_DDL``).
        create_tables: If True (default), ensure the two tables exist
            using ``CREATE TABLE IF NOT EXISTS``. Pass ``False`` if the
            caller has already run ``create_project_db`` or the editor's
            ``setup_project`` and wants a harder error on missing
            tables.

    Returns:
        :class:`SoilsWriteResult` with row counts and the list of names
        that were replaced.

    Raises:
        SwatBuilderInputError:    ``profiles`` is empty, or contains a
            duplicate ``name``, or the project DB path doesn't exist.
        SwatBuilderPipelineError: ``create_tables=False`` but the soil
            tables don't exist, or a profile claims layers but the
            Pydantic invariants weren't preserved (defensive check).
    """
    project_db = Path(project_db).expanduser().resolve()
    if not project_db.exists():
        raise SwatBuilderInputError(
            f"project_db does not exist: {project_db}",
            project_db=str(project_db),
        )

    profile_list = list(profiles)
    if not profile_list:
        raise SwatBuilderInputError("write_soils() got zero profiles", profiles=[])

    _check_unique_names(profile_list)
    _check_layer_order(profile_list)

    conn = sqlite3.connect(str(project_db))
    try:
        if create_tables:
            conn.executescript(SOILS_SOL_DDL + SOILS_SOL_LAYER_DDL)
        else:
            _assert_tables_exist(conn)

        # Foreign-key enforcement is OFF by default in sqlite; enable it
        # so our ON DELETE CASCADE actually cascades when we replace a
        # soil row.
        conn.execute("PRAGMA foreign_keys = ON")

        names = tuple(p.name for p in profile_list)
        replaced = _existing_names(conn, names)
        if replaced:
            # Parameterized IN clause — the count is bounded by the
            # caller so we can safely expand placeholders without a
            # hard cap.
            placeholders = ",".join("?" for _ in replaced)
            conn.execute(
                f"DELETE FROM soils_sol WHERE name IN ({placeholders})",
                replaced,
            )

        total_layers = 0
        with conn:  # implicit transaction
            for profile in profile_list:
                cur = conn.execute(
                    "INSERT INTO soils_sol "
                    "(name, hyd_grp, dp_tot, anion_excl, perc_crk, texture, description) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        profile.name,
                        profile.hyd_grp,
                        profile.dp_tot,
                        profile.anion_excl,
                        profile.perc_crk,
                        profile.texture,
                        profile.description,
                    ),
                )
                soil_id = cur.lastrowid
                if soil_id is None:
                    raise SwatBuilderPipelineError(
                        f"sqlite did not return a rowid for soil {profile.name!r}",
                        name=profile.name,
                    )
                conn.executemany(
                    "INSERT INTO soils_sol_layer "
                    "(soil_id, layer_num, dp, bd, awc, soil_k, carbon, "
                    " clay, silt, sand, rock, alb, usle_k, ec, caco3, ph) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _layer_rows(soil_id, profile),
                )
                total_layers += len(profile.layers)

        return SoilsWriteResult(
            project_db=project_db,
            profiles_written=len(profile_list),
            layers_written=total_layers,
            replaced_names=replaced,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _check_unique_names(profiles: list[SoilProfile]) -> None:
    seen: set[str] = set()
    dupes: list[str] = []
    for p in profiles:
        if p.name in seen:
            dupes.append(p.name)
        seen.add(p.name)
    if dupes:
        raise SwatBuilderInputError(
            f"duplicate profile names: {sorted(set(dupes))}",
            duplicates=sorted(set(dupes)),
        )


def _check_layer_order(profiles: list[SoilProfile]) -> None:
    """Defensive — Pydantic already enforces min_length, but we rely on
    strict layer_num / dp monotonicity for SWAT+ to read the profile."""
    for p in profiles:
        last_num = 0
        last_dp = 0.0
        for layer in p.layers:
            if layer.layer_num != last_num + 1:
                raise SwatBuilderPipelineError(
                    f"profile {p.name!r}: layer_num must be 1, 2, 3, ... — "
                    f"got {last_num} then {layer.layer_num}",
                    name=p.name,
                    expected=last_num + 1,
                    got=layer.layer_num,
                )
            if layer.dp <= last_dp:
                raise SwatBuilderPipelineError(
                    f"profile {p.name!r}: layer depths must strictly "
                    f"increase — layer {layer.layer_num} dp={layer.dp} "
                    f"not greater than previous {last_dp}",
                    name=p.name,
                    layer_num=layer.layer_num,
                    dp=layer.dp,
                    previous_dp=last_dp,
                )
            last_num = layer.layer_num
            last_dp = layer.dp


def _assert_tables_exist(conn: sqlite3.Connection) -> None:
    for table in ("soils_sol", "soils_sol_layer"):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row is None:
            raise SwatBuilderPipelineError(
                f"project_db is missing table {table!r}; call "
                "write_soils(..., create_tables=True) or run "
                "db.project.create_project_db first",
                missing_table=table,
            )


def _existing_names(conn: sqlite3.Connection, names: tuple[str, ...]) -> tuple[str, ...]:
    if not names:
        return ()
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        f"SELECT name FROM soils_sol WHERE name IN ({placeholders})",
        names,
    ).fetchall()
    return tuple(r[0] for r in rows)


def _layer_rows(soil_id: int, profile: SoilProfile):
    for layer in profile.layers:
        yield (
            soil_id,
            layer.layer_num,
            layer.dp,
            layer.bd,
            layer.awc,
            layer.soil_k,
            layer.carbon,
            layer.clay,
            layer.silt,
            layer.sand,
            layer.rock,
            layer.alb,
            layer.usle_k,
            layer.ec,
            layer.caco3,
            layer.ph,
        )
