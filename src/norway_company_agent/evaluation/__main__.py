"""Main entry point for python -m norway_company_agent.evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .legacy_harness import EvaluationHarness


def main() -> None:
    parser = argparse.ArgumentParser(description="OrgTrace Evaluation & Optimization Benchmark")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    parser.add_argument("--output", "-o", help="Write report to file")
    args = parser.parse_args()

    harness = EvaluationHarness()
    report = harness.run()
    content = json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else report.to_markdown()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")

    print(content)
    sys.exit(0 if report.passed_cases == report.total_cases else 1)


if __name__ == "__main__":
    main()
