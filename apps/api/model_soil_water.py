"""Pure selected-UTC-day summary of Open-Meteo ICON Global soil-water layers."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import isfinite
import re
from typing import Any

_BASIS = "weather_model_not_field_observation"
_UNIT = "m³/m³"
_SOURCE_ID = "open-meteo-icon-global"
_MODEL = "icon_global"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_UTC_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|\+00:00)")
_LAYERS = (
    ("soil_moisture_0_to_1cm", 0, 1),
    ("soil_moisture_1_to_3cm", 1, 3),
    ("soil_moisture_3_to_9cm", 3, 9),
)


def summarize_model_soil_water(dto: Any, trip_date: Any) -> dict[str, Any]:
    """Return a bounded, JSON-safe summary without mutating the weather DTO."""
    selected = _strict_date(trip_date)
    result = _empty(selected.isoformat() if selected else None)
    if selected is None or not _valid_binding(dto, selected.isoformat()):
        return result
    result.update({
        "source_id": _SOURCE_ID,
        "model": _MODEL,
        "source_sha256": dto["source"]["content_sha256"],
        "requested_point": _point(dto["requested_point"]),
        "grid_point": _point(dto["grid_point"]),
    })
    rows = dto.get("research_series")
    if not isinstance(rows, list):
        rows = dto.get("series")
    if not isinstance(rows, list) or len(rows) > 256:
        return result
    start = datetime.combine(selected, datetime.min.time(), tzinfo=UTC)
    try:
        end = start + timedelta(days=1)
    except OverflowError:
        return result
    timed: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        moment = _utc_time(row.get("time"))
        if moment is not None and start <= moment < end and moment.minute == moment.second == moment.microsecond == 0:
            timed.setdefault(moment, []).append(row)
    result["layers"] = [_layer(timed, start, name, lower, upper, dto["units"].get(name) == _UNIT) for name, lower, upper in _LAYERS]
    statuses = [layer["status"] for layer in result["layers"]]
    result["status"] = "available" if all(status == "available" for status in statuses) else "unavailable" if all(status == "unavailable" for status in statuses) else "partial"
    return result


def _empty(selected: str | None) -> dict[str, Any]:
    return {
        "date": selected, "timezone": "UTC", "basis": _BASIS, "status": "unavailable",
        "source_id": None, "model": None, "source_sha256": None, "unit": _UNIT,
        "requested_point": None, "grid_point": None,
        "layers": [_layer_empty(name, lower, upper) for name, lower, upper in _LAYERS],
    }


def _layer_empty(name: str, lower: int, upper: int) -> dict[str, Any]:
    return {"variable": name, "from_cm": lower, "to_cm": upper, "status": "unavailable", "min_m3_m3": None, "max_m3_m3": None, "known_samples": 0, "expected_samples": 24}


def _valid_binding(dto: Any, selected: str) -> bool:
    if not isinstance(dto, dict) or dto.get("assessment_date") != selected or not isinstance(dto.get("source"), dict) or not isinstance(dto.get("units"), dict):
        return False
    source = dto["source"]
    return source.get("id") == _SOURCE_ID and source.get("model") == _MODEL and isinstance(source.get("content_sha256"), str) and bool(_DIGEST.fullmatch(source["content_sha256"])) and _point(dto.get("requested_point")) is not None and _point(dto.get("grid_point")) is not None


def _strict_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _point(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    latitude, longitude = _number(value.get("latitude")), _number(value.get("longitude"))
    if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return {"latitude": latitude, "longitude": longitude}


def _utc_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _UTC_TIME.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if isfinite(number) else None


def _layer(rows: dict[datetime, list[dict[str, Any]]], start: datetime, name: str, lower: int, upper: int, valid_unit: bool) -> dict[str, Any]:
    result = _layer_empty(name, lower, upper)
    if not valid_unit:
        return result
    values: list[float] = []
    for hour in range(24):
        matching = rows.get(start + timedelta(hours=hour), [])
        value = _number(matching[0].get(name)) if len(matching) == 1 else None
        if value is not None and 0 <= value <= 1:
            values.append(value)
    result.update({"status": _status(len(values)), "min_m3_m3": min(values) if values else None, "max_m3_m3": max(values) if values else None, "known_samples": len(values)})
    return result


def _status(known: int) -> str:
    return "available" if known == 24 else "partial" if known else "unavailable"
