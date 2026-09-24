"""Stage 17: Evidence-Grounded Explanations Tests.

Validates:
1. Strong evidence: Multiple authoritative sources (BRREG + official website) produce grounded explanations with HIGH confidence.
2. Single reliable source: Produces explanation with MEDIUM confidence.
3. No evidence: Explains insufficiency explicitly without guessing (UNKNOWN confidence).
4. Conflicting evidence: Explicitly acknowledges contradictions without silently overriding (LOW confidence).
5. Hallucinated entity rejection: LLM introducing a foreign company entity is rejected by validator and falls back to deterministic.
6. Hallucinated number rejection: Numbers not in supplied facts are rejected.
7. Invalid evidence ID rejection: Non-existent evidence references fail validation and trigger fallback.
8. LLM failure resilience: Timeouts, exceptions, and malformed JSON automatically invoke deterministic fallback.
9. Change explanation: Integrates with Stage 16 change intelligence.
10. Batch resilience: Multi-company processing isolates failures.
11. CLI formatting: format_explanation_cli generates human-readable text.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.explanations import (
    CompanyExplanationReport,
    EvidenceTier,
    Explanation,
    ExplanationConfidence,
    ExplanationContext,
    ExplanationEvidenceRef,
    classify_evidence_tier,
    explain_company_profile,
    format_explanation_cli,
    generate_deterministic_explanation,
    generate_explanation,
    validate_explanation,
)


class Stage17ExplanationsTests(unittest.TestCase):
    """Test suite for evidence-grounded explanations."""

    def setUp(self):
        self.org = "923609016"
        self.name = "Equinor Energy AS"
        self.base_profile = {
            "organisation_number": self.org,
            "name": self.name,
            "status": "ACTIVE",
            "legal_form": "AS",
            "industry_code": "06.100",
            "industry_label": "Utvinning av råolje",
            "website": "https://www.equinor.com",
            "address": {
                "street": "Forusbeen 50",
                "postal_code": "4035",
                "city": "STAVANGER",
                "country": "Norway",
            },
            "employees": 1000,
            "financials": {
                "2024": {
                    "period": "2024",
                    "revenue": 50000000000,
                    "profit": 10000000000,
                }
            },
            "evidence": {
                "registry": {
                    "source_url": f"https://data.brreg.no/enhetsregisteret/api/enheter/{self.org}",
                    "source_class": "official_registry",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "status": "available",
                    "claim_span": "Equinor Energy AS, org 923 609 016, active",
                },
                "website": {
                    "source_url": "https://www.equinor.com",
                    "source_class": "company_website",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "status": "available",
                    "value": {
                        "final_url": "https://www.equinor.com",
                        "description": "Energy company exploring oil, gas and renewables.",
                    },
                },
                "financials": {
                    "source_url": f"https://data.brreg.no/regnskapsregisteret/api/regnskap/{self.org}",
                    "source_class": "regnskapsregisteret",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "status": "available",
                },
            },
        }

    # Test 1: Strong evidence -> Grounded explanation with HIGH confidence
    def test_01_strong_evidence_produces_high_confidence_explanation(self):
        report = explain_company_profile(self.base_profile)
        self.assertEqual(report.organisation_number, self.org)
        self.assertEqual(report.company_name, self.name)

        # Status explanation backed by BRREG
        status_exp = report.explanations["status"]
        self.assertEqual(status_exp.confidence, ExplanationConfidence.HIGH)
        self.assertIn("active in Norway", status_exp.summary)
        self.assertTrue(len(status_exp.supporting_evidence) >= 1)
        self.assertEqual(status_exp.supporting_evidence[0].source_name, "BRREG_ENHETSREGISTERET")

        # Industry explanation backed by BRREG + Website
        ind_exp = report.explanations["industry"]
        self.assertEqual(ind_exp.confidence, ExplanationConfidence.HIGH)
        self.assertIn("06.100", ind_exp.summary)
        self.assertIn("corroborated", ind_exp.summary)

    # Test 2: Single reliable source -> Appropriate confidence (MEDIUM)
    def test_02_single_reliable_source_produces_medium_confidence(self):
        profile = dict(self.base_profile)
        # Remove website corroboration
        profile["evidence"] = {
            "registry": self.base_profile["evidence"]["registry"]
        }
        report = explain_company_profile(profile)
        ind_exp = report.explanations["industry"]
        self.assertEqual(ind_exp.confidence, ExplanationConfidence.MEDIUM)
        self.assertIn("06.100", ind_exp.summary)

    # Test 3: No evidence -> Insufficient evidence explanation (UNKNOWN confidence)
    def test_03_no_evidence_explains_insufficiency_explicitly(self):
        empty_profile = {
            "organisation_number": "999999999",
            "name": "Ghost AS",
            "evidence": {},
        }
        report = explain_company_profile(empty_profile)

        # Status
        status_exp = report.explanations["status"]
        self.assertEqual(status_exp.confidence, ExplanationConfidence.UNKNOWN)
        self.assertIn("Insufficient evidence", status_exp.summary)
        self.assertEqual(len(status_exp.supporting_evidence), 0)
        self.assertTrue(len(status_exp.missing_evidence) >= 1)

        # Website
        web_exp = report.explanations["website"]
        self.assertEqual(web_exp.confidence, ExplanationConfidence.UNKNOWN)
        self.assertIn("No verified corporate website", web_exp.summary)

    # Test 4: Conflicting evidence -> Conflict acknowledged (LOW confidence)
    def test_04_conflicting_evidence_acknowledged_without_override(self):
        conflict_profile = dict(self.base_profile)
        conflict_profile["conflicts"] = [
            {"field": "status", "source_a": "ACTIVE", "source_b": "BANKRUPT"}
        ]
        report = explain_company_profile(conflict_profile)
        status_exp = report.explanations["status"]
        self.assertEqual(status_exp.confidence, ExplanationConfidence.LOW)
        self.assertIn("conflicting information", status_exp.summary.lower())
        self.assertTrue(len(status_exp.conflicts) >= 1)

    # Test 5: Hallucinated entity -> Rejected by validator -> Fallback
    def test_05_hallucinated_entity_rejected_by_validator(self):
        context = ExplanationContext(
            organisation_number=self.org,
            company_name=self.name,
            field_name="status",
            facts={"status": "ACTIVE"},
            evidence_items=[self.base_profile["evidence"]["registry"]],
            available_evidence_ids={"ev-registry"},
            allowed_source_names={"BRREG", "official_registry"},
            supplied_numbers={self.org},
            supplied_dates=set(),
        )

        # Simulated LLM hallucinating that Acme Corporation acquired the company
        def fake_hallucinating_llm(prompt: str) -> str:
            return (
                '{"summary": "The company was acquired by Acme Corporation and is active.", '
                '"reasoning": "Acme took over operations according to BRREG.", '
                '"confidence": "high", "evidence_ids": ["ev-registry"]}'
            )

        exp = generate_explanation("status", context, llm_callable=fake_hallucinating_llm)
        self.assertTrue(exp.is_fallback)
        self.assertFalse(exp.validation_passed)
        self.assertIn("Acme", str(exp.metadata.get("rejection_reasons")))
        # Fallback text must NOT contain the hallucinated entity
        self.assertNotIn("Acme", exp.summary)
        self.assertIn("active in Norway", exp.summary)

    # Test 6: Hallucinated number -> Rejected by validator -> Fallback
    def test_06_hallucinated_number_rejected_by_validator(self):
        context = ExplanationContext(
            organisation_number=self.org,
            company_name=self.name,
            field_name="workforce",
            facts={"employees": 42},
            evidence_items=[self.base_profile["evidence"]["registry"]],
            available_evidence_ids={"ev-registry"},
            allowed_source_names={"BRREG"},
            supplied_numbers={"42", self.org},
            supplied_dates=set(),
        )

        # Simulated LLM hallucinating 5000 employees instead of 42
        def fake_hallucinating_llm(prompt: str) -> str:
            return (
                '{"summary": "The company has 5000 employees.", '
                '"reasoning": "BRREG census lists 5000 workers.", '
                '"confidence": "high", "evidence_ids": ["ev-registry"]}'
            )

        exp = generate_explanation("workforce", context, llm_callable=fake_hallucinating_llm)
        self.assertTrue(exp.is_fallback)
        self.assertFalse(exp.validation_passed)
        self.assertIn("5000", str(exp.metadata.get("rejection_reasons")))
        # Fallback maintains true number 42
        self.assertIn("42", exp.summary)

    # Test 7: Invalid evidence ID -> Rejected by validator -> Fallback
    def test_07_invalid_evidence_id_rejected_by_validator(self):
        context = ExplanationContext(
            organisation_number=self.org,
            company_name=self.name,
            field_name="status",
            facts={"status": "ACTIVE"},
            evidence_items=[self.base_profile["evidence"]["registry"]],
            available_evidence_ids={"ev-registry"},
            allowed_source_names={"BRREG"},
            supplied_numbers={self.org},
            supplied_dates=set(),
        )

        # Simulated LLM referencing non-existent evidence-999
        def fake_hallucinating_llm(prompt: str) -> str:
            return (
                '{"summary": "Company is active.", '
                '"reasoning": "Verified by register.", '
                '"confidence": "high", "evidence_ids": ["evidence-999"]}'
            )

        exp = generate_explanation("status", context, llm_callable=fake_hallucinating_llm)
        self.assertTrue(exp.is_fallback)
        self.assertFalse(exp.validation_passed)
        self.assertIn("evidence-999", str(exp.metadata.get("rejection_reasons")))

    # Test 8: LLM failure (timeout / exception / malformed JSON) -> Automatic fallback
    def test_08_llm_failure_triggers_automatic_deterministic_fallback(self):
        context = ExplanationContext(
            organisation_number=self.org,
            company_name=self.name,
            field_name="status",
            facts={"status": "ACTIVE"},
            evidence_items=[self.base_profile["evidence"]["registry"]],
            available_evidence_ids={"ev-registry"},
            allowed_source_names={"BRREG"},
            supplied_numbers={self.org},
            supplied_dates=set(),
        )

        # Exception
        def broken_llm_exception(prompt: str) -> str:
            raise TimeoutError("API connection to LLM timed out after 30s")

        exp_timeout = generate_explanation("status", context, llm_callable=broken_llm_exception)
        self.assertTrue(exp_timeout.is_fallback)
        self.assertIn("active in Norway", exp_timeout.summary)
        self.assertIn("timed out", exp_timeout.metadata.get("llm_error", ""))

        # Malformed JSON
        def broken_llm_malformed(prompt: str) -> str:
            return "This is not JSON at all."

        exp_malformed = generate_explanation("status", context, llm_callable=broken_llm_malformed)
        self.assertTrue(exp_malformed.is_fallback)
        self.assertIn("active in Norway", exp_malformed.summary)

    # Test 9: Stage 16 change explanation integration
    def test_09_stage16_change_explanations(self):
        profile_with_changes = dict(self.base_profile)
        profile_with_changes["change_intelligence"] = {
            "status": "CHANGES_DETECTED",
            "previous_snapshot": "2025-01-01T00:00:00Z",
            "changes": [
                {
                    "field": "website",
                    "previous": "https://old-domain.no",
                    "current": "https://new-domain.no",
                    "material": True,
                    "explanation": "Company website changed from 'https://old-domain.no' to 'https://new-domain.no'",
                }
            ],
        }

        report = explain_company_profile(profile_with_changes)
        change_exp = report.explanations["company_changes"]
        self.assertEqual(change_exp.confidence, ExplanationConfidence.HIGH)
        self.assertIn("1 material change", change_exp.summary)
        self.assertIn("old-domain.no", change_exp.reasoning)
        self.assertIn("new-domain.no", change_exp.reasoning)

    # Test 10: Batch resilience over multiple profiles
    def test_10_batch_resilience_isolates_failures(self):
        p1 = dict(self.base_profile)
        p2 = {"organisation_number": "111222333", "name": None, "evidence": None}  # Incomplete
        p3 = {"organisation_number": "444555666", "name": "Third AS", "status": "DISSOLVED"}

        reports = [explain_company_profile(p) for p in (p1, p2, p3)]
        self.assertEqual(len(reports), 3)
        self.assertEqual(reports[0].overall_confidence, ExplanationConfidence.HIGH)
        self.assertEqual(reports[1].overall_confidence, ExplanationConfidence.LOW)
        self.assertEqual(reports[2].explanations["status"].summary, "The company is formally dissolved or struck off from the register.")

    # Test 11: CLI formatting
    def test_11_cli_formatting(self):
        report = explain_company_profile(self.base_profile)
        cli_text = format_explanation_cli(report)
        self.assertIn("EXPLANATIONS: 923609016 (Equinor Energy AS)", cli_text)
        self.assertIn("[STATUS]", cli_text)
        self.assertIn("[INDUSTRY]", cli_text)
        self.assertIn("Confidence: HIGH", cli_text)
        self.assertIn("BRREG_ENHETSREGISTERET", cli_text)


if __name__ == "__main__":
    unittest.main()
