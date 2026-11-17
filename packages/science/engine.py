"""Literal executable implementation of warm-soil-6h/v1 research card.

This module deliberately separates a labelled synthetic arithmetic experiment from
product physics.  No result here assesses vehicle mobility.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo
from typing import Any

UTC = timezone.utc
CARD_VERSION = "warm-soil-6h/v1"
_REQUIRED_PARAMS = ("dz_1", "dz_2", "theta_por_1", "theta_por_2", "theta_fc_1", "theta_fc_2",
                    "theta_wp_1", "theta_wp_2", "K_in", "K_12", "K_b", "H_max",
                    "a_H", "a_1", "a_2", "eta_H", "eta_1", "eta_2", "numerical_tolerance")


def _dt(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Часова позначка має бути рядком ISO")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Часова позначка має містити часовий пояс")
    return result.astimezone(UTC)


def _z(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _failure(codes: list[str], detail: str = "") -> dict[str, Any]:
    return {"status": "abstained", "reason_codes": sorted(set(codes)), "detail": detail,
            "steps": [], "forcing_inventory": []}


def _params(params: dict) -> tuple[dict[str, float], dict[str, float]]:
    if not isinstance(params, dict) or any(k not in params for k in _REQUIRED_PARAMS):
        raise ValueError("Набір затверджених параметрів неповний")
    try:
        p = {key: float(params[key]) for key in _REQUIRED_PARAMS}
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Параметр має бути скінченним числом") from exc
    if not all(isfinite(v) for v in p.values()):
        raise ValueError("Параметр не є скінченним числом")
    if not 0 < p["numerical_tolerance"] <= 1e-3:
        raise ValueError("Числова похибка має бути додатною і не більшою за 0.001")
    for i in (1, 2):
        if not (p[f"dz_{i}"] > 0 and 0 < p[f"theta_wp_{i}"] < p[f"theta_fc_{i}"] < p[f"theta_por_{i}"]):
            raise ValueError("Некоректні гідравлічні межі шару")
    if min(p["K_in"], p["K_12"], p["K_b"], p["H_max"], p["eta_H"], p["eta_1"], p["eta_2"]) < 0:
        raise ValueError("Ємність або ефективність ЕТ не можуть бути від’ємними")
    if not all(0 <= p[k] <= 1 for k in ("eta_H", "eta_1", "eta_2")):
        raise ValueError("Ефективність ЕТ має бути в межах [0,1]")
    if min(p["a_H"], p["a_1"], p["a_2"]) < 0 or abs(p["a_H"] + p["a_1"] + p["a_2"] - 1) > p["numerical_tolerance"]:
        raise ValueError("Ваги ЕТ мають бути невід’ємними та сумуватися до одного")
    storage = {f"sat{i}": 1000 * p[f"dz_{i}"] * p[f"theta_por_{i}"] for i in (1, 2)}
    storage.update({f"fc{i}": 1000 * p[f"dz_{i}"] * p[f"theta_fc_{i}"] for i in (1, 2)})
    storage.update({f"wp{i}": 1000 * p[f"dz_{i}"] * p[f"theta_wp_{i}"] for i in (1, 2)})
    return p, storage


def adapt_native_6h(rows: list[dict], start: str, end: str, step_hours: int) -> dict[str, Any]:
    """Conservatively aggregate exact native intervals; never cross cycle differences.

    Each input must carry an interval amount or a rate. Accumulations are accepted
    only when their explicit startStep/endStep belongs to one cycle; their supplied
    value is the interval amount, not a cumulative value to difference.
    """
    try:
        cursor, horizon_end = _dt(start), _dt(end)
    except ValueError:
        return {"status": "unavailable", "reason_codes": ["CRITICAL_SOURCE_MISSING"], "bins": []}
    if step_hours != 6 or horizon_end <= cursor or (horizon_end - cursor).total_seconds() % 21600:
        return {"status": "unavailable", "reason_codes": ["CRITICAL_SOURCE_MISSING"], "bins": []}
    native: dict[str, list[tuple[datetime, datetime, dict, float]]] = {"precipitation": [], "et_demand": [], "temperature": []}
    for row in rows:
        try:
            rs, re = _dt(row["start"]), _dt(row["end"])
            value = float(row["value"])
            if re <= rs or not isfinite(value): raise ValueError
            name, step_type, units = row["variable"], row["step_type"], row["native_units"]
            if name not in native or re - rs > timedelta(hours=6): raise ValueError
            if name in ("precipitation", "et_demand"):
                if step_type not in ("amount", "accumulation", "rate") or units != ("mm/h" if step_type == "rate" else "mm"): raise ValueError
                if step_type == "accumulation" and ("startStep" not in row or "endStep" not in row): raise ValueError
            elif step_type != "duration_mean" or units not in ("degC", "C", "°C"):
                raise ValueError
            native[name].append((rs, re, row, value))
        except (KeyError, TypeError, ValueError):
            return {"status": "unavailable", "reason_codes": ["CRITICAL_SOURCE_MISSING"], "bins": []}
    bins = []
    while cursor < horizon_end:
        bin_end = cursor + timedelta(hours=6)
        values: dict[str, float] = {}
        for name, variable_rows in native.items():
            if not variable_rows:
                continue
            selected = sorted((item for item in variable_rows if cursor <= item[0] and item[1] <= bin_end), key=lambda item: item[0])
            point = cursor
            for rs, re, row, v in selected:
                if rs != point: return {"status": "unavailable", "reason_codes": ["CRITICAL_SOURCE_MISSING"], "bins": []}
                point = re
                if row["step_type"] == "rate": v *= (re - rs).total_seconds() / 3600
                if name == "temperature":
                    values["_temp_weighted"] = values.get("_temp_weighted", 0.0) + v * (re - rs).total_seconds() / 3600
                    values["_temp_hours"] = values.get("_temp_hours", 0.0) + (re - rs).total_seconds() / 3600
                else:
                    values[name] = values.get(name, 0.0) + v
            if point != bin_end:
                return {"status": "unavailable", "reason_codes": ["CRITICAL_SOURCE_MISSING"], "bins": []}
        # The adapter is variable-neutral. The caller declares which variables are
        # mandatory for its card; absent variables remain unavailable, never zero.
        bins.append({"start": _z(cursor), "end": _z(bin_end), "precipitation_mm": values.get("precipitation"),
                     "et_demand_mm": values.get("et_demand"), "temperature_c": (values["_temp_weighted"] / values["_temp_hours"] if values.get("_temp_hours") else None)})
        cursor = bin_end
    return {"status": "ok", "reason_codes": [], "bins": bins}


adapt_native_to_6h = adapt_native_6h


def _validate_forcing(forcing: list[dict], cutoff: datetime) -> tuple[list[dict] | None, list[str]]:
    if not forcing: return None, ["CRITICAL_SOURCE_MISSING"]
    parsed = []
    for row in forcing:
        try:
            s, e = _dt(row["start"]), _dt(row["end"])
            if e - s != timedelta(hours=6): return None, ["CRITICAL_SOURCE_MISSING"]
            if any(k not in row for k in ("precipitation_mm", "et_demand_mm")): return None, ["CRITICAL_SOURCE_MISSING"]
            p, d = float(row["precipitation_mm"]), float(row["et_demand_mm"])
            if min(p, d) < 0 or not all(isfinite(x) for x in (p, d)): return None, ["MODEL_NUMERICAL_FAILURE"]
            for key in ("provider_available_at", "recorded_at"):
                if key not in row or row[key] is None: return None, ["CRITICAL_SOURCE_MISSING"]
                if _dt(row[key]) > cutoff:
                    return None, ["SOURCE_STALE"]
            if "ingested_at" in row and row["ingested_at"] is not None and _dt(row["ingested_at"]) > cutoff:
                return None, ["SOURCE_STALE"]
            parsed.append((s, e, row, p, d))
        except (KeyError, TypeError, ValueError): return None, ["CRITICAL_SOURCE_MISSING"]
    parsed.sort(key=lambda x: x[0])
    if any(parsed[i][1] != parsed[i + 1][0] for i in range(len(parsed) - 1)): return None, ["CRITICAL_SOURCE_MISSING"]
    return [dict(row, start=_z(s), end=_z(e), precipitation_mm=p, et_demand_mm=d) for s, e, row, p, d in parsed], []


def research_run(params: dict, initial: dict, forcing: list[dict], thermal_screen: dict) -> dict:
    """Run approved-format inputs through card 10; output is always research-only."""
    try:
        p, s = _params(params)
    except (TypeError, ValueError, OverflowError) as exc:
        return _failure(["HYDRAULIC_CLOSURE_UNAVAILABLE"], str(exc))
    research_label = params.get("research_label")
    explicit_toy = isinstance(research_label, str) and "synthetic" in research_label.lower() and ("toy" in research_label.lower() or "research" in research_label.lower())
    thermal_evidence_complete = (isinstance(thermal_screen, dict)
        and isinstance(thermal_screen.get("lookback_hours"), (int, float)) and not isinstance(thermal_screen.get("lookback_hours"), bool) and thermal_screen["lookback_hours"] > 0
        and isinstance(thermal_screen.get("margin_c"), (int, float)) and not isinstance(thermal_screen.get("margin_c"), bool) and isfinite(float(thermal_screen["margin_c"])) and thermal_screen["margin_c"] > 0
        and bool(thermal_screen.get("source_evidence")))
    if not isinstance(thermal_screen, dict) or thermal_screen.get("pass") is not True or not thermal_screen.get("thermal_screen_version") or thermal_screen.get("snow_absence") is not True or thermal_screen.get("residual_frozen_state") != "no frozen state" or (not explicit_toy and not thermal_evidence_complete):
        return _failure(["FREEZE_THAW_AMBIGUOUS"])
    try:
        cutoff = _dt(initial["knowledge_cutoff"])
        observed_at = _dt(initial["available_at"])
        state = {"H": float(initial["H"]), "L1": float(initial["L1"]), "L2": float(initial["L2"])}
        if initial.get("observed") is not True or initial.get("card_version") != CARD_VERSION or not initial.get("support_mapping_version") or observed_at > cutoff:
            return _failure(["STATE_INITIALIZATION_UNAVAILABLE"])
        if not all(isfinite(value) for value in state.values()) or not (0 <= state["H"] <= p["H_max"] and 0 <= state["L1"] <= s["sat1"] and 0 <= state["L2"] <= s["sat2"]):
            return _failure(["STATE_INITIALIZATION_UNAVAILABLE"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return _failure(["STATE_INITIALIZATION_UNAVAILABLE"])
    intervals, codes = _validate_forcing(forcing, cutoff)
    if codes: return _failure(codes)
    steps = []
    for row in intervals:
        H, L1, L2 = state["H"], state["L1"], state["L2"]
        P, D = row["precipitation_mm"], row["et_demand_mm"]
        EH = min(max(0.0, H), p["eta_H"] * p["a_H"] * D)
        Ha = max(0.0, H) - EH + P
        F = min(Ha, min(p["K_in"] * 6, max(0.0, s["sat1"] - L1)))
        Hb = Ha - F; R = max(0.0, Hb - p["H_max"]); Hn = Hb - R
        L10 = L1 + F; L20 = L2
        J = min(max(0.0, L10 - s["fc1"]), min(p["K_12"] * 6, max(0.0, s["sat2"] - L20)))
        L11 = L10 - J; L21 = L20 + J
        Db = min(max(0.0, L21 - s["fc2"]), p["K_b"] * 6); L22 = L21 - Db
        avail1 = min(max(L11 - s["wp1"], 0.0), s["sat1"] - s["wp1"])
        avail2 = min(max(L22 - s["wp2"], 0.0), s["sat2"] - s["wp2"])
        E1 = min(p["eta_1"] * p["a_1"] * D * avail1 / (s["sat1"] - s["wp1"]), avail1)
        E2 = min(p["eta_2"] * p["a_2"] * D * avail2 / (s["sat2"] - s["wp2"]), avail2)
        new_state = {"H": Hn, "L1": L11 - E1, "L2": L22 - E2}
        residual = (sum(new_state.values()) - (H + L1 + L2)) - (P - EH - E1 - E2 - R - Db)
        values = list(new_state.values()) + [EH, E1, E2, R, Db, F, J, residual]
        if not all(isfinite(v) and v >= -p["numerical_tolerance"] for v in values) or new_state["L1"] > s["sat1"] + p["numerical_tolerance"] or new_state["L2"] > s["sat2"] + p["numerical_tolerance"] or abs(residual) > p["numerical_tolerance"]:
            return _failure(["MODEL_NUMERICAL_FAILURE"])
        steps.append({"start": row["start"], "end": row["end"], "state": new_state, "flows": {"P": P, "E_H": EH, "F": F, "R": R, "J_1": J, "D_b": Db, "E_1": E1, "E_2": E2}, "mass_residual_mm": residual})
        state = new_state
    return {"status": "research_only", "reason_codes": [], "model_version": CARD_VERSION, "synthetic": bool(params.get("research_label")), "steps": steps, "final_state": state, "forcing_inventory": intervals}


def recovery_distribution(members: list[dict], reference_time: str, persistence_hours: int, horizon_hours: int) -> dict:
    """Calculate first-passage confirmation-end bounds without renormalizing failures."""
    ref = _dt(reference_time)
    if persistence_hours <= 0 or persistence_hours % 6 or horizon_hours < 0 or horizon_hours % 6:
        raise ValueError("Некоректний горизонт відновлення")
    if not isinstance(members, list) or not members:
        raise ValueError("Порожній ансамбль не має розподілу відновлення")
    count = horizon_hours // 6
    yes = unknown = 0.0; event_times = []; reasons = set()
    for member in members:
        if not isinstance(member, dict) or isinstance(member.get("weight"), bool): raise ValueError("Некоректна вага члена ансамблю")
        try:
            w = float(member["weight"]); pred = list(member["predicate"]); valid = list(member["valid"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Некоректний член ансамблю") from exc
        if not isfinite(w) or w < 0 or len(pred) < count or len(valid) < count or any(not isinstance(x, bool) for x in pred[:count] + valid[:count]):
            raise ValueError("Некоректний член ансамблю")
        required = persistence_hours // 6
        consecutive = 0; confirmed = None; failure = False
        for i in range(count):
            if not valid[i]: failure = True; reasons.add(member.get("failure_reason", "MODEL_NUMERICAL_FAILURE")); break
            consecutive = consecutive + 1 if pred[i] else 0
            if consecutive >= required and confirmed is None: confirmed = ref + timedelta(hours=(i + 1) * 6)
        if confirmed is not None:
            yes += w; event_times.append((confirmed, w))
        elif failure:
            unknown += w
    if abs(sum(float(m["weight"]) for m in members) - 1.0) > 1e-9: raise ValueError("Ваги ансамблю мають сумуватися до одного")
    upper = yes + unknown
    exact = unknown == 0
    quantiles = {"p10": None, "p50": None, "p90": None}
    if exact:
        for name, q in (("p10", .1), ("p50", .5), ("p90", .9)):
            running = 0.0
            for at, weight in sorted(event_times):
                running += weight
                if running >= q: quantiles[name] = _z(at); break
    cdf = []
    for i in range(1, count + 1):
        at = ref + timedelta(hours=i * 6)
        lower = sum(weight for event_at, weight in event_times if event_at <= at)
        upper_at = lower + unknown
        point = {"time": _z(at), "lower": lower, "upper": upper_at}
        if exact: point["probability"] = lower
        cdf.append(point)
    status = "forecast_distribution" if exact else ("right_censored" if yes or 1 - unknown > 0 else "unknown")
    return {"status": status, "distribution_kind": "exact_scenario_distribution" if exact else "partially_identified", "event_time_convention": "confirmation_end", "persistence_hours": persistence_hours, "horizon_end": _z(ref + timedelta(hours=horizon_hours)), "probability_by_horizon": yes if exact else None, "bounds_by_horizon": {"lower": yes, "upper": upper}, "cdf": cdf, "known_weight_mass": 1 - unknown, "lost_weight_mass": unknown, "missing_mass_reasons": sorted(reasons), "quantiles": quantiles}


def _toy_params() -> dict:
    return {"research_label": "explicit synthetic toy parameters; research only", "dz_1": .1, "dz_2": .2, "theta_por_1": .45, "theta_por_2": .43, "theta_fc_1": .30, "theta_fc_2": .28, "theta_wp_1": .10, "theta_wp_2": .12, "K_in": 4., "K_12": 2., "K_b": 1., "H_max": 5., "a_H": .2, "a_1": .5, "a_2": .3, "eta_H": 1., "eta_1": .8, "eta_2": .8, "numerical_tolerance": 1e-9}


def assess(assessment_date: str, gross_mass_t: float, asset: dict, seed: dict) -> dict:
    """G0b product adapter: labelled synthetic chart plus mandatory physical abstention."""
    target = date.fromisoformat(assessment_date)
    if not isinstance(gross_mass_t, (int, float)) or not isfinite(gross_mass_t) or gross_mass_t <= 0: raise ValueError("Повна маса має бути додатним скінченним числом")
    zone = ZoneInfo((seed.get("workspace") or {}).get("timezone", "Europe/Kyiv"))
    today = datetime.now(zone).date()
    available_days = int((seed.get("demo_forcing") or {}).get("availability_days", 10))
    mode = "reconstruction" if target < today else ("forecast" if target <= today + timedelta(days=available_days) else "climatology")
    local_start = datetime.combine(target, time.min, zone).astimezone(UTC)
    local_end = datetime.combine(target + timedelta(days=1), time.min, zone).astimezone(UTC)
    base = local_start - timedelta(hours=12)
    forcing = [{"start": _z(base + timedelta(hours=6*i)), "end": _z(base + timedelta(hours=6*(i+1))), "precipitation_mm": 4.0 if i == 0 else 0.0, "et_demand_mm": 1.5, "temperature_c": 10.0, "provider_available_at": _z(base), "recorded_at": _z(base)} for i in range(8)]
    toy = research_run(_toy_params(), {"H": 0., "L1": 20., "L2": 35., "observed": True, "card_version": CARD_VERSION, "support_mapping_version": "synthetic-toy-v1", "available_at": _z(base), "knowledge_cutoff": _z(base + timedelta(hours=48))}, forcing, {"thermal_screen_version": "synthetic-toy-v1", "pass": True, "snow_absence": True, "residual_frozen_state": "no frozen state"})
    series = [{"time": x["end"], "moisture_p10": None, "moisture_p50": x["state"]["L1"] / (1000 * _toy_params()["dz_1"]), "moisture_p90": None, "precipitation_mm": x["flows"]["P"], "temperature_c": forcing[i]["temperature_c"]} for i, x in enumerate(toy["steps"])]
    now = _z(datetime.now(UTC)); asset_id = asset.get("id", "unknown")
    reasons = ["HYDRAULIC_CLOSURE_UNAVAILABLE", "STATE_INITIALIZATION_UNAVAILABLE", "CRITICAL_SOURCE_MISSING"]
    return {"asset_id": asset_id, "assessment_date": assessment_date, "gross_mass_t": gross_mass_t, "mode": mode, "synthetic": True, "model_version": CARD_VERSION, "knowledge_cutoff": now, "computed_at": now, "forecast_issue_time": None, "uncertainty_available": False, "moisture_unit": "m3/m3", "chart_kind": "single_synthetic_trajectory", "condition": "unknown", "reason_codes": reasons, "mobility": {"kind": "unavailable", "risk": None, "status": "unknown", "reason_codes": ["MODEL_NOT_VALIDATED", "ROAD_STRUCTURE_UNKNOWN", "VEHICLE_ENVELOPE_UNSUPPORTED"]}, "series": series, "recovery": {"status": "unknown", "distribution_kind": "unavailable", "event_time_convention": "confirmation_end", "persistence_hours": None, "horizon_end": None, "probability_by_horizon": None, "p10": None, "p50": None, "p90": None, "cdf": [], "bounds_by_horizon": None, "lost_weight_mass": None}, "source_supports": [{"quantity": "synthetic_water_toy", "source_ref": "explicit-synthetic-toy/warm-soil-6h-v1", "estimate_kind": "model_derived"}], "warnings": ["Лише синтетична арифметична траєкторія. Це не спостереження вологості, не калібрований інтервал і не доказ прохідності."]}


def evaluate_validation(rows: list[dict], config: dict) -> dict:
    """Evaluate only explicitly held-out, non-synthetic observations; otherwise null metrics."""
    no_evidence = {"status": "insufficient_evidence", "metrics": None, "reason_codes": ["INSUFFICIENT_FIELD_EVIDENCE"], "model_approval": False, "production_eligible": False}
    if not isinstance(config, dict) or not isinstance(rows, list):
        return no_evidence
    if config.get("synthetic") is True or any(row.get("synthetic") is True for row in rows):
        return {**no_evidence, "status": "research_only"}
    if not rows or any(not isinstance(row, dict) or row.get("split") not in ("train", "test") or not isinstance(row.get("road_id"), str) or not row["road_id"] or not isinstance(row.get("event_id"), str) or not row["event_id"] for row in rows):
        return no_evidence
    train = [row for row in rows if row["split"] == "train"]
    test = [row for row in rows if row["split"] == "test"]
    if not train or not test:
        return no_evidence
    if ({row["road_id"] for row in train} & {row["road_id"] for row in test}) or ({row["event_id"] for row in train} & {row["event_id"] for row in test}):
        return no_evidence
    eligible = [row for row in test if isinstance(row.get("prediction"), (int, float)) and not isinstance(row.get("prediction"), bool) and isinstance(row.get("observed"), (int, float)) and not isinstance(row.get("observed"), bool) and isfinite(row["prediction"]) and isfinite(row["observed"])]
    if len(eligible) < int(config.get("minimum_rows", 2)):
        return no_evidence
    errors = [float(r["prediction"]) - float(r["observed"]) for r in eligible]
    return {"status": "evaluated", "metrics": {"n": len(errors), "mae": sum(abs(x) for x in errors) / len(errors), "bias": sum(errors) / len(errors)}, "reason_codes": [], "model_approval": False, "production_eligible": False}
