from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

EvidenceStatus = Literal[
    "available",
    "not_found",
    "not_applicable",
    "not_fetched",
    "source_error",
    "blocked",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Evidence:
    field: str
    status: EvidenceStatus
    source_type: str
    source_class: str
    source_url: str
    retrieved_at: str
    value: Any = None
    as_of: str | None = None
    note: str | None = None
    content_sha256: str | None = None
    source_row_key: str | None = None
    effective_at: str | None = None
    # Stage 15 Hardening Provenance Fields
    source_title: str | None = None
    published_at: str | None = None
    organisation_number: str | None = None
    company_name: str | None = None
    identity_match: bool | None = None
    evidence_excerpt: str | None = None
    confidence: float | None = None
    validation_status: str | None = None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evidence(
    field: str,
    status: EvidenceStatus,
    source_type: str,
    source_url: str,
    *,
    value: Any = None,
    as_of: str | None = None,
    note: str | None = None,
    retrieved_at: str | None = None,
    content_sha256: str | None = None,
    source_row_key: str | None = None,
    effective_at: str | None = None,
    source_title: str | None = None,
    published_at: str | None = None,
    organisation_number: str | None = None,
    company_name: str | None = None,
    identity_match: bool | None = None,
    evidence_excerpt: str | None = None,
    confidence: float | None = None,
    validation_status: str | None = None,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    return Evidence(
        field=field,
        status=status,
        source_type=source_type,
        source_class=source_type,
        source_url=source_url,
        retrieved_at=retrieved_at or utc_now(),
        value=value,
        as_of=as_of,
        note=note,
        content_sha256=content_sha256,
        source_row_key=source_row_key,
        effective_at=effective_at,
        source_title=source_title,
        published_at=published_at,
        organisation_number=organisation_number,
        company_name=company_name,
        identity_match=identity_match,
        evidence_excerpt=evidence_excerpt,
        confidence=confidence,
        validation_status=validation_status,
        rejection_reason=rejection_reason,
    ).to_dict()

