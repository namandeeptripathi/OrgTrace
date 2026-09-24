"""Tests for Stage 18 13-Category Coverage Evaluation."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.coverage import COVERAGE_SCHEMA, evaluate_company_coverage


class TestCoverageEvaluation(unittest.TestCase):
    """Verify coverage category breakdowns, missing fields tracking, and status handling."""

    def test_complete_company_profile_coverage(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "legal_form": "ASA",
            "status": "active",
            "description": "Energy company",
            "registration_date": "1972-09-18",
            "municipality": "Stavanger",
            "address": "Forusbeen 50",
            "email": "post@equinor.com",
            "phone": "+4751990000",
            "contact_url": "https://www.equinor.com/contact",
            "website": "https://www.equinor.com",
            "financials": {
                "revenue": 1000000000.0,
                "profit_loss": 200000000.0,
                "assets": 5000000000.0,
                "equity": 2500000000.0,
                "financial_year": "2024",
            },
            "industry_code": "06.100",
            "industry_label": "Extraction of crude petroleum",
            "roles": [{"name": "Anders Opedal", "role": "CEO"}],
            "group": {"parent": "Staten"},
            "locations": [{"name": "Stavanger Hovedkontor"}],
            "social_presence": [{"platform": "linkedin", "url": "https://linkedin.com/company/equinor"}],
            "news": [{"title": "Q3 Results Published"}],
            "change_intelligence": {"changes": []},
            "evidence": {"registry": {"status": "available"}},
            "explanations": [{"field_name": "identity", "summary": "Verified"}],
        }
        res = evaluate_company_coverage(profile)
        self.assertGreater(res.rate, 0.90)
        self.assertGreater(res.field_coverage_rate, 0.90)
        self.assertGreater(res.category_coverage_rate, 0.90)
        self.assertEqual(len(res.invalid_fields), 0)

    def test_minimal_company_profile_missing_fields_preserved(self):
        profile = {
            "organisation_number": "935095190",
            "name": "Fjellglød Holding AS",
            "legal_form": "AS",
            "status": "active",
        }
        res = evaluate_company_coverage(profile)
        self.assertGreater(res.rate, 0.0)
        self.assertLess(res.rate, 0.50)
        self.assertIn("website.website_url", res.missing_fields)
        self.assertIn("financial.revenue", res.missing_fields)

    def test_invalid_field_detection(self):
        profile = {
            "organisation_number": "123",  # Invalid (not 9 digits)
            "website": "not a valid url",   # Invalid
        }
        res = evaluate_company_coverage(profile)
        self.assertGreaterEqual(res.invalid_fields_count, 2)
        invalid_str = " ".join(res.invalid_fields)
        self.assertIn("organisation_number", invalid_str)
        self.assertIn("website_url", invalid_str)

    def test_empty_profile_returns_zero_coverage(self):
        res = evaluate_company_coverage(None)
        self.assertEqual(res.rate, 0.0)
        self.assertEqual(res.field_coverage_rate, 0.0)
        self.assertGreater(len(res.missing_fields), 20)


if __name__ == "__main__":
    unittest.main()
