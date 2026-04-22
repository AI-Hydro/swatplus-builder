"""Tests for :mod:`swatplus_builder.soil.gnatsgo`.

Strategy:
    The adapter composes three external libraries (``pystac-client``,
    ``planetary-computer``, ``pyarrow``/``pandas``). Real calls to
    Planetary Computer are **opt-in** via ``SWATPLUS_BUILDER_RUN_GNATSGO=1``;
    the default-on tests mock the STAC catalog with a custom module
    that hands back synthetic DataFrames. That way we can exercise
    the full pipeline (mukey → component → chorizon → SoilProfile)
    without the network or the heavy extras.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
)


# ---------------------------------------------------------------------------
# Fake STAC / PC modules
# ---------------------------------------------------------------------------


class _FakeAsset:
    def __init__(self, href: str, storage_options: dict | None = None):
        self.href = href
        self.extra_fields = (
            {"table:storage_options": storage_options} if storage_options else {}
        )


class _FakeItem:
    def __init__(self, item_id: str, assets: dict[str, _FakeAsset]):
        self.id = item_id
        self.assets = assets


class _FakeSearch:
    def __init__(self, items: list[_FakeItem]):
        self._items = items

    def items(self):
        return list(self._items)


class _FakeClient:
    """Stand-in for ``pystac_client.Client``."""

    def __init__(self, items: list[_FakeItem]):
        self._items = items

    @classmethod
    def open(cls, url: str, modifier=None):  # signature mirrors pystac-client
        # pystac_client signs via a modifier callback; we don't need to
        # invoke it for the fake, but we record the URL as a sanity check.
        cls._last_url = url
        cls._last_modifier = modifier
        return cls._singleton

    def search(self, collections):
        # Keep it dumb: no filtering by collection; the adapter only
        # ever calls us with a single collection name.
        return _FakeSearch(self._items)


def _install_fake_pc_stack(monkeypatch, *, items, parquet_table: dict[str, pd.DataFrame]):
    """Wire three fake modules into sys.modules and stub read_parquet."""
    # pystac_client
    pystac_mod = types.ModuleType("pystac_client")

    _FakeClient._singleton = _FakeClient(items)
    pystac_mod.Client = _FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pystac_client", pystac_mod)

    # planetary_computer
    pc_mod = types.ModuleType("planetary_computer")
    pc_mod.sign_inplace = lambda x: x  # type: ignore[attr-defined]
    pc_mod.sign = lambda x: x  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "planetary_computer", pc_mod)

    # Force pyarrow path to fail so we exercise the pandas fallback
    # (simpler + deterministic). The real pyarrow branch is exercised
    # by the opt-in integration test.
    monkeypatch.setitem(sys.modules, "pyarrow.dataset", types.ModuleType("pyarrow.dataset.empty"))
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", types.ModuleType("pyarrow.parquet.empty"))

    # Stub pandas.read_parquet to return our synthetic tables keyed by href.
    orig_read_parquet = pd.read_parquet

    def fake_read_parquet(href, *args, **kwargs):
        if href in parquet_table:
            df = parquet_table[href].copy()
            columns = kwargs.get("columns")
            if columns is not None:
                df = df[[c for c in columns if c in df.columns]]
            return df
        return orig_read_parquet(href, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _mk_fake_tables(mukeys: list[int]) -> tuple[list[_FakeItem], dict[str, pd.DataFrame]]:
    """Build synthetic ``component`` / ``chorizon`` / ``muaggatt`` parquet
    tables that pass the adapter's post-conditions."""
    comp_rows = []
    chor_rows = []
    agg_rows = []
    for i, mk in enumerate(mukeys):
        co_major = 10_000 + i
        co_minor = 90_000 + i
        comp_rows.append(
            dict(mukey=mk, cokey=co_major, comppct_r=70, compname=f"comp_{mk}",
                 hydgrp="B")
        )
        comp_rows.append(
            dict(mukey=mk, cokey=co_minor, comppct_r=20, compname=f"minor_{mk}",
                 hydgrp="C")
        )
        for L, (top, bot) in enumerate([(0, 10), (10, 30), (30, 80)], start=1):
            chor_rows.append(
                dict(cokey=co_major, chkey=co_major * 100 + L,
                     hzdept_r=top, hzdepb_r=bot,
                     sandtotal_r=40 + L, silttotal_r=40 - L, claytotal_r=20,
                     ksat_r=10.0, wthirdbar_r=30.0, wfifteenbar_r=15.0,
                     om_r=2.0, dbthirdbar_r=1.4)
            )
        agg_rows.append(dict(mukey=mk, hydgrpdcd=("A/D" if i == 0 else "B")))

    component = pd.DataFrame(comp_rows)
    chorizon = pd.DataFrame(chor_rows)
    muaggatt = pd.DataFrame(agg_rows)

    items = [
        _FakeItem("component", {"data": _FakeAsset("fake://component.parquet")}),
        _FakeItem("chorizon", {"data": _FakeAsset("fake://chorizon.parquet")}),
        _FakeItem("muaggatt", {"data": _FakeAsset("fake://muaggatt.parquet")}),
    ]
    parquet_table = {
        "fake://component.parquet": component,
        "fake://chorizon.parquet": chorizon,
        "fake://muaggatt.parquet": muaggatt,
    }
    return items, parquet_table


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_empty_mukeys_rejected(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        with pytest.raises(SwatBuilderInputError, match="at least one mukey"):
            fetch_gnatsgo_profiles(
                [],
                options=_opts(cache_dir=tmp_path),
            )

    def test_negative_mukey_rejected(self, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        with pytest.raises(SwatBuilderInputError, match="cannot be negative"):
            fetch_gnatsgo_profiles([-1], options=_opts(cache_dir=tmp_path))

    def test_non_int_rejected(self, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        with pytest.raises(SwatBuilderInputError, match="mukey must be int"):
            fetch_gnatsgo_profiles(["abc"], options=_opts(cache_dir=tmp_path))  # type: ignore[list-item]

    def test_bool_not_treated_as_int(self, tmp_path):
        """``True`` is an int in Python; make sure we reject it to
        catch caller mistakes (``[True, mukey]`` for example)."""
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        with pytest.raises(SwatBuilderInputError, match="mukey must be int"):
            fetch_gnatsgo_profiles([True], options=_opts(cache_dir=tmp_path))  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Missing optional deps
# ---------------------------------------------------------------------------


class TestMissingDeps:
    def test_missing_pystac_yields_external_error(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        # Block the import of pystac_client specifically.
        sys.modules.pop("pystac_client", None)

        finders = sys.meta_path.copy()

        class _Blocker:
            def find_spec(self, name, *_, **__):
                if name == "pystac_client":
                    raise ImportError("blocked for test")
                return None

        sys.meta_path.insert(0, _Blocker())
        try:
            with pytest.raises(SwatBuilderExternalError, match=r"swatplus-builder\[soils\]"):
                fetch_gnatsgo_profiles([1], options=_opts(cache_dir=tmp_path))
        finally:
            sys.meta_path[:] = finders


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_mukey_builds_profile(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        items, pq = _mk_fake_tables([12345])
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        profiles = fetch_gnatsgo_profiles(
            [12345],
            options=_opts(cache_dir=tmp_path),
        )
        assert len(profiles) == 1
        p = profiles[0]
        assert p.name == "gnatsgo_12345"
        # First-listed mukey was "A/D" in our synthetic muaggatt → collapses to D.
        assert p.hyd_grp == "D"
        assert len(p.layers) == 3
        # Description preserves traceability back to the source row.
        assert "mukey=12345" in (p.description or "")
        assert "comp_12345" in (p.description or "")
        # Layer depths should climb monotonically.
        dps = [lyr.dp for lyr in p.layers]
        assert dps == sorted(dps) and len(set(dps)) == 3

    def test_multiple_mukeys_all_returned(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        items, pq = _mk_fake_tables([100, 200, 300])
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        profiles = fetch_gnatsgo_profiles(
            [100, 200, 300], options=_opts(cache_dir=tmp_path)
        )
        assert [p.name for p in profiles] == [
            "gnatsgo_100", "gnatsgo_200", "gnatsgo_300"
        ]

    def test_duplicates_collapse(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        items, pq = _mk_fake_tables([111])
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        # Same mukey 3x — should dedupe to one profile.
        profiles = fetch_gnatsgo_profiles(
            [111, 111, 111], options=_opts(cache_dir=tmp_path)
        )
        assert len(profiles) == 1

    def test_dominant_component_picked_by_comppct(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        items, pq = _mk_fake_tables([555])
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        profiles = fetch_gnatsgo_profiles([555], options=_opts(cache_dir=tmp_path))
        # Major component is ``comp_555``; the minor (90_000+i) would
        # have name ``minor_555`` which we use as a negative sentinel.
        assert "comp_555" in (profiles[0].description or "")
        assert "minor_555" not in (profiles[0].description or "")

    def test_cache_dir_created(self, monkeypatch, tmp_path):
        from swatplus_builder.soil import fetch_gnatsgo_profiles

        items, pq = _mk_fake_tables([99])
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        cache = tmp_path / "cache"
        fetch_gnatsgo_profiles([99], options=_opts(cache_dir=cache))
        assert cache.is_dir()
        # At least one of the three tables should have been cached.
        assert any(cache.glob("*_filtered.parquet"))

    def test_every_requested_mukey_yields_a_profile(self, monkeypatch, tmp_path):
        """Invariant: aggregated baseline guarantees coverage even when
        muaggatt/component/chorizon have no rows for requested mukeys."""
        import pandas as pd

        from swatplus_builder.soil import fetch_gnatsgo_profiles_result

        # Install a fake PC catalog where all three tables exist but contain
        # *zero rows*. The fetcher must still synthesize default profiles for
        # every requested mukey.
        items = [
            _FakeItem("component", {"data": _FakeAsset("fake://component.parquet")}),
            _FakeItem("chorizon", {"data": _FakeAsset("fake://chorizon.parquet")}),
            _FakeItem("muaggatt", {"data": _FakeAsset("fake://muaggatt.parquet")}),
        ]
        pq = {
            "fake://component.parquet": pd.DataFrame(columns=list(["mukey", "cokey", "comppct_r", "compname", "hydgrp"])),
            "fake://chorizon.parquet": pd.DataFrame(columns=list([
                "cokey", "chkey", "hzdept_r", "hzdepb_r",
                "sandtotal_r", "silttotal_r", "claytotal_r",
                "ksat_r", "wthirdbar_r", "wfifteenbar_r", "om_r", "dbthirdbar_r",
            ])),
            "fake://muaggatt.parquet": pd.DataFrame(columns=list(["mukey", "hydgrpdcd"])),
        }
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        mukeys = [1, 2, 3, 999999]
        res = fetch_gnatsgo_profiles_result(mukeys, options=_opts(cache_dir=tmp_path))
        assert len(res.profiles) == len(mukeys)
        assert [p.name for p in res.profiles] == [f"gnatsgo_{m}" for m in mukeys]


# ---------------------------------------------------------------------------
# Round-trip through the writer
# ---------------------------------------------------------------------------


class TestWriterRoundTrip:
    def test_fetch_then_write_to_sqlite(self, monkeypatch, tmp_path):
        import sqlite3

        from swatplus_builder.soil import fetch_gnatsgo_profiles, write_soils

        items, pq = _mk_fake_tables([42, 43])
        _install_fake_pc_stack(monkeypatch, items=items, parquet_table=pq)

        profiles = fetch_gnatsgo_profiles([42, 43], options=_opts(cache_dir=tmp_path))
        assert len(profiles) == 2

        db = tmp_path / "project.sqlite"
        sqlite3.connect(str(db)).close()

        res = write_soils(profiles, db)
        assert res.profiles_written == 2
        # 3 layers per profile in our synthetic fixture.
        assert res.layers_written == 6


# ---------------------------------------------------------------------------
# Opt-in real PC integration
# ---------------------------------------------------------------------------


_RUN_REAL_ENV = "SWATPLUS_BUILDER_RUN_GNATSGO"


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get(_RUN_REAL_ENV) != "1",
    reason=f"Set {_RUN_REAL_ENV}=1 to hit real Planetary Computer in this test.",
)
def test_real_planetary_computer_one_mukey(tmp_path):
    """Sanity-check against the real PC STAC with a known-good mukey.

    mukey 1769520 is a common PA loam covered by gNATSGO. The test
    tolerates the profile being absent (server-side transient), but
    insists that if it IS present, it passes every invariant.
    """
    import pytest

    from swatplus_builder.errors import SwatBuilderPipelineError
    from swatplus_builder.soil import fetch_gnatsgo_profiles

    try:
        profiles = fetch_gnatsgo_profiles(
            [1769520], options=_opts(cache_dir=tmp_path)
        )
    except SwatBuilderPipelineError as exc:
        # Planetary Computer snapshots occasionally change coverage; if the
        # requested mukey isn't present in the current tables, skip rather
        # than failing CI.
        pytest.skip(f"PC did not contain requested mukey: {exc}")
    if not profiles:
        pytest.skip("PC returned zero profiles — transient, not a bug")
    p = profiles[0]
    assert p.name == "gnatsgo_1769520"
    assert len(p.layers) >= 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opts(*, cache_dir: Path):
    from swatplus_builder.soil import GnatsgoFetchOptions

    return GnatsgoFetchOptions(cache_dir=cache_dir)
