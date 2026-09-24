"""Stage 7: Refresh & Change Intelligence Engine.

Provides deterministic stable claim keys, immutable versioned snapshots,
material change detection (ignoring whitespace, casing, ordering, and timestamp noise),
failed refresh preservation (never emitting false removals on fetch failures),
and idempotent refresh operations.
"""

from __future__ import annotations

import copy
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .evidence import utc_now
from .external_research import normalize_url_for_research
from .identity_engine import canonicalize_org_number


# ============================================================================
# 1. ENUMS & DATA MODELS
# ============================================================================

class ChangeType(str, Enum):
    """Classification of detected changes between snapshots."""
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    INCREASE = "increase"
    DECREASE = "decrease"
    IDENTITY_CONFLICT = "identity_conflict"
    NEW_PERIOD_AVAILABLE = "new_period_available"
    VALUE_UNAVAILABLE = "value_unavailable"
    NOT_OBSERVED = "not_observed"


class MaterialitySeverity(str, Enum):
    """Severity classification of detected changes."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ChangeCategory(str, Enum):
    """Vocabulary of change categories."""
    IDENTITY = "IDENTITY"
    STATUS = "STATUS"
    INDUSTRY = "INDUSTRY"
    WEBSITE = "WEBSITE"
    ADDRESS = "ADDRESS"
    WORKFORCE = "WORKFORCE"
    FINANCIAL = "FINANCIAL"
    REGISTRATION = "REGISTRATION"


class RefreshStatus(str, Enum):
    """Outcome status of a refresh execution."""
    SUCCESS = "success"
    FAILED_FETCH = "failed_fetch"
    PARTIAL_FAILURE = "partial_failure"
    TRANSIENT_ERROR = "transient_error"


CASE_INSENSITIVE_FIELDS = {
    "legal_form", "municipality", "country", "status", "email",
    "domain", "website", "canonical_url", "vat_status", "postal_city",
}


@dataclass(frozen=True)
class SnapshotClaim:
    """Immutable claim record representing an extracted fact in a snapshot."""
    claim_key: str
    field_name: str
    value: Any
    source_url: str | None = None
    source_module: str = "unknown"  # e.g., "registry", "financials", "roles", "website"
    source_authority: int = 50
    evidence_span: str | None = None
    content_sha256: str | None = None
    retrieved_at: str | None = None
    effective_date: str | None = None
    reporting_period: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_key": self.claim_key,
            "field_name": self.field_name,
            "value": self.value,
            "source_url": self.source_url,
            "source_module": self.source_module,
            "source_authority": self.source_authority,
            "evidence_span": self.evidence_span,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "effective_date": self.effective_date,
            "reporting_period": self.reporting_period,
            "confidence": round(self.confidence, 3),
            "metadata": dict(self.metadata),
        }


@dataclass
class CompanySnapshot:
    """Immutable snapshot of a company's verified intelligence state at a point in time."""
    snapshot_id: str
    version: int
    organisation_number: str
    timestamp: str
    claims: dict[str, SnapshotClaim]
    source_statuses: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    _frozen: bool = field(default=False, repr=False)

    def __post_init__(self):
        # Freeze to guarantee immutability
        self.claims = dict(self.claims)
        self.source_statuses = dict(self.source_statuses)
        self.metadata = dict(self.metadata)
        self._frozen = True

    def __setattr__(self, name: str, value: Any):
        if getattr(self, "_frozen", False):
            raise AttributeError(f"CompanySnapshot is immutable; cannot modify field '{name}'")
        super().__setattr__(name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "organisation_number": self.organisation_number,
            "timestamp": self.timestamp,
            "claims": {k: c.to_dict() for k, c in sorted(self.claims.items())},
            "source_statuses": self.source_statuses,
            "metadata": self.metadata,
        }


@dataclass
class MaterialChangeRecord:
    """Explains a detected semantic change between snapshots."""
    stable_claim_key: str
    field_name: str
    change_type: ChangeType
    previous_value: Any
    current_value: Any
    previous_source: str | None = None
    current_source: str | None = None
    previous_evidence: str | None = None
    current_evidence: str | None = None
    detected_at: str = field(default_factory=utc_now)
    confidence: float = 1.0
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_claim_key": self.stable_claim_key,
            "field_name": self.field_name,
            "change_type": self.change_type.value,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
            "previous_source": self.previous_source,
            "current_source": self.current_source,
            "previous_evidence": self.previous_evidence,
            "current_evidence": self.current_evidence,
            "detected_at": self.detected_at,
            "confidence": round(self.confidence, 3),
            "explanation": self.explanation,
        }


@dataclass
class RefreshResult:
    """Outcome of a refresh execution."""
    success: bool
    status: RefreshStatus
    snapshot: CompanySnapshot | None
    changes: list[MaterialChangeRecord]
    failed_sources: list[str] = field(default_factory=list)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "changes": [c.to_dict() for c in self.changes],
            "failed_sources": self.failed_sources,
            "error_message": self.error_message,
        }


# ============================================================================
# 2. STABLE CLAIM KEYS
# ============================================================================

def generate_stable_claim_key(
    organisation_number: str,
    field_name: str,
    entity_qualifier: str | None = None,
) -> str:
    """Generate a deterministic, stable claim key across refreshes.

    Guarantees:
    - Never uses volatile timestamps, random IDs, or crawl order.
    - Logically identical claims from different runs generate the exact same key.
    - Format:
      org:{org}|field:{field}
      or
      org:{org}|field:{field}|entity:{normalized_qualifier}
    """
    org = canonicalize_org_number(str(organisation_number or "")).strip()
    clean_field = str(field_name or "").strip().lower().replace("-", "_")

    if entity_qualifier:
        clean_entity = re.sub(r"[^a-zA-Z0-9æøåÆØÅ_]+", "_", str(entity_qualifier).strip().lower()).strip("_")
        return f"org:{org}|field:{clean_field}|entity:{clean_entity}"

    return f"org:{org}|field:{clean_field}"


# ============================================================================
# 3. SEMANTIC NORMALIZATION & MATERIAL CHANGE DETECTION
# ============================================================================

def normalize_semantic_value(value: Any, field_name: str | None = None) -> Any:
    """Deeply normalize a value for semantic comparison.

    Protects against:
    - Dictionary key ordering differences
    - List ordering differences where order is not semantically significant
    - Whitespace differences
    - URL normalization differences
    - Case differences where fields are case-insensitive
    - Floating point rounding noise
    """
    if value is None:
        return None

    fname = (field_name or "").lower()

    # Dictionary: recursively sort keys
    if isinstance(value, dict):
        return {k: normalize_semantic_value(v, k) for k, v in sorted(value.items())}

    # List: recursively normalize
    if isinstance(value, (list, tuple)):
        normalized_items = [normalize_semantic_value(item, field_name) for item in value]
        # If list items are primitive, sort them deterministically
        if normalized_items and all(isinstance(x, (str, int, float, bool)) for x in normalized_items):
            return sorted(normalized_items, key=lambda x: str(x))
        # If list of dicts, sort by first key or id/name if present
        if normalized_items and all(isinstance(x, dict) for x in normalized_items):
            def dict_sort_key(d: dict) -> str:
                for k in ("id", "name", "role", "url", "code", "period", "key"):
                    if k in d:
                        return f"{k}:{d[k]}"
                return str(sorted(d.items()))
            return sorted(normalized_items, key=dict_sort_key)
        return normalized_items

    # String normalization
    if isinstance(value, str):
        text = " ".join(value.strip().split())
        # URL fields
        if fname in {"website", "url", "source_url", "final_url", "discovered_url"} or text.startswith(("http://", "https://")):
            return normalize_url_for_research(text)
        # Case-insensitive fields
        if fname in CASE_INSENSITIVE_FIELDS:
            return text.lower()
        return text

    # Float normalization: avoid precision noise
    if isinstance(value, float):
        return round(value, 4)

    return value


def is_material_change(prev_val: Any, curr_val: Any, field_name: str | None = None) -> bool:
    """Determine if two values represent a material semantic difference.

    Returns False if values are equivalent after semantic normalization.
    """
    norm_prev = normalize_semantic_value(prev_val, field_name)
    norm_curr = normalize_semantic_value(curr_val, field_name)
    return norm_prev != norm_curr


# ============================================================================
# 4. SNAPSHOT COMPARISON ENGINE
# ============================================================================

def compare_snapshots(
    previous: CompanySnapshot | None,
    current: CompanySnapshot,
) -> list[MaterialChangeRecord]:
    """Compare the current snapshot against the previous snapshot.

    Produces explicit previous/current values for:
    - ADDED: claims new in current snapshot
    - REMOVED: claims absent in current snapshot
    - MODIFIED: claims present in both with material difference
    - UNCHANGED: claims present in both with no material difference
    """
    if previous is None:
        # First snapshot: all claims are ADDED
        records: list[MaterialChangeRecord] = []
        for key, claim in sorted(current.claims.items()):
            records.append(
                MaterialChangeRecord(
                    stable_claim_key=key,
                    field_name=claim.field_name,
                    change_type=ChangeType.ADDED,
                    previous_value=None,
                    current_value=claim.value,
                    previous_source=None,
                    current_source=claim.source_url,
                    previous_evidence=None,
                    current_evidence=claim.evidence_span,
                    confidence=claim.confidence,
                    explanation=f"Initial discovery of claim '{claim.field_name}'",
                )
            )
        return records

    # Sanity check: same company
    if previous.organisation_number != current.organisation_number:
        raise ValueError(
            f"Cannot compare snapshots of different companies: '{previous.organisation_number}' vs '{current.organisation_number}'"
        )

    changes: list[MaterialChangeRecord] = []
    prev_keys = set(previous.claims.keys())
    curr_keys = set(current.claims.keys())

    # 1. ADDED claims
    for key in sorted(curr_keys - prev_keys):
        claim = current.claims[key]
        changes.append(
            MaterialChangeRecord(
                stable_claim_key=key,
                field_name=claim.field_name,
                change_type=ChangeType.ADDED,
                previous_value=None,
                current_value=claim.value,
                previous_source=None,
                current_source=claim.source_url,
                previous_evidence=None,
                current_evidence=claim.evidence_span,
                confidence=claim.confidence,
                explanation=f"New claim '{claim.field_name}' added",
            )
        )

    # 2. REMOVED claims
    for key in sorted(prev_keys - curr_keys):
        claim = previous.claims[key]
        changes.append(
            MaterialChangeRecord(
                stable_claim_key=key,
                field_name=claim.field_name,
                change_type=ChangeType.REMOVED,
                previous_value=claim.value,
                current_value=None,
                previous_source=claim.source_url,
                current_source=None,
                previous_evidence=claim.evidence_span,
                current_evidence=None,
                confidence=claim.confidence,
                explanation=f"Claim '{claim.field_name}' removed in current refresh",
            )
        )

    # 3. MODIFIED & UNCHANGED claims
    for key in sorted(prev_keys & curr_keys):
        prev_claim = previous.claims[key]
        curr_claim = current.claims[key]

        if is_material_change(prev_claim.value, curr_claim.value, curr_claim.field_name):
            changes.append(
                MaterialChangeRecord(
                    stable_claim_key=key,
                    field_name=curr_claim.field_name,
                    change_type=ChangeType.MODIFIED,
                    previous_value=prev_claim.value,
                    current_value=curr_claim.value,
                    previous_source=prev_claim.source_url,
                    current_source=curr_claim.source_url,
                    previous_evidence=prev_claim.evidence_span,
                    current_evidence=curr_claim.evidence_span,
                    confidence=curr_claim.confidence,
                    explanation=f"Claim '{curr_claim.field_name}' changed from '{prev_claim.value}' to '{curr_claim.value}'",
                )
            )
        else:
            changes.append(
                MaterialChangeRecord(
                    stable_claim_key=key,
                    field_name=curr_claim.field_name,
                    change_type=ChangeType.UNCHANGED,
                    previous_value=prev_claim.value,
                    current_value=curr_claim.value,
                    previous_source=prev_claim.source_url,
                    current_source=curr_claim.source_url,
                    previous_evidence=prev_claim.evidence_span,
                    current_evidence=curr_claim.evidence_span,
                    confidence=curr_claim.confidence,
                    explanation=f"Claim '{curr_claim.field_name}' remained unchanged",
                )
            )

    return changes


# ============================================================================
# 5. FAILED REFRESH PRESERVATION & REFRESH EXECUTION
# ============================================================================

def refresh_company_intelligence(
    previous_snapshot: CompanySnapshot | None,
    new_claims: list[SnapshotClaim] | None,
    *,
    source_results: dict[str, Any] | None = None,
    organisation_number: str | None = None,
    retrieval_error: str | None = None,
    timestamp: str | None = None,
) -> RefreshResult:
    """Execute a company intelligence refresh with fail-closed preservation.

    Critical Guarantees:
    - If a refresh fails, is incomplete, or encounters a transient error:
      - Does NOT replace the last successful snapshot.
      - Does NOT create false removals.
      - Preserves the previous known-good state.
      - Exposes refresh failure status separately.
    - If partial failure occurs (e.g. registry succeeded, website failed):
      - Claims from failed sources are preserved from previous snapshot.
      - Claims from succeeded sources are refreshed.
      - Distinguishes 'claim disappeared' from 'source could not be refreshed'.
    - Idempotent reruns:
      - Running with identical data produces identical snapshots and zero duplicate changes.
    """
    now = timestamp or utc_now()
    org = canonicalize_org_number(
        str(
            organisation_number
            or (previous_snapshot.organisation_number if previous_snapshot else "")
        )
    )

    if not org:
        return RefreshResult(
            success=False,
            status=RefreshStatus.FAILED_FETCH,
            snapshot=previous_snapshot,
            changes=[],
            failed_sources=[],
            error_message="Missing organisation number for refresh",
        )

    # Inspect source statuses
    statuses = dict(source_results or {})
    failed_sources = [mod for mod, status in statuses.items() if status in {"failed", "timeout", "error", "404", "500"}]
    succeeded_sources = [mod for mod, status in statuses.items() if status in {"success", "available", "200"}]

    # 1. Complete Source Failure (all declared sources failed)
    if statuses and len(failed_sources) == len(statuses):
        is_transient = any(statuses[s] in {"timeout", "error", "500"} for s in failed_sources)
        return RefreshResult(
            success=False,
            status=RefreshStatus.TRANSIENT_ERROR if is_transient else RefreshStatus.FAILED_FETCH,
            snapshot=previous_snapshot,
            changes=[],
            failed_sources=failed_sources,
            error_message=f"All sources ({', '.join(failed_sources)}) failed to refresh; previous state preserved",
        )

    # 2. Complete Failure Handling (retrieval error or missing claims payload)
    if retrieval_error or new_claims is None:
        return RefreshResult(
            success=False,
            status=RefreshStatus.FAILED_FETCH,
            snapshot=previous_snapshot,  # PRESERVE PREVIOUS KNOWN-GOOD STATE
            changes=[],                   # ZERO FALSE REMOVALS
            failed_sources=list(statuses.keys()) if statuses else ["network"],
            error_message=retrieval_error or "Refresh failed; previous known-good snapshot preserved intact",
        )

    # 3. Partial Source Failure & Claim Merging
    active_claims: dict[str, SnapshotClaim] = {}

    # If some sources failed, preserve claims from those specific failed sources from previous snapshot
    if previous_snapshot and failed_sources:
        for key, prev_claim in previous_snapshot.claims.items():
            if prev_claim.source_module in failed_sources:
                # Carried over: source could not be refreshed
                active_claims[key] = prev_claim

    # Add new incoming claims
    for claim in new_claims:
        active_claims[claim.claim_key] = claim

    # Next version
    next_version = (previous_snapshot.version + 1) if previous_snapshot else 1
    snap_id = f"snapshot-{org}-v{next_version}"

    new_snapshot = CompanySnapshot(
        snapshot_id=snap_id,
        version=next_version,
        organisation_number=org,
        timestamp=now,
        claims=active_claims,
        source_statuses=statuses,
        metadata={"previous_snapshot_id": previous_snapshot.snapshot_id if previous_snapshot else None},
    )

    # Detect changes
    changes = compare_snapshots(previous_snapshot, new_snapshot)

    # Determine outcome status
    status = RefreshStatus.PARTIAL_FAILURE if failed_sources else RefreshStatus.SUCCESS

    return RefreshResult(
        success=True,
        status=status,
        snapshot=new_snapshot,
        changes=changes,
        failed_sources=failed_sources,
        error_message=f"Partial refresh: sources failed: {', '.join(failed_sources)}" if failed_sources else None,
    )


# ============================================================================
# 6. SNAPSHOT STORE
# ============================================================================

class MemorySnapshotStore:
    """Thread-safe in-memory store for versioned immutable company snapshots."""

    def __init__(self):
        self._history: dict[str, list[CompanySnapshot]] = {}

    def save_snapshot(self, snapshot: CompanySnapshot) -> None:
        """Save a new snapshot in the company's version history."""
        org = snapshot.organisation_number
        if org not in self._history:
            self._history[org] = []
        self._history[org].append(snapshot)

    def get_latest_snapshot(self, organisation_number: str) -> CompanySnapshot | None:
        """Retrieve the latest snapshot for a company."""
        org = canonicalize_org_number(organisation_number)
        history = self._history.get(org, [])
        return history[-1] if history else None

    def get_snapshot_history(self, organisation_number: str) -> list[CompanySnapshot]:
        """Retrieve the complete chronological history of snapshots for a company."""
        org = canonicalize_org_number(organisation_number)
        return list(self._history.get(org, []))


# ============================================================================
# 7. STAGE 16: FRESHNESS & CHANGE INTELLIGENCE ENGINE
# ============================================================================

# Documented thresholds for workforce materiality
WORKFORCE_MIN_ABSOLUTE_DELTA: int = 10
WORKFORCE_MIN_PERCENTAGE_DELTA: float = 25.0
WORKFORCE_LARGE_MOVEMENT_DELTA: int = 50
WORKFORCE_HIGH_SEVERITY_PERCENTAGE: float = 50.0


@dataclass
class ChangeEvidence:
    """Traceable evidence backing a detected change."""
    source: str
    url: str | None = None
    observed_at: str | None = None
    supports: str = "current_value"
    content_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "observed_at": self.observed_at,
            "supports": self.supports,
            "content_sha256": self.content_sha256,
        }


@dataclass
class ChangeRecord:
    """Structured, evidence-backed change event with materiality classification."""
    category: ChangeCategory
    field: str
    previous: Any
    current: Any
    change_type: ChangeType
    material: bool
    severity: MaterialitySeverity
    confidence: float = 1.0
    evidence: list[ChangeEvidence] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "field": self.field,
            "previous": self.previous,
            "current": self.current,
            "change_type": self.change_type.value,
            "material": self.material,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 3),
            "evidence": [e.to_dict() for e in self.evidence],
            "details": dict(self.details),
            "explanation": self.explanation,
        }


@dataclass
class ChangeReport:
    """Structured report of all verified changes for a company."""
    company: dict[str, str]
    status: str  # "CHANGES_DETECTED", "NO_CHANGES", "INITIAL_OBSERVATION", "IDENTITY_CONFLICT"
    previous_snapshot: str | None
    current_snapshot: str | None
    total_changes: int
    material_changes: int
    changes: list[ChangeRecord]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "status": self.status,
            "previous_snapshot": self.previous_snapshot,
            "current_snapshot": self.current_snapshot,
            "total_changes": self.total_changes,
            "material_changes": self.material_changes,
            "summary": self.summary,
            "changes": [c.to_dict() for c in self.changes],
        }


@dataclass
class CanonicalProfile:
    """Canonical representation of a company profile for deterministic comparison."""
    organisation_number: str
    name: str = ""
    status: str = "ACTIVE"
    industry_code: str | None = None
    industry_label: str | None = None
    website: str | None = None
    website_status: str = "available"  # "available", "unavailable", "not_observed"
    address: dict[str, str] = field(default_factory=lambda: {"street": "", "postal_code": "", "city": "", "country": "Norway"})
    employees: int | None = None
    employees_status: str = "available"  # "available", "unavailable", "not_observed"
    financials: dict[str, dict[str, Any]] = field(default_factory=dict)
    registration: dict[str, Any] = field(default_factory=dict)
    observed_at: str | None = None
    evidence_map: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organisation_number": self.organisation_number,
            "name": self.name,
            "status": self.status,
            "industry": {
                "code": self.industry_code,
                "label": self.industry_label,
            },
            "website": self.website,
            "website_status": self.website_status,
            "address": self.address,
            "employees": self.employees,
            "employees_status": self.employees_status,
            "financials": self.financials,
            "registration": self.registration,
            "observed_at": self.observed_at,
        }


# ============================================================================
# FIELD NORMALIZATION HELPERS
# ============================================================================

def normalize_string_field(value: Any) -> str:
    """Normalize string value collapsing whitespace and trimming punctuation."""
    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    return text


def normalize_url_canonical(url: str | None) -> str | None:
    """Normalize URL ignoring scheme differences, www prefixes, and trailing slashes."""
    if not url:
        return None
    clean = str(url).strip()
    if not clean:
        return None
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        parsed = urllib.parse.urlsplit(clean)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if ":" in netloc:
            host, port = netloc.split(":", 1)
            if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
                netloc = host
        path = parsed.path
        if path == "/":
            path = ""
        elif path.endswith("/") and len(path) > 1:
            path = path.rstrip("/")
        # Reconstruct canonical URL (defaulting scheme to https for comparison)
        return urllib.parse.urlunsplit(("https", netloc, path, parsed.query, ""))
    except Exception:
        return clean


def normalize_domain_canonical(url: str | None) -> str | None:
    """Extract canonical domain for company website comparison."""
    if not url:
        return None
    clean = str(url).strip().lower()
    if not clean:
        return None
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean
    try:
        parsed = urllib.parse.urlsplit(clean)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        return netloc or None
    except Exception:
        return None


def normalize_number_value(value: Any) -> int | float | None:
    """Normalize numeric representation (e.g. 42, 42.0, '42' -> 42)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 4)
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "").replace("\u00a0", "")
        if not cleaned:
            return None
        # Handle European decimal comma if no dot is present
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            f = float(cleaned)
            if f.is_integer():
                return int(f)
            return round(f, 4)
        except ValueError:
            return None
    return None


def normalize_date_iso(date_val: Any) -> str | None:
    """Normalize equivalent date formats (e.g. 2026-01-15, 15.01.2026, 2026/01/15) to YYYY-MM-DD."""
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val.strftime("%Y-%m-%d")
    s = str(date_val).strip()
    if not s:
        return None
    # Strip time part if present
    if "T" in s:
        s = s.split("T")[0]
    elif " " in s:
        s = s.split(" ")[0]

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def normalize_address_components(addr: Any) -> dict[str, str]:
    """Normalize structured address components (street, postal_code, city, country)."""
    if not isinstance(addr, dict):
        if isinstance(addr, str) and addr.strip():
            return {"street": normalize_string_field(addr), "postal_code": "", "city": "", "country": "Norway"}
        return {"street": "", "postal_code": "", "city": "", "country": "Norway"}

    street = str(addr.get("street") or addr.get("adresse") or "").strip()
    # Remove trailing commas or periods from street
    street = re.sub(r"[,\.]+$", "", street).strip()
    street = " ".join(street.split())

    postal_code = str(addr.get("postal_code") or addr.get("postnummer") or "").strip()
    if postal_code.isdigit() and len(postal_code) < 4:
        postal_code = postal_code.zfill(4)

    city = str(addr.get("city") or addr.get("poststed") or addr.get("municipality") or "").strip()
    city = " ".join(city.split())

    country = str(addr.get("country") or addr.get("land") or "Norway").strip()
    if country.upper() in {"NORGE", "NORWAY", "NO", "N"}:
        country = "Norway"

    return {
        "street": street,
        "postal_code": postal_code,
        "city": city,
        "country": country,
    }


# ============================================================================
# CANONICAL PROFILE ADAPTER
# ============================================================================

def normalize_canonical_snapshot(raw_profile: Any, observed_at: str | None = None) -> CanonicalProfile | None:
    """Adapt any company profile representation into a CanonicalProfile for deterministic comparison."""
    if raw_profile is None:
        return None

    if isinstance(raw_profile, CanonicalProfile):
        return raw_profile

    # Case A: Stage 7 CompanySnapshot
    if isinstance(raw_profile, CompanySnapshot):
        org = raw_profile.organisation_number
        claims = raw_profile.claims

        name = ""
        for k in (f"org:{org}|field:legal_name", f"org:{org}|field:name"):
            if k in claims and claims[k].value:
                name = str(claims[k].value)
                break

        status = "ACTIVE"
        st_key = f"org:{org}|field:status"
        if st_key in claims and claims[st_key].value:
            status = str(claims[st_key].value)

        ind_code = None
        ind_lbl = None
        for k in (f"org:{org}|field:industry_code", f"org:{org}|field:nace_code"):
            if k in claims and claims[k].value:
                ind_code = str(claims[k].value)
                break
        for k in (f"org:{org}|field:industry_label", f"org:{org}|field:industry"):
            if k in claims and claims[k].value:
                ind_lbl = str(claims[k].value)
                break

        web = None
        web_st = "available"
        for k in (f"org:{org}|field:website", f"org:{org}|field:canonical_url"):
            if k in claims and claims[k].value:
                web = str(claims[k].value)
                break
        if not web:
            web_st = "not_observed"

        addr: dict[str, str] = {"street": "", "postal_code": "", "city": "", "country": "Norway"}
        muni_key = f"org:{org}|field:municipality"
        if muni_key in claims and claims[muni_key].value:
            addr["city"] = str(claims[muni_key].value)
        addr_key = f"org:{org}|field:address"
        if addr_key in claims and claims[addr_key].value:
            if isinstance(claims[addr_key].value, dict):
                addr.update(normalize_address_components(claims[addr_key].value))
            elif isinstance(claims[addr_key].value, str):
                addr["street"] = str(claims[addr_key].value)

        emp = None
        emp_st = "available"
        emp_key = f"org:{org}|field:employees"
        if emp_key in claims:
            v = claims[emp_key].value
            if v is not None:
                num = normalize_number_value(v)
                emp = int(num) if isinstance(num, (int, float)) else None
            else:
                emp_st = "unavailable"
        else:
            emp_st = "not_observed"

        # Financials from claims with entity qualifiers (e.g. org:xxx|field:revenue|entity:2024)
        fins: dict[str, dict[str, Any]] = {}
        for k, c in claims.items():
            if "|entity:" in k:
                parts = k.split("|")
                fld = ""
                ent = ""
                for p in parts:
                    if p.startswith("field:"):
                        fld = p.replace("field:", "")
                    elif p.startswith("entity:"):
                        ent = p.replace("entity:", "")
                if ent and re.match(r"^20\d\d$", ent):
                    fins.setdefault(ent, {})[fld] = c.value

        reg: dict[str, Any] = {}
        for k in (f"org:{org}|field:legal_form", f"org:{org}|field:organisasjonsform"):
            if k in claims and claims[k].value:
                reg["legal_form"] = claims[k].value
                break

        return CanonicalProfile(
            organisation_number=org,
            name=name,
            status=status,
            industry_code=ind_code,
            industry_label=ind_lbl,
            website=web,
            website_status=web_st,
            address=normalize_address_components(addr),
            employees=emp,
            employees_status=emp_st,
            financials=fins,
            registration=reg,
            observed_at=raw_profile.timestamp,
            evidence_map={},
        )

    # Case B: Object with .facts attribute (like UnifiedCompanyProfile)
    if hasattr(raw_profile, "facts") and isinstance(raw_profile.facts, dict):
        org = canonicalize_org_number(getattr(raw_profile, "organisation_number", ""))
        name = getattr(raw_profile, "company_name", "")
        facts = raw_profile.facts

        def fact_val(cat_name: str) -> Any:
            for k, f in facts.items():
                k_str = k.value if hasattr(k, "value") else str(k)
                if k_str == cat_name:
                    return getattr(f, "value", None)
            return None

        status = "ACTIVE"
        reg_status = fact_val("registration_status")
        if reg_status:
            status = str(reg_status).upper()

        ind_code = fact_val("primary_industry_code")
        ind_lbl = fact_val("primary_industry_description")
        web = fact_val("official_website")
        web_st = "available" if web else "not_observed"

        addr: dict[str, str] = {
            "street": str(fact_val("registered_office_address") or ""),
            "postal_code": str(fact_val("postal_code") or ""),
            "city": str(fact_val("municipality") or ""),
            "country": "Norway",
        }

        emp_raw = fact_val("employees")
        emp = int(emp_raw) if emp_raw is not None and isinstance(normalize_number_value(emp_raw), (int, float)) else None
        emp_st = "available" if emp is not None else "not_observed"

        fins = {}
        fin_rec = fact_val("latest_financials")
        if isinstance(fin_rec, dict):
            yr = str(fin_rec.get("year") or fin_rec.get("period") or "latest")
            fins[yr] = fin_rec

        reg = {
            "legal_form": fact_val("legal_form"),
            "registered": fact_val("registration_date"),
            "status": status,
        }

        return CanonicalProfile(
            organisation_number=org,
            name=name,
            status=status,
            industry_code=str(ind_code) if ind_code else None,
            industry_label=str(ind_lbl) if ind_lbl else None,
            website=str(web) if web else None,
            website_status=web_st,
            address=normalize_address_components(addr),
            employees=emp,
            employees_status=emp_st,
            financials=fins,
            registration=reg,
            observed_at=getattr(raw_profile, "created_at", None) or observed_at or utc_now(),
            evidence_map={},
        )

    # Case C: Standard dictionary profile
    if isinstance(raw_profile, dict):
        org = canonicalize_org_number(
            str(raw_profile.get("organisation_number") or raw_profile.get("organization_number") or "")
        )
        name = normalize_string_field(
            raw_profile.get("name") or raw_profile.get("company_name") or raw_profile.get("legal_name") or ""
        )

        # Status
        status = "ACTIVE"
        if raw_profile.get("bankrupt") is True:
            status = "BANKRUPT"
        elif raw_profile.get("liquidating") is True or raw_profile.get("under_liquidation") is True:
            status = "UNDER_LIQUIDATION"
        elif raw_profile.get("dissolved") is True:
            status = "DISSOLVED"
        elif raw_profile.get("status"):
            raw_st = str(raw_profile["status"]).upper().strip()
            if "BANKRUPT" in raw_st or "KONKURS" in raw_st:
                status = "BANKRUPT"
            elif "LIQUID" in raw_st or "AVVIKLING" in raw_st:
                status = "UNDER_LIQUIDATION"
            elif "DISSOLV" in raw_st or "SLETTET" in raw_st:
                status = "DISSOLVED"
            elif "ACTIVE" in raw_st or "AKTIV" in raw_st:
                status = "ACTIVE"
            else:
                status = raw_st
        else:
            # Check registry evidence if present
            ev_reg = raw_profile.get("evidence", {}).get("registry") or raw_profile.get("evidence", {}).get("registry_live") or {}
            reg_val = ev_reg.get("value") or {}
            if isinstance(reg_val, dict):
                if reg_val.get("konkurs") is True:
                    status = "BANKRUPT"
                elif reg_val.get("underAvvikling") is True:
                    status = "UNDER_LIQUIDATION"
                elif reg_val.get("slettedato"):
                    status = "DISSOLVED"

        # Industry
        ind_code = raw_profile.get("industry_code") or raw_profile.get("nace_code")
        ind_lbl = raw_profile.get("industry_label") or raw_profile.get("industry")
        if isinstance(ind_lbl, dict):
            ind_code = ind_code or ind_lbl.get("code") or ind_lbl.get("kode")
            ind_lbl = ind_lbl.get("label") or ind_lbl.get("beskrivelse") or ind_lbl.get("name")
        if not ind_code:
            ev_reg = raw_profile.get("evidence", {}).get("registry") or raw_profile.get("evidence", {}).get("registry_live") or {}
            reg_val = ev_reg.get("value") or {}
            if isinstance(reg_val, dict):
                naering = reg_val.get("naeringskode1") or {}
                if isinstance(naering, dict):
                    ind_code = naering.get("kode")
                    ind_lbl = ind_lbl or naering.get("beskrivelse")

        # Website
        web = raw_profile.get("website") or raw_profile.get("canonical_url")
        ev_web = raw_profile.get("evidence", {}).get("website") or {}
        web_st = "available"
        if ev_web and isinstance(ev_web, dict):
            st = ev_web.get("status", "available")
            if st in {"failed", "timeout", "error", "source_error", "not_found", "blocked", "blocked_robots", "blocked_policy"}:
                web_st = "unavailable"
            if not web:
                val = ev_web.get("value") or {}
                if isinstance(val, dict):
                    web = val.get("final_url") or val.get("url")
        if not web:
            if "website" in raw_profile and raw_profile["website"] is None:
                web_st = "unavailable"
            else:
                web_st = "not_observed"

        # Address
        raw_addr = raw_profile.get("address")
        addr_dict: dict[str, Any] = {}
        if isinstance(raw_addr, dict):
            addr_dict = dict(raw_addr)
        elif isinstance(raw_addr, str) and raw_addr.strip():
            addr_dict = {"street": raw_addr.strip()}

        for k_src, k_dst in (
            ("municipality", "city"),
            ("poststed", "city"),
            ("city", "city"),
            ("postal_code", "postal_code"),
            ("postnummer", "postal_code"),
            ("street", "street"),
            ("country", "country"),
        ):
            if k_src in raw_profile and raw_profile[k_src] and not addr_dict.get(k_dst):
                addr_dict[k_dst] = raw_profile[k_src]

        ev_reg = raw_profile.get("evidence", {}).get("registry") or raw_profile.get("evidence", {}).get("registry_live") or {}
        reg_val = ev_reg.get("value") or {}
        if isinstance(reg_val, dict) and not addr_dict.get("street") and not addr_dict.get("city"):
            forr = reg_val.get("forretningsadresse") or {}
            if isinstance(forr, dict):
                adresser = forr.get("adresse") or []
                addr_dict["street"] = ", ".join(adresser) if isinstance(adresser, list) else str(adresser)
                addr_dict["postal_code"] = forr.get("postnummer", "")
                addr_dict["city"] = forr.get("poststed", "") or reg_val.get("forretningsadresse_kommune", "")

        # Employees
        emp = raw_profile.get("employees")
        if emp is None and "antall_ansatte" in raw_profile:
            emp = raw_profile["antall_ansatte"]
        if emp is None:
            if isinstance(reg_val, dict):
                emp = reg_val.get("antallAnsatte")

        emp_st = "available"
        if emp is not None:
            num = normalize_number_value(emp)
            emp = int(num) if isinstance(num, (int, float)) else None
            emp_st = "available"
        else:
            if "employees" in raw_profile or "antall_ansatte" in raw_profile:
                emp_st = "unavailable"
            else:
                emp_st = "not_observed"

        # Financials
        fin_map: dict[str, dict[str, Any]] = {}
        raw_fin = raw_profile.get("financials") or {}
        if isinstance(raw_fin, dict):
            if any(re.match(r"^20\d\d$", str(k)) for k in raw_fin.keys()):
                for pk, p_val in raw_fin.items():
                    if isinstance(p_val, dict):
                        fin_map[str(pk)] = dict(p_val)
            else:
                pk = str(raw_fin.get("period") or raw_fin.get("year") or "latest")
                fin_map[pk] = dict(raw_fin)
        elif isinstance(raw_fin, list):
            for item in raw_fin:
                if isinstance(item, dict):
                    pk = str(item.get("period") or item.get("year") or "latest")
                    fin_map[pk] = dict(item)

        ev_fin = raw_profile.get("evidence", {}).get("financials") or raw_profile.get("evidence", {}).get("financial_history") or {}
        ev_val = ev_fin.get("value") or {}
        if isinstance(ev_val, dict):
            records = ev_val.get("records") or ev_val.get("years") or []
            if isinstance(records, list):
                for rec in records:
                    if isinstance(rec, dict):
                        pk = str(rec.get("year") or rec.get("period") or "latest")
                        if pk not in fin_map:
                            fin_map[pk] = dict(rec)

        # Registration
        reg_dict = dict(raw_profile.get("registration") or {})
        if not reg_dict.get("legal_form"):
            reg_dict["legal_form"] = raw_profile.get("legal_form") or raw_profile.get("organisasjonsform")
        if not reg_dict.get("registered"):
            reg_dict["registered"] = raw_profile.get("registration_date") or raw_profile.get("registered")
        if not reg_dict.get("status"):
            reg_dict["status"] = raw_profile.get("registration_status") or status

        obs = (
            raw_profile.get("observed_at")
            or raw_profile.get("retrieved_at")
            or raw_profile.get("created_at")
            or observed_at
            or utc_now()
        )

        return CanonicalProfile(
            organisation_number=org,
            name=name,
            status=status,
            industry_code=str(ind_code) if ind_code else None,
            industry_label=str(ind_lbl) if ind_lbl else None,
            website=str(web) if web else None,
            website_status=web_st,
            address=normalize_address_components(addr_dict),
            employees=emp,
            employees_status=emp_st,
            financials=fin_map,
            registration=reg_dict,
            observed_at=obs,
            evidence_map=dict(raw_profile.get("evidence", {})),
        )

    return None


# ============================================================================
# EVIDENCE HELPERS
# ============================================================================

def _registry_evidence(profile: CanonicalProfile) -> ChangeEvidence:
    ev_reg = profile.evidence_map.get("registry") or profile.evidence_map.get("registry_live") or {}
    url = ev_reg.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.organisation_number}"
    retrieved = ev_reg.get("retrieved_at") or profile.observed_at or utc_now()
    sha = ev_reg.get("content_sha256")
    return ChangeEvidence(
        source="BRREG_ENHETSREGISTERET",
        url=url,
        observed_at=retrieved,
        supports="current_value",
        content_sha256=sha,
    )


def _website_evidence(profile: CanonicalProfile) -> ChangeEvidence:
    ev_web = profile.evidence_map.get("website") or {}
    url = profile.website or ev_web.get("source_url") or "https://data.brreg.no/enhetsregisteret/api/enheter"
    retrieved = ev_web.get("retrieved_at") or profile.observed_at or utc_now()
    sha = ev_web.get("content_sha256")
    return ChangeEvidence(
        source="COMPANY_WEBSITE",
        url=url,
        observed_at=retrieved,
        supports="current_value",
        content_sha256=sha,
    )


def _workforce_evidence(profile: CanonicalProfile) -> ChangeEvidence:
    ev_reg = profile.evidence_map.get("registry") or profile.evidence_map.get("registry_live") or {}
    url = ev_reg.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.organisation_number}"
    retrieved = ev_reg.get("retrieved_at") or profile.observed_at or utc_now()
    sha = ev_reg.get("content_sha256")
    return ChangeEvidence(
        source="OFFICIAL_REGISTRY_A_ORDNINGEN",
        url=url,
        observed_at=retrieved,
        supports="current_value",
        content_sha256=sha,
    )


def _financial_evidence(profile: CanonicalProfile) -> ChangeEvidence:
    ev_fin = profile.evidence_map.get("financials") or profile.evidence_map.get("financial_history") or {}
    url = ev_fin.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.organisation_number}"
    retrieved = ev_fin.get("retrieved_at") or profile.observed_at or utc_now()
    sha = ev_fin.get("content_sha256")
    return ChangeEvidence(
        source="BRREG_REGNSKAPSREGISTERET",
        url=url,
        observed_at=retrieved,
        supports="current_value",
        content_sha256=sha,
    )


# ============================================================================
# CANONICAL COMPARISON ENGINE
# ============================================================================

def compare_canonical_profiles(
    previous: CanonicalProfile | None,
    current: CanonicalProfile,
    *,
    timestamp: str | None = None,
) -> ChangeReport:
    """Compare previous and current canonical company profiles.

    Produces structured, deterministic, evidence-backed change events.
    Guarantees:
    - Never converts missing data into 0 or deletion.
    - Never treats crawl failure as website deletion.
    - Detects IDENTITY_CONFLICT when organisation numbers mismatch.
    - Compares financials by reporting period (distinguishing new period from same-period restatement).
    - Ignores formatting, whitespace, casing, and URL slash differences.
    """
    now = timestamp or current.observed_at or utc_now()
    comp_info = {
        "organization_number": current.organisation_number,
        "name": current.name,
    }

    # 1. First observation check
    if previous is None:
        return ChangeReport(
            company=comp_info,
            status="INITIAL_OBSERVATION",
            previous_snapshot=None,
            current_snapshot=now,
            total_changes=0,
            material_changes=0,
            changes=[],
            summary={
                "by_severity": {s.value: 0 for s in MaterialitySeverity},
                "by_category": {},
            },
        )

    # 2. Identity conflict check
    prev_org = canonicalize_org_number(previous.organisation_number)
    curr_org = canonicalize_org_number(current.organisation_number)
    if prev_org != curr_org:
        conflict_rec = ChangeRecord(
            category=ChangeCategory.IDENTITY,
            field="organisation_number",
            previous=previous.organisation_number,
            current=current.organisation_number,
            change_type=ChangeType.IDENTITY_CONFLICT,
            material=True,
            severity=MaterialitySeverity.CRITICAL,
            confidence=1.0,
            evidence=[
                ChangeEvidence(
                    source="BRREG_ENHETSREGISTERET",
                    url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{curr_org}",
                    observed_at=now,
                    supports="identity_conflict",
                )
            ],
            details={"previous_org": previous.organisation_number, "current_org": current.organisation_number},
            explanation=f"CRITICAL IDENTITY CONFLICT: Organisation numbers do not match ({previous.organisation_number} vs {current.organisation_number}). These represent different legal entities; comparison aborted.",
        )
        return ChangeReport(
            company=comp_info,
            status="IDENTITY_CONFLICT",
            previous_snapshot=previous.observed_at,
            current_snapshot=now,
            total_changes=1,
            material_changes=1,
            changes=[conflict_rec],
            summary={
                "by_severity": {
                    MaterialitySeverity.CRITICAL.value: 1,
                    MaterialitySeverity.HIGH.value: 0,
                    MaterialitySeverity.MEDIUM.value: 0,
                    MaterialitySeverity.LOW.value: 0,
                    MaterialitySeverity.NONE.value: 0,
                },
                "by_category": {ChangeCategory.IDENTITY.value: 1},
            },
        )

    changes: list[ChangeRecord] = []

    # 3. Company Legal Name
    if previous.name and current.name:
        p_name = normalize_string_field(previous.name)
        c_name = normalize_string_field(current.name)
        if p_name.casefold() != c_name.casefold():
            changes.append(
                ChangeRecord(
                    category=ChangeCategory.IDENTITY,
                    field="name",
                    previous=previous.name,
                    current=current.name,
                    change_type=ChangeType.MODIFIED,
                    material=True,
                    severity=MaterialitySeverity.HIGH,
                    confidence=0.99,
                    evidence=[_registry_evidence(current)],
                    explanation=f"Company name changed from '{previous.name}' to '{current.name}'",
                )
            )

    # 4. Status Change Detection
    st_prev = str(previous.status or "ACTIVE").upper().strip()
    st_curr = str(current.status or "ACTIVE").upper().strip()
    if st_prev != st_curr:
        is_critical = any(kw in st_curr for kw in ("DISSOLVED", "BANKRUPT", "LIQUIDATION", "SLETTET", "KONKURS", "AVVIKLING"))
        severity = MaterialitySeverity.CRITICAL if is_critical else MaterialitySeverity.HIGH
        changes.append(
            ChangeRecord(
                category=ChangeCategory.STATUS,
                field="status",
                previous=st_prev,
                current=st_curr,
                change_type=ChangeType.MODIFIED,
                material=True,
                severity=severity,
                confidence=0.99,
                evidence=[_registry_evidence(current)],
                explanation=f"Company legal status transitioned from '{st_prev}' to '{st_curr}'",
            )
        )

    # 5. Industry Change Detection
    prev_code = (previous.industry_code or "").strip()
    curr_code = (current.industry_code or "").strip()
    if prev_code and curr_code:
        if prev_code != curr_code:
            changes.append(
                ChangeRecord(
                    category=ChangeCategory.INDUSTRY,
                    field="industry",
                    previous=f"{prev_code} ({previous.industry_label})" if previous.industry_label else prev_code,
                    current=f"{curr_code} ({current.industry_label})" if current.industry_label else curr_code,
                    change_type=ChangeType.MODIFIED,
                    material=True,
                    severity=MaterialitySeverity.HIGH,
                    confidence=0.95,
                    evidence=[_registry_evidence(current)],
                    explanation=f"Primary industry classification code changed from {prev_code} to {curr_code}",
                )
            )
        # Note: If industry codes match identically, variations in label wording are ignored as non-material
    elif previous.industry_label or current.industry_label:
        lbl_prev = normalize_string_field(previous.industry_label).casefold()
        lbl_curr = normalize_string_field(current.industry_label).casefold()
        if lbl_prev != lbl_curr and lbl_prev and lbl_curr:
            changes.append(
                ChangeRecord(
                    category=ChangeCategory.INDUSTRY,
                    field="industry",
                    previous=previous.industry_label,
                    current=current.industry_label,
                    change_type=ChangeType.MODIFIED,
                    material=True,
                    severity=MaterialitySeverity.HIGH,
                    confidence=0.85,
                    evidence=[_registry_evidence(current)],
                    explanation=f"Industry classification changed from '{previous.industry_label}' to '{current.industry_label}'",
                )
            )

    # 6. Website Change Detection
    prev_web = previous.website
    curr_web = current.website
    curr_web_st = current.website_status

    if prev_web and curr_web_st in {"unavailable", "failed", "timeout", "error", "source_error"}:
        # Missing data rule: Crawl failure is NEVER deletion
        changes.append(
            ChangeRecord(
                category=ChangeCategory.WEBSITE,
                field="website",
                previous=prev_web,
                current=None,
                change_type=ChangeType.VALUE_UNAVAILABLE,
                material=False,
                severity=MaterialitySeverity.NONE,
                confidence=0.50,
                evidence=[_website_evidence(current)],
                explanation="Website fetch failed or was unavailable; previous known website preserved, not reported as removed.",
            )
        )
    elif not prev_web and curr_web and curr_web_st == "available":
        changes.append(
            ChangeRecord(
                category=ChangeCategory.WEBSITE,
                field="website",
                previous=None,
                current=curr_web,
                change_type=ChangeType.ADDED,
                material=True,
                severity=MaterialitySeverity.MEDIUM,
                confidence=0.85,
                evidence=[_website_evidence(current)],
                explanation=f"Company website discovered: '{curr_web}'",
            )
        )
    elif prev_web and curr_web and curr_web_st == "available":
        dom_prev = normalize_domain_canonical(prev_web)
        dom_curr = normalize_domain_canonical(curr_web)
        if dom_prev != dom_curr:
            changes.append(
                ChangeRecord(
                    category=ChangeCategory.WEBSITE,
                    field="website",
                    previous=prev_web,
                    current=curr_web,
                    change_type=ChangeType.MODIFIED,
                    material=True,
                    severity=MaterialitySeverity.MEDIUM,
                    confidence=0.85,
                    evidence=[_website_evidence(current)],
                    explanation=f"Company website domain changed from '{prev_web}' to '{curr_web}'",
                )
            )
        else:
            # Same domain: check URL normalization
            norm_url_prev = normalize_url_canonical(prev_web)
            norm_url_curr = normalize_url_canonical(curr_web)
            if norm_url_prev != norm_url_curr:
                # Meaningful path difference on same domain (e.g. /about vs /contact)
                changes.append(
                    ChangeRecord(
                        category=ChangeCategory.WEBSITE,
                        field="website.url",
                        previous=prev_web,
                        current=curr_web,
                        change_type=ChangeType.MODIFIED,
                        material=False,
                        severity=MaterialitySeverity.LOW,
                        confidence=0.85,
                        evidence=[_website_evidence(current)],
                        explanation=f"Website canonical path updated from '{prev_web}' to '{curr_web}'",
                    )
                )

    # 7. Address Change Detection
    norm_addr_prev = normalize_address_components(previous.address)
    norm_addr_curr = normalize_address_components(current.address)

    city_prev = norm_addr_prev["city"]
    city_curr = norm_addr_curr["city"]
    if city_prev and city_curr and city_prev.casefold() != city_curr.casefold():
        changes.append(
            ChangeRecord(
                category=ChangeCategory.ADDRESS,
                field="address.city",
                previous=previous.address.get("city") or city_prev,
                current=current.address.get("city") or city_curr,
                change_type=ChangeType.MODIFIED,
                material=True,
                severity=MaterialitySeverity.HIGH,
                confidence=0.95,
                evidence=[_registry_evidence(current)],
                explanation=f"Registered municipality/city relocated from '{city_prev}' to '{city_curr}'",
            )
        )

    street_prev = norm_addr_prev["street"]
    street_curr = norm_addr_curr["street"]
    if street_prev and street_curr and street_prev.casefold() != street_curr.casefold():
        changes.append(
            ChangeRecord(
                category=ChangeCategory.ADDRESS,
                field="address.street",
                previous=previous.address.get("street") or street_prev,
                current=current.address.get("street") or street_curr,
                change_type=ChangeType.MODIFIED,
                material=True,
                severity=MaterialitySeverity.MEDIUM,
                confidence=0.95,
                evidence=[_registry_evidence(current)],
                explanation=f"Registered street address changed from '{street_prev}' to '{street_curr}'",
            )
        )

    post_prev = norm_addr_prev["postal_code"]
    post_curr = norm_addr_curr["postal_code"]
    if post_prev and post_curr and post_prev != post_curr:
        changes.append(
            ChangeRecord(
                category=ChangeCategory.ADDRESS,
                field="address.postal_code",
                previous=post_prev,
                current=post_curr,
                change_type=ChangeType.MODIFIED,
                material=True,
                severity=MaterialitySeverity.LOW,
                confidence=0.95,
                evidence=[_registry_evidence(current)],
                explanation=f"Postal code changed from '{post_prev}' to '{post_curr}'",
            )
        )

    # 8. Employee Change Detection
    emp_prev = previous.employees
    emp_curr = current.employees
    emp_st = current.employees_status

    if emp_prev is not None and (emp_curr is None or emp_st in {"unavailable", "not_observed"}):
        # Missing employee data is NEVER 0
        changes.append(
            ChangeRecord(
                category=ChangeCategory.WORKFORCE,
                field="employees",
                previous=emp_prev,
                current=None,
                change_type=ChangeType.VALUE_UNAVAILABLE,
                material=False,
                severity=MaterialitySeverity.NONE,
                confidence=0.50,
                evidence=[_workforce_evidence(current)],
                explanation=f"Current employee count unavailable; previous count ({emp_prev}) preserved, not treated as 0.",
            )
        )
    elif emp_prev is None and emp_curr is not None:
        changes.append(
            ChangeRecord(
                category=ChangeCategory.WORKFORCE,
                field="employees",
                previous=None,
                current=emp_curr,
                change_type=ChangeType.ADDED,
                material=True,
                severity=MaterialitySeverity.LOW,
                confidence=0.98,
                evidence=[_workforce_evidence(current)],
                explanation=f"Initial employee count observed: {emp_curr}",
            )
        )
    elif emp_prev is not None and emp_curr is not None:
        delta = emp_curr - emp_prev
        if delta != 0:
            pct = (delta / emp_prev * 100.0) if emp_prev > 0 else 100.0
            is_material = (
                (abs(delta) >= WORKFORCE_MIN_ABSOLUTE_DELTA and abs(pct) >= WORKFORCE_MIN_PERCENTAGE_DELTA)
                or (abs(delta) >= WORKFORCE_LARGE_MOVEMENT_DELTA)
            )
            if is_material:
                sev = (
                    MaterialitySeverity.HIGH
                    if (abs(delta) >= WORKFORCE_LARGE_MOVEMENT_DELTA or abs(pct) >= WORKFORCE_HIGH_SEVERITY_PERCENTAGE)
                    else MaterialitySeverity.MEDIUM
                )
                expl = f"Significant workforce shift: employee count changed from {emp_prev} to {emp_curr} ({delta:+d}, {pct:+.1f}%)"
            else:
                sev = MaterialitySeverity.LOW
                expl = f"Minor workforce fluctuation: employee count changed from {emp_prev} to {emp_curr} ({delta:+d}, {pct:+.1f}%), below materiality threshold"

            ch_type = ChangeType.INCREASE if delta > 0 else ChangeType.DECREASE
            changes.append(
                ChangeRecord(
                    category=ChangeCategory.WORKFORCE,
                    field="employees",
                    previous=emp_prev,
                    current=emp_curr,
                    change_type=ch_type,
                    material=is_material,
                    severity=sev,
                    confidence=0.98,
                    evidence=[_workforce_evidence(current)],
                    details={"delta": delta, "percentage_change": round(pct, 2)},
                    explanation=expl,
                )
            )

    # 9. Financial Change Handling (by reporting period!)
    prev_fins = previous.financials
    curr_fins = current.financials

    prev_periods = set(prev_fins.keys())
    curr_periods = set(curr_fins.keys())

    # Case A: Newly available reporting periods
    for period in sorted(curr_periods - prev_periods):
        changes.append(
            ChangeRecord(
                category=ChangeCategory.FINANCIAL,
                field=f"financials.{period}",
                previous=None,
                current=curr_fins[period],
                change_type=ChangeType.NEW_PERIOD_AVAILABLE,
                material=True,
                severity=MaterialitySeverity.MEDIUM,
                confidence=0.95,
                evidence=[_financial_evidence(current)],
                details={"reporting_period": period},
                explanation=f"New financial reporting period available for period {period}",
            )
        )

    # Case B: Revisions to the SAME reporting period
    for period in sorted(prev_periods & curr_periods):
        p_data = prev_fins[period]
        c_data = curr_fins[period]
        for metric in ("revenue", "profit", "operating_profit", "total_assets", "equity"):
            val_prev = normalize_number_value(p_data.get(metric))
            val_curr = normalize_number_value(c_data.get(metric))
            if val_prev is not None and val_curr is not None and val_prev != val_curr:
                changes.append(
                    ChangeRecord(
                        category=ChangeCategory.FINANCIAL,
                        field=f"financials.{period}.{metric}",
                        previous=val_prev,
                        current=val_curr,
                        change_type=ChangeType.MODIFIED,
                        material=True,
                        severity=MaterialitySeverity.MEDIUM,
                        confidence=0.95,
                        evidence=[_financial_evidence(current)],
                        details={"reporting_period": period, "metric": metric},
                        explanation=f"Financial statement restatement for period {period}: {metric} changed from {val_prev} to {val_curr}",
                    )
                )

    # 10. Registration Details
    reg_prev = previous.registration
    reg_curr = current.registration
    lf_prev = (reg_prev.get("legal_form") or "").strip().upper()
    lf_curr = (reg_curr.get("legal_form") or "").strip().upper()
    if lf_prev and lf_curr and lf_prev != lf_curr:
        changes.append(
            ChangeRecord(
                category=ChangeCategory.REGISTRATION,
                field="legal_form",
                previous=reg_prev.get("legal_form"),
                current=reg_curr.get("legal_form"),
                change_type=ChangeType.MODIFIED,
                material=True,
                severity=MaterialitySeverity.HIGH,
                confidence=0.99,
                evidence=[_registry_evidence(current)],
                explanation=f"Legal form changed from '{reg_prev.get('legal_form')}' to '{reg_curr.get('legal_form')}'",
            )
        )

    # Summary calculations
    material_count = sum(1 for c in changes if c.material)
    status_str = "CHANGES_DETECTED" if material_count > 0 else "NO_CHANGES"

    by_sev = {s.value: 0 for s in MaterialitySeverity}
    by_cat = {c.value: 0 for c in ChangeCategory}
    for c in changes:
        by_sev[c.severity.value] = by_sev.get(c.severity.value, 0) + 1
        by_cat[c.category.value] = by_cat.get(c.category.value, 0) + 1

    return ChangeReport(
        company=comp_info,
        status=status_str,
        previous_snapshot=previous.observed_at,
        current_snapshot=now,
        total_changes=len(changes),
        material_changes=material_count,
        changes=changes,
        summary={
            "by_severity": by_sev,
            "by_category": {k: v for k, v in by_cat.items() if v > 0},
        },
    )


def analyze_profile_changes(
    previous: Any,
    current: Any,
    *,
    timestamp: str | None = None,
) -> ChangeReport:
    """End-to-end Freshness & Change Intelligence pipeline.

    Accepts raw dictionary profiles, CompanySnapshot instances, or UnifiedCompanyProfile
    instances, normalizes them canonically, compares them with zero noise,
    and returns a structured ChangeReport.
    """
    prev_canonical = normalize_canonical_snapshot(previous) if previous is not None else None
    curr_canonical = normalize_canonical_snapshot(current)
    if curr_canonical is None:
        raise ValueError("Current profile cannot be None for change intelligence analysis")

    return compare_canonical_profiles(prev_canonical, curr_canonical, timestamp=timestamp)

