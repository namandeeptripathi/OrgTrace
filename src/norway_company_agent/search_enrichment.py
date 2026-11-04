from __future__ import annotations

from datetime import date, datetime, timezone
import re
import urllib.parse
from typing import Any

from .discovery import BLOCKED_DISCOVERY_HOSTS
from .identity import assess_social_identity
from .identity_engine import canonicalize_org_number, is_valid_org_mod11
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


def _parse_date(
    value: Any,
    *,
    retrieved_at: str | None = None,
    text_context: str | None = None,
) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    # Reject if explicitly labeled as modified / updated / retrieval date in text context
    if text_context:
        ctx_lower = text_context.casefold()
        for marker in ("sist oppdatert", "oppdatert:", "sist endret", "updated:", "last modified", "modified:", "hentet:", "endret dato:", "feed", "rss", "retrieved:", "retrieval", "cached:", "synced:"):
            if marker in ctx_lower and raw.casefold() in ctx_lower:
                idx = ctx_lower.find(marker)
                if idx != -1 and ctx_lower.find(raw.casefold(), idx) != -1:
                    return None

    cand_str: str | None = None
    # ISO date prefix YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$", raw):
        cand_str = raw[:10]
    else:
        for pattern in DATE_PATTERNS:
            match = pattern.search(raw)
            if match:
                candidate = match.group(1).replace("/", "-").replace(".", "-")
                parts = candidate.split("-")
                if len(parts) == 3:
                    if len(parts[0]) == 2:
                        cand_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    else:
                        cand_str = candidate
                    break

        if not cand_str:
            # Textual month matching: "15. mai 2024" or "May 15, 2024"
            match_txt = TEXT_DATE_PATTERN.search(raw)
            if match_txt:
                day_str = match_txt.group(1).zfill(2)
                month_str = match_txt.group(2).lower()
                year_str = match_txt.group(3)
                month_num = MONTH_MAP.get(month_str)
                if month_num:
                    cand_str = f"{year_str}-{month_num}-{day_str}"

    if not cand_str:
        return None

    # Validate date validity, range, and future rejection
    try:
        parts = [int(p) for p in cand_str.split("-")]
        if len(parts) != 3:
            return None
        cand_date = date(parts[0], parts[1], parts[2])
    except (ValueError, TypeError):
        return None

    today = datetime.now(timezone.utc).date()
    if cand_date > today:
        # Future date rejected!
        return None
    if cand_date.year < 2000:
        return None

    # Reject retrieval timestamp date unless article text contains explicit publication marker
    if retrieved_at and cand_str == retrieved_at[:10]:
        has_pub_marker = False
        if text_context:
            ctx_lower = text_context.casefold()
            has_pub_marker = any(m in ctx_lower for m in ("publisert", "published", "pressemelding", "press release"))
        if not has_pub_marker:
            return None

    return cand_str


def _is_social(result: dict[str, Any]) -> bool:
    host = (urllib.parse.urlparse(str(result.get("url") or "")).hostname or "").casefold().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_HOSTS)


def _ats_rejection_reason(result: dict[str, Any]) -> str:
    """Return specific non-fabricated rejection reason if candidate is on an ATS host but is invalid."""
    parsed = urllib.parse.urlparse(str(result.get("url") or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold().rstrip("/")
    query = parsed.query.casefold()

    for domain in ATS_HOSTS:
        if host == domain or host == "www." + domain:
            if domain == "finn.no":
                path_has_id = bool(re.search(r"/jobb/(?:stilling|heltid|deltid|leder|sommerjobb)/\d+", path) or re.search(r"/jobb/bedrift/[a-z0-9_-]+/\d+", path))
                query_has_id = bool(re.search(r"/jobb/(?:stilling|heltid|deltid|leder|sommerjobb)", path) and re.search(r"(?:id|finnkode)=\d+", query))
                if not (path_has_id or query_has_id):
                    if re.search(r"/(?:sok|search)\b", path) or re.search(r"(?:q|sok|search)=", query):
                        return "This is a generic ATS search page, not the company's careers page or individual vacancy"
                    return "This is the ATS vendor homepage, not the company's careers page"
            elif domain == "jobbnorge.no":
                path_has_id = bool(re.search(r"/(?:ledige-stillinger/)?stilling/\d+", path))
                query_has_id = bool(re.search(r"/(?:ledige-stillinger/)?stilling", path) and re.search(r"(?:id|jobid)=\d+", query))
                if not (path_has_id or query_has_id):
                    if re.search(r"/(?:sok|search)\b", path) or re.search(r"(?:q|sok|search)=", query):
                        return "This is a generic ATS search page, not the company's careers page or individual vacancy"
                    return "This is the ATS vendor homepage, not the company's careers page"
            else:
                if re.search(r"/(?:sok|search|explore)\b", path) or re.search(r"(?:q|sok|search)=", query):
                    return "This is a generic ATS search page, not the company's careers page or individual vacancy"
                if path in {"", "/", "/en", "/nb", "/no", "/about", "/about-us", "/pricing", "/login", "/contact", "/demo", "/privacy", "/terms", "/jobs", "/careers", "/stillinger"}:
                    return "This is the ATS vendor homepage, not the company's careers page"
                if not re.search(r"/(?:companies|jobs|stilling|positions)/[a-z0-9_-]+", path):
                    return "This is the ATS vendor homepage, not the company's careers page"
        elif host.endswith("." + domain):
            subdomain = host.removesuffix("." + domain)
            if subdomain in {"www", "app", "api", "login", "admin", "help", "support", "marketing", "blog", "status", "mail", "cdn", "demo"}:
                return "This is the ATS vendor homepage, not the company's careers page"
            if re.search(r"/(?:sok|search)\b", path) or re.search(r"(?:q|sok|search)=", query):
                return "This is a generic ATS search page, not the company's careers page or individual vacancy"

    if re.search(r"/(?:career|careers|jobs|jobb|stilling|stillinger)/(?:search|sok)\b", path) or (
        any(k in path for k in ("/jobs", "/jobb", "/stilling", "/stillinger", "/careers")) and re.search(r"(?:q|search|sok|keyword)=", query)
    ):
        return "This is a generic ATS search page, not the company's careers page or individual vacancy"

    return ""


def _is_ats(result: dict[str, Any]) -> tuple[str, bool]:
    rej = _ats_rejection_reason(result)
    if rej:
        return "", False

    parsed = urllib.parse.urlparse(str(result.get("url") or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold().rstrip("/")

    # 1. ATS vendor domains: reject vendor homepages and generic roots
    for domain, platform in ATS_HOSTS.items():
        if host == domain or host == "www." + domain:
            query = parsed.query.casefold()
            if domain == "finn.no":
                path_has_id = bool(re.search(r"/jobb/(?:stilling|heltid|deltid|leder|sommerjobb)/\d+", path) or re.search(r"/jobb/bedrift/[a-z0-9_-]+/\d+", path))
                query_has_id = bool(re.search(r"/jobb/(?:stilling|heltid|deltid|leder|sommerjobb)", path) and re.search(r"(?:id|finnkode)=\d+", query))
                if path_has_id or query_has_id:
                    return platform, True
                return "", False
            elif domain == "jobbnorge.no":
                path_has_id = bool(re.search(r"/(?:ledige-stillinger/)?stilling/\d+", path))
                query_has_id = bool(re.search(r"/(?:ledige-stillinger/)?stilling", path) and re.search(r"(?:id|jobid)=\d+", query))
                if path_has_id or query_has_id:
                    return platform, True
                return "", False
            else:
                if re.search(r"/(?:companies|jobs|stilling|positions)/[a-z0-9_-]+", path):
                    return platform, True
                return "", False
        elif host.endswith("." + domain):
            subdomain = host.removesuffix("." + domain)
            if subdomain in {"www", "app", "api", "login", "admin", "help", "support", "marketing", "blog", "status", "mail", "cdn", "demo"}:
                return "", False
            return platform, True

    # 2. Company website internal career paths
    if any(term in path for term in ("/career", "/careers", "/jobs", "/job/", "/stilling", "/stillinger", "/jobb", "/karriere")):
        return "", True

    return "", False


def _is_news_candidate(result: dict[str, Any]) -> bool:
    url = str(result.get("url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold().rstrip("/")

    if any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
        return False
    if _is_social(result):
        return False
    if _is_ats(result)[1]:
        return False

    # 1. Real article path check: reject generic section roots / index hubs
    if path in {
        "", "/", "/nyheter", "/news", "/pressemelding", "/pressemeldinger", "/press",
        "/aktuelt", "/artikler", "/artikkel", "/media", "/presse", "/siste-nytt",
        "/nyhetsarkiv", "/blog", "/blogg", "/feed", "/rss",
    }:
        return False

    # 2. Reject category, tag, archive, topic, and taxonomy pages
    if re.search(r"^/(?:kategori|category|categories|tags?|emne|seksjon|tema|arkiv|archive)\b", path) or path.endswith("/kategori") or path.endswith("/category"):
        return False

    # 3. Reject product, service, about, contact, and navigation pages
    if re.search(r"^/(?:produkter|products?|tjenester|services?|om-oss|about|about-us|kontakt|contact|priser|pricing|hjem|home)\b", path):
        return False

    # 4. Real article title check: reject generic section / navigation titles
    title = str(result.get("title") or "").strip().casefold()
    generic_titles = {
        "nyheter", "news", "aktuelt", "presse", "press", "pressemeldinger", "siste nytt",
        "nyhetsarkiv", "artikler", "blogg", "media", "forside", "hjem", "home",
        "produkter", "products", "tjenester", "services", "om oss", "about us", "kontakt", "contact",
    }
    if title in generic_titles or title.endswith(" - nyheter") or title.startswith("nyheter - ") or title.endswith(" - news") or title.startswith("news - "):
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
    rejected_news: list[dict[str, Any]] = []
    rejected_hiring: list[dict[str, Any]] = []
    seen_social: set[str] = set()
    seen_news: set[str] = set()
    seen_hiring: set[str] = set()

    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    parent_org = canonicalize_org_number(profile.get("overordnetEnhet") or profile.get("parent_organisation"))

    for result in results:
        url = str(result.get("url") or "").strip()
        if not url:
            continue
        parsed_url = urllib.parse.urlparse(url)
        host = (parsed_url.hostname or "").casefold().removeprefix("www.")
        path = parsed_url.path.casefold().rstrip("/")
        title = str(result.get("title") or "").strip()
        snippet = str(result.get("snippet") or "").strip()
        haystack = f"{title} {snippet}"
        found_orgs = [o for o in re.findall(r"\b\d{9}\b", haystack) if is_valid_org_mod11(o)]

        # 1. Social profiles with identity gating
        if _is_social(result):
            if not _name_match(profile, result):
                continue
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
                        "organisation_number": org,
                        "company_name": str(profile.get("name") or ""),
                        "identity_match": True,
                        "evidence_excerpt": title or snippet[:300],
                        "confidence": confidence,
                        "verdict": "confirmed",
                        "verdict_reason": "Social profile matches company legal identity and operations",
                    })

        # 2. Dated news only (real article, exact company attribution, genuine publication date)
        # Check if URL was considered for news (e.g. news host, path keyword, news result, or news/update context) but rejected as category/nav
        is_news_source = (
            any(host == d or host.endswith("." + d) for d in NEWS_HOSTS)
            or any(k in path for k in NEWS_PATH_KEYWORDS)
            or str(result.get("result_kind") or "").casefold() == "news"
            or any(k in haystack.casefold() for k in ("nyhet", "news", "presse", "pressemelding", "sist oppdatert", "oppdatert", "publisert"))
        )
        if is_news_source and not _is_news_candidate(result) and not _is_social(result) and not _is_ats(result)[1]:
            rejected_news.append({
                "url": url,
                "title": title,
                "reason": "Candidate is a navigation, category, or product page, not a dated article",
            })
        elif _is_news_candidate(result):
            if parent_org and parent_org in found_orgs and org not in found_orgs:
                rejected_news.append({
                    "url": url,
                    "title": title,
                    "reason": f"News candidate cites parent organisation number {parent_org}, not subsidiary {org}",
                })
                continue

            conflicting_orgs = [o for o in found_orgs if o != org and o != parent_org]
            if conflicting_orgs:
                rejected_news.append({
                    "url": url,
                    "title": title,
                    "reason": f"News candidate cites conflicting organisation number {conflicting_orgs[0]}",
                })
                continue

            if not _name_match(profile, result):
                rejected_news.append({
                    "url": url,
                    "title": title,
                    "reason": "Article does not mention the requested company",
                })
                continue

            published_at = _parse_date(
                result.get("published_at") or result.get("page_age") or title or snippet,
                retrieved_at=retrieved_at,
                text_context=haystack,
            )
            if published_at:
                if url not in seen_news:
                    seen_news.add(url)
                    publisher = host
                    news.append({
                        "title": title or "Public company news",
                        "url": url,
                        "date": published_at,
                        "published_at": published_at,
                        "publisher": publisher,
                        "snippet": snippet[:500],
                        "source": str(result.get("source") or "public_search"),
                        "source_url": url,
                        "retrieved_at": retrieved_at,
                        "organisation_number": org,
                        "company_name": str(profile.get("name") or ""),
                        "identity_match": True,
                        "evidence_excerpt": snippet[:500],
                        "confidence": 0.9 if _municipality_match(profile, result) else 0.82,
                        "verdict": "confirmed",
                        "verdict_reason": f"Dated article on {publisher} explicitly identifies the requested company with verified publication date {published_at}",
                    })
            else:
                rejected_news.append({
                    "url": url,
                    "title": title,
                    "reason": "News article lacks verifiable genuine publication date (undated or invalid date)",
                })

        # 3. Hiring & ATS portals (exact employer, company-specific listing, no vendor homepage or parent vacancies)
        ats_rej = _ats_rejection_reason(result)
        if ats_rej:
            rejected_hiring.append({
                "url": url,
                "title": title,
                "reason": ats_rej,
            })
            continue

        platform, ats = _is_ats(result)
        path_text = f"{title} {snippet} {url}".casefold()
        if ats or any(term in path_text for term in CAREER_TERMS):
            if parent_org and parent_org in found_orgs and org not in found_orgs:
                rejected_hiring.append({
                    "url": url,
                    "title": title,
                    "reason": f"Vacancy belongs to the parent company ({parent_org}), not the requested entity",
                })
                continue

            conflicting_orgs = [o for o in found_orgs if o != org and o != parent_org]
            if conflicting_orgs:
                rejected_hiring.append({
                    "url": url,
                    "title": title,
                    "reason": f"Vacancy belongs to conflicting company {conflicting_orgs[0]}, not the requested entity",
                })
                continue

            if not _name_match(profile, result):
                rejected_hiring.append({
                    "url": url,
                    "title": title,
                    "reason": "Listing does not match the requested company identity",
                })
                continue

            if url not in seen_hiring:
                seen_hiring.add(url)
                active = any(term in path_text for term in ACTIVE_HIRING_TERMS)
                publisher = platform or host
                hiring_candidates.append({
                    "url": url,
                    "title": title,
                    "platform": platform or None,
                    "publisher": publisher,
                    "hiring_active": True if active else None,
                    "source": "public_search",
                    "source_url": url,
                    "retrieved_at": retrieved_at,
                    "organisation_number": org,
                    "company_name": str(profile.get("name") or ""),
                    "identity_match": True,
                    "evidence_excerpt": (snippet or title)[:500],
                    "confidence": 0.9 if active else 0.78,
                    "verdict": "confirmed",
                    "verdict_reason": "Individual active vacancy or careers page verified for the requested company",
                })

    return {
        "social_profiles": social[:10],
        "news": news[:10],
        "hiring": hiring_candidates[:10],
        "rejected_news": rejected_news,
        "rejected_hiring": rejected_hiring,
    }
