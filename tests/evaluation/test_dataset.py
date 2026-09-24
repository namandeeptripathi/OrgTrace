"""Tests for Stage 18 Dataset Loading and Deterministic Selection."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from norway_company_agent.evaluation.dataset import (
    DEFAULT_DATASET_PATH,
    compute_dataset_hash,
    load_evaluation_dataset,
    parse_dataset_json,
    select_evaluation_cases,
)


class TestEvaluationDataset(unittest.TestCase):
    """Verify evaluation dataset integrity, sampling, and reproducibility."""

    def test_default_dataset_loads_successfully(self):
        cases, d_hash = load_evaluation_dataset()
        self.assertGreaterEqual(len(cases), 30)
        self.assertTrue(len(d_hash) > 0)

        # Check required fields
        for case in cases:
            self.assertTrue(case.case_id.startswith("eval-"))
            self.assertTrue(len(case.query) > 0)
            self.assertIn(case.category, {
                "known_valid", "rich_public_info", "limited_info", "incomplete_data",
                "similar_names", "difficult_website", "size_industry_diversity",
                "historical_change", "ambiguous", "non_target", "not_found", "general",
            })

    def test_deterministic_random_selection_with_seed(self):
        cases, _ = load_evaluation_dataset()

        # Same seed yields exact same selection
        sample_a = select_evaluation_cases(cases, count=10, seed=42)
        sample_b = select_evaluation_cases(cases, count=10, seed=42)
        self.assertEqual([c.case_id for c in sample_a], [c.case_id for c in sample_b])

        # Different seed yields different selection
        sample_c = select_evaluation_cases(cases, count=10, seed=99)
        self.assertNotEqual([c.case_id for c in sample_a], [c.case_id for c in sample_c])

    def test_no_duplicate_companies_in_sample(self):
        cases, _ = load_evaluation_dataset()
        sample = select_evaluation_cases(cases, count=25, seed=12345)
        case_ids = [c.case_id for c in sample]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_target_company_selection(self):
        cases, _ = load_evaluation_dataset()

        # By company name
        equinor = select_evaluation_cases(cases, target_company="Equinor ASA")
        self.assertEqual(len(equinor), 1)
        self.assertEqual(equinor[0].expected_org_number, "923609016")

        # By org number
        dnb = select_evaluation_cases(cases, target_company="984851006")
        self.assertEqual(len(dnb), 1)
        self.assertIn("DNB", dnb[0].expected_name)

        # Ad-hoc unknown target company
        custom = select_evaluation_cases(cases, target_company="Unknown Corp AS")
        self.assertEqual(len(custom), 1)
        self.assertEqual(custom[0].query, "Unknown Corp AS")

    def test_custom_dataset_loading_and_hashing(self):
        custom_data = [
            {"case_id": "test-1", "query": "Test 1 AS", "expected_org_number": "123456789"},
            {"case_id": "test-2", "query": "Test 2 AS", "expected_org_number": "987654321"},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(json.dumps(custom_data))
            f_path = f.name

        try:
            cases, h1 = load_evaluation_dataset(f_path)
            self.assertEqual(len(cases), 2)
            self.assertEqual(cases[0].case_id, "test-1")
            self.assertEqual(cases[1].case_id, "test-2")

            # Same data yields same hash
            _, h2 = load_evaluation_dataset(f_path)
            self.assertEqual(h1, h2)
        finally:
            Path(f_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
