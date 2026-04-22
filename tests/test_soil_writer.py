"""Tests for :mod:`swatplus_builder.soil.writer`.

Hermetic — uses ``sqlite3`` directly (no editor, no network). Each
test builds a brand-new file DB so parallel runs don't step on each
other.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from swatplus_builder.db.seed import seed_minimal_soils
from swatplus_builder.errors import (
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)
from swatplus_builder.soil import SoilsWriteResult, write_soils
from swatplus_builder.types import SoilHorizon, SoilProfile


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _mk_horizon(layer_num: int, dp: float, **overrides) -> SoilHorizon:
    defaults = dict(
        layer_num=layer_num,
        dp=dp,
        bd=1.4,
        awc=0.15,
        soil_k=10.0,
        carbon=1.0,
        clay=20.0,
        silt=40.0,
        sand=40.0,
        rock=2.0,
        alb=0.13,
        usle_k=0.25,
        ec=0.0,
        caco3=None,
        ph=6.5,
    )
    defaults.update(overrides)
    return SoilHorizon(**defaults)


def _mk_profile(name: str, n_layers: int = 2, **head_overrides) -> SoilProfile:
    layers = [
        _mk_horizon(i + 1, dp=100.0 * (i + 1))
        for i in range(n_layers)
    ]
    defaults = dict(
        name=name,
        hyd_grp="B",
        texture="loam",
        description=f"synthetic profile {name}",
        layers=layers,
    )
    defaults.update(head_overrides)
    return SoilProfile(**defaults)


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    path = tmp_path / "project.sqlite"
    sqlite3.connect(str(path)).close()
    return path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_profile(self, empty_db: Path):
        res = write_soils([_mk_profile("loam_A")], empty_db)
        assert isinstance(res, SoilsWriteResult)
        assert res.profiles_written == 1
        assert res.layers_written == 2
        assert res.replaced_names == ()
        assert res.project_db == empty_db

        conn = sqlite3.connect(str(empty_db))
        (n_sol,) = conn.execute("SELECT COUNT(*) FROM soils_sol").fetchone()
        (n_layer,) = conn.execute(
            "SELECT COUNT(*) FROM soils_sol_layer"
        ).fetchone()
        assert n_sol == 1
        assert n_layer == 2

    def test_multiple_profiles_with_different_layer_counts(self, empty_db: Path):
        profiles = [
            _mk_profile("s_1", n_layers=1),
            _mk_profile("s_3", n_layers=3),
            _mk_profile("s_5", n_layers=5),
        ]
        res = write_soils(profiles, empty_db)
        assert res.profiles_written == 3
        assert res.layers_written == 1 + 3 + 5

    def test_dp_tot_derived_from_deepest_layer(self, empty_db: Path):
        p = _mk_profile("t", n_layers=3)
        write_soils([p], empty_db)
        conn = sqlite3.connect(str(empty_db))
        (dp_tot,) = conn.execute(
            "SELECT dp_tot FROM soils_sol WHERE name='t'"
        ).fetchone()
        assert dp_tot == 300.0  # 3 layers × 100 mm steps

    def test_layer_ordering_preserved(self, empty_db: Path):
        write_soils([_mk_profile("p", n_layers=4)], empty_db)
        conn = sqlite3.connect(str(empty_db))
        rows = conn.execute(
            "SELECT layer_num, dp FROM soils_sol_layer "
            "JOIN soils_sol ON soils_sol_layer.soil_id = soils_sol.id "
            "WHERE soils_sol.name = 'p' ORDER BY layer_num"
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3, 4]
        assert [r[1] for r in rows] == [100.0, 200.0, 300.0, 400.0]


# ---------------------------------------------------------------------------
# Idempotency / replacement
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_write_same_profile_replaces(self, empty_db: Path):
        p1 = _mk_profile("loam", n_layers=2)
        write_soils([p1], empty_db)

        # Same name, different layer count — must replace fully.
        p2 = _mk_profile("loam", n_layers=5, description="updated")
        res = write_soils([p2], empty_db)

        assert res.replaced_names == ("loam",)
        assert res.layers_written == 5

        conn = sqlite3.connect(str(empty_db))
        (n_layer,) = conn.execute(
            "SELECT COUNT(*) FROM soils_sol_layer"
        ).fetchone()
        assert n_layer == 5, "stale layers from the first write must be gone"
        (desc,) = conn.execute(
            "SELECT description FROM soils_sol WHERE name='loam'"
        ).fetchone()
        assert desc == "updated"

    def test_replaces_seed_placeholder(self, empty_db: Path):
        """Exercise the primary use case: upgrade from ``seed_minimal_soils``
        to real data without leaving placeholder layers behind."""
        seed_minimal_soils(empty_db, ["loam", "sand"])
        conn = sqlite3.connect(str(empty_db))
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM soils_sol_layer"
        ).fetchone()
        assert before == 2

        real = _mk_profile("loam", n_layers=4)
        res = write_soils([real], empty_db)
        assert res.replaced_names == ("loam",)

        (after_total,) = conn.execute(
            "SELECT COUNT(*) FROM soils_sol_layer"
        ).fetchone()
        # 4 new layers for loam + 1 untouched layer for sand.
        assert after_total == 5

        # Sand's original placeholder row must still be there.
        (sand_rows,) = conn.execute(
            "SELECT COUNT(*) FROM soils_sol WHERE name='sand'"
        ).fetchone()
        assert sand_rows == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_profiles_rejected(self, empty_db: Path):
        with pytest.raises(SwatBuilderInputError, match="zero profiles"):
            write_soils([], empty_db)

    def test_duplicate_names_rejected(self, empty_db: Path):
        p1 = _mk_profile("dup", n_layers=1)
        p2 = _mk_profile("dup", n_layers=2)
        with pytest.raises(SwatBuilderInputError, match="duplicate profile names"):
            write_soils([p1, p2], empty_db)

    def test_missing_project_db_rejected(self, tmp_path: Path):
        with pytest.raises(SwatBuilderInputError, match="does not exist"):
            write_soils([_mk_profile("x")], tmp_path / "missing.sqlite")

    def test_no_create_tables_raises_when_absent(self, empty_db: Path):
        with pytest.raises(SwatBuilderPipelineError, match="is missing table"):
            write_soils([_mk_profile("x")], empty_db, create_tables=False)

    def test_layer_num_not_contiguous_rejected(self, empty_db: Path):
        p = SoilProfile(
            name="bad",
            hyd_grp="B",
            layers=[
                _mk_horizon(layer_num=1, dp=100),
                _mk_horizon(layer_num=3, dp=200),  # skipped 2
            ],
        )
        with pytest.raises(SwatBuilderPipelineError, match="layer_num must be 1"):
            write_soils([p], empty_db)

    def test_non_increasing_dp_rejected(self, empty_db: Path):
        p = SoilProfile(
            name="bad",
            hyd_grp="B",
            layers=[
                _mk_horizon(layer_num=1, dp=200),
                _mk_horizon(layer_num=2, dp=100),  # shallower than layer 1
            ],
        )
        with pytest.raises(SwatBuilderPipelineError, match="must strictly"):
            write_soils([p], empty_db)


# ---------------------------------------------------------------------------
# FK cascade
# ---------------------------------------------------------------------------


class TestCascade:
    def test_delete_sol_row_cascades_to_layers(self, empty_db: Path):
        write_soils([_mk_profile("cas", n_layers=3)], empty_db)
        conn = sqlite3.connect(str(empty_db))
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute("DELETE FROM soils_sol WHERE name='cas'")
        (n_layer,) = conn.execute(
            "SELECT COUNT(*) FROM soils_sol_layer"
        ).fetchone()
        assert n_layer == 0, "CASCADE must drop layers when the sol row is deleted"
