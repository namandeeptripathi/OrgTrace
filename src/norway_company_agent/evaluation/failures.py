"""Stage 18: Failure Classification & Resilience Module.

Ensures batch isolation so single company failures never abort the run:
- Classifies terminal states: success, partial_success, failed, timeout, identity_failure, evaluation_error
- Captures failure stage, type, and diagnostic error message
- Calculates aggregate failure rates and categorizes failure bottlenecks
"""

from __future__ import annotations

from typing import Any

from .models import CompanyEvaluationResultState, IdentityStatus


def classify_company_outcome(
    identity_status: IdentityStatus,
    coverage_rate: float,
    evidence_validity_rate: float,
    error: Exception | str | None = None,
    timed_out: bool = False,
    is_evaluation_error: bool = False,
    stage: str = "enrichment",
) -> tuple[str, dict[str, Any] | None]:
    """Classify the terminal state of a company evaluation and extract failure details if any."""
    if timed_out:
        return (
            CompanyEvaluationResultState.TIMEOUT.value,
            {
                "type": "timeout",
                "stage": stage,
                "error": str(error) if error else "Execution exceeded configured timeout budget.",
            },
        )

    if is_evaluation_error:
        return (
            CompanyEvaluationResultState.EVALUATION_ERROR.value,
            {
                "type": "evaluation_error",
                "stage": stage,
                "error": str(error) if error else "Internal evaluation error occurred.",
            },
        )

    if error is not None:
        err_str = str(error)
        f_type = "network_error" if "timeout" in err_str.lower() or "connection" in err_str.lower() else "execution_error"
        return (
            CompanyEvaluationResultState.FAILED.value,
            {
                "type": f_type,
                "stage": stage,
                "error": err_str,
            },
        )

    if identity_status in {IdentityStatus.WRONG_COMPANY, IdentityStatus.AMBIGUOUS}:
        return (
            CompanyEvaluationResultState.IDENTITY_FAILURE.value,
            {
                "type": identity_status.value,
                "stage": "identity_resolution",
                "error": f"Identity resolution classified as {identity_status.value}.",
            },
        )

    # Success or Partial Success based on coverage & evidence
    if (coverage_rate >= 0.60 or (coverage_rate >= 0.50 and identity_status == IdentityStatus.EXACT_MATCH)) and evidence_validity_rate >= 0.60:
        return CompanyEvaluationResultState.SUCCESS.value, None

    if coverage_rate >= 0.20 or identity_status in {IdentityStatus.EXACT_MATCH, IdentityStatus.PROBABLE_MATCH}:
        return CompanyEvaluationResultState.PARTIAL_SUCCESS.value, None

    return (
        CompanyEvaluationResultState.FAILED.value,
        {
            "type": "insufficient_data",
            "stage": stage,
            "error": f"Extracted coverage ({coverage_rate:.2f}) or evidence validity ({evidence_validity_rate:.2f}) was insufficient.",
        },
    )


def compute_failure_rates(records: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate outcome rates across all evaluated company records."""
    total = len(records)
    if total == 0:
        return {
            "success_rate": 0.0,
            "partial_success_rate": 0.0,
            "failure_rate": 0.0,
            "timeout_rate": 0.0,
            "identity_failure_rate": 0.0,
        }

    counts = {
        "success": 0,
        "partial_success": 0,
        "failed": 0,
        "timeout": 0,
        "identity_failure": 0,
        "evaluation_error": 0,
    }

    for r in records:
        res = r.get("result", "failed")
        counts[res] = counts.get(res, 0) + 1

    return {
        "success_rate": round(counts["success"] / total, 4),
        "partial_success_rate": round(counts["partial_success"] / total, 4),
        "failure_rate": round((counts["failed"] + counts["evaluation_error"]) / total, 4),
        "timeout_rate": round(counts["timeout"] / total, 4),
        "identity_failure_rate": round(counts["identity_failure"] / total, 4),
    }
