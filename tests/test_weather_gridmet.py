"""Tests for :mod:`swatplus_builder.weather.gridmet`.

Two tiers:

* **Unit** (always run): monkey-patch ``pygridmet`` with a fake client
  that returns hand-crafted pandas DataFrames. Verifies the adapter's
  unit conversions, variable routing, error translation, and
  :class:`WeatherBundle` assembly — without touching the network.
* **Integration** (``@pytest.mark.slow``, opt-in via
  ``SWATPLUS_BUILDER_RUN_GRIDMET=1``): calls the real THREDDS server
  and asserts only that the result passes our own post-condition
  checks. Skipped by default to keep CI fast + deterministic.
"""

from __future__ import annotations

import importlib
import os
import sys
import types

import pandas as pd
import pytest

from swatplus_builder.errors import (
    SwatBuilderExternalError,
    SwatBuilderInputError,
    SwatBuilderPipelineError,
)
from swatplus_builder.types import WeatherStation

# ---------------------------------------------------------------------------
# Fake pygridmet
# ---------------------------------------------------------------------------


class _FakeClient:
    """Drop-in for the real ``pygridmet`` module.

    Exposes ``get_bycoords(coords, dates, variables, to_xarray=False)``
    and records every call so tests can assert on arguments.
    """

    def __init__(self, df_factory):
        self._df_factory = df_factory
        self.calls: list[dict] = []

    def get_bycoords(self, *, coords, dates, variables, to_xarray=False):
        self.calls.append(
            {
                "coords": coords,
                "dates": dates,
                "variables": list(variables),
                "to_xarray": to_xarray,
            }
        )
        return self._df_factory(coords=coords, dates=dates, variables=variables)


def _install_fake_pygridmet(monkeypatch, fake):
    """Register ``fake`` as the ``pygridmet`` module for the import in the
    adapter. Uses ``sys.modules`` directly so a missing real install
    doesn't affect the tests.
    """
    monkeypatch.setitem(sys.modules, "pygridmet", fake)


def _mk_df(*, coords, dates, variables):
    """Build a deterministic DataFrame matching pygridmet's column-naming
    convention (``"<var> (<unit>)"``)."""
    start, end = (pd.Timestamp(dates[0]), pd.Timestamp(dates[1]))
    idx = pd.date_range(start, end, freq="D")
    n = len(idx)
    data: dict[str, list[float]] = {}
    # Hand-pick values so the test can assert exact post-conversion numbers.
    unit_map = {
        "pr": "mm",
        "tmmx": "K",
        "tmmn": "K",
        "rmin": "%",
        "rmax": "%",
        "vs": "m/s",
        "srad": "W/m2",
    }
    for v in variables:
        col = f"{v} ({unit_map[v]})"
        if v == "pr":
            data[col] = [1.5] * n  # 1.5 mm/day
        elif v == "tmmx":
            data[col] = [295.15] * n  # 22 °C
        elif v == "tmmn":
            data[col] = [285.15] * n  # 12 °C
        elif v == "rmin":
            data[col] = [40.0] * n  # 40 %
        elif v == "rmax":
            data[col] = [80.0] * n  # 80 %  → mean = 60 % = 0.600
        elif v == "vs":
            data[col] = [3.2] * n  # 3.2 m/s
        elif v == "srad":
            data[col] = [250.0] * n  # 250 W/m² → 21.60 MJ/m²/day
    df = pd.DataFrame(data, index=idx)
    df.index.name = "time"
    return df


# ---------------------------------------------------------------------------
# Module import contract
# ---------------------------------------------------------------------------


class TestImportContract:
    def test_module_imports_without_pygridmet(self):
        # Verifies the PYGRIDMET import is deferred — removing it from
        # ``sys.modules`` mid-session should not break re-importing this
        # module.
        sys.modules.pop("pygridmet", None)
        importlib.reload(importlib.import_module("swatplus_builder.weather.gridmet"))

    def test_missing_pygridmet_yields_clear_external_error(self, monkeypatch):
        from swatplus_builder.weather import fetch_gridmet

        # Simulate "not installed" by replacing with a sentinel that raises
        # ImportError on attribute access — matches real missing-install.
        class _Raiser:
            def __getattr__(self, name):
                raise ImportError(f"no module named pygridmet (attr={name!r})")

        monkeypatch.setitem(
            sys.modules, "pygridmet", types.ModuleType("pygridmet_missing")
        )
        # Actually simpler: just delete sys.modules['pygridmet'] and make
        # the import fail by shadowing its finder.
        sys.modules.pop("pygridmet", None)

        finders = sys.meta_path.copy()

        class _Blocker:
            def find_spec(self, name, *_, **__):
                if name == "pygridmet":
                    raise ImportError("blocked for test")
                return None

        sys.meta_path.insert(0, _Blocker())
        try:
            with pytest.raises(SwatBuilderExternalError, match="pygridmet is not installed"):
                fetch_gridmet(
                    stations=[(40.0, -80.0, 200.0)],
                    start="2015-01-01",
                    end="2015-01-05",
                )
        finally:
            sys.meta_path[:] = finders


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_rejects_empty_stations(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        with pytest.raises(SwatBuilderInputError, match="at least one station"):
            fetch_gridmet(stations=[], start="2015-01-01", end="2015-01-05", cache_dir=tmp_path)

    def test_rejects_end_before_start(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        with pytest.raises(SwatBuilderInputError, match="precedes start"):
            fetch_gridmet(
                stations=[(40.0, -80.0, 200.0)],
                start="2015-02-01",
                end="2015-01-01",
                cache_dir=tmp_path,
            )

    def test_rejects_pre_1979_start(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        with pytest.raises(SwatBuilderInputError, match="GridMET starts 1979-01-01"):
            fetch_gridmet(
                stations=[(40.0, -80.0, 200.0)],
                start="1970-01-01",
                end="1970-01-05",
                cache_dir=tmp_path,
            )

    def test_rejects_unknown_variable(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        with pytest.raises(SwatBuilderInputError, match="unknown weather variable"):
            fetch_gridmet(
                stations=[(40.0, -80.0, 200.0)],
                start="2015-01-01",
                end="2015-01-05",
                variables=["pcp", "foo"],  # type: ignore[list-item]
                cache_dir=tmp_path,
            )

    def test_rejects_bad_date_string(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        with pytest.raises(SwatBuilderInputError, match="GridMET date not ISO"):
            fetch_gridmet(
                stations=[(40.0, -80.0, 200.0)],
                start="Jan 1 2015",
                end="2015-01-05",
                cache_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# Happy path — unit conversions
# ---------------------------------------------------------------------------


class TestHappyPath:
    def _fetch(self, monkeypatch, tmp_path, **kwargs):
        from swatplus_builder.weather import fetch_gridmet

        fake = _FakeClient(_mk_df)
        _install_fake_pygridmet(monkeypatch, fake)
        bundle = fetch_gridmet(
            start="2015-01-01",
            end="2015-01-05",
            cache_dir=tmp_path,
            **kwargs,
        )
        return bundle, fake

    def test_full_variable_set(self, monkeypatch, tmp_path):
        bundle, fake = self._fetch(
            monkeypatch,
            tmp_path,
            stations=[(41.1, -77.5, 300.0)],
        )
        assert bundle.n_days == 5
        assert len(bundle.stations) == 1
        s = bundle.stations[0]
        assert s.station.name == "s41100n77500w"
        assert s.station.elev == 300.0

        # Post-conversion values.
        assert s.pcp == [1.5, 1.5, 1.5, 1.5, 1.5]
        assert s.tmax == [22.0, 22.0, 22.0, 22.0, 22.0]
        assert s.tmin == [12.0, 12.0, 12.0, 12.0, 12.0]
        assert s.hmd == [0.600, 0.600, 0.600, 0.600, 0.600]
        assert s.wnd == [3.2, 3.2, 3.2, 3.2, 3.2]
        assert s.slr == [21.60, 21.60, 21.60, 21.60, 21.60]

        # One call per station, forwarding the right args.
        (call,) = fake.calls
        assert call["coords"] == (-77.5, 41.1)
        assert call["dates"] == ("2015-01-01", "2015-01-05")
        assert set(call["variables"]) == {"pr", "tmmx", "tmmn", "rmin", "rmax", "vs", "srad"}
        assert call["to_xarray"] is False

    def test_variable_subset_only_fetches_required(self, monkeypatch, tmp_path):
        bundle, fake = self._fetch(
            monkeypatch,
            tmp_path,
            stations=[(41.1, -77.5, 300.0)],
            variables=["pcp", "tmp"],
        )
        (call,) = fake.calls
        assert set(call["variables"]) == {"pr", "tmmx", "tmmn"}
        assert "srad" not in call["variables"]

        s = bundle.stations[0]
        assert s.pcp is not None
        assert s.tmax is not None and s.tmin is not None
        assert s.hmd is None and s.wnd is None and s.slr is None

    def test_multi_station_fans_out_to_per_station_calls(
        self, monkeypatch, tmp_path
    ):
        bundle, fake = self._fetch(
            monkeypatch,
            tmp_path,
            stations=[(41.1, -77.5, 300.0), (41.2, -77.6, 280.0)],
        )
        assert len(fake.calls) == 2
        assert len(bundle.stations) == 2
        # Station naming from (lat, lon) convention.
        assert {s.station.name for s in bundle.stations} == {
            "s41100n77500w",
            "s41200n77600w",
        }

    def test_accepts_weather_station_instances(self, monkeypatch, tmp_path):
        bundle, _ = self._fetch(
            monkeypatch,
            tmp_path,
            stations=[
                WeatherStation(
                    name="custom_name",
                    lat=41.1,
                    lon=-77.5,
                    elev=300.0,
                )
            ],
        )
        assert bundle.stations[0].station.name == "custom_name"

    def test_tmax_always_gt_tmin_even_if_server_ships_inverted(
        self, monkeypatch, tmp_path
    ):
        """If GridMET ever returns tmmn >= tmmx (rare, but real bug in
        older product versions), the adapter must still produce a
        strictly-increasing pair so the engine's validator passes."""
        from swatplus_builder.weather import fetch_gridmet

        def bad(*, coords, dates, variables):
            idx = pd.date_range(dates[0], dates[1], freq="D")
            return pd.DataFrame(
                {
                    "pr (mm)": [0.0] * len(idx),
                    "tmmx (K)": [280.0] * len(idx),  # 6.85 °C
                    "tmmn (K)": [285.0] * len(idx),  # 11.85 °C → INVERTED
                    "rmin (%)": [50.0] * len(idx),
                    "rmax (%)": [60.0] * len(idx),
                    "vs (m/s)": [2.0] * len(idx),
                    "srad (W/m2)": [100.0] * len(idx),
                },
                index=idx,
            )

        _install_fake_pygridmet(monkeypatch, _FakeClient(bad))
        bundle = fetch_gridmet(
            stations=[(40.0, -80.0, 200.0)],
            start="2015-01-01",
            end="2015-01-03",
            cache_dir=tmp_path,
        )
        s = bundle.stations[0]
        assert s.tmax is not None and s.tmin is not None
        for tx, tn in zip(s.tmax, s.tmin):
            assert tx > tn

    def test_round_trip_through_writer(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import write_observed

        bundle, _ = self._fetch(
            monkeypatch,
            tmp_path,
            stations=[(41.1, -77.5, 300.0)],
        )
        out_dir = tmp_path / "txtinout"
        res = write_observed(bundle, out_dir)
        assert res.n_stations == 1
        assert (out_dir / "s41100n77500w.pcp").is_file()
        assert (out_dir / "pcp.cli").is_file()


# ---------------------------------------------------------------------------
# Error translation from the upstream client
# ---------------------------------------------------------------------------


class TestExternalErrors:
    def test_fetch_forwards_gridmet_reliability_options(
        self, monkeypatch, tmp_path
    ):
        from swatplus_builder.weather import fetch_gridmet

        captured = {}

        class _OptionAwareClient:
            def get_bycoords(self, **kwargs):
                captured.update(kwargs)
                return _mk_df(
                    coords=kwargs["coords"],
                    dates=kwargs["dates"],
                    variables=kwargs["variables"],
                )

        _install_fake_pygridmet(monkeypatch, _OptionAwareClient())

        fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-05",
            variables=["pcp"],
            cache_dir=tmp_path,
        )

        assert captured["conn_timeout"] >= 1000
        assert captured["validate_filesize"] is False

    def test_transient_pygridmet_exception_is_retried(
        self, monkeypatch, tmp_path
    ):
        from swatplus_builder.weather import fetch_gridmet

        attempts = {"n": 0}

        def flaky(**k):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TimeoutError("Timeout on reading data from socket")
            return _mk_df(coords=k["coords"], dates=k["dates"], variables=k["variables"])

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = flaky  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)
        monkeypatch.setattr("swatplus_builder.weather.gridmet.time.sleep", lambda _s: None)

        bundle = fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-05",
            variables=["pcp"],
            cache_dir=tmp_path,
        )

        assert attempts["n"] == 2
        assert bundle.stations[0].pcp == [1.5] * 5

    def test_pygridmet_exception_translates_to_external_error(
        self, monkeypatch, tmp_path
    ):
        from swatplus_builder.weather import fetch_gridmet

        attempts = {"n": 0}

        def boom(**_kwargs):
            attempts["n"] += 1
            raise ConnectionError("THREDDS 503 Service Unavailable")

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = boom  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)
        monkeypatch.setattr("swatplus_builder.weather.gridmet.time.sleep", lambda _s: None)

        with pytest.raises(SwatBuilderExternalError, match="THREDDS 503") as excinfo:
            fetch_gridmet(
                stations=[(41.1, -77.5, 300.0)],
                start="2015-01-01",
                end="2015-01-05",
                cache_dir=tmp_path,
            )
        assert excinfo.value.context.get("station") == "s41100n77500w"
        assert excinfo.value.context.get("attempts") == 3
        assert attempts["n"] == 3

    def test_row_count_mismatch_triggers_pipeline_error(
        self, monkeypatch, tmp_path
    ):
        from swatplus_builder.weather import fetch_gridmet

        def short(**k):
            dates = k["dates"]
            # Return 2 rows for a 10-day window — 8 trailing days missing,
            # which is above the 7-day repair cap and must raise.
            idx = pd.date_range(dates[0], periods=2, freq="D")
            return pd.DataFrame(
                {"pr (mm)": [1.0, 1.0]}, index=idx
            )

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = short  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)

        with pytest.raises(
            SwatBuilderPipelineError, match=r"returned 2 rows .* expected 10"
        ):
            fetch_gridmet(
                stations=[(41.1, -77.5, 300.0)],
                start="2015-01-01",
                end="2015-01-10",
                variables=["pcp"],
                cache_dir=tmp_path,
            )

    def test_single_missing_boundary_day_is_repaired(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        def missing_start(**k):
            dates = k["dates"]
            idx = pd.date_range(dates[0], dates[1], freq="D")[1:]
            return pd.DataFrame(
                {"pr (mm)": [2.0] * len(idx)}, index=idx
            )

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = missing_start  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)

        bundle = fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-05",
            variables=["pcp"],
            cache_dir=tmp_path,
        )

        assert bundle.n_days == 5
        assert bundle.stations[0].pcp == [2.0] * 5

    def test_single_missing_internal_day_is_repaired(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        def missing_internal(**k):
            idx = pd.DatetimeIndex(
                [
                    "2015-01-01",
                    "2015-01-02",
                    "2015-01-04",
                    "2015-01-05",
                ]
            )
            return pd.DataFrame(
                {"pr (mm)": [1.0, 2.0, 4.0, 5.0]}, index=idx
            )

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = missing_internal  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)

        bundle = fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-05",
            variables=["pcp"],
            cache_dir=tmp_path,
        )

        assert bundle.n_days == 5
        assert bundle.stations[0].pcp == [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_multiple_isolated_missing_days_are_repaired(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        def missing_isolated(**k):
            idx = pd.DatetimeIndex(
                [
                    "2015-01-01",
                    "2015-01-02",
                    "2015-01-04",
                    "2015-01-05",
                    "2015-01-07",
                ]
            )
            return pd.DataFrame(
                {"pr (mm)": [1.0, 2.0, 4.0, 5.0, 7.0]}, index=idx
            )

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = missing_isolated  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)

        bundle = fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-07",
            variables=["pcp"],
            cache_dir=tmp_path,
        )

        assert bundle.n_days == 7
        assert bundle.stations[0].pcp == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]

    def test_consecutive_missing_days_still_raise(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        def missing_consecutive(**k):
            idx = pd.DatetimeIndex(["2015-01-01", "2015-01-04", "2015-01-05"])
            return pd.DataFrame({"pr (mm)": [1.0, 4.0, 5.0]}, index=idx)

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = missing_consecutive  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)

        with pytest.raises(SwatBuilderPipelineError, match=r"returned 3 rows .* expected 5"):
            fetch_gridmet(
                stations=[(41.1, -77.5, 300.0)],
                start="2015-01-01",
                end="2015-01-05",
                variables=["pcp"],
                cache_dir=tmp_path,
            )

    def test_missing_column_triggers_pipeline_error(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        def no_pr(**k):
            dates = k["dates"]
            idx = pd.date_range(dates[0], dates[1], freq="D")
            # Ship something, but omit "pr".
            return pd.DataFrame(
                {"tmmx (K)": [295.15] * len(idx)}, index=idx
            )

        fake = _FakeClient(lambda **k: None)
        fake.get_bycoords = no_pr  # type: ignore[assignment]
        _install_fake_pygridmet(monkeypatch, fake)

        with pytest.raises(SwatBuilderPipelineError, match="missing expected GridMET variable 'pr'"):
            fetch_gridmet(
                stations=[(41.1, -77.5, 300.0)],
                start="2015-01-01",
                end="2015-01-05",
                variables=["pcp"],
                cache_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# _repair_bounded_day_gaps — unit tests
# ---------------------------------------------------------------------------


class TestRepairBoundedDayGaps:
    """Direct unit tests for the gap-repair helper."""

    def _make_df(self, start: str, n: int) -> pd.DataFrame:
        import pandas as pd
        idx = pd.date_range(start, periods=n, freq="D")
        return pd.DataFrame({"pr (mm)": [1.0] * n}, index=idx)

    def _station(self) -> WeatherStation:
        return WeatherStation(name="test", lat=40.0, lon=-80.0, elev=200.0)

    def test_no_gap_returns_unchanged(self):
        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        df = self._make_df("2015-01-01", 5)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-05", n_days=5,
        )
        assert len(result) == 5

    def test_trailing_1_day_gap_is_repaired(self):
        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        # Server returned 4 rows for a 5-day window (trailing day clipped)
        df = self._make_df("2015-01-01", 4)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-05", n_days=5,
        )
        assert len(result) == 5

    def test_trailing_5_day_gap_is_repaired(self):
        """The failing case: server returns 8395 rows for 8400-day window."""
        import pandas as pd

        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        idx = pd.date_range("2000-01-01", periods=8395, freq="D")
        df = pd.DataFrame({"pr (mm)": [2.5] * 8395}, index=idx)
        expected_end = (pd.Timestamp("2000-01-01") + pd.Timedelta(days=8399)).strftime("%Y-%m-%d")
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2000-01-01", end=expected_end, n_days=8400,
        )
        assert len(result) == 8400
        # Forward-filled values match the last available row
        assert result.iloc[-1]["pr (mm)"] == pytest.approx(2.5)
        assert result.iloc[-5]["pr (mm)"] == pytest.approx(2.5)

    def test_trailing_7_day_gap_is_repaired(self):
        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        df = self._make_df("2015-01-01", 3)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-10", n_days=10,
        )
        assert len(result) == 10

    def test_trailing_8_day_gap_is_not_repaired(self):
        """Above the 7-day cap the repair is skipped (validation will raise)."""
        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        df = self._make_df("2015-01-01", 2)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-10", n_days=10,
        )
        assert len(result) == 2  # unchanged

    def test_leading_gap_is_repaired(self):
        import pandas as pd

        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        # Drop the first day
        idx = pd.date_range("2015-01-02", periods=4, freq="D")
        df = pd.DataFrame({"pr (mm)": [1.0] * 4}, index=idx)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-05", n_days=5,
        )
        assert len(result) == 5
        assert pd.Timestamp("2015-01-01") in pd.DatetimeIndex(result.index)

    def test_interior_gap_is_averaged(self):
        import pandas as pd

        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        # 2015-01-01=2.0, 2015-01-03=4.0; 2015-01-02 missing
        idx = pd.DatetimeIndex([pd.Timestamp("2015-01-01"), pd.Timestamp("2015-01-03")])
        df = pd.DataFrame({"pr (mm)": [2.0, 4.0]}, index=idx)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-03", n_days=3,
        )
        assert len(result) == 3
        assert result.loc[pd.Timestamp("2015-01-02"), "pr (mm)"] == pytest.approx(3.0)

    def test_repair_preserves_sort_order(self):
        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        df = self._make_df("2015-01-01", 4)
        result = _repair_bounded_day_gaps(
            df, station=self._station(),
            start="2015-01-01", end="2015-01-05", n_days=5,
        )
        assert result.index.is_monotonic_increasing

    def test_trailing_gap_logs_warning(self, caplog):
        """Forward-fill must emit a named warning so the user knows data is synthetic."""
        import logging

        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        df = self._make_df("2015-01-01", 4)
        with caplog.at_level(logging.WARNING, logger="swatplus_builder.weather.gridmet"):
            _repair_bounded_day_gaps(
                df, station=self._station(),
                start="2015-01-01", end="2015-01-05", n_days=5,
            )
        assert any("synthetic" in r.message for r in caplog.records), (
            "Expected a warning mentioning synthetic data; got: "
            + str([r.message for r in caplog.records])
        )
        assert any("test" in r.message for r in caplog.records), (
            "Warning should name the station"
        )

    def test_no_gap_does_not_log_warning(self, caplog):
        """No-op repair must not emit spurious warnings."""
        import logging

        from swatplus_builder.weather.gridmet import _repair_bounded_day_gaps
        df = self._make_df("2015-01-01", 5)
        with caplog.at_level(logging.WARNING, logger="swatplus_builder.weather.gridmet"):
            _repair_bounded_day_gaps(
                df, station=self._station(),
                start="2015-01-01", end="2015-01-05", n_days=5,
            )
        assert caplog.records == []


# ---------------------------------------------------------------------------
# _warn_if_end_near_realtime — unit tests
# ---------------------------------------------------------------------------


class TestWarnIfEndNearRealtime:
    def test_warns_for_recent_end_date(self, caplog):
        import datetime
        import logging

        from swatplus_builder.weather.gridmet import _warn_if_end_near_realtime
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        with caplog.at_level(logging.WARNING, logger="swatplus_builder.weather.gridmet"):
            _warn_if_end_near_realtime(
                datetime.date.fromisoformat(yesterday), yesterday
            )
        assert any("lag" in r.message.lower() or "coverage" in r.message.lower()
                   for r in caplog.records)

    def test_no_warning_for_safe_historical_date(self, caplog):
        import datetime
        import logging

        from swatplus_builder.weather.gridmet import _warn_if_end_near_realtime
        safe = "2020-01-01"
        with caplog.at_level(logging.WARNING, logger="swatplus_builder.weather.gridmet"):
            _warn_if_end_near_realtime(datetime.date.fromisoformat(safe), safe)
        assert caplog.records == []

    def test_fetch_gridmet_warns_for_recent_end(self, monkeypatch, tmp_path, caplog):
        """End-to-end: fetch_gridmet emits the warning before the network call."""
        import datetime
        import logging

        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        # Use today - 3 days which is within the 7-day lag window
        recent_end = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        recent_start = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        with caplog.at_level(logging.WARNING, logger="swatplus_builder.weather.gridmet"):
            fetch_gridmet(
                stations=[(41.1, -77.5, 300.0)],
                start=recent_start,
                end=recent_end,
                variables=["pcp"],
                cache_dir=tmp_path,
            )
        assert any("lag" in r.message.lower() or "coverage" in r.message.lower()
                   for r in caplog.records)


# ---------------------------------------------------------------------------
# Cache dir resolution
# ---------------------------------------------------------------------------


class TestCacheDir:
    def test_explicit_cache_dir_is_created(self, monkeypatch, tmp_path):
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        cache = tmp_path / "cache" / "gridmet"
        fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-03",
            cache_dir=cache,
        )
        assert cache.is_dir()

    def test_default_cache_dir_derives_from_settings(self, monkeypatch, tmp_path):
        from swatplus_builder.config import DEFAULT_SETTINGS, Settings
        from swatplus_builder.weather import fetch_gridmet

        _install_fake_pygridmet(monkeypatch, _FakeClient(_mk_df))
        settings = Settings(
            **{
                **DEFAULT_SETTINGS.model_dump(),
                "reference_db_dir": tmp_path / "ref",
            }
        )
        fetch_gridmet(
            stations=[(41.1, -77.5, 300.0)],
            start="2015-01-01",
            end="2015-01-03",
            settings=settings,
        )
        assert (tmp_path / "gridmet_cache").is_dir()


# ---------------------------------------------------------------------------
# Opt-in integration test — hits the real THREDDS server
# ---------------------------------------------------------------------------


_RUN_REAL_ENV = "SWATPLUS_BUILDER_RUN_GRIDMET"


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get(_RUN_REAL_ENV) != "1",
    reason=f"Set {_RUN_REAL_ENV}=1 to fetch real GridMET data in this test.",
)
def test_real_gridmet_tiny_window(tmp_path):
    """Hit the real THREDDS server for a 3-day window at a single point
    and confirm the result passes our own post-conditions + the writer.

    Runs only when explicitly enabled — default CI stays hermetic.
    """
    from swatplus_builder.weather import fetch_gridmet, write_observed

    bundle = fetch_gridmet(
        stations=[(41.5, -77.5, 300.0)],  # central Pennsylvania
        start="2015-06-01",
        end="2015-06-03",
        cache_dir=tmp_path / "cache",
    )
    assert len(bundle.stations) == 1
    s = bundle.stations[0]
    assert s.n_days == 3
    # Plausibility checks — not hard values, because climate.
    assert s.pcp is not None and all(v >= 0 for v in s.pcp)
    assert s.tmax is not None and s.tmin is not None
    for tx, tn in zip(s.tmax, s.tmin):
        assert -50 < tn < tx < 60

    out_dir = tmp_path / "out"
    write_observed(bundle, out_dir)
    assert (out_dir / "pcp.cli").is_file()
    assert (out_dir / f"{s.station.name}.pcp").is_file()
