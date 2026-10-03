"""Full-vector geometry and bounded shared design generation checks."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from swatplus_builder.calibration import experiment_design as design


def bounds(dimension=14):
    return {f"p{n:02d}": (float(n), float(n + 2)) for n in range(dimension)}


def test_fifteen_points_span_fourteen_dimensional_affine_domain_reproducibly():
    domain = bounds()
    first = design.make_shared_design(domain, 15, seed=42, required_backend="rbf")
    second = design.make_shared_design(domain, 15, seed=42, required_backend="rbf")
    assert first.to_json() == second.to_json()
    quality = first.quality
    assert (quality.dimension, quality.npoints, quality.affine_rank) == (14, 15, 15)
    assert quality.distinct and quality.gp_ready and quality.rbf_ready
    assert quality.minimum_distance > 0
    for point in first.points:
        assert set(point) == set(domain)
        assert all(lo <= point[name] <= hi for name, (lo, hi) in domain.items())
    assert json.loads(json.dumps(first.to_json()))["quality"]["rbf_ready"]
    with pytest.raises(TypeError):
        first.points[0]["p00"] = 1


def test_declared_incumbent_is_exact_and_other_points_are_distinct():
    domain = bounds()
    incumbent = {name: pair[1] for name, pair in domain.items()}
    shared = design.make_shared_design(
        domain, 15, seed=55, incumbent=incumbent, required_backend="rbf"
    )
    assert dict(shared.points[0]) == incumbent
    assert shared.method == "latin_remaining_plus_declared_incumbent"
    assert shared.quality.rbf_ready
    incumbent["p00"] = -10
    assert shared.points[0]["p00"] == 2


def test_partial_inherited_vectors_never_fill_registry_defaults():
    domain = bounds(2)
    with pytest.raises(ValueError, match="full parameter vector"):
        design.make_shared_design(domain, 3, incumbent={"p00": 1.0})
    with pytest.raises(ValueError, match="full parameter vector"):
        design.assess_design(domain, [{"p00": 1.0}])


def test_gp_small_design_is_not_labeled_rbf_ready():
    shared = design.make_shared_design(bounds(), 8, seed=68)
    assert shared.quality.gp_ready
    assert shared.quality.affine_rank == 8
    assert not shared.quality.rbf_ready
    with pytest.raises(ValueError, match="dimension"):
        design.make_shared_design(bounds(), 8, required_backend="rbf")


def test_collinear_distinct_points_fail_rbf_affine_rank():
    domain = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
    points = [{"x": x, "y": x} for x in (0.1, 0.5, 0.9)]
    quality = design.assess_design(domain, points, required_backend="rbf")
    assert quality.distinct and quality.affine_rank == 2
    assert not quality.rbf_ready
    duplicate = design.assess_design(domain, [points[0], points[0]])
    assert not duplicate.distinct and duplicate.minimum_distance == 0


def test_generation_retry_cap_is_enforced(monkeypatch):
    original = design.assess_design
    calls = []

    def deficient(*args, **kwargs):
        calls.append(1)
        return replace(original(*args, **kwargs), affine_rank=0, rbf_ready=False)

    monkeypatch.setattr(design, "assess_design", deficient)
    with pytest.raises(ValueError, match="3 generation attempts"):
        design.make_shared_design(bounds(2), 3, max_attempts=3)
    assert len(calls) == 3


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, True, None])
def test_bad_incumbent_rejected(invalid):
    with pytest.raises(ValueError, match="finite in-bounds"):
        design.make_shared_design({"x": (0.0, 1.0)}, 2, incumbent={"x": invalid})


@pytest.mark.parametrize("name", ["n_points", "max_attempts", "seed"])
def test_boolean_and_fractional_generation_sizes_rejected(name):
    args = {"n_points": 3, "max_attempts": 2, "seed": 42}
    args[name] = 1.5
    with pytest.raises(ValueError, match="integer"):
        design.make_shared_design(bounds(2), **args)
