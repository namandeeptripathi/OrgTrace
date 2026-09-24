"""Tests for Stage 18 Request Telemetry and Domain Accounting."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.requests import (
    RequestTracker,
    classify_request_domain,
)


class TestRequestEvaluation(unittest.TestCase):
    """Verify request classification, domain accounting, failure and retry tracking."""

    def test_classify_request_domain(self):
        self.assertEqual(classify_request_domain("data.brreg.no"), "registry")
        self.assertEqual(classify_request_domain("api.search.brave.com"), "search")
        self.assertEqual(classify_request_domain("proff.no"), "financial")
        self.assertEqual(classify_request_domain("linkedin.com"), "external_research")
        self.assertEqual(classify_request_domain("equinor.com"), "company_website")

    def test_request_tracker_aggregation(self):
        tracker = RequestTracker()
        tracker.record("https://data.brreg.no/enhetsregisteret/api/enheter/923609016", status_code=200)
        tracker.record("https://data.brreg.no/regnskapsregisteret/regnskap/923609016", status_code=200)
        tracker.record("https://www.equinor.com", status_code=200)
        tracker.record("https://broken.no", status_code=500, retries=2, error="Connection timeout")

        res = tracker.get_evaluation()
        self.assertEqual(res.total, 4)
        self.assertEqual(res.failed, 1)
        self.assertEqual(res.retries, 2)
        self.assertEqual(res.requests_by_domain.get("data.brreg.no"), 2)
        self.assertEqual(res.requests_by_domain.get("www.equinor.com"), 1)
        self.assertEqual(res.requests_by_domain.get("broken.no"), 1)
        self.assertEqual(res.requests_by_type.get("registry"), 2)


if __name__ == "__main__":
    unittest.main()
