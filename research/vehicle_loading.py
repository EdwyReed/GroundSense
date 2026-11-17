"""Offline, reference-only axle loading constraints; never a mobility assessment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MODEL_VERSION = "static-axle-constraints/1"


def _kg(value: object, *, allow_zero: bool = False) -> int:
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= 1_000_000:
        raise ValueError("Mass must be integer kg within the implementation bound, not a terrain limit.")
    return value


def axle_allocation_bounds(gross_mass_kg: int, axle_upper_limits_kg: tuple[int, ...] | list[int]) -> list[dict[str, int]]:
    """Project sum(loads)=mass, 0<=load[i]<=limit[i]; no equal-load assumption."""
    gross_mass_kg = _kg(gross_mass_kg)
    if not isinstance(axle_upper_limits_kg, (list, tuple)) or not 1 <= len(axle_upper_limits_kg) <= 12:
        raise ValueError("Supply 1..12 explicit axle limits, not a wheel/drive formula.")
    if any(type(value) is not int or not 0 < value <= 1_000_000 for value in axle_upper_limits_kg):
        raise ValueError("Each axle limit must be a positive integer kg value.")
    total = sum(axle_upper_limits_kg)
    if gross_mass_kg > total:
        raise ValueError("No allocation satisfies the supplied upper limits.")
    return [{"min_kg": max(0, gross_mass_kg - (total - limit)), "max_kg": min(limit, gross_mass_kg)} for limit in axle_upper_limits_kg]


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Reference artifact exceeds the declared read budget.")
    return raw


def run_reference(profile_path: Path, gross_mass_kg: int, *, source_root: Path = ROOT) -> dict:
    """Apply only necessary static constraints; byte binding does not verify facts."""
    gross_mass_kg = _kg(gross_mass_kg)
    profile_raw = _read_bounded(Path(profile_path), 32_768)
    profile = json.loads(profile_raw)
    if not isinstance(profile, dict) or profile.get('scope') != 'documented_reference_only' or profile.get('mass_basis') != 'vehicle_gross_not_combination':
        raise ValueError("Only an explicitly scoped, non-combination reference is supported.")
    for field in ('profile_id', 'model_code_literal'):
        value = profile.get(field)
        if not isinstance(value, str) or not value or len(value) > 120 or value.strip() != value or any(ord(char) < 32 for char in value):
            raise ValueError("Invalid literal reference identifier; no normalization is applied.")
    raw_limits = profile.get('axle_upper_limits_kg')
    if not isinstance(raw_limits, list) or not 1 <= len(raw_limits) <= 12:
        raise ValueError("Reference must declare 1..12 explicit axle limits.")
    limits = [_kg(value) for value in raw_limits]
    axle_allocation_bounds(1, limits)  # Validate bounded, positive integer limits.
    floor = _kg(profile.get('nominal_chassis_without_body_kg'))
    ceiling = _kg(profile.get('gross_vehicle_limit_kg'))
    nominal = profile.get('nominal_chassis_axle_loads_kg')
    if not isinstance(nominal, list) or len(nominal) != len(limits) or any(_kg(value, allow_zero=True) > cap for value, cap in zip(nominal, limits)) or sum(nominal) != floor or not floor <= ceiling <= sum(limits):
        raise ValueError("Nominal chassis, gross and axle reference facts are inconsistent.")
    source = profile.get('source')
    if not isinstance(source, dict) or not isinstance(source.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', source['sha256']) or not isinstance(source.get('cached_pdf'), str):
        raise ValueError("A literal SHA256 and cached source PDF are required.")
    relative = Path(source['cached_pdf'])
    root = Path(source_root).resolve()
    source_path = (root / relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or not source_path.is_relative_to(root):
        raise ValueError("The cached source must remain within its explicit source root.")
    raw = _read_bounded(source_path, 5 * 1024 * 1024)
    if not raw.startswith(b'%PDF-') or hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError("Source PDF bytes do not match the recorded reference digest.")
    reasons = []
    if gross_mass_kg < floor:
        reasons.append('BELOW_NOMINAL_CHASSIS_MASS')
    if gross_mass_kg > ceiling:
        reasons.append('ABOVE_REFERENCE_GROSS_RATING')
    if gross_mass_kg > sum(limits):
        reasons.append('ABOVE_SUM_OF_REFERENCE_AXLE_RATINGS')
    bounds = [] if reasons else axle_allocation_bounds(gross_mass_kg, limits)
    return {
        'model_version': MODEL_VERSION, 'status': 'research_only',
        'basis': 'necessary_static_mass_and_rating_constraints_not_terrain_response',
        'profile_id': profile['profile_id'], 'model_code_literal': profile['model_code_literal'],
        'profile_sha256': hashlib.sha256(profile_raw).hexdigest(),
        'gross_mass_kg': gross_mass_kg, 'unit': 'kg',
        'input_consistency': 'outside_reference_constraints' if reasons else 'within_reference_constraints',
        'reason_codes': reasons, 'axle_bounds': bounds,
        'source': source, 'source_pdf_sha256_matches': True,
        'actual_axle_distribution_identified': False, 'user_fleet_match': False,
        'not_computed': ['wheel_loads', 'contact_pressure', 'soil_stress', 'soil_strength', 'rutting', 'traction', 'passability', 'recovery', 'permissible_trip_mass'],
        'assumptions': [
            'Static level reference vehicle, without external trailer/support forces.',
            'Conditional allocations respect each published axle rating and sum to gross vehicle mass.',
            'Marginal bounds are not a joint allocation, actual axle measurements or a centre-of-mass model.',
            'Nominal chassis values exclude the body; added mass is not identified payload.',
            'No equal split, tare-load minima, wheel count or tyre pressure is inferred from 6x6.',
            'Reference ratings are not ground capacity or a local legal/admission decision.',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--gross-mass-kg', type=int, nargs='+', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if len(args.gross_mass_kg) > 16:
            raise ValueError("At most 16 reference cases per offline run.")
        result = {'status': 'research_only', 'cases': [run_reference(args.profile, mass, source_root=args.source_root) for mass in args.gross_mass_kg]}
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as handle:
                handle.write(text)
        print(text, end='')
        return 0
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False, allow_nan=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
