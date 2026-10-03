"""Full-vector preparation seals inputs and tests bridge writes without an engine."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/research/calibration_fullvector_preflight.py'
spec = importlib.util.spec_from_file_location('fullvector_preflight', SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def row(name, endpoints):
    return {'parameter': name, 'activity_class': 'active',
            'evidence': {'bound_results': [{'bound': label, 'value': value}
                                          for label, value in endpoints.items()]}}


@pytest.fixture
def retained_inputs(tmp_path):
    pe1 = tmp_path / 'pe1'
    engine = tmp_path / 'engine'
    engine.write_bytes(b'not an executable: identity only')
    for gauge in preflight.BASINS:
        basin = pe1 / f'usgs_{gauge}'
        source = basin / 'calibration/locked_calibrated_TxtInOut'
        source.mkdir(parents=True)
        (source / 'hydrology.hyd').write_text('hydrology\nname esco pet_co\nhru1 0.95 1.0\n')
        benchmark = basin / 'benchmark'
        benchmark.mkdir()
        alignment = benchmark / 'alignment.csv'
        alignment.write_text('PRIVATE WITHHELD OBSERVATION CONTENT\n')
        (benchmark / 'benchmark_lock.json').write_text(json.dumps({
            'basin_id': f'usgs_{gauge}',
            'alignment_sha256': hashlib.sha256(alignment.read_bytes()).hexdigest(),
        }))
        screen = basin / 'calibration/sensitivity_screen_locked/sensitivity_screen.json'
        screen.parent.mkdir()
        screen.write_text(json.dumps({'basin_id': f'usgs_{gauge}', 'basis': 'basin_specific',
                                      'parameters': [row('ESCO', {'lower': .01, 'upper': 1.}),
                                                     row('PET_CO', {'lower': .8, 'upper': 1.2})]}))
    return pe1, engine


def test_preparation_deterministic_complete_sealed_and_original_inputs_unchanged(retained_inputs):
    pe1, engine = retained_inputs
    originals = {str(p): p.read_bytes() for p in pe1.rglob('*') if p.is_file()}
    first = preflight.prepare_preflight(pe1, engine)
    second = preflight.prepare_preflight(pe1, engine)
    assert first == second
    assert first['engine_calls'] == 0 and first['status'] == 'prepared_not_executed'
    assert first['budget_per_arm']['total_cap'] == 18
    assert sum(first['budget_per_arm'][k] for k in ('screen', 'design', 'search', 'final_training', 'validation')) == 18
    assert 'PRIVATE WITHHELD' not in json.dumps(first)
    for basin in first['basins']:
        design = basin['full_vector_design']
        assert len(design['points']) == 15
        assert design['quality']['affine_rank'] == 3 and design['quality']['rbf_ready']
        assert all(set(p) == set(basin['bounds']) for p in design['points'])
        assert len(set(basin['bridge_preflight']['applied_input_sha256'])) == 15
    assert {str(p): p.read_bytes() for p in pe1.rglob('*') if p.is_file()} == originals


def test_explicit_registry_supplement_only_for_skipped_default_endpoint():
    bounds, evidence = preflight.screened_bounds({'parameters': [row('EPCO', {'lower': .01})]})
    assert bounds['EPCO'] == (.01, 1.)
    assert evidence['EPCO']['registry_default_endpoint_supplement'] == {'upper': 1.}
    with pytest.raises(ValueError, match='not a default endpoint'):
        preflight.screened_bounds({'parameters': [row('ESCO', {'lower': .01})]})


def test_screen_malformed_missing_and_registry_mismatch_rejected():
    for payload in ({}, {'parameters': []}, {'parameters': [row('ESCO', {})]}):
        with pytest.raises(ValueError):
            preflight.screened_bounds(payload)
    with pytest.raises(ValueError, match='disagrees'):
        preflight.screened_bounds({'parameters': [row('ESCO', {'lower': .02, 'upper': 1.})]})
    with pytest.raises(ValueError, match='Duplicate'):
        preflight.screened_bounds({'parameters': [row('ESCO', {'lower': .01, 'upper': 1.})] * 2})


def test_missing_model_or_bridge_target_fails_before_output(retained_inputs):
    pe1, engine = retained_inputs
    target = pe1 / 'usgs_12054000/calibration/locked_calibrated_TxtInOut/hydrology.hyd'
    target.unlink()
    with pytest.raises(Exception, match='Required file missing'):
        preflight.prepare_preflight(pe1, engine)
    with pytest.raises(ValueError, match='Engine binary'):
        preflight.prepare_preflight(pe1, engine.with_name('missing'))


def test_incomplete_design_never_filled_with_defaults(monkeypatch, retained_inputs):
    pe1, engine = retained_inputs
    good = preflight.make_shared_design
    def incomplete(*args, **kwargs):
        design = good(*args, **kwargs)
        return SimpleNamespace(points=[{'PET_CO': 1.}], quality=design.quality)
    monkeypatch.setattr(preflight, 'make_shared_design', incomplete)
    with pytest.raises(ValueError, match='Incomplete full-vector'):
        preflight.prepare_preflight(pe1, engine)


def test_cli_no_overwrite_or_historical_output(monkeypatch, retained_inputs, tmp_path):
    import sys
    pe1, engine = retained_inputs
    old = tmp_path / 'existing.json'
    old.write_text('preserve me')
    for out in (old, pe1 / 'unsafe.json'):
        monkeypatch.setattr(sys, 'argv', ['preflight', '--pe1-root', str(pe1), '--binary', str(engine), '--out', str(out)])
        with pytest.raises(ValueError, match='overwrite prohibited'):
            preflight.main()
    assert old.read_text() == 'preserve me'
    out = tmp_path / 'new.json'
    monkeypatch.setattr(sys, 'argv', ['preflight', '--pe1-root', str(pe1), '--binary', str(engine), '--out', str(out)])
    preflight.main()
    assert json.loads(out.read_text())['status'] == 'prepared_not_executed'
