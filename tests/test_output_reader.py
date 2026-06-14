"""Tests for :mod:`swatplus_builder.output.reader` and
:mod:`swatplus_builder.output.summary`.

Coverage:

* Happy-path parse of ``basin_wb_aa.txt`` and ``channel_sd_aa.txt``
  fixtures that mirror real engine output (title / header / units /
  data layout, mixed int+float+str columns).
* Units-line autodetect (present vs. absent).
* Edge cases: blank file, title-only, blank header, wrong-token-count
  data row, unparseable numeric.
* Type coercion: ``jday``/``mon``/``unit``/``gis_id`` → ``int``,
  ``name`` → ``str``, everything else → ``float``.
* :func:`build_run_summary`: populates the canonical keys from a
  synthetic TxtInOut directory, handles the outlet-pick heuristic
  (max ``flo_out`` wins), and gracefully returns ``{}`` for missing
  or malformed files.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# Mirrors what SWAT+ 60.x actually writes for basin_wb_aa with a
# handful of columns. Real files have ~35 columns; we keep it short but
# structurally identical (3-line header + 1 data row).
_BASIN_WB_AA_SAMPLE = dedent(
    """\
    basin_wb_aa                              annual average values
       jday    mon    day     yr   unit    gis_id   name           precip        et       pet   surq_gen      latq      perc   wateryld
                                                                    mm        mm        mm         mm        mm        mm         mm
          0      0      0      0      1         0   bsn          1200.50    900.25   1100.00    150.75     30.25     80.00     180.00
    """
)


# Three channels so outlet-pick (max flo_out) has something to choose.
# Channel 3 has the largest flo_out and is therefore the "outlet" for
# our topological heuristic.
_CHANNEL_SD_AA_SAMPLE = dedent(
    """\
    channel_sd_aa                            annual average values
       jday    mon    day     yr   unit    gis_id   name           area    flo_out    sed_out
                                                                    ha         m3       tons
          0      0      0      0      1         1   cha01          10.5  1000000.0       5.0
          0      0      0      0      2         2   cha02          20.0  2500000.0      12.0
          0      0      0      0      3         3   cha03          30.5  7500000.0      20.0
    """
)


@pytest.fixture
def txtinout_with_outputs(tmp_path: Path) -> Path:
    """A TxtInOut/ dir preloaded with realistic AA output fixtures."""
    d = tmp_path / "TxtInOut"
    d.mkdir()
    (d / "basin_wb_aa.txt").write_text(_BASIN_WB_AA_SAMPLE)
    (d / "channel_sd_aa.txt").write_text(_CHANNEL_SD_AA_SAMPLE)
    return d


# ---------------------------------------------------------------------------
# read_output_file — parser contract
# ---------------------------------------------------------------------------


class TestReadOutputFile:
    def test_parses_basin_wb_aa_happy_path(self, tmp_path):
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "basin_wb_aa.txt"
        p.write_text(_BASIN_WB_AA_SAMPLE)

        t = read_output_file(p)
        assert t.path == p.resolve()
        assert t.title.startswith("basin_wb_aa")
        assert t.columns[:7] == ["jday", "mon", "day", "yr", "unit", "gis_id", "name"]
        assert "precip" in t.columns
        assert len(t) == 1
        row = t.rows[0]
        # Identifier ints
        assert row["unit"] == 1 and isinstance(row["unit"], int)
        assert row["gis_id"] == 0 and isinstance(row["gis_id"], int)
        # name stays string
        assert row["name"] == "bsn"
        # measurements are floats
        assert row["precip"] == pytest.approx(1200.50)
        assert row["et"] == pytest.approx(900.25)
        assert row["wateryld"] == pytest.approx(180.00)

    def test_units_row_parsed_and_padded(self, tmp_path):
        """Units row has fewer tokens than columns (name has no unit).

        We expect units[i] to align with columns[i], padded with "" so
        the arrays are the same length.
        """
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "basin_wb_aa.txt"
        p.write_text(_BASIN_WB_AA_SAMPLE)

        t = read_output_file(p)
        assert len(t.units) == len(t.columns)
        # First 7 columns are identifiers → units padded with "" since
        # the file's units line only covers the numeric tail.
        precip_idx = t.columns.index("precip")
        assert t.units[precip_idx] == "mm"

    def test_column_accessor(self, tmp_path):
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "channel_sd_aa.txt"
        p.write_text(_CHANNEL_SD_AA_SAMPLE)
        t = read_output_file(p)
        assert t.column("flo_out") == [1_000_000.0, 2_500_000.0, 7_500_000.0]
        assert t.column("name") == ["cha01", "cha02", "cha03"]
        with pytest.raises(KeyError):
            t.column("no_such_column")

    def test_units_line_absent_is_ok(self, tmp_path):
        """Older builds skip the units line. We should still parse."""
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "slim.txt"
        p.write_text(
            "slim_aa\n"
            "   jday    mon    day     yr   unit    gis_id   name     foo\n"
            "      0      0      0      0      1         1   a        1.5\n"
            "      0      0      0      0      2         2   b        2.5\n"
        )
        t = read_output_file(p)
        # The second line looks like data (numbers), so units stays [].
        assert t.units == []
        assert len(t) == 2
        assert t.rows[0]["foo"] == pytest.approx(1.5)

    def test_multiple_data_rows(self, tmp_path):
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "chan.txt"
        p.write_text(_CHANNEL_SD_AA_SAMPLE)
        t = read_output_file(p)
        assert len(t) == 3
        assert [row["unit"] for row in t.rows] == [1, 2, 3]
        assert [row["name"] for row in t.rows] == ["cha01", "cha02", "cha03"]

    def test_blank_lines_inside_data_are_skipped(self, tmp_path):
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "holes.txt"
        p.write_text(
            "title\n"
            "jday mon day yr unit gis_id name foo\n"
            "n/a n/a n/a n/a n/a n/a n/a mm\n"
            "0 0 0 0 1 1 a 1.0\n"
            "\n"
            "0 0 0 0 2 2 b 2.0\n"
        )
        t = read_output_file(p)
        assert len(t) == 2

    def test_missing_file_raises_input_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.output.reader import read_output_file

        with pytest.raises(SwatBuilderInputError):
            read_output_file(tmp_path / "nope.txt")

    def test_empty_file_raises_external_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "empty.txt"
        p.write_text("")
        with pytest.raises(SwatBuilderExternalError):
            read_output_file(p)

    def test_title_only_raises_external_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "title_only.txt"
        p.write_text("just a title\n\n")
        with pytest.raises(SwatBuilderExternalError):
            read_output_file(p)

    def test_wrong_token_count_raises_with_line_number(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "bad.txt"
        p.write_text(
            "title\n"
            "jday mon day yr unit gis_id name precip\n"
            "n/a n/a n/a n/a n/a n/a n/a mm\n"
            "0 0 0 0 1 1 a 1.0 EXTRA_TOKEN\n"
        )
        with pytest.raises(SwatBuilderExternalError) as ei:
            read_output_file(p)
        ctx = ei.value.context
        assert ctx["expected"] == 8
        assert ctx["got"] == 9
        assert ctx["line_no"] == 4

    def test_non_numeric_in_numeric_column_raises(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.output.reader import read_output_file

        p = tmp_path / "bad_num.txt"
        p.write_text(
            "title\n"
            "jday mon day yr unit gis_id name precip\n"
            "0 0 0 0 1 1 a NOT_A_NUMBER\n"
        )
        with pytest.raises(SwatBuilderExternalError) as ei:
            read_output_file(p)
        assert ei.value.context["column"] == "precip"
        assert ei.value.context["token"] == "NOT_A_NUMBER"


# ---------------------------------------------------------------------------
# read_basin_wb_aa / read_channel_sd_aa — convenience wrappers
# ---------------------------------------------------------------------------


class TestReadNamed:
    def test_read_basin_wb_aa_finds_file(self, txtinout_with_outputs):
        from swatplus_builder.output.reader import read_basin_wb_aa

        t = read_basin_wb_aa(txtinout_with_outputs)
        assert t.path.name == "basin_wb_aa.txt"
        assert len(t) == 1

    def test_read_channel_sd_aa_finds_file(self, txtinout_with_outputs):
        from swatplus_builder.output.reader import read_channel_sd_aa

        t = read_channel_sd_aa(txtinout_with_outputs)
        assert t.path.name == "channel_sd_aa.txt"
        assert len(t) == 3

    def test_missing_file_raises_actionable(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderExternalError
        from swatplus_builder.output.reader import read_basin_wb_aa

        d = tmp_path / "empty_txtinout"
        d.mkdir()
        with pytest.raises(SwatBuilderExternalError) as ei:
            read_basin_wb_aa(d)
        assert "basin_wb_aa.txt" in str(ei.value)
        assert "print.prt" in str(ei.value)

    def test_missing_dir_raises_input_error(self, tmp_path):
        from swatplus_builder.errors import SwatBuilderInputError
        from swatplus_builder.output.reader import read_basin_wb_aa

        with pytest.raises(SwatBuilderInputError):
            read_basin_wb_aa(tmp_path / "nope")


# ---------------------------------------------------------------------------
# build_run_summary — the SwatPlusRun.summary producer
# ---------------------------------------------------------------------------


class TestBuildRunSummary:
    def test_populates_all_canonical_keys(self, txtinout_with_outputs):
        from swatplus_builder.output.summary import SUMMARY_KEYS, build_run_summary

        s = build_run_summary(txtinout_with_outputs)
        # Every documented key is present for this fixture.
        for k in SUMMARY_KEYS:
            assert k in s, f"missing summary key: {k!r}"
        # Values round-trip correctly.
        assert s["precip_mm"] == pytest.approx(1200.50)
        assert s["et_mm"] == pytest.approx(900.25)
        assert s["pet_mm"] == pytest.approx(1100.00)
        assert s["surq_gen_mm"] == pytest.approx(150.75)
        assert s["latq_mm"] == pytest.approx(30.25)
        assert s["perc_mm"] == pytest.approx(80.00)
        assert s["wateryld_mm"] == pytest.approx(180.00)
        assert s["channel_count"] == pytest.approx(3.0)

    def test_outlet_picks_channel_with_largest_flo_out(
        self, txtinout_with_outputs
    ):
        from swatplus_builder.output.summary import build_run_summary

        s = build_run_summary(txtinout_with_outputs)
        # Outlet = cha03 with flo_out = 7_500_000 m3/yr.
        # Mean rate = 7_500_000 / (365.25 * 86400) ~= 0.2376 m3/s.
        expected = 7_500_000.0 / (365.25 * 86400.0)
        assert s["mean_q_at_outlet_m3_per_s"] == pytest.approx(expected)

    def test_returns_all_float_for_json_round_trip(self, txtinout_with_outputs):
        from swatplus_builder.output.summary import build_run_summary

        s = build_run_summary(txtinout_with_outputs)
        assert all(isinstance(v, float) for v in s.values())

    def test_empty_txtinout_returns_empty_summary(self, tmp_path):
        """No AA files present → empty dict, not an exception."""
        from swatplus_builder.output.summary import build_run_summary

        d = tmp_path / "empty_txtinout"
        d.mkdir()
        assert build_run_summary(d) == {}

    def test_only_basin_wb_present_partial_summary(self, tmp_path):
        from swatplus_builder.output.summary import build_run_summary

        d = tmp_path / "wb_only"
        d.mkdir()
        (d / "basin_wb_aa.txt").write_text(_BASIN_WB_AA_SAMPLE)

        s = build_run_summary(d)
        assert "precip_mm" in s
        assert "wateryld_mm" in s
        # No channel_sd_aa → no outlet / channel_count.
        assert "mean_q_at_outlet_m3_per_s" not in s
        assert "channel_count" not in s

    def test_only_channel_sd_present_partial_summary(self, tmp_path):
        from swatplus_builder.output.summary import build_run_summary

        d = tmp_path / "chan_only"
        d.mkdir()
        (d / "channel_sd_aa.txt").write_text(_CHANNEL_SD_AA_SAMPLE)

        s = build_run_summary(d)
        assert "channel_count" in s
        assert "mean_q_at_outlet_m3_per_s" in s
        # No basin_wb → no precip / et / etc.
        assert "precip_mm" not in s

    def test_malformed_file_is_swallowed_not_raised(self, tmp_path):
        """Parse errors should log + skip, never propagate."""
        from swatplus_builder.output.summary import build_run_summary

        d = tmp_path / "bad"
        d.mkdir()
        # Well-formed channel file, malformed basin file.
        (d / "basin_wb_aa.txt").write_text("title\ncols\nunits\n1 2 3 4 5 6\n")
        (d / "channel_sd_aa.txt").write_text(_CHANNEL_SD_AA_SAMPLE)

        s = build_run_summary(d)
        # Basin summary missing — but channel summary still present.
        assert "precip_mm" not in s
        assert "channel_count" in s
        assert s["channel_count"] == pytest.approx(3.0)

    def test_basin_wb_with_missing_column_partial_keys(self, tmp_path):
        """If the engine build doesn't emit ``pet``, that key is just skipped."""
        from swatplus_builder.output.summary import build_run_summary

        d = tmp_path / "no_pet"
        d.mkdir()
        (d / "basin_wb_aa.txt").write_text(
            "basin_wb_aa   annual average values\n"
            "jday mon day yr unit gis_id name precip et wateryld\n"
            "n/a n/a n/a n/a n/a n/a n/a mm mm mm\n"
            "0 0 0 0 1 0 bsn 1200.0 900.0 180.0\n"
        )
        s = build_run_summary(d)
        assert s["precip_mm"] == pytest.approx(1200.0)
        assert s["et_mm"] == pytest.approx(900.0)
        assert "pet_mm" not in s
        assert "surq_gen_mm" not in s
