"""OrgTrace Evaluation Package.

Exposes both legacy Stage 10 benchmark harness components (for backwards compatibility)
and Stage 18 competition evaluation v2 components.
"""

from __future__ import annotations

# Stage 18 Competition Evaluation Exports
from .costs import (
    TokenPricingConfig,
    evaluate_company_cost,
)
from .coverage import (
    COVERAGE_SCHEMA,
    evaluate_company_coverage,
)
from .dataset import (
    DEFAULT_DATASET_PATH,
    EvaluationDatasetCase,
    compute_dataset_hash,
    load_evaluation_dataset,
    select_evaluation_cases,
)
from .evidence import (
    evaluate_company_evidence,
)
from .explanations import (
    evaluate_company_explanations,
)
from .failures import (
    classify_company_outcome,
    compute_failure_rates,
)
from .freshness import (
    evaluate_company_freshness,
)
from .identity import (
    evaluate_company_identity,
)
from .models import (
    ClaimEvidenceStatus,
    CompanyEvaluationRecord,
    CompanyEvaluationResultState,
    CompetitionEvaluationReport,
    CostEvaluation,
    CoverageCategoryBreakdown,
    CoverageEvaluation,
    CoverageFieldStatus,
    EvaluationRunMetadata,
    EvaluationSummary,
    EvidenceEvaluation,
    ExplanationEvaluation,
    FreshnessEvaluation,
    IdentityEvaluation,
    IdentityStatus,
    PerformanceEvaluation,
    RequestEvaluation,
)
from .performance import (
    compute_runtime_statistics,
    measure_execution_ms,
)
from .report import (
    generate_markdown_summary,
    write_evaluation_reports,
)
from .requests import (
    RequestTracker,
    classify_request_domain,
)
from .runner import (
    CompetitionEvaluationRunner,
)

# Legacy Stage 10 exports (backward compatibility)
from .legacy_harness import (
    BottleneckObservation,
    CaseEvaluationResult,
    CostModelConfig,
    CostStats,
    CoverageMetrics,
    EvaluationHarness,
    EvaluationInstrumentation,
    EvaluationReport,
    EvidenceValidityMetrics,
    ExternalPrecisionMetrics,
    FalseChangeMetrics,
    FieldCoverageMetrics,
    PrecisionMetrics,
    RecallMetrics,
    RefreshCorrectnessMetrics,
    RequestStats,
    RuntimeStats,
    analyze_bottlenecks,
    calculate_false_change_rate,
    evaluate_coverage,
    evaluate_evidence_validity,
    evaluate_exact_precision,
    evaluate_external_precision,
    evaluate_recall,
    evaluate_refresh_correctness,
)

__all__ = [
    # Stage 18 Models & Runner
    "CompetitionEvaluationRunner",
    "CompetitionEvaluationReport",
    "CompanyEvaluationRecord",
    "EvaluationSummary",
    "EvaluationRunMetadata",
    "EvaluationDatasetCase",
    "load_evaluation_dataset",
    "select_evaluation_cases",
    "compute_dataset_hash",
    "DEFAULT_DATASET_PATH",
    "write_evaluation_reports",
    "generate_markdown_summary",
    # Stage 18 Metric Evaluators
    "IdentityStatus",
    "IdentityEvaluation",
    "evaluate_company_identity",
    "CoverageFieldStatus",
    "CoverageEvaluation",
    "CoverageCategoryBreakdown",
    "COVERAGE_SCHEMA",
    "evaluate_company_coverage",
    "ClaimEvidenceStatus",
    "EvidenceEvaluation",
    "evaluate_company_evidence",
    "FreshnessEvaluation",
    "evaluate_company_freshness",
    "ExplanationEvaluation",
    "evaluate_company_explanations",
    "PerformanceEvaluation",
    "measure_execution_ms",
    "compute_runtime_statistics",
    "RequestEvaluation",
    "RequestTracker",
    "classify_request_domain",
    "CostEvaluation",
    "TokenPricingConfig",
    "evaluate_company_cost",
    "CompanyEvaluationResultState",
    "classify_company_outcome",
    "compute_failure_rates",
    # Legacy Stage 10
    "BottleneckObservation",
    "CaseEvaluationResult",
    "CostModelConfig",
    "CostStats",
    "CoverageMetrics",
    "EvaluationHarness",
    "EvaluationInstrumentation",
    "EvaluationReport",
    "EvidenceValidityMetrics",
    "ExternalPrecisionMetrics",
    "FalseChangeMetrics",
    "FieldCoverageMetrics",
    "PrecisionMetrics",
    "RecallMetrics",
    "RefreshCorrectnessMetrics",
    "RequestStats",
    "RuntimeStats",
    "analyze_bottlenecks",
    "calculate_false_change_rate",
    "evaluate_coverage",
    "evaluate_evidence_validity",
    "evaluate_exact_precision",
    "evaluate_external_precision",
    "evaluate_recall",
    "evaluate_refresh_correctness",
]
