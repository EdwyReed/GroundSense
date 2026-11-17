from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import pytest

from apps.api.model_soil_water import summarize_model_soil_water

DATE = "2026-10-26"
DIGEST = "sha256:4ef282407d6e88b8414b9381349b45c8c1feb3a82988416697e83db9decda4b4"
LAYERS = (
    ("soil_moisture_0_to_1cm", 0, 1),
    ("soil_moisture_1_to_3cm", 1, 3),
    ("soil_moisture_3_to_9cm", 3, 9),
)


def _dto(*, rows=None):
    start = datetime.fromisoformat(DATE).replace(tzinfo=UTC)
    if rows is None:
        rows = [
            {
                "time": (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                "soil_moisture_0_to_1cm": 0.296 + hour / 10000,
                "soil_moisture_1_to_3cm": 0.298 + hour / 10000,
                "soil_moisture_3_to_9cm": 0.306 + hour / 10000,
            }
            for hour in range(24)
        ]
    return {
        "assessment_date": DATE,
        "requested_point": {"latitude": 59.98500020992624, "longitude": 10.733331822658165},
        "grid_point": {"latitude": 60, "longitude": 10.75},
        "source": {"id": "open-meteo-icon-global", "model": "icon_global", "content_sha256": DIGEST},
        "units": {name: "m³/m³" for name, _, _ in LAYERS},
        "research_series": rows,
    }


def test_summarizes_bound_dto_into_three_ordered_native_layers_without_mutation():
    dto = _dto()
    before = deepcopy(dto)

    result = summarize_model_soil_water(dto, DATE)

    assert result == {
        "date": DATE,
        "timezone": "UTC",
        "basis": "weather_model_not_field_observation",
        "status": "available",
        "source_id": "open-meteo-icon-global",
        "model": "icon_global",
        "source_sha256": DIGEST,
        "unit": "m³/m³",
        "requested_point": dto["requested_point"],
        "grid_point": dto["grid_point"],
        "layers": [
            {"variable": name, "from_cm": lower, "to_cm": upper, "status": "available", "min_m3_m3": dto["research_series"][0][name], "max_m3_m3": dto["research_series"][-1][name], "known_samples": 24, "expected_samples": 24}
            for name, lower, upper in LAYERS
        ],
    }
    assert dto == before
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_bad_unit_is_local_to_its_layer_while_zero_remains_a_known_value():
    dto = _dto()
    dto["units"]["soil_moisture_1_to_3cm"] = "percent"
    dto["research_series"][0]["soil_moisture_0_to_1cm"] = 0

    result = summarize_model_soil_water(dto, DATE)

    assert result["status"] == "partial"
    assert result["layers"][0]["status"] == "available"
    assert result["layers"][0]["min_m3_m3"] == 0
    assert result["layers"][1] == {"variable": "soil_moisture_1_to_3cm", "from_cm": 1, "to_cm": 3, "status": "unavailable", "min_m3_m3": None, "max_m3_m3": None, "known_samples": 0, "expected_samples": 24}
    assert result["layers"][2]["status"] == "available"


def test_calendar_upper_bound_and_over_budget_input_fail_closed_without_raising():
    dto = _dto(rows=[{"time": "9999-12-31T00:00:00Z"}])
    dto["assessment_date"] = "9999-12-31"

    result = summarize_model_soil_water(dto, "9999-12-31")

    assert result["date"] == "9999-12-31"
    assert result["status"] == "unavailable"
    assert all(layer["known_samples"] == 0 for layer in result["layers"])

    dto = _dto(rows=[{}] * 257)
    result = summarize_model_soil_water(dto, DATE)
    assert result["status"] == "unavailable"
    assert all(layer["known_samples"] == 0 for layer in result["layers"])


def test_duplicate_and_invalid_hourly_values_become_unknown_per_layer_and_do_not_leak_other_days():
    dto = _dto()
    duplicate = deepcopy(dto["research_series"][1])
    duplicate["time"] = "2026-10-26T01:00:00+00:00"  # Equivalent UTC instant as hour 1.
    dto["research_series"].append(duplicate)
    dto["research_series"].append({"time": "2026-10-26T03:00:00+02:00", "soil_moisture_0_to_1cm": 0})
    dto["research_series"][2]["soil_moisture_0_to_1cm"] = None
    dto["research_series"][3]["soil_moisture_0_to_1cm"] = True
    dto["research_series"][4]["soil_moisture_0_to_1cm"] = -0.01
    dto["research_series"][5]["soil_moisture_0_to_1cm"] = 1.01
    dto["research_series"].append({"time": "2026-10-27T00:00:00Z", "soil_moisture_0_to_1cm": 0})

    result = summarize_model_soil_water(dto, DATE)

    first, second, third = result["layers"]
    assert result["status"] == "partial"
    assert first["status"] == "partial" and first["known_samples"] == 19
    assert first["min_m3_m3"] == dto["research_series"][0]["soil_moisture_0_to_1cm"]
    assert second["status"] == third["status"] == "partial"
    assert second["known_samples"] == third["known_samples"] == 23


def test_invalid_outer_date_source_or_points_fail_closed_with_null_metadata():
    dto = _dto()
    dto["assessment_date"] = "2026-10-27"
    result = summarize_model_soil_water(dto, DATE)
    assert result["status"] == "unavailable"
    assert result["source_id"] is result["model"] is result["source_sha256"] is None
    assert result["requested_point"] is result["grid_point"] is None

    dto = _dto()
    dto["source"]["content_sha256"] = "sha256:" + "A" * 64
    dto["requested_point"]["latitude"] = float("nan")
    result = summarize_model_soil_water(dto, DATE)
    assert result["status"] == "unavailable"
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("rewrite", [
    lambda value: value.replace("T", " "),
    lambda value: value.replace("T", "_"),
    lambda value: value.replace("T", "t"),
    lambda value: value.replace("-", ""),
])
def test_noncanonical_timestamp_spellings_cannot_supply_hourly_coverage(rewrite):
    dto = _dto()
    for row in dto["research_series"]:
        row["time"] = rewrite(row["time"])
    result = summarize_model_soil_water(dto, DATE)
    assert result["status"] == "unavailable"
    assert [layer["known_samples"] for layer in result["layers"]] == [0, 0, 0]
