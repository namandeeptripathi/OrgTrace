"""Deterministic regression test suite for evaluator priorities.

Covers:
1. Registry-parent / brand / wrong-company website attribution.
2. Comparison of registry website with independent search candidates.
3. ATS and job validation (exact employer, vacancy path, vendor homepage rejection, parent vacancy rejection).
4. News validation (real article, genuine publication date vs modified/retrieval/future dates, parent/wrong-company rejection).
5. Strict separation of published facts, unsure facts, and rejected facts (no leakage).
6. Contract envelope integrity and non-leakage.
"""

import unittest
from datetime import datetime, timezone
from norway_company_agent.identity import assess_website_identity, apply_website_identity_gate
from norway_company_agent.discovery import compare_registry_and_search_candidates
from norway_company_agent.search_enrichment import _is_ats, _is_news_candidate, _parse_date, extract_search_enrichment
from norway_company_agent.website import extract_ats_links
from norway_company_agent.profile_extraction import extract_news
from norway_company_agent.coverage import (
    build_unified_company_profile,
    CoverageCategory,
    CoverageFieldStatus,
)
from norway_company_agent.evidence import evidence
from bs4 import BeautifulSoup


class WebsiteIdentityAttributionRegressionTests(unittest.TestCase):
    """Priority 1: Registry-parent / brand / wrong-company website attribution."""

    def test_conflicting_org_number_in_website_rejected(self):
        # Target subsidiary org number: 999888777 (Mod11 valid)
        # Website page contains conflicting valid Mod11 org number: 980 123 456
        profile = {
            "organisation_number": "999888777",
            "name": "Datterselskap AS",
            "evidence": {
                "website": {
                    "source_url": "https://datterselskap.no",
                    "value": {
                        "final_url": "https://datterselskap.no",
                        "title": "Datterselskap AS",
                        "main_text": "Velkommen til Datterselskap AS. Org.nr: 980 123 456 MVA.",
                    },
                }
            },
        }
        assessment = assess_website_identity(profile)
        self.assertFalse(assessment["publishable"])
        self.assertTrue(any("wrong_company_attribution" in r for r in assessment["reasons"]))
        self.assertEqual(assessment.get("conflicting_org_number"), "980123456")

    def test_parent_org_number_in_website_identified_as_parent_attribution(self):
        # Target has parent overordnetEnhet = "912345688" (Mod11 valid)
        profile = {
            "organisation_number": "999888777",
            "name": "Nordic Sub AS",
            "overordnetEnhet": "912345688",
            "evidence": {
                "website": {
                    "source_url": "https://nordicgroup.no",
                    "value": {
                        "final_url": "https://nordicgroup.no",
                        "title": "Nordic Group ASA",
                        "main_text": "Nordic Group ASA opererer i hele Norden. Org.nr: 912 345 688 MVA.",
                    },
                }
            },
        }
        assessment = assess_website_identity(profile)
        self.assertFalse(assessment["publishable"])
        self.assertTrue(any("parent_attribution" in r for r in assessment["reasons"]))
        self.assertEqual(assessment.get("parent_org_number"), "912345688")

    def test_aggregator_and_platform_root_hosts_rejected(self):
        for bad_url in [
            "https://purehelp.no/m/company/test-as",
            "https://proff.no/selskap/test-as/123",
            "https://wixsite.com",
            "https://wordpress.com",
            "https://shopify.com",
        ]:
            profile = {
                "organisation_number": "999888777",
                "name": "Test AS",
                "evidence": {
                    "website": {
                        "source_url": bad_url,
                        "value": {"final_url": bad_url, "title": "Test AS", "main_text": "Test AS"},
                    }
                },
            }
            assessment = assess_website_identity(profile)
            self.assertFalse(assessment["publishable"])
            self.assertTrue(any("aggregator" in r or "platform_root" in r for r in assessment["reasons"]))

    def test_apply_website_identity_gate_marks_unverified_as_not_found(self):
        profile = {
            "organisation_number": "999888777",
            "name": "Test AS",
        }
        website = evidence(
            "website",
            "available",
            "company_website",
            "https://wrong-company.no",
            value={
                "final_url": "https://wrong-company.no",
                "title": "Wrong Company AS",
                "main_text": "Helt annet innhold uten firmanavn",
            },
        )
        gate_res = apply_website_identity_gate(profile, website)
        web_ev = gate_res["website"]
        self.assertEqual(web_ev["status"], "not_found")
        self.assertTrue(web_ev.get("identity_rejected"))
        self.assertFalse(web_ev["identity_assessment"]["publishable"])


class RegistryVsSearchCandidateComparisonTests(unittest.TestCase):
    """Priority 2: Comparison of registry website with independent search candidates."""

    def test_registry_corroborated_by_search_candidate(self):
        profile = {"organisation_number": "999888777", "name": "Alpha AS"}
        registry_website = {
            "status": "available",
            "source_url": "https://alpha.no",
            "value": {
                "final_url": "https://alpha.no",
                "title": "Alpha AS",
                "main_text": "Velkommen til Alpha AS. Vi leverer sikre systemer og konsulenttjenester til bedrifter i hele Norge. Org.nr: 999 888 777 MVA.",
            },
        }
        search_candidates = [
            {"url": "https://alpha.no/om-oss", "title": "Alpha AS", "snippet": "Alpha AS org nr 999888777", "source": "brave"}
        ]
        outcome = compare_registry_and_search_candidates(profile, registry_website, search_candidates)
        self.assertEqual(outcome["verdict"], "corroborated")
        self.assertEqual(outcome["selected_url"], "https://alpha.no")

    def test_search_candidate_preferred_when_registry_rejected(self):
        profile = {"organisation_number": "999888777", "name": "Beta AS"}
        registry_website = {
            "status": "available",
            "source_url": "https://beta-parked.com",
            "value": {"final_url": "https://beta-parked.com", "title": "Domain for Sale", "main_text": "Buy this domain"},
        }
        search_candidates = [
            {"url": "https://beta.no", "title": "Beta AS", "snippet": "Velkommen til Beta AS org nr 999888777", "source": "duckduckgo"}
        ]
        outcome = compare_registry_and_search_candidates(profile, registry_website, search_candidates)
        self.assertEqual(outcome["verdict"], "search_candidate_preferred")
        self.assertEqual(outcome["selected_url"].rstrip("/"), "https://beta.no")

    def test_registry_rejected_no_search_candidate(self):
        profile = {"organisation_number": "999888777", "name": "Gamma AS"}
        registry_website = {
            "status": "available",
            "source_url": "https://hugedomains.com/gamma",
            "value": {"final_url": "https://hugedomains.com/gamma", "title": "Buy this domain", "main_text": "Buy this domain"},
        }
        outcome = compare_registry_and_search_candidates(profile, registry_website, [])
        self.assertEqual(outcome["verdict"], "registry_rejected_no_search_candidate")
        self.assertIsNone(outcome["selected_url"])


class ATSAndJobValidationRegressionTests(unittest.TestCase):
    """Priority 3: ATS and job validation (exact employer, vendor homepage rejection, parent vacancy rejection)."""

    def test_vendor_homepages_rejected_by_is_ats(self):
        vendor_homepages = [
            {"url": "https://teamtailor.com", "title": "Teamtailor ATS"},
            {"url": "https://www.teamtailor.com/en", "title": "Teamtailor ATS"},
            {"url": "https://bamboohr.com/jobs", "title": "BambooHR"},
            {"url": "https://recman.no", "title": "Recman Recruitment System"},
            {"url": "https://reachmee.com", "title": "ReachMee Talent Acquisition"},
            {"url": "https://jobbnorge.no", "title": "Jobbnorge Forside"},
            {"url": "https://finn.no/jobb", "title": "FINN jobb"},
        ]
        for res in vendor_homepages:
            _, is_ats = _is_ats(res)
            self.assertFalse(is_ats, f"Expected vendor homepage to be rejected: {res['url']}")

    def test_company_specific_tenant_and_vacancy_accepted_by_is_ats(self):
        valid_ats = [
            {"url": "https://acme.teamtailor.com", "title": "Acme Careers"},
            {"url": "https://acme.recman.no/job.php?job_id=123", "title": "Acme Vacancies"},
            {"url": "https://www.finn.no/jobb/stilling?id=12345678", "title": "Senior Utvikler hos Acme AS"},
            {"url": "https://www.finn.no/jobb/stilling/12345678", "title": "Senior Utvikler hos Acme AS"},
            {"url": "https://www.jobbnorge.no/ledige-stillinger/stilling/98765", "title": "Rådgiver hos Acme"},
        ]
        for res in valid_ats:
            _, is_ats = _is_ats(res)
            self.assertTrue(is_ats, f"Expected company specific ATS to be accepted: {res['url']}")

    def test_extract_ats_links_filters_out_vendor_homepages(self):
        html = """
        <html>
          <body>
            <a href="https://teamtailor.com">Vi bruker Teamtailor</a>
            <a href="https://finn.no/jobb">Finn jobb</a>
            <a href="https://jobbnorge.no">Ledige stillinger på Jobbnorge</a>
            <a href="https://nordic.teamtailor.com">Ledige stillinger hos oss</a>
            <a href="https://www.finn.no/jobb/stilling?id=999999">Søk stilling på FINN</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = extract_ats_links(soup, "https://nordic.no")
        urls = [item["url"] for item in links]
        self.assertNotIn("https://teamtailor.com", urls)
        self.assertNotIn("https://finn.no/jobb", urls)
        self.assertNotIn("https://jobbnorge.no", urls)
        self.assertIn("https://nordic.teamtailor.com", urls)
        self.assertIn("https://www.finn.no/jobb/stilling?id=999999", urls)

    def test_parent_job_vacancy_rejected_by_extract_search_enrichment(self):
        # Target subsidiary: Sub AS (org: 999888777, parent: Parent Corp / 912345688)
        profile = {
            "organisation_number": "999888777",
            "name": "Sub AS",
            "overordnetEnhet": "912345688",
        }
        search_results = [
            {
                "url": "https://parentcorp.teamtailor.com/jobs/555",
                "title": "Avdelingsleder hos Parent Corp ASA",
                "snippet": "Parent Corp ASA søker ny leder. Arbeidsgiver: Parent Corp ASA. Org.nr 912345688.",
            }
        ]
        enrichment = extract_search_enrichment(profile, search_results, retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["hiring"]), 0)
        self.assertTrue(len(enrichment["rejected_hiring"]) > 0)
        self.assertTrue(any("parent" in r["reason"].lower() for r in enrichment["rejected_hiring"]))


class NewsValidationRegressionTests(unittest.TestCase):
    """Priority 4: News validation (real article, genuine publication date vs modified/future/retrieval)."""

    def test_generic_news_hub_rejected_by_is_news_candidate(self):
        generic_hubs = [
            {"url": "https://company.no/nyheter", "title": "Nyheter"},
            {"url": "https://company.no/news", "title": "News"},
            {"url": "https://company.no/presse", "title": "Pressemeldinger"},
            {"url": "https://company.no/aktuelt", "title": "Aktuelt"},
        ]
        for res in generic_hubs:
            self.assertFalse(_is_news_candidate(res), f"Generic hub should be rejected: {res['url']}")

    def test_specific_news_article_accepted_by_is_news_candidate(self):
        articles = [
            {"url": "https://company.no/nyheter/2024-05-10-vinner-stor-kontrakt", "title": "Company AS vinner stor kontrakt"},
            {"url": "https://e24.no/naeringsliv/i/xyz123/company-as-dobler-omsetningen", "title": "Company AS dobler omsetningen"},
        ]
        for res in articles:
            self.assertTrue(_is_news_candidate(res), f"Real article should be accepted: {res['url']}")

    def test_date_validation_rejects_modified_retrieval_and_future_dates(self):
        # 1. Future date
        today = datetime.now(timezone.utc).date()
        future_year = today.year + 2
        future_text = f"Artikkel publisert {future_year}-01-01"
        self.assertIsNone(_parse_date(future_text, retrieved_at="2024-01-01"))

        # 2. Modified date
        modified_text = "Sist oppdatert: 2024-06-15. Artikkel om selskapet."
        self.assertIsNone(_parse_date("2024-06-15", retrieved_at="2024-06-16", text_context=modified_text))

        # 3. Retrieval date without publication marker
        retrieval_today = today.isoformat()
        retrieval_text = f"Copyright 2024. Side hentet {retrieval_today}."
        self.assertIsNone(_parse_date(retrieval_today, retrieved_at=retrieval_today, text_context=retrieval_text))

        # 4. Genuine publication date
        genuine_text = "Publisert 2024-03-15 av Redaksjonen. Ny fabrikk åpnet."
        self.assertEqual(_parse_date("2024-03-15", retrieved_at="2024-03-20", text_context=genuine_text), "2024-03-15")

    def test_extract_news_rejects_generic_hub_without_dated_content(self):
        profile = {"organisation_number": "999888777", "name": "Nordic Tech AS"}
        website_value = {
            "final_url": "https://nordictech.no",
            "pages": [
                {
                    "url": "https://nordictech.no/nyheter",
                    "title": "Nyheter",
                    "main_text_excerpt": "Her finner du våre siste nyheter og pressemeldinger.",
                }
            ],
        }
        res = extract_news(profile, website_value, "https://nordictech.no")
        # Since the only page is an undated generic hub, status should be UNAVAILABLE / not found
        self.assertNotEqual(res.status.value, "found")

    def test_extract_news_accepts_dated_announcement(self):
        profile = {"organisation_number": "999888777", "name": "Nordic Tech AS"}
        website_value = {
            "final_url": "https://nordictech.no",
            "pages": [
                {
                    "url": "https://nordictech.no/nyheter",
                    "title": "Nyheter",
                    "main_text_excerpt": "2024-04-01: Nordic Tech vokser og ansetter nye utviklere i Oslo.",
                }
            ],
        }
        res = extract_news(profile, website_value, "https://nordictech.no")
        self.assertEqual(res.status.value, "found")
        self.assertEqual(len(res.value), 1)
        self.assertEqual(res.value[0]["date"], "2024-04-01")

    def test_conflicting_org_number_news_rejected_in_enrichment(self):
        profile = {"organisation_number": "999888777", "name": "Sub AS"}
        search_results = [
            {
                "url": "https://e24.no/artikkel/123",
                "title": "Fusjon i havbruk",
                "snippet": "Konkurrent AS (org.nr 980123456) melder om rekordresultat.",
            }
        ]
        enrichment = extract_search_enrichment(profile, search_results, retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["news"]), 0)
        self.assertTrue(len(enrichment["rejected_news"]) > 0)
        self.assertTrue(any("conflicting organisation number" in r["reason"] for r in enrichment["rejected_news"]))


class SeparationOfConfirmedUnsureRejectedFactsTests(unittest.TestCase):
    """Priority 5: Unsure and rejected remain separate with reasons, never leaking into published facts."""

    def test_rejected_website_does_not_leak_into_published_claims(self):
        # A profile where website identity was rejected
        web_ev = evidence(
            "website",
            "not_found",
            "company_website",
            "https://parentcorp.com",
            as_of="2026-11-04",
        )
        web_ev["identity_rejected"] = True
        web_ev["identity_reasons"] = ["parent_attribution"]
        web_ev["identity_assessment"] = {"publishable": False, "reasons": ["parent_attribution"]}

        profile = {
            "organisation_number": "999888777",
            "name": "Kunde AS",
            "evidence": {
                "website": web_ev,
            },
            "rejected_evidence": {
                "website": {"url": "https://parentcorp.com", "reason": "parent_attribution"}
            },
        }

        unified = build_unified_company_profile(profile)
        # Check unified profile fact
        fact = unified.get_fact(CoverageCategory.WEBSITE)
        self.assertIsNotNone(fact)
        self.assertEqual(fact.status, CoverageFieldStatus.NOT_FOUND)
        self.assertIsNone(fact.value)

        # Check contract envelope
        envelope = unified.to_contract_envelope()
        web_claim = next((c for c in envelope["claims"] if c["field"] == "website"), None)
        self.assertIsNotNone(web_claim)
        self.assertIsNone(web_claim["value"])
        self.assertEqual(web_claim["availability"], "not_available")
        self.assertEqual(web_claim["evidence_ids"], [])

        # Check rejected_facts in envelope
        self.assertTrue(any(r.get("field") == "website" and "parent_attribution" in r.get("reason", "") for r in envelope["rejected_facts"]))

    def test_empty_news_is_not_published_as_available(self):
        profile = {
            "organisation_number": "999888777",
            "name": "Kunde AS",
            "evidence": {},
        }
        unified = build_unified_company_profile(profile)
        fact = unified.get_fact(CoverageCategory.NEWS_EVENTS)
        self.assertIsNotNone(fact)
        self.assertIn(fact.status, [CoverageFieldStatus.UNAVAILABLE, CoverageFieldStatus.NOT_FOUND])
        self.assertIsNone(fact.value)

        envelope = unified.to_contract_envelope()
        news_claim = next((c for c in envelope["claims"] if c["field"] == "news_events"), None)
        self.assertIsNotNone(news_claim)
        self.assertIsNone(news_claim["value"])
        self.assertEqual(news_claim["availability"], "not_available")


if __name__ == "__main__":
    unittest.main()
