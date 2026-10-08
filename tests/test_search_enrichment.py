from norway_company_agent.discovery import build_company_search_queries, score_search_candidate
from norway_company_agent.search_enrichment import extract_search_enrichment
from norway_company_agent.website import normalize_social_url


def test_website_discovery_query_variants_and_candidate():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    queries = build_company_search_queries(profile)
    assert len(queries) >= 2
    result = {
        "url": "https://example.no/",
        "title": "Example Consulting AS",
        "snippet": "Example Consulting AS 999888777 Oslo",
        "rank": 1,
    }
    scored = score_search_candidate(profile, result)
    assert scored["publishable_candidate"]


def test_social_normalization_rejects_personal_and_posts():
    assert normalize_social_url("https://www.linkedin.com/company/example-consulting/")["platform"] == "linkedin"
    assert normalize_social_url("https://www.linkedin.com/in/someone/") is None
    assert normalize_social_url("https://www.instagram.com/example/reel/123") is None


def test_search_enrichment_preserves_only_dated_news_and_valid_social():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    results = [
        {
            "url": "https://www.linkedin.com/company/example-consulting/",
            "title": "Example Consulting AS",
            "snippet": "Example Consulting AS Oslo",
        },
        {
            "url": "https://news.example.no/story",
            "title": "Example Consulting AS signs contract 2026-09-01",
            "snippet": "Example Consulting AS Oslo",
            "result_kind": "news",
        },
        {
            "url": "https://news.example.no/undated",
            "title": "Example Consulting AS announcement",
            "snippet": "Example Consulting AS Oslo",
            "result_kind": "news",
        },
    ]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert len(found["social_profiles"]) == 1
    assert len(found["news"]) == 1
    assert found["news"][0]["date"] == "2026-09-01"


def test_search_enrichment_hiring_requires_explicit_opening_signal():
    profile = {"name": "Example Consulting AS", "organisation_number": "999888777", "municipality": "Oslo"}
    results = [{
        "url": "https://example.teamtailor.com/jobs",
        "title": "Example Consulting AS - Jobs",
        "snippet": "Open positions in Oslo",
    }]
    found = extract_search_enrichment(profile, results, retrieved_at="2026-10-08T00:00:00Z")
    assert found["hiring"][0]["platform"] == "Teamtailor"
    assert found["hiring"][0]["hiring_active"] is True
