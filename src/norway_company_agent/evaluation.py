"""Stage 10: Evaluation & Optimization.

Provides a reproducible evaluation and benchmarking layer measuring:
1. Coverage (evaluated cases, usable results, field-level coverage, distinction between missing/failed/incorrect)
2. Exact-company precision (legal names, aliases, subsidiaries, similarly named, conflicting signals)
3. External precision (relevance of external entities/sources, true matches vs false positives)
4. Recall (expected relevant information/entities found, with explicit boundary documentation)
5. Evidence validity (URL syntax, source correspondence, provenance completeness, validity rate)
6. Refresh correctness (unchanged, modified, added, removed, failed-refresh preservation)
7. False-change rate (material changes vs formatting/whitespace/ordering/timestamp noise)
8. Runtime instrumentation (monotonic timing, per-stage, per-engine, p50/p95/max latencies)
9. Request count (total, per case, per engine, failed, retries, duplicate requests)
10. Cost model (configurable pricing, requests, token usage, estimated provider cost, unknown cost)
11. Bottleneck analysis (slowest engines, highest-request engines, duplicate requests, actionable recommendations)
12. Evaluation report (machine-readable dict and human-readable markdown)
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
import time
from typing import Any, Callable
import urllib.parse

from .change_intelligence import (
    ChangeType,
    MaterialChangeRecord,
    is_material_change,
    normalize_semantic_value,
)
from .evaluation_dataset import (
    CaseCategory,
    EvaluationCase,
    ExpectedOutcome,
    build_deterministic_evaluation_dataset,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# 1. METRICS DATA MODELS
# ============================================================================

@dataclass
class FieldCoverageMetrics:
    """Field-level coverage breakdown."""
    total_fields_evaluated: int = 0
    fields_present: int = 0
    fields_missing_allowed: int = 0
    fields_retrieval_failed: int = 0
    fields_incorrect: int = 0
    field_coverage_rate: float = 0.0
    field_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_fields_evaluated": self.total_fields_evaluated,
            "fields_present": self.fields_present,
            "fields_missing_allowed": self.fields_missing_allowed,
            "fields_retrieval_failed": self.fields_retrieval_failed,
            "fields_incorrect": self.fields_incorrect,
            "field_coverage_rate": round(self.field_coverage_rate, 4),
            "field_breakdown": self.field_breakdown,
        }


@dataclass
class CoverageMetrics:
    """Overall coverage metrics across evaluated cases."""
    total_cases: int = 0
    usable_results: int = 0
    usable_result_rate: float = 0.0
    field_coverage: FieldCoverageMetrics = field(default_factory=FieldCoverageMetrics)
    unusable_cases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "usable_results": self.usable_results,
            "usable_result_rate": round(self.usable_result_rate, 4),
            "field_coverage": self.field_coverage.to_dict(),
            "unusable_cases": list(self.unusable_cases),
        }


@dataclass
class PrecisionMetrics:
    """Exact-company precision metrics."""
    total_evaluations: int = 0
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    precision: float = 1.0
    recall: float = 1.0
    f1_score: float = 1.0
    exact_matches: int = 0
    alias_matches: int = 0
    subsidiaries_correct: int = 0
    similarly_named_rejected: int = 0
    conflicting_signals_handled: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "exact_matches": self.exact_matches,
            "alias_matches": self.alias_matches,
            "subsidiaries_correct": self.subsidiaries_correct,
            "similarly_named_rejected": self.similarly_named_rejected,
            "conflicting_signals_handled": self.conflicting_signals_handled,
            "notes": list(self.notes),
        }


@dataclass
class ExternalPrecisionMetrics:
    """External entity and source precision metrics."""
    total_external_evaluations: int = 0
    true_external_matches: int = 0
    false_external_positives: int = 0
    precision: float = 1.0
    unrelated_domains_detected: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_external_evaluations": self.total_external_evaluations,
            "true_external_matches": self.true_external_matches,
            "false_external_positives": self.false_external_positives,
            "precision": round(self.precision, 4),
            "unrelated_domains_detected": list(self.unrelated_domains_detected),
        }


@dataclass
class RecallMetrics:
    """Recall metrics for expected information/entities."""
    total_expected_items: int = 0
    found_expected_items: int = 0
    missed_items: list[str] = field(default_factory=list)
    recall_rate: float = 1.0
    boundary_documentation: str = (
        "Recall is bounded to Norwegian statutory registry (Brønnøysundregistrene/Enhetsregisteret) "
        "and official company domains discovered via deterministic domain matching."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_expected_items": self.total_expected_items,
            "found_expected_items": self.found_expected_items,
            "missed_items": list(self.missed_items),
            "recall_rate": round(self.recall_rate, 4),
            "boundary_documentation": self.boundary_documentation,
        }


@dataclass
class EvidenceValidityMetrics:
    """Validation results for provenance and evidence citations."""
    total_evidence_items: int = 0
    valid_syntax_urls: int = 0
    valid_source_types: int = 0
    provenance_complete: int = 0
    invalid_evidence_items: list[dict[str, Any]] = field(default_factory=list)
    validity_rate: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evidence_items": self.total_evidence_items,
            "valid_syntax_urls": self.valid_syntax_urls,
            "valid_source_types": self.valid_source_types,
            "provenance_complete": self.provenance_complete,
            "invalid_evidence_items": list(self.invalid_evidence_items),
            "validity_rate": round(self.validity_rate, 4),
        }


@dataclass
class RefreshCorrectnessMetrics:
    """Metrics measuring refresh intelligence correctness."""
    total_refresh_comparisons: int = 0
    correctly_unchanged: int = 0
    correctly_modified: int = 0
    correctly_added: int = 0
    correctly_removed: int = 0
    correctly_preserved_failures: int = 0
    formatting_noise_rejected: int = 0
    accuracy: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_refresh_comparisons": self.total_refresh_comparisons,
            "correctly_unchanged": self.correctly_unchanged,
            "correctly_modified": self.correctly_modified,
            "correctly_added": self.correctly_added,
            "correctly_removed": self.correctly_removed,
            "correctly_preserved_failures": self.correctly_preserved_failures,
            "formatting_noise_rejected": self.formatting_noise_rejected,
            "accuracy": round(self.accuracy, 4),
        }


@dataclass
class FalseChangeMetrics:
    """Metrics measuring the rate of false semantic changes."""
    total_detected_changes: int = 0
    true_material_changes: int = 0
    false_changes: int = 0
    false_change_rate: float = 0.0
    false_change_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_detected_changes": self.total_detected_changes,
            "true_material_changes": self.true_material_changes,
            "false_changes": self.false_changes,
            "false_change_rate": round(self.false_change_rate, 4),
            "false_change_details": list(self.false_change_details),
        }


# ============================================================================
# 2. RUNTIME, REQUEST & COST INSTRUMENTATION
# ============================================================================

@dataclass
class RuntimeStats:
    """Execution timing and latency statistics."""
    total_runtime_seconds: float = 0.0
    stage_runtimes: dict[str, float] = field(default_factory=dict)
    engine_runtimes: dict[str, float] = field(default_factory=dict)
    operation_latencies: list[float] = field(default_factory=list)
    avg_latency_seconds: float = 0.0
    p50_latency_seconds: float = 0.0
    p95_latency_seconds: float = 0.0
    max_latency_seconds: float = 0.0
    slowest_operations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runtime_seconds": round(self.total_runtime_seconds, 4),
            "stage_runtimes": {k: round(v, 4) for k, v in self.stage_runtimes.items()},
            "engine_runtimes": {k: round(v, 4) for k, v in self.engine_runtimes.items()},
            "avg_latency_seconds": round(self.avg_latency_seconds, 4),
            "p50_latency_seconds": round(self.p50_latency_seconds, 4),
            "p95_latency_seconds": round(self.p95_latency_seconds, 4),
            "max_latency_seconds": round(self.max_latency_seconds, 4),
            "slowest_operations": list(self.slowest_operations),
        }


@dataclass
class RequestStats:
    """Network and external request telemetry."""
    total_requests: int = 0
    requests_per_engine: dict[str, int] = field(default_factory=dict)
    requests_per_case: dict[str, int] = field(default_factory=dict)
    failed_requests: int = 0
    retries: int = 0
    duplicate_requests: int = 0
    duplicate_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "requests_per_engine": self.requests_per_engine,
            "requests_per_case": self.requests_per_case,
            "failed_requests": self.failed_requests,
            "retries": self.retries,
            "duplicate_requests": self.duplicate_requests,
            "duplicate_urls": list(self.duplicate_urls),
        }


@dataclass
class CostModelConfig:
    """Configurable provider-aware cost parameters."""
    cost_per_request: float = 0.0
    cost_per_1k_prompt_tokens: float = 0.0
    cost_per_1k_completion_tokens: float = 0.0
    currency: str = "USD"
    is_pricing_configured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_per_request": self.cost_per_request,
            "cost_per_1k_prompt_tokens": self.cost_per_1k_prompt_tokens,
            "cost_per_1k_completion_tokens": self.cost_per_1k_completion_tokens,
            "currency": self.currency,
            "is_pricing_configured": self.is_pricing_configured,
        }


@dataclass
class CostStats:
    """Cost modeling statistics."""
    total_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    currency: str = "USD"
    is_pricing_configured: bool = False
    unknown_cost_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": round(self.estimated_cost, 6),
            "currency": self.currency,
            "is_pricing_configured": self.is_pricing_configured,
            "unknown_cost_items": list(self.unknown_cost_items),
        }


@dataclass
class BottleneckObservation:
    """An actionable bottleneck identified during evaluation."""
    category: str
    severity: str
    component: str
    message: str
    actionable_recommendation: str
    measured_metric: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "component": self.component,
            "message": self.message,
            "actionable_recommendation": self.actionable_recommendation,
            "measured_metric": self.measured_metric,
        }


class EvaluationInstrumentation:
    """Monotonic timing and request tracking instrument without business logic interference."""

    def __init__(self, cost_config: CostModelConfig | None = None):
        self.cost_config = cost_config or CostModelConfig()
        self._start_time: float = time.monotonic()
        self._engine_runtimes: dict[str, float] = {}
        self._stage_runtimes: dict[str, float] = {}
        self._operations: list[dict[str, Any]] = []
        self._requests: list[dict[str, Any]] = []
        self._seen_request_keys: set[str] = set()
        self._duplicate_urls: list[str] = []
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._unknown_cost_items: list[str] = []

    @contextmanager
    def measure_operation(self, engine: str, operation: str, stage: str | None = None, metadata: dict[str, Any] | None = None):
        """Record monotonic execution time for an operation."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - t0
            self._engine_runtimes[engine] = self._engine_runtimes.get(engine, 0.0) + elapsed
            if stage:
                self._stage_runtimes[stage] = self._stage_runtimes.get(stage, 0.0) + elapsed
            self._operations.append({
                "engine": engine,
                "operation": operation,
                "stage": stage or "unspecified",
                "duration_seconds": elapsed,
                "metadata": metadata or {},
            })

    def record_request(
        self,
        engine: str,
        url: str,
        case_id: str | None = None,
        method: str = "GET",
        status_code: int = 200,
        is_retry: bool = False,
        is_failed: bool = False,
    ) -> None:
        """Record an external network request, detecting duplicates and failures."""
        key = f"{method}:{url.strip().lower()}"
        is_duplicate = key in self._seen_request_keys
        if is_duplicate:
            self._duplicate_urls.append(url)
        else:
            self._seen_request_keys.add(key)

        self._requests.append({
            "engine": engine,
            "url": url,
            "case_id": case_id or "unspecified",
            "method": method,
            "status_code": status_code,
            "is_retry": is_retry,
            "is_failed": is_failed,
            "is_duplicate": is_duplicate,
        })

    def record_tokens(self, prompt_tokens: int, completion_tokens: int, source: str | None = None) -> None:
        """Record token consumption for an operation."""
        self._prompt_tokens += max(0, prompt_tokens)
        self._completion_tokens += max(0, completion_tokens)
        if not self.cost_config.is_pricing_configured:
            item = f"{source or 'llm'}: {prompt_tokens}p + {completion_tokens}c tokens"
            if item not in self._unknown_cost_items:
                self._unknown_cost_items.append(item)

    def get_runtime_stats(self) -> RuntimeStats:
        """Compute runtime statistics from monotonic measurements."""
        total_time = time.monotonic() - self._start_time
        latencies = [op["duration_seconds"] for op in self._operations]
        sorted_latencies = sorted(latencies)

        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        p50_lat = 0.0
        p95_lat = 0.0
        max_lat = max(latencies) if latencies else 0.0

        if sorted_latencies:
            idx_50 = int(len(sorted_latencies) * 0.50)
            idx_95 = min(int(len(sorted_latencies) * 0.95), len(sorted_latencies) - 1)
            p50_lat = sorted_latencies[idx_50]
            p95_lat = sorted_latencies[idx_95]

        slowest = sorted(self._operations, key=lambda x: x["duration_seconds"], reverse=True)[:5]

        return RuntimeStats(
            total_runtime_seconds=total_time,
            stage_runtimes=dict(self._stage_runtimes),
            engine_runtimes=dict(self._engine_runtimes),
            operation_latencies=latencies,
            avg_latency_seconds=avg_lat,
            p50_latency_seconds=p50_lat,
            p95_latency_seconds=p95_lat,
            max_latency_seconds=max_lat,
            slowest_operations=slowest,
        )

    def get_request_stats(self) -> RequestStats:
        """Compute network request statistics."""
        reqs_per_engine: dict[str, int] = {}
        reqs_per_case: dict[str, int] = {}
        failed = 0
        retries = 0
        duplicates = 0

        for r in self._requests:
            eng = r["engine"]
            cid = r["case_id"]
            reqs_per_engine[eng] = reqs_per_engine.get(eng, 0) + 1
            reqs_per_case[cid] = reqs_per_case.get(cid, 0) + 1
            if r["is_failed"]:
                failed += 1
            if r["is_retry"]:
                retries += 1
            if r["is_duplicate"]:
                duplicates += 1

        return RequestStats(
            total_requests=len(self._requests),
            requests_per_engine=reqs_per_engine,
            requests_per_case=reqs_per_case,
            failed_requests=failed,
            retries=retries,
            duplicate_requests=duplicates,
            duplicate_urls=list(set(self._duplicate_urls)),
        )

    def get_cost_stats(self) -> CostStats:
        """Compute estimated cost based on configured pricing."""
        total_reqs = len(self._requests)
        total_toks = self._prompt_tokens + self._completion_tokens

        estimated_cost = 0.0
        if self.cost_config.is_pricing_configured:
            req_cost = total_reqs * self.cost_config.cost_per_request
            prompt_cost = (self._prompt_tokens / 1000.0) * self.cost_config.cost_per_1k_prompt_tokens
            completion_cost = (self._completion_tokens / 1000.0) * self.cost_config.cost_per_1k_completion_tokens
            estimated_cost = req_cost + prompt_cost + completion_cost
        else:
            if total_reqs > 0 and self.cost_config.cost_per_request == 0.0:
                self._unknown_cost_items.append(f"{total_reqs} HTTP requests (no per-request pricing configured)")

        return CostStats(
            total_requests=total_reqs,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            total_tokens=total_toks,
            estimated_cost=estimated_cost,
            currency=self.cost_config.currency,
            is_pricing_configured=self.cost_config.is_pricing_configured,
            unknown_cost_items=list(self._unknown_cost_items),
        )


# ============================================================================
# 3. METRIC EVALUATION LOGIC
# ============================================================================

def evaluate_coverage(
    cases: list[EvaluationCase],
    results: list[dict[str, Any]],
) -> CoverageMetrics:
    """Evaluate overall and field-level coverage."""
    if not cases:
        return CoverageMetrics()

    results_by_case = {r.get("case_id"): r for r in results if r.get("case_id")}
    total_cases = len(cases)
    usable_results = 0
    unusable_cases: list[str] = []

    total_fields = 0
    fields_present = 0
    fields_missing_allowed = 0
    fields_retrieval_failed = 0
    fields_incorrect = 0
    breakdown: dict[str, dict[str, int]] = {}

    target_fields = ["organisation_number", "name", "website", "financials", "leadership"]

    for case in cases:
        cid = case.case_id
        res = results_by_case.get(cid)
        gt = case.ground_truth

        # Check usable result status
        status = res.get("status") if res else "missing_output"
        is_usable = status not in ("failed", "missing_output", "error")
        if is_usable:
            usable_results += 1
        else:
            unusable_cases.append(cid)

        # Field-level evaluation
        for f in target_fields:
            total_fields += 1
            if f not in breakdown:
                breakdown[f] = {"present": 0, "allowed_missing": 0, "failed": 0, "incorrect": 0}

            if not res or res.get("status") in ("failed", "error", "missing_output"):
                if f in gt.allowed_missing_fields:
                    fields_missing_allowed += 1
                    breakdown[f]["allowed_missing"] += 1
                else:
                    fields_retrieval_failed += 1
                    breakdown[f]["failed"] += 1
                continue

            val = res.get(f)
            allowed_missing = f in gt.allowed_missing_fields

            if f == "organisation_number":
                exp = gt.expected_org_number
                if exp is None:
                    if val is None:
                        fields_missing_allowed += 1
                        breakdown[f]["allowed_missing"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1
                else:
                    if val == exp:
                        fields_present += 1
                        breakdown[f]["present"] += 1
                    elif val is None:
                        fields_retrieval_failed += 1
                        breakdown[f]["failed"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1

            elif f == "name":
                exp = gt.expected_name
                if exp is None:
                    if val is None:
                        fields_missing_allowed += 1
                        breakdown[f]["allowed_missing"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1
                else:
                    if val and normalize_semantic_value(val) == normalize_semantic_value(exp):
                        fields_present += 1
                        breakdown[f]["present"] += 1
                    elif val is None:
                        fields_retrieval_failed += 1
                        breakdown[f]["failed"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1

            elif f == "website":
                if not gt.should_publish_website:
                    if val is None:
                        fields_missing_allowed += 1
                        breakdown[f]["allowed_missing"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1
                else:
                    if val and normalize_semantic_value(val) == normalize_semantic_value(gt.expected_website):
                        fields_present += 1
                        breakdown[f]["present"] += 1
                    elif val is None:
                        fields_retrieval_failed += 1
                        breakdown[f]["failed"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1

            elif f == "financials":
                if not gt.should_have_financials:
                    if val is None or (isinstance(val, dict) and not val.get("revenue")):
                        fields_missing_allowed += 1
                        breakdown[f]["allowed_missing"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1
                else:
                    if val and (val.get("revenue") is not None or val.get("has_accounts")):
                        fields_present += 1
                        breakdown[f]["present"] += 1
                    elif val is None:
                        fields_retrieval_failed += 1
                        breakdown[f]["failed"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1

            elif f == "leadership":
                if not gt.expected_leadership:
                    if not val or allowed_missing:
                        fields_missing_allowed += 1
                        breakdown[f]["allowed_missing"] += 1
                    else:
                        fields_present += 1
                        breakdown[f]["present"] += 1
                else:
                    # check if expected leadership members found
                    roles_found = [str(x).lower() for x in (val or [])]
                    all_found = all(any(m.lower() in rf for rf in roles_found) for m in gt.expected_leadership)
                    if all_found:
                        fields_present += 1
                        breakdown[f]["present"] += 1
                    elif not val:
                        fields_retrieval_failed += 1
                        breakdown[f]["failed"] += 1
                    else:
                        fields_incorrect += 1
                        breakdown[f]["incorrect"] += 1

    field_cov_rate = (fields_present + fields_missing_allowed) / total_fields if total_fields > 0 else 1.0

    return CoverageMetrics(
        total_cases=total_cases,
        usable_results=usable_results,
        usable_result_rate=usable_results / total_cases if total_cases > 0 else 0.0,
        field_coverage=FieldCoverageMetrics(
            total_fields_evaluated=total_fields,
            fields_present=fields_present,
            fields_missing_allowed=fields_missing_allowed,
            fields_retrieval_failed=fields_retrieval_failed,
            fields_incorrect=fields_incorrect,
            field_coverage_rate=field_cov_rate,
            field_breakdown=breakdown,
        ),
        unusable_cases=unusable_cases,
    )


def evaluate_exact_precision(
    cases: list[EvaluationCase],
    results: list[dict[str, Any]],
) -> PrecisionMetrics:
    """Evaluate exact-company identification precision and abstention handling."""
    results_by_case = {r.get("case_id"): r for r in results if r.get("case_id")}

    tp = 0
    fp = 0
    tn = 0
    fn = 0
    exact_m = 0
    alias_m = 0
    subsidiaries_ok = 0
    similarly_rejected = 0
    conflicting_ok = 0
    notes: list[str] = []

    for case in cases:
        cid = case.case_id
        res = results_by_case.get(cid, {})
        gt = case.ground_truth
        cat = case.category

        actual_org = res.get("organisation_number")
        actual_status = res.get("verdict_status", "unknown")

        is_target_expected = gt.expected_org_number is not None and gt.expected_verdict_status == "verified"

        if is_target_expected:
            if actual_org == gt.expected_org_number and actual_status == "verified":
                tp += 1
                if cat == CaseCategory.EXACT_COMPANY:
                    exact_m += 1
                elif cat == CaseCategory.SUBSIDIARY:
                    subsidiaries_ok += 1
                elif "alias" in case.metadata:
                    alias_m += 1
            else:
                if actual_org and actual_org != gt.expected_org_number:
                    fp += 1
                    notes.append(f"{cid}: Selected wrong entity {actual_org} != {gt.expected_org_number}")
                else:
                    fn += 1
                    notes.append(f"{cid}: Missed expected entity {gt.expected_org_number}")
        else:
            # Expected not found / ambiguous / rejected
            if actual_status in ("ambiguous", "rejected", "not_found", "abstain") or actual_org is None:
                tn += 1
                if cat == CaseCategory.SIMILARLY_NAMED:
                    similarly_rejected += 1
                elif cat == CaseCategory.AMBIGUOUS_NAME:
                    conflicting_ok += 1
            else:
                fp += 1
                notes.append(f"{cid}: False positive verification on negative case (verified {actual_org})")

    total_evals = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fp == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return PrecisionMetrics(
        total_evaluations=total_evals,
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1_score=f1,
        exact_matches=exact_m,
        alias_matches=alias_m,
        subsidiaries_correct=subsidiaries_ok,
        similarly_named_rejected=similarly_rejected,
        conflicting_signals_handled=conflicting_ok,
        notes=notes,
    )


def evaluate_external_precision(
    cases: list[EvaluationCase],
    results: list[dict[str, Any]],
) -> ExternalPrecisionMetrics:
    """Evaluate external entities, domains, and sources relevance."""
    results_by_case = {r.get("case_id"): r for r in results if r.get("case_id")}
    total_external = 0
    true_matches = 0
    false_positives = 0
    unrelated_domains: list[str] = []

    for case in cases:
        cid = case.case_id
        res = results_by_case.get(cid, {})
        gt = case.ground_truth

        # Check external non-target abstention
        if not gt.is_external_target:
            total_external += 1
            if res.get("verdict_status") in ("rejected", "not_found", "abstain"):
                true_matches += 1
            else:
                false_positives += 1
                unrelated_domains.append(f"{cid}: failed to reject non-target external company")

        # Check discovered website relevance
        discovered_web = res.get("website")
        if discovered_web:
            total_external += 1
            if gt.should_publish_website:
                if normalize_semantic_value(discovered_web) == normalize_semantic_value(gt.expected_website):
                    true_matches += 1
                else:
                    false_positives += 1
                    unrelated_domains.append(f"{cid}: discovered unrelated website {discovered_web}")
            else:
                # Should not have website
                false_positives += 1
                unrelated_domains.append(f"{cid}: hallucinated website {discovered_web} for weak web entity")

    precision = true_matches / (true_matches + false_positives) if (true_matches + false_positives) > 0 else 1.0

    return ExternalPrecisionMetrics(
        total_external_evaluations=total_external,
        true_external_matches=true_matches,
        false_external_positives=false_positives,
        precision=precision,
        unrelated_domains_detected=unrelated_domains,
    )


def evaluate_recall(
    cases: list[EvaluationCase],
    results: list[dict[str, Any]],
) -> RecallMetrics:
    """Evaluate whether all expected verified entities and fields were found."""
    results_by_case = {r.get("case_id"): r for r in results if r.get("case_id")}

    total_expected = 0
    found_expected = 0
    missed: list[str] = []

    for case in cases:
        cid = case.case_id
        res = results_by_case.get(cid, {})
        gt = case.ground_truth

        if gt.expected_org_number:
            total_expected += 1
            if res.get("organisation_number") == gt.expected_org_number:
                found_expected += 1
            else:
                missed.append(f"{cid}: missed org_number {gt.expected_org_number}")

        if gt.should_publish_website and gt.expected_website:
            total_expected += 1
            if res.get("website") and normalize_semantic_value(res.get("website")) == normalize_semantic_value(gt.expected_website):
                found_expected += 1
            else:
                missed.append(f"{cid}: missed expected website {gt.expected_website}")

        if gt.should_have_financials:
            total_expected += 1
            fin = res.get("financials")
            if fin and (fin.get("revenue") is not None or fin.get("has_accounts")):
                found_expected += 1
            else:
                missed.append(f"{cid}: missed statutory financials")

        for lead in gt.expected_leadership:
            total_expected += 1
            roles = [str(x).lower() for x in (res.get("leadership") or [])]
            if any(lead.lower() in r for r in roles):
                found_expected += 1
            else:
                missed.append(f"{cid}: missed leadership member {lead}")

    recall_rate = found_expected / total_expected if total_expected > 0 else 1.0

    return RecallMetrics(
        total_expected_items=total_expected,
        found_expected_items=found_expected,
        missed_items=missed,
        recall_rate=recall_rate,
    )


def evaluate_evidence_validity(evidence_items: list[dict[str, Any]] | list[Any]) -> EvidenceValidityMetrics:
    """Validate evidence items and citations for syntax, authority, and provenance."""
    if not evidence_items:
        return EvidenceValidityMetrics()

    valid_url_count = 0
    valid_source_type_count = 0
    provenance_complete_count = 0
    invalid_items: list[dict[str, Any]] = []

    valid_source_types = {
        "registry", "official_registry", "financials", "annual_accounts",
        "roles", "website", "company_website", "external_research", "filings", "news",
    }

    for item in evidence_items:
        # Convert to dict if object
        d = item if isinstance(item, dict) else (item.to_dict() if hasattr(item, "to_dict") else vars(item))
        url = d.get("source_url") or d.get("url")
        source_type = d.get("source_type") or d.get("source_module")
        retrieved_at = d.get("retrieved_at")
        content_hash = d.get("content_sha256") or d.get("content_hash")

        issues: list[str] = []

        # 1. URL syntax validation
        if url:
            try:
                parsed = urllib.parse.urlparse(str(url))
                if parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc:
                    valid_url_count += 1
                else:
                    issues.append(f"Invalid URL scheme or domain: {url}")
            except Exception as e:
                issues.append(f"Malformed URL: {url} ({e})")
        else:
            issues.append("Missing source URL")

        # 2. Source type validation
        if source_type and str(source_type).lower() in valid_source_types:
            valid_source_type_count += 1
        else:
            issues.append(f"Invalid or unrecorded source type: {source_type}")

        # 3. Provenance completeness
        if retrieved_at and content_hash:
            provenance_complete_count += 1
        else:
            if not retrieved_at:
                issues.append("Missing retrieved_at timestamp")
            if not content_hash:
                issues.append("Missing content SHA-256 hash")

        if issues:
            invalid_items.append({
                "item": d,
                "issues": issues,
            })

    total = len(evidence_items)
    # Evidence item is considered fully valid if it passes all three checks
    fully_valid = total - len(invalid_items)
    validity_rate = fully_valid / total if total > 0 else 1.0

    return EvidenceValidityMetrics(
        total_evidence_items=total,
        valid_syntax_urls=valid_url_count,
        valid_source_types=valid_source_type_count,
        provenance_complete=provenance_complete_count,
        invalid_evidence_items=invalid_items,
        validity_rate=validity_rate,
    )


def evaluate_refresh_correctness(
    cases: list[EvaluationCase],
    refresh_results: list[dict[str, Any]],
) -> RefreshCorrectnessMetrics:
    """Evaluate refresh intelligence behavior against ground truth changes."""
    results_by_case = {r.get("case_id"): r for r in refresh_results if r.get("case_id")}

    total_comparisons = 0
    correct_unchanged = 0
    correct_modified = 0
    correct_added = 0
    correct_removed = 0
    correct_preserved = 0
    noise_rejected = 0

    for case in cases:
        cid = case.case_id
        res = results_by_case.get(cid, {})
        gt = case.ground_truth

        changes = res.get("changes", [])
        status = res.get("status", "success")

        total_comparisons += 1

        if status in ("failed_fetch", "partial_failure"):
            # Check failed-refresh preservation: must not emit false removals
            has_removals = any(c.get("change_type") == "removed" for c in changes)
            if not has_removals:
                correct_preserved += 1
            continue

        expected_changes = set(gt.expected_changes)
        actual_change_fields = {c.get("field_name") for c in changes if c.get("change_type") in ("modified", "added")}

        if not expected_changes:
            # Expected UNCHANGED
            if not changes:
                correct_unchanged += 1
                noise_rejected += 1
        else:
            # Expected genuine changes
            if expected_changes.issubset(actual_change_fields):
                correct_modified += 1
            for c in changes:
                ctype = c.get("change_type")
                if ctype == "added":
                    correct_added += 1
                elif ctype == "removed":
                    correct_removed += 1

    accuracy = (correct_unchanged + correct_modified + correct_preserved) / total_comparisons if total_comparisons > 0 else 1.0

    return RefreshCorrectnessMetrics(
        total_refresh_comparisons=total_comparisons,
        correctly_unchanged=correct_unchanged,
        correctly_modified=correct_modified,
        correctly_added=correct_added,
        correctly_removed=correct_removed,
        correctly_preserved_failures=correct_preserved,
        formatting_noise_rejected=noise_rejected,
        accuracy=accuracy,
    )


def calculate_false_change_rate(
    detected_changes: list[Any],
    ground_truth_changes: list[str] | set[str],
) -> FalseChangeMetrics:
    """Calculate the rate of false semantic changes."""
    gt_set = set(ground_truth_changes)
    total_detected = len(detected_changes)
    true_changes = 0
    false_changes = 0
    false_details: list[dict[str, Any]] = []

    for c in detected_changes:
        d = c if isinstance(c, dict) else (c.to_dict() if hasattr(c, "to_dict") else vars(c))
        field_name = d.get("field_name")
        prev_val = d.get("previous_value")
        curr_val = d.get("current_value")

        # Check semantic difference
        if not is_material_change(prev_val, curr_val, field_name):
            false_changes += 1
            false_details.append({
                "field_name": field_name,
                "reason": "formatting/whitespace/ordering noise; not material change",
                "record": d,
            })
        elif field_name not in gt_set:
            false_changes += 1
            false_details.append({
                "field_name": field_name,
                "reason": "unintended change not in ground truth",
                "record": d,
            })
        else:
            true_changes += 1

    rate = false_changes / total_detected if total_detected > 0 else 0.0

    return FalseChangeMetrics(
        total_detected_changes=total_detected,
        true_material_changes=true_changes,
        false_changes=false_changes,
        false_change_rate=rate,
        false_change_details=false_details,
    )


# ============================================================================
# 4. BOTTLENECK ANALYSIS
# ============================================================================

def analyze_bottlenecks(
    runtime_stats: RuntimeStats,
    request_stats: RequestStats,
    cost_stats: CostStats,
) -> list[BottleneckObservation]:
    """Identify expensive, slow, high-request, and failure-heavy components."""
    observations: list[BottleneckObservation] = []

    # 1. Runtime bottlenecks
    total_time = runtime_stats.total_runtime_seconds
    for engine, dur in runtime_stats.engine_runtimes.items():
        ratio = dur / total_time if total_time > 0 else 0.0
        if ratio >= 0.40 and dur >= 0.05:
            observations.append(
                BottleneckObservation(
                    category="runtime",
                    severity="high" if ratio >= 0.60 else "medium",
                    component=engine,
                    message=f"Engine '{engine}' consumes {ratio:.1%} of total execution time ({dur:.3f}s).",
                    actionable_recommendation=(
                        f"Optimize {engine} via parallelization, HTTP response caching, or selective field evaluation."
                    ),
                    measured_metric={"engine": engine, "duration_seconds": dur, "ratio": ratio},
                )
            )

    if runtime_stats.p95_latency_seconds >= 1.0:
        observations.append(
            BottleneckObservation(
                category="runtime",
                severity="medium",
                component="latency_distribution",
                message=f"P95 operation latency is elevated ({runtime_stats.p95_latency_seconds:.3f}s).",
                actionable_recommendation="Implement aggressive HTTP timeouts and concurrency limits on slow upstream calls.",
                measured_metric={"p95_latency": runtime_stats.p95_latency_seconds},
            )
        )

    # 2. Request volume bottlenecks
    total_reqs = request_stats.total_requests
    for engine, count in request_stats.requests_per_engine.items():
        req_ratio = count / total_reqs if total_reqs > 0 else 0.0
        if req_ratio >= 0.50 and count >= 5:
            observations.append(
                BottleneckObservation(
                    category="request_volume",
                    severity="medium",
                    component=engine,
                    message=f"Engine '{engine}' initiates {req_ratio:.1%} of all network requests ({count}/{total_reqs}).",
                    actionable_recommendation=(
                        f"Consolidate external calls in {engine} using bulk endpoints or shared discovery results."
                    ),
                    measured_metric={"engine": engine, "requests": count, "ratio": req_ratio},
                )
            )

    # 3. Duplicate request bottlenecks
    if request_stats.duplicate_requests > 0:
        observations.append(
            BottleneckObservation(
                category="duplicate_requests",
                severity="high",
                component="network_layer",
                message=(
                    f"Detected {request_stats.duplicate_requests} redundant network requests "
                    f"({len(request_stats.duplicate_urls)} distinct duplicate URLs)."
                ),
                actionable_recommendation="Enable an in-memory HTTP cache or request deduplicator before dispatch.",
                measured_metric={
                    "duplicate_count": request_stats.duplicate_requests,
                    "duplicate_urls": request_stats.duplicate_urls,
                },
            )
        )

    # 4. Failure-heavy operations
    if request_stats.failed_requests > 0:
        fail_rate = request_stats.failed_requests / total_reqs if total_reqs > 0 else 0.0
        observations.append(
            BottleneckObservation(
                category="failure_rate",
                severity="high" if fail_rate >= 0.20 else "medium",
                component="http_fetcher",
                message=f"{request_stats.failed_requests} requests failed ({fail_rate:.1%} failure rate).",
                actionable_recommendation="Review HTTP status codes, rate limits, and proxy configurations for failing endpoints.",
                measured_metric={"failed_requests": request_stats.failed_requests, "failure_rate": fail_rate},
            )
        )

    # 5. Cost driver observations
    if cost_stats.is_pricing_configured and cost_stats.estimated_cost >= 1.0:
        observations.append(
            BottleneckObservation(
                category="cost",
                severity="info",
                component="cost_driver",
                message=f"Estimated evaluation cost is ${cost_stats.estimated_cost:.4f} {cost_stats.currency}.",
                actionable_recommendation="Consider caching LLM completions or pruning prompt lengths to reduce token expense.",
                measured_metric={"estimated_cost": cost_stats.estimated_cost, "tokens": cost_stats.total_tokens},
            )
        )

    return observations


# ============================================================================
# 5. EVALUATION REPORT & HARNESS
# ============================================================================

@dataclass
class CaseEvaluationResult:
    """Detailed evaluation result for a single test case."""
    case_id: str
    category: str
    passed: bool
    status: str
    precision_pass: bool
    external_precision_pass: bool
    recall_pass: bool
    evidence_pass: bool
    refresh_pass: bool
    failure_reasons: list[str] = field(default_factory=list)
    measured_runtime_ms: float = 0.0
    request_count: int = 0
    extracted_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "status": self.status,
            "precision_pass": self.precision_pass,
            "external_precision_pass": self.external_precision_pass,
            "recall_pass": self.recall_pass,
            "evidence_pass": self.evidence_pass,
            "refresh_pass": self.refresh_pass,
            "failure_reasons": list(self.failure_reasons),
            "measured_runtime_ms": round(self.measured_runtime_ms, 2),
            "request_count": self.request_count,
            "extracted_data": self.extracted_data,
        }


@dataclass
class EvaluationReport:
    """Comprehensive evaluation and benchmark report."""
    timestamp: str
    dataset_version: str
    total_cases: int
    passed_cases: int
    overall_accuracy: float
    coverage: CoverageMetrics
    exact_precision: PrecisionMetrics
    external_precision: ExternalPrecisionMetrics
    recall: RecallMetrics
    evidence_validity: EvidenceValidityMetrics
    refresh_correctness: RefreshCorrectnessMetrics
    false_change: FalseChangeMetrics
    runtime: RuntimeStats
    requests: RequestStats
    cost: CostStats
    bottlenecks: list[BottleneckObservation]
    case_results: list[CaseEvaluationResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "dataset_version": self.dataset_version,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "overall_accuracy": round(self.overall_accuracy, 4),
            "coverage": self.coverage.to_dict(),
            "exact_precision": self.exact_precision.to_dict(),
            "external_precision": self.external_precision.to_dict(),
            "recall": self.recall.to_dict(),
            "evidence_validity": self.evidence_validity.to_dict(),
            "refresh_correctness": self.refresh_correctness.to_dict(),
            "false_change": self.false_change.to_dict(),
            "runtime": self.runtime.to_dict(),
            "requests": self.requests.to_dict(),
            "cost": self.cost.to_dict(),
            "bottlenecks": [b.to_dict() for b in self.bottlenecks],
            "case_results": [c.to_dict() for c in self.case_results],
        }

    def to_markdown(self) -> str:
        """Render a readable GitHub-flavored markdown report."""
        lines: list[str] = [
            "# OrgTrace Stage 10 Evaluation & Optimization Benchmark Report",
            "",
            f"- **Timestamp**: {self.timestamp}",
            f"- **Dataset Version**: {self.dataset_version}",
            f"- **Overall Cases**: {self.total_cases}",
            f"- **Passed Cases**: {self.passed_cases} ({self.overall_accuracy:.1%})",
            "",
            "## 1. Executive Summary Metrics",
            "",
            "| Metric | Value | Target | Status |",
            "| :--- | :--- | :--- | :--- |",
            f"| **Usable Result Coverage** | {self.coverage.usable_result_rate:.1%} | ≥ 95.0% | {'✅ Pass' if self.coverage.usable_result_rate >= 0.95 else '⚠️ Review'} |",
            f"| **Field Coverage** | {self.coverage.field_coverage.field_coverage_rate:.1%} | ≥ 90.0% | {'✅ Pass' if self.coverage.field_coverage.field_coverage_rate >= 0.90 else '⚠️ Review'} |",
            f"| **Exact-Company Precision** | {self.exact_precision.precision:.1%} | 100.0% | {'✅ Pass' if self.exact_precision.precision >= 1.0 else '❌ Fail'} |",
            f"| **External Precision** | {self.external_precision.precision:.1%} | ≥ 95.0% | {'✅ Pass' if self.external_precision.precision >= 0.95 else '⚠️ Review'} |",
            f"| **Recall** | {self.recall.recall_rate:.1%} | ≥ 90.0% | {'✅ Pass' if self.recall.recall_rate >= 0.90 else '⚠️ Review'} |",
            f"| **Evidence Validity** | {self.evidence_validity.validity_rate:.1%} | 100.0% | {'✅ Pass' if self.evidence_validity.validity_rate >= 1.0 else '❌ Fail'} |",
            f"| **Refresh Correctness** | {self.refresh_correctness.accuracy:.1%} | 100.0% | {'✅ Pass' if self.refresh_correctness.accuracy >= 1.0 else '❌ Fail'} |",
            f"| **False-Change Rate** | {self.false_change.false_change_rate:.1%} | 0.0% | {'✅ Pass' if self.false_change.false_change_rate == 0.0 else '❌ Fail'} |",
            "",
            "## 2. Runtime & Resource Telemetry",
            "",
            f"- **Total Runtime**: {self.runtime.total_runtime_seconds:.4f}s",
            f"- **P50 Latency**: {self.runtime.p50_latency_seconds:.4f}s",
            f"- **P95 Latency**: {self.runtime.p95_latency_seconds:.4f}s",
            f"- **Max Latency**: {self.runtime.max_latency_seconds:.4f}s",
            f"- **Total Network Requests**: {self.requests.total_requests}",
            f"- **Duplicate Requests**: {self.requests.duplicate_requests}",
            f"- **Failed Requests**: {self.requests.failed_requests}",
            f"- **Estimated Cost**: ${self.cost.estimated_cost:.6f} {self.cost.currency}",
            "",
            "## 3. Bottleneck Analysis & Optimization Observations",
            "",
        ]

        if not self.bottlenecks:
            lines.append("No critical bottlenecks or anomalies detected.")
        else:
            for b in self.bottlenecks:
                icon = "🚨" if b.severity == "high" else ("⚠️" if b.severity == "medium" else "ℹ️")
                lines.extend([
                    f"### {icon} [{b.severity.upper()}] {b.component} ({b.category})",
                    f"- **Observation**: {b.message}",
                    f"- **Recommendation**: {b.actionable_recommendation}",
                    "",
                ])

        lines.extend([
            "## 4. Per-Case Evaluation Details",
            "",
            "| Case ID | Category | Status | Runtime (ms) | Requests | Verdict |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])

        for c in self.case_results:
            status_badge = "✅ PASS" if c.passed else "❌ FAIL"
            lines.append(
                f"| `{c.case_id}` | {c.category} | {c.status} | {c.measured_runtime_ms:.1f}ms | {c.request_count} | {status_badge} |"
            )

        lines.append("")
        return "\n".join(lines)


class EvaluationHarness:
    """Reusable, deterministic evaluation runner and report generator."""

    def __init__(
        self,
        dataset: list[EvaluationCase] | None = None,
        cost_config: CostModelConfig | None = None,
    ):
        self.dataset = dataset if dataset is not None else build_deterministic_evaluation_dataset()
        self.cost_config = cost_config or CostModelConfig()

    def run(
        self,
        runner_fn: Callable[[EvaluationCase], dict[str, Any]] | None = None,
        instrumentation: EvaluationInstrumentation | None = None,
    ) -> EvaluationReport:
        """Run evaluation over the dataset, collect metrics, and generate report."""
        inst = instrumentation or EvaluationInstrumentation(cost_config=self.cost_config)
        results: list[dict[str, Any]] = []
        all_evidence_items: list[dict[str, Any]] = []
        all_detected_changes: list[Any] = []
        expected_change_fields: set[str] = set()

        case_eval_results: list[CaseEvaluationResult] = []

        for case in self.dataset:
            cid = case.case_id
            gt = case.ground_truth
            for ec in gt.expected_changes:
                expected_change_fields.add(ec)

            t_case_start = time.monotonic()
            if runner_fn is not None:
                with inst.measure_operation("runner", f"eval_{cid}", stage="agent_execution"):
                    res = runner_fn(case)
            else:
                # Default deterministic simulator for evaluation dataset
                res = self._deterministic_default_runner(case, inst)

            case_latency_ms = (time.monotonic() - t_case_start) * 1000.0
            res["case_id"] = cid
            results.append(res)

            # Collect evidence
            ev_list = res.get("evidence", []) or res.get("citations", [])
            all_evidence_items.extend(ev_list)

            # Collect changes
            chg_list = res.get("changes", [])
            all_detected_changes.extend(chg_list)

            # Check per-case pass/fail
            reasons: list[str] = []
            prec_pass = True
            ext_prec_pass = True
            rec_pass = True
            ev_pass = True
            ref_pass = True

            # Precision check
            actual_org = res.get("organisation_number")
            actual_status = res.get("verdict_status")
            if gt.expected_org_number:
                if actual_org != gt.expected_org_number or actual_status != gt.expected_verdict_status:
                    prec_pass = False
                    reasons.append(f"Identity mismatch: {actual_org} ({actual_status}) != {gt.expected_org_number} ({gt.expected_verdict_status})")
            else:
                if actual_status not in ("ambiguous", "rejected", "not_found", "abstain"):
                    prec_pass = False
                    reasons.append(f"Expected abstention/rejection, got status '{actual_status}'")

            # External precision check
            if not gt.is_external_target and actual_status not in ("rejected", "not_found", "abstain"):
                ext_prec_pass = False
                reasons.append("Failed to reject external non-target entity")

            if gt.should_publish_website:
                if normalize_semantic_value(res.get("website")) != normalize_semantic_value(gt.expected_website):
                    ext_prec_pass = False
                    reasons.append(f"Website mismatch: {res.get('website')} != {gt.expected_website}")
            elif res.get("website") is not None:
                ext_prec_pass = False
                reasons.append(f"Unexpected website emitted: {res.get('website')}")

            # Recall check
            if gt.should_have_financials:
                fin = res.get("financials")
                if not fin or (fin.get("revenue") is None and not fin.get("has_accounts")):
                    rec_pass = False
                    reasons.append("Missing required statutory financials")

            # Overall pass
            overall_case_pass = prec_pass and ext_prec_pass and rec_pass and ev_pass and ref_pass

            req_stats_snapshot = inst.get_request_stats()
            req_count = req_stats_snapshot.requests_per_case.get(cid, 0)

            case_eval_results.append(
                CaseEvaluationResult(
                    case_id=cid,
                    category=case.category.value,
                    passed=overall_case_pass,
                    status=res.get("status", "usable"),
                    precision_pass=prec_pass,
                    external_precision_pass=ext_prec_pass,
                    recall_pass=rec_pass,
                    evidence_pass=ev_pass,
                    refresh_pass=ref_pass,
                    failure_reasons=reasons,
                    measured_runtime_ms=case_latency_ms,
                    request_count=req_count,
                    extracted_data=res,
                )
            )

        # Aggregate metrics
        coverage_metrics = evaluate_coverage(self.dataset, results)
        precision_metrics = evaluate_exact_precision(self.dataset, results)
        external_precision_metrics = evaluate_external_precision(self.dataset, results)
        recall_metrics = evaluate_recall(self.dataset, results)
        evidence_metrics = evaluate_evidence_validity(all_evidence_items)
        refresh_metrics = evaluate_refresh_correctness(self.dataset, results)
        false_change_metrics = calculate_false_change_rate(all_detected_changes, expected_change_fields)

        runtime_stats = inst.get_runtime_stats()
        request_stats = inst.get_request_stats()
        cost_stats = inst.get_cost_stats()
        bottlenecks = analyze_bottlenecks(runtime_stats, request_stats, cost_stats)

        total_cases = len(self.dataset)
        passed_cases = sum(1 for c in case_eval_results if c.passed)
        overall_acc = passed_cases / total_cases if total_cases > 0 else 1.0

        return EvaluationReport(
            timestamp=_utc_now_iso(),
            dataset_version="1.0.0",
            total_cases=total_cases,
            passed_cases=passed_cases,
            overall_accuracy=overall_acc,
            coverage=coverage_metrics,
            exact_precision=precision_metrics,
            external_precision=external_precision_metrics,
            recall=recall_metrics,
            evidence_validity=evidence_metrics,
            refresh_correctness=refresh_metrics,
            false_change=false_change_metrics,
            runtime=runtime_stats,
            requests=request_stats,
            cost=cost_stats,
            bottlenecks=bottlenecks,
            case_results=case_eval_results,
        )

    def _deterministic_default_runner(
        self,
        case: EvaluationCase,
        inst: EvaluationInstrumentation,
    ) -> dict[str, Any]:
        """Default deterministic runner matching ground-truth dataset for baseline benchmarking."""
        gt = case.ground_truth
        cid = case.case_id

        # Simulate network request recording
        url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{gt.expected_org_number or 'search'}"
        inst.record_request("identity_engine", url, case_id=cid, method="GET", status_code=200)

        # Build output
        evidence: list[dict[str, Any]] = []
        if gt.expected_org_number:
            evidence.append({
                "source_url": url,
                "source_type": "registry",
                "source_module": "registry",
                "retrieved_at": _utc_now_iso(),
                "content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            })

        website = gt.expected_website if gt.should_publish_website else None
        if website:
            evidence.append({
                "source_url": website,
                "source_type": "website",
                "source_module": "website",
                "retrieved_at": _utc_now_iso(),
                "content_sha256": "f4c0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b899",
            })

        financials = None
        if gt.should_have_financials:
            financials = {
                "revenue": gt.expected_financial_revenue,
                "has_accounts": True,
            }

        changes: list[dict[str, Any]] = []
        for chg in gt.expected_changes:
            changes.append({
                "field_name": chg,
                "change_type": "modified",
                "previous_value": "Bergen Teknologi AS" if chg == "legal_name" else "AS",
                "current_value": "Bergen Teknologi ASA" if chg == "legal_name" else "ASA",
            })

        return {
            "case_id": cid,
            "organisation_number": gt.expected_org_number,
            "name": gt.expected_name,
            "verdict_status": gt.expected_verdict_status,
            "website": website,
            "financials": financials,
            "leadership": list(gt.expected_leadership),
            "evidence": evidence,
            "changes": changes,
            "status": "usable" if gt.expected_verdict_status != "rejected" else "rejected",
        }
