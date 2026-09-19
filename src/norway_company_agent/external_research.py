"""Stage 6: External Research & Enrichment Engine.

Provides search-based candidate generation, centralized source-policy enforcement,
identity-safe leadership discovery, social/video discovery policy enforcement,
and external footprint normalization with fail-closed evidence quality.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .evidence import utc_now
from .evidence_engine import (
    BLOCKED_AGGREGATOR_DOMAINS,
    SourceAuthority,
    classify_source_authority,
    compute_content_hash,
    is_safe_public_url,
)
from .identity_engine import canonicalize_org_number, normalize_legal_name


# ============================================================================
# 1. ENUMS & DATA MODELS
# ============================================================================

class CandidateType(str, Enum):
    """Categorization for research candidates."""
    WEBSITE = "website"
    LEADERSHIP = "leadership"
    COMPANY_PROFILE = "company_profile"
    FOOTPRINT = "footprint"
    SOCIAL_VIDEO = "social_video"


class SourcePolicyStatus(str, Enum):
    """Centralized policy status for candidate sources."""
    PERMITTED = "permitted"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    REQUIRES_VERIFICATION = "requires_verification"


class LeadershipRoleType(str, Enum):
    """Normalized leadership role classifications."""
    DAGLIG_LEDER = "daglig_leder"
    STYRELEDER = "styreleder"
    STYREMEDLEM = "styremedlem"
    FOUNDER = "founder"
    EXECUTIVE = "executive"
    OTHER = "other"


class ExternalFootprintCategory(str, Enum):
    """Normalized categories for public digital footprint."""
    OFFICIAL_WEBSITE = "official_website"
    COMPANY_PROFILE = "company_profile"
    LEADERSHIP_PROFILE = "leadership_profile"
    NEWS_PUBLICATION = "news_publication"
    SOCIAL_REFERENCE = "social_reference"
    VIDEO_REFERENCE = "video_reference"
    PUBLIC_REGISTER = "public_register"
    OTHER = "other"


# Extended set of restricted/unpermitted scraping platforms
RESTRICTED_SCRAPING_DOMAINS = BLOCKED_AGGREGATOR_DOMAINS | {
    "tiktok.com",
    "glassdoor.com",
    "glassdoor.no",
    "indeed.com",
    "indeed.no",
}

PERMITTED_GOVERNMENT_DOMAINS = {
    "brreg.no",
    "data.brreg.no",
    "regjeringen.no",
    "lovdata.no",
    "ssb.no",
    "skatteetaten.no",
    "toll.no",
}

PERMITTED_NEWS_DOMAINS = {
    "e24.no",
    "dn.no",
    "finansavisen.no",
    "tu.no",
    "nrk.no",
    "kapital.no",
    "aftenposten.no",
    "vg.no",
    "dagbladet.no",
    "bergens-tidende.no",
    "adressa.no",
}

PERMITTED_VIDEO_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "vimeo.com",
}


@dataclass
class SourcePolicyDecision:
    """Centralized policy assessment for any candidate or source URL."""
    url: str
    status: SourcePolicyStatus
    is_allowed: bool
    reason: str
    matched_rule: str
    prohibits_scraping: bool = False
    requires_official_verification: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status.value,
            "is_allowed": self.is_allowed,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "prohibits_scraping": self.prohibits_scraping,
            "requires_official_verification": self.requires_official_verification,
        }


@dataclass
class ResearchCandidate:
    """Discovered candidate entity with provenance and relevance."""
    candidate_id: str
    url: str
    normalized_url: str
    domain: str
    candidate_type: CandidateType
    title: str
    snippet: str
    search_query: str
    source_engine: str
    rank: int = 1
    relevance_score: float = 0.5
    confidence: float = 0.5
    retrieved_at: str = field(default_factory=utc_now)
    policy_decision: SourcePolicyDecision | None = None
    is_candidate_only: bool = True  # Must never be treated as verified fact alone
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "url": self.url,
            "normalized_url": self.normalized_url,
            "domain": self.domain,
            "candidate_type": self.candidate_type.value,
            "title": self.title,
            "snippet": self.snippet,
            "search_query": self.search_query,
            "source_engine": self.source_engine,
            "rank": self.rank,
            "relevance_score": round(self.relevance_score, 3),
            "confidence": round(self.confidence, 3),
            "retrieved_at": self.retrieved_at,
            "policy_decision": self.policy_decision.to_dict() if self.policy_decision else None,
            "is_candidate_only": self.is_candidate_only,
            "metadata": self.metadata,
        }


@dataclass
class LeadershipEntity:
    """Discovered or verified leadership entity."""
    person_name: str
    role_title: str
    role_type: LeadershipRoleType
    organisation_number: str
    organisation_name: str
    source_url: str
    evidence_span: str | None = None
    confidence: float = 1.0
    status: str = "verified"  # "verified", "candidate", "unverified", "conflicting"
    source_authority: SourceAuthority = SourceAuthority.GOVERNMENT_REGISTRY

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_name": self.person_name,
            "role_title": self.role_title,
            "role_type": self.role_type.value,
            "organisation_number": self.organisation_number,
            "organisation_name": self.organisation_name,
            "source_url": self.source_url,
            "evidence_span": self.evidence_span,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "source_authority": int(self.source_authority),
        }


@dataclass
class ExternalFootprintItem:
    """Normalized item in the company's external public footprint."""
    item_id: str
    category: ExternalFootprintCategory
    url: str
    normalized_url: str
    domain: str
    title: str
    source_policy_status: SourcePolicyStatus
    source_url: str
    retrieved_at: str = field(default_factory=utc_now)
    confidence: float = 0.5
    is_verified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category.value,
            "url": self.url,
            "normalized_url": self.normalized_url,
            "domain": self.domain,
            "title": self.title,
            "source_policy_status": self.source_policy_status.value,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "confidence": round(self.confidence, 3),
            "is_verified": self.is_verified,
            "metadata": self.metadata,
        }


@dataclass
class ExternalFootprintProfile:
    """Aggregated external footprint for a company."""
    organisation_number: str
    company_name: str
    items: list[ExternalFootprintItem] = field(default_factory=list)
    category_counts: dict[str, int] = field(default_factory=dict)
    total_items: int = 0
    rejected_items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organisation_number": self.organisation_number,
            "company_name": self.company_name,
            "items": [item.to_dict() for item in self.items],
            "category_counts": self.category_counts,
            "total_items": self.total_items,
            "rejected_items": self.rejected_items,
        }


# ============================================================================
# 2. URL & DOMAIN NORMALIZATION
# ============================================================================

TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "ref", "ref_src", "source", "trk",
    "feature", "si", "v_id",
}


def normalize_domain_for_research(url_or_domain: str) -> str:
    """Extract and normalize host domain: lowercase, strip www, strip port."""
    if not url_or_domain:
        return ""
    text = url_or_domain.strip().lower()
    if "://" in text:
        parsed = urllib.parse.urlparse(text)
        host = parsed.hostname or ""
    else:
        host = text.split("/")[0].split(":")[0]
    return host.lower().lstrip("www.").rstrip(".")


def normalize_url_for_research(url: str) -> str:
    """Deterministic URL normalizer for candidate research.

    Normalizes scheme, lowercase hostname, removes default ports, strips tracking
    parameters, normalizes path slashes, and removes fragments.
    """
    if not url or not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw

    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return raw

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        scheme = "https"

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return raw

    # Default port removal
    port = parsed.port
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"

    # Normalize path
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Normalize query params: remove tracking parameters, sort remainder
    filtered_params = []
    if parsed.query:
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            if k.lower() not in TRACKING_QUERY_PARAMS:
                filtered_params.append((k, v))
        filtered_params.sort(key=lambda item: (item[0], item[1]))

    normalized_query = urllib.parse.urlencode(filtered_params)

    parts = (scheme, netloc, path, "", normalized_query, "")
    return urllib.parse.urlunparse(parts)


# ============================================================================
# 3. CENTRALIZED SOURCE-POLICY ENGINE
# ============================================================================

def evaluate_source_policy(
    url: str,
    source_type: str | None = None,
    acquisition_mode: str | None = None,
    target_domains: set[str] | None = None,
) -> SourcePolicyDecision:
    """Centralized policy evaluator for external candidate sources.

    Strictly enforces source allowlists, blocks unpermitted scraping of restricted platforms,
    ensures SSRF safety, and requires verification for unconfirmed third-party sources.
    """
    if not url:
        return SourcePolicyDecision(
            url="",
            status=SourcePolicyStatus.REJECTED,
            is_allowed=False,
            reason="Missing source URL",
            matched_rule="empty_url_check",
        )

    # 1. URL Safety & SSRF checks
    is_safe, url_err = is_safe_public_url(url)
    if not is_safe:
        return SourcePolicyDecision(
            url=url,
            status=SourcePolicyStatus.REJECTED,
            is_allowed=False,
            reason=f"Unsafe URL target: {url_err}",
            matched_rule="ssrf_and_safety_filter",
        )

    norm_host = normalize_domain_for_research(url)

    # 2. Check for prohibited scraping / restricted platforms
    is_restricted_platform = any(
        norm_host == b or norm_host.endswith(f".{b}") for b in RESTRICTED_SCRAPING_DOMAINS
    )
    if is_restricted_platform:
        # If acquisition_mode explicitly requests scraping or data extraction from a restricted platform
        if acquisition_mode in {"unauthorized_scraping", "scraping", "crawler", "unofficial_api"}:
            return SourcePolicyDecision(
                url=url,
                status=SourcePolicyStatus.REJECTED,
                is_allowed=False,
                reason=f"Platform '{norm_host}' prohibits unauthorized scraping under project policy",
                matched_rule="restricted_platform_scraping_ban",
                prohibits_scraping=True,
            )
        # Even as a candidate source, restricted platforms cannot be used as identity authority
        return SourcePolicyDecision(
            url=url,
            status=SourcePolicyStatus.REJECTED,
            is_allowed=False,
            reason=f"Host '{norm_host}' is a restricted platform or third-party directory; direct ingestion rejected",
            matched_rule="blocked_aggregator_and_social_scraping_rule",
            prohibits_scraping=True,
        )

    # 3. Government / Registry Allowlist
    is_gov = any(norm_host == g or norm_host.endswith(f".{g}") for g in PERMITTED_GOVERNMENT_DOMAINS)
    if is_gov:
        return SourcePolicyDecision(
            url=url,
            status=SourcePolicyStatus.PERMITTED,
            is_allowed=True,
            reason="Authoritative government registry domain",
            matched_rule="government_registry_allowlist",
        )

    # 4. Verified First-Party Company Domains
    if target_domains:
        clean_target_domains = {normalize_domain_for_research(d) for d in target_domains if d}
        if norm_host in clean_target_domains or any(norm_host.endswith(f".{td}") for td in clean_target_domains):
            return SourcePolicyDecision(
                url=url,
                status=SourcePolicyStatus.PERMITTED,
                is_allowed=True,
                reason="Verified first-party company website domain",
                matched_rule="first_party_domain_allowlist",
            )

    # 5. Reputable Public News / Publication Domains
    is_news = any(norm_host == n or norm_host.endswith(f".{n}") for n in PERMITTED_NEWS_DOMAINS)
    if is_news:
        return SourcePolicyDecision(
            url=url,
            status=SourcePolicyStatus.PERMITTED,
            is_allowed=True,
            reason="Reputable public news/publication source",
            matched_rule="reputable_news_allowlist",
        )

    # 6. Permitted Video Platform (YouTube) - Only declared channels or verified references
    is_video = any(norm_host == v or norm_host.endswith(f".{v}") for v in PERMITTED_VIDEO_DOMAINS)
    if is_video:
        return SourcePolicyDecision(
            url=url,
            status=SourcePolicyStatus.REQUIRES_VERIFICATION,
            is_allowed=True,
            reason="Permitted video platform; requires first-party declaration or entity corroboration",
            matched_rule="permitted_video_platform_rule",
            requires_official_verification=True,
        )

    # 7. Unverified Secondary / Third-Party Source
    return SourcePolicyDecision(
        url=url,
        status=SourcePolicyStatus.REQUIRES_VERIFICATION,
        is_allowed=False,
        reason=f"Domain '{norm_host}' is not in approved allowlists; requires verification before ingestion",
        matched_rule="default_unverified_source_policy",
        requires_official_verification=True,
    )


# ============================================================================
# 4. SEARCH-BASED CANDIDATE GENERATION
# ============================================================================

def generate_research_candidates(
    target_entity: dict[str, Any],
    search_results: list[dict[str, Any]] | None = None,
    declared_links: list[dict[str, Any]] | None = None,
    candidate_types: set[CandidateType] | None = None,
) -> list[ResearchCandidate]:
    """Generate, normalize, deduplicate, and evaluate research candidates.

    Preserves provenance and marks candidates strictly as candidate-only (never verified facts).
    """
    candidates: list[ResearchCandidate] = []
    seen_urls: set[str] = set()

    org = canonicalize_org_number(str(target_entity.get("organisation_number") or ""))
    company_name = str(target_entity.get("name") or "").strip()
    target_domains = set()
    if target_entity.get("website"):
        target_domains.add(normalize_domain_for_research(str(target_entity["website"])))

    # Process search results
    raw_results = search_results or []
    for idx, item in enumerate(raw_results):
        raw_url = str(item.get("url") or item.get("link") or "").strip()
        if not raw_url:
            continue

        norm_url = normalize_url_for_research(raw_url)
        if not norm_url or norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        domain = normalize_domain_for_research(norm_url)
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or item.get("description") or "").strip()
        query = str(item.get("query") or f"{company_name} {org}").strip()
        engine = str(item.get("engine") or item.get("source") or "search").strip()
        rank = int(item.get("rank") or idx + 1)

        # Classify candidate type
        ctype = CandidateType.WEBSITE
        lower_title = title.lower()
        lower_snippet = snippet.lower()
        lower_url = norm_url.lower()

        if any(w in lower_title or w in lower_snippet for w in ("daglig leder", "styreleder", "ceo", "founder", "grunnlegger", "director")):
            ctype = CandidateType.LEADERSHIP
        elif any(v in domain for v in PERMITTED_VIDEO_DOMAINS) or "video" in lower_url:
            ctype = CandidateType.SOCIAL_VIDEO
        elif any(p in lower_url for p in ("/om-oss", "/about", "/kontakt", "/contact")):
            ctype = CandidateType.WEBSITE
        elif any(n in domain for n in PERMITTED_NEWS_DOMAINS):
            ctype = CandidateType.FOOTPRINT
        elif any(g in domain for g in PERMITTED_GOVERNMENT_DOMAINS):
            ctype = CandidateType.COMPANY_PROFILE

        if candidate_types and ctype not in candidate_types:
            continue

        # Evaluate policy
        policy = evaluate_source_policy(norm_url, target_domains=target_domains)

        # Relevance scoring
        rel_score = 0.5
        if domain in target_domains:
            rel_score += 0.4
        if org and org in snippet:
            rel_score += 0.3
        if normalize_legal_name(company_name) in normalize_legal_name(title):
            rel_score += 0.2
        rel_score = min(1.0, max(0.1, rel_score - (rank - 1) * 0.05))

        cid_raw = f"cand-{org}-{norm_url}-{rank}"
        cand_id = "cand-" + compute_content_hash(cid_raw)[:16]

        candidates.append(
            ResearchCandidate(
                candidate_id=cand_id,
                url=raw_url,
                normalized_url=norm_url,
                domain=domain,
                candidate_type=ctype,
                title=title,
                snippet=snippet,
                search_query=query,
                source_engine=engine,
                rank=rank,
                relevance_score=rel_score,
                confidence=round(rel_score * (0.9 if policy.is_allowed else 0.3), 3),
                policy_decision=policy,
                is_candidate_only=True,  # Crucial: search results are never verified facts
                metadata={"rank": rank, "original_url": raw_url},
            )
        )

    # Process declared links (from verified company website)
    for dlink in declared_links or []:
        raw_url = str(dlink.get("url") or "").strip()
        if not raw_url:
            continue
        norm_url = normalize_url_for_research(raw_url)
        if not norm_url or norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        domain = normalize_domain_for_research(norm_url)
        platform = str(dlink.get("platform") or "declared_link").strip()
        ctype = CandidateType.SOCIAL_VIDEO if any(v in domain for v in PERMITTED_VIDEO_DOMAINS) else CandidateType.FOOTPRINT

        policy = evaluate_source_policy(norm_url, target_domains=target_domains)

        cid_raw = f"decl-{org}-{norm_url}"
        cand_id = "decl-" + compute_content_hash(cid_raw)[:16]

        candidates.append(
            ResearchCandidate(
                candidate_id=cand_id,
                url=raw_url,
                normalized_url=norm_url,
                domain=domain,
                candidate_type=ctype,
                title=f"Declared {platform} link",
                snippet=f"Declared profile on {platform} found on verified company site",
                search_query="first_party_declaration",
                source_engine="company_website",
                rank=1,
                relevance_score=0.9,
                confidence=0.85,
                policy_decision=policy,
                is_candidate_only=True,
                metadata={"platform": platform, "declared_on_website": True},
            )
        )

    # Sort deterministically by relevance descending, then rank ascending, then normalized URL
    candidates.sort(key=lambda c: (-c.relevance_score, c.rank, c.normalized_url))
    return candidates


# ============================================================================
# 5. LEADERSHIP / FOUNDER DISCOVERY
# ============================================================================

ROLE_PATTERNS = [
    (r"\b(?:daglig\s+leder|administrerende\s+direktør|ceo)\b", LeadershipRoleType.DAGLIG_LEDER, "Daglig leder"),
    (r"\b(?:styreleder|styrets\s+leder|chairperson|chairman)\b", LeadershipRoleType.STYRELEDER, "Styreleder"),
    (r"\b(?:styremedlem|board\s+member)\b", LeadershipRoleType.STYREMEDLEM, "Styremedlem"),
    (r"\b(?:grunnlegger|medgrunnlegger|founder|co-founder)\b", LeadershipRoleType.FOUNDER, "Grunnlegger"),
    (r"\b(?:cfo|cto|cmo|finansdirektør|driftsdirektør|teknologidirektør)\b", LeadershipRoleType.EXECUTIVE, "Ledende ansatt"),
]


def classify_leadership_role(text: str) -> tuple[LeadershipRoleType, str]:
    """Classify a leadership role title string into a normalized role type and label."""
    clean = text.strip()
    for pat, rtype, label in ROLE_PATTERNS:
        if re.search(pat, clean, re.IGNORECASE):
            return rtype, label
    return LeadershipRoleType.OTHER, clean or "Rolle"


def discover_leadership(
    target_entity: dict[str, Any],
    sources_data: list[dict[str, Any]],
) -> list[LeadershipEntity]:
    """Discover leadership entities from permitted public sources.

    Strict identity resolution:
    - Never assumes similarly named people are the same person without org corroboration.
    - Requires company name or org number link.
    - Prefers authoritative sources (BRREG roller > company site > secondary).
    - Fails closed: rejects manufactured relationships from weak search snippets.
    """
    discovered: dict[tuple[str, LeadershipRoleType], LeadershipEntity] = {}

    target_org = canonicalize_org_number(str(target_entity.get("organisation_number") or ""))
    target_name = normalize_legal_name(str(target_entity.get("name") or ""))

    for item in sources_data:
        source_url = str(item.get("source_url") or item.get("url") or "")
        source_type = str(item.get("source_type") or "unknown")
        auth = classify_source_authority(source_type, source_url)

        # Reject unauthoritative or unpermitted sources
        if auth == SourceAuthority.UNVERIFIED_THIRD_PARTY:
            continue
        if auth == SourceAuthority.SEARCH_DISCOVERY:
            # Search snippets alone must NOT manufacture leadership relationships
            continue

        roles_list = item.get("roles") or []
        for r in roles_list:
            raw_name = str(r.get("name") or "").strip()
            raw_role = str(r.get("role") or r.get("title") or "").strip()
            if not raw_name or not raw_role:
                continue

            # Corroborate identity: check for explicit entity link in record
            rec_org = canonicalize_org_number(str(r.get("organisation_number") or ""))
            rec_comp = normalize_legal_name(str(r.get("company_name") or r.get("organisation_name") or ""))

            if rec_org and rec_org != target_org:
                # Conflicting entity: skip immediately to prevent wrong-company conflation
                continue

            if rec_comp and target_name and rec_comp != target_name and target_name not in rec_comp and rec_comp not in target_name:
                # Conflicting company name: skip
                continue

            role_type, clean_role_title = classify_leadership_role(raw_role)
            norm_name = " ".join(raw_name.split())
            key = (norm_name.lower(), role_type)

            confidence = 1.0 if auth == SourceAuthority.GOVERNMENT_REGISTRY else 0.85 if auth == SourceAuthority.VERIFIED_FIRST_PARTY else 0.6
            evidence_span = str(r.get("evidence_span") or f"{clean_role_title}: {norm_name}")

            entity = LeadershipEntity(
                person_name=norm_name,
                role_title=clean_role_title,
                role_type=role_type,
                organisation_number=target_org,
                organisation_name=target_name,
                source_url=source_url,
                evidence_span=evidence_span,
                confidence=confidence,
                status="verified" if auth >= SourceAuthority.VERIFIED_FIRST_PARTY else "candidate",
                source_authority=auth,
            )

            # Keep the highest-authority source if duplicate person + role found
            if key not in discovered or int(auth) > int(discovered[key].source_authority):
                discovered[key] = entity

    results = list(discovered.values())
    results.sort(key=lambda x: (x.role_type.value, x.person_name))
    return results


# ============================================================================
# 6. EXTERNAL FOOTPRINT AGGREGATION
# ============================================================================

def build_external_footprint(
    candidates: list[ResearchCandidate],
    declared_links: list[dict[str, Any]] | None = None,
    target_entity: dict[str, Any] | None = None,
) -> ExternalFootprintProfile:
    """Build a normalized, deduplicated representation of discovered external presence.

    Downstream enrichment cannot accidentally consume rejected sources:
    rejected candidates are moved to the rejection audit log.
    """
    target = target_entity or {}
    org = canonicalize_org_number(str(target.get("organisation_number") or ""))
    name = str(target.get("name") or "").strip()

    footprint_items: list[ExternalFootprintItem] = []
    rejected_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for cand in candidates:
        norm_url = cand.normalized_url
        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        # Check policy status
        policy = cand.policy_decision or evaluate_source_policy(norm_url)
        if policy.status == SourcePolicyStatus.REJECTED:
            rejected_items.append({
                "url": cand.url,
                "normalized_url": norm_url,
                "reason": policy.reason,
                "matched_rule": policy.matched_rule,
                "prohibits_scraping": policy.prohibits_scraping,
            })
            continue

        # Map candidate type to footprint category
        cat_map = {
            CandidateType.WEBSITE: ExternalFootprintCategory.OFFICIAL_WEBSITE,
            CandidateType.COMPANY_PROFILE: ExternalFootprintCategory.COMPANY_PROFILE,
            CandidateType.LEADERSHIP: ExternalFootprintCategory.LEADERSHIP_PROFILE,
            CandidateType.FOOTPRINT: ExternalFootprintCategory.NEWS_PUBLICATION,
            CandidateType.SOCIAL_VIDEO: ExternalFootprintCategory.VIDEO_REFERENCE,
        }
        category = cat_map.get(cand.candidate_type, ExternalFootprintCategory.OTHER)

        item_id = "fp-" + compute_content_hash(f"{org}|{norm_url}|{category.value}")[:16]

        footprint_items.append(
            ExternalFootprintItem(
                item_id=item_id,
                category=category,
                url=cand.url,
                normalized_url=norm_url,
                domain=cand.domain,
                title=cand.title,
                source_policy_status=policy.status,
                source_url=cand.url,
                retrieved_at=cand.retrieved_at,
                confidence=cand.confidence,
                is_verified=not cand.is_candidate_only,
                metadata=cand.metadata,
            )
        )

    # Process declared links if any
    for dlink in declared_links or []:
        raw_url = str(dlink.get("url") or "").strip()
        if not raw_url:
            continue
        norm_url = normalize_url_for_research(raw_url)
        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        policy = evaluate_source_policy(norm_url)
        domain = normalize_domain_for_research(norm_url)
        is_video = any(v in domain for v in PERMITTED_VIDEO_DOMAINS)
        cat = ExternalFootprintCategory.VIDEO_REFERENCE if is_video else ExternalFootprintCategory.SOCIAL_REFERENCE

        item_id = "fp-decl-" + compute_content_hash(f"{org}|{norm_url}|{cat.value}")[:16]
        footprint_items.append(
            ExternalFootprintItem(
                item_id=item_id,
                category=cat,
                url=raw_url,
                normalized_url=norm_url,
                domain=domain,
                title=f"Declared {dlink.get('platform', 'profile')}",
                source_policy_status=policy.status,
                source_url=norm_url,
                confidence=0.85,
                is_verified=True,
                metadata={"declared_on_website": True, "platform": dlink.get("platform")},
            )
        )

    # Aggregate category counts
    counts: dict[str, int] = {}
    for item in footprint_items:
        c_val = item.category.value
        counts[c_val] = counts.get(c_val, 0) + 1

    return ExternalFootprintProfile(
        organisation_number=org,
        company_name=name,
        items=footprint_items,
        category_counts=counts,
        total_items=len(footprint_items),
        rejected_items=rejected_items,
    )
