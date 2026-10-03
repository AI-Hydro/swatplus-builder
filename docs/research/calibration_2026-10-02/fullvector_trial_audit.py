"""Read-only artifact audit; invoke with PYTHONPATH pointing to the frozen package.

Only the optional audit JSON output is written. No engine or optimizer is run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import swatplus_builder
from swatplus_builder.calibration.development_comparison import measured_policy_observation
from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
from swatplus_builder.calibration.experiment_design import assess_design
from swatplus_builder.calibration.objective_policy import ObjectivePolicy
from swatplus_builder.calibration.policy_engine import (
    ExactOutputPolicyAdapter,
    calibration_process_proxy,
)
from swatplus_builder.calibration.real_engine import (
    _candidate_physical_gate,
    _staged_input_identity,
    load_observed_from_alignment_csv,
)
from swatplus_builder.evidence.integrity import input_configuration_fingerprint
from swatplus_builder.output.eval import evaluate_run


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(run: Path, frozen: Path, preflight: Path):
    run, frozen, preflight = run.resolve(), frozen.resolve(), preflight.resolve()
    assert Path(swatplus_builder.__file__).resolve().parent == frozen / 'src/swatplus_builder'
    manifest = json.loads((run / 'manifest.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    plan = json.loads(preflight.read_text())
    context = manifest['context']
    checks = []
    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    check('completed_manifest_and_result', manifest['status'] == result['status'] == 'completed')
    check('source_unchanged_report', manifest['source_and_code_unchanged'] is True)
    check('no_validation', manifest['contains_validation_scores'] is False and result['validation_used'] is False)
    source_seals = json.loads((frozen / 'source_manifest.json').read_text())
    for path, digest in source_seals.items():
        check('frozen_source:' + path, sha(frozen / path) == digest)
    for path, digest in context['package_sha256'].items():
        check('executed_package:' + path, sha(frozen / 'src/swatplus_builder' / path) == digest)
    check('trial_script_context', sha(frozen / 'calibration_fullvector_trial.py') == context['trial_script_sha256'])
    check('preflight_context', sha(preflight) == context['preflight_sha256'])
    basin = next(b for b in plan['basins'] if b['gauge'] == context['gauge'])
    for path, digest in [('screen_path', 'screen_sha256'), ('benchmark_lock_path', 'benchmark_lock_sha256'),
                         ('benchmark_alignment_path', 'benchmark_alignment_sha256')]:
        check('historical_artifact:' + path, sha(basin[path]) == basin[digest] == context[digest.removeprefix('benchmark_')])
    check('historical_static_seal', _staged_input_identity(Path(basin['source'])) == context['source_input_sha256'])
    check('input_snapshot_seal', _staged_input_identity(run / 'input_snapshot/TxtInOut') == context['source_input_sha256'])
    check('engine_current_seal', sha(plan['engine']['path']) == context['engine_sha256'])
    lock = json.loads(Path(basin['benchmark_lock_path']).read_text())
    obs = load_observed_from_alignment_csv(basin['benchmark_alignment_path']).loc['2010-01-01':'2015-12-31']
    adapter = ExactOutputPolicyAdapter.bind(ObjectivePolicy.fit(obs.tolist(), weights={'kge': 1.}), obs)
    check('adapter_identity', adapter.sha256 == context['adapter_sha256'])
    check('objective_identity', adapter.policy.sha256 == context['objective_policy_sha256'])
    ledgers = {}
    for arm in ('dds', 'gp'):
        path = run / f'{arm}_budget.jsonl'
        original = path.read_bytes()
        ledger = EvaluationBudget(path, total_cap=18, context={**context, 'arm': arm},
                                  planned_design=15, final_training_reserve=1, validation_reserve=1)
        state = ledger.snapshot()
        check('ledger_bytes_unchanged:' + arm, path.read_bytes() == original)
        check('ledger_manifest_result:' + arm, state == manifest['budgets'][arm] == result['budgets'][arm])
        check('ledger_stage_counts:' + arm, state['used_by_stage']['design'] == 15 and state['used_by_stage']['search'] == 1
              and state['remaining_validation'] == 1 and state['used_by_stage']['validation'] == 0
              and not state['pending_reservations'])
        ledgers[arm] = state
        events = [json.loads(line) for line in original.splitlines()]
        if arm == 'gp':
            reused = [e for e in events if e['kind'] == 'finish' and e['cache_hit']]
            check('15_virtual_design_attributions', len(reused) == 15 and all(not e['engine_invoked'] for e in reused))
    calls = result['physical_calls']
    telemetry = [json.loads(p.read_text()) for p in (run / 'invocations').glob('*.json')]
    check('physical_callback_cap', len(calls) == result['actual_physical_callbacks'] <= 19)
    check('attributed_request_cap', sum(s['charged_requests'] for s in ledgers.values()) == result['attributed_requests'] <= 34)
    check('one_telemetry_per_callback', len(calls) == len(telemetry))
    check('physical_vs_ledger_wrapper_counts', sum(bool(t['engine_invoked']) for t in telemetry) == sum(s['engine_wrapper_calls'] for s in ledgers.values()))
    check('no_actual_cache_reuse', all(t['cache_status'] != 'workdir_hit' for t in telemetry))
    recomputed = {}
    receipts = []
    for call in calls:
        label = call['evaluation_id']
        observation = measured_policy_observation(label, call.get('metrics', {}))
        check('typed_status:' + label, call['status'] == observation.status)
        check('typed_utility:' + label, call.get('utility') == observation.utility)
        if observation.status != 'success':
            continue
        metrics = call['metrics']
        txt = next((run / 'evaluations' / label).glob('*/TxtInOut'))
        evidence = metrics['policy_evidence']
        source = txt / evidence['provenance']['source_file']
        receipt_path = txt / 'engine_run_receipt.json'
        receipt = json.loads(receipt_path.read_text())
        check('receipt_engine:' + label, receipt['engine']['sha256'] == context['engine_sha256'])
        check('receipt_execution:' + label, receipt['execution']['threads'] == 1 and receipt['execution']['timeout_s'] == 300)
        check('receipt_input:' + label, input_configuration_fingerprint(txt)[0] == receipt['input_configuration_sha256'])
        for name, digest in receipt['files'].items():
            check('receipt_output:' + label + ':' + name, sha(txt / name) == digest)
        frame, raw_metrics, _ = evaluate_run(source, obs, outlet_gis_id=lock['outlet_gis_id'],
                                             outlet_policy=lock['outlet_policy'], return_diagnostics=True)
        gate = _candidate_physical_gate(txt, raw_metrics)
        exact = adapter.evaluate(frame, source_path=source, receipt_path=receipt_path,
                                 constraints=[calibration_process_proxy(gate.get('calibration_process_gate_pass'))]).to_payload()
        check('actual_exact_policy:' + label, exact == evidence)
        for name in ('nse', 'kge', 'pbias'):
            check('actual_raw_metric:' + label + ':' + name, math.isclose(raw_metrics[name], metrics[name], rel_tol=1e-12, abs_tol=1e-12))
        check('raw_kge_policy:' + label, metrics['policy_utility'] == raw_metrics['kge'])
        recomputed[label] = observation
        receipts.append(receipt['run_id'])
    check('distinct_successful_run_ids', len(receipts) == len(set(receipts)))
    for arm, report in result['arms'].items():
        ids = report['search_evaluation_ids']
        candidates = [(identifier, recomputed[identifier]) for identifier in ids if identifier in recomputed
                      and all(v <= 0 for v in recomputed[identifier].constraints.values())]
        if candidates:
            winner = max(candidates, key=lambda pair: pair[1].utility)
            check('measured_admissible_winner:' + arm, report['selected_evaluation_id'] == winner[0])
            final = next(c for c in calls if c['evaluation_id'] == f'{arm}_fresh_final')
            original = next(c for c in calls if c['evaluation_id'] == winner[0])
            check('fresh_different_run:' + arm, final['metrics']['policy_evidence']['provenance']['engine_run_id'] != original['metrics']['policy_evidence']['provenance']['engine_run_id'])
            check('fresh_parity_report:' + arm, report['fresh_final_matches_search'] == all(report['fresh_final_comparison'].values()))
            actual_comparisons = {key: math.isclose(original['metrics'][key], final['metrics'][key], rel_tol=1e-10, abs_tol=1e-10)
                                  for key in ('policy_utility', 'nse', 'kge', 'pbias')}
            actual_comparisons['policy_context'] = original['metrics']['policy_evidence']['context'] == final['metrics']['policy_evidence']['context']
            actual_comparisons['constraints'] = dict(recomputed[winner[0]].constraints) == dict(recomputed[final['evaluation_id']].constraints)
            actual_comparisons['admissibility'] = all(v <= 0 for v in recomputed[final['evaluation_id']].constraints.values())
            check('independent_fresh_parity:' + arm, actual_comparisons == report['fresh_final_comparison'])
        else:
            check('no_invented_winner:' + arm, report['parameters'] is None)
    shared = [c for c in calls if c['stage'] == 'design']
    finite_points = [c['parameters'] for c in shared if c['status'] == 'success']
    feasible_points = [c['parameters'] for c in shared if c['evaluation_id'] in recomputed and all(v <= 0 for v in recomputed[c['evaluation_id']].constraints.values())]
    def geometry(points):
        return assess_design(basin['bounds'], points).to_json() if points else None
    return {'status': 'passed', 'scope': 'independent read-only retained-output audit; no live engine',
            'checks': checks, 'check_count': len(checks), 'physical_callbacks': len(calls),
            'successful_policy_receipts': len(receipts), 'attributed_requests': result['attributed_requests'],
            'training_samples': len(obs), 'validation_scored': False,
            'shared_finite_count': len(finite_points), 'shared_feasible_count': len(feasible_points),
            'shared_finite_geometry': geometry(finite_points), 'shared_feasible_geometry': geometry(feasible_points),
            'proposal_diagnostics': result['gp_proposal_diagnostics'],
            'arm_results': {arm: {'selected_id': data.get('selected_evaluation_id'), 'search_utility': data.get('search_utility'),
                                  'verification_status': data['verification_status']} for arm, data in result['arms'].items()},
            'budgets': ledgers}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--frozen', type=Path, required=True)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    data = audit(args.run, args.frozen, args.preflight)
    args.out.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: data[k] for k in ('status', 'check_count', 'physical_callbacks', 'successful_policy_receipts', 'attributed_requests')}))
