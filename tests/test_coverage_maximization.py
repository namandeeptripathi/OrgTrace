"""Competition Coverage Maximization Test Suite.

Verifies:
1. Roles fetched and normalized (official BRREG roles as authoritative, all metadata preserved).
2. Locations fetched and normalized (registered office distinct from subunits, source metadata).
3. Jobs/careers extracted with openings and provenance.
4. Public activity extracted with titles, snippets, provenance.
5. Careers and news priority links selected by crawl engine.
6. Identity mismatch strictly rejected by identity gate.
7. Unavailable website does not fabricate facts.
8. Missing jobs does not become false hiring.
9. Missing publication date remains missing (never invented).
10. Duplicate facts avoided (people and locations deduplication).
11. Refresh idempotency (zero false changes on identical re-runs).
12. Request budget enforcement (guard limits requests).
13. Reduced mode triggers and skips non-critical operations.
14. Exactly 100 terminal envelopes validate successfully.
15. Evaluator batch contract processes arbitrary companies with terminal results.
"""

from __future__ import annotations

import unittest
from typing import Any

from norway_company_agent.batch import compute_profile_status, terminal_envelope, validate_envelopes
from norway_company_agent.change_intelligence import analyze_profile_changes
from norway_company_agent.evidence import evidence, utc_now
from norway_company_agent.identity import apply_website_identity_gate
from norway_company_agent.official import normalize_locations, normalize_roles
from norway_company_agent.profile_extraction import (
    FieldStatus,
    extract_careers,
    extract_company_profile,
    extract_leadership,
    extract_locations,
    extract_news,
    extract_people,
)
from norway_company_agent.resilience import CompetitionExecutionGuard
from norway_company_agent.website import _priority_links


class CoverageMaximizationTests(unittest.TestCase):
    """Targeted tests for Signalpost competition coverage maximization."""

    def test_roles_fetched_and_normalized(self):
        # 1. normalize_roles preserves BRREG fields
        raw_body = {
            "rollegrupper": [
                {
                    "type": {"kode": "STYR", "beskrivelse": "Styre"},
                    "sistEndret": "2024-01-15",
                    "roller": [
                        {
                            "type": {"kode": "LEDE", "beskrivelse": "Styreleder"},
                            "person": {"navn": {"fornavn": "Ola", "etternavn": "Nordmann"}},
                            "avregistrert": False,
                        },
                        {
                            "type": {"kode": "MEDL", "beskrivelse": "Styremedlem"},
                            "person": {"navn": {"fornavn": "Kari", "etternavn": "Nordmann"}},
                            "avregistrert": True,
                        },
                    ],
                },
                {
                    "type": {"kode": "DAGL", "beskrivelse": "Daglig leder/adm.dir."},
                    "sistEndret": "2023-06-01",
                    "roller": [
                        {
                            "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                            "person": {"navn": {"fornavn": "Per", "etternavn": "Hansen"}},
                            "avregistrert": False,
                        }
                    ],
                },
            ]
        }
        normalized = normalize_roles(raw_body)
        roles = normalized["roles"]
        self.assertEqual(len(roles), 3)
        self.assertEqual(roles[0]["name"], "Ola Nordmann")
        self.assertEqual(roles[0]["role_code"], "LEDE")
        self.assertEqual(roles[0]["group_code"], "STYR")
        self.assertEqual(roles[0]["last_changed"], "2024-01-15")
        self.assertFalse(roles[0]["inactive"])
        self.assertTrue(roles[1]["inactive"])

        # 2. extract_people exposes people with source and retrieval provenance
        profile = {
            "organisation_number": "999888777",
            "name": "Test AS",
            "evidence": {
                "roles": evidence(
                    "roles",
                    "available",
                    "official_roles",
                    "https://data.brreg.no/enhetsregisteret/api/enheter/999888777/roller",
                    value=normalized,
                    retrieved_at="2026-09-26T10:00:00Z",
                )
            },
        }
        people_field = extract_people(profile, None, {}, None)
        self.assertEqual(people_field.status, FieldStatus.FOUND)
        self.assertEqual(len(people_field.value), 3)
        active_people = [p for p in people_field.value if not p["inactive"]]
        self.assertEqual(len(active_people), 2)
        p1 = active_people[0]
        self.assertEqual(p1["name"], "Ola Nordmann")
        self.assertEqual(p1["role"], "Styreleder")
        self.assertEqual(p1["source"], "official_roles")
        self.assertEqual(p1["source_url"], "https://data.brreg.no/enhetsregisteret/api/enheter/999888777/roller")
        self.assertEqual(p1["retrieved_at"], "2026-09-26T10:00:00Z")

    def test_locations_fetched_and_normalized(self):
        # 1. normalize_locations extracts subunits
        raw_body = {
            "_embedded": {
                "underenheter": [
                    {
                        "organisasjonsnummer": "999111222",
                        "navn": "Test AS Avd Bergen",
                        "beliggenhetsadresse": {"adresse": ["Strandgaten 10"], "postnummer": "5004", "poststed": "Bergen"},
                        "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmeringstjenester"},
                        "antallAnsatte": 15,
                    }
                ]
            }
        }
        normalized = normalize_locations(raw_body)
        self.assertEqual(len(normalized["locations"]), 1)
        sub = normalized["locations"][0]
        self.assertEqual(sub["organisation_number"], "999111222")
        self.assertEqual(sub["name"], "Test AS Avd Bergen")

        # 2. extract_locations distinguishes registered office from subunits
        profile = {
            "organisation_number": "999888777",
            "name": "Test AS",
            "business_address": {"adresse": ["Karl Johans gate 1"], "postnummer": "0154", "poststed": "Oslo"},
            "municipality": "Oslo",
            "employees": 50,
            "evidence": {
                "locations": evidence(
                    "locations",
                    "available",
                    "official_subunits",
                    "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet=999888777",
                    value=normalized,
                    retrieved_at="2026-09-26T10:00:00Z",
                )
            },
        }
        loc_field = extract_locations(profile, None, {}, None)
        self.assertEqual(loc_field.status, FieldStatus.FOUND)
        locs = loc_field.value
        self.assertEqual(len(locs), 2)

        hq = next(loc for loc in locs if loc["is_headquarters"])
        subunit = next(loc for loc in locs if not loc["is_headquarters"])

        self.assertEqual(hq["location_type"], "registered_office")
        self.assertEqual(hq["city"], "Oslo")
        self.assertEqual(hq["organisation_number"], "999888777")
        self.assertTrue(hq["is_headquarters"])

        self.assertEqual(subunit["location_type"], "subunit")
        self.assertEqual(subunit["city"], "Bergen")
        self.assertEqual(subunit["organisation_number"], "999111222")
        self.assertEqual(subunit["employees"], 15)
        self.assertFalse(subunit["is_headquarters"])

    def test_jobs_careers_extracted(self):
        profile = {"organisation_number": "999888777", "name": "Test AS"}
        website_value = {
            "retrieved_at": "2026-09-26T10:00:00Z",
            "pages": [
                {
                    "url": "https://test.no/karriere",
                    "retrieved_at": "2026-09-26T10:01:00Z",
                    "main_text_excerpt": "Vi søker nye kolleger!\n- Senior Python Utvikler\n- DevOps Ingeniør\nSend søknad.",
                }
            ],
        }
        careers = extract_careers(profile, website_value, "https://test.no")
        self.assertEqual(careers.status, FieldStatus.FOUND)
        val = careers.value
        self.assertTrue(val["has_careers_page"])
        self.assertEqual(val["careers_url"], "https://test.no/karriere")
        self.assertTrue(val["hiring_active"])
        self.assertIn("Senior Python Utvikler", val["openings"])
        self.assertIn("DevOps Ingeniør", val["openings"])
        self.assertEqual(val["retrieved_at"], "2026-09-26T10:01:00Z")

    def test_public_activity_extracted(self):
        profile = {"organisation_number": "999888777", "name": "Test AS"}
        website_value = {
            "retrieved_at": "2026-09-26T10:00:00Z",
            "pages": [
                {
                    "url": "https://test.no/nyheter/ny-kontrakt",
                    "title": "Inngår stor rammeavtale",
                    "retrieved_at": "2026-09-26T10:02:00Z",
                    "main_text_excerpt": "Publisert 2024-05-15. Selskapet har inngått en ny treårig rammeavtale.",
                }
            ],
        }
        news_field = extract_news(profile, website_value, "https://test.no")
        self.assertEqual(news_field.status, FieldStatus.FOUND)
        self.assertEqual(len(news_field.value), 1)
        item = news_field.value[0]
        self.assertEqual(item["title"], "Inngår stor rammeavtale")
        self.assertEqual(item["url"], "https://test.no/nyheter/ny-kontrakt")
        self.assertEqual(item["date"], "2024-05-15")
        self.assertEqual(item["retrieved_at"], "2026-09-26T10:02:00Z")

    def test_careers_news_priority_links_selected(self):
        from bs4 import BeautifulSoup

        html = """
        <html>
          <body>
            <a href="/om-oss">Om oss</a>
            <a href="/karriere">Karriere</a>
            <a href="/nyheter">Siste nytt</a>
            <a href="/ledelse">Vår ledelse</a>
            <a href="/kontakt">Kontakt</a>
            <a href="/vilkar">Brukervilkår</a>
            <a href="/personvern">Personvern</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = _priority_links("https://example.no", soup, limit=5)
        self.assertLessEqual(len(links), 5)
        # Should pick category-diverse high-value links: careers, news, leadership, about, contact
        paths = [link.split("example.no")[1] for link in links]
        self.assertIn("/karriere", paths)
        self.assertIn("/nyheter", paths)
        self.assertIn("/om-oss", paths)
        self.assertNotIn("/personvern", paths)

    def test_identity_mismatch_rejected(self):
        profile = {"organisation_number": "999888777", "name": "Alpha Solutions AS"}
        # Crawled website belonging to completely different company
        website_record = {
            "status": "available",
            "source_url": "https://beta-consulting.no",
            "value": {
                "final_url": "https://beta-consulting.no",
                "structured_organisations": [
                    {"name": "Beta Consulting AS", "legalName": "Beta Consulting AS"}
                ],
                "main_text_excerpt": "Beta Consulting AS er et rådgivningsselskap.",
                "pages": [],
            },
        }
        gated = apply_website_identity_gate(profile, website_record)
        assessment = gated.get("assessment")
        self.assertIsNotNone(assessment)
        self.assertFalse(assessment.get("publishable"), "Mismatching company website must not be marked publishable")

    def test_unavailable_website_does_not_fabricate(self):
        profile = {"organisation_number": "999888777", "name": "Test AS"}
        careers = extract_careers(profile, None, None)
        news = extract_news(profile, None, None)
        self.assertEqual(careers.status, FieldStatus.UNAVAILABLE)
        self.assertIsNone(careers.value)
        self.assertEqual(news.status, FieldStatus.UNAVAILABLE)
        self.assertIsNone(news.value)

    def test_missing_jobs_does_not_become_false_hiring(self):
        profile = {"organisation_number": "999888777", "name": "Test AS"}
        website_value = {
            "pages": [
                {
                    "url": "https://test.no/karriere",
                    "main_text_excerpt": "Vi har for tiden ingen ledige stillinger. Følg oss gjerne på LinkedIn.",
                }
            ]
        }
        careers = extract_careers(profile, website_value, "https://test.no")
        self.assertEqual(careers.status, FieldStatus.FOUND)
        val = careers.value
        self.assertTrue(val["has_careers_page"])
        self.assertFalse(val["hiring_active"])
        self.assertEqual(val["openings"], [])

    def test_missing_publication_date_remains_missing(self):
        profile = {"organisation_number": "999888777", "name": "Test AS"}
        website_value = {
            "pages": [
                {
                    "url": "https://test.no/nyheter/artikkel",
                    "title": "Vår nye produktlinje",
                    "main_text_excerpt": "Vi lanserer vår nye produktlinje for industrien.",
                }
            ]
        }
        news_field = extract_news(profile, website_value, "https://test.no")
        self.assertEqual(news_field.status, FieldStatus.FOUND)
        item = news_field.value[0]
        self.assertIsNone(item["date"], "Missing publication date must not be invented")

    def test_duplicate_facts_avoided(self):
        # Subunits with duplicate entries must be deduplicated
        raw_body = {
            "_embedded": {
                "underenheter": [
                    {
                        "organisasjonsnummer": "999111222",
                        "navn": "Test AS Avd Bergen",
                        "beliggenhetsadresse": {"adresse": ["Strandgaten 10"], "postnummer": "5004", "poststed": "Bergen"},
                    },
                    {
                        "organisasjonsnummer": "999111222",
                        "navn": "Test AS Avd Bergen",
                        "beliggenhetsadresse": {"adresse": ["Strandgaten 10"], "postnummer": "5004", "poststed": "Bergen"},
                    },
                ]
            }
        }
        normalized = normalize_locations(raw_body)
        profile = {
            "organisation_number": "999888777",
            "name": "Test AS",
            "evidence": {
                "locations": evidence("locations", "available", "official_subunits", "https://example.no", value=normalized)
            },
        }
        loc_field = extract_locations(profile, None, {}, None)
        subunits = [loc for loc in loc_field.value if loc["location_type"] == "subunit"]
        self.assertEqual(len(subunits), 1, "Duplicate subunit records must be deduplicated")

    def test_refresh_idempotency(self):
        # Two identical profile runs must produce 0 material changes
        profile1 = {
            "organisation_number": "999888777",
            "name": "Test AS",
            "employees": 25,
            "status": "complete",
            "evidence": {
                "roles": evidence("roles", "available", "official_roles", "https://example.no/roles", value={"roles": [{"name": "Ola", "role": "CEO"}]}),
                "website": evidence("website", "available", "company_website", "https://test.no"),
            },
        }
        profile2 = dict(profile1)
        report1 = analyze_profile_changes(None, profile1)
        self.assertEqual(report1.to_dict()["status"], "INITIAL_OBSERVATION")
        report2 = analyze_profile_changes(profile1, profile2)
        self.assertEqual(report2.material_changes, 0, "Identical snapshots must yield 0 material changes")

    def test_request_budget_enforcement(self):
        guard = CompetitionExecutionGuard(max_requests=5, max_cost=1.0)
        for _ in range(5):
            allowed, _ = guard.acquire_request()
            self.assertTrue(allowed)
        # 6th request must be rejected
        allowed, reason = guard.acquire_request()
        self.assertFalse(allowed)
        self.assertIn("exhausted", reason.lower())

    def test_reduced_mode(self):
        import time
        # Reduced mode triggers when runtime threshold is exceeded
        guard = CompetitionExecutionGuard(
            max_requests=100,
            max_cost=10.0,
            max_runtime_seconds=100.0,
            reduced_mode_threshold_seconds=10.0,
        )
        guard.start_time = time.monotonic() - 15.0  # 15s elapsed > 10s threshold
        self.assertTrue(guard.is_reduced_mode())

    def test_exactly_100_terminal_envelopes(self):
        # Generate 100 mock profiles and verify validate_envelopes passes
        envelopes = []
        modules = ["registry", "accounting_obligation", "financials", "roles", "locations", "website"]
        for i in range(100):
            org = f"999000{i:03d}"
            prof = {
                "organisation_number": org,
                "name": f"Company {i} AS",
                "evidence": {
                    "registry": evidence("registry", "available", "official_registry", "https://example.no"),
                    "accounting_obligation": evidence("accounting_obligation", "available", "official_rule", "https://example.no"),
                    "financials": evidence("financials", "available", "official_accounts", "https://example.no"),
                    "roles": evidence("roles", "available", "official_roles", "https://example.no"),
                    "locations": evidence("locations", "available", "official_subunits", "https://example.no"),
                    "website": evidence("website", "not_found", "company_website", "https://example.no"),
                },
            }
            env = terminal_envelope(prof, run_id="test-run", modules=modules, started_at=utc_now(), completed_at=utc_now())
            envelopes.append(env)

        validation = validate_envelopes(envelopes, 100)
        self.assertTrue(validation["passed"])
        self.assertTrue(validation["checks"]["exact_expected_count"])
        self.assertTrue(validation["checks"]["all_entity_states_terminal"])
        self.assertTrue(validation["checks"]["all_module_states_terminal"])

    def test_evaluator_visible_extracted_profile_populated(self):
        # Verify extract_company_profile integrates all domains
        profile = {
            "organisation_number": "999888777",
            "name": "Nordic Tech AS",
            "business_address": {"adresse": ["Storgata 1"], "poststed": "Oslo"},
            "municipality": "Oslo",
            "employees": 30,
            "evidence": {
                "roles": evidence(
                    "roles",
                    "available",
                    "official_roles",
                    "https://data.brreg.no/roles",
                    value={"roles": [{"name": "Kari Leder", "role": "Daglig leder", "role_code": "DAGL", "inactive": False}]},
                ),
                "locations": evidence(
                    "locations",
                    "available",
                    "official_subunits",
                    "https://data.brreg.no/subunits",
                    value={"locations": [{"organisation_number": "999111333", "name": "Nordic Tech AS Avd Trondheim"}]},
                ),
                "website": evidence(
                    "website",
                    "available",
                    "company_website",
                    "https://nordictech.no",
                    value={
                        "final_url": "https://nordictech.no",
                        "pages": [
                            {"url": "https://nordictech.no/karriere", "main_text_excerpt": "Vi søker:\n- Frontend-utvikler"},
                            {"url": "https://nordictech.no/nyheter", "main_text_excerpt": "2024-04-01: Nordic Tech vokser"},
                        ],
                    },
                ),
            },
        }
        ext = extract_company_profile(profile)
        self.assertEqual(ext.people.status, FieldStatus.FOUND)
        self.assertEqual(ext.locations.status, FieldStatus.FOUND)
        self.assertEqual(ext.careers.status, FieldStatus.FOUND)
        self.assertEqual(ext.news.status, FieldStatus.FOUND)
        self.assertEqual(len(ext.people.value), 1)
        self.assertEqual(len(ext.locations.value), 2)  # 1 registered office + 1 subunit
        self.assertTrue(ext.careers.value["hiring_active"])
        self.assertEqual(len(ext.news.value), 1)

    def test_same_registered_domain_subdomain_accepted(self):
        from bs4 import BeautifulSoup
        html = """
        <html>
          <body>
            <a href="https://karriere.company.no/stillinger">Karriere</a>
            <a href="https://jobb.company.no/bli-med">Jobb</a>
            <a href="https://news.company.no/siste">News</a>
            <a href="https://nyheter.company.no/presse">Nyheter</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = _priority_links("https://company.no", soup, limit=7)
        self.assertIn("https://karriere.company.no/stillinger", links)
        self.assertIn("https://news.company.no/siste", links)

    def test_unrelated_domain_and_aggregators_rejected(self):
        from bs4 import BeautifulSoup
        html = """
        <html>
          <body>
            <a href="https://proff.no/selskap/company/12345">Proff profil</a>
            <a href="https://purehelp.no/company">Purehelp</a>
            <a href="https://othercompany.com/karriere">Annet selskap</a>
            <a href="https://facebook.com/company">Facebook</a>
            <a href="https://company.no/om-oss">Om oss</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = _priority_links("https://company.no", soup, limit=7)
        self.assertIn("https://company.no/om-oss", links)
        for link in links:
            self.assertNotIn("proff.no", link)
            self.assertNotIn("purehelp.no", link)
            self.assertNotIn("othercompany.com", link)
            self.assertNotIn("facebook.com", link)

    def test_ats_careers_link_detected_on_verified_page(self):
        from bs4 import BeautifulSoup
        from norway_company_agent.website import extract_ats_links
        # ATS links on verified company page
        html = """
        <html>
          <body>
            <a href="https://company.reachmee.com/jobs/123">Ledige stillinger</a>
            <a href="https://company.teamtailor.com">Jobb hos oss</a>
            <a href="https://www.finn.no/jobb/stilling?id=999">Vår stillingsannonse på Finn</a>
            <a href="https://finn.no/bil">Kjøp bil</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        ats_links = extract_ats_links(soup, "https://company.no")
        urls = [item["url"] for item in ats_links]
        self.assertIn("https://company.reachmee.com/jobs/123", urls)
        self.assertIn("https://company.teamtailor.com", urls)
        self.assertIn("https://www.finn.no/jobb/stilling?id=999", urls)
        self.assertNotIn("https://finn.no/bil", urls)

        # In profile_extraction: only extracted if website passed identity gate (website_value is present)
        profile_verified = {
            "organisation_number": "999888777",
            "name": "Verified AS",
            "evidence": {
                "website": evidence(
                    "website",
                    "available",
                    "company_website",
                    "https://company.no",
                    value={
                        "final_url": "https://company.no",
                        "outbound_career_links": ats_links,
                    },
                ),
            },
        }
        res_verified = extract_company_profile(profile_verified)
        self.assertEqual(res_verified.careers.status, FieldStatus.FOUND)
        self.assertTrue(res_verified.careers.value["has_careers_page"])
        self.assertIn("company.reachmee.com", res_verified.careers.value["careers_url"])

        # If unverified/unavailable website, ATS link must NOT be recorded
        profile_unverified = {
            "organisation_number": "999888777",
            "name": "Unverified AS",
            "evidence": {
                "website": evidence("website", "not_found", "company_website", "https://company.no"),
            },
        }
        res_unverified = extract_company_profile(profile_unverified)
        self.assertEqual(res_unverified.careers.status, FieldStatus.UNAVAILABLE)

    def test_ats_link_does_not_imply_hiring_active(self):
        profile = {
            "organisation_number": "999888777",
            "name": "Company AS",
            "evidence": {
                "website": evidence(
                    "website",
                    "available",
                    "company_website",
                    "https://company.no",
                    value={
                        "final_url": "https://company.no",
                        "outbound_career_links": [{
                            "url": "https://company.teamtailor.com",
                            "platform": "teamtailor",
                            "source_url": "https://company.no",
                        }],
                    },
                ),
            },
        }
        res = extract_company_profile(profile)
        self.assertEqual(res.careers.status, FieldStatus.FOUND)
        self.assertTrue(res.careers.value["has_careers_page"])
        # CRITICAL: hiring_active must be None (not True), openings must be empty
        self.assertIsNone(res.careers.value["hiring_active"])
        self.assertEqual(res.careers.value["openings"], [])

    def test_new_norwegian_patterns_recognized(self):
        from bs4 import BeautifulSoup
        from norway_company_agent.profile_extraction import CAREERS_PATH, NEWS_PATH
        # Check careers patterns
        for path in ("/jobbe-hos-oss", "/bli-en-av-oss", "/arbeide-hos-oss", "/rekruttering", "/stilling"):
            self.assertIsNotNone(CAREERS_PATH.search(path), f"CAREERS_PATH must match {path}")
        # Check news patterns
        for path in ("/siste-nytt", "/presse", "/nyhetsarkiv", "/medieomtale"):
            self.assertIsNotNone(NEWS_PATH.search(path), f"NEWS_PATH must match {path}")

        # Check crawler priority selector recognizes them
        html = """
        <html>
          <body>
            <a href="/jobbe-hos-oss">Jobbe hos oss</a>
            <a href="/siste-nytt">Siste nytt</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = _priority_links("https://company.no", soup, limit=7)
        self.assertIn("https://company.no/jobbe-hos-oss", links)
        self.assertIn("https://company.no/siste-nytt", links)

    def test_secondary_page_limit_is_seven(self):
        from bs4 import BeautifulSoup
        html = """
        <html>
          <body>
            <a href="/karriere">Karriere</a>
            <a href="/nyheter">Nyheter</a>
            <a href="/ledelse">Ledelse</a>
            <a href="/om-oss">Om oss</a>
            <a href="/kontakt">Kontakt</a>
            <a href="/team">Team</a>
            <a href="/pressemeldinger">Pressemeldinger</a>
            <a href="/jobbe-hos-oss">Jobbe</a>
            <a href="/siste-nytt">Siste nytt</a>
            <a href="/personvern">Personvern</a>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        links = _priority_links("https://company.no", soup, limit=7)
        self.assertEqual(len(links), 7)
        # Verify default limit is also 7
        default_links = _priority_links("https://company.no", soup)
        self.assertEqual(len(default_links), 7)

    def test_robots_ssrf_and_identity_protections_work(self):
        # 1. SSRF private IP blocked
        from norway_company_agent.website import fetch_website
        rec, _ = fetch_website("http://127.0.0.1/admin")
        self.assertEqual(rec["status"], "blocked")

        rec2, _ = fetch_website("http://169.254.169.254/latest/meta-data")
        self.assertEqual(rec2["status"], "blocked")

        # 2. Primary website identity gate still strictly rejects mismatched identity
        profile = {"organisation_number": "123456789", "name": "Real Enterprise AS"}
        website_rec = {
            "status": "available",
            "source_url": "https://completely-unrelated-entity.no",
            "value": {
                "final_url": "https://completely-unrelated-entity.no",
                "registered_domain": "completely-unrelated-entity.no",
                "title": "Random Bakery",
                "description": "Bakery goods",
                "main_text_excerpt": "We make sourdough bread only.",
            },
        }
        gated = apply_website_identity_gate(profile, website_rec)
        self.assertFalse(gated["assessment"]["publishable"])
        self.assertNotEqual(gated["assessment"]["status"], "exact")

    def test_bulk_location_and_budget_protection(self):
        # 1. profiles_from_bulk populates locations evidence
        from norway_company_agent.batch import profiles_from_bulk, terminal_envelope
        from norway_company_agent.evaluation.evidence import evaluate_company_evidence
        from pathlib import Path

        bulk_path = Path("brreg-enheter.csv") if Path("brreg-enheter.csv").exists() else None
        profiles, _ = profiles_from_bulk(bulk_path, ["985589003"])
        self.assertEqual(len(profiles), 1)
        p = profiles[0]
        self.assertIn("locations", p["evidence"])
        self.assertEqual(p["evidence"]["locations"]["status"], "available")
        self.assertEqual(p["evidence"]["locations"]["source_type"], "official_registry_bulk" if bulk_path else "official_registry_live")

        # 2. Evidence evaluation supports bulk locations claim
        ev_eval = evaluate_company_evidence(p)
        self.assertGreaterEqual(ev_eval.validity_rate, 0.9)

        # 3. Envelope terminal state for locations is complete
        env = terminal_envelope(p, run_id="test", modules=["registry", "accounting_obligation", "locations"], started_at="2026-09-26T10:00:00Z", completed_at="2026-09-26T10:01:00Z")
        self.assertEqual(env["modules"]["locations"]["state"], "complete")
        self.assertEqual(env["state"], "complete")


if __name__ == "__main__":
    unittest.main()

