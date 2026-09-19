from __future__ import annotations

import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable

from bs4 import BeautifulSoup
import trafilatura

from .discovery import BLOCKED_DISCOVERY_HOSTS, build_company_search_query
from .evidence import evidence
from .identity_engine import (
    canonicalize_org_number,
    extract_legal_form,
    match_domain_entity,
    match_legal_names,
    normalize_legal_name,
)
from .website import (
    SAFE_OPENER,
    USER_AGENT,
    _priority_links,
    _registered_domain,
    assert_public_url,
    normalize_homepage,
)

# High-signal path keywords for Norwegian and English company pages
HIGH_SIGNAL_KEYWORDS = (
    "om-oss", "om_oss", "about", "about-us", "om", "kontakt", "contact", "kontakt-oss",
    "contact-us", "ledelse", "management", "team", "selskapet", "company", "virksomhet",
    "juridisk", "legal", "impressum", "foretaksfakta", "organisasjon",
)

PARKED_PAGE_MARKERS = (
    "domain is for sale", "domain for sale", "hugedomains", "parked at", "miss hosting",
    "her flytter snart en ny gjest", "has been informing visitors",
    "find the best information and most relevant links on all topics related to",
    "buy this domain", "domainet er parkert", "parkert hos",
)


# ============================================================================
# 1. REQUEST BUDGET ACCOUNTING
# ============================================================================

@dataclass
class RequestBudget:
    """Explicit request budget tracking across all discovery categories."""
    max_total_requests: int = 15
    max_search_requests: int = 2
    max_page_requests: int = 8
    max_sitemap_requests: int = 2
    max_robots_requests: int = 3

    total_requests: int = 0
    search_requests: int = 0
    robots_requests: int = 0
    sitemap_requests: int = 0
    page_requests: int = 0
    redirects: int = 0
    failed_requests: int = 0

    def can_request(self, category: str = "page") -> bool:
        if self.total_requests >= self.max_total_requests:
            return False
        if category == "search" and self.search_requests >= self.max_search_requests:
            return False
        if category == "robots" and self.robots_requests >= self.max_robots_requests:
            return False
        if category == "sitemap" and self.sitemap_requests >= self.max_sitemap_requests:
            return False
        if category == "page" and self.page_requests >= self.max_page_requests:
            return False
        return True

    def record_request(self, category: str = "page", *, success: bool = True, redirects_count: int = 0) -> None:
        self.total_requests += 1
        if category == "search":
            self.search_requests += 1
        elif category == "robots":
            self.robots_requests += 1
        elif category == "sitemap":
            self.sitemap_requests += 1
        elif category == "page":
            self.page_requests += 1
        self.redirects += redirects_count
        if not success:
            self.failed_requests += 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# 2. SSRF-SAFE HTTP FETCHING & ROBOTS.TXT
# ============================================================================

@dataclass
class FetchResult:
    url: str
    final_url: str | None
    status_code: int
    content: bytes
    html: str
    title: str
    meta_description: str
    text_excerpt: str
    content_sha256: str
    error: str | None
    redirects_count: int
    elapsed_ms: int


class SafeHttpFetcher:
    """SSRF-protected, budget-aware HTTP fetcher with robots.txt caching."""

    def __init__(self, timeout: float = 10.0, max_bytes: int = 2_000_000):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._sitemaps_cache: dict[str, list[str]] = {}

    def is_robots_allowed(self, url: str, budget: RequestBudget) -> bool:
        """Check if robots.txt allows fetching url, caching parser per host."""
        try:
            assert_public_url(url)
        except ValueError:
            return False

        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        if host in self._robots_cache:
            return self._robots_cache[host].can_fetch(USER_AGENT, url)

        robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)

        if not budget.can_request("robots"):
            # Budget exhausted for robots: fail safe, assume allowed if not cached
            self._robots_cache[host] = parser
            return True

        started = time.monotonic()
        try:
            request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
            with SAFE_OPENER.open(request, timeout=self.timeout) as resp:
                lines = resp.read(256_000).decode("utf-8", errors="replace").splitlines()
                parser.parse(lines)
                # Also extract any Sitemap: directives
                sitemaps = [
                    line.split(":", 1)[1].strip()
                    for line in lines
                    if line.strip().lower().startswith("sitemap:") and ":" in line
                ]
                self._sitemaps_cache[host] = sitemaps
            budget.record_request("robots", success=True)
        except Exception:
            # Missing or unreachable robots.txt is not an outright ban
            budget.record_request("robots", success=False)

        self._robots_cache[host] = parser
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def get_robots_sitemaps(self, url: str) -> list[str]:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        return self._sitemaps_cache.get(host, [])

    def fetch_page(
        self,
        url: str,
        budget: RequestBudget,
        *,
        category: str = "page",
        respect_robots: bool = True,
    ) -> FetchResult:
        """Fetch a page with SSRF protection, redirect assertions, and budget accounting."""
        if not budget.can_request(category):
            return FetchResult(
                url=url, final_url=None, status_code=0, content=b"", html="", title="",
                meta_description="", text_excerpt="", content_sha256="",
                error="Request budget exhausted", redirects_count=0, elapsed_ms=0,
            )

        try:
            assert_public_url(url)
        except ValueError as exc:
            return FetchResult(
                url=url, final_url=None, status_code=0, content=b"", html="", title="",
                meta_description="", text_excerpt="", content_sha256="",
                error=f"SSRF blocked: {exc}", redirects_count=0, elapsed_ms=0,
            )

        if respect_robots and not self.is_robots_allowed(url, budget):
            return FetchResult(
                url=url, final_url=None, status_code=403, content=b"", html="", title="",
                meta_description="", text_excerpt="", content_sha256="",
                error="Blocked by robots.txt", redirects_count=0, elapsed_ms=0,
            )

        started = time.monotonic()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        )
        try:
            with SAFE_OPENER.open(request, timeout=self.timeout) as resp:
                raw = resp.read(self.max_bytes + 1)
                final_url = resp.geturl()
                assert_public_url(final_url)
                elapsed = int((time.monotonic() - started) * 1000)
                redirects = 1 if final_url.rstrip("/") != url.rstrip("/") else 0

                if len(raw) > self.max_bytes:
                    budget.record_request(category, success=False, redirects_count=redirects)
                    return FetchResult(
                        url=url, final_url=final_url, status_code=200, content=raw[:1000], html="",
                        title="", meta_description="", text_excerpt="",
                        content_sha256=__import__("hashlib").sha256(raw).hexdigest(),
                        error="Response exceeded maximum byte limit", redirects_count=redirects, elapsed_ms=elapsed,
                    )

                budget.record_request(category, success=True, redirects_count=redirects)
                html = raw.decode("utf-8", errors="replace")
                soup = BeautifulSoup(html, "lxml")
                title = soup.title.get_text(" ", strip=True)[:500] if soup.title else ""
                desc_node = soup.select_one('meta[name="description"], meta[property="og:description"]')
                meta_description = str(desc_node.get("content") or "").strip()[:2000] if desc_node else ""
                text_excerpt = (trafilatura.extract(html, url=final_url, include_links=False, include_tables=False) or "")[:5000]

                return FetchResult(
                    url=url, final_url=final_url, status_code=resp.status, content=raw, html=html,
                    title=title, meta_description=meta_description, text_excerpt=text_excerpt,
                    content_sha256=__import__("hashlib").sha256(raw).hexdigest(),
                    error=None, redirects_count=redirects, elapsed_ms=elapsed,
                )
        except urllib.error.HTTPError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            budget.record_request(category, success=False)
            return FetchResult(
                url=url, final_url=None, status_code=exc.code, content=b"", html="",
                title="", meta_description="", text_excerpt="", content_sha256="",
                error=f"HTTP {exc.code}", redirects_count=0, elapsed_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            budget.record_request(category, success=False)
            return FetchResult(
                url=url, final_url=None, status_code=0, content=b"", html="",
                title="", meta_description="", text_excerpt="", content_sha256="",
                error=f"{type(exc).__name__}: {str(exc)[:150]}", redirects_count=0, elapsed_ms=elapsed,
            )


# ============================================================================
# 3. SITEMAP DISCOVERY & PARSING
# ============================================================================

def parse_sitemap_xml(xml_content: str | bytes) -> tuple[list[str], list[str]]:
    """Parse sitemap XML safely using ElementTree, returning (page_urls, sitemap_index_urls)."""
    page_urls: list[str] = []
    sitemap_index_urls: list[str] = []

    if isinstance(xml_content, str):
        xml_bytes = xml_content.encode("utf-8")
    else:
        xml_bytes = xml_content

    if not xml_bytes.strip():
        return [], []

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        # Fallback to regex extraction if XML malformed
        locs = re.findall(r"<loc>(https?://[^<]+)</loc>", xml_bytes.decode("utf-8", errors="replace"), re.IGNORECASE)
        return [loc.strip() for loc in locs if loc.strip()], []

    # Strip XML namespace if present
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    if root.tag == "sitemapindex":
        for sitemap_node in root.findall("sitemap"):
            loc = sitemap_node.find("loc")
            if loc is not None and loc.text:
                sitemap_index_urls.append(loc.text.strip())
    elif root.tag == "urlset":
        for url_node in root.findall("url"):
            loc = url_node.find("loc")
            if loc is not None and loc.text:
                page_urls.append(loc.text.strip())

    return page_urls, sitemap_index_urls


def discover_sitemap_urls(
    base_url: str,
    fetcher: SafeHttpFetcher,
    budget: RequestBudget,
    *,
    max_urls: int = 50,
) -> list[str]:
    """Discover high-signal URLs from sitemap.xml and robots.txt sitemap directives."""
    candidates: list[str] = []
    parsed = urllib.parse.urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return []

    # Check sitemaps discovered from robots.txt, or default /sitemap.xml
    sitemap_targets = fetcher.get_robots_sitemaps(base_url)
    if not sitemap_targets:
        sitemap_targets = [urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/sitemap.xml", "", "", ""))]

    for sm_url in sitemap_targets[:budget.max_sitemap_requests]:
        if not budget.can_request("sitemap"):
            break
        res = fetcher.fetch_page(sm_url, budget, category="sitemap", respect_robots=False)
        if res.error or not res.content:
            continue

        pages, child_sitemaps = parse_sitemap_xml(res.content)
        candidates.extend(pages)

        # If it's a sitemap index, fetch at most 1 child sitemap to conserve budget
        for child_sm in child_sitemaps[:1]:
            if not budget.can_request("sitemap"):
                break
            child_res = fetcher.fetch_page(child_sm, budget, category="sitemap", respect_robots=False)
            if not child_res.error and child_res.content:
                c_pages, _ = parse_sitemap_xml(child_res.content)
                candidates.extend(c_pages)

    # Filter and rank candidates: prioritize high-signal pages, discard media/assets
    high_signal = []
    other_pages = []
    seen = set()

    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        path = urllib.parse.urlparse(url).path.lower()
        # Filter out assets
        if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".zip", ".css", ".js")):
            continue
        if any(keyword in path for keyword in HIGH_SIGNAL_KEYWORDS):
            high_signal.append(url)
        else:
            other_pages.append(url)

    # Return high-signal pages first, bounded by max_urls
    return (high_signal + other_pages)[:max_urls]


# ============================================================================
# 4. SEARCH CANDIDATE DISCOVERY
# ============================================================================

@dataclass(frozen=True)
class SearchCandidate:
    url: str
    title: str
    snippet: str
    rank: int
    provider: str
    host: str
    is_blocked_host: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _registered_domain_name(hostname: str | None) -> str | None:
    if not hostname:
        return None
    parts = hostname.split(".")
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def discover_search_candidates(
    profile: dict[str, Any],
    search_func: Callable[[str], dict[str, Any]] | None,
    budget: RequestBudget,
    *,
    count: int = 5,
) -> list[SearchCandidate]:
    """Perform deterministic search candidate discovery within budget limits."""
    if search_func is None or not budget.can_request("search"):
        return []

    query = build_company_search_query(profile)
    started = time.monotonic()
    try:
        payload = search_func(query)
        budget.record_request("search", success=True)
    except Exception:
        budget.record_request("search", success=False)
        return []

    results = (payload.get("web") or {}).get("results") or []
    candidates: list[SearchCandidate] = []

    for rank, item in enumerate(results[:count], start=1):
        if not isinstance(item, dict) or not item.get("url"):
            continue
        raw_url = str(item.get("url"))
        normalized = normalize_homepage(raw_url)
        if not normalized:
            continue

        host = (urllib.parse.urlparse(normalized).hostname or "").casefold().removeprefix("www.")
        is_blocked = any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS)

        candidates.append(SearchCandidate(
            url=normalized,
            title=str(item.get("title") or "")[:500],
            snippet=str(item.get("description") or "")[:1000],
            rank=rank,
            provider="search_api",
            host=host,
            is_blocked_host=is_blocked,
        ))

    return candidates


# ============================================================================
# 5. CANDIDATE SCORING
# ============================================================================

@dataclass
class CandidateScore:
    url: str
    score: float
    publishable_candidate: bool
    reasons: list[str]
    evidence_breakdown: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_candidate(
    profile: dict[str, Any],
    candidate_url: str,
    *,
    title: str = "",
    snippet: str = "",
    provenance: str = "search",
) -> CandidateScore:
    """Explicit, explainable scoring model for website candidates."""
    reasons: list[str] = []
    evidence_breakdown: dict[str, Any] = {}
    score = 0.0

    target_org = canonicalize_org_number(profile.get("organisation_number"))
    target_name = str(profile.get("name") or "").strip()
    target_mun = str(profile.get("municipality") or "").strip()
    target_ind = str(profile.get("industry_label") or "").strip()

    parsed = urllib.parse.urlparse(candidate_url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")

    # 1. Blocked host check
    if any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
        return CandidateScore(
            url=candidate_url, score=0.0, publishable_candidate=False,
            reasons=["Candidate host is a directory, aggregator, or social platform"],
            evidence_breakdown={"blocked_host": host},
        )

    # 2. Org number matching in evidence text
    evidence_text = f"{title} {snippet} {candidate_url}"
    evidence_digits = re.sub(r"\D", "", evidence_text)
    org_match = bool(target_org and target_org in evidence_digits)
    if org_match:
        score += 0.75
        reasons.append("Exact organisation number found in candidate evidence")
        evidence_breakdown["org_number_match"] = target_org

    # 3. Legal name & tokens matching
    t_core, _ = extract_legal_form(target_name)
    name_norm = normalize_legal_name(t_core)
    name_tokens = [t for t in name_norm.split() if len(t) > 1]
    title_norm = normalize_legal_name(title)
    snippet_norm = normalize_legal_name(snippet)

    reg_name = _registered_domain_name(host) or ""
    host_compact = re.sub(r"[^a-z0-9]", "", reg_name)
    name_compact = "".join(name_tokens)

    all_in_title = bool(name_tokens and all(token in title_norm for token in name_tokens))
    all_in_snippet = bool(name_tokens and all(token in (title_norm + " " + snippet_norm) for token in name_tokens))
    name_in_host = bool(host_compact and (host_compact in name_compact or name_compact in host_compact or any(t in host_compact for t in name_tokens if len(t) >= 4)))

    if all_in_title:
        score += 0.45
        reasons.append("All distinctive legal-name tokens appear in title")
        evidence_breakdown["name_in_title"] = True
    elif all_in_snippet:
        score += 0.25
        reasons.append("All distinctive legal-name tokens appear across evidence")
        evidence_breakdown["name_in_snippet"] = True

    if name_in_host:
        score += 0.30
        reasons.append(f"Legal name aligns with candidate hostname ({host})")
        evidence_breakdown["name_in_host"] = host

    # 4. Location / municipality matching
    if target_mun and normalize_legal_name(target_mun) in (snippet_norm + " " + title_norm):
        score += 0.10
        reasons.append(f"Registered municipality ({target_mun}) appears in candidate evidence")
        evidence_breakdown["municipality_match"] = target_mun

    # 5. Industry description matching
    if target_ind:
        ind_tokens = [t for t in normalize_legal_name(target_ind).split() if len(t) > 3]
        if any(t in snippet_norm for t in ind_tokens):
            score += 0.10
            reasons.append(f"Industry description keywords appear in candidate snippet")
            evidence_breakdown["industry_match"] = True

    # 6. Provenance weighting
    if provenance == "registry":
        score += 0.20
        reasons.append("Anchored directly to official BRREG registry website record")
    elif provenance == "sitemap":
        score += 0.10
        reasons.append("Discovered via site sitemap references")

    score = min(score, 1.0)
    # A publishable candidate requires substantive alignment: name in host + (org match or all in title or all in snippet)
    publishable = (score >= 0.70 and name_in_host and (org_match or all_in_title or all_in_snippet)) or (provenance == "registry" and score >= 0.30)

    return CandidateScore(
        url=candidate_url,
        score=round(score, 3),
        publishable_candidate=publishable,
        reasons=reasons,
        evidence_breakdown=evidence_breakdown,
    )


# ============================================================================
# 6. EXACT-ENTITY VERIFICATION & SAFE ABSTENTION
# ============================================================================

class VerificationEvidenceLevel(str, Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    CONFLICT = "conflict"


@dataclass
class VerificationItem:
    identifier: str
    level: VerificationEvidenceLevel
    observed_value: Any
    expected_value: Any
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "level": self.level.value,
            "observed_value": self.observed_value,
            "expected_value": self.expected_value,
            "explanation": self.explanation,
        }


class DiscoveryVerdictStatus(str, Enum):
    VERIFIED = "verified"
    ABSTAIN = "abstain"


@dataclass
class WebsiteDiscoveryResult:
    status: DiscoveryVerdictStatus
    url: str | None
    decision_reason: str
    reasons: list[str]
    evidence_trail: list[VerificationItem]
    budget_summary: dict[str, Any]
    pages_crawled: list[dict[str, Any]]
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "url": self.url,
            "decision_reason": self.decision_reason,
            "reasons": self.reasons,
            "evidence_trail": [item.to_dict() for item in self.evidence_trail],
            "budget_summary": self.budget_summary,
            "pages_crawled": self.pages_crawled,
            "score": self.score,
        }


def verify_exact_entity(
    profile: dict[str, Any],
    crawled_pages: list[FetchResult],
    candidate_score: CandidateScore | None = None,
) -> tuple[DiscoveryVerdictStatus, list[VerificationItem], list[str]]:
    """Verify that a crawled website genuinely represents the Stage 1 legal entity."""
    evidence_items: list[VerificationItem] = []
    reasons: list[str] = []

    target_org = canonicalize_org_number(profile.get("organisation_number"))
    target_name = str(profile.get("name") or "").strip()
    target_mun = str(profile.get("municipality") or "").strip()
    t_core, t_form = extract_legal_form(target_name)
    name_tokens = normalize_legal_name(t_core).split()

    combined_text = " ".join(f"{p.title} {p.meta_description} {p.text_excerpt}" for p in crawled_pages)
    combined_digits = re.sub(r"\D", "", combined_text)
    combined_norm = normalize_legal_name(combined_text)

    # 1. Parked domain check
    if any(marker in combined_norm for marker in PARKED_PAGE_MARKERS):
        evidence_items.append(VerificationItem(
            identifier="parked_marker",
            level=VerificationEvidenceLevel.CONFLICT,
            observed_value=True,
            expected_value=False,
            explanation="Website contains parked domain, sale placeholder, or generic hosting notices",
        ))
        reasons.append("Abstain: page is a parked or placeholder domain")
        return DiscoveryVerdictStatus.ABSTAIN, evidence_items, reasons

    # 2. Check for conflicting organisation numbers (e.g. sister company, parent, competitor)
    potential_org_matches = re.findall(r"\b\d{3}[\s\.\-]?\d{3}[\s\.\-]?\d{3}\b", combined_text)
    candidate_orgs = set()
    for raw_match in potential_org_matches:
        canon = canonicalize_org_number(raw_match)
        if canon and canon != target_org:
            candidate_orgs.add(canon)

    if candidate_orgs and not (target_org and target_org in combined_digits):
        evidence_items.append(VerificationItem(
            identifier="organisation_number",
            level=VerificationEvidenceLevel.CONFLICT,
            observed_value=sorted(candidate_orgs),
            expected_value=target_org,
            explanation=f"Page displays conflicting organisation number(s): {sorted(candidate_orgs)}",
        ))
        reasons.append("Abstain: page displays conflicting organisation number")
        return DiscoveryVerdictStatus.ABSTAIN, evidence_items, reasons

    # 3. Strong Identifier: Exact organisation number found in page content
    org_verified = False
    if target_org and target_org in combined_digits:
        org_verified = True
        evidence_items.append(VerificationItem(
            identifier="organisation_number",
            level=VerificationEvidenceLevel.STRONG,
            observed_value=target_org,
            expected_value=target_org,
            explanation=f"Exact 9-digit organisation number {target_org} confirmed in crawled page content",
        ))
        reasons.append("Strong evidence: exact organisation number confirmed on website")

    # 4. Strong/Medium Identifier: Legal name matching
    name_matched = False
    homepage_title = crawled_pages[0].title if crawled_pages else ""
    name_match = match_legal_names(target_name, homepage_title)

    if name_match.is_match:
        name_matched = True
        evidence_items.append(VerificationItem(
            identifier="legal_name_in_title",
            level=VerificationEvidenceLevel.STRONG,
            observed_value=homepage_title,
            expected_value=target_name,
            explanation=f"Exact/normalized legal name matches homepage title: {name_match.reasons}",
        ))
        reasons.append("Strong evidence: legal name matches homepage title")
    elif name_tokens and all(token in combined_norm for token in name_tokens):
        name_matched = True
        evidence_items.append(VerificationItem(
            identifier="legal_name_tokens",
            level=VerificationEvidenceLevel.MEDIUM,
            observed_value=name_tokens,
            expected_value=target_name,
            explanation="All core legal-name tokens appear in crawled website text",
        ))
        reasons.append("Medium evidence: all core legal name tokens present on website")
    else:
        evidence_items.append(VerificationItem(
            identifier="legal_name",
            level=VerificationEvidenceLevel.WEAK,
            observed_value=homepage_title,
            expected_value=target_name,
            explanation="Distinctive legal name not fully matched on website",
        ))

    # 5. Medium Identifier: Municipality / registered address match
    if target_mun and normalize_legal_name(target_mun) in combined_norm:
        evidence_items.append(VerificationItem(
            identifier="municipality",
            level=VerificationEvidenceLevel.MEDIUM,
            observed_value=target_mun,
            expected_value=target_mun,
            explanation=f"Registered municipality {target_mun} appears in website text",
        ))
        reasons.append(f"Medium evidence: municipality {target_mun} matched on website")

    # Final verdict decision:
    total_text_len = sum(len(p.text_excerpt.strip()) for p in crawled_pages)
    substantive_content = total_text_len >= (20 if org_verified else 50)

    if org_verified and substantive_content:
        return DiscoveryVerdictStatus.VERIFIED, evidence_items, reasons

    if name_matched and substantive_content:
        # If name is matched and score was high with hostname alignment, verify
        if candidate_score and candidate_score.score >= 0.70:
            return DiscoveryVerdictStatus.VERIFIED, evidence_items, reasons

    reasons.append("Abstain: insufficient exact-entity evidence to verify website without guessing")
    return DiscoveryVerdictStatus.ABSTAIN, evidence_items, reasons


# ============================================================================
# 7. DETERMINISTIC WEBSITE DISCOVERY PIPELINE
# ============================================================================

def discover_company_website(
    profile: dict[str, Any],
    *,
    search_func: Callable[[str], dict[str, Any]] | None = None,
    budget: RequestBudget | None = None,
    fetcher: SafeHttpFetcher | None = None,
) -> WebsiteDiscoveryResult:
    """Run the complete, budget-aware Stage 2 website discovery pipeline."""
    if budget is None:
        budget = RequestBudget()
    if fetcher is None:
        fetcher = SafeHttpFetcher()

    registry_website = profile.get("website")
    crawled_pages: list[FetchResult] = []

    # ------------------------------------------------------------------------
    # STEP 1: Registry Website Anchor
    # ------------------------------------------------------------------------
    if registry_website:
        norm_reg_url = normalize_homepage(registry_website)
        if norm_reg_url:
            score = score_candidate(profile, norm_reg_url, provenance="registry")
            # Crawl homepage
            hp_res = fetcher.fetch_page(norm_reg_url, budget, category="page")
            if not hp_res.error and hp_res.status_code == 200:
                crawled_pages.append(hp_res)

                # Sitemap discovery for high-signal secondary pages
                secondary_urls = discover_sitemap_urls(hp_res.final_url or norm_reg_url, fetcher, budget, max_urls=5)
                # Fallback to in-page priority links if sitemap yielded none
                if not secondary_urls:
                    soup = BeautifulSoup(hp_res.html, "lxml")
                    secondary_urls = _priority_links(hp_res.final_url or norm_reg_url, soup, limit=3)

                for sec_url in secondary_urls[:3]:
                    if not budget.can_request("page"):
                        break
                    sec_res = fetcher.fetch_page(sec_url, budget, category="page")
                    if not sec_res.error and sec_res.status_code == 200:
                        crawled_pages.append(sec_res)

                # Verify exact entity
                verdict, evidence_trail, reasons = verify_exact_entity(profile, crawled_pages, score)
                if verdict == DiscoveryVerdictStatus.VERIFIED:
                    return WebsiteDiscoveryResult(
                        status=DiscoveryVerdictStatus.VERIFIED,
                        url=hp_res.final_url or norm_reg_url,
                        decision_reason="Verified official website anchored to BRREG registry record",
                        reasons=reasons,
                        evidence_trail=evidence_trail,
                        budget_summary=budget.to_dict(),
                        pages_crawled=[asdict(p) for p in crawled_pages],
                        score=score.score,
                    )

    # ------------------------------------------------------------------------
    # STEP 2: Search Candidate Discovery (when registry website missing/unverified)
    # ------------------------------------------------------------------------
    candidates = discover_search_candidates(profile, search_func, budget)
    scored_candidates = [
        score_candidate(profile, cand.url, title=cand.title, snippet=cand.snippet, provenance="search")
        for cand in candidates
        if not cand.is_blocked_host
    ]
    scored_candidates.sort(key=lambda s: (-s.score, s.url))

    for top_cand in scored_candidates:
        if not top_cand.publishable_candidate:
            continue
        if not budget.can_request("page"):
            break

        cand_crawled: list[FetchResult] = []
        hp_res = fetcher.fetch_page(top_cand.url, budget, category="page")
        if hp_res.error or hp_res.status_code != 200:
            continue
        cand_crawled.append(hp_res)

        # Secondary pages crawl
        soup = BeautifulSoup(hp_res.html, "lxml")
        secondary_urls = _priority_links(hp_res.final_url or top_cand.url, soup, limit=2)
        for sec_url in secondary_urls:
            if not budget.can_request("page"):
                break
            sec_res = fetcher.fetch_page(sec_url, budget, category="page")
            if not sec_res.error and sec_res.status_code == 200:
                cand_crawled.append(sec_res)

        verdict, evidence_trail, reasons = verify_exact_entity(profile, cand_crawled, top_cand)
        if verdict == DiscoveryVerdictStatus.VERIFIED:
            return WebsiteDiscoveryResult(
                status=DiscoveryVerdictStatus.VERIFIED,
                url=hp_res.final_url or top_cand.url,
                decision_reason="Verified official website from search discovery with exact-entity proof",
                reasons=reasons,
                evidence_trail=evidence_trail,
                budget_summary=budget.to_dict(),
                pages_crawled=[asdict(p) for p in cand_crawled],
                score=top_cand.score,
            )

    # ------------------------------------------------------------------------
    # STEP 3: Safe Abstention
    # ------------------------------------------------------------------------
    abstention_reason = "No candidate website met exact-entity verification standards"
    if not budget.can_request("page") or not budget.can_request("total"):
        abstention_reason = "Request budget exhausted before website verification could be completed"

    return WebsiteDiscoveryResult(
        status=DiscoveryVerdictStatus.ABSTAIN,
        url=None,
        decision_reason=abstention_reason,
        reasons=["Abstained: exact company website could not be verified without guessing"],
        evidence_trail=[],
        budget_summary=budget.to_dict(),
        pages_crawled=[asdict(p) for p in crawled_pages],
        score=0.0,
    )
