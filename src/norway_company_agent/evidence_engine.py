from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Generic, TypeVar

from .evidence import Evidence, utc_now
from .identity_engine import canonicalize_org_number, normalize_legal_name
from .profile_extraction import ExtractedField, FieldStatus
from .website import assert_public_url

T = TypeVar("T")

# ============================================================================
# 1. SOURCE AUTHORITY & HIERARCHY
# ============================================================================

class SourceAuthority(IntEnum):
    """Deterministic, 7-tier source authority hierarchy for Norwegian company intelligence."""
    GOVERNMENT_REGISTRY = 100        # BRREG Enhetsregisteret, Regnskapsregisteret official APIs
    OFFICIAL_FILING_COPY = 90       # Official Brønnøysund annual report PDF copies
    VERIFIED_FIRST_PARTY = 80       # Verified primary company website (/om-oss, /investor, /karriere)
    FIRST_PARTY_STRUCTURED = 75     # Verified first-party JSON-LD / schema.org markup
    REPUTABLE_SECONDARY = 50        # Verified news publishers, official partner registers
    SEARCH_DISCOVERY = 30           # Search candidate results (candidate-only, never published as ground truth)
    UNVERIFIED_THIRD_PARTY = 10     # Third-party aggregators, directories, parked pages (quarantined/rejected)


BLOCKED_AGGREGATOR_DOMAINS = {
    "proff.no", "purehelp.no", "ratsit.no", "180.no", "gulesider.no",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "yellowpages.com", "bizapedia.com",
}


def classify_source_authority(source_type: str, url: str | None = None) -> SourceAuthority:
    """Classify the authority level of an evidence source based on its type and URL."""
    s_type = (source_type or "").lower().strip()
    parsed_host = urllib.parse.urlparse(url or "").hostname or ""
    clean_host = parsed_host.lower().lstrip("www.")

    # Check blocked aggregators first
    if any(clean_host == b or clean_host.endswith(f".{b}") for b in BLOCKED_AGGREGATOR_DOMAINS):
        return SourceAuthority.UNVERIFIED_THIRD_PARTY

    # 1. Government / Official registry
    if (
        "official_registry" in s_type
        or "regnskapsregisteret" in s_type
        or "official_roles" in s_type
        or "official_subunits" in s_type
        or "official_group_structure" in s_type
        or "data.brreg.no" in (url or "")
    ):
        return SourceAuthority.GOVERNMENT_REGISTRY

    # 2. Official filing copy (Brønnøysund PDF)
    if (
        "official_annual_account_copy" in s_type
        or "official_brreg_copy" in s_type
        or "aarsregnskap/kopi" in (url or "")
    ):
        return SourceAuthority.OFFICIAL_FILING_COPY

    # 3. First-party structured data
    if "jsonld" in s_type or "schema.org" in s_type or "microdata" in s_type or "opengraph" in s_type:
        return SourceAuthority.FIRST_PARTY_STRUCTURED

    # 4. Verified first-party company website
    if (
        "website" in s_type
        or "company_website" in s_type
        or "about_page" in s_type
        or "homepage" in s_type
        or "careers_page" in s_type
        or "news_page" in s_type
        or "company_website_ir" in s_type
    ):
        return SourceAuthority.VERIFIED_FIRST_PARTY

    # 5. Search candidates
    if "search" in s_type or "candidate" in s_type:
        return SourceAuthority.SEARCH_DISCOVERY

    # 6. Reputable secondary
    if "secondary" in s_type or "news" in s_type:
        return SourceAuthority.REPUTABLE_SECONDARY

    return SourceAuthority.UNVERIFIED_THIRD_PARTY


def is_more_authoritative(source_a: SourceAuthority | str, source_b: SourceAuthority | str) -> bool:
    """Deterministically determine if source_a outranks source_b."""
    rank_a = source_a if isinstance(source_a, SourceAuthority) else classify_source_authority(str(source_a))
    rank_b = source_b if isinstance(source_b, SourceAuthority) else classify_source_authority(str(source_b))
    return int(rank_a) > int(rank_b)


def explain_authority_rank(source: SourceAuthority | str) -> str:
    """Return an explainable human-readable justification for the source authority rank."""
    auth = source if isinstance(source, SourceAuthority) else classify_source_authority(str(source))
    explanations = {
        SourceAuthority.GOVERNMENT_REGISTRY: "Authoritative government registry (Brønnøysundregistrene / Regnskapsregisteret); primary statutory ground truth.",
        SourceAuthority.OFFICIAL_FILING_COPY: "Official statutory annual account filing copy certified by Brønnøysundregistrene.",
        SourceAuthority.VERIFIED_FIRST_PARTY: "Verified first-party company website content (direct corporate disclosure).",
        SourceAuthority.FIRST_PARTY_STRUCTURED: "First-party structured metadata (JSON-LD / Schema.org) embedded on verified company site.",
        SourceAuthority.REPUTABLE_SECONDARY: "Verified secondary publisher or authorized registry partner.",
        SourceAuthority.SEARCH_DISCOVERY: "Search engine discovery result; candidate-only, must never be published as authoritative evidence.",
        SourceAuthority.UNVERIFIED_THIRD_PARTY: "Third-party aggregator, directory, or unverified source; quarantined or rejected.",
    }
    return explanations.get(auth, "Unknown authority tier.")


# ============================================================================
# 2. EXTRACTION METHODS & SELECTORS
# ============================================================================

class ExtractionMethod(str, Enum):
    """Controlled vocabulary of supported extraction methods."""
    REGISTRY_API = "registry_api"
    STRUCTURED_DATA_JSONLD = "structured_data_jsonld"
    STRUCTURED_DATA_MICRODATA = "structured_data_microdata"
    STRUCTURED_DATA_OPENGRAPH = "structured_data_opengraph"
    HTML_METADATA = "html_metadata"
    HTML_TEXT = "html_text"
    PDF_TEXT = "pdf_text"
    TABLE_COORDINATES = "table_coordinates"
    REGEX_RULE = "regex_rule"
    DETERMINISTIC_RULE = "deterministic_rule"
    FINANCIAL_STATEMENT = "financial_statement"


class SelectorType(str, Enum):
    """Supported evidence locator types."""
    CSS = "css"
    XPATH = "xpath"
    JSON_PATH = "json_path"
    TABLE_CELL = "table_cell"
    PDF_PAGE = "pdf_page"
    TEXT_SPAN = "text_span"
    LINE_SPAN = "line_span"


@dataclass
class EvidenceSelector:
    """Structured evidence locator identifying where inside a source a claim was derived."""
    selector_type: SelectorType
    query: str
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    line_number: int | None = None
    table_row: int | None = None
    table_col: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector_type": self.selector_type.value,
            "query": self.query,
            "page_number": self.page_number,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "line_number": self.line_number,
            "table_row": self.table_row,
            "table_col": self.table_col,
        }


# ============================================================================
# 3. CLAIM-LEVEL EVIDENCE & PROVENANCE MODEL
# ============================================================================

class ValidationStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ABSTAINED = "abstained"


@dataclass
class ProvenanceClaim(Generic[T]):
    """Traceable, evidence-backed claim representing an extracted company fact."""
    claim_id: str
    field_name: str
    value: T | None
    source_url: str
    discovered_url: str | None = None
    source_type: str = "unknown"
    source_authority: SourceAuthority = SourceAuthority.UNVERIFIED_THIRD_PARTY
    retrieved_at: str = field(default_factory=utc_now)
    effective_date: str | None = None
    reporting_date: str | None = None
    reporting_period: str | None = None
    content_sha256: str | None = None
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC_RULE
    selector: EvidenceSelector | None = None
    evidence_span: str | None = None
    confidence: float = 1.0
    validation_status: ValidationStatus = ValidationStatus.ACCEPTED
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "field_name": self.field_name,
            "value": self.value,
            "source_url": self.source_url,
            "discovered_url": self.discovered_url,
            "source_type": self.source_type,
            "source_authority": self.source_authority.value,
            "retrieved_at": self.retrieved_at,
            "effective_date": self.effective_date,
            "reporting_date": self.reporting_date,
            "reporting_period": self.reporting_period,
            "content_sha256": self.content_sha256,
            "extraction_method": self.extraction_method.value,
            "selector": self.selector.to_dict() if self.selector else None,
            "evidence_span": self.evidence_span,
            "confidence": round(self.confidence, 3),
            "validation_status": self.validation_status.value,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class ValidationVerdict:
    """Result of validating a claim against source evidence and entity identity."""
    claim_id: str
    status: ValidationStatus
    reasons: list[str] = field(default_factory=list)
    is_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "reasons": self.reasons,
            "is_valid": self.is_valid,
        }


# ============================================================================
# 4. CONTENT HASHING & SNAPSHOT VERIFICATION
# ============================================================================

def compute_content_hash(content: bytes | str) -> str:
    """Compute deterministic SHA-256 hash of source content."""
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    elif isinstance(content, bytes):
        content_bytes = content
    else:
        content_bytes = str(content).encode("utf-8")
    return hashlib.sha256(content_bytes).hexdigest()


def verify_snapshot_match(current_content: bytes | str, expected_hash: str) -> bool:
    """Verify if current content matches an expected SHA-256 snapshot hash."""
    if not expected_hash:
        return False
    current_hash = compute_content_hash(current_content)
    return current_hash.lower() == expected_hash.lower()


# ============================================================================
# 5. WRONG-SOURCE REJECTION & EVIDENCE VALIDATION PIPELINE
# ============================================================================

import ipaddress

def is_safe_public_url(url: str, check_dns: bool = False) -> tuple[bool, str | None]:
    """Validate that a URL is a valid public HTTP(S) URL and not targeting local or private IP ranges.

    Does not require live network DNS resolution unless check_dns=True.
    """
    if not url:
        return False, "Missing source URL"
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return False, f"Malformed URL: {exc}"

    if parsed.scheme not in {"http", "https"}:
        return False, f"Disallowed scheme '{parsed.scheme}' (only HTTP/HTTPS allowed)"

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False, "Missing hostname in URL"

    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False, "Local hosts are blocked"

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            return False, f"Private, loopback, or reserved IP address '{host}' is blocked"
    except ValueError:
        pass

    if check_dns:
        try:
            assert_public_url(url)
        except Exception as exc:
            return False, str(exc)

    return True, None


def validate_claim_evidence(
    claim: ProvenanceClaim,
    target_entity: dict[str, Any],
    source_content: bytes | str | None = None,
) -> ValidationVerdict:
    """Validate claim provenance against entity identity, source safety, and content evidence.

    Fails closed: strictly rejects claims from wrong companies, parent/subsidiary conflation,
    third-party aggregators, search snippets, or unsafe/invalid URLs.
    """
    reasons: list[str] = []
    target_org = canonicalize_org_number(str(target_entity.get("organisation_number") or ""))
    target_name = normalize_legal_name(str(target_entity.get("name") or ""))

    # 1. Source URL & SSRF Safety
    is_safe, url_err = is_safe_public_url(claim.source_url)
    if not is_safe:
        reasons.append(f"Unsafe or invalid source URL: {url_err}")

    # 2. Blocked Aggregators & Unauthoritative Sources
    if claim.source_authority == SourceAuthority.UNVERIFIED_THIRD_PARTY:
        reasons.append(f"Source authority tier is unverified third-party ({claim.source_type})")

    parsed_host = urllib.parse.urlparse(claim.source_url or "").hostname or ""
    clean_host = parsed_host.lower().lstrip("www.")
    if any(clean_host == b or clean_host.endswith(f".{b}") for b in BLOCKED_AGGREGATOR_DOMAINS):
        reasons.append(f"Source host '{clean_host}' is a third-party aggregator, directory, or social site")

    # 3. Search Discovery Snippet Protection
    if claim.source_authority == SourceAuthority.SEARCH_DISCOVERY:
        reasons.append("Search candidate snippets cannot be published as authoritative evidence")

    # 4. Exact-Entity Identity Verification & Wrong Company Rejection
    content_str = None
    if source_content is not None:
        content_str = source_content.decode("utf-8", errors="replace") if isinstance(source_content, bytes) else str(source_content)

    if content_str:
        # Check for conflicting 9-digit org numbers
        found_orgs = set(re.findall(r"\b\d{9}\b", content_str))
        if target_org and found_orgs and target_org not in found_orgs:
            # Source explicitly reports a different organization number
            reasons.append(f"Source content contains conflicting organization numbers {sorted(found_orgs)} (expected {target_org})")

        # Check for conflicting company legal name in document header/title
        header_snippet = content_str[:1000]
        if target_name and target_name not in normalize_legal_name(header_snippet):
            # Check if another legal entity name is prominently present
            comp_match = re.search(r"\b([A-ZÆØÅa-zæøå0-9\s\-]+)\s+(?:AS|ASA|ENK|ANS|DA)\b", header_snippet)
            if comp_match:
                other_name = normalize_legal_name(comp_match.group(0))
                if other_name and other_name != target_name and target_name not in other_name and other_name not in target_name:
                    reasons.append(f"Source prominently features different company '{other_name}' (expected '{target_name}')")

    # 5. Parent vs Subsidiary Conflation
    # If the source explicitly declares itself a group/konsern report, reject unless explicitly attributed
    if content_str and re.search(r"\b(?:konsernregnskap|group\s+accounts|morselskap)\b", content_str, re.I):
        if not re.search(r"\b(?:underenhet|datterselskap|subsidiary)\b", content_str, re.I) and target_org and target_org not in content_str:
            reasons.append("Source is a consolidated group/parent document that conflates subsidiary identity")

    # 6. Evidence Span Verification in Source
    if content_str and claim.evidence_span:
        clean_span = " ".join(claim.evidence_span.split())
        clean_content = " ".join(content_str.split())
        if clean_span not in clean_content and claim.evidence_span[:50] not in content_str:
            reasons.append(f"Evidence span '{claim.evidence_span[:60]}...' not found in source content")

    # 7. Content Hash Snapshot Verification
    if content_str and claim.content_sha256:
        actual_hash = compute_content_hash(content_str)
        if actual_hash.lower() != claim.content_sha256.lower():
            reasons.append(f"Source content hash mismatch: expected {claim.content_sha256[:12]}..., got {actual_hash[:12]}...")

    # 8. Claim Proportionality
    if (
        claim.value is not None
        and not claim.evidence_span
        and claim.source_authority != SourceAuthority.GOVERNMENT_REGISTRY
        and claim.field_name not in {"website", "final_url", "source_url", "url"}
    ):
        reasons.append("Claim asserts a substantive value without an evidence span")

    if reasons:
        claim.validation_status = ValidationStatus.REJECTED
        claim.rejection_reason = "; ".join(reasons)
        return ValidationVerdict(
            claim_id=claim.claim_id,
            status=ValidationStatus.REJECTED,
            reasons=reasons,
            is_valid=False,
        )

    claim.validation_status = ValidationStatus.ACCEPTED
    claim.rejection_reason = None
    return ValidationVerdict(
        claim_id=claim.claim_id,
        status=ValidationStatus.ACCEPTED,
        reasons=[],
        is_valid=True,
    )


# ============================================================================
# 6. INTEGRATION WITH STAGE 3 & STAGE 4
# ============================================================================

def build_provenance_claim(
    field: ExtractedField[T],
    target_entity: dict[str, Any],
    *,
    discovered_url: str | None = None,
    content_sha256: str | None = None,
    effective_date: str | None = None,
    reporting_date: str | None = None,
    reporting_period: str | None = None,
    extraction_method: ExtractionMethod | None = None,
    selector: EvidenceSelector | None = None,
) -> ProvenanceClaim[T]:
    """Convert an ExtractedField into an independently traceable ProvenanceClaim."""
    org = canonicalize_org_number(str(target_entity.get("organisation_number") or "")) or "unknown"
    source_url = field.source_url or "https://data.brreg.no/enhetsregisteret/api/enheter"
    source_type = field.source_type or "unknown"
    source_auth = classify_source_authority(source_type, source_url)

    # Infer extraction method if not explicitly provided
    if extraction_method is None:
        if "jsonld" in source_type:
            extraction_method = ExtractionMethod.STRUCTURED_DATA_JSONLD
        elif "registry" in source_type:
            extraction_method = ExtractionMethod.REGISTRY_API
        elif "pdf" in source_type:
            extraction_method = ExtractionMethod.PDF_TEXT
        elif "meta" in source_type:
            extraction_method = ExtractionMethod.HTML_METADATA
        elif "text" in source_type or "about" in source_type or "page" in source_type:
            extraction_method = ExtractionMethod.HTML_TEXT
        else:
            extraction_method = ExtractionMethod.DETERMINISTIC_RULE

    # Deterministic claim identifier
    raw_id = f"{org}|{field.field_name}|{field.value}|{source_url}|{extraction_method.value}"
    claim_id = "claim-" + hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:20]

    return ProvenanceClaim(
        claim_id=claim_id,
        field_name=field.field_name,
        value=field.value,
        source_url=source_url,
        discovered_url=discovered_url,
        source_type=source_type,
        source_authority=source_auth,
        effective_date=effective_date,
        reporting_date=reporting_date,
        reporting_period=reporting_period,
        content_sha256=content_sha256,
        extraction_method=extraction_method,
        selector=selector,
        evidence_span=field.evidence_span,
        confidence=field.confidence,
        validation_status=ValidationStatus.ACCEPTED if field.status == FieldStatus.FOUND else ValidationStatus.ABSTAINED,
        rejection_reason=field.note if field.status != FieldStatus.FOUND else None,
    )
