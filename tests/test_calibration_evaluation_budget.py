"""Whole-workflow request caps persist failures, interruptions and reserve slots."""
import hashlib
import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from swatplus_builder.calibration.evaluation_budget import (
    BudgetExhaustedError,
    BudgetLedgerError,
    EvaluationBudget,
)

CONTEXT = {'source': 'sealed model', 'observations': 'training only',
           'simulation': ['2007-01-01', '2015-12-31'], 'objective': 'raw-kge-v1', 'gate': 'process-v1'}


def budget(path, **kwargs):
    options = dict(total_cap=5, context=CONTEXT, final_training_reserve=1, validation_reserve=1)
    options.update(kwargs)
    return EvaluationBudget(path, **options)


@pytest.mark.parametrize('invalid', [0, -1, True, False, 3.0, 2.5, '5'])
def test_strict_positive_integer_cap(tmp_path, invalid):
    with pytest.raises(ValueError, match='positive integer'):
        budget(tmp_path / 'ledger.jsonl', total_cap=invalid)
    assert not (tmp_path / 'ledger.jsonl').exists()


def test_preflight_planned_costs_before_ledger_creation(tmp_path):
    with pytest.raises(ValueError, match='exceed total_cap'):
        budget(tmp_path / 'ledger.jsonl', planned_screen=2, planned_design=2)
    assert not (tmp_path / 'ledger.jsonl').exists()
    with pytest.raises(ValueError, match='nonnegative integer'):
        budget(tmp_path / 'ledger.jsonl', final_training_reserve=True)


def test_failures_and_cache_hits_charged_and_protected_stages_available(tmp_path):
    b = budget(tmp_path / 'ledger.jsonl')
    t = b.reserve('screen')
    b.finish(t, status='failed', cache_hit=False, engine_invoked=False,
             metadata={'error': 'pre-engine input failure'})
    t = b.reserve('design')
    b.finish(t, status='completed', cache_hit=True, engine_invoked=False)
    t = b.reserve('search')
    b.finish(t, status='failed', cache_hit=False, engine_invoked=True)
    with pytest.raises(BudgetExhaustedError):
        b.reserve('search')
    for stage in ('final_training', 'validation'):
        t = b.reserve(stage)
        b.finish(t, status='completed', cache_hit=False, engine_invoked=True)
        with pytest.raises(BudgetExhaustedError):
            b.reserve(stage)
    s = b.snapshot()
    assert s['charged_requests'] == 5
    assert s['cache_hits'] == 1 and s['engine_wrapper_calls'] == 3
    assert s['status_counts'] == {'completed': 3, 'failed': 2, 'interrupted': 0}
    assert s['remaining_discretionary'] == s['remaining_final_training'] == s['remaining_validation'] == 0


def test_resume_retains_unfinished_reservations_without_refund(tmp_path):
    path = tmp_path / 'ledger.jsonl'
    first = budget(path)
    token = first.reserve('search')
    reserved_bytes = path.read_bytes()
    resumed = budget(path)
    assert path.read_bytes() == reserved_bytes
    assert resumed.snapshot()['pending_reservations'] == [token.reservation_id]
    assert resumed.snapshot()['charged_requests'] == 1
    resumed.finish(token, status='interrupted', cache_hit=False, engine_invoked=True)
    assert resumed.snapshot()['status_counts']['interrupted'] == 1
    assert resumed.snapshot()['charged_requests'] == 1


def test_wrong_context_configuration_foreign_token_or_duplicate_finish_rejected(tmp_path):
    path = tmp_path / 'ledger.jsonl'
    b = budget(path)
    token = b.reserve('search')
    for kwargs in ({'context': {**CONTEXT, 'objective': 'changed'}}, {'total_cap': 6}, {'planned_screen': 1}):
        with pytest.raises(BudgetLedgerError, match='identity mismatch'):
            budget(path, **kwargs)
    with pytest.raises(BudgetLedgerError, match='foreign'):
        budget(tmp_path / 'other.jsonl').finish(token, status='failed', cache_hit=False, engine_invoked=False)
    b.finish(token, status='completed', cache_hit=False, engine_invoked=True)
    with pytest.raises(BudgetLedgerError, match='already finished'):
        b.finish(token, status='completed', cache_hit=False, engine_invoked=True)


def test_identity_and_metadata_require_finite_json_and_stages_are_declared(tmp_path):
    with pytest.raises(ValueError, match='finite JSON'):
        budget(tmp_path / 'bad.jsonl', context={'objective': float('nan')})
    b = budget(tmp_path / 'good.jsonl')
    with pytest.raises(ValueError, match='Unknown budget stage'):
        b.reserve('final_trainng')
    token = b.reserve('search')
    with pytest.raises(ValueError, match='finite JSON'):
        b.finish(token, status='failed', cache_hit=False, engine_invoked=False, metadata={'bad': float('inf')})
    assert b.snapshot()['pending_reservations'] == [token.reservation_id]
    with pytest.raises(ValueError, match='cache hit'):
        b.finish(token, status='completed', cache_hit=True, engine_invoked=True)


def test_threaded_multiple_instances_reserve_atomically(tmp_path):
    path = tmp_path / 'ledger.jsonl'
    instances = [budget(path), budget(path)]
    def reserve(i):
        try:
            return instances[i % 2].reserve('search')
        except BudgetExhaustedError:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        tokens = [t for t in pool.map(reserve, range(30)) if t]
    assert len(tokens) == 3
    assert len({t.reservation_id for t in tokens}) == 3
    assert instances[0].snapshot()['charged_requests'] == 3


def _process_reserve(path, queue):
    b = budget(Path(path))
    try:
        queue.put(b.reserve('search').reservation_id)
    except BudgetExhaustedError:
        queue.put(None)


def test_posix_processes_share_atomic_capacity(tmp_path):
    context = multiprocessing.get_context('spawn')
    path = tmp_path / 'ledger.jsonl'
    budget(path)
    queue = context.Queue()
    workers = [context.Process(target=_process_reserve, args=(str(path), queue)) for _ in range(8)]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=30) for _ in workers]
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0
    assert len([r for r in results if r is not None]) == 3
    assert budget(path).snapshot()['charged_requests'] == 3


def test_corruption_or_truncation_rejected_without_refund(tmp_path):
    path = tmp_path / 'ledger.jsonl'
    b = budget(path)
    b.reserve('search')
    original = path.read_bytes()
    path.write_bytes(original[:-1])
    with pytest.raises(BudgetLedgerError):
        budget(path)
    path.write_bytes(original)
    records = [json.loads(line) for line in original.splitlines()]
    records[1]['stage'] = 'validation'
    path.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
    with pytest.raises(BudgetLedgerError, match='chain'):
        b.snapshot()


def test_digest_valid_but_impossible_transition_fails_closed(tmp_path):
    path = tmp_path / 'ledger.jsonl'
    b = budget(path)
    token = b.reserve('search')
    b.finish(token, status='completed', cache_hit=False, engine_invoked=True)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    duplicate = {**records[-1], 'seq': 3, 'prev_sha256': records[-1]['sha256']}
    duplicate.pop('sha256')
    duplicate['sha256'] = hashlib.sha256(json.dumps(duplicate, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    with path.open('a') as stream:
        stream.write(json.dumps(duplicate) + '\n')
    with pytest.raises(BudgetLedgerError, match='duplicate completion'):
        b.snapshot()


def test_unsupported_lock_platform_fails_before_creation(monkeypatch, tmp_path):
    from swatplus_builder.calibration import evaluation_budget
    monkeypatch.setattr(evaluation_budget, 'fcntl', None)
    with pytest.raises(RuntimeError, match='platform unsupported'):
        budget(tmp_path / 'ledger.jsonl')
    assert not (tmp_path / 'ledger.jsonl').exists()


def test_reserved_slots_stay_protected_when_used_before_search(tmp_path):
    b = budget(tmp_path / 'ledger.jsonl')
    b.reserve('validation')
    b.reserve('final_training')
    for _ in range(3):
        b.reserve('search')
    with pytest.raises(BudgetExhaustedError):
        b.reserve('search')
    assert b.snapshot()['charged_requests'] == 5


def test_nested_nonstring_identity_keys_cannot_collide(tmp_path):
    with pytest.raises(ValueError, match='finite JSON'):
        budget(tmp_path / 'ledger.jsonl', context={'nested': {1: 'x'}})
    assert not (tmp_path / 'ledger.jsonl').exists()
