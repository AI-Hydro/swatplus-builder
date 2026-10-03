"""Read-only audit of a completed frozen DDS/GP development pilot.

Run with --pilot <output directory> --snapshot <frozen source directory>.
Prints JSON to stdout; it never writes model/output/manifest files or invokes SWAT+.
The imported package must be the frozen snapshot, not the changing development tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    pilot, snapshot = args.pilot.resolve(), args.snapshot.resolve()
    sys.path.insert(0, str(snapshot / 'src'))
    import pandas as pd

    import swatplus_builder
    from swatplus_builder.calibration.real_engine import (
        _candidate_physical_gate,
        _objective_cache_signature,
        _objective_trace_payload_sha256,
        _observation_identity,
        _staged_input_identity,
        load_observed_from_alignment_csv,
        params_hash,
    )
    from swatplus_builder.evidence.integrity import input_configuration_fingerprint
    from swatplus_builder.output.eval import evaluate_run

    checks: list[dict] = []
    def check(name, passed, detail=None):
        checks.append({'check': name, 'passed': bool(passed), 'detail': detail})
    def close(left, right):
        return (isinstance(left, (float, int)) and isinstance(right, (float, int))
                and math.isfinite(left) and math.isfinite(right)
                and math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-10))
    def admissible(metrics):
        return (all(isinstance(metrics.get(n), (float, int))
                    and math.isfinite(metrics[n]) for n in ('nse', 'kge', 'pbias'))
                and abs(metrics['pbias']) <= 30
                and metrics.get('calibration_process_gate_passed') == 1)

    source_manifest = json.loads((snapshot / 'source_manifest.json').read_text())
    source_failures = [name for name, digest in source_manifest.items()
                       if not (snapshot / name).is_file() or sha(snapshot / name) != digest]
    check('frozen_source_manifest_byte_hashes', not source_failures,
          {'files': len(source_manifest), 'mismatches': source_failures})
    root = Path(swatplus_builder.__file__).resolve().parent
    check('audit_imports_frozen_package', root == snapshot / 'src/swatplus_builder', str(root))
    manifest = json.loads((pilot / 'manifest.json').read_text())
    result = json.loads((pilot / 'pilot_results.json').read_text())
    if manifest.get('status') != 'completed' or result.get('status') != 'completed':
        check('completed_pilot_required', False, [manifest.get('status'), result.get('status')])
        print(json.dumps({'passed': False, 'checks': checks}, indent=2))
        raise SystemExit(2)
    check('completed_pilot_required', True)
    package_hashes = {str(p.relative_to(root)): sha(p) for p in root.rglob('*.py')}
    check('loaded_source_manifest_matches_package', package_hashes == manifest['package_python_source_sha256'])
    check('pilot_script_sealed', sha(snapshot / 'calibration_optimizer_pilot.py') == manifest['pilot_script_sha256'])
    source = Path(manifest['source'])
    basin = source.parent.parent
    alignment = basin / 'benchmark/alignment.csv'
    lock_path = basin / 'benchmark/benchmark_lock.json'
    lock = json.loads(lock_path.read_text())
    observed = load_observed_from_alignment_csv(alignment).loc['2010-01-01':'2015-12-31']
    check('historical_input_unchanged', _staged_input_identity(source) == manifest['source_input_sha256'])
    check('snapshot_input_exact_copy', _staged_input_identity(pilot / 'input_snapshot/TxtInOut') == manifest['source_input_sha256'])
    check('observation_alignment_unchanged', sha(alignment) == manifest['alignment_sha256'] == lock['alignment_sha256'])
    check('benchmark_lock_unchanged', sha(lock_path) == manifest['lock_sha256'])
    check('training_calendar_declaration', manifest['score_dates'] == ['2010-01-01', '2015-12-31']
          and manifest['simulation_dates'] == ['2007-01-01', '2015-12-31']
          and manifest['withheld_years_used'] is False)

    calls = result['physical_calls']
    ids = [r['evaluation_id'] for r in calls]
    by_id = {r['evaluation_id']: r for r in calls}
    check('physical_call_cap_and_unique_ids', len(calls) <= 11 and len(ids) == len(set(ids))
          and result['actual_physical_calls'] == len(calls), len(calls))
    check('reservation_terminal_statuses', all(r['status'] not in {'attempting', 'adapter_error', 'interrupted'} for r in calls))
    check('three_shared_initial_calls', [n for n in ids if n.startswith('shared_')] == ['shared_0', 'shared_1', 'shared_2'])
    invocation_records = [json.loads(p.read_text()) for p in (pilot / 'invocations').glob('*.json')]
    invocation_ids = [r['invocation_id'] for r in invocation_records]
    check('telemetry_call_count_and_unique_ids', len(invocation_records) == len(calls)
          and len(invocation_ids) == len(set(invocation_ids)), len(invocation_records))
    # Telemetry does not store arm labels. Match its time interval to the receipt
    # sealing time plus exact parameter identity; do not infer pairing by filename.
    check('no_compact_or_workdir_reuse', all(r['cache_status'] == 'miss' for r in invocation_records))
    check('telemetry_attempt_census', all(r['engine_invoked'] and r['engine_invocation_basis'] == 'run_swat_call'
          for r in invocation_records))
    for record in invocation_records:
        stages = record['stage_seconds']
        check(f"telemetry_duration:{record['invocation_id']}",
              all(math.isfinite(v) and v >= 0 for v in stages.values())
              and record['total_seconds'] >= sum(stages.values()) - 1e-6)

    used_invocations = []
    engine_paths = set()
    bounds = manifest['bounds']
    for call in calls:
        label = call['evaluation_id']
        parameters = call['parameters']
        check(f'governed_bounds:{label}', set(parameters) == set(bounds)
              and all(math.isfinite(v) and bounds[n][0] <= v <= bounds[n][1]
                      for n, v in parameters.items()))
        if call['status'] != 'success':
            check(f'failed_call_not_numeric_target:{label}', call.get('utility') is None)
            continue
        work = pilot / 'evaluations' / label / params_hash(parameters)
        txt = work / 'TxtInOut'
        trace = json.loads((work / 'objective_trace.json').read_text())
        receipt = json.loads((txt / 'engine_run_receipt.json').read_text())
        engine = Path(receipt['engine']['path'])
        engine_paths.add(str(engine))
        check(f'engine_identity:{label}', sha(engine) == receipt['engine']['sha256'] == manifest['engine_sha256'])
        check(f'receipt_success_and_threads:{label}', receipt['returncode'] == 0
              and receipt['execution']['threads'] == manifest['engine_threads'] == 1)
        check(f'receipt_raw_output_digests:{label}', all(sha(txt / name) == digest for name, digest in receipt['files'].items()))
        check(f'receipt_static_inputs:{label}', input_configuration_fingerprint(txt)[0] == receipt['input_configuration_sha256'])
        check(f'trace_parameters_and_digest:{label}', trace['params'] == parameters
              and trace['payload_sha256'] == _objective_trace_payload_sha256(trace))
        engine_sealed = datetime.fromisoformat(receipt['sealed_at_utc'])
        matches = [r for r in invocation_records if r['params_sha256'] == params_hash(parameters)
                   and datetime.fromisoformat(r['started_at_utc']) <= engine_sealed
                   <= datetime.fromisoformat(r['finished_at_utc'])]
        check(f'telemetry_receipt_pairing:{label}', len(matches) == 1)
        if matches:
            used_invocations.append(matches[0]['invocation_id'])
            check(f'telemetry_trace_signature:{label}', matches[0]['cache_signature'] == trace['cache_signature'])
        expected_signature = _objective_cache_signature(
            'full', binary=engine,
            simulation_start=pd.Timestamp('2007-01-01').date(),
            simulation_end=pd.Timestamp('2015-12-31').date(),
            score_start=pd.Timestamp('2010-01-01').date(), score_end=pd.Timestamp('2015-12-31').date(),
            nyskip_years=0, objective_sim_file=lock['sim_source_file'],
            outlet_gis_id=lock['outlet_gis_id'], objective_outlet_policy=lock['outlet_policy'],
            observation_sha256=_observation_identity(observed),
            input_configuration_sha256=manifest['source_input_sha256'],
            include_physical_gate=True, threads=1,
        )
        check(f'semantic_cache_identity:{label}', trace['cache_signature'] == expected_signature)
        frame, raw_metrics, diagnostics = evaluate_run(
            txt / lock['sim_source_file'], observed,
            outlet_gis_id=lock['outlet_gis_id'], outlet_policy=lock['outlet_policy'], return_diagnostics=True,
        )
        saved = pd.read_csv(txt / 'alignment_calibration.csv', index_col=0, parse_dates=True)
        check(f'no_withheld_dates_scored:{label}', len(frame) > 0 and len(saved) == len(frame)
              and frame.index.min() >= pd.Timestamp('2010-01-01')
              and frame.index.max() <= pd.Timestamp('2015-12-31')
              and saved.index.equals(frame.index))
        check(f'raw_alignment_reproduces:{label}',
              all(close(a, b) for column in ('obs', 'sim')
                  for a, b in zip(saved[column], frame[column], strict=True)))
        check(f'raw_required_metrics_reproduce:{label}',
              all(close(raw_metrics[n], call['metrics'][n]) and close(raw_metrics[n], trace['metrics'][n])
                  for n in ('nse', 'kge', 'pbias')))
        gate = _candidate_physical_gate(txt, raw_metrics)
        check(f'raw_process_admissibility_reproduces:{label}',
              (1 if gate.get('calibration_process_gate_pass') else 0)
              == call['metrics']['calibration_process_gate_passed'])
        check(f'utility_and_constraints_match_measurements:{label}',
              close(call['utility'], raw_metrics['kge'])
              and close(call['constraints']['volume'], abs(raw_metrics['pbias']) / 30 - 1)
              and call['constraints']['calibration_process'] == (-1 if gate.get('calibration_process_gate_pass') else 1))
    check('each_success_has_distinct_invocation', len(used_invocations) == len(set(used_invocations)))

    attributable = 0
    for name, arm in result['arms'].items():
        search_ids = arm['search_evaluation_ids']
        check(f'six_attributed_search_calls:{name}', len(search_ids) == 6
              and len(set(search_ids)) == 6 and all(n in by_id for n in search_ids)
              and search_ids[:3] == ['shared_0', 'shared_1', 'shared_2'])
        selected = arm['parameters']
        qualifying = [by_id[n] for n in search_ids if admissible(by_id[n]['metrics'])]
        if selected is None:
            check(f'no_fabricated_winner:{name}', not qualifying and arm['verification_status'] == 'not_reached')
        else:
            selected_records = [r for r in qualifying if r['parameters'] == selected]
            check(f'selected_actual_admissible_best:{name}', bool(selected_records)
                  and close(arm['search_metrics']['kge'], max(r['metrics']['kge'] for r in qualifying))
                  and all(close(arm['search_metrics'][n], selected_records[0]['metrics'][n])
                          for n in ('nse', 'kge', 'pbias')))
            final_id = arm['fresh_final_evaluation_id']
            check(f'fresh_final_reserved_and_selected_point:{name}', final_id == f'{name}_fresh_final'
                  and final_id in by_id and by_id[final_id]['parameters'] == selected)
            finals = by_id[final_id]['metrics']
            check(f'fresh_final_reproduction:{name}', admissible(finals)
                  and all(close(finals[n], arm['search_metrics'][n]) for n in ('nse', 'kge', 'pbias'))
                  and arm['verification_status'] == 'fresh_training_reproduced')
        attributed = 6 + int(selected is not None)
        check(f'arm_attribution_count:{name}', arm['attributed_calls'] == attributed)
        attributable += attributed
    check('total_attribution_respects_sharing', attributable == result['attributed_calls'] <= 14
          and attributable - len(calls) == 3)
    summary = {'passed': all(c['passed'] for c in checks), 'checks': checks,
               'physical_attempts': len(calls), 'attributed_calls': attributable,
               'engine_paths': sorted(engine_paths),
               'timing_semantics': 'Attempt callback duration includes factory/fingerprinting overhead; telemetry stages exclude factory construction. Engine timing includes receipt generation. Serial arm order prevents speedup inference.'}
    print(json.dumps(summary, indent=2, allow_nan=False))
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
