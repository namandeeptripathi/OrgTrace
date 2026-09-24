"""Tests for Stage 18 Machine-Readable and Human-Readable Report Outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from norway_company_agent.evaluation.models import (
    CompanyEvaluationRecord,
    CompetitionEvaluationReport,
    CostEvaluation,
    CoverageEvaluation,
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
from norway_company_agent.evaluation.report import (
    generate_markdown_summary,
    write_evaluation_reports,
)


class TestReportGeneration(unittest.TestCase):
    """Verify JSON, CSV, and Markdown generation formats and schemas."""

    def setUp(self):
        self.run_metadata = EvaluationRunMetadata(
            timestamp="2026-09-24T12:00:00Z",
            seed=42,
            dataset="data/evaluation/default_companies.json",
            dataset_hash="abc12345",
            git_commit="46b80690",
            companies_requested=1,
            companies_evaluated=1,
        )
        self.summary = EvaluationSummary(
            companies_evaluated=1,
            coverage_rate=0.88,
            identity_accuracy=1.0,
            evidence_validity_rate=0.92,
            change_detection_precision=1.0,
            change_detection_recall=1.0,
            explanation_grounding_rate=0.95,
            success_rate=1.0,
            failure_rate=0.0,
            average_runtime_ms=250.0,
            p95_runtime_ms=250.0,
            total_requests=4,
            average_requests_per_company=4.0,
        )
        self.company = CompanyEvaluationRecord(
            case_id="eval-001",
            query="Equinor ASA",
            identity=IdentityEvaluation(
                status=IdentityStatus.EXACT_MATCH,
                expected_org_number="923609016",
                observed_org_number="923609016",
                name_match=True,
                website_match=True,
                accuracy=1.0,
            ),
            coverage=CoverageEvaluation(rate=0.88, missing_fields=["contact.email"]),
            evidence=EvidenceEvaluation(validity_rate=0.92, evidence_coverage=0.90),
            updates=FreshnessEvaluation(status="evaluated", changes_detected=0),
            explanations=ExplanationEvaluation(grounding_rate=0.95),
            performance=PerformanceEvaluation(runtime_ms=250.0),
            requests=RequestEvaluation(total=4),
            cost=CostEvaluation(status="unavailable"),
            result="success",
        )
        self.report = CompetitionEvaluationReport(
            run=self.run_metadata,
            summary=self.summary,
            companies=[self.company],
            failures=[],
        )

    def test_write_evaluation_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            written = write_evaluation_reports(self.report, output_dir=tmpdir)
            latest_dir = Path(tmpdir) / "latest"

            self.assertTrue((latest_dir / "evaluation.json").exists())
            self.assertTrue((latest_dir / "summary.json").exists())
            self.assertTrue((latest_dir / "failures.json").exists())
            self.assertTrue((latest_dir / "companies.json").exists())
            self.assertTrue((latest_dir / "evaluation.csv").exists())
            self.assertTrue((latest_dir / "README.md").exists())

            # Validate JSON
            eval_data = json.loads((latest_dir / "evaluation.json").read_text(encoding="utf-8"))
            self.assertEqual(eval_data["run"]["seed"], 42)
            self.assertEqual(eval_data["summary"]["coverage_rate"], 0.88)
            self.assertEqual(len(eval_data["companies"]), 1)

            # Validate CSV
            with (latest_dir / "evaluation.csv").open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["case_id"], "eval-001")
                self.assertEqual(rows[0]["result"], "success")

    def test_markdown_summary_contains_key_sections(self):
        md = generate_markdown_summary(self.report)
        self.assertIn("# OrgTrace Competition Evaluation", md)
        self.assertIn("Coverage", md)
        self.assertIn("Identity", md)
        self.assertIn("Evidence", md)
        self.assertIn("Top failure categories", md)
        self.assertIn("Worst-performing fields", md)
        self.assertIn("Companies requiring investigation", md)


if __name__ == "__main__":
    unittest.main()
