#!/usr/bin/env python3
"""Stage 18: Competition Evaluation Harness CLI.

Runs realistic, repeatable competition evaluation for OrgTrace:
- Deterministic random sampling with seeds
- Targeted company debugging
- Custom dataset support
- Complete multi-dimensional metrics (coverage, identity, evidence, freshness, explanations, runtime, requests, cost, failures)
- Machine-readable (JSON, CSV) and human-readable (Markdown) outputs
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

# Ensure root & src in PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.evaluation import (
    CompetitionEvaluationRunner,
    generate_markdown_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OrgTrace Stage 18: Realistic Competition Evaluation Harness v2",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--random", "-r", type=int, default=None, help="Number of random companies to evaluate")
    parser.add_argument("--seed", "-s", type=int, default=None, help="Deterministic random seed")
    parser.add_argument("--dataset", "-d", type=str, default=None, help="Path to custom evaluation dataset JSON/JSONL")
    parser.add_argument("--company", "-c", type=str, default=None, help="Target company name or organisation number for debugging")
    parser.add_argument("--output", "-o", type=str, default="out/competition-evaluation", help="Output directory for reports")
    parser.add_argument("--llm-evaluation", action="store_true", help="Enable optional LLM judge for explanation evaluation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    print("\n========================================================")
    print("OrgTrace Competition Evaluation Harness v2 (Stage 18)")
    print("========================================================\n")

    if args.company:
        print(f"Target company: {args.company}")
    elif args.random is not None:
        print(f"Sampling {args.random} random companies (seed={args.seed})")
    else:
        print("Evaluating complete evaluation dataset")

    runner = CompetitionEvaluationRunner(
        dataset_path=args.dataset,
        random_count=args.random,
        seed=args.seed,
        target_company=args.company,
        use_llm_evaluation=args.llm_evaluation,
        output_dir=args.output,
        verbose=args.verbose,
    )

    report = runner.run()

    # Print markdown summary to stdout
    summary_md = generate_markdown_summary(report)
    print("\n" + summary_md)

    out_latest = Path(args.output) / "latest"
    print(f"\nArtifacts successfully written to: {out_latest.resolve()}")
    print("  - evaluation.json")
    print("  - summary.json")
    print("  - failures.json")
    print("  - companies.json")
    print("  - evaluation.csv")
    print("  - README.md\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
