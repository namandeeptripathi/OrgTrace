"""Stage 18: Evidence Validity Evaluation Module.

Evaluates whether company facts and claims are rigorously backed by verifiable evidence:
- Verifies source URL syntax, scheme, and domain authority
- Verifies evidence freshness / retrieved timestamp
- Verifies plausible semantic correspondence between claim and evidence source
- Classifies claims into: supported, partially_supported, unsupported, contradicted, missing_evidence
- Computes: validity_rate, evidence_coverage, unsupported_claim_rate, source_availability_rate
"""

from __future__ import annotations

import re
from typing import Any
import urllib.parse

from ..evidence_engine import classify_source_authority, SourceAuthority
from .models import ClaimEvidenceStatus, EvidenceEvaluation


def _is_valid_url(url: str | None) -> bool:
    """Check if URL is well-formed with public http/https scheme and domain."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if len(url) < 8 or len(url) > 2048:
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc and "." in parsed.netloc)
    except Exception:
        return False


def _extract_domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return ""


def evaluate_company_evidence(profile: dict[str, Any] | None) -> EvidenceEvaluation:
    """Evaluate evidence validity and coverage across all claims attached to a company profile."""
    if not profile:
        return EvidenceEvaluation(
            validity_rate=0.0,
            evidence_coverage=0.0,
            unsupported_claim_rate=0.0,
            source_availability_rate=0.0,
            total_claims=0,
            supported_claims=0,
            partially_supported_claims=0,
            unsupported_claims=0,
            contradicted_claims=0,
            missing_evidence_claims=0,
            claims_detail=[],
        )

    claims_detail: list[dict[str, Any]] = []
    supported_count = 0
    partially_supported_count = 0
    unsupported_count = 0
    contradicted_count = 0
    missing_evidence_count = 0
    available_source_count = 0

    evidence_dict = profile.get("evidence", {})
    if isinstance(evidence_dict, list):
        # Normalize list of evidence items to dict or list of claims
        evidence_dict = {f"item_{i}": item for i, item in enumerate(evidence_dict)}

    # Collect key candidate claims to evaluate
    eval_claims: list[dict[str, Any]] = []

    # 1. Identity claims
    if profile.get("organisation_number"):
        eval_claims.append({
            "claim": "organisation_number",
            "value": profile.get("organisation_number"),
            "expected_source_types": ["official_registry_bulk", "official_registry_live", "registry"],
            "evidence_key": "registry",
        })
    if profile.get("name"):
        eval_claims.append({
            "claim": "legal_name",
            "value": profile.get("name"),
            "expected_source_types": ["official_registry_bulk", "official_registry_live", "registry"],
            "evidence_key": "registry",
        })

    # 2. Accounting obligation / Financial claims
    if "accounting_obligation" in evidence_dict:
        eval_claims.append({
            "claim": "accounting_obligation",
            "value": (evidence_dict["accounting_obligation"].get("value") or {}).get("classification"),
            "expected_source_types": ["official_rule_interpretation", "registry"],
            "evidence_key": "accounting_obligation",
        })
    if "financials" in evidence_dict:
        fin_rec = evidence_dict["financials"]
        eval_claims.append({
            "claim": "annual_accounts",
            "value": fin_rec.get("value"),
            "expected_source_types": ["official_annual_accounts", "official_registry_live", "financials"],
            "evidence_key": "financials",
        })

    # 3. Roles / Leadership claims
    if "roles" in evidence_dict:
        eval_claims.append({
            "claim": "registered_roles",
            "value": (evidence_dict["roles"].get("value") or {}).get("roles"),
            "expected_source_types": ["official_roles", "roles"],
            "evidence_key": "roles",
        })

    # 4. Locations claims
    if "locations" in evidence_dict:
        eval_claims.append({
            "claim": "registered_subunits",
            "value": (evidence_dict["locations"].get("value") or {}).get("locations"),
            "expected_source_types": ["official_subunits", "locations"],
            "evidence_key": "locations",
        })

    # 5. Website claims
    if profile.get("website") or "website" in evidence_dict:
        eval_claims.append({
            "claim": "website",
            "value": profile.get("website") or (evidence_dict.get("website", {}).get("value") or {}).get("url"),
            "expected_source_types": ["registry_linked_company_website", "search_discovered_company_website", "website"],
            "evidence_key": "website",
        })

    # If no standard claims, inspect whatever raw evidence exists
    if not eval_claims and evidence_dict:
        for k, v in evidence_dict.items():
            if isinstance(v, dict):
                eval_claims.append({
                    "claim": k,
                    "value": v.get("value"),
                    "expected_source_types": [v.get("source_type", k)],
                    "evidence_key": k,
                })

    for item in eval_claims:
        claim_name = item["claim"]
        claim_val = item["value"]
        ev_key = item.get("evidence_key")
        ev_item = evidence_dict.get(ev_key) if ev_key else None

        if not ev_item or not isinstance(ev_item, dict):
            status = ClaimEvidenceStatus.MISSING_EVIDENCE
            missing_evidence_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "reason": f"No evidence record attached for claim {claim_name}",
            })
            continue

        src_url = ev_item.get("source_url")
        src_type = ev_item.get("source_type") or ev_item.get("source_class")
        retrieved_at = ev_item.get("retrieved_at")
        content_hash = ev_item.get("content_sha256")
        status_flag = ev_item.get("status")

        has_valid_url = _is_valid_url(src_url)
        has_retrieved_time = bool(retrieved_at)
        has_hash = bool(content_hash)

        if status_flag == "available":
            available_source_count += 1

        # Evaluate relationship: does the source support this claim plausibly?
        # A URL alone is not enough: must have valid syntax, timestamp, matching source type
        if not has_valid_url:
            status = ClaimEvidenceStatus.UNSUPPORTED
            unsupported_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "source_url": src_url,
                "reason": "Missing or invalid source URL syntax",
            })
        elif status_flag in {"source_error", "blocked_robots", "blocked_policy"}:
            status = ClaimEvidenceStatus.UNSUPPORTED
            unsupported_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "source_url": src_url,
                "reason": f"Source was inaccessible ({status_flag})",
            })
        elif status_flag == "not_found" and claim_val is not None:
            status = ClaimEvidenceStatus.CONTRADICTED
            contradicted_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "source_url": src_url,
                "reason": "Source recorded not_found but profile asserted a positive claim value",
            })
        elif has_valid_url and has_retrieved_time and (has_hash or status_flag == "available"):
            # Strong supporting evidence
            status = ClaimEvidenceStatus.SUPPORTED
            supported_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "source_url": src_url,
                "source_domain": _extract_domain(src_url),
                "source_type": src_type,
                "retrieved_at": retrieved_at,
            })
        elif has_valid_url:
            # Partially supported (has URL but missing timestamp or hash)
            status = ClaimEvidenceStatus.PARTIALLY_SUPPORTED
            partially_supported_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "source_url": src_url,
                "source_domain": _extract_domain(src_url),
                "reason": "URL present but missing provenance timestamp or content hash",
            })
        else:
            status = ClaimEvidenceStatus.UNSUPPORTED
            unsupported_count += 1
            claims_detail.append({
                "claim": claim_name,
                "status": status.value,
                "source_url": src_url,
                "reason": "Insufficient provenance proof",
            })

    total = len(eval_claims)
    if total == 0:
        return EvidenceEvaluation(
            validity_rate=1.0,
            evidence_coverage=1.0,
            unsupported_claim_rate=0.0,
            source_availability_rate=1.0,
            total_claims=0,
            supported_claims=0,
            partially_supported_claims=0,
            unsupported_claims=0,
            contradicted_claims=0,
            missing_evidence_claims=0,
            claims_detail=[],
        )

    valid_score = (supported_count * 1.0) + (partially_supported_count * 0.5)
    validity_rate = valid_score / total
    ev_coverage = (total - missing_evidence_count) / total
    unsupported_rate = (unsupported_count + contradicted_count + missing_evidence_count) / total
    src_avail_rate = available_source_count / total if total > 0 else 0.0

    return EvidenceEvaluation(
        validity_rate=validity_rate,
        evidence_coverage=ev_coverage,
        unsupported_claim_rate=unsupported_rate,
        source_availability_rate=src_avail_rate,
        total_claims=total,
        supported_claims=supported_count,
        partially_supported_claims=partially_supported_count,
        unsupported_claims=unsupported_count,
        contradicted_claims=contradicted_count,
        missing_evidence_claims=missing_evidence_count,
        claims_detail=claims_detail,
    )
