"""Stage 18: Update & Freshness Evaluation Module.

Evaluates OrgTrace's ability to detect meaningful business changes over time
while rejecting timestamp/whitespace/formatting noise:
- Compares baseline snapshot against current output
- Uses Stage 16 is_material_change to filter out noise
- Computes change_detection_precision, change_detection_recall, false_positives, missed_changes
- Explicitly marks 'status: unavailable' when no historical baseline exists
"""

from __future__ import annotations

from typing import Any

from ..change_intelligence import (
    analyze_profile_changes,
    is_material_change,
    normalize_semantic_value,
)
from .models import FreshnessEvaluation


def evaluate_company_freshness(
    current_profile: dict[str, Any] | None,
    baseline_profile: dict[str, Any] | None,
    expected_changes: list[dict[str, Any]] | None = None,
) -> FreshnessEvaluation:
    """Evaluate change intelligence correctness against an authoritative baseline snapshot."""
    if baseline_profile is None or not baseline_profile:
        return FreshnessEvaluation(
            status="unavailable",
            reason="insufficient historical baseline",
            changes_detected=0,
            precision=None,
            recall=None,
            false_positives=0,
            missed_changes=0,
            unchanged_preserved=0,
            detected_changes=[],
        )

    if current_profile is None or not current_profile:
        return FreshnessEvaluation(
            status="evaluated",
            reason="current profile is empty",
            changes_detected=0,
            precision=0.0,
            recall=0.0,
            false_positives=0,
            missed_changes=len(expected_changes or []),
            unchanged_preserved=0,
            detected_changes=[],
        )

    # 1. Run Stage 16 change analysis
    ch_report = analyze_profile_changes(baseline_profile, current_profile)
    material_changes = [c for c in ch_report.changes if c.material]

    # 2. Extract detected changes with standardized schema
    detected: list[dict[str, Any]] = []
    detected_fields: set[str] = set()

    for mc in material_changes:
        field_norm = mc.field.lower().strip()
        detected_fields.add(field_norm)
        detected.append({
            "field": field_norm,
            "old_value": mc.previous,
            "new_value": mc.current,
            "change_type": mc.change_type.value if hasattr(mc.change_type, "value") else str(mc.change_type),
            "evidence": [
                {
                    "source_url": getattr(ev, "url", None) or getattr(ev, "source_url", None),
                    "retrieved_at": getattr(ev, "observed_at", None) or getattr(ev, "retrieved_at", None),
                    "source_type": getattr(ev, "source", None) or getattr(ev, "source_type", None),
                }
                for ev in mc.evidence
            ],
        })

    # 3. Compare against ground truth expected changes
    expected_list = expected_changes or []
    expected_fields: set[str] = set()
    for exp in expected_list:
        f_name = exp.get("field") or exp.get("field_name")
        if f_name:
            expected_fields.add(str(f_name).lower().strip())

    if not expected_fields:
        # Case where no changes were expected
        if not detected_fields:
            # Correctly preserved as unchanged
            return FreshnessEvaluation(
                status="evaluated",
                changes_detected=0,
                precision=1.0,
                recall=1.0,
                false_positives=0,
                missed_changes=0,
                unchanged_preserved=1,
                detected_changes=[],
            )
        else:
            # Detected changes when none were expected (false positives)
            return FreshnessEvaluation(
                status="evaluated",
                changes_detected=len(detected),
                precision=0.0,
                recall=1.0,
                false_positives=len(detected),
                missed_changes=0,
                unchanged_preserved=0,
                detected_changes=detected,
            )

    true_positives = len(detected_fields.intersection(expected_fields))
    false_positives = len(detected_fields - expected_fields)
    missed_changes = len(expected_fields - detected_fields)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + missed_changes) if (true_positives + missed_changes) > 0 else 0.0

    return FreshnessEvaluation(
        status="evaluated",
        changes_detected=len(detected),
        precision=precision,
        recall=recall,
        false_positives=false_positives,
        missed_changes=missed_changes,
        unchanged_preserved=1 if (false_positives == 0 and missed_changes == 0) else 0,
        detected_changes=detected,
    )
