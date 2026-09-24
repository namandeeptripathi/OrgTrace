"""Tests for Stage 18 Explanation Quality Evaluation."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.explanations import evaluate_company_explanations


class TestExplanationEvaluation(unittest.TestCase):
    """Verify explanation grounding, evidence referencing, and uncertainty handling."""

    def test_well_grounded_explanation_evaluation(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "explanations": [
                {
                    "field_name": "identity",
                    "summary": "Verified Norwegian entity Equinor ASA (org nr 923609016).",
                    "reasoning": "Matches official Brreg registration.",
                    "confidence": "high",
                    "supporting_evidence": [
                        {
                            "evidence_id": "ev-1",
                            "source_name": "Brreg Enhetsregisteret",
                            "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                        }
                    ],
                    "validation_passed": True,
                },
                {
                    "field_name": "financials",
                    "summary": "Financial revenue is missing for this entity.",
                    "reasoning": "No annual accounts submitted.",
                    "confidence": "low",
                    "uncertainty": "Statutory filing unavailable.",
                    "validation_passed": True,
                },
            ],
        }
        res = evaluate_company_explanations(profile)
        self.assertEqual(res.explanations_evaluated, 2)
        self.assertGreaterEqual(res.grounding_rate, 0.90)
        self.assertGreaterEqual(res.evidence_reference_rate, 0.50)
        self.assertGreaterEqual(res.uncertainty_handled, 1)
        self.assertEqual(res.unsupported_rate, 0.0)

    def test_hallucination_or_unsupported_number_detected(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "explanations": [
                {
                    "field_name": "identity",
                    "summary": "Entity reported revenue of 999999999 NOK.",  # Fabricated 9-digit number
                    "reasoning": "Unverified assertion.",
                    "validation_passed": False,
                }
            ],
        }
        res = evaluate_company_explanations(profile)
        self.assertGreater(res.unsupported_rate, 0.0)
        self.assertGreaterEqual(res.unsupported_statements_detected, 1)


if __name__ == "__main__":
    unittest.main()
