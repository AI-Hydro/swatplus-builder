from __future__ import annotations

from textwrap import dedent

import pandas as pd
import pytest


def _write(path, text: str) -> None:
    path.write_text(dedent(text))


def test_evaluate_run_falls_back_when_channel_day_is_zero(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    # Primary candidate: valid shape but zero discharge everywhere.
    _write(
        txt / "channel_day.txt",
        """\
        channel_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a ha-m
        1 1 1 2015 1 1 cha01 0.0
        2 1 2 2015 1 1 cha01 0.0
        """,
    )

    # Fallback candidate: basin-level daily routed discharge rate.
    _write(
        txt / "basin_sd_cha_day.txt",
        """\
        basin_sd_cha_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 bsn 0.1
        2 1 2 2015 1 1 bsn 0.2
        """,
    )

    obs = pd.Series(
        [0.08, 0.18],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, metrics = evaluate_run(txt / "channel_day.txt", obs, outlet_gis_id=1)

    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(0.1)
    assert df["sim"].iloc[1] == pytest.approx(0.2)
    assert "nse" in metrics


def test_evaluate_run_converts_channel_day_ha_m_to_cms(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_day.txt",
        """\
        channel_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a ha-m
        1 1 1 2015 1 1 cha01 1.0
        2 1 2 2015 1 1 cha01 2.0
        """,
    )

    obs = pd.Series(
        [0.1, 0.2],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, _ = evaluate_run(txt / "channel_day.txt", obs, outlet_gis_id=1)

    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(10000.0 / 86400.0)
    assert df["sim"].iloc[1] == pytest.approx(20000.0 / 86400.0)


def test_evaluate_run_autodetects_flowing_outlet_when_gis1_is_dry(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 0.0
        2 1 2 2015 1 1 cha01 0.0
        1 1 1 2015 7 7 cha07 1.5
        2 1 2 2015 7 7 cha07 2.5
        """,
    )

    # Mark channel 7 as terminal outlet in chandeg.con.
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        1 cha0001 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )

    obs = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    # outlet_gis_id=1 is dry; evaluator should auto-switch to the flowing outlet.
    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        return_diagnostics=True,
    )

    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(1.5)
    assert df["sim"].iloc[1] == pytest.approx(2.5)
    assert diag["requested_outlet_gis_id"] == 1
    assert diag["selected_outlet_gis_id"] == 7
    assert diag["outlet_autodetected"] is True
    assert diag["outlet_selection_reason"] == "requested_outlet_dry"


def test_evaluate_run_autodetects_terminal_when_requested_gis_is_missing(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 7 29 cha29 1.5
        2 1 2 2015 7 29 cha29 2.5
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        7 cha0029 29 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )
    obs = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        return_diagnostics=True,
    )

    assert df["sim"].tolist() == pytest.approx([1.5, 2.5])
    assert diag["requested_outlet_gis_id"] == 1
    assert diag["selected_outlet_gis_id"] == 29
    assert diag["outlet_autodetected"] is True
    assert diag["outlet_selection_reason"] == "requested_outlet_missing"


def test_evaluate_run_prefers_terminal_when_requested_outlet_is_non_terminal(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 0.2
        2 1 2 2015 1 1 cha01 0.2
        1 1 1 2015 7 7 cha07 1.0
        2 1 2 2015 7 7 cha07 2.0
        """,
    )

    # Channel 7 is terminal; channel 1 is internal.
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        1 cha0001 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )

    obs = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        return_diagnostics=True,
    )

    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(1.0)
    assert df["sim"].iloc[1] == pytest.approx(2.0)
    assert diag["requested_outlet_gis_id"] == 1
    assert diag["requested_outlet_is_terminal"] is False
    assert diag["selected_outlet_gis_id"] == 7
    assert diag["outlet_autodetected"] is True
    assert diag["outlet_selection_reason"] == "requested_outlet_non_terminal_single_terminal"


def test_evaluate_run_keeps_requested_non_terminal_when_fit_is_better(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 1.0
        2 1 2 2015 1 1 cha01 2.0
        1 1 1 2015 7 7 cha07 0.1
        2 1 2 2015 7 7 cha07 0.1
        """,
    )

    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        1 cha0001 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )

    obs = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        return_diagnostics=True,
    )

    # Auto policy must upgrade non-terminal outlets to real terminal
    # even when the non-terminal happens to fit observations better.
    assert len(df) == 2
    assert df["sim"].iloc[0] == pytest.approx(0.1)
    assert df["sim"].iloc[1] == pytest.approx(0.1)
    assert diag["requested_outlet_is_terminal"] is False
    assert diag["selected_outlet_gis_id"] == 7
    assert diag["outlet_autodetected"] is True
    assert diag["outlet_selection_reason"] == "requested_outlet_non_terminal_single_terminal"


def test_evaluate_run_labels_multi_terminal_non_terminal_upgrade(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 0.2
        2 1 2 2015 1 1 cha01 0.2
        1 1 1 2015 7 7 cha07 1.0
        2 1 2 2015 7 7 cha07 2.0
        1 1 1 2015 8 8 cha08 3.0
        2 1 2 2015 8 8 cha08 4.0
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        1 cha0001 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        8 cha0008 8 0 0 0 0 8 s 0 0 0 1 out 2 tot 1.0
        """,
    )
    obs = pd.Series(
        [3.0, 4.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        return_diagnostics=True,
    )

    assert df["sim"].tolist() == [3.0, 4.0]
    assert diag["requested_outlet_is_terminal"] is False
    assert diag["selected_outlet_gis_id"] == 8
    assert diag["terminal_outlet_count"] == 2
    assert diag["outlet_selection_reason"] == "requested_outlet_non_terminal_largest_terminal_flow"


def test_evaluate_run_reports_diagnostic_all_terminal_scope_metrics(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 7 7 cha07 1.0
        2 1 2 2015 7 7 cha07 2.0
        1 1 1 2015 8 8 cha08 2.0
        2 1 2 2015 8 8 cha08 3.0
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        8 cha0008 8 0 0 0 0 8 s 0 0 0 1 out 2 tot 1.0
        """,
    )
    obs = pd.Series(
        [3.0, 5.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    _df, _metrics, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=7,
        outlet_policy="strict",
        return_diagnostics=True,
    )

    assert diag["terminal_scope_metrics_available"] is True
    assert diag["terminal_scope_metric_claim_impact"] == "diagnostic_only_not_final_claim_evidence"
    assert diag["terminal_scope_metric_terminal_ids"] == [7, 8]
    assert diag["selected_terminal_fraction_of_all_terminal_flow"] == pytest.approx(3.0 / 8.0)
    assert diag["selected_terminal_pbias"] == pytest.approx(-62.5)
    assert diag["all_terminal_pbias"] == pytest.approx(0.0)
    assert diag["all_terminal_volume_gate_passes_diagnostic"] is True


def test_evaluate_run_reports_single_terminal_fraction_as_one(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 12 12 cha12 3.0
        2 1 2 2015 12 12 cha12 5.0
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        12 cha0012 12 0 0 0 0 12 s 0 0 0 1 out 1 tot 1.0
        """,
    )
    obs = pd.Series(
        [3.0, 5.0],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    _df, _metrics, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=12,
        outlet_policy="strict",
        return_diagnostics=True,
    )

    assert diag["terminal_scope_metrics_available"] is True
    assert diag["terminal_scope_metric_terminal_ids"] == [12]
    assert diag["selected_terminal_fraction_of_all_terminal_flow"] == pytest.approx(1.0)
    assert diag["selected_terminal_pbias"] == pytest.approx(0.0)
    assert diag["all_terminal_pbias"] == pytest.approx(0.0)
    assert diag["all_terminal_volume_gate_passes_diagnostic"] is True


def test_evaluate_run_uses_terminal_inflow_sum_when_terminal_state_is_not_accumulated(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 226 231 cha231 10.0
        2 1 2 2015 226 231 cha231 20.0
        1 1 1 2015 242 247 cha247 1.0
        2 1 2 2015 242 247 cha247 2.0
        1 1 1 2015 254 259 cha259 0.1
        2 1 2 2015 254 259 cha259 0.1
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        226 cha231 231 0 0 0 0 226 s 0 0 0 1 sdc 254 tot 1.0
        242 cha247 247 0 0 0 0 242 s 0 0 0 1 sdc 254 tot 1.0
        254 cha259 259 0 0 0 0 254 s 0 0 0 0
        """,
    )
    obs = pd.Series(
        [11.1, 22.1],
        index=pd.to_datetime(["2015-01-01", "2015-01-02"]),
        name="obs",
    )

    df, metrics, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=259,
        outlet_policy="strict",
        return_diagnostics=True,
    )

    assert df["sim"].tolist() == pytest.approx([11.1, 22.1])
    assert metrics["pbias"] == pytest.approx(0.0)
    assert diag["selected_outlet_gis_id"] == 259
    assert diag["selected_outlet_gis_ids"] == [231, 247, 259]
    assert diag["outlet_scope"] == "terminal_inflow_sum"
    assert diag["outlet_selection_reason"] == "terminal_inflow_sum"
    assert diag["terminal_inflow_parent_gis_ids"] == [231, 247]
    assert diag["terminal_scope_metric_reason"] == "terminal_inflow_sum_is_effective_selected_hydrograph"


def test_terminal_parser_uses_gis_id_not_internal_id(tmp_path):
    from swatplus_builder.output.eval import terminal_channel_ids

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        900 cha0900 10 0 0 0 0 1 s 0 0 0 1 out 1 tot 1.0
        901 cha0901 11 0 0 0 0 1 s 0 0 0 1 sdc 1 tot 1.0
        """,
    )

    terms = terminal_channel_ids(txt)
    assert terms == [10]


def test_evaluate_run_strict_policy_keeps_requested_outlet_when_dry(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()

    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 0.0
        2 1 2 2015 1 1 cha01 0.0
        1 1 1 2015 7 7 cha07 1.5
        2 1 2 2015 7 7 cha07 2.5
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        1 cha0001 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )
    obs = pd.Series([1.0, 2.0], index=pd.to_datetime(["2015-01-01", "2015-01-02"]))

    df, _, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        outlet_policy="strict",
        return_diagnostics=True,
    )
    assert len(df) == 2
    assert float(df["sim"].abs().sum()) == pytest.approx(0.0)
    assert diag["selected_outlet_gis_id"] == 1
    assert diag["outlet_autodetected"] is False


def test_evaluate_run_returns_provenance_hashes_and_terminals(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 7 7 cha07 1.0
        2 1 2 2015 7 7 cha07 2.0
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        7 cha0007 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0
        """,
    )
    obs = pd.Series([1.0, 2.0], index=pd.to_datetime(["2015-01-01", "2015-01-02"]))

    _df, _metrics, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=7,
        return_diagnostics=True,
    )
    assert diag["outlet_policy"] == "auto"
    assert diag["terminal_outlet_ids"] == [7]
    assert diag["terminal_outlet_count"] == 1
    assert isinstance(diag["chandeg_con_sha256"], str) and len(diag["chandeg_con_sha256"]) == 64
    assert isinstance(diag["sim_source_sha256"], str) and len(diag["sim_source_sha256"]) == 64


def test_evaluate_run_can_score_explicit_all_terminal_virtual_outlet(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 7 7 cha07 1.0
        1 1 1 2015 8 8 cha08 2.0
        2 1 2 2015 7 7 cha07 2.0
        2 1 2 2015 8 8 cha08 3.0
        """,
    )
    _write(
        txt / "chandeg.con",
        """\
        chandeg.con
        id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac
        7 cha0007 7 0 0 0 0 7 s 0 0 0 0 out 1 tot 1.0
        8 cha0008 8 0 0 0 0 8 s 0 0 0 0 out 2 tot 1.0
        """,
    )
    obs = pd.Series([3.0, 5.0], index=pd.to_datetime(["2015-01-01", "2015-01-02"]))

    df, metrics, diag = evaluate_run(
        txt / "channel_sd_day.txt",
        obs,
        outlet_gis_id=1,
        outlet_policy="all_terminal_sum",
        return_diagnostics=True,
    )

    assert df["sim"].tolist() == [3.0, 5.0]
    assert metrics["pbias"] == pytest.approx(0.0)
    assert diag["outlet_scope"] == "virtual_all_terminal"
    assert diag["requested_outlet_is_terminal"] is False
    assert diag["selected_outlet_gis_ids"] == [7, 8]
    assert diag["outlet_selection_reason"] == "explicit_virtual_all_terminal_sum"
    assert diag["virtual_outlet_claim_authority"] is False


def test_evaluate_run_rejects_invalid_outlet_policy(tmp_path):
    from swatplus_builder.output.eval import evaluate_run

    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    _write(
        txt / "channel_sd_day.txt",
        """\
        channel_sd_day
        jday mon day yr unit gis_id name flo_out
        n/a n/a n/a n/a n/a n/a n/a m3/s
        1 1 1 2015 1 1 cha01 1.0
        """,
    )
    obs = pd.Series([1.0], index=pd.to_datetime(["2015-01-01"]))
    with pytest.raises(ValueError):
        evaluate_run(
            txt / "channel_sd_day.txt",
            obs,
            outlet_gis_id=1,
            outlet_policy="unknown",  # type: ignore[arg-type]

        )


def _write_flow_sim(path, dates, flows):
    header = "channel_sd_day\njday mon day yr unit gis_id name flo_out\nn/a n/a n/a n/a n/a n/a n/a m3/s\n"
    rows = "\n".join(
        f"{d.dayofyear} {d.month} {d.day} {d.year} 1 1 cha01 {q:.4f}" for d, q in zip(dates, flows)
    )
    path.write_text(header + rows + "\n", encoding="utf-8")


def test_evaluate_run_includes_log_kge_metric(tmp_path):
    """evaluate_run must return a log_kge key alongside nse/kge/pbias."""
    from swatplus_builder.output.eval import evaluate_run

    dates = pd.date_range("2015-01-01", periods=30, freq="D")
    flows = [float(i % 5 + 1) for i in range(30)]

    txt = tmp_path / "TxtInOut"
    txt.mkdir()
    _write_flow_sim(txt / "channel_sd_day.txt", dates, flows)

    obs = pd.Series(flows, index=dates)
    _df, metrics = evaluate_run(txt / "channel_sd_day.txt", obs, outlet_gis_id=1)

    assert "log_kge" in metrics
    import math
    assert math.isfinite(metrics["log_kge"])
    # Perfect simulation → log_kge should be close to 1
    assert metrics["log_kge"] > 0.99


def test_log_kge_score_prefers_recession_fit(tmp_path):
    """Candidate with better low-flow fit should score higher under rank_nse_kge."""
    from swatplus_builder.calibration.locked_benchmark import _score_candidate

    # Candidate A: decent raw KGE, poor low-flow fit (log_kge low)
    candidate_a = {"nse": 0.5, "kge": 0.6, "log_kge": 0.1, "pbias": 10.0,
                   "physical_gate_passed": 1.0, "calibration_process_gate_passed": 1.0}
    # Candidate B: same raw KGE, much better low-flow fit (log_kge high)
    candidate_b = {"nse": 0.5, "kge": 0.6, "log_kge": 0.7, "pbias": 10.0,
                   "physical_gate_passed": 1.0, "calibration_process_gate_passed": 1.0}

    score_a = _score_candidate(candidate_a, objective="maintain_volume_gate_then_rank_nse_kge")
    score_b = _score_candidate(candidate_b, objective="maintain_volume_gate_then_rank_nse_kge")

    assert score_b > score_a, f"Better log_kge should rank higher: {score_b} > {score_a}"
