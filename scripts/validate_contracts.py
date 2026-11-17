"""Validate GroundSense v1.1 wire contracts; no scientific engine."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from math import isclose
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "assessment.schema.json"
QUANTILE_LEVELS = {"p10": 0.10, "p50": 0.50, "p90": 0.90}


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ref(value) -> bool:
    return isinstance(value, str) and bool(value)


def validate_assessment(record: dict) -> list[str]:
    """Return semantic errors for a shape-valid ScientificAssessment."""
    if not isinstance(record, dict):
        return ["record must be an object"]
    errors: list[str] = []
    context = record.get("context") or {}
    recovery = record.get("recovery") or {}
    mobility = record.get("mobility") or {}
    environment = record.get("environmental_condition") or {}

    try:
        zone = ZoneInfo(context["timezone"])
        day = datetime.fromisoformat(context["assessment_date"])
        interval = context["local_day_utc_interval"]
        if _time(interval["start"]) != day.replace(tzinfo=zone).astimezone(timezone.utc) or _time(interval["end"]) != (day + timedelta(days=1)).replace(tzinfo=zone).astimezone(timezone.utc):
            errors.append("local day UTC interval must match assessment_date and timezone")
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        errors.append("context.timezone must be an IANA timezone")
    try:
        cutoff, computed = _time(context["knowledge_cutoff"]), _time(context["computed_at"])
        if cutoff > computed:
            errors.append("knowledge_cutoff must not follow computed_at")
        issue = context.get("forecast_issue_time")
        if issue is not None and _time(issue) > cutoff:
            errors.append("forecast_issue_time must not follow knowledge_cutoff")
    except (KeyError, TypeError, ValueError):
        pass

    if environment.get("status") == "unknown" and not environment.get("reason_codes"):
        errors.append("unknown environmental condition requires reason_codes")
    if environment.get("status") == "unknown" and environment.get("condition") is not None:
        errors.append("unknown environment must have null condition")
    if environment.get("status") == "available" and (environment.get("condition") is None or not _ref(environment.get("condition_policy_ref")) or not _ref(environment.get("physical_series_ref"))):
        errors.append("available environment requires condition, policy and physical series")
    for support in record.get("source_supports") or []:
        try:
            if _time(support["temporal_interval"]["end"]) <= _time(support["temporal_interval"]["start"]):
                errors.append("source support interval end must follow start")
        except (KeyError, TypeError, ValueError):
            pass
        if support.get("estimate_kind") == "static_property" and support.get("quantity") == "soil_moisture":
            errors.append("static source support cannot publish soil_moisture")

    try:
        reference, horizon = _time(recovery["reference_time"]), _time(recovery["horizon_end"])
        if horizon < reference:
            errors.append("recovery horizon_end must not precede reference_time")
    except (KeyError, TypeError, ValueError):
        reference = horizon = None

    cdf = recovery.get("cdf") or []
    bounds = recovery.get("cdf_bounds") or []
    def monotonic(points, lower_key, upper_key, label):
        previous_time = previous_lower = previous_upper = None
        for point in points:
            try:
                stamp, lower, upper = _time(point["time"]), point[lower_key], point[upper_key]
            except (KeyError, TypeError, ValueError):
                continue
            if reference and stamp < reference:
                errors.append(f"{label} time must not precede reference_time")
            if horizon and stamp > horizon:
                errors.append(f"{label} time must not exceed horizon_end")
            if previous_time and stamp <= previous_time:
                errors.append(f"{label} times must strictly increase")
            if lower > upper:
                errors.append(f"{label} lower must not exceed upper")
            if previous_lower is not None and lower < previous_lower:
                errors.append(f"{label} lower must be nondecreasing")
            if previous_upper is not None and upper < previous_upper:
                errors.append(f"{label} upper must be nondecreasing")
            previous_time, previous_lower, previous_upper = stamp, lower, upper
    monotonic(cdf, "probability", "probability", "CDF")
    monotonic(bounds, "lower", "upper", "CDF bound")

    kind, status = recovery.get("distribution_kind"), recovery.get("status")
    numeric = recovery.get("probability_by_horizon") is not None or bool(cdf) or any((recovery.get("quantiles") or {}).get(x) is not None for x in QUANTILE_LEVELS)
    if status in {"unknown", "unsupported"} and (numeric or bounds):
        errors.append("unknown or unsupported recovery cannot publish numeric outputs")
    if status == "already_recovered":
        if recovery.get("confirmation_basis") not in {"model_history", "field_protocol"} or not recovery.get("confirmation_evidence_refs"):
            errors.append("already_recovered requires confirmation basis and evidence")
        if kind != "exact_scenario_distribution" or recovery.get("probability_by_horizon") != 1 or not cdf or _time(cdf[0]["time"]) != reference or any(p["probability"] != 1 for p in cdf):
            errors.append("already_recovered requires a unit CDF from reference_time")
    if status == "forecast_distribution" and kind == "unavailable":
        errors.append("forecast_distribution cannot have unavailable distribution_kind")
    if status == "right_censored" and (any(point.get("probability") != 0 for point in cdf) or recovery.get("probability_by_horizon") not in {None, 0}):
        errors.append("right_censored recovery must have zero CDF and probability")
    if kind == "partially_identified":
        if not bounds or recovery.get("bounds_by_horizon") is None:
            errors.append("partially_identified recovery requires cdf_bounds and bounds_by_horizon")
        if numeric:
            errors.append("partially_identified recovery cannot publish exact probabilities, CDF, or quantiles")
        if not recovery.get("missing_mass_reasons"):
            errors.append("partially_identified recovery requires missing_mass_reasons")
        hb = recovery.get("bounds_by_horizon")
        lost = recovery.get("lost_weight_mass")
        if isinstance(hb, dict) and lost is not None:
            if not isclose(hb["upper"] - hb["lower"], lost, abs_tol=1e-9):
                errors.append("horizon bound width must equal lost weight mass")
            if hb["lower"] > hb["upper"]:
                errors.append("horizon bound lower must not exceed upper")
            if bounds:
                last = bounds[-1]
                if last["lower"] > hb["lower"] or last["upper"] > hb["upper"]:
                    errors.append("horizon bounds must not decrease from last CDF bound")
                if _time(last["time"]) == horizon and any(not isclose(last[k], hb[k], abs_tol=1e-9) for k in ("lower", "upper")):
                    errors.append("horizon bounds must equal CDF bounds at horizon_end")
    if kind in {"exact_scenario_distribution", "partially_identified"}:
        known, lost = recovery.get("known_weight_mass"), recovery.get("lost_weight_mass")
        if known is None or lost is None or not isclose(known + lost, 1.0, abs_tol=1e-9):
            errors.append("known and lost weight masses must sum to one")
    if kind == "exact_scenario_distribution":
        lost = recovery.get("lost_weight_mass")
        if lost != 0:
            errors.append("exact scenario distribution requires zero lost weight mass")
        if recovery.get("probability_by_horizon") is not None and cdf and cdf[-1].get("probability") != recovery["probability_by_horizon"]:
            errors.append("probability_by_horizon must equal final CDF probability")
        previous_quantile = None
        for name, level in QUANTILE_LEVELS.items():
            value = (recovery.get("quantiles") or {}).get(name)
            if value is None:
                continue
            try:
                stamp = _time(value)
                first = next(_time(point["time"]) for point in cdf if point["probability"] >= level)
            except (StopIteration, TypeError, ValueError, KeyError):
                errors.append(f"{name} is published at an unattained CDF level")
                continue
            if stamp != first:
                errors.append(f"{name} must equal the first CDF crossing on the published grid")
            if previous_quantile and stamp < previous_quantile:
                errors.append("recovery quantiles must be nondecreasing")
            previous_quantile = stamp
    if kind == "unavailable" and (numeric or bounds):
        errors.append("unavailable recovery cannot publish numeric outputs")
    if recovery.get("calibration_status") == "calibrated" and not _ref(recovery.get("recovery_calibration_report_ref")):
        errors.append("calibrated recovery distribution requires a calibration report")
    if recovery.get("kind") == "vehicle_condition_recovery":
        if record.get("assessment_level") != "validated_domain":
            errors.append("vehicle recovery requires validated_domain")
        for field in ("vehicle_envelope_ref", "matching_report_ref", "recovery_calibration_report_ref"):
            if not _ref(recovery.get(field)):
                errors.append(f"vehicle recovery requires {field}")

    if context.get("assessment_mode") == "climatology":
        if recovery.get("status") != "unsupported" or mobility.get("kind") != "unavailable":
            errors.append("climatology requires unavailable mobility and unsupported recovery")
    if mobility.get("kind") in {"calibrated_probability", "probability_bounds"}:
        if record.get("assessment_level") != "validated_domain":
            errors.append("quantitative mobility requires validated_domain")
        for field in ("outcome", "estimand", "operation_ref", "configuration_aggregation", "traction_loss", "pass_policy_ref", "vehicle_envelope_ref", "calibration_report_ref"):
            if mobility.get(field) is None:
                errors.append(f"quantitative mobility requires {field}")
        aggregation = mobility.get("configuration_aggregation")
        if not isinstance(aggregation, dict) or not aggregation.get("kind") or not _ref(aggregation.get("policy_ref")):
            errors.append("configuration aggregation requires kind and policy_ref")
    if mobility.get("kind") == "calibrated_probability" and mobility.get("risk") is None:
        errors.append("calibrated_probability requires point risk")
    if mobility.get("kind") == "unavailable" and mobility.get("probability_bounds") is not None:
        errors.append("unavailable mobility cannot publish probability bounds")
    if mobility.get("kind") == "probability_bounds":
        probability_bounds = mobility.get("probability_bounds")
        if not isinstance(probability_bounds, dict):
            errors.append("probability_bounds requires probability_bounds")
        elif probability_bounds.get("lower", 1) > probability_bounds.get("upper", 0):
            errors.append("probability bounds lower must not exceed upper")
        if mobility.get("risk") is not None:
            errors.append("probability_bounds cannot publish point risk")
    if mobility.get("kind") == "unavailable" and mobility.get("risk") is not None:
        errors.append("unavailable mobility cannot publish risk")
    if record.get("production_mode") and record.get("synthetic"):
        errors.append("synthetic records are forbidden in production_mode")
    return errors


def validate_document(record) -> list[str]:
    """Return schema errors followed by semantic errors without shape crashes."""
    try:
        json.dumps(record, allow_nan=False)
    except ValueError:
        return ["record contains a non-finite JSON number"]
    except TypeError:
        pass  # The schema reports unsupported Python value types below.
    checker = FormatChecker()
    if "date-time" not in checker.checkers:
        return ["validation dependency unavailable: install jsonschema[format-nongpl] for date-time checks"]
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = [f"schema: {error.message}" for error in Draft202012Validator(schema, format_checker=checker).iter_errors(record)]
    return errors if errors else validate_assessment(record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", nargs="+", type=Path)
    args = parser.parse_args()
    failed = 0
    for path in args.records:
        errors = validate_document(json.loads(path.read_text()))
        if errors:
            failed += 1
            print(f"FAIL {path}: " + "; ".join(errors))
        else:
            print(f"PASS {path}")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
