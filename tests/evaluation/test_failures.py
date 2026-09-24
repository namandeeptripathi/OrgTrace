"""Tests for Stage 18 Failure Classification and Resilience."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.failures import (
    classify_company_outcome,
    compute_failure_rates,
)
from norway_company_agent.evaluation.models import (
    CompanyEvaluationResultState,
    IdentityStatus,
)


class TestFailureEvaluation(unittest.TestCase):
    """Verify outcome states, error isolation, and aggregate rate calculations."""

    def test_classify_success(self):
        state, failure = classify_company_outcome(
            identity_status=IdentityStatus.EXACT_MATCH,
            coverage_rate=0.85,
            evidence_validity_rate=0.90,
        )
        self.assertEqual(state, CompanyEvaluationResultState.SUCCESS.value)
        self.assertIsNone(failure)

    def test_classify_partial_success(self):
        state, failure = classify_company_outcome(
            identity_status=IdentityStatus.EXACT_MATCH,
            coverage_rate=0.45,  # Low coverage
            evidence_validity_rate=0.50,
        )
        self.assertEqual(state, CompanyEvaluationResultState.PARTIAL_SUCCESS.value)
        self.assertIsNone(failure)

    def test_classify_timeout(self):
        state, failure = classify_company_outcome(
            identity_status=IdentityStatus.NOT_FOUND,
            coverage_rate=0.0,
            evidence_validity_rate=0.0,
            timed_out=True,
            stage="website_discovery",
        )
        self.assertEqual(state, CompanyEvaluationResultState.TIMEOUT.value)
        self.assertIsNotNone(failure)
        self.assertEqual(failure["type"], "timeout")
        self.assertEqual(failure["stage"], "website_discovery")

    def test_classify_identity_failure(self):
        state, failure = classify_company_outcome(
            identity_status=IdentityStatus.WRONG_COMPANY,
            coverage_rate=0.80,
            evidence_validity_rate=0.80,
        )
        self.assertEqual(state, CompanyEvaluationResultState.IDENTITY_FAILURE.value)
        self.assertIsNotNone(failure)
        self.assertEqual(failure["type"], "wrong_company")

    def test_compute_failure_rates(self):
        records = [
            {"result": "success"},
            {"result": "success"},
            {"result": "partial_success"},
            {"result": "timeout"},
            {"result": "failed"},
        ]
        rates = compute_failure_rates(records)
        self.assertEqual(rates["success_rate"], 0.40)
        self.assertEqual(rates["partial_success_rate"], 0.20)
        self.assertEqual(rates["timeout_rate"], 0.20)
        self.assertEqual(rates["failure_rate"], 0.20)


if __name__ == "__main__":
    unittest.main()
