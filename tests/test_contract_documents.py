"""Wire-contract checks only. No trafficability engine is implemented."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_contracts import validate_assessment, validate_document

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/assessment.schema.json"
EXAMPLES = ("forcing-only-g0b", "exact-g1", "partial-loss", "synthetic-g2")


class ContractDocuments(unittest.TestCase):
    def validator(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def sample(self, name="forcing-only-g0b"):
        return json.loads((ROOT / f"contracts/examples/{name}.json").read_text())

    def assert_contract_valid(self, record):
        schema_errors = list(self.validator().iter_errors(record))
        self.assertEqual([], schema_errors, [error.message for error in schema_errors])
        self.assertEqual([], validate_assessment(record))

    def assert_invalid(self, record, text):
        errors = validate_document(record)
        self.assertTrue(errors, "mutation unexpectedly passed")
        self.assertTrue(any(text in error for error in errors), errors)

    def test_v11_bundle_and_required_first_slice_examples_are_delivered(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        self.assertEqual("urn:groundsense:contracts:1.1", schema["$id"])
        for definition in ("AnalysisAcceptance", "JobStatus", "ServingEnvelope", "ManifestView", "ResultManifest", "ScientificAssessment", "RecoveryDistribution"):
            self.assertIn(definition, schema["$defs"])
        for name in EXAMPLES:
            self.assertTrue((ROOT / f"contracts/examples/{name}.json").is_file())

    def test_dto_bundle_examples_validate_against_their_shared_definitions(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        bundle_path = ROOT / "contracts/examples/dto-bundle.json"
        self.assertTrue(bundle_path.is_file())
        bundle = json.loads(bundle_path.read_text())
        for name in ("AnalysisAcceptance", "JobStatus", "ServingEnvelope", "ManifestView", "ResultManifest"):
            with self.subTest(name=name):
                sub_schema = {"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}
                errors = list(Draft202012Validator(sub_schema, format_checker=FormatChecker()).iter_errors(bundle[name]))
                self.assertEqual([], errors, [error.message for error in errors])

    def test_every_assessment_example_uses_the_current_contract(self):
        for path in sorted((ROOT / "contracts/examples").glob("*.json")):
            if path.name == "dto-bundle.json":
                continue
            with self.subTest(path=path.name):
                self.assert_contract_valid(json.loads(path.read_text()))

    def test_first_slice_assessments_are_schema_and_semantic_valid(self):
        for name in EXAMPLES:
            with self.subTest(name=name):
                record = self.sample(name)
                self.assertTrue(record["synthetic"])
                self.assert_contract_valid(record)

    def test_forcing_only_g0b_abstains_from_water_recovery_and_mobility(self):
        record = self.sample()
        self.assertEqual("unknown", record["environmental_condition"]["status"])
        self.assertIn("HYDRAULIC_CLOSURE_UNAVAILABLE", record["environmental_condition"]["reason_codes"])
        self.assertEqual("unavailable", record["mobility"]["kind"])
        self.assertEqual("unknown", record["recovery"]["status"])

    def test_assessment_provenance_has_release_and_run_but_not_manifest_digest(self):
        record = self.sample("exact-g1")
        provenance = record["provenance"]
        self.assertIn("release_id", provenance)
        self.assertIn("run_id", provenance)
        self.assertIn("input_digest", provenance)
        self.assertNotIn("immutable_manifest_ref", provenance)

    def test_partial_distribution_conserves_declared_weight_mass(self):
        record = self.sample("partial-loss")
        record["recovery"]["known_weight_mass"] = 0.5
        self.assert_invalid(record, "known and lost weight masses must sum to one")

    def test_partial_horizon_bounds_identify_exactly_the_missing_mass(self):
        record = self.sample("partial-loss")
        record["recovery"]["bounds_by_horizon"] = {"lower": 0.6, "upper": 0.9}
        self.assert_invalid(record, "horizon bound width must equal lost weight mass")

    def test_partial_distribution_has_explicit_time_bounds_and_no_exact_outputs(self):
        record = self.sample("partial-loss")
        recovery = record["recovery"]
        self.assertEqual("partially_identified", recovery["distribution_kind"])
        self.assertTrue(recovery["cdf_bounds"])
        self.assertIsNone(recovery["probability_by_horizon"])
        self.assertEqual([], recovery["cdf"])
        self.assertEqual({"p10": None, "p50": None, "p90": None}, recovery["quantiles"])

    def test_environment_state_cannot_conflict_with_its_availability(self):
        record = self.sample()
        record["environmental_condition"]["status"] = "available"
        self.assert_invalid(record, "available environment requires condition, policy and physical series")
        record = self.sample()
        record["environmental_condition"]["condition"] = "adverse"
        self.assert_invalid(record, "unknown environment must have null condition")

    def test_schema_rejects_unknown_reason_token(self):
        record = self.sample()
        record["environmental_condition"]["reason_codes"] = ["NOT_A_REASON"]
        self.assert_invalid(record, "NOT_A_REASON")

    def test_datetime_format_checker_is_enabled(self):
        self.assertIn("date-time", FormatChecker().checkers)
        record = self.sample()
        record["context"]["computed_at"] = "not-a-dateZ"
        self.assert_invalid(record, "is not a 'date-time'")

    def test_time_contract_uses_computed_at_and_forecast_issue_time(self):
        record = self.sample("exact-g1")
        self.assertIn("computed_at", record["context"])
        self.assertIsNotNone(record["context"]["forecast_issue_time"])
        record["context"]["knowledge_cutoff"] = "2027-03-14T07:00:00Z"
        self.assert_invalid(record, "knowledge_cutoff must not follow computed_at")
        record = self.sample("exact-g1")
        record["context"]["forecast_issue_time"] = "2027-03-14T07:00:00Z"
        self.assert_invalid(record, "forecast_issue_time must not follow knowledge_cutoff")

    def test_source_support_requires_transform_geometry_depth_and_estimate_kind(self):
        record = self.sample("exact-g1")
        del record["source_supports"][0]["transform_ref"]
        self.assert_invalid(record, "transform_ref")
        record = self.sample("exact-g1")
        record["source_supports"][0]["quantity"] = "soil_moisture"
        record["source_supports"][0]["estimate_kind"] = "static_property"
        self.assert_invalid(record, "static source support cannot publish soil_moisture")

    def test_partial_bounds_require_all_components_and_are_monotonic(self):
        record = self.sample("partial-loss")
        del record["recovery"]["bounds_by_horizon"]
        self.assert_invalid(record, "bounds_by_horizon")
        record = self.sample("partial-loss")
        record["recovery"]["cdf_bounds"][0]["lower"] = 0.7
        self.assert_invalid(record, "CDF bound lower must be nondecreasing")

    def test_exact_distribution_requires_complete_known_mass_and_grid_quantiles(self):
        record = self.sample("exact-g1")
        record["recovery"]["lost_weight_mass"] = 0.1
        self.assert_invalid(record, "known and lost weight masses must sum to one")
        record = self.sample("exact-g1")
        record["recovery"]["quantiles"]["p10"] = "2027-03-19T06:00:00Z"
        self.assert_invalid(record, "p10 must equal the first CDF crossing")

    def test_already_recovered_requires_a_confirmation_basis(self):
        record = self.sample("exact-g1")
        recovery = record["recovery"]
        recovery["status"] = "already_recovered"
        recovery["probability_by_horizon"] = 1.0
        recovery["cdf"] = [{"time": recovery["reference_time"], "probability": 1.0}]
        recovery["quantiles"] = {k: recovery["reference_time"] for k in ("p10", "p50", "p90")}
        self.assert_invalid(record, "already_recovered requires confirmation basis and evidence")
        recovery["confirmation_basis"] = "model_history"
        recovery["confirmation_evidence_refs"] = ["artifact:eligible-model-history"]
        self.assert_contract_valid(record)

    def test_recovery_status_matrix_rejects_numeric_unknown_and_right_censored_cdf(self):
        record = self.sample()
        record["recovery"]["probability_by_horizon"] = 0.2
        self.assert_invalid(record, "unknown or unsupported recovery cannot publish numeric outputs")
        record = self.sample("exact-g1")
        record["recovery"]["status"] = "right_censored"
        self.assert_invalid(record, "right_censored recovery must have zero CDF")

    def test_forecast_distribution_cannot_be_unavailable_or_publish_unknown_bounds(self):
        record = self.sample()
        record["recovery"]["status"] = "forecast_distribution"
        self.assert_invalid(record, "forecast_distribution cannot have unavailable distribution_kind")
        record = self.sample()
        record["recovery"]["cdf_bounds"] = [{"time": "2027-03-18T06:00:00Z", "lower": 0.1, "upper": 0.2}]
        self.assert_invalid(record, "unknown or unsupported recovery cannot publish numeric outputs")

    def test_traction_loss_is_a_named_mobility_outcome(self):
        record = self.sample("synthetic-g2")
        record["mobility"]["outcome"] = "traction_loss"
        self.assert_contract_valid(record)

    def test_quantitative_mobility_requires_estimand_operation_and_traction_loss(self):
        record = self.sample("synthetic-g2")
        for field in ("estimand", "operation_ref", "configuration_aggregation", "traction_loss"):
            invalid = copy.deepcopy(record)
            del invalid["mobility"][field]
            self.assert_invalid(invalid, field)

    def test_quantitative_mobility_requires_validated_domain_and_complete_variant(self):
        record = self.sample("synthetic-g2")
        record["assessment_level"] = "screening"
        self.assert_invalid(record, "quantitative mobility requires validated_domain")
        record = self.sample("synthetic-g2")
        record["mobility"]["risk"] = None
        self.assert_invalid(record, "calibrated_probability requires point risk")
        record = self.sample("synthetic-g2")
        record["mobility"]["configuration_aggregation"] = {}
        self.assert_invalid(record, "configuration aggregation requires kind and policy_ref")
        record = self.sample()
        record["mobility"]["probability_bounds"] = {"lower": 0.1, "upper": 0.2}
        self.assert_invalid(record, "unavailable mobility cannot publish probability bounds")

    def test_probability_bounds_requires_bounds_and_forbids_point_risk(self):
        record = self.sample("synthetic-g2")
        record["mobility"]["kind"] = "probability_bounds"
        record["mobility"]["risk"] = 0.4
        record["mobility"]["probability_bounds"] = None
        self.assert_invalid(record, "probability_bounds")

    def test_manifest_view_has_no_internal_locator_and_envelope_carries_manifest_digest(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        manifest_view = schema["$defs"]["ManifestView"]
        self.assertNotIn("internal_locator", manifest_view["properties"])
        manifest = schema["$defs"]["ResultManifest"]
        self.assertEqual("RFC8785-JCS", manifest["properties"]["canonicalization"]["const"])
        self.assertEqual("SHA-256-UTF8", manifest["properties"]["digest_algorithm"]["const"])
        self.assertNotIn("manifest_digest", manifest["properties"])
        envelope = {
            "served_at": "2027-03-14T06:00:00Z", "policy_revision": "policy-v1",
            "authz_revision": "authz-v1", "publication_manifest_digest": "sha256:" + "0" * 64,
            "payload": {"artifact_ref": "artifact:opaque-1"},
        }
        envelope_schema = {"$ref": "#/$defs/ServingEnvelope", "$defs": schema["$defs"]}
        errors = list(Draft202012Validator(envelope_schema, format_checker=FormatChecker()).iter_errors(envelope))
        self.assertEqual([], errors, [e.message for e in errors])

    def test_synthetic_production_record_is_rejected(self):
        record = self.sample("synthetic-g2")
        record["production_mode"] = True
        self.assert_invalid(record, "synthetic records are forbidden in production_mode")

    def test_nonfinite_numbers_are_not_valid_json_contract_values(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            record = self.sample()
            record["context"]["gross_mass_t"] = value
            self.assert_invalid(record, "non-finite JSON number")

    def test_invalid_shapes_return_errors_instead_of_crashing(self):
        for value in (None, [], {"context": None}, {"recovery": {"cdf": [None]}}):
            with self.subTest(value=value):
                self.assertTrue(validate_document(value))


if __name__ == "__main__":
    unittest.main()
