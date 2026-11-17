"""Planning arithmetic is explicit and G0b is a subset, not an add-on."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlanningEstimatesTests(unittest.TestCase):
    def test_g0b_is_itemized_subset_of_g1(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/planning_estimates.py')],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout)
        self.assertIn('G0b_work_package_subset', data)
        parts = data['G0b_work_package_subset']
        self.assertEqual(set(parts), {'WP-00', 'WP-01', 'WP-02', 'WP-03', 'WP-05', 'WP-06', 'WP-10'})
        expected = [sum(v[i] for v in parts.values()) for i in (0, 1)]
        self.assertEqual(data['G0b_person_days'], expected)
        self.assertLess(expected[0], data['G1_person_days_low'])
        self.assertLess(expected[1], data['G1_person_days_high'])
        self.assertEqual(data['G0b_development_cost_USD'], [expected[0] * 150, expected[1] * 350])
        self.assertFalse(data['G0b_additive_to_G1'])
        self.assertEqual(data['G0b_scientific_output'], 'forcing_only_water_and_recovery_abstain')
        self.assertNotIn('WP-04', parts)
        self.assertNotIn('WP-08', parts)


if __name__ == '__main__':
    unittest.main()
