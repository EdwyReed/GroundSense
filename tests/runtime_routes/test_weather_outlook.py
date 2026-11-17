from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from apps.api.weather_outlook import summarize_weather_outlook


DATE = "2026-06-01"


def _row(moment: datetime) -> dict:
    return {
        "time": moment.isoformat().replace("+00:00", "Z"),
        "precipitation": 1.0,
        "precipitation_interval_start": (moment - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "precipitation_interval_end": moment.isoformat().replace("+00:00", "Z"),
        "soil_temperature_0cm": float(moment.hour - 12),
        "snow_depth": float(moment.hour) / 100,
    }


def _dto(*, rows: list[dict] | None = None, assessment_date: str = DATE) -> dict:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    return {
        "assessment_date": assessment_date,
        "units": {"precipitation": "mm", "soil_temperature_0cm": "°C", "snow_depth": "m"},
        "research_series": rows if rows is not None else [_row(start + timedelta(hours=hour)) for hour in range(73)],
    }


def test_two_complete_future_days_reuse_daily_summaries_without_mutating_dto():
    dto = _dto()
    before = deepcopy(dto)

    result = summarize_weather_outlook(dto, DATE)

    assert result["date"] == DATE
    assert result["timezone"] == "UTC"
    assert result["basis"] == "weather_model_not_field_observation"
    assert result["horizon_days"] == 2
    assert result["status"] == "available"
    assert [day["date"] for day in result["days"]] == ["2026-06-02", "2026-06-03"]
    assert all(day["status"] == "available" for day in result["days"])
    assert all(day["precipitation"] == {"status": "available", "total_mm": 24.0, "known_intervals": 24, "expected_intervals": 24} for day in result["days"])
    assert dto == before


def test_final_day_with_23_of_24_precipitation_intervals_keeps_other_metrics():
    dto = _dto()
    dto["research_series"].pop()

    result = summarize_weather_outlook(dto, DATE)

    assert result["status"] == "partial"
    assert result["days"][0]["status"] == "available"
    final = result["days"][1]
    assert final["precipitation"] == {"status": "partial", "total_mm": None, "known_intervals": 23, "expected_intervals": 24}
    assert final["soil_temperature"]["status"] == "available"
    assert final["snow_depth"]["status"] == "available"


def test_duplicate_and_bad_unit_are_metric_local():
    dto = _dto()
    dto["research_series"].append(deepcopy(dto["research_series"][28]))
    dto["units"]["snow_depth"] = "cm"

    result = summarize_weather_outlook(dto, DATE)

    day = result["days"][0]
    assert day["precipitation"]["known_intervals"] == 23
    assert day["soil_temperature"]["known_samples"] == 23
    assert day["snow_depth"] == {"status": "unavailable", "min_m": None, "max_m": None, "known_samples": 0, "expected_samples": 24}
    assert result["days"][1]["soil_temperature"]["status"] == "available"


def test_missing_rows_bad_binding_and_over_cap_are_empty_unavailable():
    missing_rows = _dto()
    missing_rows.pop("research_series")
    for dto, trip_date in (
        (missing_rows, DATE),
        (_dto(assessment_date="2026-06-02"), DATE),
        (_dto(), "2026-6-1"),
        (_dto(rows=[{}] * 257), DATE),
    ):
        result = summarize_weather_outlook(dto, trip_date)
        assert result["status"] == "unavailable"
        assert result["days"] == []

    empty_rows = summarize_weather_outlook(_dto(rows=[]), DATE)
    assert empty_rows["status"] == "unavailable"
    assert [day["date"] for day in empty_rows["days"]] == ["2026-06-02", "2026-06-03"]


def test_overflowing_integer_is_local_and_does_not_erase_valid_metrics():
    dto = _dto()
    dto["research_series"][25]["precipitation"] = 10**10000

    result = summarize_weather_outlook(dto, DATE)

    day = result["days"][0]
    assert day["precipitation"] == {"status": "partial", "total_mm": None, "known_intervals": 23, "expected_intervals": 24}
    assert day["soil_temperature"]["status"] == "available"
    assert day["snow_depth"]["status"] == "available"


def test_finite_precipitation_sum_overflow_is_unknown_total_only():
    dto = _dto()
    for row in dto["research_series"][25:49]:
        row["precipitation"] = 1e308

    result = summarize_weather_outlook(dto, DATE)

    assert result["days"][0]["precipitation"] == {"status": "partial", "total_mm": None, "known_intervals": 24, "expected_intervals": 24}
    assert result["days"][0]["soil_temperature"]["status"] == "available"


def test_calendar_overflow_retains_representable_unknown_prefix():
    dto = _dto(rows=[], assessment_date="9999-12-30")

    result = summarize_weather_outlook(dto, "9999-12-30")

    assert result["status"] == "unavailable"
    assert [day["date"] for day in result["days"]] == ["9999-12-31"]
    assert result["days"][0]["status"] == "unavailable"
