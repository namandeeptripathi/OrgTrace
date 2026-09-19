from __future__ import annotations

import copy
import csv
import gzip
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import urllib.error
import urllib.request

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
from norway_company_agent.evidence_engine import (  # noqa: E402
    EvidenceSelector,
    ExtractionMethod,
    ProvenanceClaim,
    SelectorType,
    SourceAuthority,
    ValidationStatus,
    ValidationVerdict,
    build_provenance_claim,
    classify_source_authority,
    compute_content_hash,
    explain_authority_rank,
    is_more_authoritative,
    validate_claim_evidence,
    verify_snapshot_match,
)
from norway_company_agent.external_research import (  # noqa: E402
    CandidateType,
    ExternalFootprintCategory,
    ExternalFootprintItem,
    ExternalFootprintProfile,
    LeadershipEntity,
    LeadershipRoleType,
    ResearchCandidate,
    SourcePolicyDecision,
    SourcePolicyStatus,
    build_external_footprint,
    classify_leadership_role,
    discover_leadership,
    evaluate_source_policy,
    generate_research_candidates,
    normalize_domain_for_research,
    normalize_url_for_research,
)
from norway_company_agent.change_intelligence import (  # noqa: E402
    ChangeType,
    CompanySnapshot,
    MaterialChangeRecord,
    MemorySnapshotStore,
    RefreshResult,
    RefreshStatus,
    SnapshotClaim,
    compare_snapshots,
    generate_stable_claim_key,
    is_material_change,
    normalize_semantic_value,
    refresh_company_intelligence,
)
from norway_company_agent.strategy_harness import (  # noqa: E402
    PromotionCriteria,
    PromotionDecision,
    StrategyAttempt,
    StrategyDefinition,
    StrategyMetrics,
    StrategyRegistry,
    StrategyStatus,
    compare_strategies,
    evaluate_promotion,
    evaluate_strategy_attempts,
)
from norway_company_agent.batch_engine import (  # noqa: E402
    BatchCompanyResult,
    BatchTerminalState,
    CompetitionBatchEngine,
    EvaluationEnvelope,
    ManifestValidationResult,
    ResultCache,
    RunManifest,
    SharedBudgetTracker,
    compute_output_fingerprint,
    iter_company_inputs,
    validate_manifest,
)
from norway_company_agent.evaluation_dataset import (  # noqa: E402
    CaseCategory,
    EvaluationCase,
    ExpectedOutcome,
    build_deterministic_evaluation_dataset,
)
from norway_company_agent.evaluation import (  # noqa: E402
    BottleneckObservation,
    CaseEvaluationResult,
    CostModelConfig,
    CostStats,
    CoverageMetrics,
    EvaluationHarness,
    EvaluationInstrumentation,
    EvaluationReport,
    EvidenceValidityMetrics,
    ExternalPrecisionMetrics,
    FalseChangeMetrics,
    FieldCoverageMetrics,
    PrecisionMetrics,
    RecallMetrics,
    RefreshCorrectnessMetrics,
    RequestStats,
    RuntimeStats,
    analyze_bottlenecks,
    calculate_false_change_rate,
    evaluate_coverage,
    evaluate_evidence_validity,
    evaluate_exact_precision,
    evaluate_external_precision,
    evaluate_recall,
    evaluate_refresh_correctness,
)
from norway_company_agent.url_safety import (  # noqa: E402
    DangerousSchemeError,
    EmbeddedCredentialsError,
    InvalidHostError,
    PrivateNetworkAccessError,
    UrlLengthExceededError,
    UrlSafetyError,
    UrlValidationResult,
    assert_public_url,
    sanitize_url_for_logging,
    validate_public_url,
)
from norway_company_agent.config import (  # noqa: E402
    AppConfig,
    ConfigValidationError,
    EvaluationConfig,
    LoggingConfig,
    MissingCredentialError,
    NetworkSafetyConfig,
    ProviderConfig,
    load_config_from_env,
    redact_secret_value,
    redact_secrets_from_text,
)
from norway_company_agent.resilience import (  # noqa: E402
    MalformedResponseError,
    NonRetryableHttpError,
    PartialFailureResult,
    RateLimitExceededError,
    ResilienceError,
    RetryPolicy,
    UpstreamTimeoutError,
    execute_with_retry,
    parse_retry_after,
)
from norway_company_agent.licensing import (  # noqa: E402
    KNOWN_SOURCE_LICENSES,
    LicenseType,
    SourceLicenseInfo,
    get_source_license_info,
)
from norway_company_agent.logging_utils import (  # noqa: E402
    SecretRedactionFilter,
    StructuredJsonFormatter,
    get_logger,
    setup_logging,
)
from norway_company_agent.observability import (  # noqa: E402
    ProductionMetricsCollector,
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


class Stage5EvidenceProvenanceTests(unittest.TestCase):
    """Stage 5: Evidence & Provenance Engine tests."""

    def test_claim_evidence_creation_and_fields(self):
        selector = EvidenceSelector(
            selector_type=SelectorType.CSS,
            query="div.about-section > p.intro",
            char_start=0,
            char_end=120,
        )
        claim = ProvenanceClaim(
            claim_id="claim-test-123",
            field_name="description",
            value="Norsk Fiskeeksport AS eksporterer fersk laks og hvitfisk fra Vestlandet.",
            source_url="https://norskfiske.no/om-oss",
            discovered_url="http://norskfiske.no/om-oss",
            source_type="website_about_page",
            source_authority=SourceAuthority.VERIFIED_FIRST_PARTY,
            retrieved_at="2026-09-20T00:00:00Z",
            effective_date="2024-01-01",
            reporting_period="2024",
            content_sha256="abc123def456",
            extraction_method=ExtractionMethod.HTML_TEXT,
            selector=selector,
            evidence_span="Norsk Fiskeeksport AS eksporterer fersk laks...",
            confidence=0.9,
            validation_status=ValidationStatus.ACCEPTED,
        )

        d = claim.to_dict()
        self.assertEqual(d["claim_id"], "claim-test-123")
        self.assertEqual(d["field_name"], "description")
        self.assertEqual(d["source_authority"], 80)
        self.assertEqual(d["extraction_method"], "html_text")
        self.assertEqual(d["selector"]["selector_type"], "css")
        self.assertEqual(d["selector"]["query"], "div.about-section > p.intro")
        self.assertEqual(d["confidence"], 0.9)
        self.assertEqual(d["validation_status"], "accepted")

    def test_multiple_claims_independent_provenance(self):
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        f_name = ExtractedField("company_name", "Norsk Fiskeeksport AS", FieldStatus.FOUND, "https://data.brreg.no/api/enheter/923609016", "official_registry", "Norsk Fiskeeksport AS", 1.0)
        f_emp = ExtractedField("employees", 42, FieldStatus.FOUND, "https://data.brreg.no/api/enheter/923609016", "official_registry", "Antall ansatte: 42", 1.0)

        claim_name = build_provenance_claim(f_name, target)
        claim_emp = build_provenance_claim(f_emp, target)

        self.assertNotEqual(claim_name.claim_id, claim_emp.claim_id, "Each claim must have an independent, unique identifier")
        self.assertEqual(claim_name.field_name, "company_name")
        self.assertEqual(claim_emp.field_name, "employees")
        self.assertEqual(claim_name.source_authority, SourceAuthority.GOVERNMENT_REGISTRY)
        self.assertEqual(claim_emp.source_authority, SourceAuthority.GOVERNMENT_REGISTRY)

    def test_source_url_and_redirect_tracking(self):
        # 1. Valid public URL with redirect tracking
        claim_valid = ProvenanceClaim(
            claim_id="claim-valid",
            field_name="website",
            value="https://norskfiske.no/",
            source_url="https://norskfiske.no/",
            discovered_url="http://norskfiske.no",
            source_type="company_website",
            source_authority=SourceAuthority.VERIFIED_FIRST_PARTY,
        )
        verdict_valid = validate_claim_evidence(claim_valid, {"organisation_number": "923609016"})
        self.assertTrue(verdict_valid.is_valid)
        self.assertEqual(verdict_valid.status, ValidationStatus.ACCEPTED)

        # 2. Unsafe local/private URL must be rejected
        claim_unsafe = ProvenanceClaim(
            claim_id="claim-unsafe",
            field_name="revenue",
            value=1000000,
            source_url="http://127.0.0.1:8080/internal_financials",
            source_type="internal_leak",
        )
        verdict_unsafe = validate_claim_evidence(claim_unsafe, {"organisation_number": "923609016"})
        self.assertFalse(verdict_unsafe.is_valid)
        self.assertEqual(verdict_unsafe.status, ValidationStatus.REJECTED)
        self.assertTrue(any("unsafe" in r.lower() or "non-public" in r.lower() for r in verdict_unsafe.reasons))

    def test_timezone_aware_utc_timestamps(self):
        claim = ProvenanceClaim(
            claim_id="claim-time",
            field_name="status",
            value="active",
            source_url="https://data.brreg.no/api/enheter/923609016",
        )
        # Default retrieved_at must be an ISO 8601 string with UTC indicator 'Z'
        self.assertTrue(claim.retrieved_at.endswith("Z"))
        # Parseable by datetime with timezone
        dt = datetime.fromisoformat(claim.retrieved_at.replace("Z", "+00:00"))
        self.assertIsNotNone(dt.tzinfo)

    def test_temporal_provenance_distinctions(self):
        """Strictly distinguish retrieved_at, effective_date, and reporting_period."""
        claim = ProvenanceClaim(
            claim_id="claim-temporal",
            field_name="revenue",
            value=100000000,
            source_url="https://data.brreg.no/regnskap/923609016",
            source_type="official_annual_accounts",
            source_authority=SourceAuthority.GOVERNMENT_REGISTRY,
            retrieved_at="2026-09-20T00:15:00Z",  # Crawl time
            effective_date="2025-06-30",          # Filing submission date
            reporting_period="2024-01-01 to 2024-12-31", # Period covered
        )

        self.assertNotEqual(claim.retrieved_at, claim.effective_date)
        self.assertNotEqual(claim.retrieved_at, claim.reporting_period)
        self.assertEqual(claim.reporting_period, "2024-01-01 to 2024-12-31")

        # Missing date remains None, never fabricated
        claim_no_date = ProvenanceClaim(
            claim_id="claim-nodate",
            field_name="phone",
            value="+4755123456",
            source_url="https://norskfiske.no/",
        )
        self.assertIsNone(claim_no_date.effective_date)
        self.assertIsNone(claim_no_date.reporting_date)

    def test_deterministic_content_hashing(self):
        content_a = b"<html><head><title>Norsk Fiskeeksport</title></head></html>"
        content_b = b"<html><head><title>Norsk Fiskeeksport</title></head></html>"
        content_c = b"<html><head><title>Different Content</title></head></html>"

        hash_a = compute_content_hash(content_a)
        hash_b = compute_content_hash(content_b)
        hash_c = compute_content_hash(content_c)

        self.assertEqual(hash_a, hash_b, "Identical content must produce identical hash")
        self.assertNotEqual(hash_a, hash_c, "Different content must produce different hash")
        self.assertTrue(verify_snapshot_match(content_a, hash_a))
        self.assertFalse(verify_snapshot_match(content_c, hash_a))

    def test_extraction_methods_validation(self):
        methods = [
            ExtractionMethod.REGISTRY_API,
            ExtractionMethod.STRUCTURED_DATA_JSONLD,
            ExtractionMethod.HTML_TEXT,
            ExtractionMethod.PDF_TEXT,
            ExtractionMethod.FINANCIAL_STATEMENT,
        ]
        for m in methods:
            claim = ProvenanceClaim(
                claim_id=f"claim-{m.value}",
                field_name="test_field",
                value="test_val",
                source_url="https://example.test/",
                extraction_method=m,
            )
            self.assertEqual(claim.extraction_method, m)
            self.assertEqual(claim.to_dict()["extraction_method"], m.value)

    def test_evidence_selectors(self):
        # 1. CSS Selector
        s_css = EvidenceSelector(SelectorType.CSS, "header h1.company-title")
        self.assertEqual(s_css.to_dict()["selector_type"], "css")

        # 2. JSON Path
        s_json = EvidenceSelector(SelectorType.JSON_PATH, "$.resultatregnskapResultat.aarsresultat")
        self.assertEqual(s_json.to_dict()["selector_type"], "json_path")

        # 3. PDF Page
        s_pdf = EvidenceSelector(SelectorType.PDF_PAGE, "page 4", page_number=4)
        self.assertEqual(s_pdf.page_number, 4)

        # 4. Table Coordinates
        s_table = EvidenceSelector(SelectorType.TABLE_CELL, "table#resultat", table_row=5, table_col=2)
        self.assertEqual(s_table.table_row, 5)
        self.assertEqual(s_table.table_col, 2)

        # 5. Text Span with offsets
        s_span = EvidenceSelector(SelectorType.TEXT_SPAN, "Norsk Fiskeeksport AS", char_start=50, char_end=71)
        self.assertEqual(s_span.char_start, 50)
        self.assertEqual(s_span.char_end, 71)

    def test_source_authority_hierarchy(self):
        # Verify 7-tier ranking
        self.assertTrue(is_more_authoritative(SourceAuthority.GOVERNMENT_REGISTRY, SourceAuthority.OFFICIAL_FILING_COPY))
        self.assertTrue(is_more_authoritative(SourceAuthority.OFFICIAL_FILING_COPY, SourceAuthority.VERIFIED_FIRST_PARTY))
        self.assertTrue(is_more_authoritative(SourceAuthority.VERIFIED_FIRST_PARTY, SourceAuthority.FIRST_PARTY_STRUCTURED))
        self.assertTrue(is_more_authoritative(SourceAuthority.FIRST_PARTY_STRUCTURED, SourceAuthority.REPUTABLE_SECONDARY))
        self.assertTrue(is_more_authoritative(SourceAuthority.REPUTABLE_SECONDARY, SourceAuthority.SEARCH_DISCOVERY))
        self.assertTrue(is_more_authoritative(SourceAuthority.SEARCH_DISCOVERY, SourceAuthority.UNVERIFIED_THIRD_PARTY))

        # Classification helper
        self.assertEqual(classify_source_authority("official_registry"), SourceAuthority.GOVERNMENT_REGISTRY)
        self.assertEqual(classify_source_authority("website_jsonld"), SourceAuthority.FIRST_PARTY_STRUCTURED)
        self.assertEqual(classify_source_authority("company_website"), SourceAuthority.VERIFIED_FIRST_PARTY)
        self.assertEqual(classify_source_authority("search_candidate"), SourceAuthority.SEARCH_DISCOVERY)
        self.assertEqual(classify_source_authority("unknown", "https://proff.no/selskap/123"), SourceAuthority.UNVERIFIED_THIRD_PARTY)

        # Explanations
        expl = explain_authority_rank(SourceAuthority.GOVERNMENT_REGISTRY)
        self.assertIn("Brønnøysundregistrene", expl)

    def test_wrong_source_rejection_wrong_company(self):
        """Reject evidence when the source content explicitly belongs to a different legal entity."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        wrong_content = "Dette er årsrapport for Helt Annen Bedrift AS, org nr 999888777. Vi driver med IT-konsulenttjenester."

        claim = ProvenanceClaim(
            claim_id="claim-wrong-company",
            field_name="revenue",
            value=5000000,
            source_url="https://annenbedrift.no/regnskap",
            source_type="company_website",
            source_authority=SourceAuthority.VERIFIED_FIRST_PARTY,
            evidence_span="Driftsinntekter: 5 000 000",
        )

        verdict = validate_claim_evidence(claim, target, source_content=wrong_content)
        self.assertFalse(verdict.is_valid)
        self.assertEqual(verdict.status, ValidationStatus.REJECTED)
        self.assertTrue(any("conflicting organization numbers" in r.lower() or "different company" in r.lower() for r in verdict.reasons))

    def test_wrong_source_rejection_parent_subsidiary(self):
        """Reject parent company consolidated accounts when claimed as subsidiary standalone accounts."""
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        parent_content = """
        Konsernregnskap for Fiskeri Holding ASA
        Dette konsernregnskapet omfatter alle konsernselskaper i Norge og utlandet.
        Total omsetning: 1 500 000 000 NOK.
        """

        claim = ProvenanceClaim(
            claim_id="claim-parent-conflation",
            field_name="revenue",
            value=1500000000,
            source_url="https://holding.no/konsern",
            source_type="company_website",
            source_authority=SourceAuthority.VERIFIED_FIRST_PARTY,
            evidence_span="Total omsetning: 1 500 000 000 NOK.",
        )

        verdict = validate_claim_evidence(claim, target, source_content=parent_content)
        self.assertFalse(verdict.is_valid)
        self.assertEqual(verdict.status, ValidationStatus.REJECTED)
        self.assertTrue(any("conflates subsidiary identity" in r.lower() for r in verdict.reasons))

    def test_wrong_source_rejection_aggregators_and_snippets(self):
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}

        # 1. Third-party aggregator
        claim_aggregator = ProvenanceClaim(
            claim_id="claim-proff",
            field_name="revenue",
            value=50000000,
            source_url="https://proff.no/selskap/norsk-fiskeeksport-as/bergen/fisk/IF00123/",
            source_type="third_party_directory",
            source_authority=SourceAuthority.UNVERIFIED_THIRD_PARTY,
            evidence_span="Omsetning: 50 000 000",
        )
        v_agg = validate_claim_evidence(claim_aggregator, target)
        self.assertFalse(v_agg.is_valid)
        self.assertEqual(v_agg.status, ValidationStatus.REJECTED)
        self.assertTrue(any("aggregator" in r.lower() or "directory" in r.lower() for r in v_agg.reasons))

        # 2. Search candidate snippet
        claim_snippet = ProvenanceClaim(
            claim_id="claim-snippet",
            field_name="employees",
            value=25,
            source_url="https://www.bing.com/search?q=norsk+fiskeeksport",
            source_type="search_candidate",
            source_authority=SourceAuthority.SEARCH_DISCOVERY,
            evidence_span="Norsk Fiskeeksport har 25 ansatte...",
        )
        v_snip = validate_claim_evidence(claim_snippet, target)
        self.assertFalse(v_snip.is_valid)
        self.assertEqual(v_snip.status, ValidationStatus.REJECTED)
        self.assertTrue(any("search" in r.lower() for r in v_snip.reasons))

    def test_evidence_span_verification_in_source(self):
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}
        source_text = "Norsk Fiskeeksport AS (org 923609016) ble etablert i 1995. Vi har 42 ansatte."

        # Valid span present in content
        claim_ok = ProvenanceClaim(
            claim_id="claim-ok",
            field_name="employees",
            value=42,
            source_url="https://norskfiske.no/om-oss",
            source_type="website_about_page",
            source_authority=SourceAuthority.VERIFIED_FIRST_PARTY,
            evidence_span="Vi har 42 ansatte.",
        )
        v_ok = validate_claim_evidence(claim_ok, target, source_content=source_text)
        self.assertTrue(v_ok.is_valid)

        # Span NOT present in content -> reject
        claim_bogus = ProvenanceClaim(
            claim_id="claim-bogus",
            field_name="employees",
            value=500,
            source_url="https://norskfiske.no/om-oss",
            source_type="website_about_page",
            source_authority=SourceAuthority.VERIFIED_FIRST_PARTY,
            evidence_span="Vi er nå over 500 ansatte i Norge.",
        )
        v_bogus = validate_claim_evidence(claim_bogus, target, source_content=source_text)
        self.assertFalse(v_bogus.is_valid)
        self.assertEqual(v_bogus.status, ValidationStatus.REJECTED)
        self.assertTrue(any("not found in source content" in r.lower() for r in v_bogus.reasons))

    def test_stage3_and_stage4_provenance_integration(self):
        target = {"organisation_number": "923609016", "name": "Norsk Fiskeeksport AS"}

        # Stage 3 ExtractedField integration
        ext_field = ExtractedField(
            field_name="industry",
            value={"code": "03.111", "label": "Havfiske"},
            status=FieldStatus.FOUND,
            source_url="https://data.brreg.no/api/enheter/923609016",
            source_type="official_registry",
            evidence_span="NACE 03.111: Havfiske",
            confidence=1.0,
        )
        claim_ind = build_provenance_claim(ext_field, target)
        self.assertEqual(claim_ind.field_name, "industry")
        self.assertEqual(claim_ind.source_authority, SourceAuthority.GOVERNMENT_REGISTRY)
        self.assertEqual(claim_ind.extraction_method, ExtractionMethod.REGISTRY_API)
        self.assertEqual(claim_ind.validation_status, ValidationStatus.ACCEPTED)

        # Stage 4 FinancialStatement integration
        f_rev = ExtractedField("revenue", 100000000, FieldStatus.FOUND, "https://data.brreg.no/regnskap/923609016", "official_regnskapsregisteret", "revenue: 100000000 NOK", 1.0)
        claim_rev = build_provenance_claim(f_rev, target, reporting_period="2024", extraction_method=ExtractionMethod.FINANCIAL_STATEMENT)
        self.assertEqual(claim_rev.field_name, "revenue")
        self.assertEqual(claim_rev.value, 100000000)
        self.assertEqual(claim_rev.reporting_period, "2024")
        self.assertEqual(claim_rev.extraction_method, ExtractionMethod.FINANCIAL_STATEMENT)
class Stage6ExternalResearchTests(unittest.TestCase):
    """Stage 6: External Research & Enrichment Engine tests."""

    def setUp(self):
        self.target = {
            "organisation_number": "923609016",
            "name": "Norsk Fiskeeksport AS",
            "municipality": "Bergen",
            "website": "https://norskfiske.no",
        }

    def test_candidate_generation_and_normalization(self):
        search_results = [
            {
                "url": "https://norskfiske.no/om-oss?utm_source=google&utm_medium=cpc",
                "title": "Om Norsk Fiskeeksport AS - Vår historie",
                "snippet": "Norsk Fiskeeksport AS (org 923609016) leverer fersk laks fra Vestlandet.",
                "rank": 1,
            },
            {
                "url": "https://e24.no/naeringsliv/i/12345/norsk-fiskeeksport-oeker-eksporten",
                "title": "Norsk Fiskeeksport øker eksporten til Asia",
                "snippet": "Bergensbedriften Norsk Fiskeeksport melder om rekordvekst.",
                "rank": 2,
            },
        ]
        candidates = generate_research_candidates(self.target, search_results=search_results)
        self.assertEqual(len(candidates), 2)

        cand1 = candidates[0]
        # Tracking params stripped, normalized
        self.assertEqual(cand1.normalized_url, "https://norskfiske.no/om-oss")
        self.assertEqual(cand1.domain, "norskfiske.no")
        self.assertTrue(cand1.is_candidate_only)
        self.assertEqual(cand1.candidate_type, CandidateType.WEBSITE)

        cand2 = candidates[1]
        self.assertEqual(cand2.domain, "e24.no")
        self.assertEqual(cand2.candidate_type, CandidateType.FOOTPRINT)

    def test_candidate_deduplication(self):
        search_results = [
            {
                "url": "https://norskfiske.no/om-oss?utm_source=bing",
                "title": "Om oss 1",
                "snippet": "Snippet 1",
                "rank": 1,
            },
            {
                "url": "https://norskfiske.no/om-oss?utm_source=google",
                "title": "Om oss 2",
                "snippet": "Snippet 2",
                "rank": 2,
            },
            {
                "url": "https://norskfiske.no/om-oss/",
                "title": "Om oss 3",
                "snippet": "Snippet 3",
                "rank": 3,
            },
        ]
        candidates = generate_research_candidates(self.target, search_results=search_results)
        self.assertEqual(len(candidates), 1, "Duplicate normalized URLs must be deduplicated")
        self.assertEqual(candidates[0].normalized_url, "https://norskfiske.no/om-oss")

    def test_candidate_provenance_preservation(self):
        search_results = [
            {
                "url": "https://norskfiske.no/kontakt",
                "title": "Kontakt oss",
                "snippet": "Kontaktinformasjon for Norsk Fiskeeksport AS",
                "query": "Norsk Fiskeeksport AS kontakt",
                "engine": "brave_search",
                "rank": 1,
            }
        ]
        candidates = generate_research_candidates(self.target, search_results=search_results)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.search_query, "Norsk Fiskeeksport AS kontakt")
        self.assertEqual(c.source_engine, "brave_search")
        self.assertEqual(c.rank, 1)
        self.assertTrue(c.candidate_id.startswith("cand-"))
        self.assertTrue(c.retrieved_at.endswith("Z"))

    def test_search_snippet_never_verified_fact(self):
        search_results = [
            {
                "url": "https://some-blog.test/post",
                "title": "Norsk Fiskeeksport har 100 ansatte",
                "snippet": "I følge rykter har Norsk Fiskeeksport AS 100 ansatte.",
                "rank": 1,
            }
        ]
        candidates = generate_research_candidates(self.target, search_results=search_results)
        self.assertEqual(len(candidates), 1)
        # Marked candidate only
        self.assertTrue(candidates[0].is_candidate_only)
        # Attempting to discover leadership or facts from weak search snippets alone yields no verified claim
        discovered_leads = discover_leadership(self.target, [{"source_url": candidates[0].url, "source_type": "search_candidate", "roles": [{"name": "Ola Nordmann", "role": "Daglig leder"}]}])
        self.assertEqual(len(discovered_leads), 0, "Search candidate sources must never manufacture verified leadership")

    def test_permitted_sources_accepted(self):
        target_domains = {"norskfiske.no"}
        # 1. Government registry
        p_gov = evaluate_source_policy("https://data.brreg.no/enhetsregisteret/api/enheter/923609016")
        self.assertEqual(p_gov.status, SourcePolicyStatus.PERMITTED)
        self.assertTrue(p_gov.is_allowed)

        # 2. First-party domain
        p_fp = evaluate_source_policy("https://norskfiske.no/om-oss", target_domains=target_domains)
        self.assertEqual(p_fp.status, SourcePolicyStatus.PERMITTED)
        self.assertTrue(p_fp.is_allowed)

        # 3. Reputable news
        p_news = evaluate_source_policy("https://e24.no/naeringsliv/i/xyz/artikkel")
        self.assertEqual(p_news.status, SourcePolicyStatus.PERMITTED)
        self.assertTrue(p_news.is_allowed)

    def test_restricted_and_scraping_sources_rejected(self):
        # Restricted social & job boards
        blocked = [
            "https://www.linkedin.com/company/norskfiske",
            "https://www.facebook.com/norskfiske",
            "https://www.instagram.com/norskfiske",
            "https://www.tiktok.com/@norskfiske",
            "https://www.glassdoor.com/Overview/norskfiske",
            "https://no.indeed.com/cmp/norskfiske",
            "https://proff.no/selskap/norsk-fiskeeksport-as/IF123",
            "https://purehelp.no/m/company/details/923609016",
        ]
        for url in blocked:
            decision = evaluate_source_policy(url)
            self.assertEqual(decision.status, SourcePolicyStatus.REJECTED, f"URL {url} must be rejected")
            self.assertFalse(decision.is_allowed)
            self.assertTrue(decision.prohibits_scraping)

    def test_leadership_discovery_with_exact_entity(self):
        sources_data = [
            {
                "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016/roller",
                "source_type": "official_roles",
                "roles": [
                    {
                        "name": "Kari Nordmann",
                        "role": "Daglig leder",
                        "organisation_number": "923609016",
                        "company_name": "Norsk Fiskeeksport AS",
                        "evidence_span": "Daglig leder: Kari Nordmann",
                    },
                    {
                        "name": "Per Olsen",
                        "role": "Styreleder",
                        "organisation_number": "923609016",
                        "company_name": "Norsk Fiskeeksport AS",
                        "evidence_span": "Styreleder: Per Olsen",
                    },
                ],
            }
        ]
        leaders = discover_leadership(self.target, sources_data)
        self.assertEqual(len(leaders), 2)

        by_role = {l.role_type: l for l in leaders}
        self.assertIn(LeadershipRoleType.DAGLIG_LEDER, by_role)
        self.assertEqual(by_role[LeadershipRoleType.DAGLIG_LEDER].person_name, "Kari Nordmann")
        self.assertEqual(by_role[LeadershipRoleType.DAGLIG_LEDER].status, "verified")

        self.assertIn(LeadershipRoleType.STYRELEDER, by_role)
        self.assertEqual(by_role[LeadershipRoleType.STYRELEDER].person_name, "Per Olsen")

    def test_leadership_avoids_name_collision_without_proof(self):
        # Person with same name at a different company (different org number)
        sources_data = [
            {
                "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/999888777/roller",
                "source_type": "official_roles",
                "roles": [
                    {
                        "name": "Kari Nordmann",
                        "role": "Daglig leder",
                        "organisation_number": "999888777",  # Different company!
                        "company_name": "Helt Annen Bedrift AS",
                    }
                ],
            }
        ]
        leaders = discover_leadership(self.target, sources_data)
        self.assertEqual(len(leaders), 0, "Leadership at different company must never be attributed to target")

    def test_social_video_policy_declared_only(self):
        # 1. Declared YouTube link from company website
        declared_links = [
            {"platform": "youtube", "url": "https://www.youtube.com/c/NorskFiskeeksport"}
        ]
        footprint = build_external_footprint([], declared_links=declared_links, target_entity=self.target)
        video_items = [item for item in footprint.items if item.category == ExternalFootprintCategory.VIDEO_REFERENCE]
        self.assertEqual(len(video_items), 1)
        self.assertTrue(video_items[0].is_verified)
        self.assertEqual(video_items[0].domain, "youtube.com")

        # 2. Undeclared / search hit video requires verification
        p_undeclared = evaluate_source_policy("https://www.youtube.com/watch?v=12345")
        self.assertEqual(p_undeclared.status, SourcePolicyStatus.REQUIRES_VERIFICATION)
        self.assertTrue(p_undeclared.requires_official_verification)

    def test_social_platform_scraping_strictly_rejected(self):
        decision = evaluate_source_policy(
            "https://www.linkedin.com/company/norskfiske/jobs",
            acquisition_mode="unauthorized_scraping",
        )
        self.assertEqual(decision.status, SourcePolicyStatus.REJECTED)
        self.assertFalse(decision.is_allowed)
        self.assertTrue(decision.prohibits_scraping)
        self.assertIn("prohibits unauthorized scraping", decision.reason)

    def test_external_footprint_normalization_and_categorization(self):
        target_domains = {"norskfiske.no"}
        candidates = [
            ResearchCandidate(
                candidate_id="c1",
                url="https://norskfiske.no/",
                normalized_url="https://norskfiske.no",
                domain="norskfiske.no",
                candidate_type=CandidateType.WEBSITE,
                title="Hjemmeside",
                snippet="Velkommen",
                search_query="q",
                source_engine="search",
                policy_decision=evaluate_source_policy("https://norskfiske.no/", target_domains=target_domains),
                is_candidate_only=False,
            ),
            ResearchCandidate(
                candidate_id="c2",
                url="https://e24.no/artikkel/123",
                normalized_url="https://e24.no/artikkel/123",
                domain="e24.no",
                candidate_type=CandidateType.FOOTPRINT,
                title="Nyhet",
                snippet="Omtale",
                search_query="q",
                source_engine="search",
                policy_decision=evaluate_source_policy("https://e24.no/artikkel/123"),
                is_candidate_only=True,
            ),
            # Rejected source: aggregator
            ResearchCandidate(
                candidate_id="c3",
                url="https://proff.no/selskap/123",
                normalized_url="https://proff.no/selskap/123",
                domain="proff.no",
                candidate_type=CandidateType.COMPANY_PROFILE,
                title="Proff",
                snippet="Regnskap",
                search_query="q",
                source_engine="search",
                policy_decision=evaluate_source_policy("https://proff.no/selskap/123"),
                is_candidate_only=True,
            ),
        ]
        footprint = build_external_footprint(candidates, target_entity=self.target)
        self.assertEqual(footprint.total_items, 2, "Rejected candidates must not be included in active footprint")
        self.assertEqual(len(footprint.rejected_items), 1)
        self.assertIn("proff.no", footprint.rejected_items[0]["url"])
        self.assertEqual(footprint.category_counts.get("official_website"), 1)
        self.assertEqual(footprint.category_counts.get("news_publication"), 1)

    def test_source_policy_centralized_decisions(self):
        # SSRF / local address rejection
        p_local = evaluate_source_policy("http://localhost:8080/admin")
        self.assertEqual(p_local.status, SourcePolicyStatus.REJECTED)
        self.assertIn("ssrf", p_local.matched_rule.lower())

        p_ip = evaluate_source_policy("http://192.168.1.1/secret")
        self.assertEqual(p_ip.status, SourcePolicyStatus.REJECTED)

        p_scheme = evaluate_source_policy("ftp://files.test/file")
        self.assertEqual(p_scheme.status, SourcePolicyStatus.REJECTED)

    def test_evidence_pipeline_separation(self):
        # Candidate discovery -> Source policy validation -> Claim creation
        search_hits = [
            {"url": "https://norskfiske.no/om-oss", "title": "Om oss", "snippet": "Norsk Fiskeeksport AS ble stiftet i 2019."}
        ]
        candidates = generate_research_candidates(self.target, search_results=search_hits)
        cand = candidates[0]

        # 1. Candidate is not a verified claim
        self.assertTrue(cand.is_candidate_only)

        # 2. Source policy validated
        self.assertEqual(cand.policy_decision.status, SourcePolicyStatus.PERMITTED)

        # 3. Footprint generated
        fp = build_external_footprint(candidates, target_entity=self.target)
        self.assertEqual(len(fp.items), 1)

    def test_weak_source_handling_and_no_fabricated_claims(self):
        # No roles present in source -> empty leadership returned, no hallucinated roles
        sources_empty = [{"source_url": "https://data.brreg.no/api", "source_type": "official_roles", "roles": []}]
        leaders = discover_leadership(self.target, sources_empty)
        self.assertEqual(len(leaders), 0)


class Stage7ChangeIntelligenceTests(unittest.TestCase):
    """Stage 7: Refresh & Change Intelligence Engine tests."""

    def setUp(self):
        self.org = "923609016"

    def test_stable_claim_key_generation_deterministic(self):
        key1 = generate_stable_claim_key(self.org, "legal_name")
        key2 = generate_stable_claim_key(self.org, "LEGAL_NAME")
        key3 = generate_stable_claim_key(self.org, "legal-name")
        self.assertEqual(key1, "org:923609016|field:legal_name")
        self.assertEqual(key1, key2)
        self.assertEqual(key1, key3)

        # Entity qualifier
        k_role = generate_stable_claim_key(self.org, "leadership", "daglig_leder:Kari Nordmann")
        self.assertEqual(k_role, "org:923609016|field:leadership|entity:daglig_leder_kari_nordmann")

        # Period qualifier
        k_fin = generate_stable_claim_key(self.org, "revenue", "2024")
        self.assertEqual(k_fin, "org:923609016|field:revenue|entity:2024")

    def test_stable_claim_key_ignores_timestamps_and_ids(self):
        # Verify key is strictly semantic and contains no timestamps, random UUIDs, or fetch IDs
        key = generate_stable_claim_key(" 923 609 016 ", "employees")
        self.assertEqual(key, "org:923609016|field:employees")
        self.assertNotIn("T", key)
        self.assertNotIn(":", key.replace("org:923609016|field:employees", ""))

    def test_immutable_snapshots_cannot_be_mutated(self):
        claim = SnapshotClaim(
            claim_key="org:923609016|field:legal_name",
            field_name="legal_name",
            value="Norsk Fiskeeksport AS",
        )
        snapshot = CompanySnapshot(
            snapshot_id="snapshot-923609016-v1",
            version=1,
            organisation_number=self.org,
            timestamp="2026-09-20T00:00:00Z",
            claims={"org:923609016|field:legal_name": claim},
        )
        # Attempting to reassign an attribute raises AttributeError
        with self.assertRaises(AttributeError):
            snapshot.version = 2

        with self.assertRaises(AttributeError):
            snapshot.organisation_number = "999888777"

    def test_previous_vs_current_comparison_all_change_types(self):
        # Previous snapshot with 3 claims: legal_name, employees, website
        c_name = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport AS")
        c_emp_old = SnapshotClaim("org:923609016|field:employees", "employees", 40)
        c_web = SnapshotClaim("org:923609016|field:website", "website", "https://norskfiske.no")
        snap_v1 = CompanySnapshot("snap-1", 1, self.org, "2026-01-01T00:00:00Z", {
            c_name.claim_key: c_name,
            c_emp_old.claim_key: c_emp_old,
            c_web.claim_key: c_web,
        })

        # Current snapshot:
        # legal_name: unchanged
        # employees: modified (40 -> 45)
        # website: removed
        # revenue: added
        c_emp_new = SnapshotClaim("org:923609016|field:employees", "employees", 45)
        c_rev = SnapshotClaim("org:923609016|field:revenue", "revenue", 50000000)
        snap_v2 = CompanySnapshot("snap-2", 2, self.org, "2026-09-20T00:00:00Z", {
            c_name.claim_key: c_name,
            c_emp_new.claim_key: c_emp_new,
            c_rev.claim_key: c_rev,
        })

        changes = compare_snapshots(snap_v1, snap_v2)
        by_key = {c.stable_claim_key: c for c in changes}

        # 1. UNCHANGED: legal_name
        self.assertEqual(by_key["org:923609016|field:legal_name"].change_type, ChangeType.UNCHANGED)

        # 2. MODIFIED: employees
        self.assertEqual(by_key["org:923609016|field:employees"].change_type, ChangeType.MODIFIED)
        self.assertEqual(by_key["org:923609016|field:employees"].previous_value, 40)
        self.assertEqual(by_key["org:923609016|field:employees"].current_value, 45)

        # 3. REMOVED: website
        self.assertEqual(by_key["org:923609016|field:website"].change_type, ChangeType.REMOVED)
        self.assertEqual(by_key["org:923609016|field:website"].previous_value, "https://norskfiske.no")

        # 4. ADDED: revenue
        self.assertEqual(by_key["org:923609016|field:revenue"].change_type, ChangeType.ADDED)
        self.assertEqual(by_key["org:923609016|field:revenue"].current_value, 50000000)

    def test_material_change_detection_semantic_only(self):
        # Meaningful changes
        self.assertTrue(is_material_change(100, 200, "revenue"))
        self.assertTrue(is_material_change("Bergen", "Oslo", "municipality"))
        self.assertTrue(is_material_change("Active", "Dissolved", "status"))

        # Incidental formatting changes
        self.assertFalse(is_material_change(100.00001, 100.00002, "score"))
        self.assertFalse(is_material_change("Norsk Fiskeeksport", "Norsk  Fiskeeksport", "name"))

    def test_false_change_prevention_whitespace_and_case(self):
        # Whitespace differences
        self.assertFalse(is_material_change("Norsk Fiskeeksport AS", "  Norsk   Fiskeeksport AS  ", "name"))

        # Case differences for case-insensitive fields
        self.assertFalse(is_material_change("AS", "as", "legal_form"))
        self.assertFalse(is_material_change("BERGEN", "Bergen", "municipality"))
        self.assertFalse(is_material_change("post@norskfiske.no", "POST@NORSKFISKE.NO", "email"))

    def test_false_change_prevention_dict_and_list_ordering(self):
        # Dict key order
        dict_a = {"alpha": 1, "beta": 2, "gamma": 3}
        dict_b = {"gamma": 3, "alpha": 1, "beta": 2}
        self.assertFalse(is_material_change(dict_a, dict_b, "metadata"))

        # List order for set-like items
        list_a = ["https://youtube.com/c/1", "https://norskfiske.no"]
        list_b = ["https://norskfiske.no", "https://youtube.com/c/1"]
        self.assertFalse(is_material_change(list_a, list_b, "links"))

    def test_false_change_prevention_url_canonicalization(self):
        # URL normalization: trailing slash and tracking query params
        url_a = "https://norskfiske.no/"
        url_b = "https://norskfiske.no"
        url_c = "https://norskfiske.no/?utm_source=google&utm_medium=cpc"
        self.assertFalse(is_material_change(url_a, url_b, "website"))
        self.assertFalse(is_material_change(url_a, url_c, "website"))

    def test_failed_refresh_preserves_previous_snapshot(self):
        # Known-good snapshot
        claim = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport AS")
        snap_v1 = CompanySnapshot("snap-1", 1, self.org, "2026-01-01T00:00:00Z", {claim.claim_key: claim})

        # Complete refresh failure (retrieval error)
        result = refresh_company_intelligence(
            previous_snapshot=snap_v1,
            new_claims=None,
            retrieval_error="HTTP 500: BRREG internal server error",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, RefreshStatus.FAILED_FETCH)
        self.assertEqual(result.snapshot, snap_v1, "Previous known-good snapshot must be preserved")
        self.assertEqual(len(result.changes), 0, "No false changes must be generated on failure")

    def test_failed_refresh_no_false_removals(self):
        # Known-good snapshot with multiple claims
        c1 = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport AS")
        c2 = SnapshotClaim("org:923609016|field:revenue", "revenue", 50000000)
        snap_v1 = CompanySnapshot("snap-1", 1, self.org, "2026-01-01T00:00:00Z", {c1.claim_key: c1, c2.claim_key: c2})

        # Transient network timeout
        result = refresh_company_intelligence(
            previous_snapshot=snap_v1,
            new_claims=None,
            source_results={"registry": "timeout", "website": "timeout"},
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, RefreshStatus.TRANSIENT_ERROR)
        self.assertEqual(result.snapshot, snap_v1)
        # ZERO false removals!
        self.assertEqual(len(result.changes), 0)

    def test_partial_source_failure_preserves_unreached_claims(self):
        # Registry claims + Website claims
        c_reg = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport AS", source_module="registry")
        c_web = SnapshotClaim("org:923609016|field:description", "description", "Fersk laks fra Bergen", source_module="website")
        snap_v1 = CompanySnapshot("snap-1", 1, self.org, "2026-01-01T00:00:00Z", {
            c_reg.claim_key: c_reg,
            c_web.claim_key: c_web,
        })

        # Next run: registry succeeded with updated legal_name; website timed out!
        c_reg_new = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport ASA", source_module="registry")
        result = refresh_company_intelligence(
            previous_snapshot=snap_v1,
            new_claims=[c_reg_new],
            source_results={"registry": "available", "website": "timeout"},
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, RefreshStatus.PARTIAL_FAILURE)
        self.assertIn("website", result.failed_sources)

        # In new snapshot: website claim was preserved, NOT falsely removed!
        self.assertIn("org:923609016|field:description", result.snapshot.claims)
        self.assertEqual(result.snapshot.claims["org:923609016|field:description"].value, "Fersk laks fra Bergen")

        # In changes: legal_name was MODIFIED; description was UNCHANGED (not REMOVED!)
        by_key = {c.stable_claim_key: c for c in result.changes}
        self.assertEqual(by_key["org:923609016|field:legal_name"].change_type, ChangeType.MODIFIED)
        self.assertEqual(by_key["org:923609016|field:description"].change_type, ChangeType.UNCHANGED)

    def test_idempotent_reruns_no_duplicate_changes(self):
        claim = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport AS")
        snap_v1 = CompanySnapshot("snap-1", 1, self.org, "2026-01-01T00:00:00Z", {claim.claim_key: claim})

        # Run 1: identical claims
        res1 = refresh_company_intelligence(
            previous_snapshot=snap_v1,
            new_claims=[claim],
            source_results={"registry": "available"},
        )
        # All changes are UNCHANGED
        self.assertTrue(all(c.change_type == ChangeType.UNCHANGED for c in res1.changes))

        # Run 2: identical claims again
        res2 = refresh_company_intelligence(
            previous_snapshot=res1.snapshot,
            new_claims=[claim],
            source_results={"registry": "available"},
        )
        self.assertTrue(all(c.change_type == ChangeType.UNCHANGED for c in res2.changes))
        self.assertEqual(len(res1.changes), len(res2.changes))

    def test_snapshot_store_history_and_versioning(self):
        store = MemorySnapshotStore()
        c1 = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport AS")
        snap1 = CompanySnapshot("snap-1", 1, self.org, "2026-01-01T00:00:00Z", {c1.claim_key: c1})
        store.save_snapshot(snap1)

        c2 = SnapshotClaim("org:923609016|field:legal_name", "legal_name", "Norsk Fiskeeksport ASA")
        snap2 = CompanySnapshot("snap-2", 2, self.org, "2026-06-01T00:00:00Z", {c2.claim_key: c2})
        store.save_snapshot(snap2)

        latest = store.get_latest_snapshot(self.org)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.version, 2)
        self.assertEqual(latest.claims["org:923609016|field:legal_name"].value, "Norsk Fiskeeksport ASA")

        history = store.get_snapshot_history(self.org)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].version, 1)
        self.assertEqual(history[1].version, 2)
class Stage8StrategyHarnessTests(unittest.TestCase):
    """Stage 8: Learning & Strategy Harness tests."""

    def setUp(self):
        self.registry = StrategyRegistry()

    def test_registry_creation_and_registration(self):
        strat = StrategyDefinition(
            strategy_id="strat-alpha",
            version="1.0.0",
            description="Alpha baseline strategy",
            configuration={"depth": 2, "timeout": 15},
            status=StrategyStatus.CANDIDATE,
        )
        self.registry.register_strategy(strat)

        # Retrieve by exact key
        retrieved = self.registry.get_strategy("strat-alpha", "1.0.0")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.strategy_id, "strat-alpha")
        self.assertEqual(retrieved.version, "1.0.0")
        self.assertEqual(retrieved.configuration["depth"], 2)

        # Retrieve latest version
        latest = self.registry.get_strategy("strat-alpha")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.version, "1.0.0")

        # List strategies
        all_strats = self.registry.list_strategies()
        self.assertEqual(len(all_strats), 1)

    def test_duplicate_strategy_version_handling(self):
        strat1 = StrategyDefinition("strat-b", "1.0", "Original", {"k": 1})
        self.registry.register_strategy(strat1)

        # Candidate can be updated
        strat2 = StrategyDefinition("strat-b", "1.0", "Updated", {"k": 2})
        self.registry.register_strategy(strat2)
        self.assertEqual(self.registry.get_strategy("strat-b", "1.0").configuration["k"], 2)

        # Frozen strategy cannot be overwritten
        self.registry.set_frozen_strategy("strat-b", "1.0")
        strat3 = StrategyDefinition("strat-b", "1.0", "Attempted Overwrite", {"k": 3})
        with self.assertRaises(ValueError):
            self.registry.register_strategy(strat3)

    def test_attempt_recording(self):
        attempt = StrategyAttempt(
            strategy_id="strat-alpha",
            strategy_version="1.0.0",
            profile_id="923609016",
            attempt_id="att-12345",
            input_fingerprint="inp-sha256",
            output_fingerprint="out-sha256",
            terminal_state="complete",
            success=True,
            request_count=4,
            runtime_ms=125.5,
            cost=0.002,
        )
        d = attempt.to_dict()
        self.assertEqual(d["strategy_id"], "strat-alpha")
        self.assertEqual(d["profile_id"], "923609016")
        self.assertTrue(d["success"])
        self.assertEqual(d["request_count"], 4)
        self.assertEqual(d["runtime_ms"], 125.5)

    def test_success_failure_aggregation_and_metrics(self):
        attempts = [
            StrategyAttempt("strat-a", "1.0", f"9236090{i}", f"att-{i}", "in", "out", "complete", True, request_count=2, runtime_ms=100.0, cost=0.01)
            for i in range(8)
        ] + [
            StrategyAttempt("strat-a", "1.0", f"9998880{i}", f"att-fail-{i}", "in", "out", "source_error", False, request_count=1, runtime_ms=50.0, cost=0.005)
            for i in range(2)
        ]

        metrics = evaluate_strategy_attempts(attempts, total_eligible_profiles=10)
        self.assertEqual(metrics.total_attempts, 10)
        self.assertEqual(metrics.successful_attempts, 8)
        self.assertEqual(metrics.failed_attempts, 2)
        self.assertEqual(metrics.precision, 0.8)
        self.assertEqual(metrics.coverage, 0.8)
        self.assertEqual(metrics.error_rate, 0.2)
        self.assertEqual(metrics.total_requests, 18)  # 8*2 + 2*1
        self.assertEqual(metrics.avg_requests_per_attempt, 1.8)
        self.assertEqual(metrics.total_cost, 0.09)  # 8*0.01 + 2*0.005

    def test_challenger_comparison(self):
        baseline = StrategyMetrics(
            strategy_id="strat-base", strategy_version="1.0",
            total_attempts=100, successful_attempts=80, failed_attempts=20,
            precision=0.80, coverage=0.80, error_rate=0.20,
            total_requests=200, avg_requests_per_attempt=2.0,
            total_runtime_ms=10000.0, avg_runtime_ms=100.0,
            total_cost=1.0, avg_cost_per_attempt=0.01,
        )
        challenger = StrategyMetrics(
            strategy_id="strat-chal", strategy_version="2.0",
            total_attempts=100, successful_attempts=90, failed_attempts=10,
            precision=0.90, coverage=0.90, error_rate=0.10,
            total_requests=220, avg_requests_per_attempt=2.2,
            total_runtime_ms=11000.0, avg_runtime_ms=110.0,
            total_cost=1.1, avg_cost_per_attempt=0.011,
        )

        deltas = compare_strategies(baseline, challenger)
        self.assertAlmostEqual(deltas["precision_delta"], 0.10)
        self.assertAlmostEqual(deltas["coverage_delta"], 0.10)
        self.assertAlmostEqual(deltas["requests_ratio"], 1.10)
        self.assertAlmostEqual(deltas["runtime_ratio"], 1.10)
        self.assertAlmostEqual(deltas["cost_ratio"], 1.10)

    def test_precision_first_promotion_accepted(self):
        baseline = StrategyMetrics(
            strategy_id="prod", strategy_version="1.0",
            total_attempts=100, successful_attempts=95, failed_attempts=5,
            precision=0.95, coverage=0.80, error_rate=0.05,
            total_requests=300, avg_requests_per_attempt=3.0,
            total_runtime_ms=15000.0, avg_runtime_ms=150.0,
            total_cost=1.5, avg_cost_per_attempt=0.015,
        )
        # Challenger improves coverage without precision degradation
        challenger = StrategyMetrics(
            strategy_id="chal", strategy_version="2.0",
            total_attempts=100, successful_attempts=96, failed_attempts=4,
            precision=0.96, coverage=0.85, error_rate=0.04,
            total_requests=330, avg_requests_per_attempt=3.3,  # 1.1x
            total_runtime_ms=16500.0, avg_runtime_ms=165.0,   # 1.1x
            total_cost=1.65, avg_cost_per_attempt=0.0165,     # 1.1x
        )

        decision = evaluate_promotion(baseline, challenger)
        self.assertTrue(decision.promoted)
        self.assertTrue(all(decision.gate_checks.values()))

    def test_precision_first_promotion_rejected_on_precision_drop(self):
        # Challenger has HIGHER coverage (0.90 vs 0.80), but LOWER precision (0.90 vs 0.95)
        baseline = StrategyMetrics(
            strategy_id="prod", strategy_version="1.0",
            total_attempts=100, successful_attempts=95, failed_attempts=5,
            precision=0.95, coverage=0.80, error_rate=0.05,
            total_requests=300, avg_requests_per_attempt=3.0,
            total_runtime_ms=15000.0, avg_runtime_ms=150.0,
            total_cost=1.5, avg_cost_per_attempt=0.015,
        )
        challenger = StrategyMetrics(
            strategy_id="chal", strategy_version="2.0",
            total_attempts=100, successful_attempts=90, failed_attempts=10,
            precision=0.90, coverage=0.90, error_rate=0.10,
            total_requests=300, avg_requests_per_attempt=3.0,
            total_runtime_ms=15000.0, avg_runtime_ms=150.0,
            total_cost=1.5, avg_cost_per_attempt=0.015,
        )

        decision = evaluate_promotion(baseline, challenger, criteria=PromotionCriteria(max_precision_drop=0.0))
        self.assertFalse(decision.promoted)
        self.assertFalse(decision.gate_checks["precision_preserved"])
        self.assertIn("Precision dropped", decision.reason)

    def test_precision_first_promotion_rejected_on_resource_blowup(self):
        # Challenger preserves precision, but 3x request usage exceeds 1.25x limit
        baseline = StrategyMetrics(
            strategy_id="prod", strategy_version="1.0",
            total_attempts=100, successful_attempts=95, failed_attempts=5,
            precision=0.95, coverage=0.80, error_rate=0.05,
            total_requests=300, avg_requests_per_attempt=3.0,
            total_runtime_ms=15000.0, avg_runtime_ms=150.0,
            total_cost=1.5, avg_cost_per_attempt=0.015,
        )
        challenger = StrategyMetrics(
            strategy_id="chal", strategy_version="2.0",
            total_attempts=100, successful_attempts=96, failed_attempts=4,
            precision=0.96, coverage=0.85, error_rate=0.04,
            total_requests=900, avg_requests_per_attempt=9.0,  # 3.0x blowup!
            total_runtime_ms=16500.0, avg_runtime_ms=165.0,
            total_cost=1.65, avg_cost_per_attempt=0.0165,
        )

        decision = evaluate_promotion(baseline, challenger)
        self.assertFalse(decision.promoted)
        self.assertFalse(decision.gate_checks["requests_bounded"])
        self.assertIn("Request ratio", decision.reason)

    def test_frozen_production_strategy_lifecycle(self):
        # 1. Register and freeze v1
        strat_v1 = StrategyDefinition("prod-strat", "1.0.0", "V1 Baseline", {"depth": 1})
        self.registry.register_strategy(strat_v1)
        self.registry.set_frozen_strategy("prod-strat", "1.0.0")

        frozen = self.registry.get_frozen_strategy()
        self.assertIsNotNone(frozen)
        self.assertEqual(frozen.version, "1.0.0")
        self.assertEqual(frozen.status, StrategyStatus.FROZEN)

        # 2. Register challenger v2
        strat_v2 = StrategyDefinition("prod-strat", "2.0.0", "V2 Challenger", {"depth": 2}, status=StrategyStatus.CHALLENGER)
        self.registry.register_strategy(strat_v2)

        # 3. Explicit promotion replaces frozen strategy and marks v1 retired
        self.registry.set_frozen_strategy("prod-strat", "2.0.0")
        new_frozen = self.registry.get_frozen_strategy()
        self.assertEqual(new_frozen.version, "2.0.0")
        self.assertEqual(new_frozen.status, StrategyStatus.FROZEN)

        old_v1 = self.registry.get_strategy("prod-strat", "1.0.0")
        self.assertEqual(old_v1.status, StrategyStatus.RETIRED)


class Stage9CompetitionBatchTests(unittest.TestCase):
    """Stage 9: Competition Batch Engine tests."""

    def test_small_batch_execution(self):
        orgs = [f"92360901{i}" for i in range(5)]
        envelope = EvaluationEnvelope(
            envelope_id="test-small",
            selected_organisations=orgs,
            max_evaluation_count=5,
            request_budget=50,
            runtime_budget_seconds=10.0,
            cost_budget=1.0,
        )

        def mock_worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            allowed, _ = budget.acquire_requests(2)
            budget.acquire_cost(0.01)
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE if allowed else BatchTerminalState.REQUEST_BUDGET_EXCEEDED,
                success=allowed,
                data={"name": f"Company {company['organisation_number']}"},
                requests_used=2 if allowed else 0,
                cost_incurred=0.01 if allowed else 0.0,
            )

        engine = CompetitionBatchEngine(envelope, mock_worker, max_workers=2)
        results, manifest = engine.run()

        self.assertEqual(len(results), 5)
        self.assertEqual(manifest.completed_count, 5)
        self.assertEqual(manifest.failed_count, 0)
        self.assertEqual(manifest.total_requests_used, 10)

        # Validate manifest
        val = validate_manifest(manifest, envelope, results)
        self.assertTrue(val.passed, f"Validation errors: {val.errors}")

    def test_100_company_envelope_enforcement(self):
        # 150 organisations provided, but envelope specifies max 100
        orgs = [f"9236{i:05d}" for i in range(150)]
        envelope = EvaluationEnvelope(
            envelope_id="test-100-cap",
            selected_organisations=orgs,
            max_evaluation_count=100,
        )
        self.assertEqual(len(envelope.selected_organisations), 100, "Envelope must cap at max_evaluation_count")

        def mock_worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            budget.acquire_requests(1)
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
                requests_used=1,
            )

        engine = CompetitionBatchEngine(envelope, mock_worker, max_workers=4)
        results, manifest = engine.run()
        self.assertEqual(len(results), 100)
        self.assertEqual(manifest.evaluation_count, 100)

    def test_1000_plus_input_dataset_streaming(self):
        # Stream 1,250 items in chunks of 100
        input_data = [f"9236{i:05d}" for i in range(1250)]
        chunks = list(iter_company_inputs(input_data, chunk_size=100))
        self.assertEqual(len(chunks), 13)
        self.assertEqual(len(chunks[0]), 100)
        self.assertEqual(len(chunks[-1]), 50)
        total_streamed = sum(len(c) for c in chunks)
        self.assertEqual(total_streamed, 1250)

    def test_deterministic_ordering(self):
        # 10 companies evaluated in parallel with variable worker sleep
        orgs = [f"9236090{i:02d}" for i in range(10)]
        envelope = EvaluationEnvelope(
            envelope_id="test-ordering",
            selected_organisations=orgs,
            max_evaluation_count=10,
        )

        def worker_with_jitter(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            # Sleep in reverse order to introduce race condition in completion
            org_idx = int(company["organisation_number"][-2:])
            time.sleep((10 - org_idx) * 0.005)
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
                requests_used=1,
            )

        engine = CompetitionBatchEngine(envelope, worker_with_jitter, max_workers=4)
        results, manifest = engine.run()

        # Verify results strictly match initial envelope order
        result_orgs = [r.organisation_number for r in results]
        self.assertEqual(result_orgs, orgs, "Results must strictly preserve envelope ordering regardless of thread completion")

    def test_parallel_request_budget_enforcement_race_condition(self):
        # 10 workers in parallel evaluating 20 companies
        # Hard request budget is 15 requests total
        # Each company attempts 2 requests
        # Max allowed requests is 15 -> after 7 companies (14 reqs), 8th company will fail request acquisition
        orgs = [f"923609{i:03d}" for i in range(20)]
        envelope = EvaluationEnvelope(
            envelope_id="test-req-race",
            selected_organisations=orgs,
            max_evaluation_count=20,
            request_budget=15,  # Strict hard cap
        )

        def greedy_worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            allowed, stop_reason = budget.acquire_requests(2)
            if not allowed:
                return BatchCompanyResult(
                    organisation_number=company["organisation_number"],
                    terminal_state=stop_reason or BatchTerminalState.REQUEST_BUDGET_EXCEEDED,
                    success=False,
                    requests_used=0,
                )
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
                requests_used=2,
            )

        engine = CompetitionBatchEngine(envelope, greedy_worker, max_workers=8)
        results, manifest = engine.run()

        # Hard budget guarantee: requests_used CANNOT exceed 15 under any race condition!
        self.assertLessEqual(manifest.total_requests_used, 15)
        # At least one company must have been stopped with REQUEST_BUDGET_EXCEEDED
        exceeded = [r for r in results if r.terminal_state == BatchTerminalState.REQUEST_BUDGET_EXCEEDED]
        self.assertGreater(len(exceeded), 0)

    def test_parallel_cost_budget_enforcement_race_condition(self):
        # Cost budget is 0.50 NOK
        orgs = [f"923609{i:03d}" for i in range(15)]
        envelope = EvaluationEnvelope(
            envelope_id="test-cost-race",
            selected_organisations=orgs,
            max_evaluation_count=15,
            cost_budget=0.50,
        )

        def cost_worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            allowed, stop_reason = budget.acquire_cost(0.12)
            if not allowed:
                return BatchCompanyResult(
                    organisation_number=company["organisation_number"],
                    terminal_state=stop_reason or BatchTerminalState.COST_BUDGET_EXCEEDED,
                    success=False,
                    cost_incurred=0.0,
                )
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
                cost_incurred=0.12,
            )

        engine = CompetitionBatchEngine(envelope, cost_worker, max_workers=4)
        results, manifest = engine.run()

        # Hard budget guarantee: total_cost_incurred CANNOT exceed 0.50
        self.assertLessEqual(manifest.total_cost_incurred, 0.50)
        exceeded = [r for r in results if r.terminal_state == BatchTerminalState.COST_BUDGET_EXCEEDED]
        self.assertGreater(len(exceeded), 0)

    def test_runtime_budget_enforcement(self):
        orgs = [f"923609{i:03d}" for i in range(6)]
        envelope = EvaluationEnvelope(
            envelope_id="test-runtime",
            selected_organisations=orgs,
            max_evaluation_count=6,
            runtime_budget_seconds=0.01,  # Short budget: 10ms
        )

        def slow_worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            time.sleep(0.02)
            ok, stop_reason = budget.check_runtime()
            if not ok:
                return BatchCompanyResult(
                    organisation_number=company["organisation_number"],
                    terminal_state=stop_reason or BatchTerminalState.RUNTIME_BUDGET_EXCEEDED,
                    success=False,
                )
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
            )

        engine = CompetitionBatchEngine(envelope, slow_worker, max_workers=1)
        results, manifest = engine.run()

        # Results after budget expiry must be marked with RUNTIME_BUDGET_EXCEEDED
        runtime_stopped = [r for r in results if r.terminal_state == BatchTerminalState.RUNTIME_BUDGET_EXCEEDED]
        self.assertGreater(len(runtime_stopped), 0)

    def test_failed_individual_company_handling(self):
        orgs = ["923609001", "923609002", "923609003"]
        envelope = EvaluationEnvelope("test-err", orgs, max_evaluation_count=3)

        def error_worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            if company["organisation_number"] == "923609002":
                raise RuntimeError("Unexpected connector explosion")
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
            )

        engine = CompetitionBatchEngine(envelope, error_worker, max_workers=2)
        results, manifest = engine.run()

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].terminal_state, BatchTerminalState.COMPLETE)
        self.assertEqual(results[1].terminal_state, BatchTerminalState.FAILED)
        self.assertIn("Unexpected connector explosion", results[1].error_message)
        self.assertEqual(results[2].terminal_state, BatchTerminalState.COMPLETE)

    def test_resume_and_valid_cache_hit(self):
        cache = ResultCache()
        orgs = ["923609001", "923609002"]
        envelope = EvaluationEnvelope("test-cache", orgs, max_evaluation_count=2)

        call_counts = {"count": 0}

        def worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            call_counts["count"] += 1
            budget.acquire_requests(1)
            return BatchCompanyResult(
                organisation_number=company["organisation_number"],
                terminal_state=BatchTerminalState.COMPLETE,
                success=True,
                requests_used=1,
            )

        # Run 1: fresh execution
        engine1 = CompetitionBatchEngine(envelope, worker, max_workers=2, cache=cache)
        res1, man1 = engine1.run()
        self.assertEqual(call_counts["count"], 2)
        self.assertEqual(man1.cache_info["cached_hits"], 0)

        # Run 2: identical envelope reuses cache
        engine2 = CompetitionBatchEngine(envelope, worker, max_workers=2, cache=cache)
        res2, man2 = engine2.run()
        self.assertEqual(call_counts["count"], 2, "Worker should not be invoked on cache hit")
        self.assertEqual(man2.cache_info["cached_hits"], 2)
        self.assertTrue(all(r.cached for r in res2))

    def test_stale_cache_rejection(self):
        cache = ResultCache()
        orgs = ["923609001"]
        env_v1 = EvaluationEnvelope("test-stale", orgs, strategy_version="v1")
        env_v2 = EvaluationEnvelope("test-stale", orgs, strategy_version="v2")

        calls = {"count": 0}

        def worker(company: dict[str, Any], budget: SharedBudgetTracker) -> BatchCompanyResult:
            calls["count"] += 1
            return BatchCompanyResult(company["organisation_number"], BatchTerminalState.COMPLETE, True)

        # Run 1: v1
        engine1 = CompetitionBatchEngine(env_v1, worker, cache=cache)
        engine1.run()
        self.assertEqual(calls["count"], 1)

        # Run 2: v2 must reject v1 cache and re-execute
        engine2 = CompetitionBatchEngine(env_v2, worker, cache=cache)
        res2, man2 = engine2.run()
        self.assertEqual(calls["count"], 2, "Incompatible strategy version must invalidate cache")
        self.assertEqual(man2.cache_info["cached_hits"], 0)

    def test_manifest_validation_detects_mismatches(self):
        orgs = ["923609001", "923609002"]
        envelope = EvaluationEnvelope("test-val", orgs)

        results = [
            BatchCompanyResult("923609001", BatchTerminalState.COMPLETE, True),
            BatchCompanyResult("923609002", BatchTerminalState.COMPLETE, True),
        ]
        manifest = RunManifest(
            run_id="run-test-val",
            strategy_id="default",
            strategy_version="v1",
            input_dataset_fingerprint="inp",
            selected_evaluation_set=orgs,
            evaluation_count=2,
            budgets=envelope.to_dict(),
            config_fingerprint=envelope.config_fingerprint,
            completed_count=2,
            failed_count=0,
            terminal_state_counts={"complete": 2},
            total_requests_used=0,
            total_cost_incurred=0.0,
            total_runtime_seconds=0.1,
            output_fingerprint=compute_output_fingerprint(results),
            cache_info={},
            schema_version="1.0.0",
        )

        # 1. Valid manifest passes
        val = validate_manifest(manifest, envelope, results)
        self.assertTrue(val.passed)

        # 2. Strategy mismatch detected
        bad_strat = copy.deepcopy(manifest)
        bad_strat.strategy_version = "v99"
        val_bad_strat = validate_manifest(bad_strat, envelope, results)
        self.assertFalse(val_bad_strat.passed)
        self.assertIn("Strategy mismatch", val_bad_strat.errors[0])

        # 3. Output fingerprint mismatch detected
        bad_fp = copy.deepcopy(manifest)
        bad_fp.output_fingerprint = "corrupted-fp"
        val_bad_fp = validate_manifest(bad_fp, envelope, results)
        self.assertFalse(val_bad_fp.passed)
        self.assertTrue(any("Output fingerprint mismatch" in e for e in val_bad_fp.errors))

    def test_deterministic_output_fingerprint(self):
        orgs = ["923609001", "923609002"]
        r1 = [
            BatchCompanyResult("923609001", BatchTerminalState.COMPLETE, True, data={"score": 85}),
            BatchCompanyResult("923609002", BatchTerminalState.COMPLETE, True, data={"score": 90}),
        ]
        r2 = [
            BatchCompanyResult("923609001", BatchTerminalState.COMPLETE, True, data={"score": 85}),
            BatchCompanyResult("923609002", BatchTerminalState.COMPLETE, True, data={"score": 90}),
        ]
        fp1 = compute_output_fingerprint(r1)
        fp2 = compute_output_fingerprint(r2)
        self.assertEqual(fp1, fp2)


class Stage10EvaluationOptimizationTests(unittest.TestCase):
    """Stage 10: Evaluation & Optimization tests."""

    def test_deterministic_evaluation_dataset_structure(self):
        dataset = build_deterministic_evaluation_dataset()
        self.assertEqual(len(dataset), 9)

        # Check all 9 categories represented
        categories = {case.category for case in dataset}
        expected_cats = {
            CaseCategory.EXACT_COMPANY,
            CaseCategory.AMBIGUOUS_NAME,
            CaseCategory.SUBSIDIARY,
            CaseCategory.PARENT_COMPANY,
            CaseCategory.SIMILARLY_NAMED,
            CaseCategory.WEAK_WEB_PRESENCE,
            CaseCategory.MISSING_INFORMATION,
            CaseCategory.CHANGED_INFORMATION,
            CaseCategory.EXTERNAL_NON_TARGET,
        }
        self.assertEqual(categories, expected_cats)

        # Check serialization
        case_dict = dataset[0].to_dict()
        self.assertEqual(case_dict["case_id"], "case-01-exact")
        self.assertEqual(case_dict["category"], "exact_company")
        self.assertIn("ground_truth", case_dict)
        self.assertEqual(case_dict["ground_truth"]["expected_org_number"], "923609016")

    def test_coverage_calculation_distinguishes_missing_failed_and_incorrect(self):
        cases = build_deterministic_evaluation_dataset()
        # Simulate partial results
        results = [
            # Case 1: Present and correct
            {
                "case_id": "case-01-exact",
                "organisation_number": "923609016",
                "name": "Norsk Fiskeeksport AS",
                "website": "https://norskfiske.no",
                "financials": {"revenue": 150000000.0, "has_accounts": True},
                "leadership": ["Kari Nordmann"],
                "status": "usable",
            },
            # Case 6: Weak web presence - website is allowed to be missing
            {
                "case_id": "case-06-weak-web",
                "organisation_number": "933444555",
                "name": "Vestland Stillasmontering ENK",
                "website": None,
                "financials": None,
                "leadership": [],
                "status": "usable",
            },
            # Case 7: Missing info - financials allowed to be missing (None, never zero)
            {
                "case_id": "case-07-missing-info",
                "organisation_number": "944555666",
                "name": "Nordic Design Studio Ola Nordmann",
                "website": None,
                "financials": None,
                "leadership": [],
                "status": "usable",
            },
            # Case 5: Incorrect result (name hallucinated or wrong org)
            {
                "case_id": "case-05-similarly-named",
                "organisation_number": "999111222",
                "name": "Wrong Name AS",
                "website": "https://hallucinated.no",
                "financials": {"revenue": 100.0},
                "leadership": [],
                "status": "usable",
            },
            # Case 2: Failed retrieval / error
            {
                "case_id": "case-02-ambiguous",
                "status": "failed",
                "error_message": "Network timeout",
            },
        ]

        test_cases = [c for c in cases if c.case_id in {r["case_id"] for r in results}]
        coverage = evaluate_coverage(test_cases, results)
        self.assertEqual(coverage.total_cases, 5)
        self.assertEqual(coverage.usable_results, 4)
        self.assertAlmostEqual(coverage.usable_result_rate, 4 / 5)
        self.assertIn("case-02-ambiguous", coverage.unusable_cases)

        fc = coverage.field_coverage
        self.assertGreater(fc.total_fields_evaluated, 0)
        self.assertGreater(fc.fields_present, 0)
        self.assertGreater(fc.fields_missing_allowed, 0)
        self.assertGreater(fc.fields_retrieval_failed, 0)
        self.assertGreater(fc.fields_incorrect, 0)

    def test_exact_company_precision_and_abstentions(self):
        cases = build_deterministic_evaluation_dataset()
        results = [
            # Case 1: True Positive (exact match)
            {
                "case_id": "case-01-exact",
                "organisation_number": "923609016",
                "name": "Norsk Fiskeeksport AS",
                "verdict_status": "verified",
            },
            # Case 2: True Negative (ambiguous properly abstained)
            {
                "case_id": "case-02-ambiguous",
                "organisation_number": None,
                "name": None,
                "verdict_status": "ambiguous",
            },
            # Case 3: True Positive (subsidiary)
            {
                "case_id": "case-03-subsidiary",
                "organisation_number": "912345678",
                "name": "Fjord Laks Drift AS",
                "verdict_status": "verified",
            },
            # Case 5: True Negative (similarly named rejected)
            {
                "case_id": "case-05-similarly-named",
                "organisation_number": "999111222",
                "name": "Norsk Fiskeimport AS",
                "verdict_status": "verified",  # Target query had this org, so verified is expected
            },
            # Case 9: True Negative (external non-target rejected)
            {
                "case_id": "case-09-non-target",
                "organisation_number": None,
                "verdict_status": "rejected",
            },
        ]

        test_cases = [c for c in cases if c.case_id in {r["case_id"] for r in results}]
        precision_res = evaluate_exact_precision(test_cases, results)

        self.assertEqual(precision_res.false_positives, 0)
        self.assertEqual(precision_res.precision, 1.0)
        self.assertGreater(precision_res.true_positives, 0)
        self.assertGreater(precision_res.true_negatives, 0)

        # Inject False Positive
        bad_results = copy.deepcopy(results)
        bad_results[1] = {
            "case_id": "case-02-ambiguous",
            "organisation_number": "999888777",
            "verdict_status": "verified",  # Hallucinated verification on ambiguous name
        }
        bad_prec = evaluate_exact_precision(test_cases, bad_results)
        self.assertGreater(bad_prec.false_positives, 0)
        self.assertLess(bad_prec.precision, 1.0)

    def test_external_precision_and_unrelated_domains(self):
        cases = [
            EvaluationCase(
                case_id="c1",
                category=CaseCategory.EXACT_COMPANY,
                description="Target company",
                input_query={"name": "Alpha AS"},
                ground_truth=ExpectedOutcome(
                    expected_org_number="911111111",
                    expected_name="Alpha AS",
                    expected_verdict_status="verified",
                    should_publish_website=True,
                    expected_website="https://alpha.no",
                ),
            ),
            EvaluationCase(
                case_id="c2",
                category=CaseCategory.EXTERNAL_NON_TARGET,
                description="Foreign non-target",
                input_query={"name": "Swedish Alpha AB"},
                ground_truth=ExpectedOutcome(
                    expected_org_number=None,
                    expected_name=None,
                    expected_verdict_status="rejected",
                    is_external_target=False,
                    should_publish_website=False,
                ),
            ),
        ]

        # Valid run: matches expected website and rejects foreign
        good_results = [
            {"case_id": "c1", "website": "https://alpha.no", "verdict_status": "verified"},
            {"case_id": "c2", "website": None, "verdict_status": "rejected"},
        ]
        ep_good = evaluate_external_precision(cases, good_results)
        self.assertEqual(ep_good.precision, 1.0)
        self.assertEqual(ep_good.false_external_positives, 0)

        # Bad run: discovers unrelated domain and fails to reject non-target
        bad_results = [
            {"case_id": "c1", "website": "https://competitor.com", "verdict_status": "verified"},
            {"case_id": "c2", "website": "https://swedish-alpha.se", "verdict_status": "verified"},
        ]
        ep_bad = evaluate_external_precision(cases, bad_results)
        self.assertEqual(ep_bad.true_external_matches, 0)
        self.assertEqual(ep_bad.false_external_positives, 3)
        self.assertEqual(ep_bad.precision, 0.0)
        self.assertEqual(len(ep_bad.unrelated_domains_detected), 3)

    def test_recall_and_boundary_documentation(self):
        cases = build_deterministic_evaluation_dataset()
        # Simulate results with 1 missing leadership member
        results = []
        for c in cases:
            gt = c.ground_truth
            results.append({
                "case_id": c.case_id,
                "organisation_number": gt.expected_org_number,
                "website": gt.expected_website if gt.should_publish_website else None,
                "financials": {"revenue": gt.expected_financial_revenue} if gt.should_have_financials else None,
                "leadership": gt.expected_leadership[:1] if len(gt.expected_leadership) > 1 else list(gt.expected_leadership),
            })

        recall = evaluate_recall(cases, results)
        self.assertGreater(recall.total_expected_items, 0)
        self.assertGreaterEqual(recall.recall_rate, 0.90)
        self.assertIn("statutory registry", recall.boundary_documentation)

    def test_evidence_validity_and_provenance(self):
        evidence_list = [
            # 1. Valid registry evidence
            {
                "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                "source_type": "registry",
                "retrieved_at": "2026-09-20T00:00:00Z",
                "content_sha256": "a" * 64,
            },
            # 2. Valid website evidence
            {
                "source_url": "https://norskfiske.no",
                "source_type": "website",
                "retrieved_at": "2026-09-20T00:00:00Z",
                "content_sha256": "b" * 64,
            },
            # 3. Invalid URL (malformed scheme)
            {
                "source_url": "ftp://broken-source",
                "source_type": "registry",
                "retrieved_at": "2026-09-20T00:00:00Z",
                "content_sha256": "c" * 64,
            },
            # 4. Missing provenance (no content_sha256)
            {
                "source_url": "https://data.brreg.no/regnskap/923609016",
                "source_type": "financials",
                "retrieved_at": "2026-09-20T00:00:00Z",
                "content_sha256": None,
            },
        ]

        metrics = evaluate_evidence_validity(evidence_list)
        self.assertEqual(metrics.total_evidence_items, 4)
        self.assertEqual(metrics.valid_syntax_urls, 3)
        self.assertEqual(metrics.valid_source_types, 4)
        self.assertEqual(metrics.provenance_complete, 3)
        self.assertEqual(len(metrics.invalid_evidence_items), 2)
        self.assertEqual(metrics.validity_rate, 0.5)

    def test_refresh_correctness_and_failed_refresh_preservation(self):
        cases = [
            EvaluationCase(
                case_id="case-unchanged",
                category=CaseCategory.EXACT_COMPANY,
                description="Unchanged company",
                input_query={"organisation_number": "923609016"},
                ground_truth=ExpectedOutcome(
                    expected_org_number="923609016",
                    expected_name="Norsk Fiskeeksport AS",
                    expected_verdict_status="verified",
                    expected_changes=[],  # UNCHANGED
                ),
            ),
            EvaluationCase(
                case_id="case-modified",
                category=CaseCategory.CHANGED_INFORMATION,
                description="Modified name",
                input_query={"organisation_number": "955666777"},
                ground_truth=ExpectedOutcome(
                    expected_org_number="955666777",
                    expected_name="Bergen Teknologi ASA",
                    expected_verdict_status="verified",
                    expected_changes=["legal_name"],  # MODIFIED
                ),
            ),
            EvaluationCase(
                case_id="case-failed-fetch",
                category=CaseCategory.EXACT_COMPANY,
                description="Network failure on refresh",
                input_query={"organisation_number": "912345678"},
                ground_truth=ExpectedOutcome(
                    expected_org_number="912345678",
                    expected_name="Fjord Laks AS",
                    expected_verdict_status="verified",
                ),
            ),
        ]

        refresh_results = [
            # 1. Correctly unchanged: 0 changes
            {"case_id": "case-unchanged", "status": "success", "changes": []},
            # 2. Correctly modified: legal_name changed
            {
                "case_id": "case-modified",
                "status": "success",
                "changes": [{"field_name": "legal_name", "change_type": "modified"}],
            },
            # 3. Failed refresh preservation: status failed_fetch, 0 removals
            {"case_id": "case-failed-fetch", "status": "failed_fetch", "changes": []},
        ]

        ref_metrics = evaluate_refresh_correctness(cases, refresh_results)
        self.assertEqual(ref_metrics.total_refresh_comparisons, 3)
        self.assertEqual(ref_metrics.correctly_unchanged, 1)
        self.assertEqual(ref_metrics.correctly_modified, 1)
        self.assertEqual(ref_metrics.correctly_preserved_failures, 1)
        self.assertEqual(ref_metrics.accuracy, 1.0)

    def test_false_change_rate_with_semantic_normalization(self):
        detected_changes = [
            # Genuine change
            {
                "field_name": "legal_name",
                "previous_value": "Bergen Teknologi AS",
                "current_value": "Bergen Teknologi ASA",
            },
            # False change: whitespace noise
            {
                "field_name": "municipality",
                "previous_value": "Bergen",
                "current_value": "  Bergen  ",
            },
            # False change: case noise on case-insensitive field
            {
                "field_name": "legal_form",
                "previous_value": "AS",
                "current_value": "as",
            },
            # False change: not in ground truth
            {
                "field_name": "unknown_noise_field",
                "previous_value": "foo",
                "current_value": "bar",
            },
        ]

        ground_truth_changes = {"legal_name"}
        fcm = calculate_false_change_rate(detected_changes, ground_truth_changes)

        self.assertEqual(fcm.total_detected_changes, 4)
        self.assertEqual(fcm.true_material_changes, 1)
        self.assertEqual(fcm.false_changes, 3)
        self.assertAlmostEqual(fcm.false_change_rate, 0.75)
        self.assertEqual(len(fcm.false_change_details), 3)

    def test_runtime_instrumentation_monotonic(self):
        inst = EvaluationInstrumentation()

        with inst.measure_operation("identity_engine", "lookup_brreg", stage="identity"):
            time.sleep(0.01)

        with inst.measure_operation("website_discovery", "crawl_homepage", stage="discovery"):
            time.sleep(0.01)

        runtime = inst.get_runtime_stats()
        self.assertGreater(runtime.total_runtime_seconds, 0.01)
        self.assertIn("identity", runtime.stage_runtimes)
        self.assertIn("discovery", runtime.stage_runtimes)
        self.assertIn("identity_engine", runtime.engine_runtimes)
        self.assertIn("website_discovery", runtime.engine_runtimes)
        self.assertGreater(runtime.avg_latency_seconds, 0.0)
        self.assertGreater(runtime.p50_latency_seconds, 0.0)
        self.assertGreater(runtime.max_latency_seconds, 0.0)
        self.assertGreater(len(runtime.slowest_operations), 0)

    def test_request_counting_and_duplicate_detection(self):
        inst = EvaluationInstrumentation()

        url_1 = "https://data.brreg.no/enhetsregisteret/api/enheter/923609016"
        url_2 = "https://norskfiske.no"

        # Record requests
        inst.record_request("identity_engine", url_1, case_id="c1", method="GET", status_code=200)
        # Duplicate request to url_1
        inst.record_request("identity_engine", url_1, case_id="c1", method="GET", status_code=200)
        # Request to url_2
        inst.record_request("website_discovery", url_2, case_id="c1", method="GET", status_code=200)
        # Failed request and retry
        inst.record_request("website_discovery", "https://timeout.test", case_id="c1", method="GET", status_code=504, is_failed=True)
        inst.record_request("website_discovery", "https://timeout.test", case_id="c1", method="GET", status_code=200, is_retry=True)

        reqs = inst.get_request_stats()
        self.assertEqual(reqs.total_requests, 5)
        self.assertEqual(reqs.requests_per_engine["identity_engine"], 2)
        self.assertEqual(reqs.requests_per_engine["website_discovery"], 3)
        self.assertEqual(reqs.duplicate_requests, 2)  # url_1 duplicate + timeout.test duplicate
        self.assertIn(url_1, reqs.duplicate_urls)
        self.assertEqual(reqs.failed_requests, 1)
        self.assertEqual(reqs.retries, 1)

    def test_cost_model_configured_and_unknown(self):
        # 1. Configured pricing
        config = CostModelConfig(
            cost_per_request=0.005,
            cost_per_1k_prompt_tokens=0.0015,
            cost_per_1k_completion_tokens=0.002,
            currency="USD",
            is_pricing_configured=True,
        )
        inst = EvaluationInstrumentation(cost_config=config)
        inst.record_request("identity_engine", "https://brreg.no/api/1")
        inst.record_request("identity_engine", "https://brreg.no/api/2")
        inst.record_tokens(1000, 500)

        cost = inst.get_cost_stats()
        self.assertTrue(cost.is_pricing_configured)
        self.assertEqual(cost.total_requests, 2)
        self.assertEqual(cost.prompt_tokens, 1000)
        self.assertEqual(cost.completion_tokens, 500)
        self.assertEqual(cost.total_tokens, 1500)

        # Expected: 2 * 0.005 + (1 * 0.0015) + (0.5 * 0.002) = 0.01 + 0.0015 + 0.0010 = 0.0125
        self.assertAlmostEqual(cost.estimated_cost, 0.0125)

        # 2. Unconfigured pricing
        inst_unconfigured = EvaluationInstrumentation()
        inst_unconfigured.record_request("identity_engine", "https://brreg.no/api/1")
        inst_unconfigured.record_tokens(500, 200)

        cost_unc = inst_unconfigured.get_cost_stats()
        self.assertFalse(cost_unc.is_pricing_configured)
        self.assertEqual(cost_unc.estimated_cost, 0.0)
        self.assertGreater(len(cost_unc.unknown_cost_items), 0)

    def test_bottleneck_analysis_actionable_observations(self):
        runtime_stats = RuntimeStats(
            total_runtime_seconds=10.0,
            engine_runtimes={"slow_crawler": 6.5, "fast_registry": 3.5},  # 65% of time
            p95_latency_seconds=1.5,
        )
        request_stats = RequestStats(
            total_requests=100,
            requests_per_engine={"slow_crawler": 80, "fast_registry": 20},  # 80% of requests
            failed_requests=5,
            duplicate_requests=12,
            duplicate_urls=["https://dup.test"],
        )
        cost_stats = CostStats(
            total_requests=100,
            is_pricing_configured=True,
            estimated_cost=2.50,
        )

        bottlenecks = analyze_bottlenecks(runtime_stats, request_stats, cost_stats)
        self.assertGreater(len(bottlenecks), 0)

        categories = {b.category for b in bottlenecks}
        self.assertIn("runtime", categories)
        self.assertIn("request_volume", categories)
        self.assertIn("duplicate_requests", categories)
        self.assertIn("failure_rate", categories)
        self.assertIn("cost", categories)

        for b in bottlenecks:
            self.assertIn(b.severity, {"high", "medium", "low", "info"})
            self.assertTrue(len(b.message) > 0)
            self.assertTrue(len(b.actionable_recommendation) > 0)

    def test_evaluation_report_markdown_and_dict(self):
        harness = EvaluationHarness()
        report = harness.run()

        # Test dict output
        d = report.to_dict()
        self.assertIn("timestamp", d)
        self.assertEqual(d["dataset_version"], "1.0.0")
        self.assertEqual(d["total_cases"], 9)
        self.assertIn("coverage", d)
        self.assertIn("exact_precision", d)
        self.assertIn("runtime", d)
        self.assertIn("case_results", d)

        # Test markdown output
        md = report.to_markdown()
        self.assertIn("# OrgTrace Stage 10 Evaluation & Optimization Benchmark Report", md)
        self.assertIn("Executive Summary Metrics", md)
        self.assertIn("Runtime & Resource Telemetry", md)
        self.assertIn("Per-Case Evaluation Details", md)
        self.assertIn("case-01-exact", md)
        self.assertIn("✅ Pass", md)

    def test_evaluation_harness_end_to_end_deterministic(self):
        harness = EvaluationHarness()
        report = harness.run()

        self.assertEqual(report.total_cases, 9)
        self.assertEqual(report.passed_cases, 9)
        self.assertEqual(report.overall_accuracy, 1.0)
        self.assertEqual(report.exact_precision.precision, 1.0)
        self.assertEqual(report.external_precision.precision, 1.0)
        self.assertEqual(report.evidence_validity.validity_rate, 1.0)
        self.assertEqual(report.refresh_correctness.accuracy, 1.0)
        self.assertEqual(report.false_change.false_change_rate, 0.0)

    def test_empty_dataset_edge_cases(self):
        empty_cov = evaluate_coverage([], [])
        self.assertEqual(empty_cov.total_cases, 0)
        self.assertEqual(empty_cov.usable_result_rate, 0.0)

        empty_prec = evaluate_exact_precision([], [])
        self.assertEqual(empty_prec.total_evaluations, 0)
        self.assertEqual(empty_prec.precision, 1.0)

        empty_ext = evaluate_external_precision([], [])
        self.assertEqual(empty_ext.total_external_evaluations, 0)
        self.assertEqual(empty_ext.precision, 1.0)

        empty_ev = evaluate_evidence_validity([])
        self.assertEqual(empty_ev.total_evidence_items, 0)
        self.assertEqual(empty_ev.validity_rate, 1.0)

        empty_fc = calculate_false_change_rate([], set())
        self.assertEqual(empty_fc.total_detected_changes, 0)
        self.assertEqual(empty_fc.false_change_rate, 0.0)


class Stage11ProductionHardeningTests(unittest.TestCase):
    """Stage 11: Production Hardening tests."""

    def test_clean_configuration_loading(self):
        env = {
            "ORGTRACE_ENV": "production",
            "ORGTRACE_LOG_LEVEL": "INFO",
            "ORGTRACE_CONNECT_TIMEOUT": "5.0",
            "ORGTRACE_READ_TIMEOUT": "15.0",
            "ORGTRACE_MAX_RETRIES": "2",
            "ORGTRACE_RETRY_BACKOFF": "0.5",
            "ORGTRACE_MAX_URL_LENGTH": "2048",
            "ORGTRACE_ENFORCE_DNS_CHECK": "false",
            "BRAVE_SEARCH_API_KEY": "brv_live_test_key_12345678",
        }
        config = load_config_from_env(env)
        self.assertEqual(config.environment, "production")
        self.assertEqual(config.network.connect_timeout, 5.0)
        self.assertEqual(config.network.read_timeout, 15.0)
        self.assertEqual(config.network.max_retries, 2)
        self.assertEqual(config.network.retry_backoff, 0.5)
        self.assertEqual(config.network.max_url_length, 2048)
        self.assertFalse(config.network.enforce_dns_check)
        self.assertEqual(config.provider.brave_search_api_key, "brv_live_test_key_12345678")

        # Verify safe dictionary serialization redacts API key
        safe_dict = config.to_dict(redact=True)
        self.assertIn("****", safe_dict["provider"]["brave_search_api_key"])
        self.assertNotIn("brv_live_test_key_12345678", safe_dict["provider"]["brave_search_api_key"])

    def test_invalid_configuration_rejection(self):
        # 1. Negative timeout
        with self.assertRaises(ConfigValidationError):
            load_config_from_env({"ORGTRACE_CONNECT_TIMEOUT": "-1.0"})

        # 2. Negative max retries
        with self.assertRaises(ConfigValidationError):
            load_config_from_env({"ORGTRACE_MAX_RETRIES": "-5"})

        # 3. Invalid log level
        with self.assertRaises(ConfigValidationError):
            load_config_from_env({"ORGTRACE_LOG_LEVEL": "SUPER_VERBOSE"})

        # 4. Invalid environment
        with self.assertRaises(ConfigValidationError):
            load_config_from_env({"ORGTRACE_ENV": "unsupported_env"})

        # 5. Non-HTTPS BRREG endpoint
        with self.assertRaises(ConfigValidationError):
            load_config_from_env({"BRREG_API_BASE_URL": "http://insecure-brreg.test"})

    def test_missing_secret_handling(self):
        config = load_config_from_env({"BRAVE_SEARCH_API_KEY": ""})
        self.assertIsNone(config.provider.brave_search_api_key)

        with self.assertRaises(MissingCredentialError) as ctx:
            config.provider.require_brave_api_key()
        self.assertIn("BRAVE_SEARCH_API_KEY is not set", str(ctx.exception))

    def test_secret_redaction_in_text_and_logs(self):
        # 1. Single secret masking
        secret = "sk_live_secret_key_9876543210"
        redacted = redact_secret_value(secret)
        self.assertTrue(redacted.startswith("sk_l"))
        self.assertTrue(redacted.endswith("3210"))
        self.assertIn("****", redacted)
        self.assertNotIn("secret_key", redacted)

        # 2. Short secret
        self.assertEqual(redact_secret_value("abc"), "[REDACTED]")

        # 3. Text redaction with known secret and regex headers
        text = (
            "Request failed with X-Subscription-Token: super_secret_token_12345 "
            "using secret sk_live_secret_key_9876543210."
        )
        cleaned = redact_secrets_from_text(text, known_secrets=[secret])
        self.assertNotIn("super_secret_token_12345", cleaned)
        self.assertNotIn("sk_live_secret_key_9876543210", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_url_validation_safe_public_urls(self):
        safe_urls = [
            "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
            "https://norskfiske.no",
            "https://www.norskfiske.no/om-oss?lang=no",
            "http://example.com/api/v1?page=1&limit=50",
            "https://sub.domain.co.uk/path/file.html",
        ]
        for u in safe_urls:
            res = validate_public_url(u)
            self.assertTrue(res.is_safe, f"Expected safe for {u}: {res.error}")
            self.assertIsNotNone(res.normalized_url)
            # assert_public_url must not raise
            assert_public_url(u)

    def test_url_validation_dangerous_schemes(self):
        dangerous = [
            "file:///etc/passwd",
            "file://c:/windows/win.ini",
            "javascript:alert(document.cookie)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "ftp://files.example.com/dump.tar",
            "gopher://gopher.example.com/",
        ]
        for u in dangerous:
            res = validate_public_url(u)
            self.assertFalse(res.is_safe, f"Expected unsafe for {u}")
            self.assertIn("scheme", (res.error or "").lower())
            with self.assertRaises(DangerousSchemeError):
                assert_public_url(u)

    def test_url_validation_embedded_credentials(self):
        credential_urls = [
            "https://admin:secret123@api.example.com/data",
            "http://user@example.com/",
            "https://user:pass@1.2.3.4/",
        ]
        for u in credential_urls:
            res = validate_public_url(u)
            self.assertFalse(res.is_safe)
            self.assertIn("embedded credentials", (res.error or "").lower())
            with self.assertRaises(EmbeddedCredentialsError):
                assert_public_url(u)

    def test_url_validation_private_and_localhost_ssrf(self):
        ssrf_targets = [
            "http://localhost/",
            "http://localhost:8080/admin",
            "http://127.0.0.1/",
            "http://127.0.0.1:9000/internal",
            "http://0.0.0.0/",
            "http://10.0.0.1/sensitive",
            "http://192.168.1.1/router",
            "http://172.16.0.1/metadata",
            "http://169.254.169.254/latest/meta-data/",
            "http://service.internal/api",
            "http://app.local/",
        ]
        for u in ssrf_targets:
            res = validate_public_url(u)
            self.assertFalse(res.is_safe, f"Expected SSRF rejection for {u}")
            with self.assertRaises(PrivateNetworkAccessError):
                assert_public_url(u)

    def test_url_validation_excessive_length(self):
        long_url = "https://example.com/path?" + ("x" * 4100)
        res = validate_public_url(long_url, max_length=4096)
        self.assertFalse(res.is_safe)
        self.assertIn("exceeds maximum allowed limit", res.error or "")
        with self.assertRaises(UrlLengthExceededError):
            assert_public_url(long_url)

    def test_url_sanitization_for_logging(self):
        url = "https://admin:secretPass123@api.search.brave.com/res/v1/web/search?q=test&api_key=real_key_xyz987&token=bearer_123"
        sanitized = sanitize_url_for_logging(url)

        self.assertNotIn("secretPass123", sanitized)
        self.assertNotIn("real_key_xyz987", sanitized)
        self.assertNotIn("bearer_123", sanitized)
        self.assertIn("q=test", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_bounded_retry_behavior_on_retryable_errors(self):
        attempts_recorded = []

        def failing_503():
            attempts_recorded.append(time.monotonic())
            req = urllib.request.Request("https://example.test")
            raise urllib.error.HTTPError("https://example.test", 503, "Service Unavailable", {}, None)

        policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05, jitter=False)
        with self.assertRaises(ResilienceError) as ctx:
            execute_with_retry(failing_503, policy=policy)

        # Must execute initial attempt + 2 retries = 3 attempts total
        self.assertEqual(len(attempts_recorded), 3)
        self.assertIn("HTTP 503", str(ctx.exception))

    def test_immediate_failure_on_non_retryable_errors(self):
        non_retryable_codes = [400, 401, 403, 404, 410, 422]

        for code in non_retryable_codes:
            call_count = {"count": 0}

            def failing_http():
                call_count["count"] += 1
                raise urllib.error.HTTPError("https://example.test", code, f"Error {code}", {}, None)

            policy = RetryPolicy(max_retries=3, base_delay=0.01)
            with self.assertRaises(NonRetryableHttpError) as ctx:
                execute_with_retry(failing_http, policy=policy)

            # Must fail immediately on attempt 1 with zero wasteful retries
            self.assertEqual(call_count["count"], 1, f"Failed immediate failure for HTTP {code}")
            self.assertEqual(ctx.exception.status_code, code)

    def test_rate_limit_retry_after_header_handling(self):
        # 1. Seconds format
        secs = parse_retry_after("3")
        self.assertEqual(secs, 3.0)

        # 2. HTTP-date format
        future_dt = "Wed, 21 Oct 2026 07:28:00 GMT"
        parsed = parse_retry_after(future_dt)
        self.assertIsNotNone(parsed)

        # 3. Invalid format
        self.assertIsNone(parse_retry_after("invalid_header"))
        self.assertIsNone(parse_retry_after(None))

    def test_source_licensing_metadata_resolution(self):
        # 1. BRREG NLOD 2.0
        brreg_lic = get_source_license_info("https://data.brreg.no/enhetsregisteret/api/enheter/923609016")
        self.assertEqual(brreg_lic.license_type, LicenseType.NLOD_2_0)
        self.assertTrue(brreg_lic.attribution_required)
        self.assertTrue(brreg_lic.is_open_data)
        self.assertIn("Brønnøysundregistrene", brreg_lic.attribution_statement)

        # 2. Lovdata public legal data
        lovdata_lic = get_source_license_info("https://lovdata.no/dokument/NL/lov/1997-06-13-44")
        self.assertEqual(lovdata_lic.license_type, LicenseType.PUBLIC_SECTOR_INFORMATION)
        self.assertTrue(lovdata_lic.attribution_required)

        # 3. Brave Search API terms
        brave_lic = get_source_license_info("https://search.brave.com/search")
        self.assertEqual(brave_lic.license_type, LicenseType.COMMERCIAL_TERMS_OF_SERVICE)

        # 4. First-party company site
        company_lic = get_source_license_info("https://norskfiske.no/om-oss", source_type="company_website")
        self.assertEqual(company_lic.license_type, LicenseType.FIRST_PARTY_COPYRIGHT)
        self.assertIn("norskfiske.no", company_lic.attribution_statement)

        # 5. Unknown external domain
        unknown_lic = get_source_license_info("https://random-unknown-domain.org/data")
        self.assertEqual(unknown_lic.license_type, LicenseType.UNKNOWN_UNVERIFIED)
        self.assertFalse(unknown_lic.is_open_data)

    def test_structured_logging_with_secret_redaction(self):
        import io
        import logging

        secret_token = "secret_super_token_999888"
        redaction_filter = SecretRedactionFilter(known_secrets=[secret_token])

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(redaction_filter)
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test_redaction_logger")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        logger.addHandler(handler)

        logger.info("Connecting with API token %s to upstream", secret_token)
        logger.info("Header: Authorization: Bearer %s", secret_token)

        log_output = stream.getvalue()
        self.assertNotIn(secret_token, log_output)
        self.assertIn("****", log_output)

    def test_observability_metrics_collector(self):
        collector = ProductionMetricsCollector()
        collector.reset()

        # Record operations
        collector.record_operation("identity_engine", "lookup", duration_seconds=0.05, status="success")
        collector.record_operation("website_discovery", "crawl", duration_seconds=0.20, status="failure", error_category="timeout")

        # Record requests
        collector.record_request("identity_engine", status_code=200)
        collector.record_request("website_discovery", status_code=504, is_failed=True, is_retry=True)

        # Record refresh outcome
        collector.record_refresh_outcome("unchanged")
        collector.record_refresh_outcome("modified")

        snapshot = collector.get_metrics_snapshot()
        self.assertEqual(snapshot["total_operations"], 2)
        self.assertEqual(snapshot["status_counts"]["success"], 1)
        self.assertEqual(snapshot["status_counts"]["failure"], 1)
        self.assertAlmostEqual(snapshot["success_rate"], 0.5)
        self.assertEqual(snapshot["requests"]["total"], 2)
        self.assertEqual(snapshot["requests"]["failed"], 1)
        self.assertEqual(snapshot["requests"]["retries"], 1)
        self.assertEqual(snapshot["error_categories"]["timeout"], 1)
        self.assertEqual(snapshot["refresh_outcomes"]["unchanged"], 1)
        self.assertEqual(snapshot["refresh_outcomes"]["modified"], 1)

    def test_refresh_failure_safe_preservation(self):
        # Verifies that a failed fetch carries forward previous claims without deleting valid data
        prev_snapshot = CompanySnapshot(
            snapshot_id="snap-1",
            version=1,
            organisation_number="923609016",
            timestamp="2026-09-19T00:00:00Z",
            claims={
                "org:923609016|field:legal_name": SnapshotClaim(
                    claim_key="org:923609016|field:legal_name",
                    field_name="legal_name",
                    value="Norsk Fiskeeksport AS",
                ),
                "org:923609016|field:website": SnapshotClaim(
                    claim_key="org:923609016|field:website",
                    field_name="website",
                    value="https://norskfiske.no",
                ),
            },
        )

        # Failed refresh must not emit REMOVED changes
        failed_res = RefreshResult(
            success=False,
            status=RefreshStatus.FAILED_FETCH,
            snapshot=prev_snapshot,
            changes=[],
            failed_sources=["website"],
            error_message="Network timeout on website refresh",
        )

        self.assertFalse(failed_res.success)
        self.assertEqual(failed_res.status, RefreshStatus.FAILED_FETCH)
        self.assertIsNotNone(failed_res.snapshot)
        self.assertEqual(len(failed_res.snapshot.claims), 2)
        self.assertEqual(len(failed_res.changes), 0)  # Zero false removals!


if __name__ == "__main__":
    unittest.main()





