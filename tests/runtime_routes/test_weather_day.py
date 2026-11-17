from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from apps.api.weather_day import summarize_weather_day


DATE = "2026-06-01"


def _dto(*, rows: list[dict] | None = None) -> dict:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    if rows is None:
        rows = []
        for hour in range(25):
            moment = start + timedelta(hours=hour)
            rows.append(
                {
                    "time": moment.isoformat().replace("+00:00", "Z"),
                    "precipitation": float(hour),
                    "precipitation_interval_start": (moment - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    "precipitation_interval_end": moment.isoformat().replace("+00:00", "Z"),
                    "soil_temperature_0cm": float(hour - 12),
                    "snow_depth": float(hour) / 100,
                }
            )
    return {
        "assessment_date": DATE,
        "units": {"precipitation": "mm", "soil_temperature_0cm": "°C", "snow_depth": "m"},
        "research_series": rows,
    }


def _unknown(date: str | None = DATE) -> dict:
    return {
        "date": date,
        "timezone": "UTC",
        "status": "unavailable",
        "basis": "weather_model_not_field_observation",
        "precipitation": {"status": "unavailable", "total_mm": None, "known_intervals": 0, "expected_intervals": 24},
        "soil_temperature": {"status": "unavailable", "min_c": None, "max_c": None, "known_samples": 0, "expected_samples": 24, "at_or_below_zero_samples": 0},
        "snow_depth": {"status": "unavailable", "min_m": None, "max_m": None, "known_samples": 0, "expected_samples": 24},
    }


def test_complete_selected_utc_day_uses_interval_end_and_model_samples():
    dto = _dto()
    result = summarize_weather_day(dto, DATE)

    assert result == {
        "date": DATE,
        "timezone": "UTC",
        "status": "available",
        "basis": "weather_model_not_field_observation",
        "precipitation": {"status": "available", "total_mm": 300.0, "known_intervals": 24, "expected_intervals": 24},
        "soil_temperature": {"status": "available", "min_c": -12.0, "max_c": 11.0, "known_samples": 24, "expected_samples": 24, "at_or_below_zero_samples": 13},
        "snow_depth": {"status": "available", "min_m": 0.0, "max_m": 0.23, "known_samples": 24, "expected_samples": 24},
    }


def test_partial_precipitation_never_exposes_a_partial_daily_total():
    dto = _dto()
    dto["research_series"].pop()

    result = summarize_weather_day(dto, DATE)

    assert result["precipitation"] == {"status": "partial", "total_mm": None, "known_intervals": 23, "expected_intervals": 24}


def test_finite_interval_values_with_overflow_do_not_emit_a_daily_total():
    dto = _dto()
    for row in dto["research_series"][1:]:
        row["precipitation"] = 1e308

    result = summarize_weather_day(dto, DATE)

    assert result["precipitation"] == {"status": "partial", "total_mm": None, "known_intervals": 24, "expected_intervals": 24}


def test_duplicate_timestamp_invalidates_its_local_hour_for_all_metrics():
    dto = _dto()
    dto["research_series"].append(deepcopy(dto["research_series"][4]))

    result = summarize_weather_day(dto, DATE)

    assert result["precipitation"] == {"status": "partial", "total_mm": None, "known_intervals": 23, "expected_intervals": 24}
    assert result["soil_temperature"]["known_samples"] == 23
    assert result["snow_depth"]["known_samples"] == 23


def test_invalid_schema_or_units_returns_safe_unknown_without_mutating_dto():
    dto = _dto()
    before = deepcopy(dto)
    dto["assessment_date"] = "2026-06-02"
    assert summarize_weather_day(dto, DATE) == _unknown()
    assert dto != before


    dto = _dto()
    before = deepcopy(dto)
    assert summarize_weather_day(dto, "2026-6-1") == _unknown(None)
    assert dto == before


def test_wrong_optional_snow_unit_does_not_erase_valid_rain_or_temperature():
    dto = _dto()
    dto['units']['snow_depth'] = 'cm'
    before = deepcopy(dto)
    result = summarize_weather_day(dto, DATE)
    assert result['precipitation']['status'] == 'available'
    assert result['soil_temperature']['status'] == 'available'
    assert result['snow_depth'] == _unknown()['snow_depth']
    assert result['status'] == 'partial'
    assert dto == before


def test_boolean_nonfinite_and_negative_values_are_unknown_but_real_zero_and_negative_soil_remain():
    dto = _dto()
    dto["research_series"][1]["precipitation"] = True
    dto["research_series"][2]["snow_depth"] = -1.0
    dto["research_series"][3]["soil_temperature_0cm"] = float("nan")
    dto["research_series"][4]["soil_temperature_0cm"] = -5.0
    dto["research_series"][5]["snow_depth"] = 0.0

    result = summarize_weather_day(dto, DATE)

    assert result["precipitation"]["known_intervals"] == 23
    assert result["precipitation"]["total_mm"] is None
    assert result["snow_depth"] == {"status": "partial", "min_m": 0.0, "max_m": 0.23, "known_samples": 23, "expected_samples": 24}
    assert result["soil_temperature"] == {"status": "partial", "min_c": -12.0, "max_c": 11.0, "known_samples": 23, "expected_samples": 24, "at_or_below_zero_samples": 12}


def test_series_fallback_accepts_256_rows_but_rejects_uninspected_tail_duplicates():
    dto = _dto()
    dto["series"] = dto.pop("research_series")
    dto["research_series"] = None
    outside = deepcopy(dto["series"][4])
    outside["time"] = "2026-06-03T04:00:00Z"
    duplicate = deepcopy(dto["series"][4])
    dto["series"].extend([outside] * 231)
    assert summarize_weather_day(dto, DATE)['status'] == 'available'
    dto["series"].append(duplicate)

    assert summarize_weather_day(dto, DATE) == _unknown()
