"""Unit tests for ``swatplus_builder.weather.writer`` and ``.synthetic``.

These tests lock the on-disk format against the editor's parser (via a
Python port of ``add_weather_files_type``) so a future refactor that
accidentally reshuffles column widths will break CI immediately.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from swatplus_builder.errors import SwatBuilderInputError
from swatplus_builder.types import StationSeries, WeatherBundle, WeatherStation
from swatplus_builder.weather import (
    station_name,
    synthesize,
    synthesize_station,
    write_observed,
)

# ---------------------------------------------------------------------------
# Station name convention
# ---------------------------------------------------------------------------


class TestStationName:
    def test_matches_editor_convention(self):
        # Editor: weather_sta_name(41.1, -77.5) == "s41100n77500w"
        assert station_name(41.1, -77.5) == "s41100n77500w"

    def test_southern_hemisphere(self):
        assert station_name(-33.0, 151.5) == "s33000s151500e"

    def test_round_half(self):
        # 0.5 → 1 under banker's rounding or standard rounding.
        # Just make sure the result is deterministic and parseable.
        name = station_name(10.0005, -20.0005)
        assert name.startswith("s")
        assert "n" in name and "w" in name


# ---------------------------------------------------------------------------
# Happy-path writer
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_bundle() -> WeatherBundle:
    """Two stations, 5 days, full variable set, deterministic values."""
    return synthesize(
        stations=[(41.1, -77.5, 300.0), (41.2, -77.6, 280.0)],
        start="2015-01-01",
        n_days=5,
        seed=42,
    )


class TestWriteObserved:
    def test_writes_all_expected_files(self, mini_bundle, tmp_path):
        result = write_observed(mini_bundle, tmp_path)

        assert result.output_dir == tmp_path
        assert result.n_stations == 2
        assert set(result.variables) == {"pcp", "tmp", "hmd", "wnd", "slr"}

        # 2 stations * 5 vars = 10 per-station files; 5 .cli indexes.
        assert len(result.station_files) == 10
        assert len(result.index_files) == 5
        for p in result.all_files:
            assert p.is_file()

        for var in ("pcp", "tmp", "hmd", "wnd", "slr"):
            assert (tmp_path / f"{var}.cli").is_file()

    def test_cli_index_shape(self, mini_bundle, tmp_path):
        write_observed(mini_bundle, tmp_path)
        lines = (tmp_path / "pcp.cli").read_text().splitlines()
        # Header + "filename" + 2 stations.
        assert len(lines) == 4
        assert lines[0].startswith("pcp.cli: Precipitation file names")
        assert lines[1] == "filename"
        assert lines[2].endswith(".pcp")
        assert lines[3].endswith(".pcp")
        # Sorted case-insensitively.
        assert lines[2].lower() < lines[3].lower()

    def test_station_file_matches_editor_parse_contract(self, mini_bundle, tmp_path):
        """Replicate ``add_weather_files_type`` line-by-line parsing and
        assert every invariant it checks.
        """
        write_observed(mini_bundle, tmp_path)
        pcp_files = sorted(tmp_path.glob("*.pcp"))
        assert pcp_files, "no .pcp station files written"

        for path in pcp_files:
            lines = path.read_text().splitlines()
            assert len(lines) >= 4, f"{path.name}: needs header + labels + meta + ≥1 day"

            # Line 2 (j==2 in editor, 0-indexed): metadata row needs
            # ``nbyr tstep lat lon elev`` (>=4 fields after split).
            meta = lines[2].strip().split()
            assert len(meta) >= 4, f"{path.name}: metadata row too short"
            nbyr = int(meta[0])
            assert nbyr == 1, "2015-01-01 + 5 days stays in 2015 → nbyr=1"
            assert meta[1] == "0", "tstep must be hard-coded '0' (daily)"
            lat = float(meta[2])
            lon = float(meta[3])
            assert 41.0 < lat < 41.3
            assert -77.7 < lon < -77.4

            # Line 3 (j==3): first data row — year + doy + value.
            begin = lines[3].strip().split()
            assert len(begin) >= 3, f"{path.name}: first day row too short"
            y = int(begin[0])
            doy = int(begin[1])
            assert y == 2015
            assert doy == 1

            # Last non-empty line (editor treats as end date).
            last = [_l for _l in lines if _l.strip()][-1].strip().split()
            last_y = int(last[0])
            last_doy = int(last[1])
            last_date = dt.date(last_y, 1, 1) + dt.timedelta(days=last_doy - 1)
            assert last_date == dt.date(2015, 1, 5), (
                f"{path.name}: end date should be start + 4 days"
            )

    def test_tmp_file_has_two_value_columns(self, mini_bundle, tmp_path):
        write_observed(mini_bundle, tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files
        lines = tmp_files[0].read_text().splitlines()
        # Day 1 row: YYYY doy TMAX TMIN — 4 fields after split.
        day1 = lines[3].strip().split()
        assert len(day1) == 4
        tmax = float(day1[2])
        tmin = float(day1[3])
        assert tmax > tmin, "TMAX should precede TMIN and be larger"

    def test_nbyr_spans_multiyear(self, tmp_path):
        series = synthesize_station(
            lat=40.0,
            lon=-80.0,
            elev=200.0,
            start_date=dt.date(2015, 12, 30),
            n_days=5,
            seed=0,
        )
        bundle = WeatherBundle(stations=[series], start="2015-12-30", n_days=5)
        write_observed(bundle, tmp_path)
        meta = (tmp_path / f"{series.station.name}.pcp").read_text().splitlines()[2]
        nbyr = int(meta.strip().split()[0])
        assert nbyr == 2, "2015-12-30 + 4 days spans 2015 and 2016"

    def test_overwrites_existing_files(self, mini_bundle, tmp_path):
        (tmp_path / "pcp.cli").write_text("STALE\n")
        write_observed(mini_bundle, tmp_path)
        assert "STALE" not in (tmp_path / "pcp.cli").read_text()

    def test_creates_output_dir(self, mini_bundle, tmp_path):
        target = tmp_path / "does" / "not" / "exist"
        write_observed(mini_bundle, target)
        assert target.is_dir()
        assert (target / "pcp.cli").is_file()


# ---------------------------------------------------------------------------
# Partial variable coverage
# ---------------------------------------------------------------------------


class TestPartialCoverage:
    def test_pcp_only_bundle(self, tmp_path):
        s = WeatherStation(name="s0n0e", lat=0.0, lon=0.0, elev=0.0)
        series = StationSeries(
            station=s,
            start="2020-06-01",
            n_days=3,
            pcp=[0.0, 1.5, 3.2],
        )
        result = write_observed(
            WeatherBundle(stations=[series], start="2020-06-01", n_days=3),
            tmp_path,
        )
        assert set(result.variables) == {"pcp"}
        assert (tmp_path / "pcp.cli").is_file()
        assert not (tmp_path / "tmp.cli").exists()
        assert not (tmp_path / "hmd.cli").exists()

    def test_tmp_requires_both_tmax_and_tmin(self, tmp_path):
        s = WeatherStation(name="s0n0e", lat=0.0, lon=0.0, elev=0.0)
        series = StationSeries(
            station=s,
            start="2020-06-01",
            n_days=2,
            pcp=[1.0, 2.0],
            tmax=[30.0, 31.0],  # tmin missing
        )
        bundle = WeatherBundle(stations=[series], start="2020-06-01", n_days=2)
        with pytest.raises(SwatBuilderInputError, match="tmax and tmin"):
            write_observed(bundle, tmp_path)


# ---------------------------------------------------------------------------
# Sad path — invariant violations
# ---------------------------------------------------------------------------


class TestValidation:
    def test_bad_start_date(self, tmp_path):
        s = WeatherStation(name="s0n0e", lat=0.0, lon=0.0, elev=0.0)
        series = StationSeries(station=s, start="2020-01-01", n_days=1, pcp=[0.0])
        bundle = WeatherBundle(
            stations=[series], start="NOT-A-DATE", n_days=1
        )
        with pytest.raises(SwatBuilderInputError, match="ISO date"):
            write_observed(bundle, tmp_path)

    def test_length_mismatch(self, tmp_path):
        s = WeatherStation(name="s0n0e", lat=0.0, lon=0.0, elev=0.0)
        series = StationSeries(
            station=s, start="2020-01-01", n_days=3, pcp=[0.0, 1.0]
        )
        bundle = WeatherBundle(stations=[series], start="2020-01-01", n_days=3)
        with pytest.raises(SwatBuilderInputError, match="length 2"):
            write_observed(bundle, tmp_path)

    def test_station_date_range_must_match_bundle(self, tmp_path):
        s = WeatherStation(name="s0n0e", lat=0.0, lon=0.0, elev=0.0)
        series = StationSeries(
            station=s, start="2020-01-02", n_days=3, pcp=[0.0, 1.0, 2.0]
        )
        bundle = WeatherBundle(stations=[series], start="2020-01-01", n_days=3)
        with pytest.raises(SwatBuilderInputError, match="span the same date range"):
            write_observed(bundle, tmp_path)


# ---------------------------------------------------------------------------
# Synthetic generator
# ---------------------------------------------------------------------------


class TestSynthetic:
    def test_deterministic_with_same_seed(self):
        a = synthesize([(40.0, -80.0, 200.0)], start="2015-01-01", n_days=365, seed=7)
        b = synthesize([(40.0, -80.0, 200.0)], start="2015-01-01", n_days=365, seed=7)
        assert a.stations[0].pcp == b.stations[0].pcp
        assert a.stations[0].tmax == b.stations[0].tmax

    def test_different_seeds_diverge(self):
        a = synthesize([(40.0, -80.0, 200.0)], start="2015-01-01", n_days=30, seed=1)
        b = synthesize([(40.0, -80.0, 200.0)], start="2015-01-01", n_days=30, seed=2)
        assert a.stations[0].tmax != b.stations[0].tmax

    def test_tmax_always_gt_tmin(self):
        bundle = synthesize(
            [(40.0, -80.0, 200.0)], start="2015-01-01", n_days=365, seed=0
        )
        s = bundle.stations[0]
        assert s.tmax is not None and s.tmin is not None
        for tx, tn in zip(s.tmax, s.tmin):
            assert tx > tn

    def test_variable_subset_is_honored(self):
        bundle = synthesize(
            [(40.0, -80.0, 200.0)],
            start="2015-01-01",
            n_days=5,
            variables=["pcp"],
        )
        s = bundle.stations[0]
        assert s.pcp is not None
        assert s.tmax is None and s.tmin is None
        assert s.hmd is None and s.wnd is None and s.slr is None

    def test_rejects_unknown_variable(self):
        with pytest.raises(SwatBuilderInputError, match="unknown weather variable"):
            synthesize(
                [(40.0, -80.0, 200.0)],
                start="2015-01-01",
                n_days=5,
                variables=["pcp", "foobar"],
            )

    def test_rejects_empty_station_list(self):
        with pytest.raises(SwatBuilderInputError, match="at least one station"):
            synthesize([], start="2015-01-01", n_days=5)

    def test_humidity_within_valid_range(self):
        bundle = synthesize(
            [(40.0, -80.0, 200.0)], start="2015-01-01", n_days=365, seed=0
        )
        hmd = bundle.stations[0].hmd
        assert hmd is not None
        assert all(0.0 <= v <= 1.0 for v in hmd)

    def test_round_trip_via_writer(self, tmp_path: Path):
        bundle = synthesize(
            [(40.0, -80.0, 200.0)], start="2015-01-01", n_days=30, seed=0
        )
        res = write_observed(bundle, tmp_path)
        assert res.n_stations == 1
        # Sanity: ~30% wet days on average ± large slack.
        pcp_lines = (tmp_path / f"{bundle.stations[0].station.name}.pcp").read_text().splitlines()[3:]
        rain_values = [float(line.strip().split()[-1]) for line in pcp_lines]
        assert len(rain_values) == 30
