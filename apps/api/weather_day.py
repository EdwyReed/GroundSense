"""Pure UTC-day summaries for model weather DTOs."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any


_EXPECTED_UNITS = {"precipitation": "mm", "soil_temperature_0cm": "°C", "snow_depth": "m"}


def summarize_weather_day(dto: Any, trip_date: Any) -> dict[str, Any]:
    """Summarize one selected UTC day without changing the provider DTO."""
    selected = _strict_date(trip_date)
    result = _unknown(selected.isoformat() if selected else None)
    if selected is None or not isinstance(dto, dict) or dto.get("assessment_date") != selected.isoformat():
        return result
    if not isinstance(dto.get("units"), dict):
        return result

    rows = dto.get("research_series")
    if not isinstance(rows, list):
        rows = dto.get("series")
    if not isinstance(rows, list) or len(rows) > 256:
        return result

    start = datetime.combine(selected, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    instantaneous: dict[datetime, list[dict[str, Any]]] = {}
    intervals: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        moment = _utc_time(row.get("time"))
        if moment is None:
            continue
        if start <= moment < end:
            instantaneous.setdefault(moment, []).append(row)
        if start < moment <= end:
            intervals.setdefault(moment, []).append(row)

    units = dto['units']
    soil_values = _instant_values(instantaneous, start, "soil_temperature_0cm", nonnegative=False) if units.get('soil_temperature_0cm') == _EXPECTED_UNITS['soil_temperature_0cm'] else [None] * 24
    snow_values = _instant_values(instantaneous, start, "snow_depth", nonnegative=True) if units.get('snow_depth') == _EXPECTED_UNITS['snow_depth'] else [None] * 24
    rain_values = _interval_values(intervals, start) if units.get('precipitation') == _EXPECTED_UNITS['precipitation'] else [None] * 24
    result["precipitation"] = _precipitation(rain_values)
    result["soil_temperature"] = _soil(soil_values)
    result["snow_depth"] = _snow(snow_values)
    statuses = [result[name]["status"] for name in ("precipitation", "soil_temperature", "snow_depth")]
    result["status"] = "available" if all(status == "available" for status in statuses) else "unavailable" if all(status == "unavailable" for status in statuses) else "partial"
    return result


def _unknown(selected: str | None) -> dict[str, Any]:
    return {
        "date": selected,
        "timezone": "UTC",
        "status": "unavailable",
        "basis": "weather_model_not_field_observation",
        "precipitation": {"status": "unavailable", "total_mm": None, "known_intervals": 0, "expected_intervals": 24},
        "soil_temperature": {"status": "unavailable", "min_c": None, "max_c": None, "known_samples": 0, "expected_samples": 24, "at_or_below_zero_samples": 0},
        "snow_depth": {"status": "unavailable", "min_m": None, "max_m": None, "known_samples": 0, "expected_samples": 24},
    }


def _strict_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _utc_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _number(value: Any, *, nonnegative: bool) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if not isfinite(number) or (nonnegative and number < 0):
        return None
    return number


def _instant_values(rows: dict[datetime, list[dict[str, Any]]], start: datetime, field: str, *, nonnegative: bool) -> list[float | None]:
    values: list[float | None] = []
    for hour in range(24):
        matching = rows.get(start + timedelta(hours=hour), [])
        values.append(_number(matching[0].get(field), nonnegative=nonnegative) if len(matching) == 1 else None)
    return values


def _interval_values(rows: dict[datetime, list[dict[str, Any]]], start: datetime) -> list[float | None]:
    values: list[float | None] = []
    for hour in range(1, 25):
        end = start + timedelta(hours=hour)
        matching = rows.get(end, [])
        if len(matching) != 1:
            values.append(None)
            continue
        row = matching[0]
        values.append(
            _number(row.get("precipitation"), nonnegative=True)
            if _utc_time(row.get("precipitation_interval_start")) == end - timedelta(hours=1)
            and _utc_time(row.get("precipitation_interval_end")) == end
            else None
        )
    return values


def _status(known: int) -> str:
    return "available" if known == 24 else "partial" if known else "unavailable"


def _precipitation(values: list[float | None]) -> dict[str, Any]:
    known = [value for value in values if value is not None]
    total = sum(known) if len(known) == 24 else None
    if total is not None and not isfinite(total):
        total = None
    status = 'partial' if len(known) == 24 and total is None else _status(len(known))
    return {"status": status, "total_mm": total, "known_intervals": len(known), "expected_intervals": 24}


def _soil(values: list[float | None]) -> dict[str, Any]:
    known = [value for value in values if value is not None]
    return {"status": _status(len(known)), "min_c": min(known) if known else None, "max_c": max(known) if known else None, "known_samples": len(known), "expected_samples": 24, "at_or_below_zero_samples": sum(value <= 0 for value in known)}


def _snow(values: list[float | None]) -> dict[str, Any]:
    known = [value for value in values if value is not None]
    return {"status": _status(len(known)), "min_m": min(known) if known else None, "max_m": max(known) if known else None, "known_samples": len(known), "expected_samples": 24}
