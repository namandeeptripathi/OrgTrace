"""Tests for Stage 19: Production & Execution Hardening.

Covers:
- CompetitionExecutionGuard (2,000 requests, $10 cost, 45m time limit, reduced mode, thread safety)
- Failure classification across all 9 standardized categories
- Explicit unavailable source representations (available, unavailable, timeout, rate_limited, not_found, parse_failed, not_attempted)
- Batch isolation under simulated failures (timeouts, network drops, malformed data)
- Clean environment assertion (no hardcoded developer paths in src/ or scripts/)
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from norway_company_agent.batch import (
    TERMINAL_STATES,
    evidence_terminal_state,
    profiles_from_bulk,
    terminal_envelope,
    validate_envelopes,
)
from norway_company_agent.evidence import evidence
from norway_company_agent.http import FetchResult, fetch_json
from norway_company_agent.official import _classified, fetch_official_modules
from norway_company_agent.resilience import (
    CompetitionExecutionGuard,
    FailureCategory,
    MalformedResponseError,
    NonRetryableHttpError,
    RateLimitExceededError,
    UpstreamTimeoutError,
    classify_failure,
)
from norway_company_agent.website import fetch_website


class CompetitionExecutionGuardTests(unittest.TestCase):
    """Tests for the centralized competition execution guard."""

    def test_request_budget_enforcement(self):
        guard = CompetitionExecutionGuard(max_requests=5, max_cost=10.0, max_runtime_seconds=60.0)
        for i in range(5):
            allowed, reason = guard.acquire_request()
            self.assertTrue(allowed, f"Request {i+1} should be permitted")
            self.assertIsNone(reason)

        self.assertEqual(guard.requests_used, 5)
        self.assertEqual(guard.remaining_requests, 0)

        # 6th request must be denied
        allowed, reason = guard.acquire_request()
        self.assertFalse(allowed)
        self.assertEqual(reason, "request_budget_exhausted")
        self.assertEqual(guard.failures_by_category[FailureCategory.BUDGET], 1)

        # Verify formatting
        card = guard.format_request_budget()
        self.assertIn("Limit:         5", card)
        self.assertIn("Used:          5", card)
        self.assertIn("Remaining:     0", card)

    def test_cost_budget_enforcement(self):
        guard = CompetitionExecutionGuard(max_requests=100, max_cost=1.00, max_runtime_seconds=60.0)

        allowed, _ = guard.acquire_request(cost=0.40)
        self.assertTrue(allowed)
        allowed, _ = guard.acquire_request(cost=0.50)
        self.assertTrue(allowed)

        self.assertAlmostEqual(guard.cost_incurred, 0.90)
        self.assertAlmostEqual(guard.remaining_cost, 0.10)

        # Next request with cost 0.20 exceeds $1.00 ceiling
        allowed, reason = guard.acquire_request(cost=0.20)
        self.assertFalse(allowed)
        self.assertEqual(reason, "cost_budget_exhausted")

        card = guard.format_cost_budget()
        self.assertIn("Limit:     $  1.00", card)
        self.assertIn("Used:      $  0.90", card)
        self.assertIn("Remaining: $  0.10", card)

    def test_runtime_budget_and_reduced_mode(self):
        guard = CompetitionExecutionGuard(
            max_requests=100,
            max_cost=10.0,
            max_runtime_seconds=0.25,
            reduced_mode_threshold_seconds=0.08,
            reduced_mode_remaining_requests=10,
        )

        self.assertFalse(guard.is_reduced_mode())
        time.sleep(0.12)
        # Now exceeded reduced mode threshold
        self.assertTrue(guard.is_reduced_mode())
        # First log check returns True, second returns False
        self.assertTrue(guard.should_log_reduced_mode_entry())
        self.assertFalse(guard.should_log_reduced_mode_entry())

        time.sleep(0.15)
        # Now exceeded max_runtime_seconds
        allowed, reason = guard.acquire_request()
        self.assertFalse(allowed)
        self.assertEqual(reason, "time_budget_exhausted")

    def test_format_batch_summary_output(self):
        guard = CompetitionExecutionGuard(max_requests=2000)
        guard.requests_used = 1548
        summary = guard.format_batch_summary(attempted=1000, successful=941, partial=42, failed=17)

        self.assertIn("Batch completed", summary)
        self.assertIn("Profiles attempted:    1000", summary)
        self.assertIn("Successful:              941", summary)
        self.assertIn("Partial:                  42", summary)
        self.assertIn("Failed:                   17", summary)
        self.assertIn("External requests:     1548 / 2000", summary)

    def test_concurrent_thread_safety(self):
        guard = CompetitionExecutionGuard(max_requests=150, max_cost=10.0, max_runtime_seconds=30.0)

        def worker():
            for _ in range(20):
                allowed, _ = guard.acquire_request()
                if not allowed:
                    break

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(guard.requests_used, 150)
        self.assertEqual(guard.remaining_requests, 0)


class FailureClassificationTests(unittest.TestCase):
    """Tests for standardized failure categorization."""

    def test_classify_failure_categories(self):
        # Network
        self.assertEqual(classify_failure(urllib.error.URLError("Connection reset")), FailureCategory.NETWORK)
        self.assertEqual(classify_failure(ConnectionResetError()), FailureCategory.NETWORK)
        self.assertEqual(classify_failure(None, status_code=502), FailureCategory.NETWORK)

        # Timeout
        self.assertEqual(classify_failure(TimeoutError("timed out")), FailureCategory.TIMEOUT)
        self.assertEqual(classify_failure(socket.timeout()), FailureCategory.TIMEOUT)
        self.assertEqual(classify_failure(UpstreamTimeoutError("timed out")), FailureCategory.TIMEOUT)
        self.assertEqual(classify_failure(urllib.error.URLError("timed out")), FailureCategory.TIMEOUT)

        # Rate Limit
        self.assertEqual(classify_failure(RateLimitExceededError("429")), FailureCategory.RATE_LIMIT)
        self.assertEqual(classify_failure(None, status_code=429), FailureCategory.RATE_LIMIT)

        # Auth
        self.assertEqual(classify_failure(NonRetryableHttpError(401, "unauthorized")), FailureCategory.AUTH)
        self.assertEqual(classify_failure(None, status_code=403), FailureCategory.AUTH)

        # Not Found
        self.assertEqual(classify_failure(None, status_code=404), FailureCategory.NOT_FOUND)
        self.assertEqual(classify_failure("404 Not Found"), FailureCategory.NOT_FOUND)

        # Parse
        self.assertEqual(classify_failure(MalformedResponseError("corrupt")), FailureCategory.PARSE)
        self.assertEqual(classify_failure(json.JSONDecodeError("msg", "doc", 0)), FailureCategory.PARSE)

        # Budget
        self.assertEqual(classify_failure("request_budget_exhausted"), FailureCategory.BUDGET)
        self.assertEqual(classify_failure("time_budget_exhausted"), FailureCategory.BUDGET)

        # Configuration
        self.assertEqual(classify_failure("missing environment variable BRAVE_API_KEY"), FailureCategory.CONFIGURATION)

        # Unknown
        self.assertEqual(classify_failure(ValueError("unexpected value")), FailureCategory.UNKNOWN)
        self.assertEqual(classify_failure(None), FailureCategory.UNKNOWN)


class UnavailableSourceRepresentationTests(unittest.TestCase):
    """Tests that unavailable sources are explicitly and accurately represented."""

    def test_classified_status_mapping(self):
        # 200 OK -> available
        res_ok = FetchResult("http://example.no", 200, 50, 100, body={"name": "Test AS"})
        ev_ok = _classified("test_field", "test_source", res_ok)
        self.assertEqual(ev_ok["status"], "available")
        self.assertEqual(evidence_terminal_state(ev_ok), "complete")

        # 404 Not Found -> not_found
        res_404 = FetchResult("http://example.no", 404, 50, 0, error="HTTP 404")
        ev_404 = _classified("test_field", "test_source", res_404)
        self.assertEqual(ev_404["status"], "not_found")
        self.assertEqual(evidence_terminal_state(ev_404), "not_found")

        # 429 Rate Limit -> rate_limited
        res_429 = FetchResult("http://example.no", 429, 50, 0, error="HTTP 429")
        ev_429 = _classified("test_field", "test_source", res_429)
        self.assertEqual(ev_429["status"], "rate_limited")
        self.assertEqual(evidence_terminal_state(ev_429), "rate_limited")

        # Timeout -> timeout
        res_to = FetchResult("http://example.no", 0, 15000, 0, error="Operation timed out")
        ev_to = _classified("test_field", "test_source", res_to)
        self.assertEqual(ev_to["status"], "timeout")
        self.assertEqual(evidence_terminal_state(ev_to), "timeout")

        # Budget Exhausted -> not_attempted
        res_bg = FetchResult("http://example.no", 0, 0, 0, error="Execution budget exhausted: request_budget_exhausted")
        ev_bg = _classified("test_field", "test_source", res_bg)
        self.assertEqual(ev_bg["status"], "not_attempted")
        self.assertEqual(evidence_terminal_state(ev_bg), "not_attempted")

        # Parse Failed -> parse_failed
        res_pf = FetchResult("http://example.no", 200, 50, 20, error="JSONDecodeError: Expecting value")
        ev_pf = _classified("test_field", "test_source", res_pf)
        self.assertEqual(ev_pf["status"], "parse_failed")
        self.assertEqual(evidence_terminal_state(ev_pf), "parse_failed")

        # Unhandled network failure -> unavailable
        res_un = FetchResult("http://example.no", 500, 50, 0, error="HTTP 500")
        ev_un = _classified("test_field", "test_source", res_un)
        self.assertEqual(ev_un["status"], "unavailable")
        self.assertEqual(evidence_terminal_state(ev_un), "unavailable")

    def test_all_terminal_states_valid(self):
        for state in ["complete", "not_applicable", "not_found", "timeout", "rate_limited", "parse_failed", "not_attempted", "unavailable", "source_error"]:
            self.assertIn(state, TERMINAL_STATES)


class BatchIsolationTests(unittest.TestCase):
    """Tests that failures in one company never terminate the batch or corrupt valid companies."""

    def test_batch_isolation_with_heterogeneous_outcomes(self):
        companies = [
            {"organisation_number": "985589003", "name": "ARKITEKTFIRMA JON VIKØREN AS"},
            {"organisation_number": "935095190", "name": "FJELLGLØD HOLDING AS"},
            {"organisation_number": "997830792", "name": "BEAUMONT HOLDING AS"},
            {"organisation_number": "916340257", "name": "WYSSEN NORGE AS"},
        ]

        def mock_enrich(profile: dict, simulate_failure: str | None = None) -> dict:
            org = profile["organisation_number"]
            profile["evidence"] = {
                "registry": evidence("registry", "available", "mock", f"http://brreg/{org}"),
            }
            if simulate_failure == "timeout":
                profile["evidence"]["website"] = evidence("website", "timeout", "mock", "http://timeout.no")
            elif simulate_failure == "parse_error":
                profile["evidence"]["website"] = evidence("website", "parse_failed", "mock", "http://corrupt.no")
            elif simulate_failure == "fatal_error":
                profile.setdefault("errors", []).append({"error": "Worker crash", "category": "NETWORK"})
                profile["run_metrics"] = {"status": "failed", "requests": 0}
                return profile
            else:
                profile["evidence"]["website"] = evidence("website", "available", "mock", "http://valid.no")

            profile["run_metrics"] = {"status": "complete", "requests": 2}
            return profile

        # Company 0: Success
        p0 = mock_enrich(dict(companies[0]))
        # Company 1: Timeout on website
        p1 = mock_enrich(dict(companies[1]), simulate_failure="timeout")
        # Company 2: Parse error
        p2 = mock_enrich(dict(companies[2]), simulate_failure="parse_error")
        # Company 3: Worker error
        p3 = mock_enrich(dict(companies[3]), simulate_failure="fatal_error")

        all_profiles = [p0, p1, p2, p3]

        envelopes = [
            terminal_envelope(p, run_id="test-run", modules=["registry", "website"], started_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T00:00:10Z")
            for p in all_profiles
        ]

        # All 4 envelopes must be produced
        self.assertEqual(len(envelopes), 4)

        # Company 0 has complete state
        self.assertEqual(envelopes[0]["state"], "complete")
        self.assertEqual(envelopes[0]["modules"]["website"]["state"], "complete")

        # Company 1 has timeout state on website, but entity still terminal
        self.assertEqual(envelopes[1]["modules"]["website"]["state"], "timeout")

        # Company 2 has parse_failed state on website
        self.assertEqual(envelopes[2]["modules"]["website"]["state"], "parse_failed")

        # Validate envelopes passes
        validation = validate_envelopes(envelopes, expected_count=4)
        self.assertTrue(validation["passed"])


class CleanEnvironmentVerificationTests(unittest.TestCase):
    """Verifies that no developer-specific or absolute machine paths exist in repository code."""

    def test_no_hardcoded_developer_paths_in_code(self):
        root = Path(__file__).resolve().parents[1]
        code_dirs = [root / "src", root / "scripts"]

        violations = []
        forbidden_patterns = ["/Users/", "/home/", "file:///Users/"]

        for d in code_dirs:
            for py_file in d.rglob("*.py"):
                text = py_file.read_text(encoding="utf-8")
                for pattern in forbidden_patterns:
                    if pattern in text:
                        violations.append(f"{py_file.relative_to(root)}: contains '{pattern}'")

        self.assertEqual(violations, [], f"Hardcoded developer paths found in code: {violations}")


if __name__ == "__main__":
    unittest.main()
