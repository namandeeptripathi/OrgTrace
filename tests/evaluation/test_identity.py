"""Tests for Stage 18 Identity Accuracy Evaluation."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.identity import evaluate_company_identity
from norway_company_agent.evaluation.models import IdentityStatus


class TestIdentityEvaluation(unittest.TestCase):
    """Verify exact, probable, ambiguous, wrong company, and not found classifications."""

    def test_exact_match(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "website": "https://www.equinor.com",
        }
        res = evaluate_company_identity(
            expected_org_number="923609016",
            expected_name="Equinor ASA",
            observed_profile=profile,
            expected_website="https://www.equinor.com",
        )
        self.assertEqual(res.status, IdentityStatus.EXACT_MATCH)
        self.assertEqual(res.accuracy, 1.0)
        self.assertTrue(res.name_match)
        self.assertTrue(res.website_match)

    def test_probable_match_minor_name_variation(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Equinor",  # Suffix omitted
            "website": "https://www.equinor.com",
        }
        res = evaluate_company_identity(
            expected_org_number="923609016",
            expected_name="Equinor ASA",
            observed_profile=profile,
        )
        self.assertEqual(res.status, IdentityStatus.EXACT_MATCH)
        self.assertEqual(res.accuracy, 1.0)

    def test_wrong_company_org_mismatch(self):
        profile = {
            "organisation_number": "987654321",  # Different org number
            "name": "Equinor ASA",
        }
        res = evaluate_company_identity(
            expected_org_number="923609016",
            expected_name="Equinor ASA",
            observed_profile=profile,
        )
        self.assertEqual(res.status, IdentityStatus.WRONG_COMPANY)
        self.assertEqual(res.accuracy, 0.0)

    def test_ambiguous_case_handled(self):
        profile = {
            "organisation_number": None,
            "name": "Norsk Fisk",
            "verdict_status": "ambiguous",
        }
        res = evaluate_company_identity(
            expected_org_number=None,
            expected_name=None,
            observed_profile=profile,
        )
        self.assertEqual(res.status, IdentityStatus.EXACT_MATCH)
        self.assertEqual(res.accuracy, 1.0)

    def test_not_found_on_empty_profile(self):
        res = evaluate_company_identity(
            expected_org_number="923609016",
            expected_name="Equinor ASA",
            observed_profile=None,
        )
        self.assertEqual(res.status, IdentityStatus.NOT_FOUND)
        self.assertEqual(res.accuracy, 0.0)


if __name__ == "__main__":
    unittest.main()
