from __future__ import annotations

import pytest

from norway_company_agent.batch import terminal_envelope, validate_envelopes
from norway_company_agent.discovery import (
    build_company_search_queries,
    choose_search_candidate,
    score_search_candidate,
)
from norway_company_agent.evidence import evidence, utc_now
from norway_company_agent.identity import apply_website_identity_gate
from norway_company_agent.resilience import CompetitionExecutionGuard
from norway_company_agent.search_enrichment import extract_search_enrichment
from norway_company_agent.website import assert_public_url, normalize_social_url


# ---------------------------------------------------------------------------
# Website Discovery Tests (Phase 2 & Phase 8)
# ---------------------------------------------------------------------------

def test_website_discovery_query_variants():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    queries = build_company_search_queries(profile)
    assert len(queries) >= 2


def test_website_candidate_accepted():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    result = {
        "url": "https://nordictech.no/",
        "title": "Nordic Tech AS - Offisiell nettside",
        "snippet": "Nordic Tech AS org nr 123456789 i Oslo leverer programvare.",
        "rank": 1,
    }
    scored = score_search_candidate(profile, result)
    assert scored["publishable_candidate"] is True
    assert scored["status"] == "accepted_for_crawl"


def test_website_candidate_aggregator_rejected():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    for host in ["proff.no", "purehelp.no", "1881.no", "gulesider.no"]:
        result = {
            "url": f"https://www.{host}/selskap/nordic-tech-as/123456789",
            "title": "Nordic Tech AS - Proff",
            "snippet": "Nordic Tech AS 123456789",
            "rank": 1,
        }
        scored = score_search_candidate(profile, result)
        assert scored["publishable_candidate"] is False
        assert scored["status"] == "rejected"


def test_wrong_same_name_company_rejected():
    """A search snippet citing a conflicting 9-digit org number must be rejected."""
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    result = {
        "url": "https://nordictech-bergen.no/",
        "title": "Nordic Tech AS",
        "snippet": "Nordic Tech AS er registrert i Bergen med org nr 987654321.",
        "rank": 1,
    }
    scored = score_search_candidate(profile, result)
    assert scored["publishable_candidate"] is False
    assert scored["status"] == "rejected"
    assert "conflicting organisation number" in scored["reasons"][0]


def test_exact_org_number_candidate_preferred():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    results = [
        {
            "url": "https://nordictech.com/",
            "title": "Nordic Tech Consulting",
            "snippet": "Consulting services across the Nordics.",
            "rank": 1,
        },
        {
            "url": "https://nordictech.no/",
            "title": "Nordic Tech AS",
            "snippet": "Nordic Tech AS, org.nr. 123456789, Oslo.",
            "rank": 2,
        },
    ]
    decision = choose_search_candidate(profile, results)
    assert decision["selected"] is not None
    assert decision["selected"]["url"] == "https://nordictech.no/"


# ---------------------------------------------------------------------------
# Social Discovery Tests (Phase 3 & Phase 8)
# ---------------------------------------------------------------------------

def test_valid_linkedin_company_url_accepted():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    norm = normalize_social_url("https://www.linkedin.com/company/example-consulting/")
    assert norm is not None
    assert norm["platform"] == "linkedin"
    assert norm["url"] == "https://linkedin.com/company/example-consulting"


def test_personal_linkedin_rejected():
    assert normalize_social_url("https://www.linkedin.com/in/someone/") is None


def test_instagram_company_profile_accepted():
    norm = normalize_social_url("https://www.instagram.com/exampleconsulting/")
    assert norm is not None
    assert norm["platform"] == "instagram"
    assert norm["url"] == "https://instagram.com/exampleconsulting"


def test_instagram_post_and_reel_rejected():
    assert normalize_social_url("https://www.instagram.com/example/reel/123") is None
    assert normalize_social_url("https://www.instagram.com/example/p/123") is None
    assert normalize_social_url("https://www.instagram.com/reel/123") is None
    assert normalize_social_url("https://www.instagram.com/p/123") is None


def test_facebook_share_rejected():
    assert normalize_social_url("https://www.facebook.com/sharer/sharer.php?u=https://example.no") is None
    assert normalize_social_url("https://www.facebook.com/share.php?u=https://example.no") is None


def test_youtube_channel_accepted():
    norm = normalize_social_url("https://www.youtube.com/@exampleconsulting")
    assert norm is not None
    assert norm["platform"] == "youtube"


def test_social_identity_gate_rejects_unrelated():
    """If handle does not match company legal name, it must be rejected."""
    profile = {"name": "Bergen Shipping AS", "organisation_number": "111222333", "municipality": "Bergen"}
    results = [
        {
            "url": "https://www.linkedin.com/company/oslo-bakery-as/",
            "title": "Oslo Bakery AS - mentioned Bergen Shipping AS",
            "snippet": "Oslo Bakery AS collaborates with Bergen Shipping AS",
        }
    ]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["social_profiles"]) == 0


# ---------------------------------------------------------------------------
# News Discovery Tests (Phase 4 & Phase 8)
# ---------------------------------------------------------------------------

def test_dated_news_accepted():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    results = [
        {
            "url": "https://e24.no/naeringsliv/i/123/example-consulting-avtale",
            "title": "Example Consulting AS inngår ny storkontrakt",
            "snippet": "Publisert 15. mai 2024. Example Consulting AS i Oslo melder om avtale.",
            "page_age": "2024-05-15",
        }
    ]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["news"]) == 1
    assert found["news"][0]["date"] == "2024-05-15"
    assert found["news"][0]["url"] == "https://e24.no/naeringsliv/i/123/example-consulting-avtale"


def test_undated_news_rejected():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    results = [
        {
            "url": "https://news.example.no/undated-story",
            "title": "Example Consulting AS kunngjør nytt produkt",
            "snippet": "Example Consulting AS lanserer sin nye tjeneste for bedrifter.",
        }
    ]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["news"]) == 0


def test_unrelated_news_rejected():
    profile = {"name": "Stavanger Olje AS", "organisation_number": "333444555", "municipality": "Stavanger"}
    results = [
        {
            "url": "https://e24.no/nyhet/oslo-tech-nyhet",
            "title": "Trondheim Bakeri AS vinner pris 2024-06-01",
            "snippet": "Trondheim Bakeri AS har vunnet årets bakeri 2024-06-01.",
            "result_kind": "news",
        }
    ]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["news"]) == 0


# ---------------------------------------------------------------------------
# ATS / Hiring Tests (Phase 5 & Phase 8)
# ---------------------------------------------------------------------------

def test_ats_platforms_recognized():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    ats_urls = [
        ("https://nordictech.teamtailor.com/jobs", "Teamtailor"),
        ("https://nordictech.reachmee.com/jobs", "ReachMee"),
        ("https://jobbnorge.no/ledige-stillinger/stilling/123/nordic-tech-as", "Jobbnorge"),
        ("https://nordictech.webcruiter.no/stillinger", "Webcruiter"),
        ("https://nordictech.recman.no/jobs", "RecMan"),
        ("https://www.finn.no/jobb/stilling/123456", "Finn"),
        ("https://nordictech.bamboohr.com/careers", "BambooHR"),
    ]
    for url, expected_platform in ats_urls:
        results = [{
            "url": url,
            "title": "Nordic Tech AS - Stillinger",
            "snippet": "Nordic Tech AS søker medarbeidere.",
        }]
        found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
        assert len(found["hiring"]) == 1
        assert found["hiring"][0]["platform"] == expected_platform


def test_finn_non_job_rejected():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    results = [{
        "url": "https://www.finn.no/bap/forsale/ad.html?finnkode=999",
        "title": "Nordic Tech AS selger kontorstoler",
        "snippet": "Nordic Tech AS selger 5 kontorstoler på finn torget.",
    }]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["hiring"]) == 0


def test_explicit_hiring_opening_true():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    results = [{
        "url": "https://nordictech.teamtailor.com/jobs",
        "title": "Nordic Tech AS - Vi søker senior utvikler",
        "snippet": "Ledige stillinger hos Nordic Tech AS. Bli med på laget vårt!",
    }]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["hiring"]) == 1
    assert found["hiring"][0]["hiring_active"] is True


def test_careers_portal_without_openings_none():
    profile = {"name": "Nordic Tech AS", "organisation_number": "123456789", "municipality": "Oslo"}
    results = [{
        "url": "https://nordictech.teamtailor.com/",
        "title": "Nordic Tech AS Career Site",
        "snippet": "Welcome to Nordic Tech AS.",
    }]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["hiring"]) == 1
    assert found["hiring"][0]["hiring_active"] is None


# ---------------------------------------------------------------------------
# Guard, Identity, Robots, SSRF, & Envelopes (Phase 8)
# ---------------------------------------------------------------------------

def test_guard_remains_under_limit():
    guard = CompetitionExecutionGuard(max_requests=2000, max_cost=10.0)
    for _ in range(500):
        ok, _ = guard.acquire_request(cost=0.005)
        assert ok is True
    assert guard.tracked_requests == 500
    assert guard.cost_incurred <= 2.50
    assert guard.remaining_requests == 1500


def test_identity_gate_rejects_mismatch():
    profile = {"name": "Alpha Solutions AS", "organisation_number": "111222333"}
    website_record = {
        "status": "available",
        "source_url": "https://beta-consulting.no",
        "value": {
            "final_url": "https://beta-consulting.no",
            "title": "Beta Consulting AS",
            "main_text_excerpt": "Beta Consulting AS driver med rådgivning.",
            "social_links": [],
        },
    }
    gated = apply_website_identity_gate(profile, website_record)
    assert gated["assessment"]["publishable"] is False


def test_ssrf_protection_still_works():
    with pytest.raises(ValueError):
        assert_public_url("http://127.0.0.1:8000")
    with pytest.raises(ValueError):
        assert_public_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError):
        assert_public_url("http://localhost:5000")


def test_terminal_envelope_validation():
    profile = {
        "organisation_number": "123456789",
        "name": "Test AS",
        "evidence": {
            "registry": evidence("registry", "available", "official_registry", "https://brreg.no"),
            "website": evidence("website", "not_found", "search_discovery", "https://brave.com"),
        },
    }
    modules = ["registry", "website"]
    now = utc_now()
    env = terminal_envelope(profile, run_id="test-run", modules=modules, started_at=now, completed_at=now)
    assert env["state"] == "complete"
    validation = validate_envelopes([env], expected_count=1)
    assert validation["passed"] is True
