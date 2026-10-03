"""Live integration check: exact-output scoring, cache charging and reserved final.

Development-only retained inputs; no optimization, temporal validation or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import swatplus_builder
from swatplus_builder.calibration.evaluation_budget import BudgetExhaustedError, EvaluationBudget
from swatplus_builder.calibration.objective_policy import ObjectivePolicy
from swatplus_builder.calibration.policy_engine import ExactOutputPolicyAdapter
from swatplus_builder.calibration.real_engine import (
    _copy_fresh_txtinout,
    _staged_input_identity,
    load_observed_from_alignment_csv,
    make_real_objective,
)
from swatplus_builder.run.swatplus import locate_binary


def save(path, payload):
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def run(basin: Path, out: Path):
    basin, out = basin.resolve(), out.resolve()
    if out.exists() or out.is_relative_to(basin):
        raise ValueError('Use a new output directory outside historical evidence')
    base = basin / 'calibration/locked_calibrated_TxtInOut'
    before = _staged_input_identity(base)
    alignment = basin / 'benchmark/alignment.csv'
    lock_path = basin / 'benchmark/benchmark_lock.json'
    lock = json.loads(lock_path.read_text())
    alignment_hash = hashlib.sha256(alignment.read_bytes()).hexdigest()
    if alignment_hash != lock['alignment_sha256']:
        raise ValueError('Observation alignment differs from historical lock')
    obs = load_observed_from_alignment_csv(alignment).loc['2010-01-01':'2015-12-31']
    adapter = ExactOutputPolicyAdapter.bind(ObjectivePolicy.fit(obs.tolist(), weights={'kge': 1.0}), obs)
    binary = locate_binary()
    package = Path(swatplus_builder.__file__).resolve().parent
    context = {
        'source_input_sha256': before, 'alignment_sha256': alignment_hash,
        'lock_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        'engine_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'adapter_sha256': adapter.sha256, 'threads': 1,
        'simulation_dates': ['2007-01-01', '2015-12-31'],
        'score_dates': ['2010-01-01', '2015-12-31'],
        'package_sources': {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(package.rglob('*.py'))},
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    out.mkdir(parents=True)
    snapshot = out / 'input_snapshot/TxtInOut'
    snapshot.parent.mkdir()
    _copy_fresh_txtinout(base, snapshot)
    if _staged_input_identity(snapshot) != before:
        raise ValueError('Copied input identity mismatch')
    ledger = EvaluationBudget(out / 'budget.jsonl', total_cap=4, context=context,
                              planned_design=1, final_training_reserve=1, validation_reserve=1)
    manifest = {'purpose': 'development integration check, not optimizer evidence',
                'context': context, 'status': 'running', 'validation_scored': False}
    save(out / 'manifest.json', manifest)
    options = dict(base_txtinout=snapshot, observed_series=obs,
                   outlet_gis_id=lock['outlet_gis_id'], binary=binary, threads=1, timeout_s=300,
                   objective_sim_file=lock['sim_source_file'], strict_objective_file=True,
                   objective_outlet_policy=lock['outlet_policy'], parameter_mode='full',
                   keep_workdirs=True, include_physical_gate=True, nyskip_years=0,
                   simulation_start='2007-01-01', simulation_end='2015-12-31',
                   score_start='2010-01-01', score_end='2015-12-31',
                   objective_policy=adapter, evaluation_budget=ledger,
                   telemetry_dir=out / 'invocations')
    try:
        first = make_real_objective(**options, work_root=out / 'shared', budget_stage='design')({})
        replay = make_real_objective(**options, work_root=out / 'shared', budget_stage='search')({})
        try:
            ledger.reserve('search')
        except BudgetExhaustedError:
            pass
        else:
            raise AssertionError('Discretionary search consumed protected reserve')
        fresh = make_real_objective(**options, work_root=out / 'fresh',
                                    budget_stage='final_training', force_fresh=True)({})
        for result in (first, replay, fresh):
            assert result['policy_status'] == 'valid', result['policy_evidence']
            assert math.isfinite(result['policy_utility'])
            assert result['policy_utility'] == result['kge']
        for metric in ('nse', 'kge', 'pbias', 'policy_utility'):
            assert first[metric] == replay[metric]
            assert math.isclose(first[metric], fresh[metric], rel_tol=1e-10, abs_tol=1e-10)
        records = [json.loads(p.read_text()) for p in (out / 'invocations').glob('*.json')]
        assert len(records) == 3
        assert sum(bool(r['engine_invoked']) for r in records) == 2
        assert sum(r['cache_status'] == 'workdir_hit' for r in records) == 1
        state = ledger.snapshot()
        assert state['charged_requests'] == 3
        assert state['remaining_validation'] == 1
        assert state['remaining_discretionary'] == 0
        manifest.update(status='passed', first=first, replay=replay, fresh=fresh,
                        budget=state, engine_wrapper_calls=2, cache_hits=1)
    except BaseException as error:
        manifest.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        manifest['historical_source_unchanged'] = _staged_input_identity(base) == before
        save(out / 'manifest.json', manifest)
        if not manifest['historical_source_unchanged']:
            raise RuntimeError('Historical source changed')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basin-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.basin_root, args.out)
    print(json.dumps({k: result[k] for k in ('status', 'budget', 'historical_source_unchanged')}, indent=2))
