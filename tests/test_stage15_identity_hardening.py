"""Stage 15: Identity & Evidence Hardening Tests.

Tests all 33 required verification scenarios:
1-5: Organisation number matching (exact, formatting, mismatch, missing source, missing target)
6-10: Company name matching (case, legal suffix, unicode, similar-but-different, clearly different)
11-15: Domain matching (exact, www normalization, subdomains, unrelated, lookalike)
16-20: Source validation (official registry, official website, third-party, wrong-company, ambiguous)
21-25: Financial safeguards (correct entity/year/metric, wrong org, group vs subsidiary, conflict, missing currency/unit)
26-29: Contradictions (registry vs third-party, website vs registry, financial conflict, unresolvable)
30-33: Final fact gate (verified accepted, supported accepted, uncertain marked, rejected excluded)
"""

from __future__ import annotations

import unittest

from norway_company_agent.identity_hardening import (
    ContradictionRecord,
    DomainEntityValidation,
    DomainValidationStatus,
    EvidenceValidationStatus,
    FactAcceptanceDecision,
    FactAcceptanceVerdict,
    FinancialValidationResult,
    IdentityValidation,
    NameComparisonResult,
    NameMatchStatus,
    OrgNumberComparison,
    SourceAuthority,
    SourceIdentity,
    canonicalize_domain_hostname,
    compare_company_names,
    compare_org_numbers,
    detect_and_resolve_contradiction,
    evaluate_fact_acceptance,
    robust_normalize_company_name,
    validate_domain_entity,
    validate_financial_fact,
    validate_source_identity,
)


class TestStage15IdentityHardening(unittest.TestCase):

    # ========================================================================
    # 1. ORGANISATION NUMBER TESTS (1 - 5)
    # ========================================================================

    def test_01_org_number_exact_match(self):
        """1. Exact match between requested and source organisation number."""
        res = compare_org_numbers("923609016", "923609016")
        self.assertTrue(res.is_match)
        self.assertFalse(res.is_conflict)
        self.assertEqual(res.status, "match")
        self.assertEqual(res.confidence, "verified")
        self.assertEqual(res.requested_org, "923609016")
        self.assertEqual(res.source_org, "923609016")

    def test_02_org_number_formatting_differences(self):
        """2. Formatting differences: prefix NO, whitespace, dots, and MVA suffix."""
        res = compare_org_numbers("NO 923 609 016 MVA", "923.609.016")
        self.assertTrue(res.is_match)
        self.assertFalse(res.is_conflict)
        self.assertEqual(res.requested_org, "923609016")
        self.assertEqual(res.source_org, "923609016")
        self.assertEqual(res.confidence, "verified")

    def test_03_org_number_mismatch(self):
        """3. Mismatch between two valid organisation numbers triggers definitive rejection."""
        res = compare_org_numbers("923609016", "912345678")
        self.assertFalse(res.is_match)
        self.assertTrue(res.is_conflict)
        self.assertEqual(res.status, "mismatch")
        self.assertEqual(res.confidence, "rejected")
        self.assertIn("target 923609016 != source 912345678", res.reason)

    def test_04_org_number_missing_source(self):
        """4. Source organisation number is missing or unparseable."""
        res = compare_org_numbers("923609016", None)
        self.assertFalse(res.is_match)
        self.assertFalse(res.is_conflict)
        self.assertEqual(res.status, "missing_source")
        self.assertEqual(res.confidence, "uncertain")
        self.assertIsNone(res.source_org)

    def test_05_org_number_missing_target(self):
        """5. Target organisation number is missing or invalid."""
        res = compare_org_numbers(None, "923609016")
        self.assertFalse(res.is_match)
        self.assertFalse(res.is_conflict)
        self.assertEqual(res.status, "missing_target")
        self.assertEqual(res.confidence, "uncertain")
        self.assertIsNone(res.requested_org)

    # ========================================================================
    # 2. COMPANY NAME TESTS (6 - 10)
    # ========================================================================

    def test_06_company_name_case_differences(self):
        """6. Case differences: 'Equinor ASA' vs 'EQUINOR ASA' match exactly normalized."""
        res = compare_company_names("Equinor ASA", "EQUINOR ASA")
        self.assertTrue(res.normalized_name_match)
        self.assertEqual(res.name_match_status, NameMatchStatus.NORMALIZED_EXACT)
        self.assertTrue(res.is_acceptable_match)
        self.assertEqual(res.fuzzy_name_similarity, 1.0)

    def test_07_company_name_legal_suffix_differences(self):
        """7. Legal suffix differences: 'Nordic Tech AS' vs 'Nordic Tech A/S' vs omitted."""
        res_var = compare_company_names("Nordic Tech AS", "Nordic Tech A/S")
        self.assertTrue(res_var.is_acceptable_match)
        self.assertEqual(res_var.name_match_status, NameMatchStatus.NORMALIZED_EXACT)

        res_omit = compare_company_names("Nordic Tech AS", "Nordic Tech")
        self.assertTrue(res_omit.is_acceptable_match)
        self.assertEqual(res_omit.name_match_status, NameMatchStatus.LEGAL_SUFFIX_OMITTED)

        # Conflict: AS vs ENK
        res_conflict = compare_company_names("Nordic Tech AS", "Nordic Tech ENK")
        self.assertFalse(res_conflict.is_acceptable_match)
        self.assertEqual(res_conflict.name_match_status, NameMatchStatus.LEGAL_FORM_CONFLICT)

    def test_08_company_name_unicode_normalization(self):
        """8. Unicode normalization: 'Blåbær & Grøt AS' vs 'Blaabaer og Grot AS'."""
        res = compare_company_names("Blåbær & Grøt AS", "Blaabaer og Grot AS")
        self.assertTrue(res.is_acceptable_match)
        self.assertTrue(res.normalized_name_match)

    def test_09_company_name_similar_but_different_company(self):
        """9. Similar but different company: 'Nordic Logistics AS' vs 'Nordic Logistics Group AS'."""
        res = compare_company_names("Nordic Logistics AS", "Nordic Logistics Group AS")
        self.assertFalse(res.is_acceptable_match)
        self.assertEqual(res.name_match_status, NameMatchStatus.PARTIAL_OVERLAP)
        self.assertIn("Entity scope modifier conflict", res.reasons[0])

    def test_10_company_name_clearly_different_company(self):
        """10. Clearly different company names share no distinctive tokens."""
        res = compare_company_names("Kongsberg Gruppen ASA", "Telenor ASA")
        self.assertFalse(res.is_acceptable_match)
        self.assertEqual(res.name_match_status, NameMatchStatus.CONFLICTING)
        self.assertLess(res.fuzzy_name_similarity, 0.5)

    # ========================================================================
    # 3. DOMAIN TESTS (11 - 15)
    # ========================================================================

    def test_11_domain_exact_match(self):
        """11. Exact registered domain match against BRREG website."""
        target = {"website": "https://equinor.com", "name": "Equinor ASA", "organisation_number": "923609016"}
        res = validate_domain_entity(target, "https://equinor.com")
        self.assertEqual(res.status, DomainValidationStatus.VERIFIED)
        self.assertTrue(res.is_publishable)

    def test_12_domain_www_normalization(self):
        """12. www normalization: 'https://www.equinor.com/about' vs 'equinor.com'."""
        host = canonicalize_domain_hostname("https://www.equinor.com/about?lang=no#top")
        self.assertEqual(host, "equinor.com")
        target = {"website": "https://equinor.com", "name": "Equinor ASA"}
        res = validate_domain_entity(target, "http://www.equinor.com/")
        self.assertEqual(res.status, DomainValidationStatus.VERIFIED)
        self.assertTrue(res.is_publishable)

    def test_13_domain_subdomain_handling(self):
        """13. Subdomain handling: 'careers.equinor.com' correctly recognized as strongly supported."""
        target = {"website": "https://equinor.com", "name": "Equinor ASA"}
        res = validate_domain_entity(target, "https://careers.equinor.com")
        self.assertEqual(res.status, DomainValidationStatus.STRONGLY_SUPPORTED)
        self.assertTrue(res.is_publishable)

    def test_14_domain_unrelated_domain(self):
        """14. Unrelated domain without name or org evidence is rejected."""
        target = {"website": "https://equinor.com", "name": "Equinor ASA", "organisation_number": "923609016"}
        res = validate_domain_entity(target, "https://unrelated-domain.no")
        self.assertEqual(res.status, DomainValidationStatus.REJECTED)
        self.assertFalse(res.is_publishable)

    def test_15_domain_lookalike_or_parked_domain(self):
        """15. Lookalike / parked placeholder domain is rejected."""
        target = {"website": "https://equinor.com", "name": "Equinor ASA"}
        res = validate_domain_entity(
            target,
            "https://equinor-holding.com",
            page_text="This domain is for sale! Hugedomains has been informing visitors.",
        )
        self.assertEqual(res.status, DomainValidationStatus.REJECTED)
        self.assertFalse(res.is_publishable)
        self.assertIn("parked or for-sale placeholder", res.reasons[0])

    # ========================================================================
    # 4. SOURCE VALIDATION TESTS (16 - 20)
    # ========================================================================

    def test_16_source_validation_official_registry(self):
        """16. Official registry source with exact org number is unconditionally verified."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        source = SourceIdentity(
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
            source_type="official_registry",
            organisation_number="923609016",
            company_name="NORSK FISKEEKSPORT AS",
        )
        verdict = validate_source_identity(target, source)
        self.assertEqual(verdict.status, EvidenceValidationStatus.VERIFIED)
        self.assertTrue(verdict.organisation_number_match)
        self.assertEqual(verdict.confidence, 1.0)

    def test_17_source_validation_official_company_website(self):
        """17. Official company website matching registered domain with legal name."""
        target = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "website": "https://norskfiske.no",
        }
        source = SourceIdentity(
            source_url="https://norskfiske.no/kontakt",
            source_type="company_website",
            company_name="Norsk Fiskeeksport AS",
            raw_evidence_snippet="Velkommen til Norsk Fiskeeksport AS. Org.nr. 923 609 016.",
        )
        verdict = validate_source_identity(target, source)
        self.assertEqual(verdict.status, EvidenceValidationStatus.VERIFIED)
        self.assertTrue(verdict.domain_match)
        self.assertGreaterEqual(verdict.confidence, 0.95)

    def test_18_source_validation_third_party_directory(self):
        """18. Third-party directory source with verified org number is verified, but supported without org."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        # With org number
        source_with_org = SourceIdentity(
            source_url="https://proff.no/selskap/norsk-fiskeeksport-as/923609016",
            source_type="secondary_directory",
            organisation_number="923609016",
            company_name="Norsk Fiskeeksport AS",
        )
        v1 = validate_source_identity(target, source_with_org)
        self.assertEqual(v1.status, EvidenceValidationStatus.VERIFIED)

        # Without org number
        source_no_org = SourceIdentity(
            source_url="https://proff.no/selskap/norsk-fiskeeksport-as",
            source_type="secondary_directory",
            company_name="Norsk Fiskeeksport AS",
        )
        v2 = validate_source_identity(target, source_no_org)
        self.assertEqual(v2.status, EvidenceValidationStatus.UNCERTAIN)

    def test_19_source_validation_wrong_company_source(self):
        """19. Source explicitly belonging to another organisation number is definitively rejected."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        wrong_source = SourceIdentity(
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter/987654321",
            source_type="official_registry",
            organisation_number="987654321",
            company_name="Annet Selskap AS",
        )
        verdict = validate_source_identity(target, wrong_source)
        self.assertEqual(verdict.status, EvidenceValidationStatus.REJECTED)
        self.assertEqual(verdict.rejection_reason, "organisation_number_mismatch")
        self.assertEqual(verdict.confidence, 0.0)

    def test_20_source_validation_ambiguous_source(self):
        """20. Ambiguous source lacking organisation number and domain grounding is marked uncertain."""
        target = {"organisation_number": "923609016", "name": "Nordic Tech AS"}
        ambig_source = SourceIdentity(
            source_url="https://industry-blog.com/nordic-tech-article",
            source_type="news",
            company_name="Nordic Tech",
            raw_evidence_snippet="Nordic Tech reported growing revenues this quarter.",
        )
        verdict = validate_source_identity(target, ambig_source)
        self.assertEqual(verdict.status, EvidenceValidationStatus.UNCERTAIN)
        self.assertEqual(verdict.rejection_reason, "insufficient_identity_evidence")

    # ========================================================================
    # 5. FINANCIAL SAFEGUARDS (21 - 25)
    # ========================================================================

    def test_21_financials_correct_entity_year_metric(self):
        """21. Valid financial fact with correct org, metric, year, and currency."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        res = validate_financial_fact(
            target,
            metric_name="revenue",
            amount=50000000,
            currency="NOK",
            reporting_year=2024,
            account_type="SELSKAP",
            source_org="923609016",
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(res.status, EvidenceValidationStatus.VERIFIED)
        self.assertEqual(res.amount, 50000000)
        self.assertEqual(res.currency, "NOK")

    def test_22_financials_wrong_organisation_number(self):
        """22. Financial statement belonging to another organisation is strictly rejected."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        res = validate_financial_fact(
            target,
            metric_name="revenue",
            amount=120000000,
            currency="NOK",
            reporting_year=2024,
            source_org="999888777",
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, EvidenceValidationStatus.REJECTED)
        self.assertEqual(res.rejection_reason, "organisation_number_mismatch")

    def test_23_financials_group_vs_subsidiary(self):
        """23. Consolidated group accounts (KONSERN) cannot substitute standalone accounts."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "is_in_group": True}
        res = validate_financial_fact(
            target,
            metric_name="revenue",
            amount=250000000,
            currency="NOK",
            reporting_year=2024,
            account_type="KONSERN",
            source_org="923609016",
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, EvidenceValidationStatus.UNCERTAIN)
        self.assertEqual(res.rejection_reason, "consolidated_group_scope")

    def test_24_financials_boundary_checked_org_in_text(self):
        """24. PDF text with concatenated digits across lines does not falsely validate."""
        target = {"organisation_number": "985589003", "name": "Target AS"}
        # Page 1 ends in 985, page 2 starts with 589003 -> concatenated: 985589003
        leaky_text = "Account balance: 1985\nInvoice id: 589003"
        res = validate_financial_fact(
            target,
            metric_name="revenue",
            amount=10000000,
            document_text=leaky_text,
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, EvidenceValidationStatus.REJECTED)
        self.assertEqual(res.rejection_reason, "organisation_number_not_in_filing")

        # Proper formatted text matches cleanly
        valid_text = "Årsregnskap 2024 for Target AS, org.nr. 985 589 003"
        res_valid = validate_financial_fact(
            target,
            metric_name="revenue",
            amount=10000000,
            document_text=valid_text,
        )
        self.assertTrue(res_valid.is_valid)
        self.assertEqual(res_valid.status, EvidenceValidationStatus.VERIFIED)

    def test_25_financials_missing_currency_or_unit(self):
        """25. Missing or invalid currency/unit marks the financial value uncertain."""
        target = {"organisation_number": "923609016", "name": "Target AS"}
        res = validate_financial_fact(
            target,
            metric_name="revenue",
            amount=15000000,
            currency="XYZ_INVALID",
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, EvidenceValidationStatus.UNCERTAIN)
        self.assertEqual(res.rejection_reason, "unsupported_currency")

    # ========================================================================
    # 6. CONTRADICTIONS (26 - 29)
    # ========================================================================

    def test_26_contradiction_registry_vs_third_party(self):
        """26. Official registry takes precedence over third-party directory."""
        rec_reg = {
            "value": "Oslo",
            "source_url": "https://data.brreg.no/api",
            "source_priority": SourceAuthority.OFFICIAL_REGISTRY.value,
        }
        rec_third = {
            "value": "Bergen",
            "source_url": "https://directory.no/company",
            "source_priority": SourceAuthority.REPUTABLE_SECONDARY.value,
        }
        conflict = detect_and_resolve_contradiction("municipality", rec_reg, rec_third)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.resolution_status, "resolved")
        self.assertEqual(conflict.preferred_value, "Oslo")
        self.assertEqual(conflict.preferred_source_url, "https://data.brreg.no/api")

    def test_27_contradiction_website_vs_registry(self):
        """27. Official registry filing takes precedence over website text."""
        rec_reg = {
            "value": "Dronning Eufemias gate 10",
            "source_url": "https://data.brreg.no/api",
            "source_priority": SourceAuthority.OFFICIAL_REGISTRY.value,
        }
        rec_web = {
            "value": "Storgata 1",
            "source_url": "https://company.no/contact",
            "source_priority": SourceAuthority.FIRST_PARTY_WEBSITE.value,
        }
        conflict = detect_and_resolve_contradiction("address", rec_web, rec_reg)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.resolution_status, "resolved")
        self.assertEqual(conflict.preferred_value, "Dronning Eufemias gate 10")

    def test_28_contradiction_financial_values(self):
        """28. Official Regnskapsregisteret filing overrides secondary estimate."""
        rec_filing = {
            "value": 45000000,
            "source_url": "https://data.brreg.no/regnskap",
            "source_priority": SourceAuthority.OFFICIAL_FILING.value,
        }
        rec_blog = {
            "value": 60000000,
            "source_url": "https://industry-news.com/post",
            "source_priority": SourceAuthority.REPUTABLE_SECONDARY.value,
        }
        conflict = detect_and_resolve_contradiction("revenue", rec_filing, rec_blog)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.resolution_status, "resolved")
        self.assertEqual(conflict.preferred_value, 45000000)

    def test_29_contradiction_unresolvable(self):
        """29. Equal authority sources with conflicting values are marked uncertain."""
        rec_1 = {
            "value": "+47 22 00 00 01",
            "source_url": "https://company.no/contact-oslo",
            "source_priority": SourceAuthority.FIRST_PARTY_WEBSITE.value,
        }
        rec_2 = {
            "value": "+47 22 00 00 02",
            "source_url": "https://company.no/contact-bergen",
            "source_priority": SourceAuthority.FIRST_PARTY_WEBSITE.value,
        }
        conflict = detect_and_resolve_contradiction("phone", rec_1, rec_2)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.resolution_status, "uncertain")
        self.assertIsNone(conflict.preferred_value)
        self.assertIn("Contradictory values from equally authoritative sources", conflict.reason)

    # ========================================================================
    # 7. FINAL FACT ACCEPTANCE GATE (30 - 33)
    # ========================================================================

    def test_30_fact_gate_verified_accepted(self):
        """30. Verified fact from official registry is accepted into trusted profile."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        source = {
            "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
            "source_type": "official_registry",
            "organisation_number": "923609016",
            "company_name": "Norsk Fiskeeksport AS",
        }
        verdict = evaluate_fact_acceptance(target, "legal_name", "Norsk Fiskeeksport AS", source)
        self.assertEqual(verdict.decision, FactAcceptanceDecision.ACCEPT)
        self.assertEqual(verdict.validation_status, EvidenceValidationStatus.VERIFIED)
        self.assertEqual(verdict.confidence, 1.0)
        self.assertEqual(verdict.value, "Norsk Fiskeeksport AS")

    def test_31_fact_gate_supported_accepted(self):
        """31. Supported fact from corroborated website is accepted with supported status."""
        target = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "website": None,  # Not registered in BRREG, but corroborated on web
        }
        source = {
            "source_url": "https://norskfiske.no",
            "source_type": "company_website",
            "company_name": "Norsk Fiskeeksport AS",
            "raw_evidence_snippet": "Vi leverer fersk sjømat til hele Europa fra vårt anlegg i Bergen. Norsk Fiskeeksport AS kvalitet.",
        }
        verdict = evaluate_fact_acceptance(target, "products_services", ["Fersk sjømat"], source)
        self.assertEqual(verdict.decision, FactAcceptanceDecision.ACCEPT)
        self.assertEqual(verdict.validation_status, EvidenceValidationStatus.SUPPORTED)
        self.assertEqual(verdict.value, ["Fersk sjømat"])


    def test_32_fact_gate_uncertain_marked(self):
        """32. Fact with incomplete identity grounding is marked uncertain."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        source = {
            "source_url": "https://blog.com/fish",
            "source_type": "news",
            "company_name": "Norsk Fiskeeksport",
        }
        verdict = evaluate_fact_acceptance(target, "revenue", 50000000, source)
        self.assertEqual(verdict.decision, FactAcceptanceDecision.UNCERTAIN)
        self.assertEqual(verdict.validation_status, EvidenceValidationStatus.UNCERTAIN)
        self.assertEqual(verdict.value, 50000000)

    def test_33_fact_gate_rejected_excluded(self):
        """33. Fact from conflicting organisation number is rejected and excluded."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        wrong_source = {
            "source_url": "https://data.brreg.no/api/987654321",
            "source_type": "official_registry",
            "organisation_number": "987654321",
            "company_name": "Wrong Company AS",
        }
        verdict = evaluate_fact_acceptance(target, "revenue", 99999999, wrong_source)
        self.assertEqual(verdict.decision, FactAcceptanceDecision.REJECT)
        self.assertEqual(verdict.validation_status, EvidenceValidationStatus.REJECTED)
        self.assertIsNone(verdict.value)
        self.assertEqual(verdict.rejection_reason, "organisation_number_mismatch")


if __name__ == "__main__":
    unittest.main()
