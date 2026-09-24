"""Stage 15: Identity & Evidence Hardening.

Provides an authoritative, zero-hallucination identity and evidence verification layer:
1. Strict Organisation-Number Matching: Distinguishes requested vs discovered vs source org numbers;
   enforces definitive mismatch rejection without fuzzy override.
2. Robust Company-Name Matching: Comprehensive normalization, legal suffix disambiguation,
   and explicit match categorization (exact, normalized, suffix variation, conflict).
3. Domain & Entity Matching: Canonical hostname normalization and 4-tier domain status
   (VERIFIED, STRONGLY_SUPPORTED, WEAKLY_SUPPORTED, REJECTED).
4. Centralized Source -> Company Validation: Unified validation pipeline
   SOURCE -> SOURCE IDENTITY -> TARGET COMPANY IDENTITY -> IDENTITY MATCH -> ACCEPT / REJECT.
5. Evidence Completeness & Provenance: Structured provenance containing fact, source, target org,
   identity match, confidence, and validation status.
6. Financial Value Safeguards: Scope verification (standalone company vs corporate group),
   boundary-checked org number matching, currency and unit integrity.
7. Explicit Wrong-Company Rejection: Typed rejection records with target and source org details.
8. Lightweight Contradiction Detection: Identifies conflicting facts, resolves via source authority,
   or marks uncertain if unresolvable.
9. 4-Tier Evidence Status Model: VERIFIED, SUPPORTED, UNCERTAIN, REJECTED.
10. Final Fact Acceptance Gate: Intercepts raw facts before entry into trusted company profiles.
11. Structured Observability Logging: Emits machine-parsable identity and evidence audit events.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import re
from typing import Any
import unicodedata
import urllib.parse

from .identity_engine import (
    COMMON_ORG_PREFIXES,
    COMMON_ORG_SUFFIXES,
    LEGAL_FORM_SUFFIXES,
    canonicalize_org_number,
    is_valid_org_mod11,
    normalize_legal_name,
    validate_org_number,
)

logger = logging.getLogger("orgtrace.identity_hardening")


# ============================================================================
# 1. 4-TIER EVIDENCE STATUS MODEL
# ============================================================================

class EvidenceValidationStatus(str, Enum):
    """Deterministic evidence status model for Stage 15."""
    VERIFIED = "verified"       # Strong identity + authoritative source + sufficient evidence
    SUPPORTED = "supported"     # Reasonable evidence, plausible identity, but not statutory
    UNCERTAIN = "uncertain"     # Incomplete evidence, weak match, or unresolvable conflict
    REJECTED = "rejected"       # Direct identity conflict, wrong company, or disallowed source


class DomainValidationStatus(str, Enum):
    """Domain to company association confidence."""
    VERIFIED = "verified"                   # Exact org number on site or official BRREG registered domain
    STRONGLY_SUPPORTED = "strongly_supported" # Legal name match + substantive corporate content
    WEAKLY_SUPPORTED = "weakly_supported"   # Distinctive token overlap or plausible name derivation
    REJECTED = "rejected"                   # Parked domain, wrong entity, or conflicting domain


class NameMatchStatus(str, Enum):
    """Categorized company name matching outcome."""
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    LEGAL_SUFFIX_VARIATION = "legal_suffix_variation"
    LEGAL_SUFFIX_OMITTED = "legal_suffix_omitted"
    PARTIAL_OVERLAP = "partial_overlap"
    LEGAL_FORM_CONFLICT = "legal_form_conflict"
    CONFLICTING = "conflicting"


# ============================================================================
# 2. STRUCTURED OBSERVABILITY LOGGING
# ============================================================================

def log_identity_event(event_type: str, message: str, **context: Any) -> None:
    """Emit structured identity lifecycle logs for observability."""
    ctx_str = " ".join(f"{k}={v!r}" for k, v in sorted(context.items()))
    log_msg = f"[{event_type}] {message} | {ctx_str}" if ctx_str else f"[{event_type}] {message}"
    if event_type in {"SOURCE_REJECTED", "IDENTITY_MISMATCH", "CONTRADICTION_DETECTED"}:
        logger.warning(log_msg)
    else:
        logger.info(log_msg)


# ============================================================================
# 3. ORGANISATION-NUMBER MATCHING (SECTION 2)
# ============================================================================

@dataclass(frozen=True)
class OrgNumberComparison:
    """Rigorous comparison between requested, discovered, and source organisation numbers."""
    requested_org: str | None
    source_org: str | None
    discovered_org: str | None
    is_match: bool
    is_conflict: bool
    status: str  # "match", "mismatch", "missing_source", "missing_target"
    confidence: str  # "verified", "rejected", "uncertain"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_org_numbers(
    requested: Any,
    source: Any,
    *,
    discovered: Any = None,
) -> OrgNumberComparison:
    """Compare requested vs source organisation numbers with strict mismatch rejection.

    A mismatch between non-empty requested and source numbers is a FATAL identity rejection.
    No name similarity or secondary signal may override this conflict.
    """
    req_canon = canonicalize_org_number(requested)
    src_canon = canonicalize_org_number(source)
    disc_canon = canonicalize_org_number(discovered) if discovered else None

    # Case 1: Both present and match exactly
    if req_canon and src_canon:
        if req_canon == src_canon:
            log_identity_event(
                "IDENTITY_MATCH",
                "Authoritative organisation number matches exactly",
                target_org=req_canon,
                source_org=src_canon,
            )
            return OrgNumberComparison(
                requested_org=req_canon,
                source_org=src_canon,
                discovered_org=disc_canon,
                is_match=True,
                is_conflict=False,
                status="match",
                confidence="verified",
                reason=f"Authoritative organisation number {req_canon} matches source exactly",
            )
        else:
            # Fatal mismatch
            log_identity_event(
                "IDENTITY_MISMATCH",
                "Organisation numbers conflict definitively",
                target_org=req_canon,
                source_org=src_canon,
            )
            return OrgNumberComparison(
                requested_org=req_canon,
                source_org=src_canon,
                discovered_org=disc_canon,
                is_match=False,
                is_conflict=True,
                status="mismatch",
                confidence="rejected",
                reason=f"Organisation number mismatch: target {req_canon} != source {src_canon}",
            )

    # Case 2: Source org missing
    if req_canon and not src_canon:
        return OrgNumberComparison(
            requested_org=req_canon,
            source_org=None,
            discovered_org=disc_canon,
            is_match=False,
            is_conflict=False,
            status="missing_source",
            confidence="uncertain",
            reason="Source does not provide an authoritative organisation number",
        )

    # Case 3: Target org missing
    if not req_canon and src_canon:
        return OrgNumberComparison(
            requested_org=None,
            source_org=src_canon,
            discovered_org=disc_canon,
            is_match=False,
            is_conflict=False,
            status="missing_target",
            confidence="uncertain",
            reason="Target company lacks a canonical organisation number for comparison",
        )

    # Case 4: Both missing
    return OrgNumberComparison(
        requested_org=None,
        source_org=None,
        discovered_org=disc_canon,
        is_match=False,
        is_conflict=False,
        status="both_missing",
        confidence="uncertain",
        reason="Neither target nor source provides an organisation number",
    )


# ============================================================================
# 4. COMPANY-NAME MATCHING (SECTION 3)
# ============================================================================

@dataclass(frozen=True)
class NameComparisonResult:
    """Explicit company name matching result with similarity metrics."""
    target_name: str
    source_name: str
    normalized_target: str
    normalized_source: str
    exact_name_match: bool
    normalized_name_match: bool
    fuzzy_name_similarity: float
    name_match_status: NameMatchStatus
    target_legal_form: str | None
    source_legal_form: str | None
    is_acceptable_match: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["name_match_status"] = self.name_match_status.value
        return data


def robust_normalize_company_name(name: str | None) -> str:
    """Normalize company name handling case, whitespace, punctuation, '&' vs 'og', and Norwegian vowels."""
    raw = str(name or "").strip()
    if not raw:
        return ""

    # Replace ampersands with Norwegian conjunction 'og'
    text = re.sub(r"\s*&\s*", " og ", raw)

    # Map Norwegian specific letters
    text = text.translate(str.maketrans({
        "ø": "o", "Ø": "O",
        "å": "a", "Å": "A",
        "æ": "ae", "Æ": "AE",
    }))

    # Unicode NFKD decomposition
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()

    # Transliterate classical Norwegian digraph 'aa' -> 'a' (representing 'å')
    text = re.sub(r"(?i)aa", "a", text)

    # Replace non-alphanumeric with spaces
    text = re.sub(r"[^\w\s]", " ", text)

    # Collapse multiple whitespaces and lowercase
    return " ".join(text.casefold().split())


def _extract_suffix(name: str) -> tuple[str, str | None]:
    """Extract canonical legal form suffix from raw name."""
    clean = re.sub(r"[,\.]+$", "", name.strip())
    for suffix, canonical in sorted(LEGAL_FORM_SUFFIXES.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = rf"(?:^|\s+|[,/\-])({re.escape(suffix)})\s*$"
        if re.search(pattern, clean, re.IGNORECASE):
            core = re.sub(pattern, "", clean, flags=re.IGNORECASE).strip()
            return core, canonical
    return clean, None


def compare_company_names(
    target_name: str | None,
    source_name: str | None,
) -> NameComparisonResult:
    """Compare two company names deterministically without allowing fuzzy similarity to mask conflicts."""
    t_raw = str(target_name or "").strip()
    s_raw = str(source_name or "").strip()

    if not t_raw or not s_raw:
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target="",
            normalized_source="",
            exact_name_match=False,
            normalized_name_match=False,
            fuzzy_name_similarity=0.0,
            name_match_status=NameMatchStatus.CONFLICTING,
            target_legal_form=None,
            source_legal_form=None,
            is_acceptable_match=False,
            reasons=["One or both company names are empty"],
        )

    # Exact string match
    if t_raw == s_raw:
        _, t_form = _extract_suffix(t_raw)
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target=robust_normalize_company_name(t_raw),
            normalized_source=robust_normalize_company_name(s_raw),
            exact_name_match=True,
            normalized_name_match=True,
            fuzzy_name_similarity=1.0,
            name_match_status=NameMatchStatus.EXACT,
            target_legal_form=t_form,
            source_legal_form=t_form,
            is_acceptable_match=True,
            reasons=["Exact identical name strings"],
        )

    t_norm = robust_normalize_company_name(t_raw)
    s_norm = robust_normalize_company_name(s_raw)

    t_core, t_form = _extract_suffix(t_raw)
    s_core, s_form = _extract_suffix(s_raw)

    t_core_norm = robust_normalize_company_name(t_core)
    s_core_norm = robust_normalize_company_name(s_core)

    # Sequence similarity ratio
    sim = round(difflib.SequenceMatcher(None, t_norm, s_norm).ratio(), 4)

    # Case: Exact normalized match
    if t_norm == s_norm:
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target=t_norm,
            normalized_source=s_norm,
            exact_name_match=False,
            normalized_name_match=True,
            fuzzy_name_similarity=1.0,
            name_match_status=NameMatchStatus.NORMALIZED_EXACT,
            target_legal_form=t_form,
            source_legal_form=s_form,
            is_acceptable_match=True,
            reasons=["Identical after casing, whitespace, punctuation, and Unicode normalization"],
        )

    # Core names identical
    if t_core_norm == s_core_norm:
        if t_form == s_form:
            return NameComparisonResult(
                target_name=t_raw,
                source_name=s_raw,
                normalized_target=t_norm,
                normalized_source=s_norm,
                exact_name_match=False,
                normalized_name_match=True,
                fuzzy_name_similarity=sim,
                name_match_status=NameMatchStatus.NORMALIZED_EXACT,
                target_legal_form=t_form,
                source_legal_form=s_form,
                is_acceptable_match=True,
                reasons=["Core company name matches with equivalent legal suffix"],
            )
        elif t_form and s_form and t_form != s_form:
            # Legal form conflict: e.g. AS vs ASA, AS vs ENK
            return NameComparisonResult(
                target_name=t_raw,
                source_name=s_raw,
                normalized_target=t_norm,
                normalized_source=s_norm,
                exact_name_match=False,
                normalized_name_match=False,
                fuzzy_name_similarity=sim,
                name_match_status=NameMatchStatus.LEGAL_FORM_CONFLICT,
                target_legal_form=t_form,
                source_legal_form=s_form,
                is_acceptable_match=False,
                reasons=[f"Legal form conflict: target is {t_form}, source is {s_form}"],
            )
        else:
            # Legal suffix omitted on one side
            return NameComparisonResult(
                target_name=t_raw,
                source_name=s_raw,
                normalized_target=t_norm,
                normalized_source=s_norm,
                exact_name_match=False,
                normalized_name_match=False,
                fuzzy_name_similarity=sim,
                name_match_status=NameMatchStatus.LEGAL_SUFFIX_OMITTED,
                target_legal_form=t_form,
                source_legal_form=s_form,
                is_acceptable_match=True,
                reasons=["Core company name matches exactly; legal suffix omitted on one side"],
            )

    # Token overlap analysis
    t_tokens = set(t_norm.split()) - set(LEGAL_FORM_SUFFIXES.keys())
    s_tokens = set(s_norm.split()) - set(LEGAL_FORM_SUFFIXES.keys())

    overlap = t_tokens & s_tokens
    if not overlap:
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target=t_norm,
            normalized_source=s_norm,
            exact_name_match=False,
            normalized_name_match=False,
            fuzzy_name_similarity=sim,
            name_match_status=NameMatchStatus.CONFLICTING,
            target_legal_form=t_form,
            source_legal_form=s_form,
            is_acceptable_match=False,
            reasons=["Company names share no distinctive tokens"],
        )

    # Words like "group", "holding", "norge" indicate corporate hierarchy differences
    differentiators = {"group", "gruppen", "holding", "invest", "eiendom", "norge", "norway", "nordic", "international"}
    t_diff = t_tokens & differentiators
    s_diff = s_tokens & differentiators

    if t_diff != s_diff:
        # e.g. "Example AS" vs "Example Group AS"
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target=t_norm,
            normalized_source=s_norm,
            exact_name_match=False,
            normalized_name_match=False,
            fuzzy_name_similarity=sim,
            name_match_status=NameMatchStatus.PARTIAL_OVERLAP,
            target_legal_form=t_form,
            source_legal_form=s_form,
            is_acceptable_match=False,
            reasons=[f"Entity scope modifier conflict: target has {t_diff or 'none'}, source has {s_diff or 'none'}"],
        )

    if t_tokens == s_tokens:
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target=t_norm,
            normalized_source=s_norm,
            exact_name_match=False,
            normalized_name_match=True,
            fuzzy_name_similarity=sim,
            name_match_status=NameMatchStatus.NORMALIZED_EXACT,
            target_legal_form=t_form,
            source_legal_form=s_form,
            is_acceptable_match=True,
            reasons=["All distinctive core name tokens match"],
        )


    overlap = t_tokens & s_tokens
    if overlap:
        return NameComparisonResult(
            target_name=t_raw,
            source_name=s_raw,
            normalized_target=t_norm,
            normalized_source=s_norm,
            exact_name_match=False,
            normalized_name_match=False,
            fuzzy_name_similarity=sim,
            name_match_status=NameMatchStatus.PARTIAL_OVERLAP,
            target_legal_form=t_form,
            source_legal_form=s_form,
            is_acceptable_match=False,
            reasons=[f"Partial token overlap ({sorted(overlap)}), but core names differ ({sorted(t_tokens ^ s_tokens)})"],
        )

    return NameComparisonResult(
        target_name=t_raw,
        source_name=s_raw,
        normalized_target=t_norm,
        normalized_source=s_norm,
        exact_name_match=False,
        normalized_name_match=False,
        fuzzy_name_similarity=sim,
        name_match_status=NameMatchStatus.CONFLICTING,
        target_legal_form=t_form,
        source_legal_form=s_form,
        is_acceptable_match=False,
        reasons=["Company names share no distinctive tokens"],
    )


# ============================================================================
# 5. DOMAIN & ENTITY MATCHING (SECTION 4)
# ============================================================================

PARKED_DOMAIN_PATTERNS = (
    "domain is for sale",
    "domain for sale",
    "hugedomains",
    "parked at",
    "miss hosting",
    "buy this domain",
    "her flytter snart en ny gjest",
    "has been informing visitors",
    "find the best information and most relevant links",
)


def canonicalize_domain_hostname(raw_url_or_domain: str | None) -> str | None:
    """Normalize domain: remove protocol, www, port, paths, query, hash, and trailing dots."""
    val = str(raw_url_or_domain or "").strip().lower()
    if not val:
        return None
    if not re.match(r"^https?://", val):
        val = "https://" + val
    try:
        parsed = urllib.parse.urlparse(val)
        host = parsed.hostname
        if host:
            # Strip trailing dots and www
            clean = host.rstrip(".")
            return re.sub(r"^www\d*\.", "", clean)
    except Exception:
        pass
    return None


@dataclass(frozen=True)
class DomainEntityValidation:
    """Harded domain and website association outcome."""
    target_domain: str | None
    candidate_domain: str | None
    normalized_target_host: str | None
    normalized_candidate_host: str | None
    status: DomainValidationStatus
    is_publishable: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def validate_domain_entity(
    target_company: dict[str, Any],
    candidate_url: str | None,
    *,
    page_text: str | None = None,
    structured_data: dict[str, Any] | None = None,
) -> DomainEntityValidation:
    """Validate that candidate domain belongs to target company using multi-factor identity proof."""
    t_web = target_company.get("website")
    t_org = canonicalize_org_number(target_company.get("organisation_number"))
    t_name = str(target_company.get("name") or "").strip()

    t_host = canonicalize_domain_hostname(t_web)
    c_host = canonicalize_domain_hostname(candidate_url)

    if not c_host:
        return DomainEntityValidation(
            target_domain=t_web,
            candidate_domain=candidate_url,
            normalized_target_host=t_host,
            normalized_candidate_host=None,
            status=DomainValidationStatus.REJECTED,
            is_publishable=False,
            reasons=["Candidate domain is missing or unparseable"],
        )

    # 1. Parked Domain Check
    text_sample = str(page_text or "").casefold()
    if any(marker in text_sample for marker in PARKED_DOMAIN_PATTERNS):
        log_identity_event("SOURCE_REJECTED", "Domain is parked or for sale", domain=c_host)
        return DomainEntityValidation(
            target_domain=t_web,
            candidate_domain=candidate_url,
            normalized_target_host=t_host,
            normalized_candidate_host=c_host,
            status=DomainValidationStatus.REJECTED,
            is_publishable=False,
            reasons=["Captured domain page is a parked or for-sale placeholder"],
        )

    # 2. Exact Organisation Number on Page (The Gold Standard)
    if t_org:
        # Bounded 9-digit match (prevents boundary concatenation)
        org_pattern = rf"(?<!\d){re.escape(t_org[:3])}[\s\.]?{re.escape(t_org[3:6])}[\s\.]?{re.escape(t_org[6:])}(?!\d)"
        if re.search(org_pattern, text_sample):
            reasons = [f"Exact organisation number {t_org} verified on website page/footer"]
            return DomainEntityValidation(
                target_domain=t_web,
                candidate_domain=candidate_url,
                normalized_target_host=t_host,
                normalized_candidate_host=c_host,
                status=DomainValidationStatus.VERIFIED,
                is_publishable=True,
                reasons=reasons,
            )

    # 3. Target Registered Domain Match in BRREG
    if t_host:
        if t_host == c_host:
            return DomainEntityValidation(
                target_domain=t_web,
                candidate_domain=candidate_url,
                normalized_target_host=t_host,
                normalized_candidate_host=c_host,
                status=DomainValidationStatus.VERIFIED,
                is_publishable=True,
                reasons=["Domain matches authoritative BRREG registered website exactly"],
            )

        # Subdomain match (e.g. shop.example.no vs example.no)
        if c_host.endswith("." + t_host) or t_host.endswith("." + c_host):
            return DomainEntityValidation(
                target_domain=t_web,
                candidate_domain=candidate_url,
                normalized_target_host=t_host,
                normalized_candidate_host=c_host,
                status=DomainValidationStatus.STRONGLY_SUPPORTED,
                is_publishable=True,
                reasons=[f"Subdomain relationship between {c_host} and registered domain {t_host}"],
            )

    # 4. Legal Name Corroboration
    name_tokens = robust_normalize_company_name(t_name).split()
    core_name_tokens = [tok for tok in name_tokens if tok not in LEGAL_FORM_SUFFIXES and len(tok) > 1]
    core_compact = "".join(core_name_tokens)
    c_host_compact = re.sub(r"[^a-z0-9]", "", c_host.split(".")[0])

    if core_name_tokens and all(tok in text_sample for tok in core_name_tokens):
        if len(text_sample) >= 80:  # Substantive content
            return DomainEntityValidation(
                target_domain=t_web,
                candidate_domain=candidate_url,
                normalized_target_host=t_host,
                normalized_candidate_host=c_host,
                status=DomainValidationStatus.STRONGLY_SUPPORTED,
                is_publishable=True,
                reasons=["Legal company name appears substantively on website"],
            )

    # 5. Name-derived domain (e.g. nordicsolutions.no)
    if core_compact and (core_compact == c_host_compact or c_host_compact.startswith(core_compact)):
        return DomainEntityValidation(
            target_domain=t_web,
            candidate_domain=candidate_url,
            normalized_target_host=t_host,
            normalized_candidate_host=c_host,
            status=DomainValidationStatus.WEAKLY_SUPPORTED,
            is_publishable=False,  # Requires further evidence before publishing
            reasons=["Domain name resembles legal name, but lacks explicit organisation number verification"],
        )

    # 6. Unrelated Domain
    return DomainEntityValidation(
        target_domain=t_web,
        candidate_domain=candidate_url,
        normalized_target_host=t_host,
        normalized_candidate_host=c_host,
        status=DomainValidationStatus.REJECTED,
        is_publishable=False,
        reasons=["Candidate domain shows no verifiable association with the target company"],
    )


# ============================================================================
# 6. SOURCE -> COMPANY VALIDATION & DECISION ENGINE (SECTIONS 5 & 12)
# ============================================================================

@dataclass
class SourceIdentity:
    """Identity attributes declared or extracted from a source."""
    source_url: str
    source_type: str  # "official_registry", "official_filing", "company_website", "secondary_directory", "news"
    organisation_number: str | None = None
    company_name: str | None = None
    domain: str | None = None
    entity_scope: str = "standalone"  # "standalone", "corporate_group", "subunit", "unknown"
    reporting_year: int | None = None
    raw_evidence_snippet: str | None = None
    retrieved_at: str | None = None


@dataclass(frozen=True)
class IdentityValidation:
    """Comprehensive identity verification verdict for a candidate source."""
    status: EvidenceValidationStatus
    organisation_number_match: bool
    name_match: bool
    domain_match: bool
    entity_scope_match: bool
    confidence: float
    target_org: str | None
    source_org: str | None
    rejection_reason: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def validate_source_identity(
    target_company: dict[str, Any],
    source: SourceIdentity | dict[str, Any],
) -> IdentityValidation:
    """Centralized, deterministic identity decision function for all pipeline stages.

    Validates whether the provided source belongs to the target company.
    """
    if isinstance(source, dict):
        source_obj = SourceIdentity(
            source_url=str(source.get("source_url") or ""),
            source_type=str(source.get("source_type") or "unknown"),
            organisation_number=source.get("organisation_number"),
            company_name=source.get("company_name") or source.get("name"),
            domain=source.get("domain") or source.get("source_url"),
            entity_scope=str(source.get("entity_scope") or "standalone"),
            reporting_year=source.get("reporting_year"),
            raw_evidence_snippet=source.get("raw_evidence_snippet") or source.get("evidence_span"),
            retrieved_at=source.get("retrieved_at"),
        )
    else:
        source_obj = source

    t_org = canonicalize_org_number(target_company.get("organisation_number"))
    t_name = str(target_company.get("name") or "").strip()
    s_org = canonicalize_org_number(source_obj.organisation_number)
    s_name = str(source_obj.company_name or "").strip()

    reasons: list[str] = []

    # 1. Official Registry Source (Self-verifying)
    if source_obj.source_type in {"official_registry", "official_filing", "official_registry_bulk"}:
        if t_org and s_org:
            if t_org != s_org:
                log_identity_event("SOURCE_REJECTED", "Registry source org mismatch", target=t_org, source=s_org)
                return IdentityValidation(
                    status=EvidenceValidationStatus.REJECTED,
                    organisation_number_match=False,
                    name_match=False,
                    domain_match=False,
                    entity_scope_match=False,
                    confidence=0.0,
                    target_org=t_org,
                    source_org=s_org,
                    rejection_reason="organisation_number_mismatch",
                    reasons=[f"Registry source org {s_org} conflicts with target org {t_org}"],
                )
            return IdentityValidation(
                status=EvidenceValidationStatus.VERIFIED,
                organisation_number_match=True,
                name_match=True,
                domain_match=True,
                entity_scope_match=True,
                confidence=1.0,
                target_org=t_org,
                source_org=s_org,
                reasons=["Authoritative statutory registry record"],
            )

    # 2. Check Organisation Number Matching
    org_comp = compare_org_numbers(t_org, s_org)
    if org_comp.is_conflict:
        # Fatal rejection
        log_identity_event("SOURCE_REJECTED", org_comp.reason, target=t_org, source=s_org)
        return IdentityValidation(
            status=EvidenceValidationStatus.REJECTED,
            organisation_number_match=False,
            name_match=False,
            domain_match=False,
            entity_scope_match=False,
            confidence=0.0,
            target_org=t_org,
            source_org=s_org,
            rejection_reason="organisation_number_mismatch",
            reasons=[org_comp.reason],
        )

    # 3. Check Company Name Matching
    name_comp = compare_company_names(t_name, s_name) if t_name and s_name else None
    name_matched = bool(name_comp and name_comp.is_acceptable_match)

    # 4. Check Domain Matching if URL provided
    domain_val = validate_domain_entity(target_company, source_obj.source_url, page_text=source_obj.raw_evidence_snippet)

    # 5. Entity Scope Check (Standalone vs Corporate Group)
    entity_scope_ok = True
    if source_obj.entity_scope == "corporate_group" and not target_company.get("is_in_group"):
        entity_scope_ok = False
        reasons.append("Source contains consolidated group data, but target is standalone entity")

    # 6. Synthesize Final Status
    if org_comp.is_match:
        # Organisation numbers match definitively
        if entity_scope_ok:
            reasons.append("Exact organisation number verified")
            return IdentityValidation(
                status=EvidenceValidationStatus.VERIFIED,
                organisation_number_match=True,
                name_match=name_matched,
                domain_match=domain_val.is_publishable,
                entity_scope_match=True,
                confidence=1.0,
                target_org=t_org,
                source_org=s_org,
                reasons=reasons,
            )
        else:
            return IdentityValidation(
                status=EvidenceValidationStatus.UNCERTAIN,
                organisation_number_match=True,
                name_match=name_matched,
                domain_match=domain_val.is_publishable,
                entity_scope_match=False,
                confidence=0.5,
                target_org=t_org,
                source_org=s_org,
                rejection_reason="entity_scope_mismatch",
                reasons=reasons,
            )

    # No source org number: evaluate name + domain depending on source type
    is_first_party_web = source_obj.source_type in {"company_website", "first_party_website"}

    if is_first_party_web:
        if domain_val.status == DomainValidationStatus.VERIFIED:
            return IdentityValidation(
                status=EvidenceValidationStatus.VERIFIED,
                organisation_number_match=False,
                name_match=name_matched,
                domain_match=True,
                entity_scope_match=entity_scope_ok,
                confidence=0.95,
                target_org=t_org,
                source_org=s_org,
                reasons=domain_val.reasons,
            )
        if domain_val.status == DomainValidationStatus.STRONGLY_SUPPORTED and name_matched:
            return IdentityValidation(
                status=EvidenceValidationStatus.SUPPORTED,
                organisation_number_match=False,
                name_match=True,
                domain_match=True,
                entity_scope_match=entity_scope_ok,
                confidence=0.80,
                target_org=t_org,
                source_org=s_org,
                reasons=domain_val.reasons + (name_comp.reasons if name_comp else []),
            )
        if domain_val.status == DomainValidationStatus.REJECTED:
            return IdentityValidation(
                status=EvidenceValidationStatus.REJECTED,
                organisation_number_match=False,
                name_match=False,
                domain_match=False,
                entity_scope_match=False,
                confidence=0.0,
                target_org=t_org,
                source_org=s_org,
                rejection_reason="unrelated_entity_or_domain",
                reasons=["Company website domain conflicts with target company identity"],
            )

    # Secondary, news, directory sources (where the domain is an external host, e.g. proff.no, e24.no)
    if name_matched:
        return IdentityValidation(
            status=EvidenceValidationStatus.UNCERTAIN,
            organisation_number_match=False,
            name_match=True,
            domain_match=False,
            entity_scope_match=entity_scope_ok,
            confidence=0.50,
            target_org=t_org,
            source_org=s_org,
            rejection_reason="insufficient_identity_evidence",
            reasons=["Secondary source names target company but lacks definitive organisation number proof"],
        )

    if name_comp and not name_comp.is_acceptable_match and name_comp.name_match_status == NameMatchStatus.CONFLICTING:
        return IdentityValidation(
            status=EvidenceValidationStatus.REJECTED,
            organisation_number_match=False,
            name_match=False,
            domain_match=False,
            entity_scope_match=False,
            confidence=0.0,
            target_org=t_org,
            source_org=s_org,
            rejection_reason="conflicting_company_name",
            reasons=["Source company name conflicts with target company name"],
        )

    # Ambiguous or incomplete
    return IdentityValidation(
        status=EvidenceValidationStatus.UNCERTAIN,
        organisation_number_match=False,
        name_match=name_matched,
        domain_match=False,
        entity_scope_match=entity_scope_ok,
        confidence=0.40,
        target_org=t_org,
        source_org=s_org,
        rejection_reason="insufficient_identity_evidence",
        reasons=["Source lacks definitive organisation number or strong domain corroboration"],
    )



# ============================================================================
# 7. FINANCIAL-VALUE SAFEGUARDS (SECTION 8)
# ============================================================================

SUPPORTED_CURRENCIES = {"NOK", "EUR", "USD", "SEK", "DKK", "GBP"}


@dataclass(frozen=True)
class FinancialValidationResult:
    """Rigorous audit result for an extracted financial fact."""
    is_valid: bool
    status: EvidenceValidationStatus
    metric_name: str
    amount: float | int | None
    currency: str
    reporting_year: int | None
    account_type: str  # "SELSKAP" vs "KONSERN"
    rejection_reason: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def validate_financial_fact(
    target_company: dict[str, Any],
    metric_name: str,
    amount: Any,
    *,
    currency: str = "NOK",
    reporting_year: int | None = None,
    account_type: str = "SELSKAP",
    source_org: str | None = None,
    document_text: str | None = None,
) -> FinancialValidationResult:
    """Harden financial facts against cross-entity leakage, group vs company mixing, and boundary errors."""
    t_org = canonicalize_org_number(target_company.get("organisation_number"))
    s_org = canonicalize_org_number(source_org) if source_org else None

    # 1. Exact Organisation Number Match
    if s_org and t_org and s_org != t_org:
        log_identity_event(
            "SOURCE_REJECTED",
            "Financial statement belongs to different organisation number",
            target=t_org,
            source=s_org,
        )
        return FinancialValidationResult(
            is_valid=False,
            status=EvidenceValidationStatus.REJECTED,
            metric_name=metric_name,
            amount=amount,
            currency=currency,
            reporting_year=reporting_year,
            account_type=account_type,
            rejection_reason="organisation_number_mismatch",
            reasons=[f"Financial record organisation {s_org} conflicts with target {t_org}"],
        )

    # 2. Bound-Checked Document Search (Fixing Digit Concatenation Vulnerability)
    if document_text and t_org:
        org_pattern = rf"(?<!\d){re.escape(t_org[:3])}[\s\.]?{re.escape(t_org[3:6])}[\s\.]?{re.escape(t_org[6:])}(?!\d)"
        if not re.search(org_pattern, document_text):
            log_identity_event("SOURCE_REJECTED", "Financial filing does not contain bounded target org number", target=t_org)
            return FinancialValidationResult(
                is_valid=False,
                status=EvidenceValidationStatus.REJECTED,
                metric_name=metric_name,
                amount=amount,
                currency=currency,
                reporting_year=reporting_year,
                account_type=account_type,
                rejection_reason="organisation_number_not_in_filing",
                reasons=["Financial document does not contain the target 9-digit organisation number"],
            )

    # 3. Account Type Scope (Standalone vs Group)
    if account_type.upper() == "KONSERN":
        # Group accounts must not be presented as standalone company accounts
        log_identity_event("FINANCIAL_SCOPE_MISMATCH", "Consolidated group accounts cannot substitute standalone accounts")
        return FinancialValidationResult(
            is_valid=False,
            status=EvidenceValidationStatus.UNCERTAIN,
            metric_name=metric_name,
            amount=amount,
            currency=currency,
            reporting_year=reporting_year,
            account_type=account_type,
            rejection_reason="consolidated_group_scope",
            reasons=["Consolidated group figures (KONSERN) cannot be attributed to standalone entity accounts"],
        )

    # 4. Currency and Unit Validation
    curr_clean = str(currency or "").strip().upper()
    if curr_clean not in SUPPORTED_CURRENCIES:
        return FinancialValidationResult(
            is_valid=False,
            status=EvidenceValidationStatus.UNCERTAIN,
            metric_name=metric_name,
            amount=amount,
            currency=curr_clean or "UNKNOWN",
            reporting_year=reporting_year,
            account_type=account_type,
            rejection_reason="unsupported_currency",
            reasons=[f"Financial currency {curr_clean!r} is unrecognized or missing"],
        )

    # 5. Numeric Amount Verification
    if amount is None or isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return FinancialValidationResult(
            is_valid=False,
            status=EvidenceValidationStatus.UNCERTAIN,
            metric_name=metric_name,
            amount=None,
            currency=curr_clean,
            reporting_year=reporting_year,
            account_type=account_type,
            rejection_reason="non_numeric_amount",
            reasons=["Financial amount is missing or not a valid number"],
        )

    return FinancialValidationResult(
        is_valid=True,
        status=EvidenceValidationStatus.VERIFIED,
        metric_name=metric_name,
        amount=amount,
        currency=curr_clean,
        reporting_year=reporting_year,
        account_type=account_type,
        reasons=["Financial fact passed all identity, scope, currency, and numerical integrity gates"],
    )


# ============================================================================
# 8. CONTRADICTION HANDLING (SECTION 10)
# ============================================================================

class SourceAuthority(int, Enum):
    OFFICIAL_REGISTRY = 100
    OFFICIAL_FILING = 90
    FIRST_PARTY_STRUCTURED = 85
    FIRST_PARTY_WEBSITE = 80
    REPUTABLE_SECONDARY = 50
    UNVERIFIED = 10


@dataclass(frozen=True)
class ContradictionRecord:
    """Documented divergence or conflict between two sources."""
    field_name: str
    conflict_type: str  # "value_divergence", "authority_override", "unresolvable_conflict"
    source_a_url: str
    source_a_value: Any
    source_a_authority: int
    source_b_url: str
    source_b_value: Any
    source_b_authority: int
    resolution_status: str  # "resolved", "uncertain"
    preferred_value: Any
    preferred_source_url: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_and_resolve_contradiction(
    field_name: str,
    record_a: dict[str, Any],
    record_b: dict[str, Any],
) -> ContradictionRecord | None:
    """Detect conflicts between two observations and apply deterministic source authority."""
    val_a = record_a.get("value")
    val_b = record_b.get("value")

    # If identical values or one is missing, no contradiction
    if val_a == val_b or val_a is None or val_b is None:
        return None

    auth_a = int(record_a.get("source_priority") or SourceAuthority.UNVERIFIED.value)
    auth_b = int(record_b.get("source_priority") or SourceAuthority.UNVERIFIED.value)

    url_a = str(record_a.get("source_url") or "")
    url_b = str(record_b.get("source_url") or "")

    log_identity_event(
        "CONTRADICTION_DETECTED",
        f"Contradiction on field {field_name}",
        val_a=val_a,
        auth_a=auth_a,
        val_b=val_b,
        auth_b=auth_b,
    )

    if auth_a > auth_b:
        return ContradictionRecord(
            field_name=field_name,
            conflict_type="authority_override",
            source_a_url=url_a,
            source_a_value=val_a,
            source_a_authority=auth_a,
            source_b_url=url_b,
            source_b_value=val_b,
            source_b_authority=auth_b,
            resolution_status="resolved",
            preferred_value=val_a,
            preferred_source_url=url_a,
            reason=f"Authoritative source ({auth_a}) takes precedence over secondary source ({auth_b})",
        )
    elif auth_b > auth_a:
        return ContradictionRecord(
            field_name=field_name,
            conflict_type="authority_override",
            source_a_url=url_a,
            source_a_value=val_a,
            source_a_authority=auth_a,
            source_b_url=url_b,
            source_b_value=val_b,
            source_b_authority=auth_b,
            resolution_status="resolved",
            preferred_value=val_b,
            preferred_source_url=url_b,
            reason=f"Authoritative source ({auth_b}) takes precedence over secondary source ({auth_a})",
        )
    else:
        # Equal authority conflict -> Cannot safely guess; mark uncertain
        return ContradictionRecord(
            field_name=field_name,
            conflict_type="unresolvable_conflict",
            source_a_url=url_a,
            source_a_value=val_a,
            source_a_authority=auth_a,
            source_b_url=url_b,
            source_b_value=val_b,
            source_b_authority=auth_b,
            resolution_status="uncertain",
            preferred_value=None,
            preferred_source_url=None,
            reason="Contradictory values from equally authoritative sources; marked uncertain without guessing",
        )


# ============================================================================
# 9. FINAL FACT ACCEPTANCE GATE (SECTION 13)
# ============================================================================

class FactAcceptanceDecision(str, Enum):
    ACCEPT = "accept"
    UNCERTAIN = "uncertain"
    REJECT = "reject"


@dataclass(frozen=True)
class FactAcceptanceVerdict:
    """Final gate decision for a fact entering the trusted company profile."""
    decision: FactAcceptanceDecision
    field_name: str
    value: Any
    validation_status: EvidenceValidationStatus
    confidence: float
    rejection_reason: str | None = None
    contradiction: ContradictionRecord | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        data["validation_status"] = self.validation_status.value
        if self.contradiction:
            data["contradiction"] = self.contradiction.to_dict()
        return data


def evaluate_fact_acceptance(
    target_company: dict[str, Any],
    field_name: str,
    fact_value: Any,
    source_identity: SourceIdentity | dict[str, Any],
    *,
    prior_fact: dict[str, Any] | None = None,
    financial_metadata: dict[str, Any] | None = None,
) -> FactAcceptanceVerdict:
    """Execute the complete Stage 15 acceptance gate on an incoming fact."""
    # Step 1: Validate Source Identity
    ident_val = validate_source_identity(target_company, source_identity)

    # If identity is REJECTED, fact is unconditionally REJECTED
    if ident_val.status == EvidenceValidationStatus.REJECTED:
        log_identity_event(
            "EVIDENCE_REJECTED",
            f"Fact rejected for field {field_name}",
            reason=ident_val.rejection_reason,
        )
        return FactAcceptanceVerdict(
            decision=FactAcceptanceDecision.REJECT,
            field_name=field_name,
            value=None,
            validation_status=EvidenceValidationStatus.REJECTED,
            confidence=0.0,
            rejection_reason=ident_val.rejection_reason,
            reasons=ident_val.reasons,
        )

    # Step 2: Financial Fact Specific Safeguards
    if financial_metadata:
        fin_val = validate_financial_fact(
            target_company,
            field_name,
            fact_value,
            currency=financial_metadata.get("currency", "NOK"),
            reporting_year=financial_metadata.get("reporting_year"),
            account_type=financial_metadata.get("account_type", "SELSKAP"),
            source_org=financial_metadata.get("source_org"),
            document_text=financial_metadata.get("document_text"),
        )
        if fin_val.status == EvidenceValidationStatus.REJECTED:
            return FactAcceptanceVerdict(
                decision=FactAcceptanceDecision.REJECT,
                field_name=field_name,
                value=None,
                validation_status=EvidenceValidationStatus.REJECTED,
                confidence=0.0,
                rejection_reason=fin_val.rejection_reason,
                reasons=fin_val.reasons,
            )
        elif fin_val.status == EvidenceValidationStatus.UNCERTAIN:
            return FactAcceptanceVerdict(
                decision=FactAcceptanceDecision.UNCERTAIN,
                field_name=field_name,
                value=fact_value,
                validation_status=EvidenceValidationStatus.UNCERTAIN,
                confidence=0.5,
                rejection_reason=fin_val.rejection_reason,
                reasons=fin_val.reasons,
            )

    # Step 3: Contradiction Check against prior observation if present
    contradiction: ContradictionRecord | None = None
    if prior_fact and prior_fact.get("value") is not None:
        curr_fact_dict = {
            "value": fact_value,
            "source_url": getattr(source_identity, "source_url", "") if hasattr(source_identity, "source_url") else source_identity.get("source_url", ""),
            "source_priority": SourceAuthority.OFFICIAL_REGISTRY.value if ident_val.status == EvidenceValidationStatus.VERIFIED else SourceAuthority.REPUTABLE_SECONDARY.value,
        }
        contradiction = detect_and_resolve_contradiction(field_name, prior_fact, curr_fact_dict)
        if contradiction and contradiction.resolution_status == "uncertain":
            log_identity_event("EVIDENCE_UNCERTAIN", f"Unresolvable contradiction on {field_name}")
            return FactAcceptanceVerdict(
                decision=FactAcceptanceDecision.UNCERTAIN,
                field_name=field_name,
                value=fact_value,
                validation_status=EvidenceValidationStatus.UNCERTAIN,
                confidence=0.5,
                contradiction=contradiction,
                reasons=[contradiction.reason],
            )

    # Step 4: Map status to decision
    if ident_val.status == EvidenceValidationStatus.VERIFIED:
        log_identity_event("EVIDENCE_ACCEPTED", f"Verified fact accepted for {field_name}")
        return FactAcceptanceVerdict(
            decision=FactAcceptanceDecision.ACCEPT,
            field_name=field_name,
            value=fact_value,
            validation_status=EvidenceValidationStatus.VERIFIED,
            confidence=ident_val.confidence,
            contradiction=contradiction,
            reasons=ident_val.reasons,
        )
    elif ident_val.status == EvidenceValidationStatus.SUPPORTED:
        log_identity_event("EVIDENCE_ACCEPTED", f"Supported fact accepted for {field_name}")
        return FactAcceptanceVerdict(
            decision=FactAcceptanceDecision.ACCEPT,
            field_name=field_name,
            value=fact_value,
            validation_status=EvidenceValidationStatus.SUPPORTED,
            confidence=ident_val.confidence,
            contradiction=contradiction,
            reasons=ident_val.reasons,
        )
    else:
        log_identity_event("EVIDENCE_UNCERTAIN", f"Fact marked uncertain for {field_name}")
        return FactAcceptanceVerdict(
            decision=FactAcceptanceDecision.UNCERTAIN,
            field_name=field_name,
            value=fact_value,
            validation_status=EvidenceValidationStatus.UNCERTAIN,
            confidence=ident_val.confidence,
            contradiction=contradiction,
            reasons=ident_val.reasons,
        )
