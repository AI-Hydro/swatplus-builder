"""The live CLI must fail closed before dependencies, output or callbacks."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/research/calibration_fullvector_trial.py'
spec = importlib.util.spec_from_file_location('fullvector_trial_test', SCRIPT)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


@pytest.fixture
def sealed(tmp_path):
    pe1, engine = tmp_path / 'pe1', tmp_path / 'engine'
    engine.write_bytes(b'identity only; never executed')
    for gauge in trial._preparer.BASINS:
        root = pe1 / f'usgs_{gauge}'
        source = root / 'calibration/locked_calibrated_TxtInOut'
        source.mkdir(parents=True)
        (source / 'hydrology.hyd').write_text('hydrology\nname esco pet_co\nhru1 .95 1\n')
        bench = root / 'benchmark'
        bench.mkdir()
        alignment = bench / 'alignment.csv'
        alignment.write_text('date,obs,sim\n2010-01-01,1,1\n2010-01-02,2,1\n2010-01-03,3,2\n2019-01-01,99999,0\n')
        (bench / 'benchmark_lock.json').write_text(json.dumps({
            'basin_id': f'usgs_{gauge}', 'alignment_sha256': trial.file_sha(alignment),
            'outlet_gis_id': 1, 'outlet_policy': 'strict', 'sim_source_file': 'channel_sd_day.txt'}))
        screen = root / 'calibration/sensitivity_screen_locked/sensitivity_screen.json'
        screen.parent.mkdir()
        screen.write_text(json.dumps({'basin_id': f'usgs_{gauge}', 'basis': 'basin_specific',
            'parameters': [{'parameter': name, 'activity_class': 'active', 'evidence': {'bound_results':
                [{'bound': 'lower', 'value': lo}, {'bound': 'upper', 'value': hi}]}}
                for name, lo, hi in [('ESCO', .01, 1.), ('PET_CO', .8, 1.2)]]}))
    plan = trial._preparer.prepare_preflight(pe1, engine)
    preflight = tmp_path / 'preflight.json'
    preflight.write_text(json.dumps(plan))
    return preflight, plan, tmp_path / 'trial'


def test_sealed_valid_plan_has_no_output_or_engine(sealed):
    path, plan, out = sealed
    verified = trial.verify_plan(path, '12054000', out)
    assert verified['basin']['gauge'] == '12054000'
    assert verified['preflight_sha256'] == trial.file_sha(path)
    assert verified['package_sha256']
    assert not out.exists()


@pytest.mark.parametrize('kind', ['source', 'screen_path', 'benchmark_lock_path', 'benchmark_alignment_path', 'engine'])
@pytest.mark.parametrize('missing', [False, True])
def test_tampered_and_missing_artifacts_fail_before_dependencies(sealed, monkeypatch, kind, missing):
    path, plan, out = sealed
    b = plan['basins'][0]
    target = (Path(b['source']) / 'hydrology.hyd' if kind == 'source' else
              Path(plan['engine']['path']) if kind == 'engine' else Path(b[kind]))
    if missing:
        target.unlink()
    else:
        target.write_text('tampered')
    dependencies = []
    monkeypatch.setattr(trial.ConstrainedGPOptimizer, 'check_dependencies', lambda: dependencies.append(1))
    with pytest.raises(ValueError):
        trial.run_trial(path, '12054000', out)
    assert dependencies == [] and not out.exists()


@pytest.mark.parametrize('mutation', ['status', 'cap', 'vector', 'code', 'seed'])
def test_invalid_plan_structure_fail_closed(sealed, mutation):
    path, plan, out = sealed
    if mutation == 'status': plan['status'] = 'completed'
    if mutation == 'cap': plan['budget_per_arm']['total_cap'] = 18.0
    if mutation == 'vector': del plan['basins'][0]['full_vector_design']['points'][0]['ESCO']
    if mutation == 'code': plan['code_sha256']['parameter_bridge'] = 'bad'
    if mutation == 'seed': plan['basins'][0]['full_vector_design']['seed'] += 1
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError): trial.verify_plan(path, '12054000', out)
    assert not out.exists()


def test_overwrite_historical_and_unknown_gauge_rejected(sealed):
    path, plan, out = sealed
    out.mkdir()
    with pytest.raises(ValueError, match='overwrite'): trial.verify_plan(path, '12054000', out)
    unsafe = Path(plan['basins'][0]['source']).parents[1] / 'unsafe'
    with pytest.raises(ValueError, match='historical'): trial.verify_plan(path, '12054000', unsafe)
    with pytest.raises(ValueError, match='Gauge'): trial.verify_plan(path, 'unknown', out)


@pytest.mark.parametrize("mutate_source", [False, True])
def test_mocked_trial_binds_training_only_fresh_adapter_and_ledgers(sealed, monkeypatch, mutate_source):
    path, plan, out = sealed
    captured = []
    monkeypatch.setattr(trial, "version", lambda name: "mock-version")
    monkeypatch.setattr(trial.ConstrainedGPOptimizer, 'check_dependencies', lambda: None)
    def factory(**kwargs):
        captured.append(kwargs)
        def evaluate(point):
            token = kwargs['evaluation_budget'].reserve(kwargs['budget_stage'])
            kwargs['evaluation_budget'].finish(token, status='completed', cache_hit=False, engine_invoked=True)
            return {'policy_status': 'valid', 'policy_utility': .5, 'nse': .4, 'kge': .5, 'pbias': 0}
        return evaluate
    monkeypatch.setattr(trial, 'make_real_objective', factory)
    def runner(evaluate, bounds, points, *, budgets, search_budget, seed, checkpoint):
        assert search_budget == 1 and len(points) == 15
        evaluate(points[0], 'shared_0', 'design', 'dds', budgets['dds'])
        checkpoint({'status': 'mocked', 'unavailable': float('nan')})
        if mutate_source:
            (Path(plan['basins'][0]['source']) / 'hydrology.hyd').write_text('changed during run')
        return {'status': 'completed', 'test_only': True}
    monkeypatch.setattr(trial, 'run_development_comparison', runner)
    if mutate_source:
        with pytest.raises(RuntimeError, match='invalidated'):
            trial.run_trial(path, '12054000', out)
    else:
        trial.run_trial(path, '12054000', out)
    kw = captured[0]
    assert kw['observed_series'].index.max().year == 2010
    assert kw['observed_series'].max() == 3
    assert kw['force_fresh'] and kw['keep_workdirs'] and kw['include_physical_gate']
    assert kw['nyskip_years'] == 0 and kw['simulation_end'] == '2015-12-31'
    assert kw['parameter_mode'] == 'full' and kw['timeout_s'] == 300 and kw['threads'] == 1
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['source_and_code_unchanged'] == (not mutate_source)
    assert not manifest['contains_validation_scores']
    assert manifest['context']['engine_timeout_s'] == 300
    assert manifest['context']['runtime_versions']['botorch'] == 'mock-version'
    if mutate_source:
        assert manifest['status'] == 'invalidated_source_changed'
    assert manifest['budgets']['dds']['charged_requests'] == 1
    assert manifest['budgets']['dds']['remaining_validation'] == 1
    assert manifest['budgets']['gp']['charged_requests'] == 0
    assert json.loads((out / 'checkpoint.json').read_text())['unavailable'] is None
    assert '99999' not in (out / 'manifest.json').read_text()
