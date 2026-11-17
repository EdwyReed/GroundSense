import random
import unittest
from datetime import datetime, timedelta, timezone

from packages.science.engine import (
    adapt_native_6h,
    assess,
    evaluate_validation,
    recovery_distribution,
    research_run,
)

UTC = timezone.utc
PARAMS = {
    "research_label": "synthetic toy parameters; not approved for product physics",
    "dz_1": 0.1, "dz_2": 0.2,
    "theta_por_1": 0.45, "theta_por_2": 0.43,
    "theta_fc_1": 0.30, "theta_fc_2": 0.28,
    "theta_wp_1": 0.10, "theta_wp_2": 0.12,
    "K_in": 4.0, "K_12": 2.0, "K_b": 1.0, "H_max": 5.0,
    "a_H": 0.2, "a_1": 0.5, "a_2": 0.3,
    "eta_H": 1.0, "eta_1": 0.8, "eta_2": 0.8,
    "numerical_tolerance": 1e-9,
}
INITIAL = {"H": 0.0, "L1": 20.0, "L2": 35.0, "observed": True,
           "card_version": "warm-soil-6h/v1", "support_mapping_version": "test-v1", "available_at": "2026-01-01T00:00:00Z",
           "knowledge_cutoff": "2026-01-03T00:00:00Z"}
THERMAL = {"thermal_screen_version": "test-v1", "pass": True, "snow_absence": True,
           "residual_frozen_state": "no frozen state"}


def iso(hours):
    return (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def forcing(n=4):
    return [{"start": iso(6*i), "end": iso(6*(i+1)), "precipitation_mm": 4.0 if i == 0 else 0.0,
             "et_demand_mm": 1.5, "temperature_c": 10.0,
             "provider_available_at": iso(6*i), "recorded_at": iso(6*i)} for i in range(n)]


class ScienceEngineTests(unittest.TestCase):
    def test_research_transition_conserves_mass_and_stays_bounded(self):
        result = research_run(PARAMS, INITIAL, forcing(), THERMAL)
        self.assertEqual(result["status"], "research_only")
        self.assertTrue(all(abs(step["mass_residual_mm"]) <= 1e-9 for step in result["steps"]))
        self.assertTrue(all(0 <= step["state"]["L1"] <= 45 for step in result["steps"]))
        self.assertTrue(all(0 <= step["state"]["L2"] <= 86 for step in result["steps"]))

    def test_randomized_valid_forcing_preserves_mass_and_bounds(self):
        rng = random.Random(14)
        for _ in range(25):
            rows = forcing(8)
            for row in rows:
                row["precipitation_mm"] = rng.uniform(0, 30)
                row["et_demand_mm"] = rng.uniform(0, 10)
            result = research_run(PARAMS, INITIAL, rows, THERMAL)
            self.assertEqual(result["status"], "research_only")
            self.assertTrue(all(abs(s["mass_residual_mm"]) <= 1e-9 for s in result["steps"]))
            self.assertTrue(all(0 <= s["state"]["H"] <= PARAMS["H_max"] for s in result["steps"]))

    def test_recovery_confirmation_survives_late_failure_and_late_candidate_is_no(self):
        confirmed = recovery_distribution([
            {"weight": 1.0, "predicate": [True, False], "valid": [True, False], "failure_reason": "SOURCE_STALE"},
        ], "2026-01-01T00:00:00Z", 6, 12)
        self.assertEqual(confirmed["probability_by_horizon"], 1.0)
        late = recovery_distribution([
            {"weight": 1.0, "predicate": [False, True], "valid": [True, True]},
        ], "2026-01-01T00:00:00Z", 12, 12)
        self.assertEqual(late["probability_by_horizon"], 0.0)
        self.assertEqual(late["lost_weight_mass"], 0.0)

    def test_research_rejects_cold_missing_late_and_gapped_evidence(self):
        cold = dict(THERMAL, pass_=False)
        cold["pass"] = False
        self.assertIn("FREEZE_THAW_AMBIGUOUS", research_run(PARAMS, INITIAL, forcing(), cold)["reason_codes"])
        missing = forcing(); missing[1].pop("et_demand_mm")
        self.assertIn("CRITICAL_SOURCE_MISSING", research_run(PARAMS, INITIAL, missing, THERMAL)["reason_codes"])
        late = forcing(); late[0]["provider_available_at"] = "2027-01-01T00:00:00Z"
        self.assertIn("SOURCE_STALE", research_run(PARAMS, INITIAL, late, THERMAL)["reason_codes"])
        gap = forcing(); gap[1]["start"] = iso(13)
        self.assertIn("CRITICAL_SOURCE_MISSING", research_run(PARAMS, INITIAL, gap, THERMAL)["reason_codes"])

    def test_native_adapter_keeps_cycle_final_interval_without_cross_cycle_difference(self):
        rows = [
            {"start": iso(0), "end": iso(1), "variable": "precipitation", "value": 1,
             "step_type": "accumulation", "native_units": "mm", "cycle": "a", "startStep": 23, "endStep": 24},
            {"start": iso(1), "end": iso(2), "variable": "precipitation", "value": 2,
             "step_type": "accumulation", "native_units": "mm", "cycle": "b", "startStep": 0, "endStep": 1},
            {"start": iso(2), "end": iso(6), "variable": "precipitation", "value": 3,
             "step_type": "amount", "native_units": "mm", "cycle": "b", "startStep": 1, "endStep": 5},
        ]
        out = adapt_native_6h(rows, iso(0), iso(6), 6)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["bins"][0]["precipitation_mm"], 6.0)

    def test_native_adapter_tiles_each_present_variable_independently(self):
        rows = [
            {"start": iso(0), "end": iso(3), "variable": "precipitation", "value": 2, "step_type": "amount", "native_units": "mm"},
            {"start": iso(3), "end": iso(6), "variable": "precipitation", "value": 4, "step_type": "amount", "native_units": "mm"},
            {"start": iso(0), "end": iso(6), "variable": "et_demand", "value": 1, "step_type": "amount", "native_units": "mm"},
            {"start": iso(0), "end": iso(2), "variable": "temperature", "value": 6, "step_type": "duration_mean", "native_units": "degC"},
            {"start": iso(2), "end": iso(6), "variable": "temperature", "value": 12, "step_type": "duration_mean", "native_units": "degC"},
        ]
        out = adapt_native_6h(rows, iso(0), iso(6), 6)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["bins"], [{"start": iso(0), "end": iso(6), "precipitation_mm": 6.0,
                                        "et_demand_mm": 1.0, "temperature_c": 10.0}])

    def test_native_adapter_rejects_unknown_steps_or_wrong_units(self):
        base = {"start": iso(0), "end": iso(6), "variable": "precipitation", "value": 1}
        for row in ({**base, "step_type": "mystery", "native_units": "mm"},
                    {**base, "step_type": "amount", "native_units": "kg/m2"}):
            self.assertEqual(adapt_native_6h([row], iso(0), iso(6), 6)["status"], "unavailable")

    def test_recovery_keeps_lost_weight_and_censors_quantiles(self):
        result = recovery_distribution([
            {"weight": 0.5, "predicate": [True, True], "valid": [True, True]},
            {"weight": 0.25, "predicate": [False, True], "valid": [True, False], "failure_reason": "MODEL_NUMERICAL_FAILURE"},
            {"weight": 0.25, "predicate": [False, False], "valid": [True, True]},
        ], "2026-01-01T00:00:00Z", 6, 12)
        self.assertEqual(result["bounds_by_horizon"], {"lower": 0.5, "upper": 0.75})
        self.assertIsNone(result["probability_by_horizon"])
        self.assertEqual(result["lost_weight_mass"], 0.25)
        self.assertIsNone(result["quantiles"]["p50"])

    def test_recovery_rejects_empty_nonfinite_or_boolean_weights(self):
        bad = ([], [{"weight": float("nan"), "predicate": [], "valid": []}],
               [{"weight": float("inf"), "predicate": [], "valid": []}],
               [{"weight": True, "predicate": [], "valid": []}])
        for members in bad:
            with self.assertRaises(ValueError):
                recovery_distribution(members, iso(0), 6, 0)

    def test_recovery_distinguishes_complete_zero_from_all_unknown(self):
        zero = recovery_distribution([{"weight": 1., "predicate": [False], "valid": [True]}], iso(0), 6, 6)
        unknown = recovery_distribution([{"weight": 1., "predicate": [False], "valid": [False]}], iso(0), 6, 6)
        self.assertEqual(zero["status"], "forecast_distribution")
        self.assertEqual(zero["probability_by_horizon"], 0.)
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(unknown["bounds_by_horizon"], {"lower": 0., "upper": 1.})
        self.assertTrue(unknown["cdf"])

    def test_research_malformed_params_and_missing_eligibility_abstain(self):
        bad = dict(PARAMS, K_in="not a number")
        self.assertIn("HYDRAULIC_CLOSURE_UNAVAILABLE", research_run(bad, INITIAL, forcing(), THERMAL)["reason_codes"])
        missing_time = forcing(); missing_time[0].pop("provider_available_at")
        self.assertIn("CRITICAL_SOURCE_MISSING", research_run(PARAMS, INITIAL, missing_time, THERMAL)["reason_codes"])

    def test_research_requires_bounded_initial_state_and_card_match(self):
        too_high = dict(INITIAL, H=PARAMS["H_max"] + 1)
        wrong_card = dict(INITIAL, card_version="other-card")
        for initial in (too_high, wrong_card):
            self.assertIn("STATE_INITIALIZATION_UNAVAILABLE", research_run(PARAMS, initial, forcing(), THERMAL)["reason_codes"])
        bad_tolerance = dict(PARAMS, numerical_tolerance=0)
        self.assertIn("HYDRAULIC_CLOSURE_UNAVAILABLE", research_run(bad_tolerance, INITIAL, forcing(), THERMAL)["reason_codes"])

    def test_validation_rejects_leaked_groups_and_evaluates_explicit_heldout_rows(self):
        config = {"heldout": True, "out_of_sample": True, "synthetic": False, "minimum_rows": 2}
        leaked = [
            {"split": "train", "road_id": "r1", "event_id": "e1", "prediction": 1, "observed": 1},
            {"split": "test", "road_id": "r1", "event_id": "e2", "prediction": 2, "observed": 1},
        ]
        self.assertEqual(evaluate_validation(leaked, config)["status"], "insufficient_evidence")
        event_leak = [
            {"split": "train", "road_id": "r1", "event_id": "e1", "prediction": 1, "observed": 1},
            {"split": "test", "road_id": "r2", "event_id": "e1", "prediction": 2, "observed": 1},
        ]
        self.assertEqual(evaluate_validation(event_leak, config)["status"], "insufficient_evidence")
        heldout = [
            {"split": "train", "road_id": "r1", "event_id": "e1", "prediction": 1, "observed": 1},
            {"split": "test", "road_id": "r2", "event_id": "e2", "prediction": 2, "observed": 1},
            {"split": "test", "road_id": "r3", "event_id": "e3", "prediction": 4, "observed": 2},
        ]
        result = evaluate_validation(heldout, config)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["n"], 2)
        self.assertFalse(result["production_eligible"])

    def test_assess_never_makes_a_safe_truck_claim_or_changes_water_by_mass(self):
        a = assess("2026-10-25", 10.0, {"id": "GS-014"}, {})
        b = assess("2026-10-25", 40.0, {"id": "GS-014"}, {})
        self.assertEqual(a["mobility"]["kind"], "unavailable")
        self.assertIn("VEHICLE_ENVELOPE_UNSUPPORTED", a["mobility"]["reason_codes"])
        self.assertEqual(a["series"], b["series"])
        self.assertEqual(a["condition"], "unknown")

    def test_synthetic_chart_uses_volumetric_units_without_invented_spread(self):
        result = assess('2026-10-25', 20., {'id':'GS-014'}, {})
        self.assertTrue(result['series'])
        for row in result['series']:
            self.assertLessEqual(row['moisture_p50'], .45)
            self.assertGreaterEqual(row['moisture_p50'], 0)
            self.assertIsNone(row['moisture_p10'])
            self.assertIsNone(row['moisture_p90'])
        self.assertFalse(result['uncertainty_available'])
        self.assertIsNone(result['forecast_issue_time'])

    def test_validation_requires_heldout_non_synthetic_data(self):
        self.assertIsNone(evaluate_validation([], {"heldout": True, "out_of_sample": True, "synthetic": False})["metrics"])
        self.assertEqual(evaluate_validation([{"prediction": 1, "observed": 1}], {"heldout": True, "out_of_sample": True, "synthetic": True})["status"], "research_only")
        self.assertEqual(evaluate_validation([{"prediction": 1, "observed": 1}], {"heldout": False, "out_of_sample": True, "synthetic": False})["status"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
