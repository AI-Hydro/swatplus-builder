"""Run a sealed warm-development full-vector integration comparison.

15 shared design requests, one adaptive request and one fresh training rerun
per arm. The eighteenth attributed slot is protected for validation and unused.
Historical locks supply observation/outlet identity, not warm-input equivalence.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import platform
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

import swatplus_builder
from swatplus_builder.calibration.development_comparison import run_development_comparison
from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
from swatplus_builder.calibration.experiment_design import assess_design
from swatplus_builder.calibration.objective_policy import ObjectivePolicy
from swatplus_builder.calibration.policy_engine import ExactOutputPolicyAdapter
from swatplus_builder.calibration.real_engine import (
    _copy_fresh_txtinout,
    _staged_input_identity,
    load_observed_from_alignment_csv,
    make_real_objective,
)
from swatplus_builder.calibration.surrogate_optimizer import ConstrainedGPOptimizer

# Import the neighboring preparer without relying on the CLI's sys.path.
_spec = importlib.util.spec_from_file_location('_fullvector_preparer', Path(__file__).with_name('calibration_fullvector_preflight.py'))
_preparer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_preparer)
file_sha = _preparer.file_sha
DATES = {'simulation_start': '2007-01-01', 'simulation_end': '2015-12-31',
         'score_start': '2010-01-01', 'score_end': '2015-12-31'}


def package_hashes() -> dict[str, str]:
    root = Path(swatplus_builder.__file__).resolve().parent
    return {str(p.relative_to(root)): file_sha(p) for p in sorted(root.rglob('*.py'))}


def verify_plan(preflight: Path, gauge: str, out: Path, binary: Path | None = None) -> dict[str, Any]:
    """Fail closed before dependencies, output directories, or engine callbacks."""
    preflight, out = preflight.resolve(), out.resolve()
    plan = json.loads(preflight.read_text())
    if (plan.get('schema') != 'calibration_fullvector_preflight_v1'
            or plan.get('status') != 'prepared_not_executed'
            or plan.get('engine_calls') != 0
            or plan.get('contains_validation_observation_values') is not False):
        raise ValueError('Plan must be a prepared, unexecuted development preflight')
    expected = {'total_cap': 18, 'screen': 0, 'design': 15, 'search': 1,
                'final_training': 1, 'validation': 1}
    if any(type(plan.get('budget_per_arm', {}).get(k)) is not int
           or plan['budget_per_arm'][k] != v for k, v in expected.items()):
        raise ValueError('Incorrect sealed 18-request accounting')
    rows = [b for b in plan['basins'] if b.get('gauge') == gauge]
    if len(rows) != 1 or gauge not in _preparer.BASINS:
        raise ValueError('Gauge missing or duplicated in sealed plan')
    for b in plan['basins']:
        historical = Path(b['source']).resolve().parents[1]
        if out.is_relative_to(historical):
            raise ValueError('Output must be outside historical evidence')
    if out.exists():
        raise ValueError('Output overwrite or automatic resume prohibited')
    basin = rows[0]
    source = Path(basin['source']).resolve()
    if not source.is_dir() or _staged_input_identity(source) != basin['source_input_sha256']:
        raise ValueError('Source input hash mismatch or missing source')
    for path_key, sha_key in [('screen_path', 'screen_sha256'),
                              ('benchmark_lock_path', 'benchmark_lock_sha256'),
                              ('benchmark_alignment_path', 'benchmark_alignment_sha256')]:
        p = Path(basin[path_key])
        if not p.is_file() or file_sha(p) != basin[sha_key]:
            raise ValueError(f'Missing or tampered artifact: {path_key}')
    lock = json.loads(Path(basin['benchmark_lock_path']).read_text())
    screen = json.loads(Path(basin['screen_path']).read_text())
    if lock.get('basin_id') != f'usgs_{gauge}' or lock.get('alignment_sha256') != basin['benchmark_alignment_sha256']:
        raise ValueError('Lock alignment/gauge mismatch')
    bounds, provenance = _preparer.screened_bounds(screen)
    if ({k: list(v) for k, v in bounds.items()} != basin['bounds']
            or provenance != basin['bound_provenance']):
        raise ValueError('Screen bounds/provenance mismatch')
    if (type(lock.get('outlet_gis_id')) is not int or lock['outlet_gis_id'] <= 0
            or lock.get('outlet_policy') not in {'strict', 'all_terminal_sum'}
            or not isinstance(lock.get('sim_source_file'), str)):
        raise ValueError('Missing explicit historical outlet/file identity')
    points = basin['full_vector_design']['points']
    if len(points) != 15 or any(set(p) != set(bounds) for p in points):
        raise ValueError('Incomplete 15-point full-vector design')
    quality = assess_design(bounds, points, required_backend='rbf')
    if not quality.rbf_ready or quality.to_json() != basin['full_vector_design']['quality']:
        raise ValueError('Sealed design quality mismatch')
    if type(plan['seed']) is not int or basin['full_vector_design']['seed'] != plan['seed']:
        raise ValueError('Seed identity mismatch')
    engine = (binary or Path(plan['engine']['path'])).resolve()
    if not engine.is_file() or file_sha(engine) != plan['engine']['sha256']:
        raise ValueError('Missing or tampered engine identity')
    codes = {'experiment_design': 'swatplus_builder.calibration.experiment_design',
             'parameter_bridge': 'swatplus_builder.full_mode.parameter_bridge',
             'parameter_registry': 'swatplus_builder.params.registry'}
    current = {k: file_sha(Path(importlib.import_module(v).__file__)) for k, v in codes.items()}
    current['preflight_script'] = file_sha(Path(_preparer.__file__))
    if current != plan['code_sha256']:
        raise ValueError('Preparation source code hash mismatch')
    return {'plan': plan, 'basin': basin, 'lock': lock, 'binary': engine,
            'preflight_sha256': file_sha(preflight), 'package_sha256': package_hashes()}


def finite_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): finite_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [finite_json(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.pending', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(finite_json(payload), stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp).replace(path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run_trial(preflight: Path, gauge: str, out: Path, binary: Path | None = None) -> dict:
    sealed = verify_plan(preflight, gauge, out, binary)
    b, lock = sealed['basin'], sealed['lock']
    obs = load_observed_from_alignment_csv(b['benchmark_alignment_path']).loc[DATES['score_start']:DATES['score_end']]
    policy = ObjectivePolicy.fit(obs.to_numpy(), weights={'kge': 1.0})
    adapter = ExactOutputPolicyAdapter.bind(policy, obs)
    ConstrainedGPOptimizer.check_dependencies()  # Before output or charged requests.
    context = {'scope': 'warm_development_only_no_historical_input_lock_equivalence',
               'source_input_sha256': b['source_input_sha256'], 'engine_sha256': sealed['plan']['engine']['sha256'],
               'preflight_sha256': sealed['preflight_sha256'], 'trial_script_sha256': file_sha(Path(__file__)),
               'package_sha256': sealed['package_sha256'], 'adapter_sha256': adapter.sha256,
               'objective_policy_sha256': policy.sha256, 'dates': DATES,
               'screen_sha256': b['screen_sha256'], 'lock_sha256': b['benchmark_lock_sha256'],
               'alignment_sha256': b['benchmark_alignment_sha256'], 'gauge': gauge,
               'budget_per_arm': sealed['plan']['budget_per_arm'],
               'engine_threads': 1, 'engine_timeout_s': 300,
               'runtime_versions': {name: version(name) for name in ('numpy', 'pandas', 'torch', 'botorch', 'gpytorch')},
               'platform': platform.platform(), 'python': sys.version}
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'running', 'context': context, 'contains_validation_scores': False,
                'historical_lock_input_equivalence_claimed': False,
                'interpretation': 'Development integration test; one adaptive request per arm cannot establish convergence or superiority.',
                'source_issue': b.get('source_issue')}
    budgets = {}
    try:
        snapshot = out / 'input_snapshot/TxtInOut'
        _copy_fresh_txtinout(Path(b['source']), snapshot)
        if _staged_input_identity(snapshot) != b['source_input_sha256']:
            raise ValueError('Snapshot differs from sealed source')
        budgets = {arm: EvaluationBudget(out / f'{arm}_budget.jsonl', total_cap=18,
                   context={**context, 'arm': arm}, planned_design=15,
                   final_training_reserve=1, validation_reserve=1) for arm in ('dds', 'gp')}
        write_json(out / 'manifest.json', manifest)
        def evaluate(point, label, stage, arm, budget):
            objective = make_real_objective(
                base_txtinout=snapshot, observed_series=obs, work_root=out / 'evaluations' / label,
                outlet_gis_id=lock['outlet_gis_id'], binary=sealed['binary'], threads=1, timeout_s=300,
                objective_sim_file=lock['sim_source_file'], strict_objective_file=True,
                objective_outlet_policy=lock['outlet_policy'], parameter_mode='full',
                keep_workdirs=True, force_fresh=True, include_physical_gate=True, nyskip_years=0,
                telemetry_dir=out / 'invocations', objective_policy=adapter,
                evaluation_budget=budget, budget_stage=stage, **DATES)
            return objective(dict(point))
        result = run_development_comparison(evaluate, b['bounds'], b['full_vector_design']['points'],
                    budgets=budgets, search_budget=1, seed=sealed['plan']['seed'],
                    checkpoint=lambda data: write_json(out / 'checkpoint.json', data))
        write_json(out / 'result.json', result)
        manifest['status'] = result['status']
        return result
    except BaseException as error:
        manifest.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        already_failing = sys.exc_info()[0] is not None
        try:
            unchanged = (_staged_input_identity(Path(b['source'])) == b['source_input_sha256']
                         and file_sha(preflight) == sealed['preflight_sha256']
                         and file_sha(sealed['binary']) == sealed['plan']['engine']['sha256']
                         and package_hashes() == sealed['package_sha256']
                         and file_sha(Path(__file__)) == context['trial_script_sha256'])
            for path_key, hash_key in [('screen_path','screen_sha256'), ('benchmark_lock_path','benchmark_lock_sha256'),
                                       ('benchmark_alignment_path','benchmark_alignment_sha256')]:
                unchanged = unchanged and file_sha(Path(b[path_key])) == b[hash_key]
        except Exception as verification_error:
            unchanged = False
            manifest['unchanged_verification_error'] = str(verification_error)
        manifest['source_and_code_unchanged'] = unchanged
        manifest['budgets'] = {arm: budget.snapshot() for arm, budget in budgets.items()}
        if not unchanged:
            manifest['status'] = 'invalidated_source_changed'
        write_json(out / 'manifest.json', manifest)
        if not unchanged and not already_failing:
            raise RuntimeError('Trial invalidated: sealed source or code changed; manifest retained')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--gauge', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--binary', type=Path)
    args = parser.parse_args()
    run_trial(args.preflight.expanduser().resolve(), args.gauge,
              args.out.expanduser().resolve(), args.binary)
    print(str(args.out.resolve()))


if __name__ == '__main__':
    main()
