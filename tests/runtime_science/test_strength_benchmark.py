"""Synthetic contract fixtures, separate from the native field-data receipt."""
import csv
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

HEADER = 'cluster,id,tipo,UTM_N,UTM_E,depth(m),BD(g/cm3),VWC(m3/m3),PR(Mpa),Sand(%),Silt(%),Clay(%),EC(fdem),EC(ert)'.split(',')


def native_csv(rows):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return stream.getvalue().encode()


def row(cluster='1', identity='1', depth='0.1', water='0.24', pr='1.77'):
    return [cluster, identity, 'tramline', '5026203.506', '730851.6209', depth, '1.49', water, pr, '18.4', '53.5', '28.2', '4.73', '34.1']


def test_native_schema_preserves_missing_water_and_unnormalized_texture():
    from research.soil_strength_benchmark import parse_database

    result = parse_database(native_csv([row(), row(depth='0.2', water='')]))
    assert len(result) == 2
    assert result[0]['PR(Mpa)'] == 1.77
    assert result[0]['VWC(m3/m3)'] == 0.24
    assert result[0]['Sand(%)'] == 18.4
    assert result[0]['Clay(%)'] == 28.2
    assert result[0]['profile_key'] == '1:1'
    assert result[0]['source_row'] == 2
    assert result[1]['VWC(m3/m3)'] is None


@pytest.mark.parametrize(('index', 'value'), [(0, ' 1'), (1, '01'), (2, 'unknown'), (3, 'NaN'), (5, '0'), (6, '0'), (7, '1.01'), (8, '-1'), (8, 'NaN'), (9, '101')])
def test_rejects_invalid_identifiers_units_or_numeric_states(index, value):
    from research.soil_strength_benchmark import parse_database

    values = row()
    values[index] = value
    with pytest.raises(ValueError):
        parse_database(native_csv([values]))


@pytest.mark.parametrize('fault', ['duplicate', 'point_shift', 'empty', 'row_budget', 'byte_budget', 'header', 'extra_field'])
def test_native_reader_does_not_silently_change_scope(fault):
    from research.soil_strength_benchmark import parse_database

    a, b = row(), row(depth='0.2')
    if fault == 'duplicate':
        b = a.copy()
    elif fault == 'point_shift':
        b[3] = '5000000'
    raw = native_csv([a, b])
    if fault == 'empty':
        raw = native_csv([])
    elif fault == 'row_budget':
        raw = native_csv([row(identity=str(i + 1)) for i in range(1025)])
    elif fault == 'byte_budget':
        raw = b'x' * 262145
    elif fault == 'header':
        raw = raw.replace(b'PR(Mpa)', b'PR(kPa)')
    elif fault == 'extra_field':
        raw = native_csv([a + ['hidden']])
    with pytest.raises(ValueError):
        parse_database(raw)


def linear_fixture():
    values = []
    for cluster in range(1, 5):
        for identity, water in enumerate((0.1, 0.2, 0.3), 1):
            item = row(str(cluster), str(identity), water=str(water), pr=str(1 + 2 * water))
            item[3] = str(5_000_000 + 100 * cluster + identity)
            values.append(item)
    return values


def test_cluster_holdout_fits_only_training_rows_and_scores_every_eligible_row_once():
    from research.soil_strength_benchmark import benchmark_csv

    values = linear_fixture()
    result = benchmark_csv(native_csv(values))
    assert result['status'] == 'research_only'
    assert result['eligible_rows'] == 12
    assert len(result['folds']) == 4
    assert result['pooled_metrics']['ols']['mae_mpa'] == pytest.approx(0, abs=1e-12)
    assert result['pooled_metrics']['training_mean']['mae_mpa'] > 0
    predicted_rows = []
    for fold in result['folds']:
        assert fold['test_cluster'] not in fold['training_clusters']
        assert set(fold['training_profiles']).isdisjoint(fold['test_profiles'])
        predicted_rows.extend(item['source_row'] for item in fold['predictions'])
    assert len(predicted_rows) == len(set(predicted_rows)) == result['eligible_rows']
    for item in values:
        if item[0] == '1':
            item[8] = str(float(item[8]) + 100)
    changed = benchmark_csv(native_csv(values))
    assert changed['folds'][0]['coefficients'] == result['folds'][0]['coefficients']
    assert changed['folds'][0]['metrics'] != result['folds'][0]['metrics']
    assert result['validation_scope'] == 'one_site_exploratory_cluster_holdout_not_external_validation'
    assert {'passability', 'recovery', 'bearing_capacity'} <= set(result['not_computed'])


def test_cli_executes_csv_and_refuses_to_replace_receipt(tmp_path):
    raw = native_csv(linear_fixture())
    source, output = tmp_path / 'synthetic.csv', tmp_path / 'result.json'
    source.write_bytes(raw)
    command = [sys.executable, '-m', 'research.soil_strength_benchmark', '--csv', str(source), '--output', str(output)]
    first = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert first.returncode == 0, first.stderr
    saved = output.read_bytes()
    assert json.loads(saved) == json.loads(first.stdout)
    assert json.loads(saved)['eligible_rows'] == 12
    again = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert again.returncode == 2
    assert json.loads(again.stdout)['status'] == 'failed'
    assert output.read_bytes() == saved


def test_missing_or_deep_rows_are_counted_but_never_imputed_into_cohort():
    from research.soil_strength_benchmark import benchmark_csv

    values = linear_fixture()
    values.append(row('5', depth='0.1', water=''))
    values.append(row('5', depth='0.7', water='0.2'))
    result = benchmark_csv(native_csv(values))
    assert result['native_rows'] == 14
    assert result['paired_core_rows'] == 13
    assert result['missing_core_rows'] == 1
    assert result['eligible_rows'] == 12
    assert all(fold['test_cluster'] != '5' for fold in result['folds'])


@pytest.mark.parametrize('fault', ['too_few_clusters', 'constant_water'])
def test_underidentified_benchmark_does_not_return_partial_metrics(fault):
    from research.soil_strength_benchmark import benchmark_csv

    values = linear_fixture()
    if fault == 'too_few_clusters':
        values = [item for item in values if item[0] in ('1', '2')]
    else:
        for item in values:
            item[7] = '0.2'
    with pytest.raises(ValueError):
        benchmark_csv(native_csv(values))
