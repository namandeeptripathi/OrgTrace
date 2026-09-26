from __future__ import annotations

import json
import ipaddress
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
import extruct
import tldextract
import trafilatura

from .evidence import evidence

USER_AGENT = "builderr-signalpost-poc/0.1 (+https://builderr.ai)"
SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "tiktok.com": "tiktok",
}
PRIORITY_CATEGORIES = {
    "careers": (
        "karriere", "careers", "career", "jobb", "job", "jobs", "stillinger",
        "ledige-stillinger", "ledige stillinger", "work-with-us", "work with us",
        "hiring", "vacancies", "rekruttering", "bli-med-pa-laget", "bli-med",
        "jobbe-hos-oss", "jobbe hos oss", "bli-en-av-oss", "bli en av oss",
        "arbeide-hos-oss", "arbeide hos oss", "stilling",
    ),
    "news": (
        "aktuelt", "nyheter", "pressemeldinger", "pressemelding", "press",
        "news", "artikler", "blog", "presse", "media", "magasin", "siste-nytt",
        "siste nytt", "nyhetsarkiv", "medieomtale",
    ),
    "leadership": (
        "ledelse", "management", "team", "people", "styre", "ansatte", "nokkelpersoner",
    ),
    "about": (
        "om-oss", "om_oss", "om-selskapet", "om oss", "about", "about-us",
        "about_us", "selskapet", "hvem-er-vi", "hvem er vi",
    ),
    "contact": (
        "kontakt", "contact", "kontakt-oss", "kontakt oss", "lokasjoner",
        "locations", "avdelinger", "butikker", "finn-oss", "kontor",
    ),
}

PRIORITY_TERMS = tuple(
    term for terms in PRIORITY_CATEGORIES.values() for term in terms
)

KNOWN_ATS_DOMAINS = (
    "reachmee.com", "teamtailor.com", "jobbnorge.no", "webcruiter.no",
    "recman.no", "finn.no/jobb", "bamboohr.com", "bamboohr",
)

CAREER_ANCHOR_TERMS = (
    "karriere", "career", "careers", "jobb", "job", "jobs", "stilling",
    "stillinger", "ledige", "work", "hiring", "rekruttering", "søk", "apply",
    "bli med", "bli-en-av-oss", "jobbe-hos-oss", "arbeide", "ledig",
    "recruitment", "vacancy", "vacancies",
    "reachmee", "teamtailor", "jobbnorge", "webcruiter", "recman", "bamboohr",
)


def _clean_ats_platform(matched: str) -> str:
    if "reachmee" in matched:
        return "reachmee"
    if "teamtailor" in matched:
        return "teamtailor"
    if "jobbnorge" in matched:
        return "jobbnorge"
    if "webcruiter" in matched:
        return "webcruiter"
    if "recman" in matched:
        return "recman"
    if "finn.no" in matched:
        return "finn"
    if "bamboohr" in matched:
        return "bamboohr"
    return matched.replace(".com", "").replace(".no", "").replace("/jobb", "")


def extract_ats_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Detect outbound links to known recruitment/ATS platforms with career context."""
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = (parsed.hostname or "").lower()
        full_lower = url.lower()
        matched_platform = next(
            (ats for ats in KNOWN_ATS_DOMAINS if ats in host or (ats == "finn.no/jobb" and "finn.no/jobb" in full_lower)),
            None,
        )
        if not matched_platform:
            continue
        anchor_text = anchor.get_text(" ", strip=True)
        aria_label = str(anchor.get("aria-label") or "")
        title_attr = str(anchor.get("title") or "")
        haystack = f"{anchor_text} {aria_label} {title_attr} {parsed.path}".lower()
        if any(term in haystack for term in CAREER_ANCHOR_TERMS):
            if url not in seen:
                seen.add(url)
                links.append({
                    "url": url,
                    "anchor_text": anchor_text[:200],
                    "platform": _clean_ats_platform(matched_platform),
                    "source_url": base_url,
                })
    return links


_extract_ats_links = extract_ats_links


from .url_safety import assert_public_url


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


SAFE_OPENER = urllib.request.build_opener(SafeRedirectHandler())

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_robots_cache_lock = threading.Lock()


def clear_robots_cache() -> None:
    with _robots_cache_lock:
        _robots_cache.clear()


def normalize_homepage(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _registered_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    ext = tldextract.extract(parsed.hostname or "")
    return ext.top_domain_under_public_suffix


def _get_robots_parser(url: str, timeout: float) -> tuple[urllib.robotparser.RobotFileParser | None, bool]:
    """Retrieve or fetch robots.txt parser, returning (parser, was_network_fetched)."""
    assert_public_url(url)
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower()
    with _robots_cache_lock:
        if netloc in _robots_cache:
            return _robots_cache[netloc], False
    robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    network_fetched = True
    try:
        request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            parser.parse(response.read().decode("utf-8", errors="replace").splitlines())
    except Exception:
        parser = None
    with _robots_cache_lock:
        _robots_cache[netloc] = parser
    return parser, network_fetched


def _robots_allowed(url: str, timeout: float, parser: urllib.robotparser.RobotFileParser | None = None) -> bool:
    target_netloc = urllib.parse.urlparse(url).netloc.lower()
    p = parser
    if p is not None and getattr(p, "url", None):
        if urllib.parse.urlparse(p.url).netloc.lower() != target_netloc:
            p = None
    if p is None:
        p, _ = _get_robots_parser(url, timeout)
    if p is None:
        return True
    try:
        return p.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _social_links(base_url: str, soup: BeautifulSoup) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    candidates = [str(node.get("href") or "") for node in soup.select("a[href]")]
    candidates.extend(str(node.get("data-href") or "") for node in soup.select("[data-href]"))
    candidates.extend(str(node.get("src") or "") for node in soup.select("iframe[src]"))
    for candidate in candidates:
        url = urllib.parse.urljoin(base_url, candidate)
        parsed_candidate = urllib.parse.urlparse(url)
        if (parsed_candidate.hostname or "").casefold().removeprefix("www.") == "facebook.com" and parsed_candidate.path.startswith("/plugins/"):
            embedded = urllib.parse.parse_qs(parsed_candidate.query).get("href", [])
            if embedded:
                url = embedded[0]
        normalized = normalize_social_url(url)
        if not normalized:
            continue
        found[(normalized["platform"], normalized["url"])] = normalized
    return sorted(found.values(), key=lambda item: (item["platform"], item["url"]))


def structured_social_links(value: Any) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            same_as = node.get("sameAs")
            urls = same_as if isinstance(same_as, list) else [same_as]
            for raw in urls:
                if not isinstance(raw, str):
                    continue
                normalized = normalize_social_url(raw.strip())
                if normalized:
                    found[(normalized["platform"], normalized["url"])] = normalized
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(found.values(), key=lambda item: (item["platform"], item["url"]))


def normalize_social_url(url: str) -> dict[str, str] | None:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    platform = next((label for domain, label in SOCIAL_HOSTS.items() if host == domain or host.endswith("." + domain)), None)
    if not platform:
        return None
    parts = [part.strip() for part in parsed.path.split("/") if part.strip()]
    lowered = [part.casefold() for part in parts]
    rejected_first = {
        "facebook": {"sharer", "sharer.php", "share.php", "dialog", "policy.php", "privacy", "events", "groups", "plugins"},
        "instagram": {"p", "reel", "reels", "stories", "explore"},
        "x": {"intent", "share", "home", "search", "i"},
    }
    if not parts or lowered[0] in rejected_first.get(platform, set()):
        return None
    if platform == "facebook" and lowered[0] == "profile.php":
        return None
    if platform == "linkedin" and (lowered[0] != "company" or len(parts) < 2):
        return None
    if platform == "youtube" and lowered[0] not in {"channel", "user", "c"} and not parts[0].startswith("@"):
        return None
    if host == "youtu.be":
        return None
    if platform == "tiktok" and not parts[0].startswith("@"):
        return None
    if platform == "x" and len(parts) != 1:
        return None
    canonical_host = {
        "linkedin": "linkedin.com",
        "facebook": "facebook.com",
        "instagram": "instagram.com",
        "x": "x.com",
        "youtube": "youtube.com",
        "tiktok": "tiktok.com",
    }[platform]
    if platform == "linkedin":
        parts = parts[:2]
    elif platform == "youtube":
        parts = parts[:1] if parts[0].startswith("@") else parts[:2]
    return {"platform": platform, "url": f"https://{canonical_host}/{'/'.join(parts)}"}


def _priority_links(base_url: str, soup: BeautifulSoup, limit: int = 7) -> list[str]:
    base_reg = _registered_domain(base_url)
    if not base_reg:
        return []
    base_clean = base_url.rstrip("/").split("://", 1)[-1]
    candidates: dict[str, dict[str, Any]] = {}
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        cand_reg = _registered_domain(url)
        if not cand_reg or cand_reg != base_reg:
            continue
        lower_path = parsed.path.lower()
        if any(lower_path.endswith(ext) for ext in (".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js")):
            continue
        haystack = (parsed.netloc + " " + parsed.path + " " + anchor.get_text(" ", strip=True)).casefold()
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
        clean_comp = clean.rstrip("/").split("://", 1)[-1]
        if clean_comp == base_clean:
            continue

        best_cat = None
        best_rank = 999
        for cat, terms in PRIORITY_CATEGORIES.items():
            for rank, term in enumerate(terms):
                if term in haystack:
                    if rank < best_rank:
                        best_rank = rank
                        best_cat = cat
                    break
        if best_cat is None:
            host_lower = (parsed.hostname or "").lower()
            if host_lower.startswith(("karriere.", "jobb.")):
                best_cat = "careers"
                best_rank = 0
            elif host_lower.startswith(("news.", "nyheter.", "presse.")):
                best_cat = "news"
                best_rank = 0
            else:
                continue

        if clean not in candidates or best_rank < candidates[clean]["rank"]:
            candidates[clean] = {"url": clean, "category": best_cat, "rank": best_rank}

    if not candidates:
        return []

    # Diversity selection across categories: pick best from each category in priority order
    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in candidates.values():
        by_category.setdefault(item["category"], []).append(item)
    for cat in by_category:
        by_category[cat].sort(key=lambda x: (x["rank"], len(x["url"])))

    selected: list[str] = []
    category_order = ("careers", "news", "leadership", "about", "contact")
    for cat in category_order:
        if cat in by_category and by_category[cat]:
            selected.append(by_category[cat].pop(0)["url"])
            if len(selected) >= limit:
                break

    # If still below limit, fill with remaining candidates sorted by overall rank
    if len(selected) < limit:
        remaining = [item for cat_list in by_category.values() for item in cat_list if item["url"] not in selected]
        remaining.sort(key=lambda x: (x["rank"], len(x["url"])))
        for item in remaining:
            selected.append(item["url"])
            if len(selected) >= limit:
                break

    return selected[:limit]


def _fetch_secondary_page(
    url: str,
    *,
    homepage_domain: str,
    timeout: float,
    max_bytes: int,
    parser: urllib.robotparser.RobotFileParser | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]], int, int, int, str | None]:
    try:
        assert_public_url(url)
    except Exception as exc:
        return None, [], 0, 0, 0, f"Blocked: {exc}"
    if not _robots_allowed(url, timeout, parser=parser):
        return None, [], 0, 0, 0, "robots.txt disallows page"
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            elapsed = int((time.monotonic() - started) * 1000)
            final_url = response.geturl()
            assert_public_url(final_url)
            if len(raw) > max_bytes or "html" not in response.headers.get("content-type", "").lower():
                return None, [], 1, len(raw), elapsed, "unsupported or oversized page"
            if _registered_domain(final_url) != homepage_domain:
                return None, [], 1, len(raw), elapsed, "redirected outside registered domain"
        page_html = raw.decode("utf-8", errors="replace")
        page_soup = BeautifulSoup(page_html, "lxml")
        page_text = trafilatura.extract(page_html, url=final_url, include_links=False, include_tables=False, favor_precision=True) or ""
        outbound_ats = extract_ats_links(page_soup, final_url)
        page = {
            "url": final_url,
            "title": page_soup.title.get_text(" ", strip=True)[:500] if page_soup.title else "",
            "main_text_excerpt": page_text[:5000],
            "content_sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "outbound_career_links": outbound_ats,
        }
        return page, _social_links(final_url, page_soup), 1, len(raw), elapsed, None
    except Exception as exc:
        return None, [], 1, 0, int((time.monotonic() - started) * 1000), f"{type(exc).__name__}: {str(exc)[:120]}"


def _jsonld_organisations(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            kind = value.get("@type")
            kinds = set(kind if isinstance(kind, list) else [kind])
            if kinds & {"Organization", "Corporation", "LocalBusiness", "Store", "Restaurant"}:
                values.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(metadata.get("json-ld", []))
    return values[:20]


def _extraction_state(text: str, soup: BeautifulSoup) -> str:
    return "js_fallback_candidate" if len(text.strip()) < 100 and len(soup.select("script[src]")) >= 2 else "static_complete"


def fetch_website(url: str | None, *, timeout: float = 15.0, max_bytes: int = 2_000_000, guard: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    supplied_url = str(url or "").strip()
    supplied_scheme = bool(re.match(r"^https?://", supplied_url, re.I))
    normalized = normalize_homepage(url)
    if not normalized:
        return evidence("website", "not_found", "registry_linked_company_website", "https://data.brreg.no/enhetsregisteret/api/enheter", note="No valid registry website URL"), {"requests": 0, "bytes": 0, "latencies_ms": []}

    # 1. Budget Guard Check
    if guard is not None:
        allowed, reason = guard.acquire_request()
        if not allowed:
            return evidence("website", "not_attempted", "registry_linked_company_website", normalized, note=f"Execution budget exhausted: {reason}"), {"requests": 0, "bytes": 0, "latencies_ms": []}

    try:
        assert_public_url(normalized)
    except ValueError as exc:
        return evidence("website", "blocked", "registry_linked_company_website", normalized, note=str(exc)), {"requests": 0, "bytes": 0, "latencies_ms": []}

    parser, robots_network = _get_robots_parser(normalized, timeout)
    if parser is not None and not parser.can_fetch(USER_AGENT, normalized):
        return evidence("website", "blocked", "registry_linked_company_website", normalized, note="robots.txt disallows this user agent"), {"requests": 1 if robots_network else 0, "bytes": 0, "latencies_ms": []}

    started = time.monotonic()
    request = urllib.request.Request(normalized, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(max_bytes + 1)
            elapsed = int((time.monotonic() - started) * 1000)
            if len(raw) > max_bytes:
                return evidence("website", "blocked", "registry_linked_company_website", normalized, note="Homepage exceeds byte limit"), {"requests": 2 if robots_network else 1, "bytes": len(raw), "latencies_ms": [elapsed]}
            if "html" not in content_type.lower():
                return evidence("website", "unavailable", "registry_linked_company_website", normalized, note=f"Unsupported content type: {content_type}"), {"requests": 2 if robots_network else 1, "bytes": len(raw), "latencies_ms": [elapsed]}
            final_url = response.geturl()
            assert_public_url(final_url)
        html = raw.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        structured = extruct.extract(html, base_url=final_url, syntaxes=["json-ld", "microdata", "opengraph"])
        text = trafilatura.extract(html, url=final_url, include_links=False, include_tables=False, favor_precision=True) or ""
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description_tag = soup.select_one('meta[name="description"], meta[property="og:description"]')
        description = str(description_tag.get("content") or "").strip() if description_tag else ""
        homepage_ats = extract_ats_links(soup, final_url)
        value = {
            "requested_url": normalized,
            "final_url": final_url,
            "registered_domain": _registered_domain(final_url),
            "title": title[:500],
            "description": description[:2000],
            "main_text_excerpt": text[:5000],
            "social_links": _social_links(final_url, soup),
            "structured_organisations": _jsonld_organisations(structured),
            "content_sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "extraction_state": _extraction_state(text, soup),
            "outbound_career_links": homepage_ats,
        }
        pages = [{"url": final_url, "title": title[:500], "main_text_excerpt": text[:5000], "content_sha256": value["content_sha256"], "outbound_career_links": homepage_ats}]
        social = value["social_links"]
        all_ats = list(homepage_ats)
        crawl_errors = []
        requests = 2 if robots_network else 1
        bytes_received = len(raw)
        page_latencies = [elapsed]
        homepage_domain = value["registered_domain"]

        # Only crawl secondary pages if NOT in reduced-enrichment mode
        if not (guard is not None and guard.is_reduced_mode()):
            for page_url in _priority_links(final_url, soup, limit=7):
                if guard is not None:
                    allowed, _ = guard.acquire_request()
                    if not allowed:
                        break
                page, page_social, page_requests, page_bytes, page_elapsed, page_error = _fetch_secondary_page(
                    page_url,
                    homepage_domain=homepage_domain,
                    timeout=timeout,
                    max_bytes=min(max_bytes, 1_000_000),
                    parser=parser,
                )
                requests += page_requests
                bytes_received += page_bytes
                if page_elapsed:
                    page_latencies.append(page_elapsed)
                if page:
                    pages.append(page)
                    social.extend(page_social)
                    if "outbound_career_links" in page:
                        all_ats.extend(page["outbound_career_links"])
                elif page_error:
                    crawl_errors.append({"url": page_url, "error": page_error})

        value["pages"] = pages
        value["social_links"] = list({(item["platform"], item["url"]): item for item in social}.values())
        deduped_ats: dict[str, dict[str, Any]] = {}
        for item in all_ats:
            if item["url"] not in deduped_ats:
                deduped_ats[item["url"]] = item
        value["outbound_career_links"] = list(deduped_ats.values())
        value["crawl_errors"] = crawl_errors
        if guard is not None:
            guard.record_request_result(domain=homepage_domain, status_code=200)
        return evidence("website", "available", "registry_linked_company_website", final_url, value=value, note="Company-controlled claim layer; not an official registry fact", content_sha256=value["content_sha256"]), {"requests": requests, "bytes": bytes_received, "latencies_ms": page_latencies}
    except urllib.error.HTTPError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        status = "not_found" if exc.code in {404, 410} else "rate_limited" if exc.code == 429 else "unavailable"
        if guard is not None:
            guard.record_request_result(domain=_registered_domain(normalized) or "unknown", status_code=exc.code)
        return evidence("website", status, "registry_linked_company_website", normalized, note=f"HTTP {exc.code}"), {"requests": 2, "bytes": 0, "latencies_ms": [elapsed]}
    except urllib.error.URLError as exc:
        reason_str = str(getattr(exc, "reason", ""))
        is_timeout = "timeout" in reason_str.lower() or "timed out" in reason_str.lower()
        if not supplied_scheme and normalized.startswith("https://") and not is_timeout:
            first_elapsed = int((time.monotonic() - started) * 1000)
            record, metrics = fetch_website("http://" + supplied_url, timeout=timeout, max_bytes=max_bytes, guard=guard)
            metrics["requests"] += 2
            metrics["latencies_ms"].insert(0, first_elapsed)
            return record, metrics
        elapsed = int((time.monotonic() - started) * 1000)
        status = "timeout" if is_timeout else "unavailable"
        if guard is not None:
            guard.record_request_result(domain=_registered_domain(normalized) or "unknown", status_code=0)
        return evidence("website", status, "registry_linked_company_website", normalized, note=f"URLError: {reason_str[:180]}"), {"requests": 2, "bytes": 0, "latencies_ms": [elapsed]}
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        is_timeout = "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower()
        status = "timeout" if is_timeout else "unavailable"
        if guard is not None:
            guard.record_request_result(domain=_registered_domain(normalized) or "unknown", status_code=0)
        return evidence("website", status, "registry_linked_company_website", normalized, note=f"{type(exc).__name__}: {str(exc)[:180]}"), {"requests": 2, "bytes": 0, "latencies_ms": [elapsed]}
