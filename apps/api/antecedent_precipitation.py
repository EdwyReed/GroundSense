"""Pure summaries of modelled precipitation before a selected UTC day."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any


def summarize_antecedent_precipitation(dto: Any, trip_date: Any) -> dict[str, Any]:
    """Return seven complete UTC daily sums without modifying *dto*."""
    selected = _strict_date(trip_date)
    result = _unknown(selected)
    if selected is None or not isinstance(dto, dict) or dto.get("assessment_date") != selected.isoformat():
        return result
    if not isinstance(dto.get("units"), dict) or dto["units"].get("precipitation") != "mm":
        return result
    rows = dto.get("antecedent_series")
    if not isinstance(rows, list) or len(rows) > 200:
        return result

    start = datetime.combine(selected - timedelta(days=7), datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(selected, datetime.min.time(), tzinfo=UTC)
    intervals: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        moment = _utc_time(row.get("time"))
        if moment is not None and start < moment <= end:
            intervals.setdefault(moment, []).append(row)

    all_values: list[float | None] = []
    days: list[dict[str, Any]] = []
    for day in range(7):
        day_start = start + timedelta(days=day)
        values = [_interval_value(intervals.get(day_start + timedelta(hours=hour), []), day_start + timedelta(hours=hour)) for hour in range(1, 25)]
        known = [value for value in values if value is not None]
        total = sum(known) if len(known) == 24 else None
        if total is not None and not isfinite(total):
            total = None
        status = "available" if total is not None else "partial" if known else "unavailable"
        days.append({"date": day_start.date().isoformat(), "status": status, "total_mm": total, "known_intervals": len(known), "expected_intervals": 24})
        all_values.extend(values)
    known = [value for value in all_values if value is not None]
    total = sum(known) if len(known) == 168 else None
    if total is not None and not isfinite(total):
        total = None
    result.update({"days": days, "known_intervals": len(known), "total_mm": total})
    result["status"] = "available" if total is not None else "partial" if known else "unavailable"
    return result


def _unknown(selected: date | None) -> dict[str, Any]:
    start = selected - timedelta(days=7) if selected else None
    days = [] if selected is None else [
        {"date": (start + timedelta(days=day)).isoformat(), "status": "unavailable", "total_mm": None, "known_intervals": 0, "expected_intervals": 24}
        for day in range(7)
    ]
    return {"date": selected.isoformat() if selected else None, "timezone": "UTC", "basis": "weather_model_not_field_observation", "window_start": start.isoformat() if start else None, "window_end_exclusive": selected.isoformat() if selected else None, "window_days": 7, "status": "unavailable", "total_mm": None, "known_intervals": 0, "expected_intervals": 168, "days": days}


def _strict_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value and parsed >= date(1, 1, 8) else None


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


def _interval_value(rows: list[dict[str, Any]], end: datetime) -> float | None:
    if len(rows) != 1:
        return None
    row = rows[0]
    if _utc_time(row.get("precipitation_interval_start")) != end - timedelta(hours=1) or _utc_time(row.get("precipitation_interval_end")) != end:
        return None
    value = row.get("precipitation")
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if isfinite(number) and number >= 0 else None
