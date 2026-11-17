"""Offline native soil-strength benchmark; no vehicle or trip assessment."""
from __future__ import annotations

import csv
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
from statistics import fmean

HEADER = 'cluster,id,tipo,UTM_N,UTM_E,depth(m),BD(g/cm3),VWC(m3/m3),PR(Mpa),Sand(%),Silt(%),Clay(%),EC(fdem),EC(ert)'.split(',')
CORE = ('depth(m)', 'BD(g/cm3)', 'VWC(m3/m3)', 'PR(Mpa)', 'Sand(%)', 'Silt(%)', 'Clay(%)')


def parse_database(raw: bytes) -> list[dict]:
    """Preserve the native column identities, missing values and profile grouping."""
    if type(raw) is not bytes or len(raw) > 262_144:
        raise ValueError('Native CSV exceeds the 256 KiB implementation read budget.')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
    if reader.fieldnames != HEADER:
        raise ValueError('Native field names/order differ; no header normalization is applied.')
    result: list[dict] = []
    seen: set[tuple[str, float]] = set()
    profiles: dict[str, tuple[str, str, str]] = {}
    for source in reader:
        if len(result) >= 1024 or None in source or any(value is None for value in source.values()):
            raise ValueError('Row budget or native row shape violated.')
        if any(not re.fullmatch(r'[1-9][0-9]{0,3}', source[field]) for field in ('cluster', 'id')) or source['tipo'] not in {'tramline', 'cross', 'uncomp', 'heavy_comp'}:
            raise ValueError('Invalid literal profile identity or treatment.')
        if any(not math.isfinite(float(source[field])) for field in ('UTM_N', 'UTM_E')):
            raise ValueError('Invalid native coordinate; no CRS is inferred.')
        record: dict = dict(source)
        for field in CORE:
            value = None if source[field] == '' else float(source[field])
            if value is not None:
                if not math.isfinite(value) or not 0 <= value <= 1e12:
                    raise ValueError('Invalid finite/nonnegative native number or implementation magnitude bound.')
                if (field == 'VWC(m3/m3)' and value > 1) or (field.endswith('(%)') and value > 100) or (field == 'BD(g/cm3)' and value == 0):
                    raise ValueError('Number contradicts the declared native unit.')
            record[field] = value
        if record['depth(m)'] not in {0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7}:
            raise ValueError('Unsupported native depth label; no depth interpolation.')
        record['profile_key'] = source['cluster'] + ':' + source['id']
        record['source_row'] = reader.line_num
        key = (record['profile_key'], record['depth(m)'])
        location = (source['tipo'], source['UTM_N'], source['UTM_E'])
        if key in seen or profiles.get(record['profile_key'], location) != location:
            raise ValueError('Repeated profile/depth or inconsistent profile location/treatment.')
        seen.add(key)
        profiles[record['profile_key']] = location
        result.append(record)
    if not result:
        raise ValueError('The native database has no rows.')
    return result


def _metrics(predictions: list[dict], key: str) -> dict:
    errors = [item[key] - item['observed_pr_mpa'] for item in predictions]
    mae, rmse = fmean(abs(value) for value in errors), math.hypot(*errors) / math.sqrt(len(errors))
    if not all(math.isfinite(value) for value in (mae, rmse)):
        raise ValueError('Unrepresentable benchmark errors; no partial metric.')
    return {'mae_mpa': mae, 'rmse_mpa': rmse, 'negative_prediction_count': sum(item[key] < 0 for item in predictions)}


def benchmark_csv(raw: bytes) -> dict:
    """Test a deliberately simple moisture-only OLS against train-mean prediction."""
    rows = parse_database(raw)
    paired = [r for r in rows if all(r[k] is not None for k in ('VWC(m3/m3)', 'BD(g/cm3)', 'Clay(%)', 'PR(Mpa)'))]
    cohort = [r for r in paired if r['depth(m)'] in (0.1, 0.2, 0.3)]
    clusters = sorted({r['cluster'] for r in cohort})
    if len(clusters) < 3:
        raise ValueError('At least three complete shallow clusters are required for this benchmark.')
    folds, all_predictions = [], []
    for cluster in clusters:
        train = [r for r in cohort if r['cluster'] != cluster]
        test = [r for r in cohort if r['cluster'] == cluster]
        xbar, ybar = fmean(r['VWC(m3/m3)'] for r in train), fmean(r['PR(Mpa)'] for r in train)
        denominator = math.fsum((r['VWC(m3/m3)'] - xbar) ** 2 for r in train)
        if denominator == 0:
            raise ValueError('Training moisture has no variance; OLS is not identified.')
        slope = math.fsum((r['VWC(m3/m3)'] - xbar) * (r['PR(Mpa)'] - ybar) for r in train) / denominator
        intercept = ybar - slope * xbar
        if not all(math.isfinite(value) for value in (slope, intercept)):
            raise ValueError('Unrepresentable OLS coefficients.')
        predictions = [{'source_row': r['source_row'], 'profile_key': r['profile_key'], 'observed_pr_mpa': r['PR(Mpa)'], 'ols_prediction_mpa': intercept + slope * r['VWC(m3/m3)'], 'training_mean_prediction_mpa': ybar} for r in test]
        fold_metrics = {'ols': _metrics(predictions, 'ols_prediction_mpa'), 'training_mean': _metrics(predictions, 'training_mean_prediction_mpa')}
        folds.append({'test_cluster': cluster, 'training_clusters': [c for c in clusters if c != cluster], 'training_profiles': sorted({r['profile_key'] for r in train}), 'test_profiles': sorted({r['profile_key'] for r in test}), 'training_rows': len(train), 'test_rows': len(test), 'coefficients': {'intercept_mpa': intercept, 'slope_mpa_per_vwc': slope}, 'metrics': fold_metrics, 'predictions': predictions})
        all_predictions.extend(predictions)
    if len(all_predictions) != len(cohort) or len({r['source_row'] for r in all_predictions}) != len(cohort):
        raise ValueError('Holdout coverage is inconsistent.')
    observed_pr = [r['PR(Mpa)'] for r in rows if r['PR(Mpa)'] is not None]
    return {
        'status': 'research_only', 'model_version': 'native-pr-moisture-ols/1', 'input_sha256': hashlib.sha256(raw).hexdigest(),
        'validation_scope': 'one_site_exploratory_cluster_holdout_not_external_validation',
        'native_rows': len(rows), 'native_profiles': len({r['profile_key'] for r in rows}),
        'paired_core_rows': len(paired), 'missing_core_rows': len(rows) - len(paired),
        'eligible_rows': len(cohort), 'eligible_profiles': len({r['profile_key'] for r in cohort}), 'depth_labels_m': [0.1, 0.2, 0.3],
        'cohort_required_fields': ['VWC(m3/m3)', 'BD(g/cm3)', 'Clay(%)', 'PR(Mpa)'], 'fitted_feature_fields': ['VWC(m3/m3)'],
        'observed_native_pr_max_mpa': max(observed_pr), 'native_pr_at_max_count': sum(value == max(observed_pr) for value in observed_pr),
        'ceiling_or_right_censoring_semantics': 'not_established_do_not_relabel_or_extrapolate',
        'folds': folds, 'pooled_metrics': {'ols': _metrics(all_predictions, 'ols_prediction_mpa'), 'training_mean': _metrics(all_predictions, 'training_mean_prediction_mpa')},
        'cohort_ranges': {key: {'min': min(r[key] for r in cohort), 'max': max(r[key] for r in cohort)} for key in ('VWC(m3/m3)', 'BD(g/cm3)', 'Clay(%)', 'PR(Mpa)')},
        'not_computed': ['wheel_loads', 'soil_stress', 'bearing_capacity', 'passability', 'recovery', 'permissible_trip_mass'],
        'limitations': ['One agricultural site/campaign, not independent field validation.', 'Cluster labels are publisher spatial groups; nearby profiles remain autocorrelated.', 'No missing-value imputation, texture normalization, depth interpolation or prediction clamping.', 'Depth labels and measured water are not interchangeable with current weather-model layers.', 'PR is penetration resistance, not transport admission or load-bearing capacity.', 'This baseline does not use vehicle, traffic history, bulk density or clay as fitted features.'],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        with args.csv.open('rb') as handle:
            result = benchmark_csv(handle.read(262_145))
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as handle:
                handle.write(text)
        print(text, end='')
        return 0
    except (OSError, ValueError, ArithmeticError, csv.Error) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
