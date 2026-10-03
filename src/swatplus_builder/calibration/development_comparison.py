"""Bounded paired development comparison; no model promotion or superiority claim.

Physical callbacks must reserve and finish their supplied EvaluationBudget,
including failures. Final-training callbacks must force a fresh solver run.
This runner supports fresh experiments only: interrupted ledgers remain charged
and cannot silently restart an optimizer from a different trajectory.
"""
from __future__ import annotations

import math
import random
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..errors import SwatBuilderExternalError
from .evaluation_budget import EvaluationBudget
from .experiment_design import assess_design
from .locked_benchmark import _dds_search
from .surrogate_optimizer import ConstrainedGPOptimizer, ConstrainedObservation

PROCESS = 'reported_calibration_process_gate_proxy'
CONSTRAINTS = ('volume', PROCESS)


def measured_policy_observation(label: str, metrics: Mapping[str, Any]) -> ConstrainedObservation:
    """Require explicit exact-policy success; no legacy or neutral fallback."""
    if metrics.get('policy_status') != 'valid':
        return ConstrainedObservation(label, 'failed')
    values = {}
    for name in ('policy_utility', 'nse', 'kge', 'pbias'):
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return ConstrainedObservation(label, 'failed')
        values[name] = float(value)
    evidence = metrics.get('policy_evidence')
    if not isinstance(evidence, Mapping) or evidence.get('status') != 'valid':
        return ConstrainedObservation(label, 'failed')
    if not isinstance(evidence.get('context'), Mapping) or not evidence['context']:
        return ConstrainedObservation(label, 'failed')
    residuals = evidence.get('constraints')
    if not isinstance(residuals, (list, tuple)) or any(not isinstance(c, Mapping) for c in residuals):
        return ConstrainedObservation(label, 'failed')
    if any(not isinstance(c.get('name'), str) or not c['name'] for c in residuals):
        return ConstrainedObservation(label, 'failed')
    if len({c.get('name') for c in residuals}) != len(residuals):
        return ConstrainedObservation(label, 'failed')
    selected = [c for c in residuals if c.get('name') == PROCESS]
    if len(selected) != 1 or selected[0].get('kind') != 'process_policy':
        return ConstrainedObservation(label, 'failed')
    value = selected[0].get('residual')
    # This is a declared categorical proxy, not an invented physical distance.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (-1., 1.):
        return ConstrainedObservation(label, 'failed')
    # Do not discard another declared policy constraint or unknown assessment.
    for constraint in residuals:
        residual = constraint.get('residual')
        if isinstance(residual, bool) or not isinstance(residual, (int, float)) or not math.isfinite(residual):
            return ConstrainedObservation(label, 'failed')
        if constraint.get('name') != PROCESS and residual > 0:
            return ConstrainedObservation(label, 'failed')
    return ConstrainedObservation(label, 'success', values['policy_utility'],
                                  {'volume': abs(values['pbias']) / 30. - 1., PROCESS: float(value)})


def _admissible(observation: ConstrainedObservation) -> bool:
    return observation.status == 'success' and all(v <= 0 for v in observation.constraints.values())


def _finite_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, Mapping):
        return {str(k): _finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(v) for v in value]
    return value


def run_development_comparison(
    evaluate: Callable[[dict[str, float], str, str, str, EvaluationBudget], Mapping[str, Any]],
    bounds: Mapping[str, tuple[float, float]],
    initial_points: Sequence[Mapping[str, float]],
    *, budgets: Mapping[str, EvaluationBudget], search_budget: int, seed: int = 42,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
    gp: ConstrainedGPOptimizer | None = None,
) -> dict[str, Any]:
    """Shared full-vector design, equal adaptive requests, reserved fresh checks.

    Validation slots are retained untouched. Design/screen governance and the
    complete sealed scientific ledger context are caller responsibilities.
    """
    if type(search_budget) is not int or search_budget < 0 or type(seed) is not int:
        raise ValueError('Explicit nonnegative integer search budget and integer seed required')
    bounds = {name: tuple(pair) for name, pair in bounds.items()}
    points = [dict(point) for point in initial_points]
    quality = assess_design(bounds, points, required_backend='rbf')
    if not quality.rbf_ready:
        raise ValueError('Shared design requires at least dimension+1 distinct full-rank full vectors')
    n = len(points)
    cap = n + search_budget + 2
    if set(budgets) != {'dds', 'gp'} or budgets['dds'].path == budgets['gp'].path:
        raise ValueError('Two distinct arm ledgers are required')
    for budget in budgets.values():
        state = budget.snapshot()
        if (state['total_cap'] != cap or state['charged_requests'] != 0
                or state['remaining_final_training'] != 1 or state['remaining_validation'] != 1
                or state['remaining_discretionary'] != n + search_budget):
            raise ValueError('Fresh arm ledgers must match design+search+two protected requests')
    gp = gp or ConstrainedGPOptimizer(bounds, CONSTRAINTS, budget=n + search_budget,
                                     initial_design_size=n, initial_points=points, seed=seed)
    if (gp.budget != n + search_budget or gp.proposals_issued != 0
            or dict(gp.bounds) != bounds or gp.constraint_names != CONSTRAINTS or gp.seed != seed):
        raise ValueError('Fresh GP proposal budget must match declared design+search')
    gp_state = gp.export_state()
    supplied_design = gp_state.get('initial_normalized_design', [])
    if (gp_state.get('pending') is not None or gp_state.get('observations')
            or len(supplied_design) != n
            or any(len(actual) != len(expected)
                   or any(not math.isclose(x, y, rel_tol=0, abs_tol=1e-14)
                          for x, y in zip(actual, expected, strict=True))
                   for actual, expected in zip(supplied_design, quality.normalized, strict=True))):
        raise ValueError('Fresh GP state and entire shared proposal design must match frozen points')
    gp.check_dependencies()  # Before budget reservations or evaluator callbacks.
    report: dict[str, Any] = {
        'schema': 'paired_development_comparison_v1', 'status': 'running',
        'interpretation': 'touched development comparison; no superiority or promotion claim',
        'shared_design': dict(quality=quality.to_json(), points=points),
        'search_budget_per_arm': search_budget, 'request_cap_per_arm': cap,
        'physical_callback_cap': n + 2 * search_budget + 2,
        'callback_count_basis': 'attempted evaluator callbacks, not confirmed process launches',
        'validation_used': False, 'physical_calls': [], 'arms': {},
    }
    started = time.monotonic()
    observations: dict[str, ConstrainedObservation] = {}
    metrics_by_id: dict[str, dict[str, Any]] = {}
    arm_ids = {'dds': [], 'gp': []}

    def save():
        report['elapsed_seconds'] = time.monotonic() - started
        report['gp_proposal_diagnostics'] = [d.to_json() for d in gp.proposal_diagnostics]
        report['gp_state'] = gp.export_state()
        report['budgets'] = {arm: budget.snapshot() for arm, budget in budgets.items()}
        if checkpoint:
            checkpoint(_finite_json(report))

    def call(point, label, stage, arm):
        assess_design(bounds, [point])  # Validate full key set/bounds on every proposal.
        if len(report['physical_calls']) >= report['physical_callback_cap']:
            raise RuntimeError('Physical callback cap exhausted')
        record = dict(evaluation_id=label, parameters=dict(point), stage=stage, arm=arm, status='attempting')
        report['physical_calls'].append(record)
        before_state = budgets[arm].snapshot()
        before = before_state['charged_requests']
        save()
        tic = time.monotonic()
        metrics: dict[str, Any] = {}
        try:
            metrics = dict(evaluate(dict(point), label, stage, arm, budgets[arm]))
            observation = measured_policy_observation(label, metrics)
            record.update(status=observation.status, metrics=metrics, utility=observation.utility,
                          constraints=dict(observation.constraints))
        except (SwatBuilderExternalError, TimeoutError, subprocess.TimeoutExpired) as error:
            observation = ConstrainedObservation(label, 'failed')
            record.update(status='failed', error=f'{type(error).__name__}: {error}')
        except BaseException as error:
            record.update(status='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'adapter_error',
                          error=f'{type(error).__name__}: {error}')
            save()
            raise
        finally:
            record['seconds'] = time.monotonic() - tic
        after_state = budgets[arm].snapshot()
        if after_state['charged_requests'] != before + 1:
            record['status'] = 'adapter_error'
            save()
            raise RuntimeError('Physical callback must charge exactly one supplied-ledger request')
        if stage == 'final_training' and (after_state['cache_hits'] != before_state['cache_hits']
                or after_state['engine_wrapper_calls'] != before_state['engine_wrapper_calls'] + 1):
            record['status'] = 'adapter_error'
            save()
            raise RuntimeError('Final training callback must perform a fresh engine-wrapper call')
        observations[label] = observation
        metrics_by_id[label] = metrics
        save()
        return metrics, observation

    def winner(arm):
        candidates = [r for r in report['physical_calls'] if r['evaluation_id'] in arm_ids[arm]
                      and _admissible(observations[r['evaluation_id']])]
        return max(candidates, key=lambda r: observations[r['evaluation_id']].utility) if candidates else None

    try:
        for index, point in enumerate(points):
            proposal = gp.ask()
            actual = dict(proposal.parameters)
            if set(actual) != set(point) or any(not math.isclose(actual[name], point[name], rel_tol=0, abs_tol=1e-12) for name in bounds):
                raise RuntimeError('GP shared proposal does not match frozen initial point')
            label = f'shared_{index}'
            token = budgets['gp'].reserve('design')
            save()  # Virtual attribution is charged before physical acquisition.
            reuse_status = 'failed'
            try:
                metrics, observation = call(actual, label, 'design', 'dds')
                reuse_status = 'completed' if observation.status == 'success' else 'failed'
            finally:
                budgets['gp'].finish(token, status=reuse_status, cache_hit=True, engine_invoked=False,
                                     metadata={'shared_source_evaluation_id': label, 'physical_arm': 'dds',
                                               'attribution': 'shared measurement reuse; not fresh engine execution'})
                save()
            gp.tell(proposal.proposal_id, observation)
            for arm in arm_ids:
                arm_ids[arm].append(label)
        initial = winner('dds')
        initial_best = (dict(initial['parameters']), metrics_by_id[initial['evaluation_id']],
                        observations[initial['evaluation_id']].utility) if initial else None

        def dds_evaluate(point):
            label = f'dds_search_{len(arm_ids["dds"]) - n}'
            metrics, _ = call(point, label, 'search', 'dds')
            arm_ids['dds'].append(label)
            return metrics

        def score(metrics):
            observation = measured_policy_observation('dds_score', metrics)
            return observation.utility if observation.status == 'success' else float('-inf')

        def feasible(metrics):
            return _admissible(measured_policy_observation('dds_feasible', metrics))

        _dds_search(evaluate=dds_evaluate, score_fn=score, feasible_fn=feasible,
                    phase_parameters=sorted(bounds), param_bounds=bounds,
                    start_params=dict(initial['parameters']) if initial else points[0],
                    budget=search_budget, budget_is_total=True, rng=random.Random(seed), initial_best=initial_best)
        while gp.proposals_issued < gp.budget:
            proposal = gp.ask()
            label = f'gp_search_{len(arm_ids["gp"]) - n}'
            _, observation = call(dict(proposal.parameters), label, 'search', 'gp')
            gp.tell(proposal.proposal_id, observation)
            arm_ids['gp'].append(label)
        for arm in arm_ids:
            selected = winner(arm)
            result = {'search_evaluation_ids': arm_ids[arm], 'parameters': None,
                      'verification_status': 'not_reached'}
            report['arms'][arm] = result
            if selected:
                selected_id = selected['evaluation_id']
                result.update(parameters=dict(selected['parameters']), selected_evaluation_id=selected_id,
                              search_metrics=metrics_by_id[selected_id],
                              search_utility=observations[selected_id].utility)
                fresh_metrics, fresh_obs = call(selected['parameters'], f'{arm}_fresh_final', 'final_training', arm)
                before = metrics_by_id[selected_id]
                comparisons = {name: isinstance(fresh_metrics.get(name), (int, float))
                               and not isinstance(fresh_metrics[name], bool)
                               and math.isfinite(fresh_metrics[name])
                               and math.isclose(before[name], fresh_metrics[name], rel_tol=1e-10, abs_tol=1e-10)
                               for name in ('policy_utility', 'nse', 'kge', 'pbias')}
                comparisons['policy_context'] = before.get('policy_evidence', {}).get('context') == fresh_metrics.get('policy_evidence', {}).get('context')
                comparisons['constraints'] = dict(observations[selected_id].constraints) == dict(fresh_obs.constraints)
                comparisons['admissibility'] = _admissible(fresh_obs)
                result.update(fresh_final_metrics=fresh_metrics, fresh_final_comparison=comparisons,
                              fresh_final_admissible=_admissible(fresh_obs),
                              fresh_final_matches_search=all(comparisons.values()),
                              verification_status='fresh_training_reproduced' if all(comparisons.values()) else 'verification_failed')
            if len(arm_ids[arm]) != n + search_budget:
                raise RuntimeError('Attributed design/search count does not match frozen budget')
        report['arms']['gp']['proposal_methods'] = [r.proposal.method for r in gp.observations]
        report['arms']['gp']['proposal_diagnostics'] = [d.to_json() for d in gp.proposal_diagnostics]
        report['actual_physical_callbacks'] = len(report['physical_calls'])
        report['attributed_requests'] = sum(b.snapshot()['charged_requests'] for b in budgets.values())
        if any(b.snapshot()['remaining_validation'] != 1 for b in budgets.values()):
            raise RuntimeError('Comparison must not consume protected validation reservations')
        report['status'] = 'completed'
        save()
        return _finite_json(report)
    except BaseException:
        report['status'] = 'interrupted_or_failed'
        save()
        raise
