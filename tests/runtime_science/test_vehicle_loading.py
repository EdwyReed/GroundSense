"""Exact load-constraint checks, not field/mobility validation."""
from itertools import product
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_reference_axle_bounds_match_independent_allocation_enumeration():
    from research.vehicle_loading import axle_allocation_bounds

    # Published reference upper limits and GVW, not an assumed load split.
    limits = (9_000, 11_500, 11_500)
    mass = 30_000
    allocations = [row for row in product(*(range(0, limit + 1, 500) for limit in limits)) if sum(row) == mass]
    expected = [{"min_kg": min(row[i] for row in allocations), "max_kg": max(row[i] for row in allocations)} for i in range(len(limits))]
    assert axle_allocation_bounds(mass, limits) == expected
    assert all(row['min_kg'] < row['max_kg'] for row in expected)


@pytest.mark.parametrize(('mass', 'limits'), [
    (True, (3, 4)), (1.5, (3, 4)), ('3', (3, 4)), (0, (3, 4)), (-1, (3, 4)),
    (float('nan'), (3, 4)), (10**1000, (3, 4)), (8, (3, 4)),
    (3, (True, 4)), (3, (3.0, 4)), (3, (0, 4)), (3, (3, -4)), (3, ()),
    (3, (1,) * 13), (3, iter((3, 4))),
])
def test_rejects_invalid_or_inconsistent_load_constraints(mass, limits):
    from research.vehicle_loading import axle_allocation_bounds

    with pytest.raises(ValueError):
        axle_allocation_bounds(mass, limits)


def test_all_small_integer_projections_match_exhaustive_feasible_allocations():
    from research.vehicle_loading import axle_allocation_bounds

    for limits in product(range(1, 5), repeat=3):
        possible = list(product(*(range(limit + 1) for limit in limits)))
        for mass in range(1, sum(limits) + 1):
            allocations = [row for row in possible if sum(row) == mass]
            expected = [{'min_kg': min(row[i] for row in allocations), 'max_kg': max(row[i] for row in allocations)} for i in range(3)]
            assert axle_allocation_bounds(mass, limits) == expected


def profile_fixture(tmp_path):
    raw = b'%PDF-1.4\nSYNTHETIC UNIT FIXTURE; NOT A REAL DATASHEET\n'
    (tmp_path / 'source.pdf').write_bytes(raw)
    profile = {
        'profile_id': 'synthetic-unit-fixture', 'model_code_literal': 'SYNTHETIC UNIT FIXTURE',
        'scope': 'documented_reference_only', 'mass_basis': 'vehicle_gross_not_combination',
        'nominal_chassis_without_body_kg': 10_250, 'gross_vehicle_limit_kg': 30_000,
        'axle_upper_limits_kg': [9_000, 11_500, 11_500],
        'nominal_chassis_axle_loads_kg': [5_900, 2_175, 2_175],
        'source': {'cached_pdf': 'source.pdf', 'sha256': hashlib.sha256(raw).hexdigest(), 'distribution': 'synthetic_unit_fixture'},
    }
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile))
    return path, profile


def test_reference_run_binds_bytes_without_inventing_wheel_load_or_ground_response(tmp_path):
    from research.vehicle_loading import run_reference

    path, profile = profile_fixture(tmp_path)
    result = run_reference(path, 20_000, source_root=tmp_path)
    assert result['status'] == 'research_only'
    assert result['input_consistency'] == 'within_reference_constraints'
    assert result['profile_id'] == profile['profile_id']
    assert result['source_pdf_sha256_matches'] is True
    assert result['profile_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['axle_bounds'][0]['min_kg'] == 0  # Tare split is NOT a loaded-axle minimum.
    assert result['actual_axle_distribution_identified'] is False
    assert {'contact_pressure', 'soil_strength', 'traction', 'passability', 'recovery'} <= set(result['not_computed'])
    assert result['user_fleet_match'] is False


@pytest.mark.parametrize(('mass', 'reason'), [
    (10_249, 'BELOW_NOMINAL_CHASSIS_MASS'), (31_000, 'ABOVE_REFERENCE_GROSS_RATING'),
])
def test_reference_nominal_mass_range_is_not_replaced_by_sum_of_axle_ratings(tmp_path, mass, reason):
    from research.vehicle_loading import run_reference

    path, _ = profile_fixture(tmp_path)
    result = run_reference(path, mass, source_root=tmp_path)
    assert result['input_consistency'] == 'outside_reference_constraints'
    assert result['gross_mass_kg'] == mass
    assert reason in result['reason_codes']
    assert result['axle_bounds'] == []
    assert result['status'] == 'research_only'


@pytest.mark.parametrize('change', ['pdf', 'digest', 'nominal_sum', 'fractional_limit', 'scope', 'mass_basis', 'path_escape'])
def test_refuses_modified_or_incompatible_reference_data(tmp_path, change):
    from research.vehicle_loading import run_reference

    path, profile = profile_fixture(tmp_path)
    if change == 'pdf':
        (tmp_path / 'source.pdf').write_bytes(b'%PDF-1.4\nDIFFERENT UNIT BYTES\n')
    elif change == 'digest':
        profile['source']['sha256'] = 'SHA256:' + profile['source']['sha256']
    elif change == 'nominal_sum':
        profile['nominal_chassis_axle_loads_kg'][0] += 1
    elif change == 'fractional_limit':
        profile['axle_upper_limits_kg'][0] = 9_000.5
    elif change == 'scope':
        profile['scope'] = 'user_fleet_validated'
    elif change == 'mass_basis':
        profile['mass_basis'] = 'loaded_vehicle_combination'
    else:
        profile['source']['cached_pdf'] = '../outside.pdf'
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):
        run_reference(path, 20_000, source_root=tmp_path)


def test_cli_writes_exercised_local_reference_cases(tmp_path):
    path, _ = profile_fixture(tmp_path)
    output = tmp_path / 'receipt.json'
    result = subprocess.run([
        sys.executable, '-m', 'research.vehicle_loading', '--profile', str(path), '--source-root', str(tmp_path),
        '--gross-mass-kg', '20000', '29000', '31000', '--output', str(output),
    ], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text())
    assert [row['gross_mass_kg'] for row in receipt['cases']] == [20_000, 29_000, 31_000]
    assert receipt['cases'][0]['axle_bounds'] != receipt['cases'][1]['axle_bounds']
    assert receipt['cases'][2]['axle_bounds'] == []
    assert json.loads(result.stdout) == receipt


@pytest.mark.parametrize('artifact', ['profile_budget', 'source_budget', 'not_pdf'])
def test_reference_reads_are_bounded_and_keep_pdf_distinct_from_other_bytes(tmp_path, artifact):
    from research.vehicle_loading import run_reference

    path, profile = profile_fixture(tmp_path)
    if artifact == 'profile_budget':
        path.write_bytes(b' ' * 32_769)
    else:
        raw = b'%PDF-' + b'x' * (5 * 1024 * 1024) if artifact == 'source_budget' else b'NOT A PDF'
        (tmp_path / 'source.pdf').write_bytes(raw)
        profile['source']['sha256'] = hashlib.sha256(raw).hexdigest()
        path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):
        run_reference(path, 20_000, source_root=tmp_path)


def test_cli_does_not_overwrite_an_existing_receipt(tmp_path):
    path, _ = profile_fixture(tmp_path)
    output = tmp_path / 'keep.json'
    output.write_text('{"existing":true}')
    before = output.read_bytes()
    result = subprocess.run([
        sys.executable, '-m', 'research.vehicle_loading', '--profile', str(path), '--source-root', str(tmp_path),
        '--gross-mass-kg', '20000', '--output', str(output),
    ], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'failed'
    assert output.read_bytes() == before
