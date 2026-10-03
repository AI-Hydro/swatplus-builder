"""Prepare sealed full-vector development designs; never launch the engine.

Fifteen shared design points and one search/fresh-training/validation request
per arm fit an 18-request attributed budget. This is preparation, not an
optimizer comparison, and reveals no validation observations or results.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from swatplus_builder.calibration.experiment_design import make_shared_design
from swatplus_builder.calibration.real_engine import _copy_fresh_txtinout, _staged_input_identity
from swatplus_builder.full_mode.parameter_bridge import apply_parameters_to_full_swat_txtinout
from swatplus_builder.params.registry import get_parameter
from swatplus_builder.run.swatplus import locate_binary

BASINS = ('12054000', '01592500', '03042280')
_ELIGIBLE = {'active', 'weak', 'limited'}


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def screened_bounds(payload: dict[str, Any]) -> tuple[dict[str, tuple[float, float]], dict[str, Any]]:
    """Use tested screen endpoints; explicitly account for skipped-default endpoints."""
    rows = payload.get('parameters')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing basin-specific sensitivity parameter rows')
    bounds, evidence = {}, {}
    names = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('parameter'), str):
            raise ValueError('Malformed screen parameter row')
        name = row['parameter']
        if name in names:
            raise ValueError(f'Duplicate sensitivity parameter: {name}')
        names.append(name)
        if row.get('activity_class') not in _ELIGIBLE:
            continue
        spec = get_parameter(name)
        governed = tuple(float(v) for v in spec.range)
        tested = {}
        for bound in (row.get('evidence') or {}).get('bound_results', []):
            label, value = bound.get('bound'), bound.get('value')
            if label not in {'lower', 'upper'} or isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'Malformed tested endpoint for {name}')
            endpoint = 0 if label == 'lower' else 1
            if (label in tested or not math.isfinite(value)
                    or not math.isclose(float(value), governed[endpoint], rel_tol=0, abs_tol=1e-12)):
                raise ValueError(f'Screen endpoint disagrees with governed registry for {name}')
            tested[label] = float(value)
        if not tested:
            raise ValueError(f'No tested screen endpoints for retained parameter {name}')
        supplements = {}
        for endpoint, label in enumerate(('lower', 'upper')):
            if label not in tested:
                # The screen deliberately skips registry-default endpoints.
                # Do not treat an arbitrary missing/failed endpoint as an observed bound.
                if not math.isclose(float(spec.default), governed[endpoint], rel_tol=0, abs_tol=1e-12):
                    raise ValueError(f'Incomplete screen endpoints for {name}; missing {label} is not a default endpoint')
                supplements[label] = governed[endpoint]
        bounds[name] = governed
        evidence[name] = {'screen_tested_endpoints': tested,
                          'registry_default_endpoint_supplement': supplements,
                          'activity_class': row['activity_class']}
    if not bounds:
        raise ValueError('No eligible full-vector parameters in basin-specific screen')
    return bounds, evidence


def prepare_preflight(pe1_root: Path, binary: Path, *, seed: int = 42) -> dict[str, Any]:
    pe1_root, binary = pe1_root.resolve(), binary.resolve()
    if not binary.is_file():
        raise ValueError('Engine binary is required for identity sealing, not execution')
    engine_sha = file_sha(binary)
    from swatplus_builder.calibration import experiment_design
    from swatplus_builder.full_mode import parameter_bridge
    registry = importlib.import_module("swatplus_builder.params.registry")
    code_sources = {
        'experiment_design': file_sha(Path(experiment_design.__file__)),
        'parameter_bridge': file_sha(Path(parameter_bridge.__file__)),
        'parameter_registry': file_sha(Path(registry.__file__)),
        'preflight_script': file_sha(Path(__file__)),
    }
    result: dict[str, Any] = {
        'schema': 'calibration_fullvector_preflight_v1',
        'status': 'prepared_not_executed',
        'scope': 'exposed retained development basins; warm model inputs; no confirmatory comparison',
        'engine_calls': 0,
        'contains_validation_observation_values': False,
        'engine': {'path': str(binary), 'sha256': engine_sha},
        'code_sha256': code_sources,
        'seed': seed,
        'budget_per_arm': {
            'total_cap': 18, 'screen': 0, 'design': 15, 'search': 1,
            'final_training': 1, 'validation': 1,
            'screen_accounting': 'historical screening reused and separately disclosed; no fresh screen executed',
            'attribution': 'shared design has 15 requests attributed to each arm; actual shared calls counted separately',
            'interpretation': 'one adaptive request is an integration test, not convergence evidence',
        },
        'basins': [],
    }
    for gauge in BASINS:
        basin = pe1_root / f'usgs_{gauge}'
        source = basin / 'calibration/locked_calibrated_TxtInOut'
        screen = basin / 'calibration/sensitivity_screen_locked/sensitivity_screen.json'
        lock_path = basin / 'benchmark/benchmark_lock.json'
        alignment = basin / 'benchmark/alignment.csv'
        for path in (source, screen, lock_path, alignment):
            if not path.exists():
                raise ValueError(f'Missing required retained input: {path}')
        source_sha = _staged_input_identity(source)
        screen_sha, lock_sha, alignment_sha = file_sha(screen), file_sha(lock_path), file_sha(alignment)
        lock = json.loads(lock_path.read_text())
        screen_payload = json.loads(screen.read_text())
        if (lock.get('basin_id') != f'usgs_{gauge}'
                or lock.get('alignment_sha256') != alignment_sha
                or screen_payload.get('basin_id') != f'usgs_{gauge}'
                or screen_payload.get('basis') != 'basin_specific'):
            raise ValueError(f'Retained benchmark/screen identity mismatch for {gauge}')
        bounds, provenance = screened_bounds(screen_payload)
        design = make_shared_design(bounds, 15, seed=seed, required_backend='rbf')
        expected_keys = set(bounds)
        applied_sha = []
        with tempfile.TemporaryDirectory(prefix=f'swatplus_fullvector_preflight_{gauge}_') as temp:
            for index, point in enumerate(design.points):
                if set(point) != expected_keys:
                    raise ValueError('Incomplete full-vector design; default filling is prohibited')
                copied = Path(temp) / f'point_{index}'
                _copy_fresh_txtinout(source, copied)
                if _staged_input_identity(copied) != source_sha:
                    raise ValueError('Temporary preflight copy differs from source inputs')
                apply_parameters_to_full_swat_txtinout(copied, point)
                applied_sha.append(_staged_input_identity(copied))
                # Free copied inputs before staging the next candidate.
                import shutil
                shutil.rmtree(copied)
        if (_staged_input_identity(source) != source_sha or file_sha(screen) != screen_sha
                or file_sha(lock_path) != lock_sha or file_sha(alignment) != alignment_sha):
            raise ValueError(f'Retained inputs changed during preflight for {gauge}')
        result['basins'].append({
            'gauge': gauge, 'source': str(source), 'source_input_sha256': source_sha,
            'screen_path': str(screen), 'benchmark_lock_path': str(lock_path),
            'benchmark_alignment_path': str(alignment),
            'screen_sha256': screen_sha, 'benchmark_lock_sha256': lock_sha,
            'benchmark_alignment_sha256': alignment_sha,
            'bounds': bounds, 'bound_provenance': provenance,
            'full_vector_design': design.to_json(),
            'bridge_preflight': {'status': 'all_design_vectors_applied_to_fresh_temporary_inputs',
                                'applied_input_sha256': applied_sha, 'engine_executed': False,
                                'interpretation': 'Bridge writers completed; engine response and physical validity are not assessed.'},
            'scientific_status': 'not_verified_by_preflight',
            'source_issue': 'historical promotion invalidated by non-finite water-balance evidence; cause unresolved'
                if gauge == '03042280' else None,
            'inherited_unscreened_values': 'Only parameters excluded by the recorded screen remain fixed in the sealed source; every opened parameter is explicit.',
        })
    current_code = {
        'experiment_design': file_sha(Path(experiment_design.__file__)),
        'parameter_bridge': file_sha(Path(parameter_bridge.__file__)),
        'parameter_registry': file_sha(Path(registry.__file__)),
        'preflight_script': file_sha(Path(__file__)),
    }
    if current_code != code_sources:
        raise ValueError('Preparation code changed during preflight')
    if file_sha(binary) != engine_sha:
        raise ValueError('Engine identity changed during preparation')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pe1-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    pe1 = args.pe1_root.expanduser().resolve()
    if out.exists() or out.is_relative_to(pe1):
        raise ValueError('Use a new output file outside historical evidence; overwrite prohibited')
    binary = args.binary if args.binary is not None else locate_binary()
    report = prepare_preflight(pe1, binary, seed=args.seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against an output appearing during preflight.
    with out.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    print(str(out))


if __name__ == '__main__':
    main()
