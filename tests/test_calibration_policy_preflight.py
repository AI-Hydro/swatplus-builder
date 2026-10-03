"""Policy configuration must fail before expensive work or ledger charges."""
from unittest.mock import Mock

import pandas as pd
import pytest

from swatplus_builder.calibration import real_engine
from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
from swatplus_builder.calibration.objective_policy import ObjectivePolicy
from swatplus_builder.calibration.policy_engine import ExactOutputPolicyAdapter


@pytest.fixture
def configured(tmp_path, monkeypatch):
    dates = pd.date_range('2010-01-01', '2015-12-31')
    obs = pd.Series(range(1, len(dates) + 1), index=dates, dtype=float)
    policy = ExactOutputPolicyAdapter.bind(ObjectivePolicy.fit(obs.tolist(), weights={'kge': 1.}), obs)
    budget = EvaluationBudget(tmp_path / 'ledger.jsonl', total_cap=4, context={'study': 'preflight'})
    identity = Mock(return_value='test-identity')
    engine = Mock(side_effect=AssertionError('engine must not run during preflight'))
    monkeypatch.setattr(real_engine, '_staged_input_identity', identity)
    monkeypatch.setattr(real_engine, '_objective_cache_signature', Mock(return_value='cache'))
    monkeypatch.setattr(real_engine, 'run_swat', engine)
    kwargs = dict(base_txtinout=tmp_path / 'base', work_root=tmp_path / 'runs',
                  observed_series=obs, objective_policy=policy, evaluation_budget=budget)
    return kwargs, budget, identity, engine


@pytest.mark.parametrize('changes', [
    {},  # Historical default nyskip=2 contradicts the six-year bound policy.
    {'nyskip_years': 0, 'score_start': '2011-01-01'},
    {'nyskip_years': 0, 'score_end': '2014-12-31'},
    {'nyskip_years': 0, 'changed_values': True},
    {'nyskip_years': 0, 'changed_calendar': True},
])
def test_incompatible_training_context_rejected_before_work(configured, changes):
    kwargs, budget, identity, engine = configured
    changes = dict(changes)
    if changes.pop('changed_values', False):
        kwargs['observed_series'] = kwargs['observed_series'] * 2
    if changes.pop('changed_calendar', False):
        series = kwargs['observed_series'].copy()
        series.index = series.index + pd.Timedelta(days=1)
        kwargs['observed_series'] = series
    with pytest.raises(ValueError, match='objective_policy training'):
        real_engine.make_real_objective(**kwargs, **changes)
    identity.assert_not_called()
    engine.assert_not_called()
    assert budget.snapshot()['charged_requests'] == 0


@pytest.mark.parametrize('stage', ['final_trainng', '', None, True, [], {}])
def test_invalid_budget_stage_rejected_before_work(configured, stage):
    kwargs, budget, identity, engine = configured
    with pytest.raises(ValueError, match='Unknown budget stage'):
        real_engine.make_real_objective(**kwargs, nyskip_years=0, budget_stage=stage)
    identity.assert_not_called()
    engine.assert_not_called()
    assert budget.snapshot()['charged_requests'] == 0


def test_correct_context_constructs_without_engine_or_charge(configured):
    kwargs, budget, identity, engine = configured
    assert callable(real_engine.make_real_objective(**kwargs, nyskip_years=0))
    identity.assert_called_once()
    engine.assert_not_called()
    assert budget.snapshot()['charged_requests'] == 0


def test_adapter_may_bind_to_declared_trimmed_window(configured):
    kwargs, budget, identity, engine = configured
    obs = kwargs['observed_series'].loc['2012-01-01':]
    kwargs['objective_policy'] = ExactOutputPolicyAdapter.bind(
        ObjectivePolicy.fit(obs.tolist(), weights={'kge': 1.}), obs)
    assert callable(real_engine.make_real_objective(**kwargs, nyskip_years=2))
    identity.assert_called_once()
    engine.assert_not_called()
    assert budget.snapshot()['charged_requests'] == 0
