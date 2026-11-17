"""Warm, real-input research water balance; never a mobility assessment."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

UTC = timezone.utc
MODEL_VERSION = "live-warm-water/1"
MIN_HORIZON_HOURS = 24
MAX_HORIZON_HOURS = 72
STEP_HOURS = 6

# These are sensitivity hypotheses, deliberately not site measurements or priors.
_SCENARIOS = (
    ("slow-drainage", "Повільне дренування (гіпотеза)", {"por1": .45, "por2": .43, "fc1": .30, "fc2": .28, "wp1": .10, "wp2": .12, "kin": 2., "k12": .5, "kb": .2, "hmax": 5., "et1": .65, "et2": .55}),
    ("central-hypothesis", "Проміжна гідравлічна гіпотеза", {"por1": .45, "por2": .43, "fc1": .30, "fc2": .28, "wp1": .10, "wp2": .12, "kin": 4., "k12": 2., "kb": 1., "hmax": 5., "et1": .75, "et2": .65}),
    ("fast-drainage", "Швидке дренування (гіпотеза)", {"por1": .45, "por2": .43, "fc1": .30, "fc2": .28, "wp1": .10, "wp2": .12, "kin": 8., "k12": 5., "kb": 3., "hmax": 3., "et1": .85, "et2": .75}),
)



def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(UTC)


def _z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _source_refs(weather: dict) -> list[dict]:
    sources = []
    supplied = weather.get("source")
    if isinstance(supplied, dict):
        sources.append(supplied)
    rows = weather.get("research_series")
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("source"), dict):
            sources.append(row["source"])
    refs, seen = [], set()
    for source in sources:
        ident, digest = source.get("id"), source.get("content_sha256")
        if isinstance(ident, str) and isinstance(digest, str) and (ident, digest) not in seen:
            refs.append({"id": ident, "content_sha256": digest})
            seen.add((ident, digest))
    return refs


def _base(status: str, codes: list[str], refs: list[dict], *, metrics: dict | None = None, scenarios: list | None = None) -> dict:
    return {"status": status, "model_version": MODEL_VERSION, "condition": "unknown", "summary_uk": "Дослідницький розрахунок водного балансу; це не оцінка прохідності.", "reason_codes": sorted(set(codes)), "metrics": metrics or {"precipitation_mm": None, "et0_mm": None, "net_atmospheric_input_mm": None, "horizon_hours": 0, "max_mass_residual_mm": None}, "scenarios": scenarios or [], "drying_window": {"kind": "unavailable", "earliest": None, "latest": None, "persistence_hours": 12, "censored_scenarios": 0}, "assumptions_uk": ["Початкові модельні вологості сітки не є спостереженнями.", "0–3 cm сіткову вологість перенесено на гіпотетичний шар 0–10 cm, а 3–9 cm — на 10–30 cm; це явне припущення support mapping.", "Три набори параметрів є некаліброваними гідравлічними гіпотезами чутливості, не властивостями ґрунту або дороги.", "ET0 FAO є попитом еталонної евапотранспірації; фактична ET тут обмежена водою.", "Залишкова мерзлота невідома: thermal screen не доводить її відсутність. Результат лише для дослідження."], "source_refs": refs}


def _number(row: dict, name: str) -> float:
    value = row.get(name)
    if isinstance(value, bool):
        raise ValueError
    value = float(value)
    if not isfinite(value):
        raise ValueError
    return value


def _valid_rows(weather: dict) -> tuple[list[dict] | None, list[str]]:
    rows = weather.get("research_series")
    if not isinstance(rows, list) or not rows:
        return None, ["CRITICAL_SOURCE_MISSING"]
    parsed = []
    try:
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError
            at = _time(row["time"])
            parsed.append((at, row))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, ["FORCING_GAP"]
    parsed.sort(key=lambda item: item[0])
    try:
        start = _time(weather["assessment_date"] + "T00:00:00Z") if "assessment_date" in weather else parsed[0][0]
    except (TypeError, ValueError):
        return None, ["STATE_INITIALIZATION_UNAVAILABLE"]
    # Validate only the declared experiment window; later forecast rows cannot
    # change the result of an otherwise identical <=72-hour run.
    parsed = [(at, row) for at, row in parsed if start <= at <= start + timedelta(hours=MAX_HORIZON_HOURS)]
    if not parsed or parsed[0][0] != start:
        return None, ["STATE_INITIALIZATION_UNAVAILABLE"]
    if len({at for at, _ in parsed}) != len(parsed):
        return None, ["FORCING_GAP"]
    return [row for _, row in parsed], []


def _initial(rows: list[dict]) -> tuple[float, float] | None:
    try:
        native = [_number(rows[0], field) for field in ("soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm")]
        if any(value < 0 or value > 1 for value in native):
            return None
        top = (native[0] + 2 * native[1]) / 3
        lower = native[2]
    except (TypeError, ValueError, OverflowError):
        return None
    # Reject rather than clip: no scenario may repair an invalid grid state.
    return (top, lower) if 0 <= top <= 1 and 0 <= lower <= 1 else None


def _forcing(rows: list[dict]) -> tuple[list[dict], list[str]]:
    start = _time(rows[0]["time"])
    contiguous = [rows[0]]
    codes = []
    for row in rows[1:]:
        if _time(row["time"]) != start + timedelta(hours=len(contiguous)):
            codes.append("FORCING_GAP")
            break
        try:
            if min(_number(row, "precipitation"), _number(row, "et0_fao_evapotranspiration")) < 0:
                return [], ["INVALID_FORCING"]
        except (TypeError, ValueError, OverflowError):
            codes.append("FORCING_GAP")
            break
        contiguous.append(row)
    complete_hours = min(MAX_HORIZON_HOURS, len(contiguous) - 1)
    complete_hours -= complete_hours % STEP_HOURS
    bins = []
    for offset in range(0, complete_hours, STEP_HOURS):
        # Row zero is an initial state. Hourly accumulated fields at rows 1..6
        # describe (00,01]..(05,06], hence no row-zero double count.
        hourly = contiguous[offset + 1:offset + STEP_HOURS + 1]
        try:
            precip = sum(_number(r, "precipitation") for r in hourly)
            et0 = sum(_number(r, "et0_fao_evapotranspiration") for r in hourly)
            if not isfinite(precip) or not isfinite(et0):
                return [], ["MODEL_NUMERICAL_FAILURE"]
        except (TypeError, ValueError, OverflowError):
            return [], ["MODEL_NUMERICAL_FAILURE"]
        bins.append({"start": _z(start + timedelta(hours=offset)), "end": _z(start + timedelta(hours=offset + STEP_HOURS)), "P": precip, "D": et0})
    return bins, codes


def _warm(rows: list[dict]) -> bool:
    try:
        return all(_number(row, "soil_temperature_0cm") > 2 and _number(row, "snow_depth") == 0 and _number(row, "snowfall") == 0 for row in rows)
    except (TypeError, ValueError, OverflowError):
        return False


def _run(identifier: str, label: str, p: dict, top: float, lower: float, forcing: list[dict]) -> dict:
    dz1, dz2 = .1, .2
    sat1, sat2 = 1000 * dz1 * p["por1"], 1000 * dz2 * p["por2"]
    fc1, fc2 = 1000 * dz1 * p["fc1"], 1000 * dz2 * p["fc2"]
    wp1, wp2 = 1000 * dz1 * p["wp1"], 1000 * dz2 * p["wp2"]
    L1, L2, H = top * 1000 * dz1, lower * 1000 * dz2, 0.0
    if L1 > sat1 or L2 > sat2:
        return {"id": identifier, "label_uk": label, "status": "unavailable", "parameters": {**p, "dz_1_m": dz1, "dz_2_m": dz2, "parameter_status": "research_hypothesis_not_measured_or_calibrated"}, "initial_state": {"kind": "modelled_grid_moisture_mapped_to_hypothetical_profile", "L1_mm": L1, "L2_mm": L2}, "steps": [], "drying_confirmed_at": None}
    steps = []
    for item in forcing:
        old = H + L1 + L2
        P, D = item["P"], item["D"]
        E_H = min(H, .1 * D)
        surface = H - E_H + P
        F = min(surface, p["kin"] * STEP_HOURS, sat1 - L1)
        surface -= F
        R = max(0., surface - p["hmax"])
        H = surface - R
        L1 += F
        J = min(max(0., L1 - fc1), p["k12"] * STEP_HOURS, sat2 - L2)
        L1 -= J; L2 += J
        Db = min(max(0., L2 - fc2), p["kb"] * STEP_HOURS)
        L2 -= Db
        avail1, avail2 = max(0., L1 - wp1), max(0., L2 - wp2)
        E1 = min(p["et1"] * .55 * D * avail1 / (sat1 - wp1), avail1)
        E2 = min(p["et2"] * .35 * D * avail2 / (sat2 - wp2), avail2)
        L1 -= E1; L2 -= E2
        residual = (H + L1 + L2 - old) - (P - E_H - E1 - E2 - R - Db)
        values = (H, L1, L2, E_H, F, R, J, Db, E1, E2)
        if (not all(isfinite(value) and value >= -1e-9 for value in values)
                or not isfinite(residual) or abs(residual) > 1e-8
                or H > p["hmax"] + 1e-9 or L1 > sat1 + 1e-9 or L2 > sat2 + 1e-9):
            return {"id": identifier, "label_uk": label, "status": "unavailable",
                    "reason_codes": ["MODEL_NUMERICAL_FAILURE"],
                    "parameters": {**p, "dz_1_m": dz1, "dz_2_m": dz2, "parameter_status": "research_hypothesis_not_measured_or_calibrated"},
                    "initial_state": {"L1_mm": top * 1000 * dz1, "L2_mm": lower * 1000 * dz2},
                    "steps": [], "drying_confirmed_at": None}
        steps.append({"start": item["start"], "end": item["end"], "state": {"H": H, "L1": L1, "L2": L2}, "flows": {"precipitation_mm": P, "et0_demand_mm": D, "actual_et_surface_mm": E_H, "infiltration_mm": F, "interlayer_drainage_mm": J, "bottom_drainage_mm": Db, "actual_et_l1_mm": E1, "actual_et_l2_mm": E2, "overflow_runoff_mm": R}, "mass_residual_mm": residual, "theta_1": L1 / (1000 * dz1), "theta_2": L2 / (1000 * dz2)})
    drying = None
    for index in range(len(steps) - 1):
        if steps[index]["state"]["H"] == 0 and steps[index]["state"]["L1"] <= fc1 and steps[index]["state"]["L2"] <= fc2 and steps[index + 1]["state"]["H"] == 0 and steps[index + 1]["state"]["L1"] <= fc1 and steps[index + 1]["state"]["L2"] <= fc2:
            drying = steps[index + 1]["end"]
            break
    return {"id": identifier, "label_uk": label, "status": "research_only", "parameters": {**p, "dz_1_m": dz1, "dz_2_m": dz2, "parameter_status": "research_hypothesis_not_measured_or_calibrated"}, "initial_state": {"kind": "modelled_grid_moisture_mapped_to_hypothetical_profile", "theta_top_m3_m3": top, "theta_lower_m3_m3": lower, "L1_mm": top * 1000 * dz1, "L2_mm": lower * 1000 * dz2}, "steps": steps, "drying_confirmed_at": drying}


def assess_public_weather(weather: dict) -> dict:
    """Assess supplied Open-Meteo-like weather only; it performs no retrieval."""
    refs = _source_refs(weather) if isinstance(weather, dict) else []
    if not isinstance(weather, dict):
        return _base("abstained", ["CRITICAL_SOURCE_MISSING"], refs)
    rows, codes = _valid_rows(weather)
    if rows is None:
        return _base("abstained", codes, refs)
    initial = _initial(rows)
    if initial is None:
        return _base("abstained", ["STATE_INITIALIZATION_UNAVAILABLE"], refs)
    forcing, gap_codes = _forcing(rows)
    if len(forcing) * STEP_HOURS < MIN_HORIZON_HOURS:
        return _base("abstained", sorted(set(gap_codes + ["INSUFFICIENT_COMPLETE_HORIZON"])), refs)
    evaluated_rows = [row for row in rows if _time(row["time"]) <= _time(forcing[-1]["end"])]
    if not _warm(evaluated_rows):
        return _base("abstained", ["FREEZE_THAW_AMBIGUOUS"], refs)
    scenarios = [_run(*scenario, *initial, forcing) for scenario in _SCENARIOS]
    usable = [s for s in scenarios if s["status"] == "research_only"]
    if not usable:
        numerical = any("MODEL_NUMERICAL_FAILURE" in s.get("reason_codes", []) for s in scenarios)
        return _base("abstained", ["MODEL_NUMERICAL_FAILURE" if numerical else "STATE_INITIALIZATION_UNAVAILABLE"], refs)
    precipitation = sum(item["P"] for item in forcing)
    et0 = sum(item["D"] for item in forcing)
    if not isfinite(precipitation) or not isfinite(et0):
        return _base("abstained", ["MODEL_NUMERICAL_FAILURE"], refs)
    final_adverse = any(s["steps"][-1]["state"]["H"] > 0 or s["steps"][-1]["theta_1"] > s["parameters"]["fc1"] or s["steps"][-1]["theta_2"] > s["parameters"]["fc2"] for s in usable)
    condition = "adverse" if final_adverse else "less_adverse"
    if len(usable) != len(scenarios):
        condition = "unknown"
        gap_codes.append("SCENARIO_UNAVAILABLE")
    confirmed = [s["drying_confirmed_at"] for s in usable if s["drying_confirmed_at"]]
    censored = len(scenarios) - len(confirmed)
    drying = {"kind": "scenario_bounds", "earliest": min(confirmed), "latest": max(confirmed) if censored == 0 else None, "persistence_hours": 12, "censored_scenarios": censored} if confirmed else {"kind": "not_reached", "earliest": None, "latest": None, "persistence_hours": 12, "censored_scenarios": censored}
    metrics = {"precipitation_mm": precipitation, "et0_mm": et0, "net_atmospheric_input_mm": precipitation - et0, "horizon_hours": len(forcing) * STEP_HOURS, "max_mass_residual_mm": max(abs(step["mass_residual_mm"]) for s in usable for step in s["steps"])}
    result = _base("research_only", gap_codes, refs, metrics=metrics, scenarios=scenarios)
    result["condition"] = condition
    result["summary_uk"] = "Стан на кінець розрахованого горизонту за найменш сприятливим сценарієм. Це не оцінка прохідності."
    result["assumptions_uk"].extend([
        "Початковий поверхневий запас H=0 mm — припущення; фактичні калюжі або рівень ґрунтових вод не виміряні.",
        "Критерій сценарного підсихання: H=0, θ₁≤0.30 та θ₂≤0.28 m³/m³ на двох послідовних 6-годинних кроках. Ці пороги не є нормою проїзду.",
        "Поточний знімок постачальника від 00:00 обраної UTC-дати; це не історичний прогноз, відновлений станом на минулий момент рішення.",
    ])
    result["drying_window"] = drying
    return result
