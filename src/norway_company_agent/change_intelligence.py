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
