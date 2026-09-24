"""Stage 18: Competition Evaluation Data Models.

Defines strongly-typed, serialization-ready models for evaluating OrgTrace:
- Identity evaluation & classifications
- Coverage breakdowns across 13 categories
- Evidence validity & claim provenance verification
- Freshness & change intelligence verification
- Explanation quality & grounding
- Monotonic runtime performance
- Outbound request & domain tracking
- Token & API cost accounting
- Failure tracking & resilience
- Run metadata & composite summaries
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any


class IdentityStatus(str, Enum):
    """Authoritative identity classification states."""
    EXACT_MATCH = "exact_match"
    PROBABLE_MATCH = "probable_match"
    AMBIGUOUS = "ambiguous"
    WRONG_COMPANY = "wrong_company"
    NOT_FOUND = "not_found"


class CoverageFieldStatus(str, Enum):
    """Standardized coverage status per field."""
    FOUND = "found"
    MISSING = "missing"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ClaimEvidenceStatus(str, Enum):
    """Categorized validity of an evidence claim."""
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    MISSING_EVIDENCE = "missing_evidence"


class CompanyEvaluationResultState(str, Enum):
    """Terminal outcome of an individual company evaluation."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    IDENTITY_FAILURE = "identity_failure"
    EVALUATION_ERROR = "evaluation_error"


@dataclass
class IdentityEvaluation:
    """Detailed identity accuracy assessment."""
    status: IdentityStatus
    expected_org_number: str | None
    observed_org_number: str | None
    name_match: bool
    website_match: bool
    accuracy: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "expected_org_number": self.expected_org_number,
            "observed_org_number": self.observed_org_number,
            "name_match": self.name_match,
            "website_match": self.website_match,
            "accuracy": round(self.accuracy, 4),
            "notes": list(self.notes),
        }


@dataclass
class CoverageCategoryBreakdown:
    """Coverage counts and rate for a single category."""
    found: int = 0
    missing: int = 0
    invalid: int = 0
    unknown: int = 0
    not_applicable: int = 0
    rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "missing": self.missing,
            "invalid": self.invalid,
            "unknown": self.unknown,
            "not_applicable": self.not_applicable,
            "rate": round(self.rate, 4),
        }


@dataclass
class CoverageEvaluation:
    """Comprehensive coverage breakdown across categories."""
    rate: float = 0.0
    field_coverage_rate: float = 0.0
    category_coverage_rate: float = 0.0
    found_fields_count: int = 0
    missing_fields_count: int = 0
    invalid_fields_count: int = 0
    missing_fields: list[str] = field(default_factory=list)
    invalid_fields: list[str] = field(default_factory=list)
    categories: dict[str, dict[str, int | float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": round(self.rate, 4),
            "field_coverage_rate": round(self.field_coverage_rate, 4),
            "category_coverage_rate": round(self.category_coverage_rate, 4),
            "found_fields_count": self.found_fields_count,
            "missing_fields_count": self.missing_fields_count,
            "invalid_fields_count": self.invalid_fields_count,
            "missing_fields": list(self.missing_fields),
            "invalid_fields": list(self.invalid_fields),
            "categories": self.categories,
        }


@dataclass
class EvidenceEvaluation:
    """Assessment of evidence attachment and plausibility."""
    validity_rate: float = 0.0
    evidence_coverage: float = 0.0
    unsupported_claim_rate: float = 0.0
    source_availability_rate: float = 0.0
    total_claims: int = 0
    supported_claims: int = 0
    partially_supported_claims: int = 0
    unsupported_claims: int = 0
    contradicted_claims: int = 0
    missing_evidence_claims: int = 0
    claims_detail: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validity_rate": round(self.validity_rate, 4),
            "evidence_coverage": round(self.evidence_coverage, 4),
            "unsupported_claim_rate": round(self.unsupported_claim_rate, 4),
            "source_availability_rate": round(self.source_availability_rate, 4),
            "total_claims": self.total_claims,
            "supported_claims": self.supported_claims,
            "partially_supported_claims": self.partially_supported_claims,
            "unsupported_claims": self.unsupported_claims,
            "contradicted_claims": self.contradicted_claims,
            "missing_evidence_claims": self.missing_evidence_claims,
            "claims_detail": self.claims_detail,
        }


@dataclass
class FreshnessEvaluation:
    """Assessment of detected changes against historical ground truth."""
    status: str = "unavailable"  # "evaluated" or "unavailable"
    reason: str | None = None
    changes_detected: int = 0
    precision: float | None = None
    recall: float | None = None
    false_positives: int = 0
    missed_changes: int = 0
    unchanged_preserved: int = 0
    detected_changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "status": self.status,
            "changes_detected": self.changes_detected,
        }
        if self.reason is not None:
            data["reason"] = self.reason
        if self.precision is not None:
            data["precision"] = round(self.precision, 4)
        else:
            data["precision"] = None
        if self.recall is not None:
            data["recall"] = round(self.recall, 4)
        else:
            data["recall"] = None
        data["false_positives"] = self.false_positives
        data["missed_changes"] = self.missed_changes
        data["unchanged_preserved"] = self.unchanged_preserved
        data["detected_changes"] = self.detected_changes
        return data


@dataclass
class ExplanationEvaluation:
    """Assessment of explanation grounding and evidence references."""
    grounding_rate: float = 0.0
    evidence_reference_rate: float = 0.0
    unsupported_rate: float = 0.0
    explanations_present: int = 0
    explanations_evaluated: int = 0
    claims_grounded: int = 0
    evidence_referenced: int = 0
    uncertainty_handled: int = 0
    unsupported_statements_detected: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounding_rate": round(self.grounding_rate, 4),
            "evidence_reference_rate": round(self.evidence_reference_rate, 4),
            "unsupported_rate": round(self.unsupported_rate, 4),
            "explanations_present": self.explanations_present,
            "explanations_evaluated": self.explanations_evaluated,
            "claims_grounded": self.claims_grounded,
            "evidence_referenced": self.evidence_referenced,
            "uncertainty_handled": self.uncertainty_handled,
            "unsupported_statements_detected": self.unsupported_statements_detected,
            "details": self.details,
        }


@dataclass
class PerformanceEvaluation:
    """Monotonic execution latency."""
    runtime_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_ms": round(self.runtime_ms, 2),
        }


@dataclass
class RequestEvaluation:
    """Outbound request instrumentation."""
    total: int = 0
    requests_by_domain: dict[str, int] = field(default_factory=dict)
    requests_by_type: dict[str, int] = field(default_factory=dict)
    failed: int = 0
    retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "requests_by_domain": self.requests_by_domain,
            "requests_by_type": self.requests_by_type,
            "failed": self.failed,
            "retries": self.retries,
        }


@dataclass
class CostEvaluation:
    """LLM and API cost accounting."""
    status: str = "unavailable"  # "available" or "unavailable"
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6) if self.estimated_cost_usd is not None else None,
        }


@dataclass
class CompanyEvaluationRecord:
    """Comprehensive evaluation record for a single company."""
    case_id: str
    query: str
    identity: IdentityEvaluation
    coverage: CoverageEvaluation
    evidence: EvidenceEvaluation
    updates: FreshnessEvaluation
    explanations: ExplanationEvaluation
    performance: PerformanceEvaluation
    requests: RequestEvaluation
    cost: CostEvaluation
    result: str  # "success", "partial_success", "failed", "timeout", "identity_failure", "evaluation_error"
    failure: dict[str, Any] | None = None
    raw_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "case_id": self.case_id,
            "query": self.query,
            "identity": self.identity.to_dict(),
            "coverage": self.coverage.to_dict(),
            "evidence": self.evidence.to_dict(),
            "updates": self.updates.to_dict(),
            "explanations": self.explanations.to_dict(),
            "performance": self.performance.to_dict(),
            "requests": self.requests.to_dict(),
            "cost": self.cost.to_dict(),
            "result": self.result,
        }
        if self.failure is not None:
            data["failure"] = self.failure
        return data

    def to_flat_dict(self) -> dict[str, Any]:
        """Flatten record for CSV representation."""
        return {
            "case_id": self.case_id,
            "query": self.query,
            "expected_org": self.identity.expected_org_number or "",
            "observed_org": self.identity.observed_org_number or "",
            "identity_status": self.identity.status.value,
            "identity_accuracy": round(self.identity.accuracy, 4),
            "coverage_rate": round(self.coverage.rate, 4),
            "missing_fields_count": len(self.coverage.missing_fields),
            "evidence_validity_rate": round(self.evidence.validity_rate, 4),
            "evidence_coverage": round(self.evidence.evidence_coverage, 4),
            "unsupported_claims": self.evidence.unsupported_claims,
            "freshness_status": self.updates.status,
            "changes_detected": self.updates.changes_detected,
            "explanation_grounding_rate": round(self.explanations.grounding_rate, 4),
            "runtime_ms": round(self.performance.runtime_ms, 2),
            "requests_total": self.requests.total,
            "requests_failed": self.requests.failed,
            "llm_calls": self.cost.llm_calls,
            "total_tokens": self.cost.total_tokens,
            "estimated_cost_usd": self.cost.estimated_cost_usd if self.cost.estimated_cost_usd is not None else "",
            "result": self.result,
            "failure_type": self.failure.get("type", "") if self.failure else "",
        }


@dataclass
class EvaluationSummary:
    """Transparent summary exposing all major evaluation dimensions independently."""
    companies_evaluated: int = 0
    coverage_rate: float = 0.0
    field_coverage_rate: float = 0.0
    category_coverage_rate: float = 0.0
    identity_accuracy: float = 0.0
    wrong_company_rate: float = 0.0
    ambiguous_identity_rate: float = 0.0
    evidence_validity_rate: float = 0.0
    evidence_coverage: float = 0.0
    unsupported_claim_rate: float = 0.0
    change_detection_precision: float | None = None
    change_detection_recall: float | None = None
    explanation_grounding_rate: float = 0.0
    explanation_evidence_reference_rate: float = 0.0
    unsupported_explanation_rate: float = 0.0
    success_rate: float = 0.0
    partial_success_rate: float = 0.0
    failure_rate: float = 0.0
    timeout_rate: float = 0.0
    identity_failure_rate: float = 0.0
    total_runtime_ms: float = 0.0
    average_runtime_ms: float = 0.0
    median_runtime_ms: float = 0.0
    p95_runtime_ms: float = 0.0
    min_runtime_ms: float = 0.0
    max_runtime_ms: float = 0.0
    total_requests: int = 0
    average_requests_per_company: float = 0.0
    requests_by_domain: dict[str, int] = field(default_factory=dict)
    failed_requests: int = 0
    retry_count: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    top_failure_categories: dict[str, int] = field(default_factory=dict)
    worst_performing_fields: list[dict[str, Any]] = field(default_factory=list)
    companies_requiring_investigation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "companies_evaluated": self.companies_evaluated,
            "coverage_rate": round(self.coverage_rate, 4),
            "field_coverage_rate": round(self.field_coverage_rate, 4),
            "category_coverage_rate": round(self.category_coverage_rate, 4),
            "identity_accuracy": round(self.identity_accuracy, 4),
            "wrong_company_rate": round(self.wrong_company_rate, 4),
            "ambiguous_identity_rate": round(self.ambiguous_identity_rate, 4),
            "evidence_validity_rate": round(self.evidence_validity_rate, 4),
            "evidence_coverage": round(self.evidence_coverage, 4),
            "unsupported_claim_rate": round(self.unsupported_claim_rate, 4),
            "change_detection_precision": round(self.change_detection_precision, 4) if self.change_detection_precision is not None else None,
            "change_detection_recall": round(self.change_detection_recall, 4) if self.change_detection_recall is not None else None,
            "explanation_grounding_rate": round(self.explanation_grounding_rate, 4),
            "explanation_evidence_reference_rate": round(self.explanation_evidence_reference_rate, 4),
            "unsupported_explanation_rate": round(self.unsupported_explanation_rate, 4),
            "success_rate": round(self.success_rate, 4),
            "partial_success_rate": round(self.partial_success_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
            "identity_failure_rate": round(self.identity_failure_rate, 4),
            "total_runtime_ms": round(self.total_runtime_ms, 2),
            "average_runtime_ms": round(self.average_runtime_ms, 2),
            "median_runtime_ms": round(self.median_runtime_ms, 2),
            "p95_runtime_ms": round(self.p95_runtime_ms, 2),
            "min_runtime_ms": round(self.min_runtime_ms, 2),
            "max_runtime_ms": round(self.max_runtime_ms, 2),
            "total_requests": self.total_requests,
            "average_requests_per_company": round(self.average_requests_per_company, 2),
            "requests_by_domain": self.requests_by_domain,
            "failed_requests": self.failed_requests,
            "retry_count": self.retry_count,
            "total_llm_calls": self.total_llm_calls,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6) if self.estimated_cost_usd is not None else None,
            "top_failure_categories": self.top_failure_categories,
            "worst_performing_fields": self.worst_performing_fields,
            "companies_requiring_investigation": list(self.companies_requiring_investigation),
        }


@dataclass
class EvaluationRunMetadata:
    """Provenance and reproduction metadata for an evaluation run."""
    timestamp: str
    seed: int | None
    dataset: str
    dataset_hash: str
    git_commit: str | None
    companies_requested: int
    companies_evaluated: int
    configuration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "seed": self.seed,
            "dataset": self.dataset,
            "dataset_hash": self.dataset_hash,
            "git_commit": self.git_commit,
            "companies_requested": self.companies_requested,
            "companies_evaluated": self.companies_evaluated,
            "configuration": self.configuration,
        }


@dataclass
class CompetitionEvaluationReport:
    """Full machine-readable and reproducible competition evaluation artifact."""
    run: EvaluationRunMetadata
    summary: EvaluationSummary
    companies: list[CompanyEvaluationRecord]
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "summary": self.summary.to_dict(),
            "companies": [c.to_dict() for c in self.companies],
            "failures": self.failures,
        }
