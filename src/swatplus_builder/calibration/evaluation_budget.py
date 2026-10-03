"""Durable whole-workflow objective-request budgets on POSIX filesystems.

Every reservation counts, including cache hits, failed calls and unfinished
requests recovered after interruption. Protected final-training and validation
slots cannot be consumed by screening/design/search. These are request counts,
not subprocess-launch counts. The caller supplies the complete sealed scientific
context (inputs, observations, simulation, objective and gate versions).
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # Fail closed rather than promise unsupported locking.
    fcntl = None


STAGES = frozenset({'screen', 'design', 'search', 'final_training', 'validation'})
_STATUSES = frozenset({'completed', 'failed', 'interrupted'})
_SCHEMA = 'whole_workflow_objective_requests_v1'
_ZERO_HASH = '0' * 64


class BudgetExhaustedError(RuntimeError):
    """The requested stage cannot reserve another objective request."""


class BudgetLedgerError(ValueError):
    """A ledger is corrupt or does not match the sealed workflow identity."""


@dataclass(frozen=True)
class BudgetToken:
    """Opaque identity of a durable, charged reservation."""
    ledger_id: str
    reservation_id: str
    stage: str


def _canonical(value: Any) -> str:
    def validate_keys(item: Any) -> None:
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise ValueError('JSON object keys must be strings')
            for nested in item.values():
                validate_keys(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                validate_keys(nested)
    try:
        validate_keys(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Budget identities and metadata must be finite JSON values') from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _count(name: str, value: int, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(f'{name} must be a {"positive" if positive else "nonnegative"} integer')
    return value


class EvaluationBudget:
    """Append-only, hash-chained requests with cross-process POSIX flock.

    Each operation replays the ledger under a sidecar-file lock; two instances
    or processes using the same resolved ledger path see the same state. The
    ledger must remain on a filesystem with working flock/fsync semantics.
    Unsupported platforms fail before ledger creation. Hashes detect accidental
    corruption, not deliberate rewriting by a party who controls the files.
    """

    def __init__(
        self, path: Path | str, *, total_cap: int, context: Mapping[str, Any],
        final_training_reserve: int = 1, validation_reserve: int = 1,
        planned_screen: int = 0, planned_design: int = 0,
    ) -> None:
        if fcntl is None:
            raise RuntimeError('EvaluationBudget requires POSIX fcntl.flock; platform unsupported')
        total_cap = _count('total_cap', total_cap, positive=True)
        final_training_reserve = _count('final_training_reserve', final_training_reserve)
        validation_reserve = _count('validation_reserve', validation_reserve)
        planned_screen = _count('planned_screen', planned_screen)
        planned_design = _count('planned_design', planned_design)
        if not isinstance(context, Mapping) or not context or any(not isinstance(k, str) for k in context):
            raise ValueError('A nonempty scientific context with string keys is required')
        context_copy = json.loads(_canonical(dict(context)))
        if planned_screen + planned_design + final_training_reserve + validation_reserve > total_cap:
            raise ValueError('Planned screening/design and protected reserves exceed total_cap')
        self.path = Path(path).expanduser().resolve()
        self._lock_path = self.path.with_name(self.path.name + '.lock')
        self._thread_lock = threading.RLock()
        self._config = {
            'schema': _SCHEMA, 'total_cap': total_cap, 'context': context_copy,
            'final_training_reserve': final_training_reserve,
            'validation_reserve': validation_reserve,
            'planned_screen': planned_screen, 'planned_design': planned_design,
        }
        self._identity = _digest(self._config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            if not self.path.exists():
                self._append({
                    'kind': 'init', 'ledger_id': uuid4().hex,
                    'identity_sha256': self._identity, 'config': self._config,
                }, seq=0, previous=_ZERO_HASH)
            self._replay()

    @contextmanager
    def _locked(self):
        with self._thread_lock, self._lock_path.open('a+b') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _append(self, payload: dict[str, Any], *, seq: int, previous: str) -> None:
        import os
        record = {**payload, 'seq': seq, 'prev_sha256': previous}
        record['sha256'] = _digest(record)
        creating = not self.path.exists()
        # A completed fsync precedes returning a token and hence the callback.
        with self.path.open('ab') as handle:
            handle.write((_canonical(record) + '\n').encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        if creating:
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def _replay(self) -> dict[str, Any]:
        try:
            raw = self.path.read_bytes()
            if not raw or not raw.endswith(b'\n'):
                raise BudgetLedgerError('Empty or interrupted/truncated ledger; no reservations are refunded')
            records = [json.loads(line) for line in raw.splitlines()]
        except (OSError, ValueError, UnicodeError) as exc:
            raise BudgetLedgerError('Unreadable or truncated budget ledger') from exc
        previous = _ZERO_HASH
        reservations: dict[str, dict[str, Any]] = {}
        used = {stage: 0 for stage in STAGES}
        ledger_id = None
        for seq, record in enumerate(records):
            if not isinstance(record, dict):
                raise BudgetLedgerError('Invalid ledger record')
            sealed = {k: v for k, v in record.items() if k != 'sha256'}
            try:
                valid_hash = record.get('sha256') == _digest(sealed)
            except ValueError as exc:
                raise BudgetLedgerError('Non-finite or invalid ledger payload') from exc
            if (type(record.get('seq')) is not int or record['seq'] != seq
                    or record.get('prev_sha256') != previous or not valid_hash):
                raise BudgetLedgerError('Ledger sequence or digest chain is corrupt')
            previous = record['sha256']
            kind = record.get('kind')
            if seq == 0:
                if (kind != 'init' or record.get('config') != self._config
                        or record.get('identity_sha256') != self._identity
                        or not isinstance(record.get('ledger_id'), str) or not record['ledger_id']):
                    raise BudgetLedgerError('Budget context/configuration identity mismatch')
                ledger_id = record['ledger_id']
                continue
            reservation_id = record.get('reservation_id')
            if not isinstance(reservation_id, str) or not reservation_id:
                raise BudgetLedgerError('Missing reservation identity')
            if kind == 'reserve':
                stage = record.get('stage')
                if stage not in STAGES or reservation_id in reservations:
                    raise BudgetLedgerError('Unknown stage or duplicate reservation')
                used[stage] += 1
                reservations[reservation_id] = {'stage': stage, 'completion': None}
                self._validate_used(used)
            elif kind == 'finish':
                reservation = reservations.get(reservation_id)
                if (reservation is None or reservation['completion'] is not None
                        or record.get('stage') != reservation['stage']
                        or record.get('status') not in _STATUSES
                        or type(record.get('cache_hit')) is not bool
                        or type(record.get('engine_invoked')) is not bool
                        or not isinstance(record.get('metadata'), dict)):
                    raise BudgetLedgerError('Invalid or duplicate completion')
                if record['cache_hit'] and record['engine_invoked']:
                    raise BudgetLedgerError('A cache hit cannot also invoke the engine wrapper')
                reservation['completion'] = record
            else:
                raise BudgetLedgerError('Unknown ledger event')
        return {'ledger_id': ledger_id, 'reservations': reservations, 'used': used,
                'next_seq': len(records), 'previous': previous}

    def _validate_used(self, used: dict[str, int]) -> None:
        discretionary = used['screen'] + used['design'] + used['search']
        protected = self._config['final_training_reserve'] + self._config['validation_reserve']
        if (sum(used.values()) > self._config['total_cap']
                or discretionary > self._config['total_cap'] - protected
                or used['final_training'] > self._config['final_training_reserve']
                or used['validation'] > self._config['validation_reserve']):
            raise BudgetLedgerError('Recorded requests exceed budget/reservation policy')

    def reserve(self, stage: str) -> BudgetToken:
        """Charge a slot durably before calling an objective; never silently refund."""
        if stage not in STAGES:
            raise ValueError(f'Unknown budget stage: {stage}')
        with self._locked():
            state = self._replay()
            used = dict(state['used'])
            used[stage] += 1
            try:
                self._validate_used(used)
            except BudgetLedgerError as exc:
                raise BudgetExhaustedError(f'No request capacity remains for stage {stage}') from exc
            reservation_id = uuid4().hex
            self._append({'kind': 'reserve', 'reservation_id': reservation_id, 'stage': stage},
                         seq=state['next_seq'], previous=state['previous'])
            return BudgetToken(state['ledger_id'], reservation_id, stage)

    def finish(
        self, token: BudgetToken, *, status: str, cache_hit: bool,
        engine_invoked: bool, metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Record an outcome; engine_invoked means wrapper called, not subprocess receipt."""
        if status not in _STATUSES or type(cache_hit) is not bool or type(engine_invoked) is not bool:
            raise ValueError('Completion requires a known status and explicit boolean call metadata')
        if cache_hit and engine_invoked:
            raise ValueError('A cache hit cannot also invoke the engine wrapper')
        metadata_copy = json.loads(_canonical(dict(metadata or {})))
        with self._locked():
            state = self._replay()
            reservation = state['reservations'].get(token.reservation_id)
            if (token.ledger_id != state['ledger_id'] or reservation is None
                    or token.stage != reservation['stage'] or reservation['completion'] is not None):
                raise BudgetLedgerError('Unknown, foreign or already finished reservation token')
            self._append({'kind': 'finish', 'reservation_id': token.reservation_id,
                          'stage': token.stage, 'status': status, 'cache_hit': cache_hit,
                          'engine_invoked': engine_invoked, 'metadata': metadata_copy},
                         seq=state['next_seq'], previous=state['previous'])

    def snapshot(self) -> dict[str, Any]:
        """Replay current requests and explicit remaining protected/discretionary slots."""
        with self._locked():
            state = self._replay()
            reservations = state['reservations']
            completed = [r['completion'] for r in reservations.values() if r['completion'] is not None]
            used = state['used']
            protected = self._config['final_training_reserve'] + self._config['validation_reserve']
            return {
                'schema': _SCHEMA, 'ledger_id': state['ledger_id'],
                'identity_sha256': self._identity, 'total_cap': self._config['total_cap'],
                'charged_requests': len(reservations), 'used_by_stage': dict(used),
                'pending_reservations': [reservation_id for reservation_id, r in reservations.items()
                                         if r['completion'] is None],
                'status_counts': {status: sum(r['status'] == status for r in completed) for status in _STATUSES},
                'cache_hits': sum(r['cache_hit'] for r in completed),
                'engine_wrapper_calls': sum(r['engine_invoked'] for r in completed),
                'engine_call_count_basis': 'reported run_swat wrapper attempts; not subprocess launches',
                'remaining_discretionary': self._config['total_cap'] - protected
                    - used['screen'] - used['design'] - used['search'],
                'remaining_final_training': self._config['final_training_reserve'] - used['final_training'],
                'remaining_validation': self._config['validation_reserve'] - used['validation'],
                'ledger_event_count': state['next_seq'], 'ledger_head_sha256': state['previous'],
            }
