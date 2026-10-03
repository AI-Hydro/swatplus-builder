"""Evaluation shares parsed sources while preserving outlet and metric evidence."""
from pathlib import Path

import pandas as pd
import pytest

from swatplus_builder.output import eval as evaluator


@pytest.fixture
def channel_case(tmp_path):
    path = tmp_path / 'channel_sd_day.txt'
    lines = ['channel_sd_day', 'jday mon day yr unit gis_id name flo_out',
             'n/a n/a n/a n/a n/a n/a n/a m3/s']
    for gid, values in ((1, [0.2, 0.3, 0.4]), (7, [1., 2., 3.]), (8, [.5, 1., 1.5])):
        lines += [f'{d} 1 {d} 2015 {gid} {gid} cha{gid} {flow}'
                  for d, flow in enumerate(values, 1)]
    path.write_text('\n'.join(lines) + '\n')
    (tmp_path / 'chandeg.con').write_text(
        'chandeg.con\n'
        'id name gis_id area lat lon elev lcha wst cst ovfl rule out_tot obj_typ obj_id hyd_typ frac\n'
        '1 cha1 1 0 0 0 0 1 s 0 0 0 1 sdc 7 tot 1.0\n'
        '7 cha7 7 0 0 0 0 7 s 0 0 0 1 out 1 tot 1.0\n'
        '8 cha8 8 0 0 0 0 8 s 0 0 0 1 out 1 tot 1.0\n'
    )
    obs = pd.Series([1., 2., 3.], index=pd.date_range('2015-01-01', periods=3))
    return path, obs


@pytest.mark.parametrize('policy,gid,expected_reads', [
    ('strict', 1, 3),
    ('strict', 7, 2),
    ('auto', 1, 2),
    ('best_terminal_nse', 1, 3),
    ('all_terminal_sum', 1, 2),
])
def test_metrics_diagnostics_alignment_equal_to_uncached_path(
    monkeypatch, channel_case, tmp_path, policy, gid, expected_reads,
):
    path, obs = channel_case
    actual_reader = evaluator.read_output_file
    shared_reader = evaluator._evaluation_table
    calls = []

    def counted(source):
        calls.append(Path(source))
        return actual_reader(source)

    monkeypatch.setattr(evaluator, 'read_output_file', counted)
    monkeypatch.setattr(evaluator, '_evaluation_table', lambda source, tables: counted(source))
    baseline = evaluator.evaluate_run(path, obs, gid, outlet_policy=policy,
                                     return_diagnostics=True, out_alignment_csv=tmp_path / 'old.csv')
    assert len(calls) == expected_reads
    calls.clear()
    monkeypatch.setattr(evaluator, '_evaluation_table', shared_reader)
    revised = evaluator.evaluate_run(path, obs, gid, outlet_policy=policy,
                                    return_diagnostics=True, out_alignment_csv=tmp_path / 'new.csv')
    assert calls == [path]
    pd.testing.assert_frame_equal(baseline[0], revised[0])
    assert baseline[1] == revised[1]
    assert baseline[2] == revised[2]
    assert (tmp_path / 'old.csv').read_bytes() == (tmp_path / 'new.csv').read_bytes()
    if policy == 'strict':
        assert revised[2]['selected_outlet_gis_id'] == gid
        assert not revised[2]['outlet_autodetected']
    assert revised[2]['terminal_scope_metrics_available']
    assert revised[2]['terminal_scope_metric_terminal_ids'] == [7, 8]


def test_cache_is_call_local_and_does_not_reuse_changed_outputs(monkeypatch, channel_case):
    path, obs = channel_case
    actual_reader = evaluator.read_output_file
    calls = []
    def counted(source):
        calls.append(Path(source))
        return actual_reader(source)
    monkeypatch.setattr(evaluator, 'read_output_file', counted)
    first = evaluator.evaluate_run(path, obs, 7, outlet_policy='strict', return_diagnostics=True)
    path.write_text(path.read_text().replace('cha7 1.0', 'cha7 1.5'))
    second = evaluator.evaluate_run(path, obs, 7, outlet_policy='strict', return_diagnostics=True)
    assert calls == [path, path]
    assert first[0]['sim'].iloc[0] == 1.
    assert second[0]['sim'].iloc[0] == 1.5
    assert first[2]['sim_source_sha256'] != second[2]['sim_source_sha256']


def test_fallback_sources_each_parsed_once(monkeypatch, channel_case, tmp_path):
    path, obs = channel_case
    original = path.read_text()
    fallback = tmp_path / 'basin_sd_cha_day.txt'
    fallback.write_text(original.replace('channel_sd_day', 'basin_sd_cha_day'))
    path.write_text(original.replace('cha7 1.0', 'cha7 0.0')
                   .replace('cha7 2.0', 'cha7 0.0').replace('cha7 3.0', 'cha7 0.0'))
    actual_reader = evaluator.read_output_file
    calls = []
    def counted(source):
        calls.append(Path(source))
        return actual_reader(source)
    monkeypatch.setattr(evaluator, 'read_output_file', counted)
    frame, metrics, diag = evaluator.evaluate_run(path, obs, 7, outlet_policy='strict', return_diagnostics=True)
    assert calls == [path, fallback]
    assert diag['sim_source_file'] == fallback.name
    assert metrics['nse'] == 1.
    assert frame['sim'].tolist() == [1., 2., 3.]
