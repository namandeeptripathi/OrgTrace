"""Tests for Stage 18 Evidence Validity and Provenance Evaluation."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.evidence import evaluate_company_evidence
from norway_company_agent.evaluation.models import ClaimEvidenceStatus


class TestEvidenceEvaluation(unittest.TestCase):
    """Verify claim evidence verification, URL syntax, and support classification."""

    def test_strong_evidence_supported(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Equinor ASA",
            "evidence": {
                "registry": {
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    "source_type": "official_registry_live",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "content_sha256": "abc123hash",
                    "status": "available",
                    "value": {"name": "Equinor ASA"},
                }
            }
        }
        res = evaluate_company_evidence(profile)
        self.assertGreaterEqual(res.validity_rate, 0.90)
        self.assertGreaterEqual(res.supported_claims, 1)
        self.assertEqual(res.unsupported_claims, 0)

    def test_url_syntax_invalid_is_unsupported(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {
                "registry": {
                    "source_url": "ftp://bad-scheme.com",  # Invalid scheme
                    "status": "available",
                }
            }
        }
        res = evaluate_company_evidence(profile)
        self.assertGreater(res.unsupported_claims, 0)

    def test_missing_evidence_classified_properly(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {},  # No evidence attached
        }
        res = evaluate_company_evidence(profile)
        self.assertGreater(res.missing_evidence_claims, 0)
        self.assertEqual(res.validity_rate, 0.0)

    def test_contradicted_evidence_status(self):
        profile = {
            "organisation_number": "923609016",
            "website": "https://fake.no",
            "evidence": {
                "website": {
                    "source_url": "https://fake.no",
                    "status": "not_found",  # Source not found, but profile claimed website
                    "retrieved_at": "2026-09-24T12:00:00Z",
                }
            }
        }
        res = evaluate_company_evidence(profile)
        self.assertGreaterEqual(res.contradicted_claims, 1)


if __name__ == "__main__":
    unittest.main()
