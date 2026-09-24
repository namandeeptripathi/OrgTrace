"""Tests for Pre-Frontend Cleanup:
- Authoritative external request budget metrics (request_limit, actual_external_requests, request_budget_remaining, request_budget_consumed_percent)
- Clear distinction between tracked_requests (internal reservations) and actual_external_requests (wire HTTP requests)
- Frontend-ready profile status computation without state conflation
- Evidence field preservation (status, value, source_url, retrieved_at, note)
- Change intelligence baseline observation semantics
"""

from __future__ import annotations

import unittest
from norway_company_agent.batch import (
    compute_profile_status,
    terminal_envelope,
    validate_envelopes,
    TERMINAL_STATES,
)
from norway_company_agent.evidence import evidence
from norway_company_agent.resilience import CompetitionExecutionGuard


class RequestBudgetTerminologyTests(unittest.TestCase):
    """Verifies that the authoritative competition request budget metrics match Stage 20 specifications."""

    def test_actual_external_requests_budget_metrics(self):
        guard = CompetitionExecutionGuard(max_requests=2000)
        # Simulate 1310 internally tracked permits
        for _ in range(1310):
            allowed, _ = guard.acquire_request()
            self.assertTrue(allowed)

        # Wire HTTP requests totaled 1618
        guard.record_actual_external_requests(1618)

        self.assertEqual(guard.tracked_requests, 1310)
        self.assertEqual(guard.actual_external_requests, 1618)
        self.assertEqual(guard.remaining_requests, 382)

        data = guard.to_dict()
        self.assertEqual(data["request_limit"], 2000)
        self.assertEqual(data["actual_external_requests"], 1618)
        self.assertEqual(data["tracked_requests"], 1310)
        self.assertEqual(data["requests_used"], 1618)
        self.assertEqual(data["remaining_requests"], 382)
        self.assertEqual(data["request_budget_remaining"], 382)
        self.assertEqual(data["request_budget_consumed_percent"], 80.9)

        # Verify summary card formatting
        card = guard.format_request_budget()
        self.assertIn("Limit:      2000", card)
        self.assertIn("Used:       1618", card)
        self.assertIn("Remaining:   382", card)

        batch_card = guard.format_batch_summary(attempted=1000, successful=93, partial=907, failed=0)
        self.assertIn("External requests:     1618 / 2000", batch_card)

    def test_backwards_compatibility_when_actual_requests_not_set(self):
        guard = CompetitionExecutionGuard(max_requests=2000)
        for _ in range(50):
            guard.acquire_request()

        self.assertIsNone(guard.actual_external_requests)
        self.assertEqual(guard.tracked_requests, 50)
        self.assertEqual(guard.remaining_requests, 1950)

        data = guard.to_dict()
        self.assertEqual(data["requests_used"], 50)
        self.assertEqual(data["tracked_requests"], 50)
        self.assertEqual(data["remaining_requests"], 1950)
        self.assertEqual(data["request_budget_remaining"], 1950)
        self.assertEqual(data["request_budget_consumed_percent"], 2.5)


class ProfileStatusFrontendReadinessTests(unittest.TestCase):
    """Verifies that profile status clearly distinguishes actual states without conflation."""

    def test_complete_profile_status(self):
        profile = {
            "organisation_number": "123456789",
            "evidence": {
                "registry": evidence("registry", "available", "source_a", "https://example.com/a"),
                "accounting_obligation": evidence("accounting_obligation", "available", "source_b", "https://example.com/b"),
                "website": evidence("website", "available", "source_c", "https://example.com/c"),
                "financials": evidence("financials", "available", "source_d", "https://example.com/d"),
            },
        }
        self.assertEqual(compute_profile_status(profile), "complete")

    def test_partial_profile_status_with_missing_website(self):
        profile = {
            "organisation_number": "123456789",
            "evidence": {
                "registry": evidence("registry", "available", "source_a", "https://example.com/a"),
                "accounting_obligation": evidence("accounting_obligation", "available", "source_b", "https://example.com/b"),
                "website": evidence("website", "not_found", "source_c", "https://example.com/c", note="No valid registry website URL"),
                "financials": evidence("financials", "available", "source_d", "https://example.com/d"),
            },
        }
        self.assertEqual(compute_profile_status(profile), "partial")

    def test_partial_profile_status_with_blocked_website(self):
        profile = {
            "organisation_number": "123456789",
            "evidence": {
                "registry": evidence("registry", "available", "source_a", "https://example.com/a"),
                "accounting_obligation": evidence("accounting_obligation", "available", "source_b", "https://example.com/b"),
                "website": evidence("website", "blocked", "source_c", "https://example.com/c", note="robots.txt disallows this user agent"),
                "financials": evidence("financials", "available", "source_d", "https://example.com/d"),
            },
        }
        # Partial must NOT be collapsed to failed or not_found
        self.assertEqual(compute_profile_status(profile), "partial")
        # And the website itself retains blocked status and note
        self.assertEqual(profile["evidence"]["website"]["status"], "blocked")
        self.assertEqual(profile["evidence"]["website"]["note"], "robots.txt disallows this user agent")

    def test_partial_profile_status_with_timeout_website(self):
        profile = {
            "organisation_number": "123456789",
            "evidence": {
                "registry": evidence("registry", "available", "source_a", "https://example.com/a"),
                "accounting_obligation": evidence("accounting_obligation", "available", "source_b", "https://example.com/b"),
                "website": evidence("website", "timeout", "source_c", "https://example.com/c", note="URLError: timed out"),
                "financials": evidence("financials", "available", "source_d", "https://example.com/d"),
            },
        }
        self.assertEqual(compute_profile_status(profile), "partial")
        self.assertEqual(profile["evidence"]["website"]["status"], "timeout")

    def test_failed_profile_status(self):
        profile = {
            "organisation_number": "123456789",
            "run_metrics": {"status": "failed"},
            "evidence": {},
        }
        self.assertEqual(compute_profile_status(profile), "failed")


class EnvelopeContractAndEvidenceIntegrityTests(unittest.TestCase):
    """Verifies that terminal envelopes preserve evidence attributes and validate cleanly."""

    def test_terminal_envelope_preserves_status_and_evidence(self):
        profile = {
            "organisation_number": "985589003",
            "name": "ARKITEKTFIRMA JON VIKØREN AS",
            "evidence": {
                "registry": evidence("registry", "available", "bulk", "https://data.brreg.no", value={"raw": 1}),
                "website": evidence("website", "not_found", "registry", "https://data.brreg.no", note="No valid registry website URL"),
            },
        }
        env = terminal_envelope(
            profile,
            run_id="run-01",
            modules=["registry", "website"],
            started_at="2026-09-24T14:00:00Z",
            completed_at="2026-09-24T14:00:05Z",
        )

        self.assertEqual(env["state"], "complete")
        self.assertEqual(env["status"], "partial")
        self.assertEqual(env["profile"]["status"], "partial")

        # Check evidence fields are completely intact
        web_ev = env["profile"]["evidence"]["website"]
        self.assertEqual(web_ev["status"], "not_found")
        self.assertEqual(web_ev["source_url"], "https://data.brreg.no")
        self.assertIsNotNone(web_ev["retrieved_at"])
        self.assertEqual(web_ev["note"], "No valid registry website URL")

        # Verify envelope passes validation
        res = validate_envelopes([env], 1)
        self.assertTrue(res["passed"])


if __name__ == "__main__":
    unittest.main()
