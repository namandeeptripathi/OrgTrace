from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .website import normalize_social_url

ATS_HOSTS = {
    "teamtailor.com": "Teamtailor",
    "reachmee.com": "ReachMee",
    "jobbnorge.no": "Jobbnorge",
    "webcruiter.com": "Webcruiter",
    "recman.no": "RecMan",
    "finn.no": "Finn",
    "bamboohr.com": "BambooHR",
}

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "x.com": "x",
    "twitter.com": "x",
}

GENERIC_NAME_TOKENS = {"as", "asa", "ans", "da", "enk", "sa", "nuf", "company", "norge", "norway", "gruppen", "group"}
CAREER_TERMS = (
    "career", "careers", "jobs", "job", "jobb", "jobbe", "stillinger",
    "stilling", "ledige stillinger", "ledige-stillinger", "hiring",
    "vacancies", "rekruttering", "work with us",
)
ACTIVE_HIRING_TERMS = (
    "ledige stillinger", "åpne stillinger", "open positions", "open roles",
    "we are hiring", "currently hiring", "join our team", "apply now",
    "vi søker", "søk jobb", "stillingsannonser",
)
DATE_PATTERNS = (
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b"),
    re.compile(r"\b(\d{4}/\d{2}/\d{2})\b"),
)


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "å": "a", "æ": "ae", "Ø": "O", "Å": "A", "Æ": "AE"}))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.casefold())
    return [token for token in text.split() if len(token) > 1]


def _name_match(profile: dict[str, Any], result: dict[str, Any]) -> bool:
    tokens = [t for t in _tokens(profile.get("name")) if t not in GENERIC_NAME_TOKENS]
    if not tokens:
        return False
    haystack = " ".join([
        str(result.get("title") or ""),
        str(result.get("snippet") or ""),
    ])
    evidence_tokens = set(_tokens(haystack))
    return set(tokens).issubset(evidence_tokens)


def _municipality_match(profile: dict[str, Any], result: dict[str, Any]) -> bool:
    municipality = set(_tokens(profile.get("municipality")))
    if not municipality:
        return False
    evidence_tokens = set(_tokens(f"{result.get('title', '')} {result.get('snippet', '')}"))
    return municipality.issubset(evidence_tokens)


def _parse_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:T.*)?$", raw):
        return raw[:10]
    for pattern in DATE_PATTERNS:
        match = pattern.search(raw)
        if match:
            candidate = match.group(1).replace("/", "-").replace(".", "-")
            parts = candidate.split("-")
            if len(parts) == 3 and len(parts[0]) == 2:
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            return candidate
    return None


def _is_social(result: dict[str, Any]) -> bool:
    host = (urllib.parse.urlparse(str(result.get("url") or "")).hostname or "").casefold().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_HOSTS)


def _is_ats(result: dict[str, Any]) -> tuple[str, bool]:
    parsed = urllib.parse.urlparse(str(result.get("url") or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    for domain, platform in ATS_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return platform, True
    path = parsed.path.casefold()
    if any(term in path for term in ("/career", "/careers", "/jobs", "/job/", "/stilling", "/jobb")):
        return "", True
    return "", False


def extract_search_enrichment(profile: dict[str, Any], results: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    """Extract only strongly attributable public social/news/hiring signals from transient search results."""
    social: list[dict[str, Any]] = []
    news: list[dict[str, Any]] = []
    hiring_candidates: list[dict[str, Any]] = []
    seen_social: set[str] = set()
    seen_news: set[str] = set()
    seen_hiring: set[str] = set()

    for result in results:
        url = str(result.get("url") or "").strip()
        if not url:
            continue
        title = str(result.get("title") or "").strip()
        snippet = str(result.get("snippet") or "").strip()
        if not _name_match(profile, result):
            continue

        if _is_social(result):
            normalized = normalize_social_url(url)
            if normalized and normalized["url"] not in seen_social:
                seen_social.add(normalized["url"])
                confidence = 0.92 if _municipality_match(profile, result) else 0.84
                social.append({
                    **normalized,
                    "source_url": url,
                    "source": "public_search",
                    "retrieved_at": retrieved_at,
                    "organisation_number": str(profile.get("organisation_number") or ""),
                    "company_name": str(profile.get("name") or ""),
                    "identity_match": True,
                    "evidence_excerpt": title or snippet[:300],
                    "confidence": confidence,
                })

        result_kind = str(result.get("result_kind") or "").casefold()
        if result_kind == "news":
            published_at = _parse_date(result.get("page_age") or result.get("published_at") or title or snippet)
            if published_at and url not in seen_news:
                seen_news.add(url)
                news.append({
                    "title": title or "Public company news",
                    "url": url,
                    "date": published_at,
                    "published_at": published_at,
                    "snippet": snippet[:500],
                    "source": str(result.get("source") or "public_search"),
                    "source_url": url,
                    "retrieved_at": retrieved_at,
                    "organisation_number": str(profile.get("organisation_number") or ""),
                    "company_name": str(profile.get("name") or ""),
                    "identity_match": True,
                    "evidence_excerpt": snippet[:500],
                    "confidence": 0.9 if _municipality_match(profile, result) else 0.82,
                })

        platform, ats = _is_ats(result)
        path_text = f"{title} {snippet} {url}".casefold()
        if ats or any(term in path_text for term in CAREER_TERMS):
            if url not in seen_hiring:
                seen_hiring.add(url)
                active = any(term in path_text for term in ACTIVE_HIRING_TERMS)
                hiring_candidates.append({
                    "url": url,
                    "title": title,
                    "platform": platform or None,
                    "hiring_active": True if active else None,
                    "source": "public_search",
                    "source_url": url,
                    "retrieved_at": retrieved_at,
                    "organisation_number": str(profile.get("organisation_number") or ""),
                    "company_name": str(profile.get("name") or ""),
                    "identity_match": True,
                    "evidence_excerpt": (snippet or title)[:500],
                    "confidence": 0.9 if active else 0.78,
                })

    return {
        "social_profiles": social[:10],
        "news": news[:10],
        "hiring": hiring_candidates[:10],
    }
