"""Integration test for CompetitionEvaluationRunner using mocked fetchers (offline)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from norway_company_agent.evaluation.runner import CompetitionEvaluationRunner
from norway_company_agent.http import FetchResult


def make_mock_fetcher(org_data: dict[str, dict]):
    """Return a mock HTTP fetcher simulating Brreg responses offline."""
    def mock_fetch(url: str) -> FetchResult:
        for org, data in org_data.items():
            if org in url:
                if "/roller" in url:
                    body = {"roller": [{"type": "DAGL", "navn": "Ola Nordmann"}]}
                elif "/konsernstruktur" in url:
                    body = {"morselskap": None}
                elif "/underenheter" in url:
                    body = {"_embedded": {"underenheter": []}}
                elif "/regnskap/" in url:
                    body = [{
                        "avsluttet": "2024-12-31",
                        "egenkapital": 1000000.0,
                        "eiendeler": 2000000.0,
                        "salgsinntekter": 5000000.0,
                        "ordinaertResultatForSkattekostnad": 500000.0,
                    }]
                else:
                    body = {
                        "organisasjonsnummer": org,
                        "navn": data.get("name", "Test AS"),
                        "organisasjonsform": {"kode": data.get("legal_form", "AS")},
                        "hjemmeside": data.get("website", ""),
                        "konkurs": False,
                        "underAvvikling": False,
                        "antallAnsatte": 5,
                        "forretningsadresse": {"kommune": "Oslo", "adresse": ["Storgata 1"]},
                        "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmeringstjenester"},
                    }
                return FetchResult(
                    url=url,
                    status=200,
                    error=None,
                    retrieved_at="2026-09-24T12:00:00Z",
                    effective_at=None,
                    content_sha256="mockhash123",
                    body=body,
                    bytes_received=500,
                    elapsed_ms=5.0,
                )
        return FetchResult(
            url=url,
            status=404,
            error="Not found",
            retrieved_at="2026-09-24T12:00:00Z",
            effective_at=None,
            content_sha256="",
            body={},
            bytes_received=0,
            elapsed_ms=5.0,
        )
    return mock_fetch


class TestRunnerIntegration(unittest.TestCase):
    """Verify end-to-end evaluation runner workflow without network dependency."""

    def test_runner_batch_execution_offline(self):
        mock_data = {
            "923609016": {"name": "Equinor ASA", "legal_form": "ASA", "website": "https://www.equinor.com"},
            "984851006": {"name": "DNB Bank ASA", "legal_form": "ASA", "website": "https://www.dnb.no"},
            "955666777": {"name": "Bergen Teknologi ASA", "legal_form": "ASA", "website": "https://bergentek.no"},
        }
        mock_fetch = make_mock_fetcher(mock_data)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = CompetitionEvaluationRunner(
                random_count=3,
                seed=42,
                output_dir=tmpdir,
                fetcher=mock_fetch,
            )

            report = runner.run()

            # 1. Verification of evaluation results
            self.assertEqual(len(report.companies), 3)
            self.assertGreater(report.summary.coverage_rate, 0.0)
            self.assertGreaterEqual(report.summary.identity_accuracy, 0.0)
            self.assertGreater(report.summary.total_runtime_ms, 0.0)
            self.assertGreaterEqual(report.summary.total_requests, 3)

            # 2. Verification of generated artifacts
            latest_dir = Path(tmpdir) / "latest"
            self.assertTrue((latest_dir / "evaluation.json").exists())
            self.assertTrue((latest_dir / "summary.json").exists())
            self.assertTrue((latest_dir / "failures.json").exists())
            self.assertTrue((latest_dir / "companies.json").exists())
            self.assertTrue((latest_dir / "evaluation.csv").exists())
            self.assertTrue((latest_dir / "README.md").exists())

            # 3. Verify single company failure / non-target doesn't abort run
            runner_with_bad_target = CompetitionEvaluationRunner(
                target_company="999999999",  # Not found
                output_dir=tmpdir,
                fetcher=mock_fetch,
            )
            report_bad = runner_with_bad_target.run()
            self.assertEqual(len(report_bad.companies), 1)
            self.assertIn(report_bad.companies[0].result, {"failed", "partial_success", "identity_failure"})


if __name__ == "__main__":
    unittest.main()
