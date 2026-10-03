import json

import pytest

from swatplus_builder.output.streamflow_performance import (
    assess_streamflow_performance,
    assess_streamflow_series,
)

SCOPE = dict(timestep="daily", period_start="2020-01-01", period_end="2020-01-03",
             evaluation_role="locked_training_verification")


@pytest.mark.parametrize("r2,nse,pbias,status", [
    (0.61, 0.51, 15, "met"), (0.61, 0.51, -15, "met"),
    (0.60, 0.51, 0, "not_met"), (0.61, 0.50, 0, "not_met"),
    (0.61, 0.51, 15.00001, "not_met"),
])
def test_exact_threshold_boundaries(r2, nse, pbias, status):
    result = assess_streamflow_performance(dict(r2=r2, nse=nse, pbias=pbias), **SCOPE)
    assert result["status"] == status
    assert "claim_tier" not in result


@pytest.mark.parametrize("missing", ["r2", "nse", "pbias"])
def test_missing_metric_cannot_pass(missing):
    metrics = dict(r2=1, nse=1, pbias=0, kge=1)
    del metrics[missing]
    result = assess_streamflow_performance(metrics, **SCOPE)
    assert result["status"] == "not_evaluated"
    assert result["metrics"][missing] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value", [
    ("r2", float("nan")), ("nse", float("inf")), ("pbias", float("-inf")),
    ("r2", 1.1), ("r2", -0.1), ("nse", 1.01), ("r2", True),
])
def test_invalid_metrics_are_not_ratings(field, value):
    metrics = dict(r2=1, nse=1, pbias=0)
    metrics[field] = value
    result = assess_streamflow_performance(metrics, **SCOPE)
    assert result["status"] == "not_evaluated"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value", [
    ("timestep", None), ("timestep", "hourly"), ("period_start", None),
    ("period_end", "2019-01-01"), ("evaluation_role", ""),
    ("spatial_scale", "field"),
])
def test_unscoped_metrics_cannot_pass(field, value):
    scope = {**SCOPE, field: value}
    assert assess_streamflow_performance(dict(r2=1, nse=1, pbias=0), **scope)["status"] == "not_evaluated"


def test_exact_alignment_recomputed_without_workflow_promotion():
    result = assess_streamflow_series([1, 2, 3], [1, 2, 3],
                                     dates=["2020-01-01", "2020-01-02", "2020-01-03"], **SCOPE)
    assert result["status"] == "met"
    assert result["metrics"] == dict(r2=1, nse=1, pbias=0)
    assert result["evaluation_role"] == "locked_training_verification"
    assert "numeric criteria only" in result["assessment_scope"]


def test_correlation_is_not_nse_and_negative_correlation_is_squared():
    result = assess_streamflow_series([1, 2, 3], [3, 2, 1], **SCOPE)
    assert result["metrics"]["r2"] == 1
    assert result["metrics"]["nse"] == -3
    assert result["status"] == "not_met"


@pytest.mark.parametrize("obs,sim", [
    ([1, float("nan"), 3], [1, 2, 3]), ([1, 2, 3], [1, -2, 3]),
    ([1, 1, 1], [1, 1, 1]), ([1, 2, 3], [2, 2, 2]), ([1], [1]),
    ([1, 2, 3], [1, 2]),
])
def test_invalid_series_are_not_silently_filtered(obs, sim):
    result = assess_streamflow_series(obs, sim, **SCOPE)
    assert result["status"] == "not_evaluated"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("dates", [
    ["2020-01-01", "2020-01-01", "2020-01-03"],
    ["2020-01-01", "2020-01-03", "2020-01-02"],
    ["2020-01-01", "2020-01-02", "2020-01-04"], [],
])
def test_duplicate_unordered_or_wrong_period_dates_block_assessment(dates):
    result = assess_streamflow_series([1, 2, 3], [1, 2, 3], dates=dates, **SCOPE)
    assert result["status"] == "not_evaluated"
    assert "date_alignment_or_period_mismatch" in result["reasons"]


@pytest.mark.parametrize("middle", [
    "2020-01-02garbage", "2020-01-02T12:00:00", "2020-01-02T00:00:00.000001",
    "2020-01-02 invalid", "2020-01-02T00:00:00trailing",
])
def test_date_suffixes_and_within_day_times_are_not_discarded(middle):
    result = assess_streamflow_series([1, 2, 3], [1, 2, 3],
                                     dates=["2020-01-01", middle, "2020-01-03"], **SCOPE)
    assert result["status"] == "not_evaluated"
    assert "invalid_alignment_dates" in result["reasons"]


@pytest.mark.parametrize("suffix", ["T00:00:00", " 00:00:00", "T00:00:00Z"])
def test_midnight_iso_timestamp_alignment_is_supported(suffix):
    result = assess_streamflow_series([1, 2, 3], [1, 2, 3],
                                     dates=[f"2020-01-0{i}{suffix}" for i in (1, 2, 3)], **SCOPE)
    assert result["status"] == "met"
