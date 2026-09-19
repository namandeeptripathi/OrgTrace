from __future__ import annotations

import json
import gzip
import csv
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.evidence import evidence  # noqa: E402
from norway_company_agent.crawl_events import extract_page_event, merge_profile_events, missing_seed_error_events  # noqa: E402
from norway_company_agent.discovery import build_company_search_query, choose_search_candidate, parse_brave_web_results, score_search_candidate  # noqa: E402
from norway_company_agent.official import _reserve_history_slot, accounting_obligation_assessment, normalize_entity, normalize_financial_history, normalize_financials, normalize_roles  # noqa: E402
from norway_company_agent.operations import domain_request_summary, latency_summary, percentile  # noqa: E402
from norway_company_agent.sampling import deterministic_extension_sample, deterministic_financial_filer_sample, deterministic_website_audit_sample, financial_filer_eligible, normalize_row, stratum  # noqa: E402
from norway_company_agent.research import answer_profile, parse_screen_query, screen_profiles  # noqa: E402
from norway_company_agent.workspace import load_workspace, record_screen, save_workspace  # noqa: E402
from norway_company_agent.refresh import diff_datasets, diff_profile  # noqa: E402
from norway_company_agent.sentiment import aggregate_company_sentiment, evaluate_predictions, publishable_sentiment_item, sentiment_input_eligibility  # noqa: E402
from norway_company_agent.external_footprint import aggregate_footprint, publishable_observation, validate_observation  # noqa: E402
from norway_company_agent.external_tasks import plan_external_tasks  # noqa: E402
from norway_company_agent.external_control import development_score, run_company_control, strategy_order  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate, assess_social_identity, assess_website_identity  # noqa: E402
from norway_company_agent.identity_engine import (  # noqa: E402
    DomainMatch,
    DomainMatchCategory,
    GroupRelationship,
    GroupRelationType,
    IdentityConfidence,
    IdentityEvidence,
    IdentityVerdict,
    IdentityVerdictStatus,
    LegalNameMatch,
    LegalNameMatchCategory,
    OrgNumberValidation,
    assess_company_identity,
    canonicalize_org_number,
    classify_group_relationship,
    compute_mod11_check_digit,
    detect_ambiguity,
    extract_legal_form,
    is_valid_org_mod11,
    match_domain_entity,
    match_legal_names,
    normalize_legal_name,
    validate_org_number,
)
from norway_company_agent.website_discovery import (  # noqa: E402
    CandidateScore,
    DiscoveryVerdictStatus,
    FetchResult as DiscoveryFetchResult,
    RequestBudget,
    SafeHttpFetcher,
    SearchCandidate,
    VerificationEvidenceLevel,
    VerificationItem,
    WebsiteDiscoveryResult,
    discover_company_website,
    discover_search_candidates,
    discover_sitemap_urls,
    parse_sitemap_xml,
    score_candidate,
    verify_exact_entity,
)
from norway_company_agent.profile_extraction import (  # noqa: E402
    ExtractedCompanyProfile,
    ExtractedField,
    FieldStatus,
    extract_careers,
    extract_company_profile,
    extract_contact,
    extract_description,
    extract_employees,
    extract_industry,
    extract_leadership,
    extract_locations,
    extract_news,
)
from norway_company_agent.financial_intelligence import (  # noqa: E402
    CompanyFinancialProfile,
    FinancialAccountType,
    FinancialPdfDocument,
    FinancialReportingPeriod,
    FinancialStatement,
    build_company_financial_profile,
    extract_financial_pdfs,
    extract_financials_from_pdf,
    extract_official_accounts,
)
from norway_company_agent.website import _extraction_state, _priority_links, _social_links, assert_public_url, normalize_homepage, normalize_social_url, structured_social_links  # noqa: E402
from norway_company_agent.batch import evidence_terminal_state, profile_complete_for_modules, read_organisation_inputs, terminal_envelope, validate_envelopes  # noqa: E402
from norway_company_agent.snapshots import SnapshotFetcher  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from scripts.build_prototype import compact as compact_prototype, qualification_copy  # noqa: E402
from scripts.run_brave_discovery import brave_search  # noqa: E402
from scripts.run_annual_report_workforce_connector import extract_candidate, needs_ocr  # noqa: E402
from scripts.normalize_google_maps_results import candidate_score  # noqa: E402
from scripts.run_scrapy_websites import terminal_events_for_run  # noqa: E402
from scripts.run_sentiment_model import MODEL_REVISION, normalize_generated_label  # noqa: E402
from scripts.score_company_completeness import score_rows, summarize  # noqa: E402
from scripts.extract_company_site_activity import observation as site_activity_observation  # noqa: E402
from scripts.extract_company_site_news import observation as site_news_observation  # noqa: E402
from scripts.build_verified_observations import build as build_verified_observations  # noqa: E402
from scripts.run_google_news_rss_connector import exact_title_match  # noqa: E402
from scripts.run_linkedin_guest_jobs_connector import canonical_company_url, parse_detail_company_urls, parse_job_cards, parse_typeahead  # noqa: E402
from scripts.run_linkedin_guest_experiment import (  # noqa: E402
    assess_profile_identity as assess_linkedin_profile_identity,
    extract_profile as extract_linkedin_profile,
    legal_name_profile_url,
)
from scripts.run_fagfolkguiden_reviews_connector import extract_aggregate_rating, slug  # noqa: E402
from scripts.discover_linkedin_company_profiles import (  # noqa: E402
    discovery_identity as linkedin_discovery_identity,
    normalized_full_name as linkedin_normalized_full_name,
    official_site_aliases as linkedin_official_site_aliases,
    parse_exact_typeahead as parse_linkedin_exact_typeahead,
)


class EvidenceTests(unittest.TestCase):
    def test_missing_is_not_zero_and_provenance_is_required(self):
        record = evidence("financials", "not_found", "official_annual_accounts", "https://example.test/123")
        self.assertIsNone(record["value"])
        self.assertNotEqual(record["value"], 0)
        self.assertTrue(record["source_url"])
        self.assertTrue(record["retrieved_at"])

    def test_available_zero_is_preserved(self):
        record = evidence("employees", "available", "official_registry_bulk", "https://example.test", value=0)
        self.assertEqual(record["value"], 0)
        self.assertEqual(record["status"], "available")

    def test_content_hash_can_be_carried_with_evidence(self):
        record = evidence("entity", "available", "official", "https://example.test", value={}, content_sha256="a" * 64, source_row_key="999999999")
        self.assertEqual(record["content_sha256"], "a" * 64)
        self.assertEqual(record["source_class"], "official")
        self.assertEqual(record["source_row_key"], "999999999")

    def test_not_fetched_is_distinct_from_not_applicable(self):
        record = evidence("history", "not_fetched", "official", "https://example.test", note="No filing flag in snapshot")
        self.assertEqual(record["status"], "not_fetched")
        self.assertNotEqual(record["status"], "not_applicable")


class ExternalFootprintTests(unittest.TestCase):
    def observation(self, **changes):
        base = {
            "id": "obs-1",
            "organisation_number": "923609016",
            "platform": "google_places",
            "signal_type": "review",
            "source_url": "https://maps.google.com/example",
            "retrieved_at": "2026-08-20T00:00:00Z",
            "content_sha256": "a" * 64,
            "exact_entity": True,
            "identity_proof": [{"type": "address_match", "value": "Oslo"}],
            "acquisition_mode": "official_api",
            "rights_status": "approved",
            "source_class": "customer_review",
            "evidence_span": "Helpful staff",
        }
        return {**base, **changes}

    def test_publication_requires_rights_identity_hash_and_span(self):
        self.assertTrue(publishable_observation(self.observation()))
        bad = self.observation(exact_entity=False, content_sha256=None, evidence_span=None, rights_status="unknown")
        reasons = validate_observation(bad)
        self.assertIn("exact legal entity is not verified", reasons)
        self.assertIn("missing content hash", reasons)
        self.assertIn("missing evidence span", reasons)
        self.assertIn("source rights are not approved", reasons)

    def test_unofficial_scraper_output_is_experimental_not_publishable(self):
        item = self.observation(platform="linkedin", signal_type="job_posting", acquisition_mode="jobspy_experiment")
        self.assertFalse(publishable_observation(item))

    def test_linkedin_guest_jobs_require_exact_verified_company_url(self):
        raw = b'''<div class="base-search-card" data-entity-urn="urn:li:jobPosting:4456746433">
          <a class="base-card__full-link" href="https://no.linkedin.com/jobs/view/example-4456746433?x=1"></a>
          <span class="sr-only">Project manager</span>
          <h4 class="base-search-card__subtitle"><a href="https://no.linkedin.com/company/af-gruppen?trk=x">AF Gruppen</a></h4>
          <span class="job-search-card__location">Oslo</span><time datetime="2026-08-23"></time>
        </div>
        <div class="base-search-card" data-entity-urn="urn:li:jobPosting:4456746434">
          <a class="base-card__full-link" href="https://linkedin.com/jobs/view/other-4456746434"></a>
          <span class="sr-only">Wrong parent job</span>
          <h4 class="base-search-card__subtitle"><a href="https://linkedin.com/company/af-gruppen-sverige">AF Gruppen Sverige</a></h4>
        </div>'''
        jobs, candidates = parse_job_cards(raw, "https://linkedin.com/company/af-gruppen")
        self.assertEqual(candidates, 2)
        self.assertEqual([item["job_id"] for item in jobs], ["4456746433"])
        self.assertEqual(jobs[0]["company_url"], "https://linkedin.com/company/af-gruppen")

    def test_linkedin_company_urls_and_typeahead_are_normalized_without_claiming_ambiguous_ids(self):
        self.assertEqual(
            canonical_company_url("https://no.linkedin.com/company/Norsk-Fiskeeksport/about?trk=x"),
            "https://linkedin.com/company/norsk-fiskeeksport",
        )
        candidates = parse_typeahead(
            json.dumps([
                {"id": "34440", "type": "COMPANY", "displayName": "AF Gruppen"},
                {"id": "1188022", "type": "COMPANY", "displayName": "AF Gruppen Sverige"},
            ]).encode(),
            "AF GRUPPEN ASA",
        )
        self.assertTrue(candidates[0]["exact_legal_name_core"])
        self.assertFalse(candidates[1]["exact_legal_name_core"])
        self.assertEqual(
            parse_detail_company_urls(
                b'<a href="https://no.linkedin.com/company/af-gruppen?trk=job">AF Gruppen</a>'
                b'<a href="https://example.test/company/wrong">Wrong</a>'
            ),
            {"https://linkedin.com/company/af-gruppen"},
        )

    def test_linkedin_guest_profile_uses_structured_company_data_and_ignores_dormant_challenge_code(self):
        graph = {
            "@graph": [
                {
                    "@type": "DiscussionForumPosting",
                    "author": {"url": "https://no.linkedin.com/company/af-gruppen"},
                    "datePublished": "2026-08-21T06:15:05Z",
                    "text": "Exact company update",
                    "url": "https://no.linkedin.com/posts/example-activity-7496449781678927873-x",
                },
                {
                    "@type": "Organization",
                    "name": "AF Gruppen",
                    "url": "https://no.linkedin.com/company/af-gruppen",
                    "description": "Construction group",
                    "numberOfEmployees": {"value": 1303},
                },
            ]
        }
        raw = (
            '<meta name="description" content="AF Gruppen | 56 726 followers on LinkedIn">'
            f'<script type="application/ld+json">{json.dumps(graph)}</script>'
            '<script>const dormant="recaptcha/challengepage";</script>'
            '<div data-test-id="about-us__size"><dd>5,001-10,000 employees</dd></div>'
            '<article class="main-feed-activity-card" data-activity-urn="urn:li:activity:7496449781678927873">'
            '<a data-test-id="social-actions__reactions" data-num-reactions="29"></a>'
            '<a data-test-id="social-actions__comments" data-num-comments="4"></a></article>'
        ).encode()
        profile = extract_linkedin_profile(raw, "https://linkedin.com/company/af-gruppen")
        self.assertEqual(profile["followers"], 56726)
        self.assertEqual(profile["visible_employees"], 1303)
        self.assertEqual(profile["employee_size_label"], "5,001-10,000 employees")
        self.assertEqual(profile["posts"][0]["likes"], 29)
        self.assertEqual(profile["posts"][0]["comments"], 4)

    def test_linkedin_guest_profile_rejects_authwall_without_organization_data(self):
        with self.assertRaisesRegex(RuntimeError, "no structured organization"):
            extract_linkedin_profile(b'<script>recaptcha/challengepage</script>', "https://linkedin.com/company/example")

    def test_linkedin_stale_handle_fallback_is_bounded_to_registry_legal_name(self):
        self.assertEqual(legal_name_profile_url("DIPS AS"), "https://www.linkedin.com/company/dips-as")
        self.assertEqual(legal_name_profile_url("RØD & BLÅ AS"), "https://www.linkedin.com/company/rod-bla-as")

    def test_linkedin_discovery_requires_exact_typeahead_name_and_corroboration(self):
        raw = json.dumps([
            {"id": "1", "type": "COMPANY", "displayName": "DIPS AS"},
            {"id": "2", "type": "COMPANY", "displayName": "DIPS ASA"},
        ]).encode()
        self.assertEqual([item["linkedin_company_id"] for item in parse_linkedin_exact_typeahead(raw, "DIPS AS")], ["1"])
        self.assertEqual(linkedin_normalized_full_name("RØD & BLÅ AS"), "rød blå as")
        company = {
            "name": "DIPS AS",
            "municipality": "BODØ",
            "website": "https://dips.com",
            "evidence": {"website": {"status": "available", "value": {"final_url": "https://dips.com"}}},
        }
        exact = linkedin_discovery_identity(company, {"name": "DIPS AS", "website": "https://www.dips.com", "headquarters": "Bodø"}, {"legal_name_slug"})
        self.assertTrue(exact["exact_entity"])
        weak = linkedin_discovery_identity(company, {"name": "DIPS AS", "website": "https://unrelated.test", "headquarters": "Oslo"}, {"legal_name_slug"})
        self.assertFalse(weak["exact_entity"])

    def test_linkedin_fuzzy_discovery_uses_verified_site_alias_and_reverse_domain(self):
        company = {
            "name": "JARRE AS",
            "municipality": "INDRE ØSTFOLD",
            "website": "https://jarre.co",
            "evidence": {
                "website": {"status": "available", "value": {"final_url": "https://jarre.co", "title": "Jarre&Co"}},
                "roles": {"value": {"roles": [{"name": "Christian Jarre", "role_code": "DAGL"}]}},
            },
        }
        self.assertEqual(linkedin_official_site_aliases(company), ["Jarre&Co"])
        exact = linkedin_discovery_identity(
            company,
            {"name": "Jarre & Co", "website": "https://www.jarre.co", "headquarters": "Askim", "description": ""},
            {"official_site_alias:Jarre&Co"},
        )
        self.assertTrue(exact["exact_entity"])

    def test_linkedin_profile_identity_accepts_redirect_alias_only_with_name_or_reverse_domain_proof(self):
        profile = {
            "name": "ZAPTEC ASA",
            "website": "https://zaptec.com",
            "evidence": {"website": {"source_url": "https://www.zaptec.com/", "value": {"final_url": "https://www.zaptec.com/"}}},
        }
        accepted = assess_linkedin_profile_identity(
            profile,
            "https://linkedin.com/company/gozaptec",
            {"name": "Zaptec", "page_url": "https://linkedin.com/company/zaptec", "website": "https://www.zaptec.com"},
        )
        self.assertTrue(accepted["publishable_candidate"])
        rejected = assess_linkedin_profile_identity(
            profile,
            "https://linkedin.com/company/gozaptec",
            {"name": "Unrelated Parent", "page_url": "https://linkedin.com/company/unrelated", "website": "https://parent.test"},
        )
        self.assertFalse(rejected["publishable_candidate"])

    def test_google_play_observation_is_supported_but_unofficial_output_stays_experimental(self):
        item = self.observation(
            platform="google_play",
            signal_type="review_summary",
            acquisition_mode="unofficial_api_experiment",
            rights_status="review_required",
        )
        reasons = validate_observation(item)
        self.assertNotIn("unsupported platform", reasons)
        self.assertFalse(publishable_observation(item))

    def test_company_directory_is_not_a_website_discovery_candidate(self):
        profile = {"name": "OBLOMOV AS", "organisation_number": "991167315", "municipality": "SOLA"}
        result = {"url": "https://www.northdata.com/Oblomov-AS/BR-991167315", "title": "Oblomov AS", "snippet": "991167315", "rank": 1}
        assessment = score_search_candidate(profile, result)
        self.assertFalse(assessment["publishable_candidate"])
        self.assertEqual(assessment["status"], "rejected")

    def test_unknown_company_directory_with_org_number_is_not_a_candidate(self):
        profile = {"name": "AKSLA AS", "organisation_number": "923304290", "municipality": "ÅLESUND"}
        result = {"url": "https://vexter.no/selskap/aksla-as/923304290", "title": "AKSLA AS", "snippet": "923304290", "rank": 1}
        self.assertFalse(score_search_candidate(profile, result)["publishable_candidate"])

    def test_annual_workforce_parser_does_not_treat_norwegian_o_as_zero(self):
        heading = "Note 2 - Lonnskostnader, antall ansatte og lan til ansatte"
        self.assertEqual(extract_candidate(heading), (None, None, "no_employee_phrase", None))
        count, span, status, measure = extract_candidate("Det er to ansatte i sameiet.")
        self.assertEqual((count, status, measure), (2, "accepted", "employees"))
        self.assertEqual(span, "Det er to ansatte i sameiet.")
        self.assertEqual(extract_candidate("Selskapet har 1 2025 sysselsatt 2 arsverk.")[0], 2)
        self.assertEqual(extract_candidate("Antall arsverk syssetsatt i regnskapsaret: 3")[0], 3)
        self.assertEqual(extract_candidate("Stiftelsen har ingen ansatte og ingen arsverk.")[0], 0)
        self.assertEqual(extract_candidate("Selskapet hadde ingen ansatte i 2025.")[0], 0)
        self.assertEqual(extract_candidate("Gjennomsnittlig antall ansatte i regnskapsaret: 0")[0], 0)
        self.assertEqual(extract_candidate("Note Antall Aarsverk i regnskapsaret 0.00")[0], 0)
        self.assertEqual(extract_candidate("Tal pa Aarsverk i rekneskapsaret 1.50")[0], 1.5)
        self.assertTrue(needs_ocr("Digital cover text without the employee note"))
        self.assertFalse(needs_ocr("Selskapet har 2 ansatte. " + "Digital report text. " * 8))

    def test_aggregate_keeps_source_metrics_separate_and_abstains_on_thin_sentiment(self):
        items = [
            self.observation(id="a", sentiment_label="positive", sentiment_model_version="m1"),
            self.observation(id="b", platform="youtube", signal_type="profile_metrics", source_url="https://youtube.com/@example", evidence_span=None),
        ]
        result = aggregate_footprint(items, as_of="2026-08-22T00:00:00Z")
        self.assertEqual(result["accepted_observations"], 2)
        self.assertEqual(result["sentiment"]["status"], "abstain")
        self.assertNotIn("popularity_score", result)

    def test_customer_review_sentiment_accepts_ten_independent_reviewers_on_one_platform(self):
        items = [
            self.observation(
                id=f"review-{index}",
                sentiment_label="positive",
                sentiment_model_version="explicit_star_rating_v1",
                reviewer_id=f"reviewer-{index}",
            )
            for index in range(10)
        ]
        result = aggregate_footprint(items, as_of="2026-08-22T00:00:00Z")
        self.assertEqual(result["sentiment"]["status"], "available")
        self.assertEqual(result["sentiment"]["independent_reviewers"], 10)

    def test_google_maps_identity_gate_rejects_neighbor_and_accepts_exact_address(self):
        profile = {
            "organisation_number": "938702675",
            "name": "AF GRUPPEN ASA",
            "evidence": {
                "registry": {"value": {
                    "forretningsadresse.adresse": "Standardveien 1",
                    "forretningsadresse.postnummer": "0581",
                    "telefon": "22 89 11 00",
                }},
                "website": {"value": {
                    "final_url": "https://afgruppen.no/",
                    "identity_assessment": {"publishable": True},
                }},
            },
        }
        exact = candidate_score(profile, {
            "title": "AF Gruppen", "address": "Standardveien 1, 0581 Oslo, Norge",
            "phone": "+47 22 89 11 00", "web_site": "https://afgruppen.no/", "review_count": 21,
        })
        neighbor = candidate_score(profile, {
            "title": "AF Eiendom", "address": "Standardveien 1, 0581 Oslo, Norge",
            "phone": "+47 22 89 11 00", "web_site": "https://afgruppen.no/eiendom/", "review_count": 0,
        })
        self.assertTrue(exact["accepted"])
        self.assertFalse(neighbor["accepted"])

    def test_google_maps_exact_name_and_postcode_city_can_resolve_operating_address(self):
        profile = {
            "organisation_number": "999999999",
            "name": "EXAMPLE INDUSTRI AS",
            "evidence": {"registry": {"value": {
                "forretningsadresse.adresse": "c/o Accountant Other Street 1",
                "forretningsadresse.postnummer": "4021",
                "forretningsadresse.poststed": "STAVANGER",
            }}},
        }
        result = candidate_score(profile, {
            "title": "Example Industri AS", "address": "Factory Road 7, 4021 Stavanger, Norway",
            "phone": "", "web_site": "", "review_count": 4,
        })
        self.assertTrue(result["accepted"])
        self.assertTrue(result["postcode_city_match"])

    def test_google_maps_trade_name_requires_exact_address_phone_and_no_partial_name_collision(self):
        profile = {
            "name": "OSLOFJORDEN EIENDOMSMEGLING AS",
            "evidence": {"registry": {"value": {
                "forretningsadresse.adresse": "Stranden 81", "forretningsadresse.postnummer": "0250",
                "forretningsadresse.poststed": "Oslo", "telefon": "22620000",
            }}},
        }
        candidate = {"title": "PrivatMegleren Premium", "address": "Stranden 81, 0250 Oslo", "phone": "+47 22 62 00 00"}
        result = candidate_score(profile, candidate)
        self.assertFalse(result["trade_name_match"])
        self.assertFalse(result["accepted"])
        profile["organisation_number"] = "932083108"
        result = candidate_score(profile, candidate)
        self.assertTrue(result["trade_name_match"])
        self.assertTrue(result["accepted"])
        candidate["phone"] = "+47 99 99 99 99"
        self.assertFalse(candidate_score(profile, candidate)["accepted"])

    def test_experimental_maps_signals_raise_only_experimental_places_score(self):
        profile = {
            "organisation_number": "938702675",
            "name": "AF GRUPPEN ASA",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": False}}}},
        }
        common = {
            "organisation_number": "938702675",
            "platform": "google_places",
            "source_url": "https://www.google.com/maps/place/example",
            "retrieved_at": "2026-08-22T00:00:00Z",
            "content_sha256": "a" * 64,
            "exact_entity": True,
            "identity_proof": [{"type": "registry_address_match", "value": True}],
            "acquisition_mode": "unofficial_api_experiment",
            "rights_status": "review_required",
            "source_class": "public_business_listing",
            "evidence_span": "AF Gruppen; Standardveien 1; rating=2.5; reviews=21",
        }
        observations = [
            {**common, "id": "place", "signal_type": "place_summary", "strategy": "places_identity_resolution"},
            {**common, "id": "summary", "signal_type": "review_summary", "strategy": "places_rating_reviews"},
        ]
        score = development_score(profile, observations)
        self.assertEqual(score["score"], 0.0)
        self.assertEqual(score["experimental_potential_score"], 35.0)

    def test_aggregate_maps_rating_is_experimental_sentiment_and_buzz(self):
        profile = {
            "organisation_number": "938702675",
            "name": "AF GRUPPEN ASA",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": False}}}},
        }
        common = {
            "organisation_number": "938702675",
            "platform": "google_places",
            "source_url": "https://www.google.com/maps/place/example",
            "retrieved_at": "2026-08-22T00:00:00Z",
            "content_sha256": "a" * 64,
            "exact_entity": True,
            "identity_proof": [{"type": "registry_address_match", "value": True}],
            "acquisition_mode": "unofficial_api_experiment",
            "rights_status": "review_required",
            "evidence_span": "AF Gruppen; rating=4.4; reviews=21",
            "metrics": {"rating": 4.4, "rating_scale": 5, "review_count": 21},
        }
        observations = [
            {**common, "id": "summary", "signal_type": "review_summary", "strategy": "places_rating_reviews"},
            {**common, "id": "buzz", "signal_type": "buzz_metrics", "strategy": "buzz_peer_normalization"},
        ]
        score = development_score(profile, observations)
        self.assertEqual(score["score"], 0.0)
        self.assertEqual(score["experimental_sentiment_status"], "available")
        self.assertEqual(score["experimental_potential_score"], 35.0)

    def test_task_planner_uses_verified_handles_and_adds_core_connectors(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {
                "website": {"value": {"social_links": [{"platform": "youtube", "url": "https://youtube.com/@example"}]}},
            },
        }
        tasks = plan_external_tasks(profile)
        connectors = {item["connector"] for item in tasks}
        self.assertIn("google_places_api", connectors)
        self.assertIn("jobs_provider", connectors)
        self.assertIn("youtube_connector", connectors)
        self.assertNotIn("permitted_search_api", connectors)

    def test_controller_recomputes_sentiment_and_records_marginal_gain(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": True}}}},
        }
        handle = self.observation(signal_type="profile_handle", source_class="company_social", evidence_span=None, strategy="verified_handle_extraction")
        score = development_score(profile, [handle])
        self.assertGreater(score["score"], 0)
        self.assertEqual(score["sentiment_status"], "abstain")
        result = run_company_control(profile, [handle], minimum_iterations=10, maximum_iterations=15)
        self.assertGreaterEqual(result["iterations_run"], 10)
        self.assertTrue(any(item["score_delta"] > 0 for item in result["iterations"]))
        self.assertTrue(all("sentiment_status" in item for item in result["iterations"]))

    def test_controller_final_score_is_not_path_dependent_after_target_is_reached(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": True}}}},
        }
        observations = [
            self.observation(signal_type="profile_handle", source_class="company_social", evidence_span=None, strategy="verified_handle_extraction"),
            self.observation(id="metric", platform="youtube", signal_type="profile_metrics", source_url="https://youtube.com/@example", evidence_span=None, strategy="social_profile_metrics"),
        ]
        result = run_company_control(profile, observations, target=20, minimum_iterations=1)
        self.assertEqual(result["iterations_run"], len(strategy_order([])))
        self.assertEqual(result["final"], development_score(profile, observations))

    def test_exact_wikidata_org_profile_can_supply_external_identity(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Example AS",
            "evidence": {"website": {"value": {"identity_assessment": {"publishable": False}}}},
        }
        wikidata = self.observation(
            platform="wikidata",
            signal_type="company_profile",
            source_url="https://www.wikidata.org/wiki/Q123",
            evidence_span="Q123: P2333=923609016",
            source_class="open_knowledge_graph",
            strategy="company_site_identity",
        )
        score = development_score(profile, [wikidata])
        self.assertEqual(score["components"]["exact_external_identity"], 20.0)
        self.assertTrue(publishable_observation(wikidata))

    def test_controller_replicates_prior_winning_strategy_first(self):
        prior = [
            {"strategy": "youtube_channel_feed", "learning_gain": 8.0},
            {"strategy": "verified_handle_extraction", "learning_gain": 2.0},
        ]
        self.assertEqual(strategy_order(prior)[0], "youtube_channel_feed")
        profile = {"organisation_number": "923609016", "name": "Example AS", "evidence": {"website": {"value": {"identity_assessment": {"publishable": True}}}}}
        result = run_company_control(profile, [], prior_iterations=prior, minimum_iterations=1, maximum_iterations=2)
        self.assertEqual(result["iterations"][0]["strategy"], "youtube_channel_feed")
        self.assertEqual(result["iterations"][0]["controller_action"], "replicate")


class CompletenessScoreTests(unittest.TestCase):
    def test_all_source_weights_sum_to_one_hundred(self):
        from scripts.score_company_completeness import ENRICHMENT_WEIGHTS, FOUNDATION_WEIGHTS

        self.assertEqual(sum(FOUNDATION_WEIGHTS.values()) + sum(ENRICHMENT_WEIGHTS.values()), 100.0)

    def test_all_source_score_combines_foundation_and_external_without_imputing_missing(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {
                "registry_live": {"status": "available", "value": {"organisation_number": "923609016"}},
                "financials": {"status": "available"},
                "roles": {"status": "available"},
                "locations": {"status": "available"},
                "website": {"status": "not_found"},
            },
        }
        components = {
            "exact_external_identity": 20,
            "verified_handles": 15,
            "profile_metrics": 10,
            "places_identity": 5,
            "places_reviews": 10,
            "workforce_jobs": 10,
            "public_buzz": 10,
            "independent_sentiment": 0,
            "freshness_evidence": 5,
        }
        result = {"organisation_number": "923609016", "company_name": "Example AS", "final": {"components": components, "experimental_components": components}}
        scored = score_rows([profile], [result])
        self.assertEqual(scored[0]["foundation_score"], 30.0)
        self.assertEqual(scored[0]["strict_enrichment"]["independent_sentiment"], 0.0)
        self.assertEqual(scored[0]["strict_completeness_score"], 88.0)
        self.assertEqual(summarize(scored)["companies"], 1)

    def test_site_activity_requires_exact_identity_and_preserves_snapshot_provenance(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {"website": {
                "status": "available",
                "source_url": "https://example.test/",
                "retrieved_at": "2026-08-23T00:00:00Z",
                "value": {
                    "final_url": "https://example.test/",
                    "content_sha256": "a" * 64,
                    "identity_assessment": {"publishable": True, "status": "exact", "score": 1.0},
                    "pages": [{"url": "https://example.test/"}],
                },
            }},
        }
        item = site_activity_observation(profile)
        self.assertIsNotNone(item)
        self.assertEqual(item["strategy"], "company_site_activity")
        self.assertTrue(publishable_observation(item))
        profile["evidence"]["website"]["value"]["identity_assessment"]["publishable"] = False
        self.assertIsNone(site_activity_observation(profile))

    def test_news_title_gate_requires_the_full_legal_name_core(self):
        self.assertTrue(exact_title_match("NORDIC DOOR AS", "Nordic Door AS åpner ny fabrikk - Lokalavisa"))
        self.assertFalse(exact_title_match("NORDIC DOOR AS", "Nordic investors prefer another door - Example"))
        self.assertTrue(exact_title_match("SOLVANG ASA", "Sterkt årsresultat fra Solvang ASA i 2024 - Skipsrevyen"))
        self.assertFalse(exact_title_match("VIND HOLDING AS", "Inntektene til Aneo Roan Vind Holding AS stupte - mn24.no"))
        self.assertFalse(exact_title_match("CONSTO AS", "Drastisk fall hos Consto Bergen AS - BT"))

    def test_site_news_requires_exact_identity_and_a_captured_news_path(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {"website": {
                "status": "available", "retrieved_at": "2026-08-23T00:00:00Z",
                "value": {
                    "identity_assessment": {"publishable": True, "score": 1.0},
                    "pages": [{"url": "https://example.test/aktuelt/new-contract", "title": "New contract", "content_sha256": "a" * 64}],
                },
            }},
        }
        item = site_news_observation(profile)
        self.assertEqual(item["signal_type"], "public_post")
        self.assertTrue(publishable_observation(item))
        profile["evidence"]["website"]["value"]["pages"][0]["url"] = "https://example.test/contact"
        self.assertIsNone(site_news_observation(profile))

    def test_verified_observations_require_known_org_and_snapshot_hash(self):
        profiles = [{"organisation_number": "923609016", "name": "Example AS"}]
        seed = {"organisation_number": "923609016", "platform": "news", "signal_type": "public_mention", "source_url": "https://example.test/news", "content_sha256": "a" * 64, "evidence_span": "Example AS", "proof": "Exact legal name"}
        self.assertTrue(build_verified_observations([seed], profiles)[0]["exact_entity"])
        seed["content_sha256"] = "bad"
        with self.assertRaises(ValueError):
            build_verified_observations([seed], profiles)

    def test_directory_identity_is_experimental_and_never_becomes_strict(self):
        item = {
            "id": "directory-1", "organisation_number": "923609016", "platform": "company_directory",
            "signal_type": "company_profile", "source_url": "https://example.test/923609016",
            "retrieved_at": "2026-08-23T00:00:00Z", "content_sha256": "a" * 64,
            "exact_entity": True, "identity_proof": [{"type": "organisation_number", "value": "923609016"}],
            "acquisition_mode": "rights_review_experiment", "rights_status": "review_required",
            "source_class": "public_company_directory", "strategy": "company_directory_identity",
        }
        profile = {"organisation_number": "923609016", "name": "Example AS", "evidence": {}}
        score = development_score(profile, [item])
        self.assertEqual(score["components"]["exact_external_identity"], 0.0)
        self.assertEqual(score["experimental_components"]["exact_external_identity"], 20.0)
        self.assertFalse(publishable_observation(item))

    def test_fagfolk_rating_parser_uses_jsonld_and_slug_is_stable(self):
        raw = b'<script type="application/ld+json">{"aggregateRating":{"ratingValue":4.4,"ratingCount":25}}</script>'
        self.assertEqual(extract_aggregate_rating(raw)[:2], (4.4, 25))
        self.assertEqual(slug("NORDIC DØR AS"), "nordic-dor-as")


class SamplingTests(unittest.TestCase):
    def test_financial_filer_sample_requires_current_active_rows_and_preserves_overlap(self):
        fields = ["organisasjonsnummer", "navn", "organisasjonsform.kode", "sisteInnsendteAarsregnskap", "konkurs", "underAvvikling"]
        rows = [
            {"organisasjonsnummer": str(200000000 + index), "navn": f"Company {index}", "organisasjonsform.kode": "AS", "sisteInnsendteAarsregnskap": "2025", "konkurs": "false", "underAvvikling": "false"}
            for index in range(12)
        ] + [
            {"organisasjonsnummer": "300000001", "navn": "Stale AS", "organisasjonsform.kode": "AS", "sisteInnsendteAarsregnskap": "2024", "konkurs": "false", "underAvvikling": "false"},
            {"organisasjonsnummer": "300000002", "navn": "Bankrupt AS", "organisasjonsform.kode": "AS", "sisteInnsendteAarsregnskap": "2025", "konkurs": "true", "underAvvikling": "false"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            selected, metadata = deterministic_financial_filer_sample(path, 5, latest_year="2025", preserved_organisation_numbers={"200000003"}, seed=7)
            repeated, _ = deterministic_financial_filer_sample(path, 5, latest_year="2025", preserved_organisation_numbers={"200000003"}, seed=7)
        self.assertEqual([row["organisation_number"] for row in selected], [row["organisation_number"] for row in repeated])
        self.assertIn("200000003", {row["organisation_number"] for row in selected})
        self.assertNotIn("300000001", {row["organisation_number"] for row in selected})
        self.assertNotIn("300000002", {row["organisation_number"] for row in selected})
        self.assertEqual(metadata["eligible_rows"], 12)
        self.assertEqual(metadata["preserved_eligible_selected"], 1)
        self.assertTrue(all(financial_filer_eligible(row, "2025") for row in selected))

    def test_extension_sample_is_deterministic_and_excludes_initial(self):
        fields = ["organisasjonsnummer", "navn", "hjemmeside", "organisasjonsform.kode"]
        rows = [
            {"organisasjonsnummer": str(100000000 + index), "navn": f"Company {index}", "hjemmeside": "", "organisasjonsform.kode": "AS"}
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            first, metadata = deterministic_extension_sample(path, 5, {"100000000", "100000001"}, seed=3)
            second, _ = deterministic_extension_sample(path, 5, {"100000000", "100000001"}, seed=3)
        self.assertEqual([item["organisation_number"] for item in first], [item["organisation_number"] for item in second])
        self.assertEqual(len(first), 5)
        self.assertEqual(metadata["overlap_with_excluded"], 0)

    def test_strata_distinguish_adverse_and_web_coverage(self):
        base = {"legal_form": "AS", "employees": 12, "bankrupt": False, "liquidating": False, "website": "example.no"}
        self.assertEqual(stratum(base), "AS|5-19|active|web")
        self.assertEqual(stratum({**base, "bankrupt": True, "website": ""}), "AS|5-19|adverse|no-web")

    def test_normalize_does_not_invent_employee_count(self):
        row = normalize_row({"organisasjonsnummer": "923609016", "navn": "Example AS", "antallAnsatte": ""})
        self.assertIsNone(row["employees"])
        self.assertEqual(row["latest_submitted_accounts"], "")

    def test_fresh_website_audit_sample_excludes_poc_and_deduplicates_hosts(self):
        fields = ["organisasjonsnummer", "navn", "hjemmeside", "organisasjonsform.kode"]
        rows = [
            {"organisasjonsnummer": "111111111", "navn": "Excluded AS", "hjemmeside": "excluded.no", "organisasjonsform.kode": "AS"},
            {"organisasjonsnummer": "222222222", "navn": "A AS", "hjemmeside": "https://www.shared.no/a", "organisasjonsform.kode": "AS"},
            {"organisasjonsnummer": "333333333", "navn": "B AS", "hjemmeside": "shared.no/b", "organisasjonsform.kode": "AS"},
            {"organisasjonsnummer": "444444444", "navn": "C AS", "hjemmeside": "unique.no", "organisasjonsform.kode": "AS"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            selected, metadata = deterministic_website_audit_sample(path, 1, {"111111111"}, {"shared.no"}, seed=9)
        self.assertEqual(len(selected), 1)
        self.assertNotIn("111111111", {row["organisation_number"] for row in selected})
        self.assertEqual(selected[0]["organisation_number"], "444444444")
        self.assertEqual(metadata["unique_hosts_selected"], 1)
        self.assertEqual(metadata["excluded_website_hosts"], 1)


class OperationsTests(unittest.TestCase):
    def test_history_rate_limiter_spaces_request_starts_not_responses(self):
        import norway_company_agent.official as official

        old = official._history_last_request
        now = [10.0]
        sleeps = []

        def clock():
            return now[0]

        def sleeper(delay):
            sleeps.append(delay)
            now[0] += delay

        try:
            official._history_last_request = 9.0
            _reserve_history_slot(clock, sleeper)
            self.assertAlmostEqual(sleeps[0], 1.1)
            self.assertAlmostEqual(official._history_last_request, 11.1)
            now[0] = 13.3
            _reserve_history_slot(clock, sleeper)
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(official._history_last_request, 13.3)
        finally:
            official._history_last_request = old

    def test_batch_input_preserves_split_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orgs.jsonl"
            path.write_text(json.dumps({"organisation_number": "923609016", "evaluation_split": "held_out", "sample_slice": "stress", "ignored": "x"}) + "\n", encoding="utf-8")
            self.assertEqual(read_organisation_inputs(path), [{"organisation_number": "923609016", "evaluation_split": "held_out", "sample_slice": "stress"}])

    def test_batch_contract_emits_exact_terminal_envelopes(self):
        profile = {
            "organisation_number": "923609016",
            "evidence": {
                "registry": evidence("registry", "available", "official", "https://example.test", content_sha256="a" * 64),
                "website": evidence("website", "blocked", "company_site", "https://example.test", note="robots.txt denied"),
            },
        }
        envelope = terminal_envelope(profile, run_id="day-1", modules=["registry", "website"], started_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T00:01:00Z")
        self.assertEqual(envelope["modules"]["registry"]["state"], "complete")
        self.assertEqual(envelope["modules"]["website"]["state"], "blocked_robots")
        self.assertTrue(validate_envelopes([envelope], 1)["passed"])
        self.assertFalse(validate_envelopes([envelope], 2)["passed"])

    def test_unknown_evidence_state_is_submission_error(self):
        self.assertEqual(evidence_terminal_state({"status": "not_fetched"}), "submission_error")

    def test_batch_resume_only_skips_profiles_with_all_terminal_modules(self):
        complete = {"evidence": {"registry": {"status": "available"}, "website": {"status": "not_found"}}}
        partial = {"evidence": {"registry": {"status": "available"}, "website": {"status": "not_fetched"}}}
        self.assertTrue(profile_complete_for_modules(complete, ["registry", "website"]))
        self.assertFalse(profile_complete_for_modules(partial, ["registry", "website"]))

    def test_nearest_rank_percentiles_are_deterministic(self):
        self.assertEqual(percentile([1, 2, 3, 4, 100], 0.5), 3)
        self.assertEqual(percentile([1, 2, 3, 4, 100], 0.95), 100)
        self.assertEqual(latency_summary([1, 2, 3]), {"n": 3, "p50_ms": 2.0, "p95_ms": 3.0, "max_ms": 3.0})

    def test_domain_fairness_summary_preserves_tail(self):
        result = domain_request_summary(__import__("collections").Counter({"a.no": 1, "b.no": 2, "c.no": 9}))
        self.assertEqual(result["domains"], 3)
        self.assertEqual(result["p50_requests"], 2.0)
        self.assertEqual(result["max_requests"], 9)


class WebsiteTests(unittest.TestCase):
    def test_interrupted_run_does_not_synthesize_terminal_failures(self):
        profiles = [{"organisation_number": "1", "website": "pending.no"}]
        self.assertEqual(terminal_events_for_run(profiles, [], False), [])
        self.assertEqual(len(terminal_events_for_run(profiles, [], True)), 1)

    def test_missing_seed_gets_explicit_terminal_event(self):
        profiles = [
            {"organisation_number": "1", "website": "example.no"},
            {"organisation_number": "2", "website": "blocked.no"},
            {"organisation_number": "3", "website": ""},
        ]
        existing = [{"organisation_number": "1", "status": "available"}]
        missing = missing_seed_error_events(profiles, existing)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["organisation_number"], "2")
        self.assertEqual(missing[0]["status"], "source_error")
        self.assertIn("robots.txt", missing[0]["error"])

    def test_crawl_event_extraction_and_merge_preserve_page_hashes(self):
        homepage = extract_page_event(
            organisation_number="923609016",
            requested_url="https://example.no/",
            final_url="https://example.no/",
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=b'<html><head><title>Example AS</title><meta name="description" content="Company"></head><body><p>Example AS provides enough substantive company information for extraction and identity review.</p><a href="https://linkedin.com/company/example">LinkedIn</a></body></html>',
            page_kind="homepage",
            retrieved_at="2026-08-22T00:00:00Z",
        )
        secondary = extract_page_event(
            organisation_number="923609016",
            requested_url="https://example.no/contact",
            final_url="https://example.no/contact",
            status_code=200,
            content_type="text/html",
            body=b"<html><title>Contact</title><body>Contact Example AS in Oslo.</body></html>",
            page_kind="priority",
            retrieved_at="2026-08-22T00:00:01Z",
        )
        record = merge_profile_events({"website": "https://example.no"}, [homepage, secondary])
        self.assertEqual(record["status"], "available")
        self.assertEqual(len(record["value"]["pages"]), 2)
        self.assertEqual(record["content_sha256"], homepage["content_sha256"])
        self.assertEqual(record["value"]["scheduler"], "scrapy_resumable_v1")

    def test_footer_identity_is_preserved_for_exact_company_gate(self):
        event = extract_page_event(
            organisation_number="985628572",
            requested_url="https://netsolution.no/",
            final_url="https://netsolution.no/",
            status_code=200,
            content_type="text/html",
            body=(
                b'<html><head><title>IT services</title></head><body><main>Useful services for customers.</main>'
                b'<footer>Netsolution Viken AS, Kobbervikdalen 75 A, 3036 Drammen</footer></body></html>'
            ),
            page_kind="homepage",
            retrieved_at="2026-08-23T00:00:00Z",
        )
        website = merge_profile_events({"website": "https://netsolution.no/"}, [event])
        profile = {
            "organisation_number": "985628572",
            "name": "NETSOLUTION VIKEN AS",
            "evidence": {"website": website},
        }
        self.assertIn("Netsolution Viken AS", website["value"]["identity_text_excerpt"])
        self.assertTrue(assess_website_identity(profile)["publishable"])

    def test_normalizes_registry_hostname(self):
        self.assertEqual(normalize_homepage("example.no"), "https://example.no/")
        self.assertEqual(normalize_homepage("http://example.no"), "http://example.no/")

    def test_only_extracts_declared_social_links(self):
        soup = BeautifulSoup('<a href="https://www.linkedin.com/company/example/">LinkedIn</a><a href="/about">About</a>', "html.parser")
        self.assertEqual(_social_links("https://example.no", soup), [{"platform": "linkedin", "url": "https://linkedin.com/company/example"}])

    def test_extracts_embedded_company_social_profiles(self):
        soup = BeautifulSoup(
            '<div class="fb-page" data-href="https://www.facebook.com/ExampleCompany"></div>'
            '<iframe src="https://www.facebook.com/plugins/page.php?href=https%3A%2F%2Fwww.facebook.com%2FSecondCompany"></iframe>',
            "html.parser",
        )
        self.assertEqual(
            _social_links("https://example.no/", soup),
            [
                {"platform": "facebook", "url": "https://facebook.com/ExampleCompany"},
                {"platform": "facebook", "url": "https://facebook.com/SecondCompany"},
            ],
        )

    def test_extracts_schema_same_as_company_social_profiles(self):
        value = [{
            "@type": "Organization",
            "sameAs": [
                "https://www.facebook.com/ExampleCompany/",
                "https://instagram.com/examplecompany",
                "https://linkedin.com/in/example-person",
            ],
        }]
        self.assertEqual(
            structured_social_links(value),
            [
                {"platform": "facebook", "url": "https://facebook.com/ExampleCompany"},
                {"platform": "instagram", "url": "https://instagram.com/examplecompany"},
            ],
        )

    def test_social_profiles_reject_share_event_group_and_policy_links(self):
        rejected = (
            "https://facebook.com/sharer.php?u=x", "https://facebook.com/events/123",
            "https://facebook.com/groups/123", "https://facebook.com/policy.php",
            "https://facebook.com/privacy/explanation",
            "https://linkedin.com/shareArticle?url=x", "https://instagram.com/p/abc",
        )
        self.assertTrue(all(normalize_social_url(url) is None for url in rejected))

    def test_social_profiles_canonicalize_www_variants(self):
        self.assertEqual(normalize_social_url("https://www.facebook.com/Example/"), {"platform": "facebook", "url": "https://facebook.com/Example"})
        self.assertEqual(normalize_social_url("https://linkedin.com/company/example/admin/feed/posts"), {"platform": "linkedin", "url": "https://linkedin.com/company/example"})
        self.assertEqual(normalize_social_url("https://youtube.com/channel/abc/featured"), {"platform": "youtube", "url": "https://youtube.com/channel/abc"})
        self.assertIsNone(normalize_social_url("https://facebook.com/profile.php"))
        self.assertIsNone(normalize_social_url("https://[object Object]"))

    def test_priority_pages_stay_on_exact_site(self):
        soup = BeautifulSoup('<a href="/kontakt">Contact</a><a href="https://other.no/about">About</a><a href="/products">Products</a>', "html.parser")
        self.assertEqual(_priority_links("https://example.no/", soup), ["https://example.no/kontakt"])

    def test_js_shell_is_only_a_fallback_candidate(self):
        shell = BeautifulSoup('<html><script src="a.js"></script><script src="b.js"></script></html>', "html.parser")
        self.assertEqual(_extraction_state("", shell), "js_fallback_candidate")
        self.assertEqual(_extraction_state("A" * 100, shell), "static_complete")

    def test_blocks_local_network_targets(self):
        for url in ("http://127.0.0.1/admin", "http://localhost/", "http://169.254.169.254/latest/meta-data"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                assert_public_url(url)


class DiscoveryTests(unittest.TestCase):
    def test_brave_request_keeps_key_out_of_url_and_parses_in_memory(self):
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"web": {"results": [{
                    "url": "https://example.no", "title": "Example AS", "description": "Example in Oslo",
                }]}}).encode()

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("X-subscription-token")
            captured["timeout"] = timeout
            return Response()

        with patch("scripts.run_brave_discovery.urllib.request.urlopen", fake_open):
            results, operation = brave_search({
                "name": "Example AS", "organisation_number": "999999999", "municipality": "OSLO",
            }, "secret-test-key", timeout=3.0, count=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(operation["status"], 200)
        self.assertNotIn("secret-test-key", captured["url"])
        self.assertEqual(captured["key"], "secret-test-key")
        self.assertEqual(captured["timeout"], 3.0)

    def test_company_query_contains_exact_name_org_and_location(self):
        query = build_company_search_query({
            "name": "Norsk Fiskeeksport AS", "organisation_number": "923 609 016", "municipality": "NOTODDEN",
        })
        self.assertEqual(query, '"Norsk Fiskeeksport AS" 923609016 NOTODDEN')

    def test_brave_parser_is_provider_neutral_candidate_input(self):
        results = parse_brave_web_results({"web": {"results": [
            {"url": "https://example.no", "title": "Example AS", "description": "Example in Oslo"},
            {"title": "Missing URL"},
        ]}}, query='"Example AS" 999999999')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "brave_search_api")
        self.assertEqual(results[0]["rank"], 1)

    def test_directory_and_social_results_are_not_company_site_candidates(self):
        profile = {"organisation_number": "923609016", "name": "Example Norge AS", "municipality": "OSLO"}
        for url in ("https://proff.no/selskap/example", "https://linkedin.com/company/example"):
            with self.subTest(url=url):
                self.assertEqual(score_search_candidate(profile, {"url": url, "title": "Example Norge AS"})["status"], "rejected")

    def test_exact_name_in_title_and_host_is_only_a_crawl_candidate(self):
        profile = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "municipality": "NOTODDEN"}
        decision = choose_search_candidate(profile, [{
            "url": "https://norskfiskeeksport.no/",
            "title": "Norsk Fiskeeksport AS",
            "snippet": "Seafood exporter in Notodden",
            "rank": 1,
            "provider": "fixture",
        }])
        self.assertFalse(decision["abstained"])
        self.assertEqual(decision["selected"]["status"], "accepted_for_crawl")
        self.assertIn("Publication still requires", decision["policy"])

    def test_ambiguous_name_match_without_host_support_abstains(self):
        profile = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "municipality": "NOTODDEN"}
        decision = choose_search_candidate(profile, [{"url": "https://parent-group.no/", "title": "Norsk Fiskeeksport AS - portfolio", "snippet": "Group companies"}])
        self.assertTrue(decision["abstained"])


class SentimentTests(unittest.TestCase):
    @staticmethod
    def item(item_id, label="positive", source="https://news.example/a", **changes):
        item = {
            "id": str(item_id), "label": label, "exact_entity": True,
            "source_class": "licensed_news", "source_url": source,
            "retrieved_at": "2026-08-22T00:00:00Z", "evidence_span": "Exact-company event sentence.",
            "content_sha256": "a" * 64,
        }
        item.update(changes)
        return item

    def test_company_owned_or_unhashed_items_are_not_publishable(self):
        self.assertFalse(publishable_sentiment_item(self.item(1, source_class="company_owned")))
        self.assertFalse(publishable_sentiment_item(self.item(1, content_sha256=None)))

    def test_inference_input_requires_exact_entity_independent_source_and_hash(self):
        item = self.item(1, text="Selskapet vant en ny kontrakt.")
        self.assertTrue(sentiment_input_eligibility(item)[0])
        accepted, reasons = sentiment_input_eligibility({**item, "exact_entity": False, "content_sha256": None})
        self.assertFalse(accepted)
        self.assertIn("exact company identity is not verified", reasons)
        self.assertIn("missing content_sha256", reasons)

    def test_pinned_model_output_normalization_is_closed_set(self):
        self.assertEqual(len(MODEL_REVISION), 40)
        self.assertEqual(normalize_generated_label(" Positive. "), "positive")
        self.assertIsNone(normalize_generated_label("bullish"))

    def test_rollup_requires_two_independent_publishers(self):
        same_publisher = [
            self.item(1, source="https://news.example/a"),
            self.item(2, source="https://news.example/b"),
        ]
        self.assertEqual(aggregate_company_sentiment(same_publisher)["status"], "abstain")
        independent = same_publisher + [self.item(3, source="https://other.example/c")]
        result = aggregate_company_sentiment(independent)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["label"], "positive")

    def test_perfect_balanced_300_item_corpus_passes_poc_gate(self):
        labels = ("positive", "neutral", "negative", "mixed")
        gold = [{"id": str(i), "label": labels[i % 4]} for i in range(300)]
        predictions = [self.item(i, labels[i % 4], source=f"https://news{i % 7}.example/item/{i}") for i in range(300)]
        report = evaluate_predictions(gold, predictions)
        self.assertEqual(report["accuracy"], 1.0)
        self.assertEqual(report["macro_f1"], 1.0)
        self.assertTrue(report["qualification_passed"])
        self.assertFalse(report["production_scale_gate_passed"])

    def test_wrong_entity_and_company_owned_predictions_fail_gate(self):
        labels = ("positive", "neutral", "negative")
        gold = [{"id": str(i), "label": labels[i % 3]} for i in range(300)]
        predictions = [self.item(i, labels[i % 3], source=f"https://news.example/{i}") for i in range(300)]
        predictions[0]["exact_entity"] = False
        predictions[1]["source_class"] = "company_owned"
        report = evaluate_predictions(gold, predictions)
        self.assertEqual(report["wrong_entity_predictions"], 1)
        self.assertEqual(report["company_owned_predictions"], 1)
        self.assertFalse(report["qualification_passed"])

    def test_qualification_minimum_cannot_be_weakened(self):
        with self.assertRaises(ValueError):
            evaluate_predictions([{"id": "1", "label": "positive"}], [self.item(1)], minimum_items=1)


class OfficialNormalizationTests(unittest.TestCase):
    def test_accounting_obligation_is_categorical_for_as_but_not_enk(self):
        company = accounting_obligation_assessment({"organisation_number": "923609016", "legal_form": "AS"})
        sole_trader = accounting_obligation_assessment({"organisation_number": "923609017", "legal_form": "ENK", "employees": 0})
        self.assertEqual(company["value"]["classification"], "required_by_legal_form")
        self.assertEqual(sole_trader["value"]["classification"], "threshold_or_activity_dependent")
        self.assertTrue(company["content_sha256"])
        self.assertEqual(company["source_row_key"], "923609016")

    def test_observed_filing_overrides_rule_path(self):
        record = accounting_obligation_assessment({"organisation_number": "923609018", "legal_form": "ENK", "latest_submitted_accounts": "2024"})
        self.assertEqual(record["value"]["classification"], "filing_observed")

    def test_entity_normalization_keeps_identity(self):
        record = normalize_entity({"organisasjonsnummer": "923609016", "navn": "EQUINOR ASA", "organisasjonsform": {"kode": "ASA"}})
        self.assertEqual(record["organisation_number"], "923609016")
        self.assertEqual(record["legal_form"], "ASA")

    def test_financial_fields_keep_period_currency_and_zero(self):
        body = [{"id": 1, "valuta": "NOK", "regnskapsperiode": {"tilDato": "2025-12-31"}, "resultatregnskapResultat": {"driftsresultat": {"driftsresultat": 0, "driftsinntekter": {"sumDriftsinntekter": 12}}}}]
        record = normalize_financials(body)["records"][0]
        self.assertEqual(record["revenue"], 12)
        self.assertEqual(record["operating_result"], 0)
        self.assertEqual(record["currency"], "NOK")

    def test_financial_history_is_sorted_and_links_to_official_pdfs(self):
        record = normalize_financial_history(["2024", "2022", "2024", "invalid"], "923609016")
        self.assertEqual(record["years"], ["2022", "2024"])
        self.assertEqual(record["pdfs"][0]["year"], "2024")
        self.assertTrue(record["pdfs"][0]["url"].endswith("/923609016/2024"))

    def test_public_roles_drop_birth_dates(self):
        body = {"rollegrupper": [{"type": {"kode": "STYR"}, "roller": [{"type": {"kode": "LEDE", "beskrivelse": "Chair"}, "person": {"fodselsdato": "1970-01-01", "navn": {"fornavn": "Ada", "etternavn": "Nord"}}}]}]}
        record = normalize_roles(body)["roles"][0]
        self.assertEqual(record["name"], "Ada Nord")
        self.assertNotIn("fodselsdato", json.dumps(record))


class ResearchAgentTests(unittest.TestCase):
    @staticmethod
    def screen_row(org, municipality, employees, revenue):
        return {
            "organisation_number": org,
            "name": f"Company {org}",
            "municipality": municipality,
            "employees": employees,
            "evidence": {
                "registry": evidence("registry", "available", "official_registry_bulk", "https://example.test/registry", content_sha256="a" * 64),
                "financials": evidence("financials", "available", "official_annual_accounts", "https://example.test/accounts", value={"records": [{"revenue": revenue, "annual_result": 1}]}, content_sha256="b" * 64),
            },
        }

    def test_cross_company_screen_has_exact_membership_and_inspectable_plan(self):
        rows = [
            self.screen_row("111111111", "OSLO", 20, 2_000_000),
            self.screen_row("222222222", "OSLO", 5, 2_000_000),
            self.screen_row("333333333", "BERGEN", 20, 2_000_000),
            self.screen_row("444444444", "OSLO", 20, 500_000),
        ]
        result = screen_profiles(rows, "companies in Oslo with more than 10 employees and revenue over 1 million")
        self.assertFalse(result["abstained"])
        self.assertEqual([item["organisation_number"] for item in result["results"]], ["111111111"])
        self.assertEqual(len(result["plan"]["filters"]), 3)
        self.assertTrue(all(citation["content_sha256"] for citation in result["results"][0]["citations"]))

    def test_unsupported_cross_company_criterion_abstains(self):
        plan = parse_screen_query("companies in Oslo with positive Glassdoor sentiment")
        self.assertFalse(plan["executable"])
        result = screen_profiles([], "companies in Oslo with positive Glassdoor sentiment")
        self.assertTrue(result["abstained"])
        self.assertIn("Glassdoor", result["reason"])

    def test_missing_website_is_not_treated_as_proven_absence(self):
        result = screen_profiles([], "companies without a website")
        self.assertTrue(result["abstained"])
        self.assertIn("does not prove", result["reason"])

    def test_workspace_saves_pins_history_and_recovers_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            workspace, warning = load_workspace(path)
            self.assertIsNone(warning)
            updated = record_screen(workspace, {"query": "in Oslo", "plan": {"filters": []}, "result_count": 1, "results": [{"organisation_number": "111111111"}]}, pin_organisations=["111111111"])
            save_workspace(path, updated)
            loaded, warning = load_workspace(path)
            self.assertEqual(loaded["pins"], ["111111111"])
            self.assertEqual(len(loaded["history"]), 1)
            path.write_text("not json", encoding="utf-8")
            recovered, warning = load_workspace(path)
            self.assertEqual(recovered["pins"], [])
            self.assertIn("recovery", warning or "")

    def test_sentiment_abstains_and_every_fact_has_a_source(self):
        row = {
            "organisation_number": "923609016", "name": "Example AS", "legal_form": "AS",
            "municipality": "OSLO", "employees": None,
            "evidence": {"registry": evidence("registry", "available", "official", "https://example.test")},
        }
        result = answer_profile(row, "Give me employee sentiment")
        self.assertTrue(any("Sentiment is not scored" in item for item in result["unsupported_or_uncertain"]))
        self.assertTrue(all(fact["source_url"] for fact in result["facts"]))
        self.assertFalse(any(fact["claim"] == "Registry employee count" for fact in result["facts"]))

    def test_natural_leads_word_routes_to_roles(self):
        roles = evidence("roles", "available", "official", "https://example.test/roles", value={"roles": [{"name": "Ada Nord", "role": "Chair", "inactive": False}]})
        row = {"organisation_number": "923609016", "name": "Example AS", "evidence": {"roles": roles}}
        result = answer_profile(row, "Who leads this company?")
        self.assertEqual(result["facts"][0]["value"], "Ada Nord")

    def test_quarantined_website_claims_are_not_returned(self):
        website = evidence("website", "available", "company_site", "https://parent.test", value={"description": "Parent claim", "social_links": [{"platform": "linkedin", "url": "https://linkedin.com/company/parent"}], "identity_assessment": {"publishable": False}})
        row = {"organisation_number": "923609016", "name": "Subsidiary AS", "evidence": {"website": website}}
        result = answer_profile(row, "What social information is available?")
        self.assertFalse(result["facts"])
        self.assertTrue(any("quarantined" in item for item in result["unsupported_or_uncertain"]))


class PrototypeTests(unittest.TestCase):
    def test_qualification_copy_keeps_production_boundary_visible(self):
        header, boundary = qualification_copy({
            "weighted_score": {"verified_points": 100, "maximum_points": 100},
            "qualification": {"poc_qualified": True, "production_qualified": False},
        })
        self.assertIn("100/100", header)
        self.assertIn("not production-qualified", header)
        self.assertIn("remain quarantined", boundary)

    def test_quarantined_social_links_are_counted_but_not_published(self):
        row = {
            "organisation_number": "923609016",
            "name": "Subsidiary AS",
            "legal_form": "AS",
            "employees": None,
            "municipality": "OSLO",
            "industry_code": None,
            "industry_label": None,
            "website": "https://parent.test",
            "bankrupt": False,
            "liquidating": False,
            "evidence": {
                "website": evidence(
                    "website",
                    "available",
                    "company_site",
                    "https://parent.test",
                    value={
                        "identity_assessment": {"publishable": False},
                        "social_links": [],
                        "discovered_social_links": [
                            {"platform": "linkedin", "url": "https://linkedin.com/company/parent"}
                        ],
                    },
                )
            },
        }
        website = compact_prototype(row)["web"]["value"]
        self.assertEqual(website["quarantined_social_count"], 1)
        self.assertEqual(website["social_links"], [])


class RefreshTests(unittest.TestCase):
    def test_snapshot_fetcher_hashes_evaluator_bytes_and_carries_times(self):
        url = "https://example.test/entity/1"
        fetcher = SnapshotFetcher({"retrieved_at": "2026-01-02T00:00:00Z", "effective_at": "2026-01-01T00:00:00Z", "responses": {url: {"body": {"value": 1}}}})
        result = fetcher(url)
        self.assertEqual(result.status, 200)
        self.assertEqual(len(result.content_sha256 or ""), 64)
        self.assertEqual(result.effective_at, "2026-01-01T00:00:00Z")

    def test_identical_refresh_is_an_idempotent_noop(self):
        row = {"organisation_number": "923609016", "name": "Example AS", "employees": 4}
        self.assertEqual(diff_profile(row, dict(row)), [])

    def test_missing_to_zero_is_a_real_change_with_provenance(self):
        source = evidence("registry", "available", "official", "https://example.test/entity")
        old = {"organisation_number": "923609016", "employees": None, "evidence": {"registry": source}}
        new = {"organisation_number": "923609016", "employees": 0, "evidence": {"registry": source}}
        change = diff_profile(old, new)[0]
        self.assertIsNone(change["old_value"])
        self.assertEqual(change["new_value"], 0)
        self.assertEqual(change["source_url"], "https://example.test/entity")

    def test_refresh_rejects_membership_or_identity_drift(self):
        with self.assertRaises(ValueError):
            diff_datasets([{"organisation_number": "923609016"}], [{"organisation_number": "999999999"}])


class WebsiteIdentityTests(unittest.TestCase):
    def test_group_contact_page_listing_subsidiary_org_number_is_not_exact_homepage_identity(self):
        profile = {
            "organisation_number": "915637353",
            "name": "SKS PRODUKSJON AS",
            "evidence": {"website": evidence("website", "available", "company_site", "https://sks.no", value={
                "final_url": "https://sks.no/",
                "title": "Konsern - SKS - Forside",
                "main_text_excerpt": "SKS is a power group with multiple subsidiaries.",
                "pages": [{"title": "Contact", "main_text_excerpt": "SKS Produksjon AS organisation number 915 637 353"}],
            })},
        }
        assessment = assess_website_identity(profile)
        self.assertFalse(assessment["publishable"])
        self.assertNotEqual(assessment["score"], 1.0)

    def test_shared_identity_gate_quarantines_parent_social_links(self):
        website = evidence("website", "available", "company_site", "https://parent.test", value={
            "title": "Parent Group", "main_text_excerpt": "Parent Group portfolio",
            "social_links": [{"platform": "linkedin", "url": "https://linkedin.com/company/parent"}],
        })
        profile = {"organisation_number": "923609016", "name": "Exact Subsidiary AS", "evidence": {}}
        result = apply_website_identity_gate(profile, website)
        self.assertFalse(result["assessment"]["publishable"])
        self.assertEqual(result["website"]["value"]["social_links"], [])
        self.assertEqual(result["quarantined_social_links"], 1)

    def test_exact_legal_name_is_publishable(self):
        row = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS", "evidence": {"website": {"status": "available", "value": {"title": "Norsk Fiskeeksport AS"}}}}
        self.assertTrue(assess_website_identity(row)["publishable"])

    def test_parent_brand_without_legal_name_is_quarantined(self):
        row = {"organisation_number": "988412406", "name": "Tevlingveien 23 Invest AS", "evidence": {"website": {"status": "available", "value": {"title": "Ragde Eiendom"}}}}
        self.assertFalse(assess_website_identity(row)["publishable"])

    def test_parked_domain_and_parent_company_sports_site_are_quarantined(self):
        parked = {"organisation_number": "996081001", "name": "Condalign AS", "evidence": {"website": {"status": "available", "value": {"title": "CondAlign.com is for sale | HugeDomains"}}}}
        sports = {"organisation_number": "996242692", "name": "Primulator B.I.L.", "evidence": {"website": {"status": "available", "value": {"title": "Primulator", "description": "Premium products for HoReCa"}}}}
        self.assertFalse(assess_website_identity(parked)["publishable"])
        self.assertFalse(assess_website_identity(sports)["publishable"])

    def test_hosting_placeholder_and_generic_link_page_are_quarantined(self):
        hosting = {"organisation_number": "917568278", "name": "HJELMEN AS", "evidence": {"website": {"status": "available", "value": {"title": "www.Hjelmen-as.no is parked at Miss Hosting Web Hosting", "main_text_excerpt": "Hjelmen " * 100}}}}
        links = {"organisation_number": "986606009", "name": "KOALA ANS", "evidence": {"website": {"status": "available", "value": {"title": "koala.no", "description": "Find the best information and most relevant links on all topics related to"}}}}
        self.assertFalse(assess_website_identity(hosting)["publishable"])
        self.assertFalse(assess_website_identity(links)["publishable"])

    def test_broader_umbrella_site_is_not_exact_when_name_only_appears_in_body(self):
        row = {
            "organisation_number": "976994027",
            "name": "AVALDSNES SOKN",
            "evidence": {"website": {"status": "available", "value": {
                "title": "Kirken i Karmøy",
                "final_url": "https://www.karmoykirken.no/",
                "main_text_excerpt": "Avaldsnes sokn is one of several parishes represented on this umbrella site.",
            }}},
        }
        self.assertFalse(assess_website_identity(row)["publishable"])

    def test_social_handle_requires_exact_entity_name_evidence(self):
        aon = {"name": "Aon Norway AS"}
        fish = {"name": "Norsk Fiskeeksport AS"}
        self.assertFalse(assess_social_identity(aon, {"platform": "linkedin", "url": "https://linkedin.com/company/aon"})["publishable"])
        self.assertTrue(assess_social_identity(fish, {"platform": "linkedin", "url": "https://linkedin.com/company/norsk-fiskeeksport"})["publishable"])


class VerifiedSiteSeedTests(unittest.TestCase):
    def test_verified_seed_is_applied_and_unknown_org_is_rejected(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "profiles.jsonl"
            seeds = root / "seeds.json"
            output = root / "output.jsonl"
            report = root / "report.json"
            profiles.write_text(json.dumps({"organisation_number": "123456789", "name": "Example AS"}) + "\n")
            seeds.write_text(json.dumps([{
                "organisation_number": "123456789",
                "website": "https://example.no/",
                "proof_url": "https://source.example/proof",
                "proof": "Exact name and organisation number",
            }]))
            command = [
                sys.executable, str(ROOT / "scripts" / "apply_verified_site_seeds.py"),
                "--profiles", str(profiles), "--seeds", str(seeds),
                "--output", str(output), "--report", str(report),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            row = json.loads(output.read_text().strip())
            self.assertEqual(row["website"], "https://example.no/")
            self.assertEqual(row["website_seed_source"], "independently_verified_exact_entity")
            self.assertEqual(json.loads(report.read_text())["applied"], 1)

            seeds.write_text(json.dumps([{
                "organisation_number": "987654321",
                "website": "https://unknown.no/",
                "proof_url": "https://source.example/proof",
            }]))
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unknown organisations", failed.stderr)

class CompetitionBatchDiscoveryTests(unittest.TestCase):
    """Tests for the discovery fallback inside the competition batch enrich() path."""

    BATCH_MODULE = "scripts.run_competition_batch"

    def _make_profile(self, *, website="", name="Norsk Fiskeeksport AS", org="923609016"):
        return {
            "organisation_number": org,
            "name": name,
            "website": website,
            "municipality": "NOTODDEN",
            "evidence": {"registry": evidence("registry", "available", "bulk", "https://example.test")},
        }

    def _fake_official(self, org, modules, fetcher=None):
        return {}, []

    def _fake_fetch_website_available(self, url, **kwargs):
        return evidence("website", "available", "registry_linked_company_website", url, value={
            "title": "Norsk Fiskeeksport AS",
            "final_url": url,
            "main_text_excerpt": "Seafood exporter in Notodden since 1985.",
            "social_links": [],
        }), {"requests": 2, "bytes": 5000, "latencies_ms": [100]}

    def test_registry_website_present_skips_discovery(self):
        """When the registry provides a website, the production enrich() must not call brave_search."""
        import tempfile
        import scripts.run_competition_batch as batch_mod

        profile = self._make_profile(website="https://known.no")

        brave_called = {"count": 0}

        def mock_brave(*_args, **_kwargs):
            brave_called["count"] += 1
            return [], {"status": 0, "latency_ms": 0, "bytes": 0, "query_sha256": "x"}

        def mock_profiles_from_bulk(_path, orgs):
            return [dict(profile)], {"registry_snapshot_sha256": "a" * 64, "registry_rows_scanned": 1, "requested": 1, "selected": 1}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orgs_file = root / "orgs.txt"
            orgs_file.write_text(profile["organisation_number"] + "\n")
            output = root / "output.jsonl"
            profiles_output = root / "profiles.jsonl"
            report = root / "report.json"

            saved_argv = sys.argv
            try:
                sys.argv = [
                    "run_competition_batch.py",
                    "--organisations", str(orgs_file),
                    "--bulk", "/dev/null",
                    "--output", str(output),
                    "--profiles-output", str(profiles_output),
                    "--report", str(report),
                    "--run-id", "test-skip-discovery",
                    "--expected-count", "1",
                    "--modules", "registry,website",
                    "--workers", "1",
                ]
                with patch.object(batch_mod, "brave_search", mock_brave), \
                     patch.object(batch_mod, "fetch_website", self._fake_fetch_website_available), \
                     patch.object(batch_mod, "fetch_official_modules", self._fake_official), \
                     patch.object(batch_mod, "profiles_from_bulk", mock_profiles_from_bulk), \
                     patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "test-key"}):
                    with self.assertRaises(SystemExit) as ctx:
                        batch_mod.main()
                    self.assertEqual(ctx.exception.code, 0, "Batch should exit cleanly")
            finally:
                sys.argv = saved_argv

            self.assertEqual(brave_called["count"], 0, "brave_search must not be called when registry website exists")
            result = json.loads(profiles_output.read_text().strip())
            self.assertEqual(result["evidence"]["website"]["status"], "available")

    def test_missing_website_valid_discovery_candidate(self):
        """Missing website + valid search candidate + identity-verified → published as available."""
        profile = self._make_profile(website="")
        brave_api_key = "test-key"

        search_results = [{
            "url": "https://norskfiskeeksport.no/",
            "title": "Norsk Fiskeeksport AS",
            "snippet": "Seafood exporter 923609016 in Notodden",
            "rank": 1,
            "provider": "brave_search_api",
            "query": "\"Norsk Fiskeeksport AS\" 923609016 NOTODDEN",
        }]

        website_record = evidence("website", "available", "registry_linked_company_website", "https://norskfiskeeksport.no/", value={
            "title": "Norsk Fiskeeksport AS",
            "final_url": "https://norskfiskeeksport.no/",
            "main_text_excerpt": "Norsk Fiskeeksport AS is a leading seafood exporter based in Notodden, Norway.",
            "social_links": [],
        })

        requested_modules = ["registry", "website"]
        decision = choose_search_candidate(profile, search_results)
        selected = decision.get("selected")
        self.assertIsNotNone(selected, "The candidate should pass the crawl-candidate gate")

        gated = apply_website_identity_gate(profile, website_record)
        assessment = gated.get("assessment")
        self.assertTrue(assessment["publishable"], "Identity should be verified for exact legal name match")

        # Simulate the enrich() branch
        website = gated["website"]
        website["source_type"] = "search_discovered_company_website"
        if assessment and assessment.get("publishable") and website.get("status") == "available":
            profile["evidence"]["website"] = website

        self.assertEqual(profile["evidence"]["website"]["status"], "available")
        self.assertEqual(profile["evidence"]["website"]["source_type"], "search_discovered_company_website")

    def test_missing_website_wrong_company_candidate(self):
        """Missing website + crawled candidate fails identity gate → not_found, never published."""
        profile = self._make_profile(website="", name="Norsk Fiskeeksport AS", org="923609016")
        brave_api_key = "test-key"

        search_results = [{
            "url": "https://norskfiskeeksport.no/",
            "title": "Norsk Fiskeeksport AS",
            "snippet": "Seafood exporter 923609016 in Notodden",
            "rank": 1,
            "provider": "brave_search_api",
            "query": "\"Norsk Fiskeeksport AS\" 923609016 NOTODDEN",
        }]

        # The crawled site belongs to a different company
        website_record = evidence("website", "available", "registry_linked_company_website", "https://norskfiskeeksport.no/", value={
            "title": "Totally Different Company",
            "final_url": "https://norskfiskeeksport.no/",
            "main_text_excerpt": "We are Totally Different Company providing unrelated services.",
            "social_links": [],
        })

        decision = choose_search_candidate(profile, search_results)
        selected = decision.get("selected")
        self.assertIsNotNone(selected)

        gated = apply_website_identity_gate(profile, website_record)
        assessment = gated.get("assessment")
        self.assertFalse(assessment["publishable"], "Identity must fail for a wrong-company page")

        # Simulate the enrich() branch
        website = gated["website"]
        website["source_type"] = "search_discovered_company_website"
        if assessment and assessment.get("publishable") and website.get("status") == "available":
            profile["evidence"]["website"] = website
        else:
            profile["evidence"]["website"] = evidence(
                "website", "not_found",
                "search_discovered_company_website", selected["url"],
                note="Search candidate crawled but exact-entity identity not verified",
            )

        self.assertEqual(profile["evidence"]["website"]["status"], "not_found")
        self.assertIn("not verified", profile["evidence"]["website"]["note"])

    def test_missing_website_no_candidate(self):
        """Missing website + no search result passes scoring → not_found."""
        profile = self._make_profile(website="")

        # All results are on blocked hosts or irrelevant
        search_results = [
            {"url": "https://proff.no/selskap/norsk-fiskeeksport", "title": "Norsk Fiskeeksport AS", "snippet": "Directory", "rank": 1, "provider": "brave_search_api", "query": "test"},
            {"url": "https://linkedin.com/company/norsk-fiskeeksport", "title": "Norsk Fiskeeksport AS", "snippet": "Social", "rank": 2, "provider": "brave_search_api", "query": "test"},
        ]

        decision = choose_search_candidate(profile, search_results)
        selected = decision.get("selected")
        self.assertIsNone(selected, "Blocked-host results must not become candidates")
        self.assertTrue(decision["abstained"])

        # Simulate the enrich() branch
        profile["evidence"]["website"] = evidence(
            "website", "not_found",
            "search_discovery", "https://api.search.brave.com/res/v1/web/search",
            note="No search result passed the deterministic crawl-candidate gate",
        )

        self.assertEqual(profile["evidence"]["website"]["status"], "not_found")
        self.assertIn("crawl-candidate gate", profile["evidence"]["website"]["note"])


class Stage1IdentityEngineTests(unittest.TestCase):
    """Stage 1: Exact Company Identity Engine tests."""

    def test_valid_org_numbers(self):
        # Known valid Norwegian organisation numbers (Modulo 11 valid)
        valid_orgs = ["923609016", "915637353"]
        for org in valid_orgs:
            self.assertEqual(canonicalize_org_number(org), org)
            self.assertEqual(canonicalize_org_number(org, verify_checksum=True), org)
            res = validate_org_number(org, verify_checksum=True)
            self.assertTrue(res.is_valid)
            self.assertTrue(res.has_valid_checksum)
            self.assertEqual(res.canonical, org)
            self.assertIsNone(res.error)
            self.assertTrue(is_valid_org_mod11(org))
            self.assertEqual(compute_mod11_check_digit(org[:8]), int(org[8]))

    def test_malformed_org_numbers(self):
        # 8 digits (too short)
        self.assertIsNone(canonicalize_org_number("12345678"))
        res_short = validate_org_number("12345678")
        self.assertFalse(res_short.is_valid)
        self.assertIn("Invalid length", res_short.error or "")

        # 10 digits (too long)
        self.assertIsNone(canonicalize_org_number("1234567890"))
        res_long = validate_org_number("1234567890")
        self.assertFalse(res_long.is_valid)
        self.assertIn("Invalid length", res_long.error or "")

        # Non-digits
        self.assertIsNone(canonicalize_org_number("ABCDEFGHI"))
        res_alpha = validate_org_number("ABCDEFGHI")
        self.assertFalse(res_alpha.is_valid)
        self.assertIn("invalid characters", res_alpha.error or "")

        # Empty / None
        self.assertIsNone(canonicalize_org_number(""))
        self.assertIsNone(canonicalize_org_number(None))

        # Modulo 11 failure with verify_checksum=True
        # "123456789" has invalid check digit (check digit should be 5, not 9)
        self.assertIsNone(canonicalize_org_number("123456789", verify_checksum=True))
        res_mod11 = validate_org_number("123456789", verify_checksum=True)
        self.assertFalse(res_mod11.is_valid)
        self.assertFalse(res_mod11.has_valid_checksum)
        self.assertIn("Invalid Modulo 11 check digit", res_mod11.error or "")

        # Test check digit 10 (disallowed in Modulo 11)
        # "11100000": 1*3 + 1*2 + 1*7 = 12 % 11 = 1 => 11 - 1 = 10 (invalid)
        self.assertIsNone(compute_mod11_check_digit("11100000"))

    def test_org_number_formatting_variations(self):
        expected = "923609016"
        variations = [
            "923 609 016",
            " 923  609  016 ",
            "923.609.016",
            "923-609-016",
            "923.609-016",
            "NO 923 609 016",
            "NO923609016",
            "no-923-609-016",
            "Org.nr: 923 609 016",
            "Organisasjonsnummer: 923609016",
            "Foretaksregisteret 923609016",
            "923 609 016 MVA",
            "NO 923 609 016 MVA",
            "923609016MVA",
            "923 609 016 Foretaksregisteret",
            923609016,  # int
        ]
        for var in variations:
            self.assertEqual(canonicalize_org_number(var), expected, f"Failed for variation: {var!r}")
            res = validate_org_number(var)
            self.assertTrue(res.is_valid, f"Validation failed for: {var!r}")
            self.assertEqual(res.canonical, expected)

    def test_exact_legal_name_matches(self):
        match1 = match_legal_names("Equinor ASA", "Equinor ASA")
        self.assertTrue(match1.is_match)
        self.assertEqual(match1.category, LegalNameMatchCategory.EXACT)
        self.assertEqual(match1.target_form, "ASA")
        self.assertEqual(match1.candidate_form, "ASA")

        match2 = match_legal_names("NORSK FISKEEKSPORT AS", "norsk fiskeeksport as")
        self.assertTrue(match2.is_match)
        self.assertEqual(match2.category, LegalNameMatchCategory.EXACT_NORMALIZED)

    def test_normalized_legal_name_matches(self):
        # Whitespace
        match_ws = match_legal_names("  Equinor   ASA  ", "Equinor ASA")
        self.assertTrue(match_ws.is_match)

        # Suffix punctuation: A/S vs AS, A.S. vs AS
        match_slash = match_legal_names("Norsk Fiskeeksport A/S", "Norsk Fiskeeksport AS")
        self.assertTrue(match_slash.is_match)
        self.assertIn(match_slash.category, {LegalNameMatchCategory.EXACT_NORMALIZED, LegalNameMatchCategory.EXACT})

        match_dot = match_legal_names("Norsk Fiskeeksport A.S.", "Norsk Fiskeeksport AS")
        self.assertTrue(match_dot.is_match)

        # Suffix omitted on one side
        match_omitted = match_legal_names("Equinor ASA", "Equinor")
        self.assertTrue(match_omitted.is_match)
        self.assertEqual(match_omitted.category, LegalNameMatchCategory.LEGAL_SUFFIX_OMITTED)

        # Unicode & Norwegian diacritics
        match_nordic1 = match_legal_names("Tromsø Bygg AS", "Tromso Bygg AS")
        self.assertTrue(match_nordic1.is_match)

        match_nordic2 = match_legal_names("Blåbær Syltetøy AS", "Blabaer Syltetoy AS")
        self.assertTrue(match_nordic2.is_match)

        match_accent = match_legal_names("Café Bakeri AS", "Cafe Bakeri AS")
        self.assertTrue(match_accent.is_match)

    def test_conflicting_legal_names(self):
        # Different distinctive tokens (partial overlap is NOT identity)
        match_partial = match_legal_names("Acme Trading AS", "Acme Transport AS")
        self.assertFalse(match_partial.is_match)
        self.assertEqual(match_partial.category, LegalNameMatchCategory.PARTIAL_OVERLAP)

        # Incompatible legal forms (AS vs ASA)
        match_form_conflict = match_legal_names("Acme AS", "Acme ASA")
        self.assertFalse(match_form_conflict.is_match)
        self.assertEqual(match_form_conflict.category, LegalNameMatchCategory.LEGAL_FORM_CONFLICT)

        # Incompatible legal forms (AS vs ENK)
        match_form_conflict2 = match_legal_names("Hansen Bygg AS", "Hansen Bygg ENK")
        self.assertFalse(match_form_conflict2.is_match)
        self.assertEqual(match_form_conflict2.category, LegalNameMatchCategory.LEGAL_FORM_CONFLICT)

        # Completely unrelated names
        match_unrelated = match_legal_names("Equinor ASA", "Telenor ASA")
        self.assertFalse(match_unrelated.is_match)
        self.assertEqual(match_unrelated.category, LegalNameMatchCategory.CONFLICTING)

    def test_exact_domain_matches(self):
        m1 = match_domain_entity("https://equinor.com", "https://equinor.com")
        self.assertTrue(m1.is_match)
        self.assertEqual(m1.category, DomainMatchCategory.EXACT)

        m2 = match_domain_entity("equinor.com", "equinor.com")
        self.assertTrue(m2.is_match)
        self.assertEqual(m2.category, DomainMatchCategory.EXACT)

    def test_normalized_domain_matches(self):
        m1 = match_domain_entity("http://www.equinor.com/", "https://equinor.com")
        self.assertTrue(m1.is_match)
        self.assertEqual(m1.category, DomainMatchCategory.NORMALIZED)

        m2 = match_domain_entity("https://WWW.EQUINOR.COM", "equinor.com")
        self.assertTrue(m2.is_match)
        self.assertEqual(m2.category, DomainMatchCategory.NORMALIZED)

    def test_related_derived_domains(self):
        # Subdomain
        m_sub = match_domain_entity("https://equinor.com", "https://careers.equinor.com")
        self.assertTrue(m_sub.is_match)
        self.assertEqual(m_sub.category, DomainMatchCategory.RELATED_DERIVED)

        # ccTLD variant
        m_tld = match_domain_entity("https://equinor.no", "https://equinor.com")
        self.assertTrue(m_tld.is_match)
        self.assertEqual(m_tld.category, DomainMatchCategory.RELATED_DERIVED)

        # Name derived
        m_name = match_domain_entity(None, "https://norsk-fiskeeksport.no", target_name="Norsk Fiskeeksport AS")
        self.assertTrue(m_name.is_match)
        self.assertEqual(m_name.category, DomainMatchCategory.RELATED_DERIVED)

    def test_conflicting_domains(self):
        m = match_domain_entity("https://target-company.no", "https://competitor.com", target_name="Target Company AS")
        self.assertFalse(m.is_match)
        self.assertEqual(m.category, DomainMatchCategory.CONFLICTING)

    def test_unavailable_domains(self):
        m1 = match_domain_entity(None, "https://equinor.com")
        self.assertFalse(m1.is_match)
        self.assertEqual(m1.category, DomainMatchCategory.UNAVAILABLE)

        m2 = match_domain_entity("", "")
        self.assertFalse(m2.is_match)
        self.assertEqual(m2.category, DomainMatchCategory.UNAVAILABLE)

    def test_parent_subsidiary_group_relationships(self):
        parent_org = "915637000"
        sub_org = "915637353"
        sister_org = "915637999"

        target_sub = {"organisation_number": sub_org, "name": "SKS Produksjon AS", "overordnetEnhet": parent_org}
        cand_parent = {"organisation_number": parent_org, "name": "SKS AS"}
        cand_sister = {"organisation_number": sister_org, "name": "SKS Handel AS", "overordnetEnhet": parent_org}

        # Subunit to parent
        rel_parent = classify_group_relationship(target_sub, cand_parent)
        self.assertEqual(rel_parent.relation_type, GroupRelationType.PARENT)
        self.assertFalse(rel_parent.is_same_legal_entity)

        # Parent to subunit
        rel_sub = classify_group_relationship(cand_parent, target_sub)
        self.assertEqual(rel_sub.relation_type, GroupRelationType.SUBUNIT)
        self.assertFalse(rel_sub.is_same_legal_entity)

        # Sister entities sharing parent
        rel_sister = classify_group_relationship(target_sub, cand_sister)
        self.assertEqual(rel_sister.relation_type, GroupRelationType.SISTER_SUBSIDIARY)
        self.assertFalse(rel_sister.is_same_legal_entity)

        # Same entity
        rel_same = classify_group_relationship(target_sub, target_sub)
        self.assertEqual(rel_same.relation_type, GroupRelationType.SAME_ENTITY)
        self.assertTrue(rel_same.is_same_legal_entity)

        # Corporate group via group_data (konsernstruktur)
        group_data = {
            "morselskap": {"organisasjonsnummer": parent_org, "navn": "SKS AS"},
            "datterselskaper": [{"organisasjonsnummer": sub_org, "navn": "SKS Produksjon AS"}],
        }
        rel_group_parent = classify_group_relationship(
            {"organisation_number": sub_org, "name": "SKS Produksjon AS"},
            {"organisation_number": parent_org, "name": "SKS AS"},
            group_data=group_data,
        )
        self.assertEqual(rel_group_parent.relation_type, GroupRelationType.PARENT)
        self.assertFalse(rel_group_parent.is_same_legal_entity)

        # Assess company identity: parent entity must be explicitly rejected for exact identity
        verdict = assess_company_identity(target_sub, cand_parent, group_data=group_data)
        self.assertEqual(verdict.verdict, IdentityVerdictStatus.REJECTED)
        self.assertEqual(verdict.confidence, IdentityConfidence.HIGH)
        self.assertTrue(verdict.flags["is_parent_or_subsidiary"])
        self.assertTrue(any("parent" in r.lower() for r in verdict.reasons))

    def test_multiple_candidate_entities_and_ambiguity(self):
        target = {"name": "Hansen Bygg AS", "organisation_number": None}
        candidates = [
            {"organisation_number": "912345678", "name": "Hansen Bygg AS", "municipality": "Oslo"},
            {"organisation_number": "987654321", "name": "Hansen Bygg AS", "municipality": "Bergen"},
        ]

        is_ambig, reasons = detect_ambiguity(target, candidates)
        self.assertTrue(is_ambig)
        self.assertTrue(any("Multiple distinct BRREG entities" in r for r in reasons))

        # When evaluated against candidate pool, verdict must be AMBIGUOUS
        verdict = assess_company_identity(target, candidates[0], candidate_pool=candidates)
        self.assertEqual(verdict.verdict, IdentityVerdictStatus.AMBIGUOUS)
        self.assertEqual(verdict.confidence, IdentityConfidence.NONE)
        self.assertTrue(verdict.flags["ambiguity_detected"])

        # If target has exact org number matching one candidate, it is unambiguous
        target_with_org = {"name": "Hansen Bygg AS", "organisation_number": "912345678"}
        is_ambig2, _ = detect_ambiguity(target_with_org, candidates)
        self.assertFalse(is_ambig2)

    def test_wrong_company_explicit_rejection(self):
        target = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "website": "https://norskfiske.no",
        }

        # 1. Candidate with different org number (unrelated company)
        cand_wrong_org = {
            "organisation_number": "987654321",
            "name": "Annet Selskap AS",
        }
        v1 = assess_company_identity(target, cand_wrong_org)
        self.assertEqual(v1.verdict, IdentityVerdictStatus.REJECTED)
        self.assertEqual(v1.confidence, IdentityConfidence.HIGH)
        self.assertTrue(any("does not match target org" in r for r in v1.reasons))

        # 2. Candidate with conflicting legal form (AS vs ASA) and no org number
        cand_form_conflict = {
            "organisation_number": None,
            "name": "Norsk Fiskeeksport ASA",
        }
        v2 = assess_company_identity(target, cand_form_conflict)
        self.assertEqual(v2.verdict, IdentityVerdictStatus.REJECTED)
        self.assertTrue(v2.flags["legal_form_conflict"])

        # 3. Candidate with conflicting domain and no org number
        cand_domain_conflict = {
            "organisation_number": None,
            "name": "Norsk Fiskeeksport AS",
            "website": "https://completely-unrelated-competitor.com",
        }
        v3 = assess_company_identity(target, cand_domain_conflict)
        self.assertEqual(v3.verdict, IdentityVerdictStatus.REJECTED)
        self.assertTrue(v3.flags["domain_conflict"])

    def test_missing_evidence_and_deterministic_repeated_results(self):
        target = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "website": "https://norskfiske.no",
        }

        # Missing candidate evidence: name matches, but no org number and no domain
        cand_bare = {"name": "Norsk Fiskeeksport AS"}
        v_bare = assess_company_identity(target, cand_bare)
        self.assertEqual(v_bare.verdict, IdentityVerdictStatus.UNRESOLVED)
        self.assertEqual(v_bare.confidence, IdentityConfidence.LOW)

        # Missing both org numbers and no domain
        v_unresolved = assess_company_identity({"name": "Mystery AS"}, {"name": "Mystery AS"})
        self.assertEqual(v_unresolved.verdict, IdentityVerdictStatus.UNRESOLVED)

        # Determinism: run assess_company_identity 10 times, verify bit-for-bit identical results
        cand_match = {
            "organisation_number": "923609016",
            "name": "NORSK FISKEEKSPORT AS",
            "website": "https://www.norskfiske.no/",
        }
        first_run = assess_company_identity(target, cand_match).to_dict()
        for i in range(9):
            subsequent_run = assess_company_identity(target, cand_match).to_dict()
            self.assertEqual(first_run, subsequent_run, f"Non-deterministic result at iteration {i + 2}")


class Stage2WebsiteDiscoveryTests(unittest.TestCase):
    """Stage 2: Deterministic Website Discovery tests."""

    def _make_profile(self, **kwargs):
        base = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "municipality": "Bergen",
            "industry_label": "Engroshandel med fisk",
            "website": "",
            "evidence": {},
        }
        base.update(kwargs)
        return base

    def test_request_budget_accounting(self):
        budget = RequestBudget(max_total_requests=5, max_page_requests=2, max_search_requests=1)
        self.assertTrue(budget.can_request("page"))
        self.assertTrue(budget.can_request("search"))

        budget.record_request("search", success=True)
        self.assertEqual(budget.search_requests, 1)
        self.assertEqual(budget.total_requests, 1)
        self.assertFalse(budget.can_request("search"), "Search budget should be exhausted")

        budget.record_request("page", success=True, redirects_count=1)
        budget.record_request("page", success=False)
        self.assertEqual(budget.page_requests, 2)
        self.assertEqual(budget.redirects, 1)
        self.assertEqual(budget.failed_requests, 1)
        self.assertFalse(budget.can_request("page"), "Page budget should be exhausted")

        # Total requests now 3 / 5
        self.assertTrue(budget.can_request("robots"))
        budget.record_request("robots", success=True)
        budget.record_request("robots", success=True)
        self.assertEqual(budget.total_requests, 5)
        self.assertFalse(budget.can_request("robots"), "Total budget should be exhausted")
        self.assertFalse(budget.can_request("page"))

    def test_sitemap_xml_parsing(self):
        # Direct urlset
        urlset_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/</loc></url>
            <url><loc>https://example.com/om-oss</loc></url>
            <url><loc>https://example.com/kontakt</loc></url>
            <url><loc>https://example.com/image.jpg</loc></url>
        </urlset>"""
        pages, sitemaps = parse_sitemap_xml(urlset_xml)
        self.assertEqual(len(pages), 4)
        self.assertEqual(sitemaps, [])
        self.assertIn("https://example.com/om-oss", pages)

        # Sitemap index
        index_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
            <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
        </sitemapindex>"""
        pages, sitemaps = parse_sitemap_xml(index_xml)
        self.assertEqual(pages, [])
        self.assertEqual(len(sitemaps), 2)
        self.assertEqual(sitemaps[0], "https://example.com/sitemap1.xml")

    def test_sitemap_url_discovery_filtering(self):
        fetcher = SafeHttpFetcher()
        budget = RequestBudget(max_sitemap_requests=2)

        sitemap_content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/products/item1</loc></url>
            <url><loc>https://example.com/om-oss</loc></url>
            <url><loc>https://example.com/kontakt</loc></url>
            <url><loc>https://example.com/banner.png</loc></url>
            <url><loc>https://example.com/annual-report.pdf</loc></url>
        </urlset>"""

        with patch.object(fetcher, "fetch_page") as mock_fetch:
            mock_fetch.return_value = DiscoveryFetchResult(
                url="https://example.com/sitemap.xml",
                final_url="https://example.com/sitemap.xml",
                status_code=200,
                content=sitemap_content,
                html="",
                title="",
                meta_description="",
                text_excerpt="",
                content_sha256="abc",
                error=None,
                redirects_count=0,
                elapsed_ms=10,
            )
            discovered = discover_sitemap_urls("https://example.com/", fetcher, budget)

            # High signal pages (om-oss, kontakt) must be prioritized, assets excluded
            self.assertTrue(len(discovered) >= 2)
            self.assertEqual(discovered[0], "https://example.com/om-oss")
            self.assertEqual(discovered[1], "https://example.com/kontakt")
            self.assertNotIn("https://example.com/banner.png", discovered)
            self.assertNotIn("https://example.com/annual-report.pdf", discovered)

    def test_search_candidate_discovery_filtering(self):
        profile = self._make_profile()
        budget = RequestBudget(max_search_requests=1)

        search_payload = {
            "web": {
                "results": [
                    {"url": "https://proff.no/selskap/norsk-fiskeeksport", "title": "Proff", "description": "Dir"},
                    {"url": "https://norskfiske.no/", "title": "Norsk Fiskeeksport AS", "description": "Offisiell side"},
                    {"url": "https://facebook.com/norskfiske", "title": "Facebook", "description": "Social"},
                ]
            }
        }
        mock_search = lambda q: search_payload
        candidates = discover_search_candidates(profile, mock_search, budget)

        self.assertEqual(len(candidates), 3)
        self.assertEqual(budget.search_requests, 1)

        # proff.no and facebook.com must be identified as blocked hosts
        blocked_hosts = [c.host for c in candidates if c.is_blocked_host]
        self.assertIn("proff.no", blocked_hosts)
        self.assertIn("facebook.com", blocked_hosts)

        # Clean candidate
        valid_candidates = [c for c in candidates if not c.is_blocked_host]
        self.assertEqual(len(valid_candidates), 1)
        self.assertEqual(valid_candidates[0].url, "https://norskfiske.no/")

    def test_candidate_scoring(self):
        profile = self._make_profile()

        # 1. High scoring candidate with org number, name in title, name in host, municipality
        score_high = score_candidate(
            profile,
            "https://norskfiske.no/",
            title="Norsk Fiskeeksport AS - Forside",
            snippet="Velkommen til Norsk Fiskeeksport AS i Bergen. Org nr 923 609 016. Engroshandel med fisk.",
        )
        self.assertTrue(score_high.publishable_candidate)
        self.assertGreaterEqual(score_high.score, 0.8)
        self.assertTrue(score_high.evidence_breakdown.get("org_number_match"))
        self.assertTrue(score_high.evidence_breakdown.get("name_in_title"))
        self.assertTrue(score_high.evidence_breakdown.get("name_in_host"))
        self.assertTrue(score_high.evidence_breakdown.get("municipality_match"))

        # 2. Blocked host candidate scores 0.0
        score_blocked = score_candidate(profile, "https://proff.no/selskap/norsk-fiske")
        self.assertEqual(score_blocked.score, 0.0)
        self.assertFalse(score_blocked.publishable_candidate)
        self.assertIn("directory", score_blocked.reasons[0].lower())

        # 3. Unrelated candidate scores low
        score_unrelated = score_candidate(
            profile,
            "https://completelyunrelated.com/",
            title="Sko og Klær Nettbutikk",
            snippet="Kjøp sko på nett.",
        )
        self.assertLess(score_unrelated.score, 0.4)
        self.assertFalse(score_unrelated.publishable_candidate)

    def test_exact_entity_verification(self):
        profile = self._make_profile()

        # 1. Verified via exact org number in content
        page_verified = DiscoveryFetchResult(
            url="https://norskfiske.no/",
            final_url="https://norskfiske.no/",
            status_code=200,
            content=b"html",
            html="<html></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="Norsk Fiskeeksport AS er et selskap i Bergen med organisasjonsnummer 923 609 016.",
            content_sha256="123",
            error=None,
            redirects_count=0,
            elapsed_ms=50,
        )
        verdict, evidence_trail, reasons = verify_exact_entity(profile, [page_verified])
        self.assertEqual(verdict, DiscoveryVerdictStatus.VERIFIED)
        self.assertTrue(any(item.identifier == "organisation_number" and item.level == VerificationEvidenceLevel.STRONG for item in evidence_trail))

        # 2. Abstain due to parked page marker
        page_parked = DiscoveryFetchResult(
            url="https://norskfiske.no/",
            final_url="https://norskfiske.no/",
            status_code=200,
            content=b"html",
            html="<html></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="This domain is for sale | HugeDomains. Norsk Fiskeeksport AS.",
            content_sha256="123",
            error=None,
            redirects_count=0,
            elapsed_ms=50,
        )
        v_parked, _, r_parked = verify_exact_entity(profile, [page_parked])
        self.assertEqual(v_parked, DiscoveryVerdictStatus.ABSTAIN)
        self.assertTrue(any("parked" in r.lower() for r in r_parked))

        # 3. Abstain due to conflicting org number
        page_conflict = DiscoveryFetchResult(
            url="https://norskfiske.no/",
            final_url="https://norskfiske.no/",
            status_code=200,
            content=b"html",
            html="<html></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="Norsk Fiskeeksport AS. Org nr 987 654 321. Different company.",
            content_sha256="123",
            error=None,
            redirects_count=0,
            elapsed_ms=50,
        )
        v_conflict, _, r_conflict = verify_exact_entity(profile, [page_conflict])
        self.assertEqual(v_conflict, DiscoveryVerdictStatus.ABSTAIN)
        self.assertTrue(any("conflicting" in r.lower() for r in r_conflict))

    def test_ssrf_and_robots_protection(self):
        fetcher = SafeHttpFetcher()
        budget = RequestBudget()

        # SSRF: localhost and private IPs blocked
        res_local = fetcher.fetch_page("http://localhost:8080/test", budget)
        self.assertIn("SSRF blocked", res_local.error or "")

        res_private = fetcher.fetch_page("http://127.0.0.1/test", budget)
        self.assertIn("SSRF blocked", res_private.error or "")

        res_loopback = fetcher.fetch_page("http://169.254.169.254/metadata", budget)
        self.assertIn("SSRF blocked", res_loopback.error or "")

        # Non-HTTP scheme
        res_file = fetcher.fetch_page("file:///etc/passwd", budget)
        self.assertIn("SSRF blocked", res_file.error or "")

        # Robots.txt disallowed
        with patch.object(fetcher, "is_robots_allowed", return_value=False):
            res_robots = fetcher.fetch_page("https://example.com/secret", budget)
            self.assertEqual(res_robots.status_code, 403)
            self.assertIn("robots.txt", res_robots.error or "")

    def test_discovery_pipeline_registry_website(self):
        profile = self._make_profile(website="https://norskfiske.no/")
        fetcher = SafeHttpFetcher()
        budget = RequestBudget()

        mock_page = DiscoveryFetchResult(
            url="https://norskfiske.no/",
            final_url="https://norskfiske.no/",
            status_code=200,
            content=b"<html><head><title>Norsk Fiskeeksport AS</title></head><body>Norsk Fiskeeksport AS org nr 923 609 016</body></html>",
            html="<html><head><title>Norsk Fiskeeksport AS</title></head><body>Norsk Fiskeeksport AS org nr 923 609 016</body></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="Norsk Fiskeeksport AS org nr 923 609 016 i Bergen.",
            content_sha256="abc",
            error=None,
            redirects_count=0,
            elapsed_ms=30,
        )

        with patch.object(fetcher, "fetch_page", return_value=mock_page):
            result = discover_company_website(profile, fetcher=fetcher, budget=budget)
            self.assertEqual(result.status, DiscoveryVerdictStatus.VERIFIED)
            self.assertEqual(result.url, "https://norskfiske.no/")
            self.assertIn("BRREG", result.decision_reason)

    def test_discovery_pipeline_search_candidate(self):
        profile = self._make_profile(website="")  # No registry website
        fetcher = SafeHttpFetcher()
        budget = RequestBudget()

        search_payload = {
            "web": {
                "results": [
                    {"url": "https://norskfiske.no/", "title": "Norsk Fiskeeksport AS - Forside", "description": "Norsk Fiskeeksport AS org 923609016"},
                ]
            }
        }
        mock_search = lambda q: search_payload

        mock_page = DiscoveryFetchResult(
            url="https://norskfiske.no/",
            final_url="https://norskfiske.no/",
            status_code=200,
            content=b"html",
            html="<html></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="Norsk Fiskeeksport AS org 923 609 016.",
            content_sha256="abc",
            error=None,
            redirects_count=0,
            elapsed_ms=25,
        )

        with patch.object(fetcher, "fetch_page", return_value=mock_page):
            result = discover_company_website(profile, search_func=mock_search, fetcher=fetcher, budget=budget)
            self.assertEqual(result.status, DiscoveryVerdictStatus.VERIFIED)
            self.assertEqual(result.url, "https://norskfiske.no/")
            self.assertIn("search discovery", result.decision_reason)

    def test_discovery_pipeline_safe_abstention_on_conflict(self):
        profile = self._make_profile(website="")
        fetcher = SafeHttpFetcher()
        budget = RequestBudget()

        search_payload = {
            "web": {
                "results": [
                    {"url": "https://wrongfiske.no/", "title": "Norsk Fiskeeksport AS", "description": "Norsk Fiskeeksport"},
                ]
            }
        }
        mock_search = lambda q: search_payload

        # Page has conflicting org number
        mock_page = DiscoveryFetchResult(
            url="https://wrongfiske.no/",
            final_url="https://wrongfiske.no/",
            status_code=200,
            content=b"html",
            html="<html></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="Norsk Fiskeeksport AS org 987 654 321. Another entity entirely.",
            content_sha256="abc",
            error=None,
            redirects_count=0,
            elapsed_ms=25,
        )

        with patch.object(fetcher, "fetch_page", return_value=mock_page):
            result = discover_company_website(profile, search_func=mock_search, fetcher=fetcher, budget=budget)
            self.assertEqual(result.status, DiscoveryVerdictStatus.ABSTAIN)
            self.assertIsNone(result.url)
            self.assertTrue(any("abstain" in r.lower() for r in result.reasons))

    def test_discovery_pipeline_budget_exhaustion(self):
        profile = self._make_profile(website="")
        fetcher = SafeHttpFetcher()
        # Budget already exhausted
        budget = RequestBudget(max_total_requests=0)

        result = discover_company_website(profile, search_func=lambda q: {}, fetcher=fetcher, budget=budget)
        self.assertEqual(result.status, DiscoveryVerdictStatus.ABSTAIN)
        self.assertIn("budget exhausted", result.decision_reason.lower())

    def test_deterministic_repeated_results(self):
        profile = self._make_profile(website="https://norskfiske.no/")
        mock_page = DiscoveryFetchResult(
            url="https://norskfiske.no/",
            final_url="https://norskfiske.no/",
            status_code=200,
            content=b"html",
            html="<html></html>",
            title="Norsk Fiskeeksport AS",
            meta_description="",
            text_excerpt="Norsk Fiskeeksport AS org nr 923 609 016.",
            content_sha256="abc",
            error=None,
            redirects_count=0,
            elapsed_ms=25,
        )

        runs = []
        for _ in range(5):
            fetcher = SafeHttpFetcher()
            budget = RequestBudget()
            with patch.object(fetcher, "fetch_page", return_value=mock_page):
                res = discover_company_website(profile, fetcher=fetcher, budget=budget).to_dict()
                runs.append(res)

        for i in range(1, len(runs)):
            self.assertEqual(runs[0], runs[i], f"Non-deterministic discovery result at run {i + 1}")


class Stage3ProfileExtractionTests(unittest.TestCase):
    """Stage 3: Company Profile Extraction tests."""

    def _make_base_profile(self, **kwargs):
        base = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "municipality": "Bergen",
            "industry_code": "03.111",
            "industry_label": "Havfiske",
            "employees": 42,
            "evidence": {},
        }
        base.update(kwargs)
        return base

    def test_description_extraction(self):
        profile = self._make_base_profile()

        # 1. Description from JSON-LD
        structured = {
            "json-ld": [{
                "@type": "Organization",
                "name": "Norsk Fiskeeksport AS",
                "description": "Ledende eksportør av førsteklasses norsk villfisk til det globale markedet.",
            }]
        }
        website_val = {"final_url": "https://norskfiske.no/", "pages": []}
        desc_field = extract_description(profile, website_val, structured, "https://norskfiske.no/")
        self.assertEqual(desc_field.status, FieldStatus.FOUND)
        self.assertIn("Ledende eksportør", desc_field.value or "")
        self.assertEqual(desc_field.source_type, "website_jsonld")
        self.assertGreater(desc_field.confidence, 0.9)

        # 2. Description from meta description
        meta_website = {
            "final_url": "https://norskfiske.no/",
            "description": "Norsk Fiskeeksport AS leverer bærekraftig sjømat fra Norskehavet.",
            "pages": [],
        }
        desc_meta = extract_description(profile, meta_website, {"json-ld": []}, "https://norskfiske.no/")
        self.assertEqual(desc_meta.status, FieldStatus.FOUND)
        self.assertIn("bærekraftig sjømat", desc_meta.value or "")
        self.assertEqual(desc_meta.source_type, "website_meta_description")

        # 3. Description from about page text
        about_website = {
            "final_url": "https://norskfiske.no/",
            "pages": [{
                "url": "https://norskfiske.no/om-oss",
                "main_text_excerpt": "Vi ble etablert i 1995 og har vokst til å bli en anerkjent leverandør av fersk fisk.",
            }],
        }
        desc_about = extract_description(profile, about_website, {"json-ld": []}, "https://norskfiske.no/")
        self.assertEqual(desc_about.status, FieldStatus.FOUND)
        self.assertIn("anerkjent leverandør", desc_about.value or "")
        self.assertEqual(desc_about.source_type, "website_about_page")

        # 4. Fallback to registry industry label when website is unavailable
        desc_fallback = extract_description(profile, None, {}, None)
        self.assertEqual(desc_fallback.status, FieldStatus.FOUND)
        self.assertEqual(desc_fallback.source_type, "official_registry")
        self.assertIn("Havfiske", desc_fallback.value or "")

        # 5. Not found when website inspected but empty
        empty_website = {"final_url": "https://empty.no/", "pages": []}
        desc_empty = extract_description({"name": "Empty AS"}, empty_website, {"json-ld": []}, "https://empty.no/")
        self.assertEqual(desc_empty.status, FieldStatus.NOT_FOUND)
        self.assertIsNone(desc_empty.value)

    def test_industry_extraction(self):
        # 1. Authoritative BRREG NACE industry
        profile = self._make_base_profile()
        ind_field = extract_industry(profile, None, {}, None)
        self.assertEqual(ind_field.status, FieldStatus.FOUND)
        self.assertEqual(ind_field.value["code"], "03.111")
        self.assertEqual(ind_field.value["label"], "Havfiske")
        self.assertEqual(ind_field.source_type, "official_registry")
        self.assertEqual(ind_field.confidence, 1.0)

        # 2. Schema.org JSON-LD industry
        structured = {
            "json-ld": [{
                "@type": "Organization",
                "name": "Tech Corp AS",
                "industry": "Software Development & AI",
            }]
        }
        ind_structured = extract_industry({"name": "Tech Corp AS"}, {"final_url": "https://tech.no/"}, structured, "https://tech.no/")
        self.assertEqual(ind_structured.status, FieldStatus.FOUND)
        self.assertIn("Software Development", ind_structured.value["label"])
        self.assertEqual(ind_structured.source_type, "website_jsonld")

        # 3. Unavailable when no source available
        ind_unavail = extract_industry({}, None, {}, None)
        self.assertEqual(ind_unavail.status, FieldStatus.UNAVAILABLE)
        self.assertIsNone(ind_unavail.value)

    def test_contact_extraction_and_normalization(self):
        profile = self._make_base_profile(
            business_address={"adresse": ["Strandgaten 12"], "postnummer": "5004", "poststed": "Bergen", "land": "Norge"}
        )
        website_val = {
            "final_url": "https://norskfiske.no/",
            "main_text_excerpt": "Kontakt oss på post@norskfiske.no eller telefon +47 55 12 34 56. Besøk oss i 5004 Bergen.",
            "pages": [],
        }
        contact_field = extract_contact(profile, website_val, {"json-ld": []}, "https://norskfiske.no/")
        self.assertEqual(contact_field.status, FieldStatus.FOUND)
        self.assertEqual(contact_field.value["email"], "post@norskfiske.no")
        self.assertIn("55 12 34 56", contact_field.value["phone"])
        self.assertEqual(contact_field.value["postal_code"], "5004")
        self.assertEqual(contact_field.value["city"], "Bergen")
        self.assertEqual(contact_field.value["address"], "Strandgaten 12")

        # Test unavailable vs not found
        contact_unavail = extract_contact({}, None, {}, None)
        self.assertEqual(contact_unavail.status, FieldStatus.UNAVAILABLE)

        contact_empty = extract_contact({"name": "No Contact AS"}, {"final_url": "https://nocontact.no/", "pages": []}, {"json-ld": []}, "https://nocontact.no/")
        self.assertEqual(contact_empty.status, FieldStatus.NOT_FOUND)

    def test_multiple_locations_extraction_and_deduplication(self):
        # 1. From official subunits
        profile = self._make_base_profile(
            evidence={
                "locations": {
                    "value": {
                        "locations": [
                            {"name": "Avdeling Bergen", "address": {"adresse": "Kai 4", "postnummer": "5003", "poststed": "Bergen"}},
                            {"name": "Avdeling Tromsø", "address": {"adresse": "Havnegata 1", "postnummer": "9008", "poststed": "Tromsø"}},
                            # Duplicate of Bergen
                            {"name": "Avdeling Bergen", "address": {"adresse": "Kai 4", "postnummer": "5003", "poststed": "Bergen"}},
                        ]
                    }
                }
            }
        )
        loc_field = extract_locations(profile, None, {}, None)
        self.assertEqual(loc_field.status, FieldStatus.FOUND)
        self.assertEqual(len(loc_field.value), 2, "Duplicate locations must be deduplicated")
        cities = [l["city"] for l in loc_field.value]
        self.assertIn("Bergen", cities)
        self.assertIn("Tromsø", cities)

    def test_leadership_extraction_and_filtering(self):
        # Official roles with leadership titles and non-leadership staff
        profile = self._make_base_profile(
            evidence={
                "roles": {
                    "value": {
                        "roles": [
                            {"name": "Ola Nordmann", "role": "Daglig leder", "inactive": False},
                            {"name": "Kari Nordmann", "role": "Styreleder", "inactive": False},
                            {"name": "Per Hansen", "role": "Varamedlem", "inactive": False},  # Non-leadership role
                            {"name": "Inaktiv Leder", "role": "Daglig leder", "inactive": True},  # Inactive
                        ]
                    }
                }
            }
        )
        lead_field = extract_leadership(profile, None, {}, None)
        self.assertEqual(lead_field.status, FieldStatus.FOUND)
        names = [p["name"] for p in lead_field.value]
        self.assertIn("Ola Nordmann", names)
        self.assertIn("Kari Nordmann", names)
        self.assertNotIn("Per Hansen", names, "Non-leadership roles must be excluded")
        self.assertNotIn("Inaktiv Leder", names, "Inactive roles must be excluded")

    def test_employee_count_extraction_and_ranges(self):
        # 1. BRREG exact count
        profile = self._make_base_profile(employees=42)
        emp_reg = extract_employees(profile, None, {}, None)
        self.assertEqual(emp_reg.status, FieldStatus.FOUND)
        self.assertEqual(emp_reg.value, 42)
        self.assertEqual(emp_reg.source_type, "official_registry")

        # 2. JSON-LD range
        structured_range = {
            "json-ld": [{
                "@type": "Organization",
                "numberOfEmployees": {"@type": "QuantitativeValue", "minValue": 10, "maxValue": 50},
            }]
        }
        emp_range = extract_employees({"name": "Range AS"}, {"final_url": "https://range.no/"}, structured_range, "https://range.no/")
        self.assertEqual(emp_range.status, FieldStatus.FOUND)
        self.assertEqual(emp_range.value, "10-50")
        self.assertEqual(emp_range.source_type, "website_jsonld")

        # 3. Website text exact
        website_text = {"final_url": "https://text.no/", "main_text_excerpt": "Vi er i dag 25 ansatte fordelt på to kontorer.", "pages": []}
        emp_text = extract_employees({"name": "Text AS"}, website_text, {"json-ld": []}, "https://text.no/")
        self.assertEqual(emp_text.status, FieldStatus.FOUND)
        self.assertEqual(emp_text.value, 25)
        self.assertEqual(emp_text.source_type, "website_text")

    def test_careers_detection(self):
        # 1. Active careers page with job openings
        website_careers = {
            "final_url": "https://norskfiske.no/",
            "pages": [{
                "url": "https://norskfiske.no/karriere",
                "main_text_excerpt": "Bli en del av vårt team! Vi søker dyktige medarbeidere:\n- Senior Eksportansvarlig\n- Kvalitetskontrollør",
            }],
        }
        careers_field = extract_careers({"name": "Norsk Fiskeeksport AS"}, website_careers, "https://norskfiske.no/")
        self.assertEqual(careers_field.status, FieldStatus.FOUND)
        self.assertTrue(careers_field.value["has_careers_page"])
        self.assertTrue(careers_field.value["hiring_active"])
        self.assertIn("Senior Eksportansvarlig", careers_field.value["openings"])

        # 2. Careers page with no open positions
        website_no_jobs = {
            "final_url": "https://norskfiske.no/",
            "pages": [{
                "url": "https://norskfiske.no/karriere",
                "main_text_excerpt": "Vi har for øyeblikket ingen ledige stillinger.",
            }],
        }
        careers_no_jobs = extract_careers({"name": "Norsk Fiskeeksport AS"}, website_no_jobs, "https://norskfiske.no/")
        self.assertEqual(careers_no_jobs.status, FieldStatus.FOUND)
        self.assertTrue(careers_no_jobs.value["has_careers_page"])
        self.assertFalse(careers_no_jobs.value["hiring_active"])

        # 3. No careers page
        website_bare = {"final_url": "https://bare.no/", "pages": []}
        careers_bare = extract_careers({"name": "Bare AS"}, website_bare, "https://bare.no/")
        self.assertFalse(careers_bare.value["has_careers_page"])

    def test_news_activity_extraction(self):
        website_news = {
            "final_url": "https://norskfiske.no/",
            "pages": [
                {
                    "url": "https://norskfiske.no/nyheter/ny-fiskebat-kontrakt",
                    "title": "Inngår ny kontrakt for fiskebåtleveranse",
                    "main_text_excerpt": "2024-04-15: Norsk Fiskeeksport AS har i dag signert en ny avtale.",
                },
                {
                    "url": "https://norskfiske.no/aktuelt/aarsresultat-2023",
                    "title": "Rekordresultat for 2023",
                    "main_text_excerpt": "2024-02-28: Selskapet oppnådde solid vekst i fjor.",
                },
            ],
        }
        news_field = extract_news({"name": "Norsk Fiskeeksport AS"}, website_news, "https://norskfiske.no/")
        self.assertEqual(news_field.status, FieldStatus.FOUND)
        self.assertEqual(len(news_field.value), 2)
        titles = [item["title"] for item in news_field.value]
        self.assertIn("Inngår ny kontrakt for fiskebåtleveranse", titles)
        self.assertEqual(news_field.value[0]["date"], "2024-04-15")

    def test_structured_data_jsonld_integration(self):
        raw_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Norsk Fiskeeksport AS</title>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Corporation",
                "name": "Norsk Fiskeeksport AS",
                "description": "Totalleverandør av fersk og frossen fisk fra Vestlandet.",
                "telephone": "+47 55 99 88 77",
                "email": "kontakt@norskfiske.no",
                "numberOfEmployees": 45,
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "Skuteviksbodene 1",
                    "postalCode": "5035",
                    "addressLocality": "Bergen",
                    "addressCountry": "Norge"
                },
                "founder": {
                    "@type": "Person",
                    "name": "Lars Fisker",
                    "jobTitle": "Founder & Managing Director"
                }
            }
            </script>
        </head>
        <body>
            <h1>Velkommen</h1>
        </body>
        </html>
        """
        profile = self._make_base_profile()
        extracted = extract_company_profile(profile, html=raw_html)

        self.assertEqual(extracted.description.status, FieldStatus.FOUND)
        self.assertIn("Totalleverandør", extracted.description.value or "")
        self.assertEqual(extracted.contact.value["email"], "kontakt@norskfiske.no")
        self.assertEqual(extracted.contact.value["phone"], "+47 55 99 88 77")
        self.assertEqual(extracted.contact.value["postal_code"], "5035")
        self.assertEqual(extracted.employees.value, 42, "Authoritative BRREG employee count must be preserved")
        self.assertTrue(any(p["name"] == "Lars Fisker" for p in extracted.leadership.value))
        self.assertGreater(extracted.structured_data_summary["json_ld_entities_count"], 0)

    def test_evidence_spans_and_provenance(self):
        profile = self._make_base_profile()
        website_val = {
            "final_url": "https://norskfiske.no/",
            "description": "Bærekraftig eksport av sjømat fra Norge.",
            "main_text_excerpt": "Kontakt: info@norskfiske.no",
            "pages": [],
        }
        profile["evidence"]["website"] = {"status": "available", "value": website_val}

        extracted = extract_company_profile(profile)
        # Every found field must have evidence_span and source_url
        for field_obj in (extracted.description, extracted.industry, extracted.contact, extracted.employees):
            if field_obj.status == FieldStatus.FOUND:
                self.assertIsNotNone(field_obj.evidence_span)
                self.assertIsNotNone(field_obj.source_url)
                self.assertGreater(field_obj.confidence, 0.0)

    def test_missing_vs_unavailable_handling(self):
        # Empty profile with no evidence
        profile = {"organisation_number": "999999999", "name": "Spøkelse AS", "evidence": {}}
        extracted = extract_company_profile(profile)

        self.assertEqual(extracted.description.status, FieldStatus.UNAVAILABLE)
        self.assertEqual(extracted.industry.status, FieldStatus.UNAVAILABLE)
        self.assertEqual(extracted.contact.status, FieldStatus.UNAVAILABLE)
        self.assertEqual(extracted.employees.status, FieldStatus.UNAVAILABLE)
        self.assertEqual(extracted.careers.status, FieldStatus.UNAVAILABLE)
        self.assertEqual(extracted.news.status, FieldStatus.UNAVAILABLE)

        # Profile with empty website crawled
        profile_with_empty_web = {
            "organisation_number": "999999999",
            "name": "Spøkelse AS",
            "evidence": {"website": {"status": "available", "value": {"final_url": "https://empty.test/", "pages": []}}},
        }
        extracted_empty = extract_company_profile(profile_with_empty_web)
        self.assertEqual(extracted_empty.description.status, FieldStatus.NOT_FOUND)
        self.assertEqual(extracted_empty.contact.status, FieldStatus.NOT_FOUND)
        self.assertEqual(extracted_empty.employees.status, FieldStatus.NOT_FOUND)
        self.assertEqual(extracted_empty.news.status, FieldStatus.NOT_FOUND)

    def test_malformed_partial_pages(self):
        # Broken HTML should not raise unhandled exceptions
        broken_html = "<html><head><title>Broken<script>invalid json ld</script></head><body><<>>"
        profile = self._make_base_profile()
        extracted = extract_company_profile(profile, html=broken_html)
        self.assertEqual(extracted.overall_status, "complete")
        self.assertIsNotNone(extracted.description)


class Stage4FinancialIntelligenceTests(unittest.TestCase):
    """Stage 4: Financial Intelligence tests."""

    def _make_sample_accounts_body(self):
        return [
            {
                "id": 101,
                "regnskapstype": "SELSKAP",
                "valuta": "NOK",
                "regnskapsperiode": {
                    "fraDato": "2024-01-01",
                    "tilDato": "2024-12-31",
                },
                "resultatregnskapResultat": {
                    "driftsresultat": {
                        "driftsinntekter": {"sumDriftsinntekter": 100000000},
                        "driftsresultat": 15000000,
                    },
                    "ordinaertResultatFoerSkattekostnad": 14000000,
                    "aarsresultat": 10500000,
                },
                "eiendeler": {"sumEiendeler": 85000000},
                "egenkapitalGjeld": {
                    "egenkapital": {"sumEgenkapital": 45000000},
                    "gjeldOversikt": {"sumGjeld": 40000000},
                },
            },
            {
                "id": 102,
                "regnskapstype": "KONSERN",
                "valuta": "NOK",
                "regnskapsperiode": {
                    "fraDato": "2024-01-01",
                    "tilDato": "2024-12-31",
                },
                "resultatregnskapResultat": {
                    "driftsresultat": {
                        "driftsinntekter": {"sumDriftsinntekter": 180000000},
                        "driftsresultat": 25000000,
                    },
                    "ordinaertResultatFoerSkattekostnad": 23000000,
                    "aarsresultat": 17500000,
                },
                "eiendeler": {"sumEiendeler": 150000000},
                "egenkapitalGjeld": {
                    "egenkapital": {"sumEgenkapital": 75000000},
                    "gjeldOversikt": {"sumGjeld": 75000000},
                },
            },
        ]

    def test_official_accounts_extraction(self):
        body = self._make_sample_accounts_body()
        statements = extract_official_accounts(body, "923609016")

        self.assertEqual(len(statements), 2)
        stmt = statements[0]  # Standalone SELSKAP sorted first
        self.assertEqual(stmt.account_type, FinancialAccountType.SELSKAP.value)
        self.assertEqual(stmt.currency, "NOK")
        self.assertEqual(stmt.period.year, 2024)
        self.assertEqual(stmt.period.months, 12)

        # Revenue
        self.assertEqual(stmt.revenue.status, FieldStatus.FOUND)
        self.assertEqual(stmt.revenue.value, 100000000)

        # Operating profit (driftsresultat)
        self.assertEqual(stmt.operating_profit.status, FieldStatus.FOUND)
        self.assertEqual(stmt.operating_profit.value, 15000000)

        # Profit before tax
        self.assertEqual(stmt.profit_before_tax.status, FieldStatus.FOUND)
        self.assertEqual(stmt.profit_before_tax.value, 14000000)

        # Net profit (årsresultat)
        self.assertEqual(stmt.net_profit.status, FieldStatus.FOUND)
        self.assertEqual(stmt.net_profit.value, 10500000)

        # Assets & Equity
        self.assertEqual(stmt.total_assets.status, FieldStatus.FOUND)
        self.assertEqual(stmt.total_assets.value, 85000000)
        self.assertEqual(stmt.total_equity.status, FieldStatus.FOUND)
        self.assertEqual(stmt.total_equity.value, 45000000)
        self.assertEqual(stmt.total_debt.status, FieldStatus.FOUND)
        self.assertEqual(stmt.total_debt.value, 40000000)

    def test_zero_vs_missing_financial_values(self):
        """CRITICAL: Explicit zero must be preserved as 0, missing must be None (never 0)."""
        body_with_zero = [
            {
                "id": 201,
                "regnskapstype": "SELSKAP",
                "valuta": "NOK",
                "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
                "revenue": 0,  # Explicit zero revenue
                "operating_result": 0,  # Explicit break-even
                "profit_before_tax": None,  # Not reported
                "annual_result": None,  # Not reported
            }
        ]
        statements = extract_official_accounts(body_with_zero, "923609016")
        stmt = statements[0]

        # Explicit 0 is FOUND with value 0
        self.assertEqual(stmt.revenue.status, FieldStatus.FOUND)
        self.assertEqual(stmt.revenue.value, 0)
        self.assertEqual(stmt.operating_profit.status, FieldStatus.FOUND)
        self.assertEqual(stmt.operating_profit.value, 0)

        # Missing metric is NOT_FOUND with value None, NEVER 0!
        self.assertEqual(stmt.profit_before_tax.status, FieldStatus.NOT_FOUND)
        self.assertIsNone(stmt.profit_before_tax.value)
        self.assertNotEqual(stmt.profit_before_tax.value, 0, "Missing metric must NEVER be converted to zero")

        self.assertEqual(stmt.net_profit.status, FieldStatus.NOT_FOUND)
        self.assertIsNone(stmt.net_profit.value)
        self.assertNotEqual(stmt.net_profit.value, 0, "Missing metric must NEVER be converted to zero")

    def test_negative_financial_values(self):
        """Verify operating loss and net loss are accurately preserved as negative numbers."""
        body_loss = [
            {
                "id": 301,
                "regnskapstype": "SELSKAP",
                "valuta": "NOK",
                "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
                "revenue": 5000000,
                "operating_result": -1200000,  # Operating loss
                "profit_before_tax": -1300000,
                "annual_result": -1500000,  # Net loss
            }
        ]
        statements = extract_official_accounts(body_loss, "923609016")
        stmt = statements[0]

        self.assertEqual(stmt.operating_profit.status, FieldStatus.FOUND)
        self.assertEqual(stmt.operating_profit.value, -1200000)
        self.assertEqual(stmt.net_profit.status, FieldStatus.FOUND)
        self.assertEqual(stmt.net_profit.value, -1500000)

    def test_reporting_period_parsing(self):
        # 1. Full standard 12-month period
        p1 = {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}
        stmts1 = extract_official_accounts([{"regnskapsperiode": p1}], "923609016")
        self.assertEqual(stmts1[0].period.year, 2024)
        self.assertEqual(stmts1[0].period.months, 12)

        # 2. Shortened 6-month stub period
        p2 = {"fraDato": "2024-07-01", "tilDato": "2024-12-31"}
        stmts2 = extract_official_accounts([{"regnskapsperiode": p2}], "923609016")
        self.assertEqual(stmts2[0].period.year, 2024)
        self.assertEqual(stmts2[0].period.months, 6)

        # 3. Simple year string
        stmts3 = extract_official_accounts([{"regnskapsperiode": "2023"}], "923609016")
        self.assertEqual(stmts3[0].period.year, 2023)
        self.assertEqual(stmts3[0].period.months, 12)

    def test_selskap_vs_konsern_distinction(self):
        body = self._make_sample_accounts_body()
        statements = extract_official_accounts(body, "923609016")

        # Standalone SELSKAP statement must be sorted first for exact entity identity
        self.assertEqual(statements[0].account_type, FinancialAccountType.SELSKAP.value)
        self.assertEqual(statements[0].revenue.value, 100000000)

        # Consolidated KONSERN statement must follow
        self.assertEqual(statements[1].account_type, FinancialAccountType.KONSERN.value)
        self.assertEqual(statements[1].revenue.value, 180000000)

    def test_accounting_obligation_integration(self):
        # 1. AS: Always obliged
        as_profile = {"organisation_number": "923609016", "name": "Test AS", "legal_form": "AS"}
        fin_as = build_company_financial_profile(as_profile)
        self.assertEqual(fin_as.accounting_obligation["value"]["classification"], "required_by_legal_form")

        # 2. ENK: Threshold or activity dependent
        enk_profile = {"organisation_number": "923609017", "name": "Test ENK", "legal_form": "ENK", "employees": 0}
        fin_enk = build_company_financial_profile(enk_profile)
        self.assertEqual(fin_enk.accounting_obligation["value"]["classification"], "threshold_or_activity_dependent")
        self.assertEqual(fin_enk.overall_status, "exempt_or_threshold_dependent")

    def test_financial_history_and_pdf_links(self):
        history = ["2022", "2024", "2023", "invalid"]
        pdfs = extract_financial_pdfs(history, "923609016")

        self.assertEqual(len(pdfs), 3)
        years = [p.year for p in pdfs]
        self.assertEqual(years, ["2024", "2023", "2022"], "PDFs must be sorted descending by year")
        self.assertTrue(pdfs[0].is_official_filing)
        self.assertTrue(pdfs[0].url.endswith("/923609016/2024"))

    def test_website_annual_report_pdf_detection(self):
        website_val = {
            "final_url": "https://norskfiske.no/",
            "pages": [
                {"url": "https://norskfiske.no/investor/aarsrapport-2023.pdf"},
                {"url": "https://norskfiske.no/media/produktkatalog.pdf"},  # Non-financial
                {"url": "https://norskfiske.no/ir/delarsrapport-q2-2024.pdf"},
            ],
        }
        pdfs = extract_financial_pdfs([], "923609016", website_value=website_val)

        urls = [p.url for p in pdfs]
        self.assertIn("https://norskfiske.no/investor/aarsrapport-2023.pdf", urls)
        self.assertIn("https://norskfiske.no/ir/delarsrapport-q2-2024.pdf", urls)
        self.assertNotIn("https://norskfiske.no/media/produktkatalog.pdf", urls)

        ar = next(p for p in pdfs if "aarsrapport-2023" in p.url)
        self.assertEqual(ar.year, "2023")
        self.assertEqual(ar.document_type, "annual_report")
        self.assertEqual(ar.source_type, "company_website_ir")
        self.assertFalse(ar.is_official_filing)

    def test_pdf_exact_entity_verification(self):
        # PDF text containing numbers but missing the 9-digit org number -> reject
        unverified_text = """
        ÅRSRAPPORT 2023
        Driftsinntekter: 50 000 000
        Driftsresultat: 5 000 000
        Årsresultat: 3 000 000
        """
        stmt_rejected = extract_financials_from_pdf(unverified_text, "923609016", "2023", "https://example.test/ar.pdf")
        self.assertIsNone(stmt_rejected, "PDF without exact org number must be rejected to prevent entity confusion")

        # PDF text containing the exact 9-digit org number -> accept
        verified_text = f"""
        Norsk Fiskeeksport AS
        Organisasjonsnummer: 923 609 016
        ÅRSRAPPORT 2023
        Driftsinntekter: 50 000 000
        Driftsresultat: 5 000 000
        Årsresultat: 3 000 000
        Sum eiendeler: 70 000 000
        Sum egenkapital: 35 000 000
        """
        stmt_accepted = extract_financials_from_pdf(verified_text, "923609016", "2023", "https://example.test/ar.pdf")
        self.assertIsNotNone(stmt_accepted)
        self.assertEqual(stmt_accepted.revenue.value, 50000000)
        self.assertEqual(stmt_accepted.operating_profit.value, 5000000)
        self.assertEqual(stmt_accepted.net_profit.value, 3000000)
        self.assertEqual(stmt_accepted.total_assets.value, 70000000)
        self.assertEqual(stmt_accepted.total_equity.value, 35000000)

    def test_pdf_text_financial_extraction(self):
        # Test TNOK multiplier detection ("tall i tusen")
        tnok_text = """
        Equinor AS
        Org.nr: 923 609 016
        Årsregnskap 2023 (Tall i tusen kroner)
        Sum driftsinntekter: 45 000
        Driftsresultat: 8 500
        Ordinært resultat før skattekostnad: 8 000
        Årsresultat: 6 200
        Sum eiendeler: 120 000
        Sum egenkapital: 65 000
        Sum gjeld: 55 000
        """
        stmt = extract_financials_from_pdf(tnok_text, "923609016", "2023", "https://example.test/ar.pdf")
        self.assertIsNotNone(stmt)
        self.assertEqual(stmt.revenue.value, 45000000)
        self.assertEqual(stmt.operating_profit.value, 8500000)
        self.assertEqual(stmt.profit_before_tax.value, 8000000)
        self.assertEqual(stmt.net_profit.value, 6200000)
        self.assertEqual(stmt.total_assets.value, 120000000)
        self.assertEqual(stmt.total_equity.value, 65000000)
        self.assertEqual(stmt.total_debt.value, 55000000)

    def test_evidence_spans_and_source_attribution(self):
        body = self._make_sample_accounts_body()
        statements = extract_official_accounts(body, "923609016")
        stmt = statements[0]

        for field_obj in (stmt.revenue, stmt.operating_profit, stmt.profit_before_tax, stmt.net_profit, stmt.total_assets, stmt.total_equity, stmt.total_debt):
            self.assertEqual(field_obj.status, FieldStatus.FOUND)
            self.assertIsNotNone(field_obj.evidence_span)
            self.assertIsNotNone(field_obj.source_url)
            self.assertEqual(field_obj.source_type, "official_regnskapsregisteret")
            self.assertEqual(field_obj.confidence, 1.0)

    def test_missing_accounts_honest_abstention(self):
        # Empty profile with no accounts and no PDFs
        empty_profile = {"organisation_number": "999999999", "name": "Spøkelse AS", "legal_form": "AS"}
        fin_profile = build_company_financial_profile(empty_profile)

        self.assertIsNone(fin_profile.latest_accounts)
        self.assertEqual(len(fin_profile.historical_accounts), 0)
        self.assertEqual(len(fin_profile.financial_pdfs), 0)
        self.assertEqual(fin_profile.overall_status, "no_accounts_available")

    def test_deterministic_financial_results(self):
        profile = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "legal_form": "AS",
            "evidence": {
                "accounting_obligation": accounting_obligation_assessment({"legal_form": "AS", "organisation_number": "923609016"}),
                "financials": {"status": "available", "value": self._make_sample_accounts_body()},
                "financial_history": {"status": "available", "value": ["2023", "2024"]},
            },
        }
        runs = []
        for _ in range(5):
            runs.append(build_company_financial_profile(profile).to_dict())

        for i in range(1, len(runs)):
            self.assertEqual(runs[0], runs[i], f"Non-deterministic financial profile at run {i + 1}")


if __name__ == "__main__":
    unittest.main()




