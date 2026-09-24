"""Stage 18: Competition Evaluation Report Generator.

Emits machine-readable (JSON, CSV) and human-readable (Markdown README) reports:
- out/competition-evaluation/latest/evaluation.json
- out/competition-evaluation/latest/summary.json
- out/competition-evaluation/latest/failures.json
- out/competition-evaluation/latest/companies.json
- out/competition-evaluation/latest/evaluation.csv
- out/competition-evaluation/latest/README.md
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from .models import CompetitionEvaluationReport


def write_evaluation_reports(
    report: CompetitionEvaluationReport,
    output_dir: str | Path = "out/competition-evaluation",
) -> dict[str, Path]:
    """Write all machine-readable and human-readable evaluation files to output_dir and latest/."""
    base_path = Path(output_dir)
    latest_path = base_path / "latest"

    base_path.mkdir(parents=True, exist_ok=True)
    latest_path.mkdir(parents=True, exist_ok=True)

    report_dict = report.to_dict()
    summary_dict = report.summary.to_dict()
    failures_list = report.failures
    companies_list = [c.to_dict() for c in report.companies]

    # Generate CSV
    csv_rows = [c.to_flat_dict() for c in report.companies]
    fieldnames = list(csv_rows[0].keys()) if csv_rows else [
        "case_id", "query", "expected_org", "observed_org", "identity_status",
        "identity_accuracy", "coverage_rate", "evidence_validity_rate",
        "freshness_status", "explanation_grounding_rate", "runtime_ms",
        "requests_total", "result"
    ]
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(csv_rows)
    csv_content = csv_buffer.getvalue()

    # Generate Markdown README
    markdown_content = generate_markdown_summary(report)

    written_paths: dict[str, Path] = {}

    for folder in (latest_path,):
        # 1. evaluation.json
        eval_p = folder / "evaluation.json"
        eval_p.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        written_paths["evaluation_json"] = eval_p

        # 2. summary.json
        sum_p = folder / "summary.json"
        sum_p.write_text(json.dumps(summary_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        written_paths["summary_json"] = sum_p

        # 3. failures.json
        fail_p = folder / "failures.json"
        fail_p.write_text(json.dumps(failures_list, indent=2, ensure_ascii=False), encoding="utf-8")
        written_paths["failures_json"] = fail_p

        # 4. companies.json
        comp_p = folder / "companies.json"
        comp_p.write_text(json.dumps(companies_list, indent=2, ensure_ascii=False), encoding="utf-8")
        written_paths["companies_json"] = comp_p

        # 5. evaluation.csv
        csv_p = folder / "evaluation.csv"
        csv_p.write_text(csv_content, encoding="utf-8")
        written_paths["evaluation_csv"] = csv_p

        # 6. README.md
        md_p = folder / "README.md"
        md_p.write_text(markdown_content, encoding="utf-8")
        written_paths["readme_md"] = md_p

    return written_paths


def generate_markdown_summary(report: CompetitionEvaluationReport) -> str:
    """Generate concise human-readable markdown summary for competition evaluation."""
    run = report.run
    sum_ = report.summary

    cost_str = f"${sum_.estimated_cost_usd:.4f}" if sum_.estimated_cost_usd is not None else "unavailable"
    chg_prec_str = f"{sum_.change_detection_precision * 100:.1f}%" if sum_.change_detection_precision is not None else "unavailable"
    chg_rec_str = f"{sum_.change_detection_recall * 100:.1f}%" if sum_.change_detection_recall is not None else "unavailable"

    lines = [
        "# OrgTrace Competition Evaluation",
        "",
        f"**Dataset**: `{run.dataset}` (hash: `{run.dataset_hash}`)",
        f"**Companies Evaluated**: {run.companies_evaluated} (requested: {run.companies_requested})",
        f"**Seed**: `{run.seed}`",
        f"**Git Commit**: `{run.git_commit or 'unavailable'}`",
        f"**Timestamp**: {run.timestamp}",
        "",
        "---",
        "",
        "## Key Performance Dimensions",
        "",
        "| Dimension | Metric | Score |",
        "| :--- | :--- | :--- |",
        f"| **Coverage** | Overall Coverage Rate | **{sum_.coverage_rate * 100:.1f}%** (Field: {sum_.field_coverage_rate * 100:.1f}%, Category: {sum_.category_coverage_rate * 100:.1f}%) |",
        f"| **Identity** | Identity Accuracy | **{sum_.identity_accuracy * 100:.1f}%** (Wrong: {sum_.wrong_company_rate * 100:.1f}%, Ambiguous: {sum_.ambiguous_identity_rate * 100:.1f}%) |",
        f"| **Evidence** | Evidence Validity Rate | **{sum_.evidence_validity_rate * 100:.1f}%** (Coverage: {sum_.evidence_coverage * 100:.1f}%, Unsupported: {sum_.unsupported_claim_rate * 100:.1f}%) |",
        f"| **Updates / Freshness** | Change Detection Precision / Recall | **{chg_prec_str} / {chg_rec_str}** |",
        f"| **Explanations** | Grounding Rate | **{sum_.explanation_grounding_rate * 100:.1f}%** (Evidence Cited: {sum_.explanation_evidence_reference_rate * 100:.1f}%) |",
        f"| **Runtime** | Average / P95 Latency | **{sum_.average_runtime_ms:.1f} ms / {sum_.p95_runtime_ms:.1f} ms** (Total: {sum_.total_runtime_ms:.1f} ms) |",
        f"| **Outbound Requests** | Total / Avg per company | **{sum_.total_requests} reqs ({sum_.average_requests_per_company:.1f}/co)** (Failed: {sum_.failed_requests}, Retries: {sum_.retry_count}) |",
        f"| **Cost** | LLM Calls / Estimated USD | **{sum_.total_llm_calls} calls ({cost_str})** |",
        f"| **Success & Resilience** | Success / Failure Rate | **{sum_.success_rate * 100:.1f}% success ({sum_.partial_success_rate * 100:.1f}% partial) / {sum_.failure_rate * 100:.1f}% failure** (Timeouts: {sum_.timeout_rate * 100:.1f}%) |",
        "",
        "---",
        "",
        "## Failure Diagnostics",
        "",
        "### Top failure categories:",
    ]

    if sum_.top_failure_categories:
        for cat, cnt in sorted(sum_.top_failure_categories.items(), key=lambda x: -x[1]):
            lines.append(f"- **{cat}**: {cnt} occurrences")
    else:
        lines.append("- *None observed (all evaluations succeeded).*")

    lines.extend([
        "",
        "### Worst-performing fields:",
    ])

    if sum_.worst_performing_fields:
        for f in sum_.worst_performing_fields[:10]:
            lines.append(f"- **{f.get('field')}**: {f.get('missing_count', 0)} missing, {f.get('invalid_count', 0)} invalid")
    else:
        lines.append("- *All core fields retrieved with high completeness.*")

    lines.extend([
        "",
        "### Companies requiring investigation:",
    ])

    if sum_.companies_requiring_investigation:
        for c in sum_.companies_requiring_investigation[:15]:
            lines.append(f"- `{c}`")
    else:
        lines.append("- *No companies flagged for investigation.*")

    lines.append("")
    return "\n".join(lines)
