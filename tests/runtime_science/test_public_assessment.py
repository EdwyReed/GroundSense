from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite

from packages.science.public_assessment import assess_public_weather

UTC = timezone.utc


def _weather(hours=72, *, rain_at=None, et0=0.25):
    start = datetime(2026, 6, 1, tzinfo=UTC)
    rows = []
    for hour in range(hours + 1):
        rows.append({
            "time": (start + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
            "precipitation": 12.0 if hour == rain_at else 0.0,
            "et0_fao_evapotranspiration": et0,
            "temperature_2m": 12.0,
            "soil_temperature_0cm": 8.0,
            "soil_moisture_0_to_1cm": 0.25,
            "soil_moisture_1_to_3cm": 0.25,
            "soil_moisture_3_to_9cm": 0.26,
            "snow_depth": 0.0,
            "snowfall": 0.0,
        })
    return {"series": rows[:25], "research_series": rows,
            "source": {"id": "open-meteo-test", "model": "test", "content_sha256": "abc", "retrieved_at": "2026-06-01T00:00:00Z", "issue_time": None}}


def test_real_input_run_has_exact_research_contract_and_six_hour_mass_balance():
    result = assess_public_weather(_weather(rain_at=2))

    assert set(result) == {"status", "model_version", "condition", "summary_uk", "reason_codes", "metrics", "scenarios", "drying_window", "assumptions_uk", "source_refs"}
    assert result["status"] == "research_only"
    assert result["model_version"] == "live-warm-water/1"
    assert len(result["scenarios"]) == 3
    assert result["metrics"]["horizon_hours"] == 72
    assert result["metrics"]["precipitation_mm"] == 12.0
    assert result["metrics"]["et0_mm"] == 18.0
    assert result["source_refs"] == [{"id": "open-meteo-test", "content_sha256": "abc"}]
    for scenario in result["scenarios"]:
        assert scenario["status"] == "research_only"
        assert len(scenario["steps"]) == 12
        assert scenario["initial_state"]["kind"] == "modelled_grid_moisture_mapped_to_hypothetical_profile"
        assert all(abs(step["mass_residual_mm"]) < 1e-9 for step in scenario["steps"])
        assert all(isfinite(value) and value >= 0 for step in scenario["steps"] for value in step["state"].values())


def test_initial_row_is_state_not_forcing_and_dry_forcing_drains():
    weather = _weather(et0=1.0)
    weather["research_series"][0]["precipitation"] = 99.0
    result = assess_public_weather(weather)

    assert result["metrics"]["precipitation_mm"] == 0.0
    assert all(s["steps"][-1]["state"]["L1"] < s["initial_state"]["L1_mm"] for s in result["scenarios"])


def test_missing_or_cold_or_snow_abstains_without_invented_fallback():
    missing = _weather()
    missing["research_series"][4]["et0_fao_evapotranspiration"] = None
    cold = _weather()
    cold["research_series"][10]["soil_temperature_0cm"] = 2.0
    snow = _weather()
    snow["research_series"][10]["snowfall"] = 0.1

    for weather, reason in ((missing, "FORCING_GAP"), (cold, "FREEZE_THAW_AMBIGUOUS"), (snow, "FREEZE_THAW_AMBIGUOUS")):
        result = assess_public_weather(weather)
        assert result["status"] == "abstained"
        assert reason in result["reason_codes"]
        assert result["scenarios"] == []


def test_invalid_initial_modelled_moisture_abstains_instead_of_clipping():
    weather = _weather()
    weather["research_series"][0]["soil_moisture_0_to_1cm"] = 1.2

    result = assess_public_weather(weather)

    assert result["status"] == "abstained"
    assert "STATE_INITIALIZATION_UNAVAILABLE" in result["reason_codes"]


def test_stops_at_first_incomplete_six_hour_bin_and_uses_complete_partial_horizon():
    result = assess_public_weather(_weather(hours=30))

    assert result["status"] == "research_only"
    assert result["metrics"]["horizon_hours"] == 30
    assert all(len(s["steps"]) == 5 for s in result["scenarios"])


def test_fewer_than_24_complete_hours_abstains():
    result = assess_public_weather(_weather(hours=23))

    assert result["status"] == "abstained"
    assert "INSUFFICIENT_COMPLETE_HORIZON" in result["reason_codes"]


def test_null_is_missing_but_zero_is_valid_forcing():
    zero = assess_public_weather(_weather(et0=0.0))
    null = _weather(et0=0.0)
    null["research_series"][1]["precipitation"] = None

    assert zero["status"] == "research_only"
    assert zero["metrics"]["et0_mm"] == 0.0
    assert assess_public_weather(null)["status"] == "abstained"


def test_rain_increases_stored_water_and_random_bounded_inputs_conserve_mass():
    dry = assess_public_weather(_weather(et0=0.1))
    wet = assess_public_weather(_weather(rain_at=2, et0=0.1))
    assert wet["scenarios"][0]["steps"][-1]["state"]["L1"] > dry["scenarios"][0]["steps"][-1]["state"]["L1"]

    weather = _weather(et0=0.0)
    for hour, row in enumerate(weather["research_series"]):
        row["precipitation"] = (hour * 7 % 13) / 10
        row["et0_fao_evapotranspiration"] = (hour * 11 % 9) / 20
    result = assess_public_weather(weather)
    assert result["status"] == "research_only"
    for scenario in result["scenarios"]:
        parameters = scenario["parameters"]
        for step in scenario["steps"]:
            assert 0 <= step["theta_1"] <= parameters["por1"]
            assert 0 <= step["theta_2"] <= parameters["por2"]
            assert abs(step["mass_residual_mm"]) < 1e-9
