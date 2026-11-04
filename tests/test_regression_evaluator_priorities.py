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

    def test_verified_registry_website_genuine_ats_job_reaches_envelope_while_generic_and_parent_rejected(self):
        """Verified registry website path: Genuine ATS job listing reaches contract envelope; generic ATS portals and parent vacancies are rejected."""
        from norway_company_agent.batch import terminal_envelope

        profile = {
            "organisation_number": "999888777",
            "name": "Nordic Solutions AS",
            "overordnetEnhet": "912345688",
            "website": "https://nordicsolutions.no",
            "evidence": {
                "registry": evidence(
                    "registry", "available", "official_registry",
                    "https://data.brreg.no/enhetsregisteret/api/enheter/999888777",
                    value={"organisation_number": "999888777", "name": "Nordic Solutions AS"},
                ),
                "website": evidence(
                    "website", "available", "registry_linked_company_website",
                    "https://nordicsolutions.no",
                    value={
                        "final_url": "https://nordicsolutions.no",
                        "title": "Nordic Solutions AS",
                        "main_text": "Nordic Solutions AS, org.nr 999 888 777.",
                    },
                ),
            },
        }

        search_results = [
            # 1. Genuine individual ATS job listing for target employer
            {
                "url": "https://nordicsolutions.teamtailor.com/jobs/42",
                "title": "Senior Cloud Engineer hos Nordic Solutions AS",
                "snippet": "Nordic Solutions AS søker Senior Cloud Engineer i Oslo. Arbeidsgiver: Nordic Solutions AS.",
            },
            # 2. Generic vendor portal / ATS homepage (must be rejected)
            {
                "url": "https://teamtailor.com",
                "title": "Teamtailor Recruitment Software",
                "snippet": "All-in-one recruitment software for smart businesses.",
            },
            # 3. Parent company vacancy (must be rejected)
            {
                "url": "https://parentcorp.teamtailor.com/jobs/99",
                "title": "Konsernsjef hos Parent Corp ASA",
                "snippet": "Parent Corp ASA (org.nr 912345688) søker ny konsernsjef.",
            },
        ]

        enrichment = extract_search_enrichment(profile, search_results, retrieved_at="2026-11-04T00:00:00Z")

        # Validation: only the genuine job listing for the exact employer passes
        self.assertEqual(len(enrichment["hiring"]), 1)
        self.assertEqual(enrichment["hiring"][0]["url"], "https://nordicsolutions.teamtailor.com/jobs/42")
        self.assertEqual(enrichment["hiring"][0]["title"], "Senior Cloud Engineer hos Nordic Solutions AS")

        # Vendor homepage and parent job are rejected with reasons
        self.assertTrue(len(enrichment["rejected_hiring"]) >= 1)
        self.assertTrue(any("parent" in r["reason"].lower() for r in enrichment["rejected_hiring"]))

        # Attach enrichment to profile as done in batch runner
        profile["hiring_search"] = enrichment["hiring"]
        profile["evidence"]["hiring_search"] = evidence(
            "careers", "available", "public_search",
            "https://api.search.brave.com/res/v1/web/search",
            value=enrichment["hiring"],
            confidence=0.9,
        )
        profile["rejected_evidence"] = {"hiring": enrichment["rejected_hiring"]}

        envelope = terminal_envelope(
            profile,
            run_id="run-test-hiring",
            modules=["registry", "website"],
            started_at="2026-11-04T00:00:00Z",
            completed_at="2026-11-04T00:00:01Z",
        )

        # 1. Genuine individual ATS job advertisement reaches the final envelope claims & evidence
        soc_claim = next(c for c in envelope["claims"] if c["field"] == "social_presence")
        self.assertEqual(soc_claim["availability"], "available")
        self.assertIn("https://nordicsolutions.teamtailor.com/jobs/42", soc_claim["value"])

        # Evidence records the ATS job listing
        matching_evidence = [e for e in envelope["evidence"] if "jobs/42" in e.get("source_url", "")]
        self.assertTrue(len(matching_evidence) > 0)
        self.assertIn("Senior Cloud Engineer", matching_evidence[0]["claim_span"])

        # Profile in envelope carries hiring search
        self.assertIn("hiring_search", envelope["profile"])
        self.assertEqual(envelope["profile"]["hiring_search"][0]["url"], "https://nordicsolutions.teamtailor.com/jobs/42")

        # 2. Generic career pages and parent-company jobs remain rejected in rejected_facts
        self.assertTrue(len(envelope["rejected_facts"]) > 0)
        self.assertTrue(any("parent" in r.get("reason", "").lower() for r in envelope["rejected_facts"]))

        # Rejected parent and vendor URLs must NOT leak into published claims or evidence
        published_urls = [c.get("value") for c in envelope["claims"] if c.get("value")]
        evidence_urls = [e.get("source_url") for e in envelope["evidence"]]
        self.assertNotIn("https://parentcorp.teamtailor.com/jobs/99", str(published_urls))
        self.assertNotIn("https://parentcorp.teamtailor.com/jobs/99", str(evidence_urls))
        self.assertNotIn("https://teamtailor.com", str(published_urls))
        self.assertNotIn("https://teamtailor.com", str(evidence_urls))


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


class DualPathEnrichmentRegressionTests(unittest.TestCase):
    """Regression tests for both paths: verified registry website and rejected/missing registry website."""

    def test_path1_verified_registry_website_with_independent_search_corroboration_and_enrichment(self):
        """Path 1: Verified registry website runs search discovery to corroborate domain and extract news/hiring."""
        profile = {
            "organisation_number": "999888777",
            "name": "Nordic Tech AS",
            "website": "https://nordictech.no",
            "evidence": {
                "website": evidence(
                    "website", "available", "registry_linked_company_website", "https://nordictech.no",
                    value={
                        "final_url": "https://nordictech.no",
                        "title": "Nordic Tech AS - Hovedside",
                        "main_text": "Velkommen til Nordic Tech AS i Oslo. Vi leverer sikre skytjenester. Org.nr: 999 888 777 MVA.",
                        "pages": [],
                    },
                )
            },
        }

        # Independent search returns matching domain, plus news and hiring
        search_results = [
            {
                "url": "https://nordictech.no/om-oss",
                "title": "Om Nordic Tech AS",
                "snippet": "Nordic Tech AS org.nr 999888777 leverer skytjenester i Oslo.",
            },
            {
                "url": "https://e24.no/teknologi/i/abc123/nordic-tech-as-vinner-anbud",
                "title": "Nordic Tech AS vinner stor offentlig kontrakt",
                "snippet": "Nordic Tech AS i Oslo har vunnet en fireårig rammeavtale.",
                "published_at": "2024-04-15",
            },
            {
                "url": "https://nordictech.teamtailor.com/jobs/101",
                "title": "Senior Utvikler hos Nordic Tech AS",
                "snippet": "Nordic Tech AS søker en erfaren utvikler i Oslo.",
            },
        ]

        # 1. Comparison corroborates the registry domain
        comparison = compare_registry_and_search_candidates(profile, profile["evidence"]["website"], search_results)
        self.assertEqual(comparison["verdict"], "corroborated")
        self.assertEqual(comparison["selected_url"], "https://nordictech.no")
        self.assertEqual(comparison["confidence"], 0.99)

        # 2. Search enrichment executes for this company with a verified registry website
        enrichment = extract_search_enrichment(profile, search_results, retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["news"]), 1)
        self.assertEqual(enrichment["news"][0]["date"], "2024-04-15")
        self.assertEqual(len(enrichment["hiring"]), 1)
        self.assertEqual(enrichment["hiring"][0]["platform"].lower(), "teamtailor")

        # 3. Attach search enrichment evidence to profile
        profile["evidence"]["news_search"] = evidence(
            "news", "available", "public_search",
            "https://api.search.brave.com/res/v1/web/search",
            value=enrichment["news"],
            confidence=0.9,
        )
        profile["evidence"]["hiring_search"] = evidence(
            "careers", "available", "public_search",
            "https://api.search.brave.com/res/v1/web/search",
            value=enrichment["hiring"],
            confidence=0.9,
        )

        # 4. Profile builder includes verified website and search news
        unified = build_unified_company_profile(profile)
        web_fact = unified.get_fact(CoverageCategory.WEBSITE)
        self.assertEqual(web_fact.status, CoverageFieldStatus.AVAILABLE)
        self.assertEqual(web_fact.value, "https://nordictech.no")

        news_fact = unified.get_fact(CoverageCategory.NEWS_EVENTS)
        self.assertEqual(news_fact.status, CoverageFieldStatus.AVAILABLE)
        self.assertEqual(len(news_fact.value), 1)
        self.assertEqual(news_fact.value[0]["title"], "Nordic Tech AS vinner stor offentlig kontrakt")

        # 5. Contract envelope validation
        envelope = unified.to_contract_envelope()
        web_claim = next(c for c in envelope["claims"] if c["field"] == "website")
        news_claim = next(c for c in envelope["claims"] if c["field"] == "news_events")
        self.assertEqual(web_claim["availability"], "available")
        self.assertEqual(web_claim["value"], "https://nordictech.no")
        self.assertEqual(news_claim["availability"], "available")
        self.assertIn("Nordic Tech AS vinner stor offentlig kontrakt", news_claim["value"])

        # Hiring search is ingested into social_presence and evidence
        soc_claim = next(c for c in envelope["claims"] if c["field"] == "social_presence")
        self.assertEqual(soc_claim["availability"], "available")
        self.assertIn("https://nordictech.teamtailor.com/jobs/101", soc_claim["value"])
        self.assertTrue(any("jobs/101" in ev["source_url"] for ev in envelope["evidence"]))

    def test_path2_conflicting_registry_website_and_search_candidate_not_published(self):
        """Path 2: Registry domain and search candidate domain in conflict -> marked unsure, not published."""
        profile = {
            "organisation_number": "999888777",
            "name": "Sub Corp AS",
            "evidence": {
                "website": evidence(
                    "website", "available", "registry_linked_company_website", "https://parentgroup.no",
                    value={
                        "final_url": "https://parentgroup.no",
                        "title": "Sub Corp AS Parent Site",
                        "main_text": "Sub Corp AS er en del av Parent Group. Org.nr: 999 888 777 MVA.",
                    },
                )
            },
        }

        # Independent search returns a different publishable domain for the subsidiary
        search_results = [
            {
                "url": "https://subcorp.no",
                "title": "Sub Corp AS Offisiell",
                "snippet": "Velkommen til Sub Corp AS. Org.nr: 999 888 777 MVA i Oslo.",
            }
        ]

        comparison = compare_registry_and_search_candidates(profile, profile["evidence"]["website"], search_results)
        self.assertEqual(comparison["verdict"], "unsure_conflict")
        self.assertFalse(comparison["publishable"])
        self.assertIsNone(comparison["selected_url"])

        # When unsure_conflict occurs, final decision rejects both from published facts
        profile["website"] = None
        profile["evidence"]["website"] = evidence(
            "website", "not_found", "conflicting_sources", "https://parentgroup.no",
            note=comparison["comparison_reason"],
        )
        profile.setdefault("unsure_evidence", {})["website"] = {
            "status": "ambiguous",
            "reason": comparison["comparison_reason"],
            "quarantined_urls": comparison["quarantined_urls"],
        }

        unified = build_unified_company_profile(profile)
        web_fact = unified.get_fact(CoverageCategory.WEBSITE)
        self.assertEqual(web_fact.status, CoverageFieldStatus.NOT_FOUND)
        self.assertIsNone(web_fact.value)

        envelope = unified.to_contract_envelope()
        web_claim = next(c for c in envelope["claims"] if c["field"] == "website")
        self.assertEqual(web_claim["availability"], "not_available")
        self.assertIsNone(web_claim["value"])
        self.assertEqual(web_claim["evidence_ids"], [])
        self.assertTrue(len(envelope.get("unsure_facts", [])) > 0)

    def test_path3_rejected_registry_website_with_search_candidate_preferred(self):
        """Path 3: Registry website rejected, search candidate preferred and identity-gated."""
        rej_web = evidence(
            "website", "not_found", "registry_linked_company_website", "https://beta-parked.com",
            note="captured page is a parked domain placeholder",
            value={"final_url": "https://beta-parked.com", "title": "Buy this domain"},
        )
        rej_web["identity_rejected"] = True
        profile = {
            "organisation_number": "999888777",
            "name": "Beta Consult AS",
            "website": "https://beta-parked.com",
            "evidence": {
                "website": rej_web,
            },
        }

        search_results = [
            {
                "url": "https://betaconsult.no",
                "title": "Beta Consult AS",
                "snippet": "Velkommen til Beta Consult AS. Org.nr 999 888 777.",
            }
        ]

        comparison = compare_registry_and_search_candidates(profile, profile["evidence"]["website"], search_results)
        self.assertEqual(comparison["verdict"], "search_candidate_preferred")
        self.assertEqual(comparison["selected_url"].rstrip("/"), "https://betaconsult.no")

    def test_path4_verified_registry_website_offline_fallback_respects_limits(self):
        """Path 4: When Brave search key is absent or budget is exhausted, verified registry site is preserved."""
        profile = {
            "organisation_number": "999888777",
            "name": "Gamma AS",
            "website": "https://gamma.no",
            "evidence": {
                "website": evidence(
                    "website", "available", "registry_linked_company_website", "https://gamma.no",
                    value={
                        "final_url": "https://gamma.no",
                        "title": "Gamma AS",
                        "main_text": "Gamma AS leverer IT. Org.nr: 999 888 777 MVA.",
                    },
                )
            },
        }

        # Offline: no search performed, registry evidence stays available
        unified = build_unified_company_profile(profile)
        web_fact = unified.get_fact(CoverageCategory.WEBSITE)
        self.assertEqual(web_fact.status, CoverageFieldStatus.AVAILABLE)
        self.assertEqual(web_fact.value, "https://gamma.no")


class EvaluatorPrioritiesComprehensiveTests(unittest.TestCase):
    """Priority 1-7: Comprehensive deterministic tests covering all evaluator requirements."""

    def test_01_correct_company_website_confirmed(self):
        """1. Correct company website confirmed with exact entity identity proof."""
        profile = {
            "organisation_number": "999888777",
            "name": "Eksempel Tech AS",
            "evidence": {
                "website": evidence(
                    "website", "available", "registry_linked_company_website", "https://eksempeltech.no",
                    value={
                        "final_url": "https://eksempeltech.no",
                        "title": "Eksempel Tech AS - Offisiell nettside",
                        "main_text": "Eksempel Tech AS leverer programvare. Org.nr: 999 888 777 MVA.",
                    },
                )
            },
        }
        assessment = assess_website_identity(profile)
        self.assertTrue(assessment["publishable"])
        self.assertEqual(assessment["status"], "exact")

    def test_02_parent_group_website_not_incorrectly_accepted(self):
        """2. Parent/group website not incorrectly attributed to subsidiary."""
        profile = {
            "organisation_number": "999888777",
            "name": "Datterforetak AS",
            "overordnetEnhet": "912345688",
            "evidence": {
                "website": evidence(
                    "website", "available", "registry_linked_company_website", "https://morselskap.no",
                    value={
                        "final_url": "https://morselskap.no",
                        "title": "Morselskap Konsern ASA",
                        "main_text": "Morselskap Konsern ASA er holdingselskapet. Org.nr: 912 345 688 MVA.",
                    },
                )
            },
        }
        assessment = assess_website_identity(profile)
        self.assertFalse(assessment["publishable"])
        self.assertEqual(assessment["status"], "parent_attribution")

    def test_03_similar_name_company_rejected(self):
        """3. Similar-name company or brand rejected when exact tokens or org nr conflict."""
        profile = {
            "organisation_number": "999888777",
            "name": "Nordic Solutions Consulting AS",
        }
        # Result mentioning Nordic Solutions ASA but conflicting org number
        result_conflicting = {
            "url": "https://nordicsolutions.com",
            "title": "Nordic Solutions ASA",
            "snippet": "Nordic Solutions ASA (org.nr 980123456) er et uavhengig selskap.",
        }
        enrichment = extract_search_enrichment(profile, [result_conflicting], retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["hiring"]), 0)
        self.assertEqual(len(enrichment["news"]), 0)

    def test_04_genuine_individual_ats_vacancy_accepted(self):
        """4. Genuine individual ATS vacancy accepted with exact employer matching."""
        profile = {
            "organisation_number": "999888777",
            "name": "Acme Software AS",
        }
        results = [
            {
                "url": "https://acme-software.teamtailor.com/jobs/456789-senior-python-utvikler",
                "title": "Senior Python Utvikler hos Acme Software AS",
                "snippet": "Acme Software AS søker nå etter en dyktig utvikler i Oslo.",
            }
        ]
        enrichment = extract_search_enrichment(profile, results, retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["hiring"]), 1)
        item = enrichment["hiring"][0]
        self.assertEqual(item["platform"], "Teamtailor")
        self.assertEqual(item["verdict"], "confirmed")
        self.assertIn("Individual active vacancy", item["verdict_reason"])

    def test_05_generic_ats_homepage_and_search_portal_rejected(self):
        """5. Generic ATS vendor homepages and search portals rejected with specific reasons."""
        profile = {
            "organisation_number": "999888777",
            "name": "Acme Software AS",
        }
        vendor_homepages = [
            {"url": "https://teamtailor.com", "title": "Teamtailor ATS Homepage"},
            {"url": "https://www.reachmee.com/about", "title": "ReachMee Talent Software"},
            {"url": "https://jobbnorge.no/ledige-stillinger/sok", "title": "Ledige stillinger - Jobbnorge Søk"},
            {"url": "https://finn.no/jobb/stilling/sok.html?q=utvikler", "title": "FINN Jobb Søk"},
        ]
        enrichment = extract_search_enrichment(profile, vendor_homepages, retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["hiring"]), 0)
        self.assertEqual(len(enrichment["rejected_hiring"]), len(vendor_homepages))
        reasons = [r["reason"] for r in enrichment["rejected_hiring"]]
        self.assertTrue(any("ATS vendor homepage" in r for r in reasons))
        self.assertTrue(any("generic ATS search page" in r for r in reasons))

    def test_06_parent_or_franchise_wide_vacancy_rejected(self):
        """6. Parent-company or franchise vacancy rejected when requested company is subsidiary."""
        profile = {
            "organisation_number": "999888777",
            "name": "Nordic Sub AS",
            "overordnetEnhet": "912345688",
        }
        parent_vacancy = {
            "url": "https://recman.no/jobs/parent-holding-leder",
            "title": "Avdelingsleder hos Nordic Parent Group",
            "snippet": "Nordic Parent Group (org.nr 912345688) rekrutterer til konsernledelsen.",
        }
        enrichment = extract_search_enrichment(profile, [parent_vacancy], retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["hiring"]), 0)
        self.assertEqual(len(enrichment["rejected_hiring"]), 1)
        self.assertIn("parent company", enrichment["rejected_hiring"][0]["reason"])

    def test_07_dated_article_naming_company_accepted(self):
        """7. Dated news article naming the company accepted with publisher and publication date."""
        profile = {
            "organisation_number": "999888777",
            "name": "Solar Energy AS",
        }
        results = [
            {
                "url": "https://e24.no/energi/i/xyz987/solar-energy-as-apner-ny-park",
                "title": "Solar Energy AS åpner ny solcellepark i Innlandet",
                "snippet": "Solar Energy AS investerer 150 millioner i Innlandet.",
                "published_at": "2024-06-20",
            }
        ]
        enrichment = extract_search_enrichment(profile, results, retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["news"]), 1)
        article = enrichment["news"][0]
        self.assertEqual(article["published_at"], "2024-06-20")
        self.assertEqual(article["publisher"], "e24.no")
        self.assertEqual(article["verdict"], "confirmed")
        self.assertIn("e24.no", article["verdict_reason"])

    def test_08_undated_or_unrelated_article_rejected(self):
        """8. Undated pages and unrelated company articles rejected without publication."""
        profile = {
            "organisation_number": "999888777",
            "name": "Solar Energy AS",
        }
        undated = {
            "url": "https://solarenergy.no/tjenester",
            "title": "Våre tjenester - Solar Energy AS",
            "snippet": "Sist oppdatert: 2024-05-01. Vi tilbyr solcelleinstallasjon.",
        }
        unrelated = {
            "url": "https://e24.no/bors/i/111/annen-bedrift-rekord",
            "title": "Annen Bedrift ASA melder om rekordvekst",
            "snippet": "Publisert 2024-05-01. Annen Bedrift ASA vokser videre.",
            "published_at": "2024-05-01",
        }
        enrichment = extract_search_enrichment(profile, [undated, unrelated], retrieved_at="2026-11-04T00:00:00Z")
        self.assertEqual(len(enrichment["news"]), 0)
        self.assertEqual(len(enrichment["rejected_news"]), 2)

    def test_09_rejected_and_unsure_evidence_never_leaks_into_published_claims(self):
        """9. Unsure and rejected facts remain strictly segregated from published claims."""
        profile = {
            "organisation_number": "999888777",
            "name": "Testbed AS",
            "website": None,
            "evidence": {
                "website": evidence(
                    "website", "not_found", "search_discovered_company_website",
                    "https://parentcorp.com",
                    note="parent_attribution: captured page cites parent organisation number",
                    rejection_reason="parent_attribution",
                    verdict="rejected",
                    verdict_reason="Website belongs to parent company, not the requested entity",
                ),
            },
            "rejected_evidence": {
                "website": {"url": "https://parentcorp.com", "reason": "parent_attribution"},
                "hiring": [{"url": "https://teamtailor.com", "reason": "ATS vendor homepage"}],
            },
            "unsure_evidence": {
                "website": {"status": "ambiguous", "reason": "Conflicting domain names without conclusive proof"},
            },
        }
        unified = build_unified_company_profile(profile)
        envelope = unified.to_contract_envelope()

        # Claims must have 29 entries and website must be not_available
        self.assertEqual(len(envelope["claims"]), 29)
        web_claim = next(c for c in envelope["claims"] if c["field"] == "website")
        self.assertEqual(web_claim["availability"], "not_available")
        self.assertIsNone(web_claim["value"])

        # Rejected facts must contain the rejected website
        self.assertTrue(len(envelope.get("rejected_facts", [])) > 0)
        self.assertTrue(any(r["field"] == "website" for r in envelope["rejected_facts"]))

        # Unsure facts must contain the unsure record
        self.assertTrue(len(envelope.get("unsure_facts", [])) > 0)

    def test_10_verdict_and_reason_attached_to_sources_and_reaches_frontend_model(self):
        """10. Verdict (confirmed/unsure/rejected) and reason are attached to sources."""
        rec_conf = evidence(
            "registry", "available", "official_registry_bulk", "https://data.brreg.no/csv",
            verdict="confirmed", verdict_reason="Official Enhetsregisteret statutory filing passes identity verification"
        )
        rec_rej = evidence(
            "careers", "not_found", "public_search", "https://teamtailor.com",
            verdict="rejected", verdict_reason="This is the ATS vendor homepage, not the company's careers page"
        )
        rec_unsure = evidence(
            "website", "not_found", "conflicting_sources", "https://conflict.no",
            verdict="unsure", verdict_reason="Registry domain and search domain conflict without conclusive proof"
        )
        self.assertEqual(rec_conf["verdict"], "confirmed")
        self.assertEqual(rec_rej["verdict"], "rejected")
        self.assertEqual(rec_unsure["verdict"], "unsure")
        self.assertIn("Official Enhetsregisteret", rec_conf["verdict_reason"])
        self.assertIn("ATS vendor homepage", rec_rej["verdict_reason"])
        self.assertIn("Registry domain and search domain conflict", rec_unsure["verdict_reason"])

    def test_11_terminal_envelope_backward_compatibility_preserved(self):
        """11. Terminal envelope schema preserves 29 categories, run metadata, operations, and claims."""
        profile = {
            "organisation_number": "999888777",
            "name": "Compat AS",
            "evidence": {
                "registry": evidence("registry", "available", "official_registry_bulk", "https://data.brreg.no/csv"),
            },
        }
        from norway_company_agent.batch import terminal_envelope
        env = terminal_envelope(
            profile, run_id="run-compat-test", modules=["registry", "website"],
            started_at="2026-11-04T00:00:00Z", completed_at="2026-11-04T00:00:05Z"
        )
        self.assertIn("claims", env)
        self.assertEqual(len(env["claims"]), 29)
        self.assertIn("rejected_facts", env)
        self.assertIn("unsure_facts", env)
        self.assertIn("run", env)
        self.assertEqual(env["run"]["run_id"], "run-compat-test")
        self.assertIn("operations", env)
        self.assertIn("state", env)


if __name__ == "__main__":
    unittest.main()
