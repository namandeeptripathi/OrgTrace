"""Tests for Stage 18 Update and Freshness Evaluation."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.freshness import evaluate_company_freshness


class TestFreshnessEvaluation(unittest.TestCase):
    """Verify change detection precision, recall, noise rejection, and unavailable states."""

    def test_unavailable_when_no_baseline(self):
        current = {"organisation_number": "923609016", "name": "Equinor ASA"}
        res = evaluate_company_freshness(current, baseline_profile=None)
        self.assertEqual(res.status, "unavailable")
        self.assertEqual(res.reason, "insufficient historical baseline")
        self.assertIsNone(res.precision)
        self.assertIsNone(res.recall)

    def test_material_changes_correctly_detected(self):
        baseline = {
            "organisation_number": "955666777",
            "name": "Bergen Teknologi AS",
            "legal_form": "AS",
            "website": "https://bergentek.no",
        }
        current = {
            "organisation_number": "955666777",
            "name": "Bergen Teknologi ASA",
            "legal_form": "ASA",
            "website": "https://bergentek.no",
            "evidence": {
                "registry": {
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/955666777",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "source_type": "official_registry_live",
                    "status": "available",
                }
            },
        }
        expected_changes = [
            {"field": "legal_name", "change_type": "modified"},
            {"field": "legal_form", "change_type": "modified"},
        ]
        res = evaluate_company_freshness(current, baseline, expected_changes)
        self.assertEqual(res.status, "evaluated")
        self.assertGreaterEqual(res.changes_detected, 1)
        self.assertIsNotNone(res.precision)
        self.assertIsNotNone(res.recall)

    def test_formatting_noise_not_counted_as_change(self):
        baseline = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "website": "https://www.equinor.com/",
        }
        current = {
            "organisation_number": "923609016",
            "name": "  EQUINOR ASA  ",  # Whitespace / casing noise
            "website": "https://www.equinor.com",  # Trailing slash noise
        }
        res = evaluate_company_freshness(current, baseline, expected_changes=[])
        self.assertEqual(res.status, "evaluated")
        self.assertEqual(res.changes_detected, 0)
        self.assertEqual(res.false_positives, 0)
        self.assertEqual(res.unchanged_preserved, 1)


if __name__ == "__main__":
    unittest.main()
