"""Adversarial scientific integrity regressions; deliberately controlled input fixtures."""
from copy import deepcopy

import pytest

from tests.runtime_science.test_public_assessment import _weather
from packages.science.public_assessment import assess_public_weather


@pytest.mark.parametrize("field", ["precipitation", "et0_fao_evapotranspiration"])
def test_negative_hourly_amount_cannot_be_cancelled_by_positive_neighbour(field):
    weather = _weather()
    weather["research_series"][1][field] = -1.0
    weather["research_series"][2][field] = 2.0
    result = assess_public_weather(weather)
    assert result["status"] == "abstained"
    assert result["reason_codes"]


def test_invalid_native_initial_moisture_is_not_hidden_in_weighted_mean():
    weather = _weather()
    weather["research_series"][0]["soil_moisture_0_to_1cm"] = -.1
    weather["research_series"][0]["soil_moisture_1_to_3cm"] = .4
    assert assess_public_weather(weather)["status"] == "abstained"


def test_finite_hourly_values_that_overflow_bin_cannot_publish_nonfinite_balance():
    weather = _weather()
    for row in weather["research_series"][1:7]:
        row["precipitation"] = 1e308
    assert assess_public_weather(weather)["status"] == "abstained"


def test_censored_scenario_does_not_invent_a_finite_latest_drying_time():
    weather = _weather(et0=.01)
    for row in weather["research_series"]:
        row["soil_moisture_0_to_1cm"] = .325
        row["soil_moisture_1_to_3cm"] = .325
        row["soil_moisture_3_to_9cm"] = .328
        row["precipitation"] = .5
    result = assess_public_weather(weather)
    assert result["status"] == "research_only"
    window = result["drying_window"]
    assert 0 < window["censored_scenarios"] < 3
    assert window["earliest"] is not None
    assert window["latest"] is None


def test_rows_after_72h_do_not_change_the_bounded_experiment():
    weather = _weather()
    expected = assess_public_weather(weather)
    extra = deepcopy(weather["research_series"][-1])
    extra["time"] = "2026-06-04T01:00:00Z"
    extra["soil_temperature_0cm"] = -10
    weather["research_series"].append(extra)
    assert assess_public_weather(weather) == expected


def test_selected_date_requires_midnight_initial_state_not_shifted_missing_hour():
    weather = _weather()
    weather["assessment_date"] = "2026-06-01"
    weather["research_series"].pop(0)
    result = assess_public_weather(weather)
    assert result["status"] == "abstained"
    assert result["reason_codes"]


def test_late_null_stops_at_first_gap_without_discarding_complete_prefix():
    weather = _weather()
    weather["research_series"][31]["precipitation"] = None
    result = assess_public_weather(weather)
    assert result["status"] == "research_only"
    assert result["metrics"]["horizon_hours"] == 30
    assert "FORCING_GAP" in result["reason_codes"]
