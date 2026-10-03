"""Paired full-vector request accounting and exact-policy evidence without engines."""
from __future__ import annotations

import json

import pytest

from swatplus_builder.calibration.development_comparison import (
    CONSTRAINTS,
    PROCESS,
    measured_policy_observation,
    run_development_comparison,
)
from swatplus_builder.calibration.evaluation_budget import EvaluationBudget
from swatplus_builder.calibration.surrogate_optimizer import (
    ConstrainedGPOptimizer,
    SurrogateDependencyError,
)


def metrics(**overrides):
    return {'policy_status': 'valid', 'policy_utility': .6, 'policy_feasible': True,
            'nse': .4, 'kge': .6, 'pbias': 2.,
            'policy_evidence': {'status': 'valid', 'context': {'policy_sha256': 'frozen', 'epsilon': .01},
                                'constraints': [{'name': PROCESS, 'kind': 'process_policy', 'residual': -1.}]}, **overrides}


def setup(monkeypatch, tmp_path, search=2):
    bounds = {'x': (0., 1.), 'y': (0., 1.)}
    points = [{'x': 0., 'y': 0.}, {'x': 1., 'y': 0.}, {'x': 0., 'y': 1.}]
    ledgers = {a: EvaluationBudget(tmp_path / f'{a}.jsonl', total_cap=3+search+2,
                                   context={'arm': a, 'model': 'frozen'}) for a in ('dds', 'gp')}
    gp = ConstrainedGPOptimizer(bounds, CONSTRAINTS, budget=3+search, initial_design_size=3, initial_points=points)
    monkeypatch.setattr(gp, 'check_dependencies', lambda: None)
    monkeypatch.setattr(gp, '_gp_proposal', lambda measured: (.4, .6))
    return bounds, points, ledgers, gp


def evaluator(callback=None, *, check_virtual=None):
    calls=[]
    def evaluate(parameters,label,stage,arm,budget):
        if check_virtual and label.startswith('shared'):
            assert check_virtual.snapshot()['charged_requests'] == len([c for c in calls if c[1].startswith('shared')]) + 1
        token=budget.reserve(stage)
        calls.append((dict(parameters),label,stage,arm))
        status='failed'
        try:
            result=callback(parameters,label,stage,arm) if callback else metrics(policy_utility=.6+parameters['x']*.1)
            status='completed' if result.get('policy_status') == 'valid' else 'failed'
            return result
        finally:
            budget.finish(token,status=status,cache_hit=False,engine_invoked=True,metadata={'label':label})
    return evaluate,calls


def test_shared_full_vector_budgets_and_reserved_fresh_verification(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    evaluate,calls=evaluator(check_virtual=ledgers['gp'])
    snapshots=[]
    report=run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp,checkpoint=snapshots.append)
    assert len(calls)==report['actual_physical_callbacks']==9
    assert report['attributed_requests']==12
    assert report['shared_design']['quality']['affine_rank']==3
    assert all(set(p)==set(bounds) for p,_,_,_ in calls)
    assert all(r['verification_status']=='fresh_training_reproduced' for r in report['arms'].values())
    for ledger in ledgers.values():
        state=ledger.snapshot()
        assert state['charged_requests']==6 and state['remaining_validation']==1
        assert state['remaining_discretionary']==state['remaining_final_training']==0
    gp_finishes=[json.loads(line) for line in ledgers['gp'].path.read_text().splitlines() if json.loads(line)['kind']=='finish']
    assert [r['cache_hit'] for r in gp_finishes[:3]]==[True]*3
    assert [r['engine_invoked'] for r in gp_finishes[:3]]==[False]*3
    assert snapshots[0]['physical_calls']==[]


@pytest.mark.parametrize('bad', [None,float('nan'),True])
@pytest.mark.parametrize('key',['policy_utility','nse','kge','pbias'])
def test_missing_or_invalid_metric_has_no_fake_utility(key,bad):
    obs=measured_policy_observation('run',metrics(**{key:bad}))
    assert obs.status=='failed' and obs.utility is None


def test_unresolved_or_duplicate_process_proxy_rejected():
    m=metrics();m['policy_evidence']['constraints'][0]['residual']=None
    assert measured_policy_observation('run',m).status=='failed'
    m=metrics();m['policy_evidence']['constraints']*=2
    assert measured_policy_observation('run',m).status=='failed'
    assert measured_policy_observation('run',metrics(policy_status='invalid')).status=='failed'


def test_finite_process_and_volume_violations_are_measured_not_fake_failures():
    m=metrics(pbias=45.)
    m['policy_evidence']['constraints'][0]['residual']=1.
    obs=measured_policy_observation('run',m)
    assert obs.status=='success' and obs.utility==.6
    assert obs.constraints[PROCESS]==1. and obs.constraints['volume']==.5


def test_failed_shared_design_seed_is_included_in_dds_total(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    def fail(*args):
        raise TimeoutError('engine timeout')
    evaluate,calls=evaluator(fail)
    report=run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert len(calls)==7
    assert [c[1] for c in calls if c[3]=='dds' and c[2]=='search']==['dds_search_0','dds_search_1']
    assert calls[3][0]==points[0]  # Failed initial context requires a charged seed request.
    assert all(a['parameters'] is None for a in report['arms'].values())
    assert all(b.snapshot()['remaining_final_training']==1 for b in ledgers.values())
    assert all(b.snapshot()['status_counts']['failed']==5 for b in ledgers.values())


def test_fresh_utility_or_context_mismatch_not_certified(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    def change(parameters,label,stage,arm):
        m=metrics()
        if label=='gp_fresh_final':
            m['policy_utility']=.7
            m['policy_evidence']['context']['epsilon']=.02
        return m
    evaluate,_=evaluator(change)
    report=run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    arm=report['arms']['gp']
    assert arm['verification_status']=='verification_failed'
    assert not arm['fresh_final_comparison']['policy_utility']
    assert not arm['fresh_final_comparison']['policy_context']


def test_unknown_error_is_checkpointed_mirrored_and_propagated(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    def fail(*args):
        raise TypeError('adapter bug')
    evaluate,calls=evaluator(fail)
    snapshots=[]
    with pytest.raises(TypeError,match='adapter bug'):
        run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp,checkpoint=snapshots.append)
    assert len(calls)==1
    assert snapshots[-1]['status']=='interrupted_or_failed'
    assert snapshots[-1]['physical_calls'][0]['status']=='adapter_error'
    assert all(b.snapshot()['charged_requests']==1 for b in ledgers.values())
    assert ledgers['gp'].snapshot()['engine_wrapper_calls']==0


def test_dependencies_and_design_geometry_fail_before_callbacks(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    evaluate,calls=evaluator()
    def unavailable():
        raise SurrogateDependencyError('backend missing')
    monkeypatch.setattr(gp,'check_dependencies',unavailable)
    with pytest.raises(SurrogateDependencyError):
        run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert not calls and all(b.snapshot()['charged_requests']==0 for b in ledgers.values())
    bad=[{'x':0.,'y':0.},{'x':.5,'y':.5},{'x':1.,'y':1.}]
    with pytest.raises(ValueError,match='full-rank'):
        run_development_comparison(evaluate,bounds,bad,budgets=ledgers,search_budget=2,gp=gp)


def test_restart_cannot_silently_refund_or_replay_charged_search(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    ledgers['dds'].reserve('design')
    evaluate,calls=evaluator()
    with pytest.raises(ValueError,match='Fresh arm ledgers'):
        run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert not calls and ledgers['dds'].snapshot()['charged_requests']==1


def test_zero_adaptive_budget_still_reproduces_measured_design_winners(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path,search=0)
    evaluate,calls=evaluator()
    report=run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=0,gp=gp)
    assert len(calls)==5 and report['attributed_requests']==8
    assert all(a['verification_status']=='fresh_training_reproduced' for a in report['arms'].values())
    assert not any(stage=='search' for _,_,stage,_ in calls)


def test_gp_design_mismatch_is_detected_before_acquiring_mismatched_point(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    gp._design[0]=(.2,.2)
    evaluate,calls=evaluator()
    with pytest.raises(ValueError,match='shared proposal'):
        run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert not calls and all(b.snapshot()['charged_requests']==0 for b in ledgers.values())


def test_fresh_cache_reuse_is_rejected_not_called_reproduction(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    evaluate,_=evaluator()
    def bad(point,label,stage,arm,budget):
        if stage!='final_training':
            return evaluate(point,label,stage,arm,budget)
        token=budget.reserve(stage)
        budget.finish(token,status='completed',cache_hit=True,engine_invoked=False)
        return metrics()
    with pytest.raises(RuntimeError,match='fresh engine-wrapper'):
        run_development_comparison(bad,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert ledgers['dds'].snapshot()['remaining_final_training']==0
    assert ledgers['dds'].snapshot()['remaining_validation']==1


def test_callback_cannot_skip_physical_request_accounting(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    with pytest.raises(RuntimeError,match='charge exactly one'):
        run_development_comparison(lambda *a:metrics(),bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert ledgers['gp'].snapshot()['charged_requests']==1


def test_later_injected_gp_design_error_is_rejected_before_any_acquisition(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    gp._design[-1]=(.2,.3)
    evaluate,calls=evaluator()
    with pytest.raises(ValueError,match='entire shared proposal design'):
        run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert not calls and all(b.snapshot()['charged_requests']==0 for b in ledgers.values())


def test_injected_pending_gp_state_is_rejected_before_any_acquisition(monkeypatch,tmp_path):
    bounds,points,ledgers,gp=setup(monkeypatch,tmp_path)
    proposal=gp.ask()
    gp._issued=0  # Exercise malformed injected state beyond the ordinary issued-count check.
    assert gp.export_state()['pending']['proposal_id']==proposal.proposal_id
    evaluate,calls=evaluator()
    with pytest.raises(ValueError,match='Fresh GP state'):
        run_development_comparison(evaluate,bounds,points,budgets=ledgers,search_budget=2,gp=gp)
    assert not calls and all(b.snapshot()['charged_requests']==0 for b in ledgers.values())
