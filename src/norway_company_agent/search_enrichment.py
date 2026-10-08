from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .discovery import BLOCKED_DISCOVERY_HOSTS
from .identity import assess_social_identity
from .website import normalize_social_url

ATS_HOSTS = {
    "teamtailor.com": "Teamtailor",
    "reachmee.com": "ReachMee",
    "jobbnorge.no": "Jobbnorge",
    "webcruiter.com": "Webcruiter",
    "webcruiter.no": "Webcruiter",
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

NEWS_HOSTS = {
    "e24.no", "dn.no", "finansavisen.no", "nrk.no", "tu.no", "nettavisen.no",
    "kapital.no", "shifter.no", "digi.no", "kode24.no", "bygg.no",
}

NEWS_PATH_KEYWORDS = (
    "/nyheter", "/news", "/pressemelding", "/pressemeldinger", "/press",
    "/aktuelt", "/artikler", "/artikkel", "/media", "/presse",
)

NEWS_CONTENT_KEYWORDS = (
    "pressemelding", "press release", "kunngjør", "inngår avtale", "rammeavtale",
    "ny kontrakt", "lanserer", "nyhet", "aktuelt", "årsresultat",
)

GENERIC_NAME_TOKENS = {"as", "asa", "ans", "da", "enk", "sa", "nuf", "company", "norge", "norway", "gruppen", "group"}

CAREER_TERMS = (
    "career", "careers", "jobs", "job", "jobb", "jobbe", "stillinger",
    "stilling", "ledige stillinger", "ledige-stillinger", "hiring",
    "vacancies", "rekruttering", "work with us",
)

ACTIVE_HIRING_TERMS = (
    "ledige stillinger", "åpne stillinger", "open positions", "open roles",
    "we are hiring", "currently hiring", "join our team", "apply now",
    "vi søker", "søk jobb", "stillingsannonser", "søk stillingen",
)

MONTH_MAP = {
    "januar": "01", "january": "01", "jan": "01",
    "februar": "02", "february": "02", "feb": "02",
    "mars": "03", "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "mai": "05", "may": "05",
    "juni": "06", "june": "06", "jun": "06",
    "juli": "07", "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "oktober": "10", "october": "10", "okt": "10", "oct": "10",
    "november": "11", "nov": "11",
    "desember": "12", "december": "12", "des": "12", "dec": "12",
}

DATE_PATTERNS = (
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b"),
    re.compile(r"\b(\d{4}/\d{2}/\d{2})\b"),
)

TEXT_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\.?\s+([A-Za-zæøåÆØÅ]+)\s+(\d{4})\b"
)


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "å": "a", "æ": "ae", "Ø": "O", "Å": "A", "Æ": "AE"}))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.casefold())
    return [token for token in text.split() if len(token) > 1]


def _name_match(profile: dict[str, Any], result: dict[str, Any]) -> bool:
    name_tokens = [t for t in _tokens(profile.get("name")) if t not in GENERIC_NAME_TOKENS]
    if not name_tokens:
        return False
    haystack = " ".join([
        str(result.get("title") or ""),
        str(result.get("snippet") or ""),
    ])
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))

    # Reject if haystack mentions a conflicting 9-digit Norwegian organisation number
    found_orgs = re.findall(r"\b\d{9}\b", haystack)
    if found_orgs and all(cand != org for cand in found_orgs):
        return False

    evidence_tokens = set(_tokens(haystack))
    all_tokens_match = set(name_tokens).issubset(evidence_tokens)
    org_in_snippet = bool(org and org in re.sub(r"\D", "", haystack))
    return all_tokens_match or org_in_snippet


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
    # ISO date prefix YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$", raw):
        return raw[:10]

    for pattern in DATE_PATTERNS:
        match = pattern.search(raw)
        if match:
            candidate = match.group(1).replace("/", "-").replace(".", "-")
            parts = candidate.split("-")
            if len(parts) == 3:
                if len(parts[0]) == 2:
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
                return candidate

    # Textual month matching: "15. mai 2024" or "May 15, 2024"
    match_txt = TEXT_DATE_PATTERN.search(raw)
    if match_txt:
        day_str = match_txt.group(1).zfill(2)
        month_str = match_txt.group(2).lower()
        year_str = match_txt.group(3)
        month_num = MONTH_MAP.get(month_str)
        if month_num:
            return f"{year_str}-{month_num}-{day_str}"

    return None


def _is_social(result: dict[str, Any]) -> bool:
    host = (urllib.parse.urlparse(str(result.get("url") or "")).hostname or "").casefold().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_HOSTS)


def _is_ats(result: dict[str, Any]) -> tuple[str, bool]:
    parsed = urllib.parse.urlparse(str(result.get("url") or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold()
    for domain, platform in ATS_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            if domain == "finn.no" and not any(term in path for term in ("/jobb", "/stilling", "/stillinger")):
                continue
            return platform, True
    if any(term in path for term in ("/career", "/careers", "/jobs", "/job/", "/stilling", "/stillinger", "/jobb")):
        return "", True
    return "", False


def _is_news_candidate(result: dict[str, Any]) -> bool:
    url = str(result.get("url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold()

    if any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
        return False
    if _is_social(result):
        return False
    if _is_ats(result)[1]:
        return False

    result_kind = str(result.get("result_kind") or "").casefold()
    if result_kind == "news":
        return True

    if any(host == d or host.endswith("." + d) for d in NEWS_HOSTS):
        return True
    if any(k in path for k in NEWS_PATH_KEYWORDS):
        return True

    text = f"{result.get('title', '')} {result.get('snippet', '')}".casefold()
    if any(k in text for k in NEWS_CONTENT_KEYWORDS):
        return True

    return False


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

        # 1. Social profiles with identity gating
        if _is_social(result):
            normalized = normalize_social_url(url)
            if normalized and normalized["url"] not in seen_social:
                identity = assess_social_identity(profile, normalized)
                if identity.get("publishable"):
                    seen_social.add(normalized["url"])
                    confidence = identity.get("identity_score", 0.9)
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

        # 2. Dated news only (undated never becomes dated news)
        if _is_news_candidate(result):
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

        # 3. Hiring & ATS portals
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
