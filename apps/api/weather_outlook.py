"""Pure two-day UTC weather outlook summaries."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.api.weather_day import summarize_weather_day


_BASIS = "weather_model_not_field_observation"


def summarize_weather_outlook(dto: Any, trip_date: Any) -> dict[str, Any]:
    """Summarize the two UTC days following a bound weather assessment."""
    selected = _strict_date(trip_date)
    result = _empty(selected.isoformat() if selected else None)
    if selected is None or not _valid_outer_dto(dto, selected.isoformat()):
        return result

    for offset in (1, 2):
        try:
            daily_date = selected + timedelta(days=offset)
        except OverflowError:
            break
        try:
            daily_dto = dict(dto)
            daily_dto["assessment_date"] = daily_date.isoformat()
            result["days"].append(summarize_weather_day(daily_dto, daily_date.isoformat()))
        except OverflowError:
            result["days"].append(summarize_weather_day({}, daily_date.isoformat()))

    statuses = [day["status"] for day in result["days"]]
    if len(statuses) == 2 and all(status == "available" for status in statuses):
        result["status"] = "available"
    elif any(status != "unavailable" for status in statuses):
        result["status"] = "partial"
    return result


def _empty(selected: str | None) -> dict[str, Any]:
    return {
        "date": selected,
        "timezone": "UTC",
        "basis": _BASIS,
        "horizon_days": 2,
        "status": "unavailable",
        "days": [],
    }


def _strict_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _valid_outer_dto(dto: Any, selected: str) -> bool:
    if not isinstance(dto, dict) or dto.get("assessment_date") != selected or not isinstance(dto.get("units"), dict):
        return False
    rows = dto.get("research_series")
    if not isinstance(rows, list):
        rows = dto.get("series")
    return isinstance(rows, list) and len(rows) <= 256
