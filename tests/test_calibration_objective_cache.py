"""Cache semantics and invocation accounting without launching SWAT+."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.calibration import real_engine


@pytest.fixture
def objective_factory(monkeypatch, tmp_path):
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'model.hyd').write_text('static model version 1')
    calls = []
    guard = threading.Lock()

    def run(*args, **kwargs):
        with guard:
            calls.append(args[0])
        time.sleep(0.015)

    def evaluate(path, obs, **kwargs):
        return pd.DataFrame(), {'nse': float(obs.iloc[0]) / 10, 'kge': .5, 'pbias': 1.}, {
            'sim_source_file': path.name,
            'outlet_autodetected': False,
        }

    monkeypatch.setattr(real_engine, 'run_swat', run)
    monkeypatch.setattr(real_engine, 'evaluate_run', evaluate)
    monkeypatch.setattr(real_engine, '_prepare_full_mode_txtinout_for_objective', lambda *a, **k: None)
    monkeypatch.setattr(real_engine, '_prepare_txtinout_for_objective', lambda *a, **k: None)
    monkeypatch.setattr(real_engine, '_apply_parameters_for_mode', lambda *a, **k: None)
    monkeypatch.setattr(real_engine, '_candidate_physical_gate', lambda *a, **k: {
        'pass': True, 'calibration_process_gate_pass': True,
    })

    def factory(**kwargs):
        options = dict(
            base_txtinout=base,
            observed_series=pd.Series([1., 2.], index=pd.to_datetime(['2010-01-01', '2010-01-02'])),
            work_root=tmp_path / 'cache',
            nyskip_years=0,
            keep_workdirs=False,
            reuse_compact_traces=True,
            trace_context_sha256='same sealed caller context',
            telemetry_dir=tmp_path / 'telemetry',
        )
        options.update(kwargs)
        return real_engine.make_real_objective(**options)
    return factory, calls, base


def test_observation_and_static_changes_invalidate_same_caller_context(objective_factory):
    factory, calls, base = objective_factory
    first = factory()
    assert first({})['nse'] == .1
    assert factory()({})['nse'] == .1
    assert len(calls) == 1
    assert factory(observed_series=pd.Series([3., 2.], index=pd.to_datetime(['2010-01-01', '2010-01-02'])))({})['nse'] == .3
    assert len(calls) == 2
    (base / 'model.hyd').write_text('static model version 2')
    factory()({})
    assert len(calls) == 3


@pytest.mark.parametrize('filename', ['metrics.py', 'eval.py', 'water_balance_gate.py', 'registry.py', 'governance.py', 'reader.py'])
def test_dependency_edit_invalidates_cache_without_builder_version_change(monkeypatch, objective_factory, filename):
    factory, calls, _ = objective_factory
    factory()({})
    original = Path.read_bytes

    def altered(path):
        contents = original(path)
        return contents + b'\n# semantic change\n' if path.name == filename else contents
    monkeypatch.setattr(Path, 'read_bytes', altered)
    factory()({})
    assert len(calls) == 2


def test_single_flight_across_factories_and_telemetry(objective_factory, tmp_path):
    factory, calls, _ = objective_factory
    objectives = [factory(), factory()]
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda i: objectives[i % 2]({'CN2': 55.}), range(6)))
    assert len(calls) == 1
    assert results == [results[0]] * 6
    records = [json.loads(p.read_text()) for p in (tmp_path / 'telemetry').glob('*.json')]
    assert len(records) == 6
    assert sum(r['engine_invoked'] for r in records) == 1
    assert sum(r['cache_status'] == 'compact_hit' for r in records) == 5
    assert all(r['status'] == 'completed' for r in records)
    assert all(r['total_seconds'] >= r['stage_seconds']['lock_wait'] >= 0 for r in records)
    miss = next(r for r in records if r['engine_invoked'])
    assert {'staging', 'parameter_preparation', 'engine_and_receipt', 'evaluation', 'trace_publication', 'cleanup'} <= miss['stage_seconds'].keys()
    assert not list((tmp_path / 'cache').glob('.*.tmp'))


def test_failure_is_recorded_and_never_cached(monkeypatch, objective_factory, tmp_path):
    factory, _, _ = objective_factory
    def fail(*args, **kwargs):
        raise RuntimeError('solver failed')
    monkeypatch.setattr(real_engine, 'run_swat', fail)
    obj = factory()
    for _ in range(2):
        with pytest.raises(RuntimeError, match='solver failed'):
            obj({})
    records = [json.loads(p.read_text()) for p in (tmp_path / 'telemetry').glob('*.json')]
    assert len(records) == 2
    assert all(r['status'] == 'failed' and r['engine_invoked'] for r in records)
    assert all(r['error'] == 'RuntimeError: solver failed' for r in records)
    assert all('engine_and_receipt' in r['stage_seconds'] and 'cleanup' in r['stage_seconds'] for r in records)
    assert not list((tmp_path / 'cache').glob('*trace.json'))


def test_force_fresh_still_invokes_engine_on_every_call(objective_factory):
    factory, calls, _ = objective_factory
    obj = factory(reuse_compact_traces=False, force_fresh=True, keep_workdirs=True)
    obj({})
    obj({})
    assert len(calls) == 2


def test_sealed_nonfinite_required_metrics_not_reused(objective_factory, tmp_path):
    factory, calls, _ = objective_factory
    obj = factory()
    obj({})
    path = next((tmp_path / 'cache').glob('*trace.json'))
    data = json.loads(path.read_text())
    data['metrics']['nse'] = float('nan')
    data['payload_sha256'] = real_engine._objective_trace_payload_sha256(data)
    path.write_text(json.dumps(data))
    assert obj({})['nse'] == .1
    assert len(calls) == 2


def test_telemetry_is_optional(objective_factory, tmp_path):
    factory, _, _ = objective_factory
    factory(telemetry_dir=None)({})
    assert not (tmp_path / 'telemetry').exists()


def test_generated_outputs_do_not_invalidate_staged_input_identity(objective_factory):
    factory, calls, base = objective_factory
    factory()({})
    for filename in ('channel_sd_day.txt', 'basin_wb_aa.txt', 'diagnostics.out', 'engine_run_receipt.json', 'alignment_old.csv'):
        (base / filename).write_text('new generated output')
    factory()({})
    assert len(calls) == 1


def test_scored_date_identity_invalidates_cache(objective_factory):
    factory, calls, _ = objective_factory
    factory()({})
    factory(observed_series=pd.Series([1., 2.], index=pd.to_datetime(['2011-01-01', '2011-01-02'])))({})
    assert len(calls) == 2


def test_physical_gate_requirement_invalidates_metric_only_cache(objective_factory):
    factory, calls, _ = objective_factory
    factory()({})
    result = factory(include_physical_gate=True)({})
    assert len(calls) == 2
    assert result['physical_gate_passed'] == 1.


def test_distinct_parameter_points_are_not_serialized(monkeypatch, objective_factory):
    factory, _, _ = objective_factory
    obj = factory()
    barrier = threading.Barrier(2)
    def run(*args, **kwargs):
        barrier.wait(timeout=3)
    monkeypatch.setattr(real_engine, 'run_swat', run)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(obj, [{'CN2': 45.}, {'CN2': 65.}]))
    assert len(results) == 2
