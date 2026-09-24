"""Stage 18: Explanation Quality Evaluation Module.

Evaluates Stage 17 evidence-grounded explanations:
- Verifies that explanations cite actual retrieved facts and evidence
- Verifies proper handling of uncertainty when facts are missing or ambiguous
- Detects unsupported claims or potential hallucinations
- Computes:
  - explanation_grounding_rate
  - explanation_evidence_reference_rate
  - unsupported_explanation_rate
- Provides pluggable LLM judge hook behind optional flag without making the pipeline dependent on LLM.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..explanations import explain_company_profile, validate_explanation
from .models import ExplanationEvaluation


def evaluate_company_explanations(
    profile: dict[str, Any] | None,
    use_llm_judge: bool = False,
    llm_judge_fn: Callable[[str, str], bool] | None = None,
) -> ExplanationEvaluation:
    """Evaluate grounding, evidence references, and uncertainty handling of explanations."""
    if not profile:
        return ExplanationEvaluation(
            grounding_rate=0.0,
            evidence_reference_rate=0.0,
            unsupported_rate=0.0,
            explanations_present=0,
            explanations_evaluated=0,
            claims_grounded=0,
            evidence_referenced=0,
            uncertainty_handled=0,
            unsupported_statements_detected=0,
            details=[],
        )

    # 1. Retrieve or generate explanations
    exp_report = profile.get("explanations")
    if not exp_report:
        # Run deterministic explanation generator if not yet attached
        exp_obj = explain_company_profile(profile)
        exp_report = exp_obj.to_dict()

    raw_exp = exp_report.get("explanations") if isinstance(exp_report, dict) else exp_report
    if isinstance(raw_exp, dict):
        explanation_items = list(raw_exp.values())
    elif isinstance(raw_exp, list):
        explanation_items = raw_exp
    else:
        explanation_items = []

    if not explanation_items:
        return ExplanationEvaluation(
            grounding_rate=0.0,
            evidence_reference_rate=0.0,
            unsupported_rate=0.0,
            explanations_present=0,
            explanations_evaluated=0,
            claims_grounded=0,
            evidence_referenced=0,
            uncertainty_handled=0,
            unsupported_statements_detected=0,
            details=[],
        )

    total_evaluated = len(explanation_items)
    grounded_count = 0
    evidence_ref_count = 0
    uncertainty_count = 0
    unsupported_count = 0
    details: list[dict[str, Any]] = []

    # Flatten existing profile facts into searchable text
    fact_corpus = " ".join([
        str(profile.get("name") or ""),
        str(profile.get("organisation_number") or ""),
        str(profile.get("legal_form") or ""),
        str(profile.get("website") or ""),
        str(profile.get("municipality") or ""),
        str(profile.get("status") or ""),
    ]).lower()

    for item in explanation_items:
        f_name = item.get("field_name") or "general"
        summary = item.get("summary") or ""
        reasoning = item.get("reasoning") or ""
        full_text = f"{summary} {reasoning}".lower()

        supp_ev = item.get("supporting_evidence") or []
        missing_ev = item.get("missing_evidence") or []
        uncertainty = item.get("uncertainty")
        confidence = item.get("confidence")
        is_fallback = item.get("is_fallback", False)
        val_passed = item.get("validation_passed", True)

        # 1. Evidence Referenced
        has_ev_ref = False
        if supp_ev and len(supp_ev) > 0:
            for ev in supp_ev:
                if ev.get("source_url") or ev.get("source_name") or ev.get("evidence_id"):
                    has_ev_ref = True
                    break
        elif "brreg" in full_text or "enhetsregisteret" in full_text or "http" in full_text:
            has_ev_ref = True

        if has_ev_ref:
            evidence_ref_count += 1

        # 2. Uncertainty Handled
        has_uncertainty_handling = False
        if uncertainty or (missing_ev and len(missing_ev) > 0) or confidence in {"low", "unknown"}:
            has_uncertainty_handling = True
        elif any(marker in full_text for marker in [
            "missing", "not found", "unavailable", "uncertain", "not registered", "unverified", "no public"
        ]):
            has_uncertainty_handling = True

        if has_uncertainty_handling:
            uncertainty_count += 1

        # 3. Grounding & Hallucination Checks
        is_grounded = True
        is_unsupported = False

        if not val_passed:
            is_grounded = False
            is_unsupported = True

        # Check for numbers in summary/reasoning
        nums_in_text = re.findall(r"\b\d{4,9}\b", summary)
        for num in nums_in_text:
            # If a specific 4-9 digit number is asserted, it should appear in the profile
            if num not in fact_corpus and num != str(profile.get("organisation_number")):
                # Exception: year numbers like 2023, 2024, 2025, 2026
                if num in {"2020", "2021", "2022", "2023", "2024", "2025", "2026"}:
                    continue
                is_grounded = False
                is_unsupported = True
                break

        # Optional LLM Judge Hook
        if use_llm_judge and llm_judge_fn:
            try:
                llm_eval_pass = llm_judge_fn(fact_corpus, full_text)
                if not llm_eval_pass:
                    is_grounded = False
                    is_unsupported = True
            except Exception:
                pass

        if is_grounded:
            grounded_count += 1
        if is_unsupported:
            unsupported_count += 1

        details.append({
            "field": f_name,
            "grounded": is_grounded,
            "evidence_referenced": has_ev_ref,
            "uncertainty_handled": has_uncertainty_handling,
            "unsupported": is_unsupported,
            "confidence": confidence,
            "summary_snippet": summary[:80],
        })

    grounding_rate = grounded_count / total_evaluated if total_evaluated > 0 else 1.0
    ev_ref_rate = evidence_ref_count / total_evaluated if total_evaluated > 0 else 0.0
    unsupported_rate = unsupported_count / total_evaluated if total_evaluated > 0 else 0.0

    return ExplanationEvaluation(
        grounding_rate=grounding_rate,
        evidence_reference_rate=ev_ref_rate,
        unsupported_rate=unsupported_rate,
        explanations_present=total_evaluated,
        explanations_evaluated=total_evaluated,
        claims_grounded=grounded_count,
        evidence_referenced=evidence_ref_count,
        uncertainty_handled=uncertainty_count,
        unsupported_statements_detected=unsupported_count,
        details=details,
    )
