from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from apps.api.antecedent_precipitation import summarize_antecedent_precipitation

DATE = "2026-06-08"


def _dto() -> dict:
    selected = datetime(2026, 6, 8, tzinfo=UTC)
    rows = []
    for hour in range(169):
        end = selected - timedelta(days=7) + timedelta(hours=hour)
        rows.append({
            "time": end.isoformat().replace("+00:00", "Z"),
            "precipitation": 1.0,
            "precipitation_interval_start": (end - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "precipitation_interval_end": end.isoformat().replace("+00:00", "Z"),
        })
    return {"assessment_date": DATE, "units": {"precipitation": "mm"}, "antecedent_series": rows}


def test_complete_window_uses_168_preceding_hour_intervals_and_seven_daily_totals():
    result = summarize_antecedent_precipitation(_dto(), DATE)

    assert result["date"] == DATE
    assert result["window_start"] == "2026-06-01"
    assert result["window_end_exclusive"] == DATE
    assert result["status"] == "available"
    assert result["total_mm"] == 168.0
    assert result["known_intervals"] == 168
    assert [day["total_mm"] for day in result["days"]] == [24.0] * 7
    assert [day["date"] for day in result["days"]] == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06", "2026-06-07"]


def test_partial_duplicate_invalid_and_overflow_never_claim_totals_or_mutate_input():
    dto = _dto()
    dto["antecedent_series"].append(deepcopy(dto["antecedent_series"][2]))
    dto["antecedent_series"][27]["precipitation"] = -1.0
    dto["antecedent_series"][52]["precipitation"] = float("nan")
    for row in dto["antecedent_series"][73:97]:
        row["precipitation"] = 1e308
    before = deepcopy(dto)

    result = summarize_antecedent_precipitation(dto, DATE)

    assert result["status"] == "partial"
    assert result["total_mm"] is None
    assert result["known_intervals"] == 165
    assert result["days"][0] == {"date": "2026-06-01", "status": "partial", "total_mm": None, "known_intervals": 23, "expected_intervals": 24}
    assert result["days"][1]["status"] == "partial"
    assert result["days"][2]["status"] == "partial"
    assert result["days"][3]["status"] == "partial"
    assert result["days"][3]["total_mm"] is None
    assert dto == before


def test_invalid_date_unbound_units_or_more_than_200_rows_is_safe_unknown():
    dto = _dto()
    assert summarize_antecedent_precipitation(dto, "2026-6-8")["days"] == []
    dto["units"]["precipitation"] = "cm"
    result = summarize_antecedent_precipitation(dto, DATE)
    assert result["status"] == "unavailable"
    assert result["days"] == [{"date": f"2026-06-0{day}", "status": "unavailable", "total_mm": None, "known_intervals": 0, "expected_intervals": 24} for day in range(1, 8)]
    dto = _dto()
    dto["antecedent_series"].extend(deepcopy(dto["antecedent_series"][:32]))
    assert summarize_antecedent_precipitation(dto, DATE)["known_intervals"] == 0


def test_nonrepresentable_interval_value_stays_unknown_without_hiding_other_days():
    dto = _dto()
    dto['antecedent_series'][1]['precipitation'] = 10 ** 1000
    result = summarize_antecedent_precipitation(dto, DATE)
    assert result['total_mm'] is None and result['known_intervals'] == 167
    assert result['days'][0]['total_mm'] is None
    assert all(day['total_mm'] == 24 for day in result['days'][1:])


def test_date_without_representable_prior_seven_days_is_safe_unknown():
    result = summarize_antecedent_precipitation({'assessment_date': '0001-01-01'}, '0001-01-01')
    assert result['status'] == 'unavailable' and result['total_mm'] is None
    assert result['date'] is None and result['window_start'] is None and result['days'] == []
