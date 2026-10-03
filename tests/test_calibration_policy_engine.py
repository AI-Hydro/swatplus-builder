"""Exact training provenance and budget integration; no solver is launched."""
from __future__ import annotations

import json
from hashlib import sha256

import pandas as pd
import pytest

from swatplus_builder.calibration import real_engine
from swatplus_builder.calibration.objective_policy import ObjectivePolicy
from swatplus_builder.calibration.policy_engine import (
    ExactOutputPolicyAdapter,
    calibration_process_proxy,
)


def training():
    return pd.Series([0., 1., 4.], index=pd.date_range('2010-01-01', periods=3))


def adapter(series=None, weights=None):
    series = training() if series is None else series
    policy = ObjectivePolicy.fit(series.tolist(), weights=weights or {'sqrt_nse': 1., 'log_nse': 1.},
                                 epsilon_fraction=.01 if weights is None else None)
    return ExactOutputPolicyAdapter.bind(policy, series)


def seal(tmp_path):
    source = tmp_path / 'basin_sd_cha_day.txt'
    source.write_text('measured output')
    receipt = tmp_path / 'engine_run_receipt.json'
    receipt.write_text(json.dumps({'schema_version': '2.0', 'returncode': 0, 'run_id': 'run1', 'input_configuration_sha256': 'a' * 64, 'engine': {'sha256': 'b' * 64},
                                  'files': {source.name: sha256(source.read_bytes()).hexdigest()}}))
    return source, receipt


def test_actual_aligned_flows_and_source_are_scored(tmp_path):
    source, receipt = seal(tmp_path)
    a = adapter()
    frame = pd.DataFrame({'obs': training(), 'sim': [0., 1.2, 3.7]})
    result = a.evaluate(frame, source_path=source, receipt_path=receipt)
    assert result.objective.status == 'valid'
    assert result.objective.components == a.policy.evaluate(frame['obs'], frame['sim']).components
    assert result.provenance['scored_observation_sha256'] == a.policy.training_observation_sha256
    assert result.provenance['engine_receipt_sha256'] == sha256(receipt.read_bytes()).hexdigest()
    assert result.to_payload()['context']['epsilon'] == .01 * (5 / 3)


@pytest.mark.parametrize('change', ['missing_date', 'different_dates', 'no_datetime', 'changed_observation', 'extra_withheld'])
def test_calendar_or_observation_changes_cannot_claim_training_context(tmp_path, change):
    source, receipt = seal(tmp_path)
    frame = pd.DataFrame({'obs': training(), 'sim': [0., 1., 4.]})
    if change == 'missing_date':
        frame = frame.iloc[:2]
    elif change == 'different_dates':
        frame.index = frame.index + pd.Timedelta(days=365)
    elif change == 'no_datetime':
        frame.index = range(3)
    elif change == 'changed_observation':
        frame.loc[frame.index[1], 'obs'] = 2.
    else:
        frame.loc[pd.Timestamp('2016-01-01')] = [2., 2.]
    result = adapter().evaluate(frame, source_path=source, receipt_path=receipt)
    assert result.objective.status == 'invalid'
    assert result.objective.utility is None
    assert not result.objective.feasible


@pytest.mark.parametrize('bad_receipt', ['missing', 'tampered_output', 'unsuccessful', 'unsealed_source'])
def test_output_receipt_is_required_not_only_a_caller_context(tmp_path, bad_receipt):
    source, receipt = seal(tmp_path)
    if bad_receipt == 'missing':
        receipt.unlink()
    elif bad_receipt == 'tampered_output':
        source.write_text('different output')
    else:
        data = json.loads(receipt.read_text())
        if bad_receipt == 'unsuccessful':
            data['returncode'] = 1
        else:
            data['files'] = {}
        receipt.write_text(json.dumps(data))
    result = adapter().evaluate(pd.DataFrame({'obs': training(), 'sim': training()}),
                                source_path=source, receipt_path=receipt)
    assert result.objective.status == 'invalid'
    assert result.objective.utility is None


def test_unknown_gate_remains_unevaluated(tmp_path):
    source, receipt = seal(tmp_path)
    frame = pd.DataFrame({'obs': training(), 'sim': training()})
    for value in [None, float('nan'), 1., 'pass']:
        result = adapter().evaluate(frame, source_path=source, receipt_path=receipt,
                                   constraints=[calibration_process_proxy(value)])
        assert result.objective.status == 'invalid'
        assert result.objective.constraints[0].residual is None
    failing = adapter().evaluate(frame, source_path=source, receipt_path=receipt,
                                constraints=[calibration_process_proxy(False)])
    assert failing.objective.status == 'valid' and not failing.objective.feasible
    assert failing.objective.constraints[0].residual == 1.


def test_binding_same_values_to_a_different_calendar_changes_identity():
    a = adapter()
    s = training(); s.index = s.index + pd.Timedelta(days=1)
    assert adapter(s).sha256 != a.sha256
    with pytest.raises(ValueError, match='observations_do_not_match'):
        ExactOutputPolicyAdapter.bind(a.policy, training() * 2)


@pytest.fixture
def objective_factory(monkeypatch, tmp_path):
    base = tmp_path / 'base'; base.mkdir()
    (base / 'model.hyd').write_text('static')
    calls = []
    frame_override = []
    gate = [{'pass': True, 'calibration_process_gate_pass': True}]

    def run(txt, **kwargs):
        calls.append(txt)
        seal(txt)

    def evaluate(path, obs, **kwargs):
        frame = frame_override[0] if frame_override else pd.DataFrame({'obs': obs, 'sim': obs * .95})
        # Legacy metric values intentionally differ from actual exact output.
        return frame, {'nse': .123, 'kge': .321, 'pbias': 1.}, {'sim_source_file': path.name}

    monkeypatch.setattr(real_engine, 'run_swat', run)
    monkeypatch.setattr(real_engine, 'evaluate_run', evaluate)
    for name in ['_prepare_full_mode_txtinout_for_objective', '_prepare_txtinout_for_objective', '_apply_parameters_for_mode']:
        monkeypatch.setattr(real_engine, name, lambda *a, **k: None)
    monkeypatch.setattr(real_engine, '_candidate_physical_gate', lambda *a, **k: gate[0])

    def factory(**kwargs):
        options = dict(base_txtinout=base, observed_series=training(), work_root=tmp_path / 'runs',
                       nyskip_years=0, telemetry_dir=tmp_path / 'telemetry')
        options.update(kwargs)
        return real_engine.make_real_objective(**options)
    return factory, calls, frame_override, gate


def test_policy_recomputes_actual_output_and_cache_is_not_fresh(objective_factory):
    factory, calls, _, _ = objective_factory
    a = adapter()
    objective = factory(objective_policy=a)
    first = objective({})
    assert first['policy_status'] == 'valid'
    assert first['sqrt_nse'] != .123
    assert first['policy_utility'] == pytest.approx(a.policy.evaluate(training(), training() * .95).utility)
    second = objective({})
    assert len(calls) == 1 and first['policy_evidence'] == second['policy_evidence']
    assert factory(objective_policy=a, force_fresh=True)({})['policy_utility'] == first['policy_utility']
    assert len(calls) == 2
    trace = json.loads((calls[-1].parent / 'objective_trace.json').read_text())
    assert trace['policy_evidence']['provenance']['engine_run_id'] == 'run1'


def test_legacy_return_and_policy_reuse_is_explicit(objective_factory):
    factory, calls, _, _ = objective_factory
    assert factory()({}) == {'nse': .123, 'kge': .321, 'pbias': 1.}
    with pytest.raises(ValueError, match='compact trace reuse'):
        factory(objective_policy=adapter(), reuse_compact_traces=True)
    assert len(calls) == 1


def test_score_window_excludes_withheld_values_before_evaluation(objective_factory):
    factory, _, _, _ = objective_factory
    all_obs = training(); all_obs.loc[pd.Timestamp('2016-01-01')] = 999999.
    result = factory(objective_policy=adapter(), observed_series=all_obs,
                     score_start='2010-01-01', score_end='2010-01-03')({})
    assert result['policy_status'] == 'valid'
    assert result['policy_evidence']['provenance']['scored_sample_count'] == 3
    assert result['policy_evidence']['context']['epsilon'] == pytest.approx(.01 * (5 / 3))


def test_unknown_gate_invalidates_opt_in_policy_not_legacy(objective_factory):
    factory, _, _, gate = objective_factory
    gate[0] = {'pass': False, 'reason': 'unavailable'}
    result = factory(objective_policy=adapter(), include_physical_gate=True)({})
    assert result['policy_status'] == 'invalid'
    assert result['policy_utility'] is None
    assert result['policy_evidence']['constraints'][0]['residual'] is None


def test_invalid_calendar_returns_no_utility(objective_factory):
    factory, _, override, _ = objective_factory
    override.append(pd.DataFrame({'obs': [0., 1., 4.], 'sim': [0., 1., 4.]}))
    result = factory(objective_policy=adapter())({})
    assert result['policy_status'] == 'invalid'
    assert result['policy_utility'] is None


def test_whole_workflow_budget_counts_cache_and_protects_final(objective_factory, tmp_path):
    from swatplus_builder.calibration.evaluation_budget import (
        BudgetExhaustedError,
        EvaluationBudget,
    )
    factory, calls, _, _ = objective_factory
    budget = EvaluationBudget(tmp_path / 'budget.jsonl', total_cap=4, context={'experiment': 'fixture'},
                              final_training_reserve=1, validation_reserve=1)
    obj = factory(objective_policy=adapter(), evaluation_budget=budget)
    obj({}); obj({})
    with pytest.raises(BudgetExhaustedError):
        obj({})
    assert len(calls) == 1
    factory(objective_policy=adapter(), evaluation_budget=budget, budget_stage='final_training', force_fresh=True)({})
    assert len(calls) == 2
    rows = [json.loads(line) for line in budget.path.read_text().splitlines()]
    finishes = [r for r in rows if r['kind'] == 'finish']
    assert [r['cache_hit'] for r in finishes] == [False, True, False]
    assert [r['engine_invoked'] for r in finishes] == [True, False, True]
    assert all(r['status'] == 'completed' for r in finishes)


def test_invalid_policy_attempt_is_charged_failed(objective_factory, tmp_path):
    from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
    factory, calls, override, _ = objective_factory
    override.append(pd.DataFrame({'obs': [0., 1., 4.], 'sim': [0., 1., 4.]}))
    budget = EvaluationBudget(tmp_path / 'budget.jsonl', total_cap=3, context={'experiment': 'fixture'})
    result = factory(objective_policy=adapter(), evaluation_budget=budget)({})
    assert result['policy_status'] == 'invalid' and len(calls) == 1
    finish = json.loads(budget.path.read_text().splitlines()[-1])
    assert finish['kind'] == 'finish' and finish['status'] == 'failed'
    assert finish['engine_invoked']
    assert finish['metadata']['policy_evidence']['status'] == 'invalid'


@pytest.mark.parametrize('exception,status', [(RuntimeError('engine error'), 'failed'), (KeyboardInterrupt(), 'interrupted')])
def test_engine_exception_finished_in_budget(objective_factory, tmp_path, monkeypatch, exception, status):
    from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
    factory, _, _, _ = objective_factory
    def fail(*args, **kwargs):
        raise exception
    monkeypatch.setattr(real_engine, 'run_swat', fail)
    budget = EvaluationBudget(tmp_path / 'budget.jsonl', total_cap=3, context={'experiment': 'fixture'})
    with pytest.raises(type(exception)):
        factory(evaluation_budget=budget)({})
    finish = json.loads(budget.path.read_text().splitlines()[-1])
    assert finish['status'] == status and finish['engine_invoked']


def test_bad_parameter_diagnostic_does_not_break_budget_finalization(objective_factory, tmp_path, monkeypatch):
    from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
    factory, _, _, _ = objective_factory
    def fail(*args, **kwargs):
        raise ValueError('nonfinite parameter')
    monkeypatch.setattr(real_engine, '_apply_parameters_for_mode', fail)
    budget = EvaluationBudget(tmp_path / 'budget.jsonl', total_cap=3, context={'experiment': 'fixture'})
    with pytest.raises(ValueError, match='nonfinite parameter'):
        factory(evaluation_budget=budget)({'PET_CO': float('nan')})
    finish = json.loads(budget.path.read_text().splitlines()[-1])
    assert finish['status'] == 'failed' and not finish['engine_invoked']
    assert finish['metadata']['params']['PET_CO'] == 'nan'


def test_changed_policy_cannot_reuse_previous_policy_context(objective_factory):
    factory, calls, _, _ = objective_factory
    first = factory(objective_policy=adapter())({})
    changed = adapter(weights={'kge': 1.})
    second = factory(objective_policy=changed)({})
    assert len(calls) == 2
    assert second['policy_evidence']['context']['policy_sha256'] == changed.policy.sha256
    assert first['policy_evidence']['context'] != second['policy_evidence']['context']
    assert 'sqrt_nse' not in second and 'log_nse' not in second


def test_receipt_without_execution_identity_is_invalid(tmp_path):
    source, receipt = seal(tmp_path)
    data = json.loads(receipt.read_text()); del data['engine']
    receipt.write_text(json.dumps(data))
    result = adapter().evaluate(pd.DataFrame({'obs': training(), 'sim': training()}),
                                source_path=source, receipt_path=receipt)
    assert result.objective.status == 'invalid'
    assert 'missing_or_invalid_engine_receipt_identity' in result.objective.reasons
