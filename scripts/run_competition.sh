#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# OrgTrace — One-Command Competition Execution Script
# ==============================================================================
# Usage:
#   ./scripts/run_competition.sh [full|smoke|eval|test|replay|manifest]
#
# Default: runs 'full' mode (1,000-profile competition batch)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Detect Python execution environment
if command -v uv >/dev/null 2>&1; then
    PYTHON_CMD="uv run python"
elif [ -f "${ROOT_DIR}/.venv/bin/python" ]; then
    PYTHON_CMD="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
else
    echo "ERROR: No suitable Python environment found." >&2
    echo "Please install Python >=3.12 and uv, or activate a virtualenv." >&2
    exit 1
fi

export PYTHONPATH="src:${PYTHONPATH:-}"

MODE="${1:-full}"

case "${MODE}" in
    full|--full)
        echo "================================================================================"
        echo " OrgTrace: Running 1,000-Profile Competition Batch"
        echo "================================================================================"
        if [ ! -f "brreg-enheter.csv" ]; then
            echo "ERROR: 'brreg-enheter.csv' not found. Please download it via:" >&2
            echo "  curl -L 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv" >&2
            exit 1
        fi
        if [ ! -f "entry-companies.jsonl" ]; then
            echo "Notice: 'entry-companies.jsonl' not found. Generating from universe..."
            ${PYTHON_CMD} select_entry_batch.py --universe signalpost-universe.jsonl.gz --count 1000 --output entry-companies.jsonl
        fi
        mkdir -p out
        ${PYTHON_CMD} scripts/run_competition_batch.py \
            --organisations entry-companies.jsonl \
            --bulk brreg-enheter.csv \
            --profiles-output out/profiles.jsonl \
            --output out/envelopes.jsonl \
            --report out/run-report.json \
            --run-id competition-final-001 \
            --expected-count 1000 \
            --modules registry,accounting_obligation
        echo ""
        echo "SUCCESS: 1,000-profile batch complete."
        echo "  - Envelopes: out/envelopes.jsonl"
        echo "  - Profiles:  out/profiles.jsonl"
        echo "  - Report:    out/run-report.json"
        ;;
    smoke|--smoke)
        echo "================================================================================"
        echo " OrgTrace: Running 10-Profile Smoke Batch"
        echo "================================================================================"
        if [ ! -f "brreg-enheter.csv" ]; then
            echo "ERROR: 'brreg-enheter.csv' not found." >&2
            exit 1
        fi
        mkdir -p out
        ${PYTHON_CMD} scripts/run_competition_batch.py \
            --organisations smoke-companies.jsonl \
            --bulk brreg-enheter.csv \
            --profiles-output out/smoke-profiles.jsonl \
            --output out/smoke-envelopes.jsonl \
            --report out/smoke-report.json \
            --run-id smoke-final-001 \
            --expected-count 10 \
            --modules registry,accounting_obligation
        echo ""
        echo "SUCCESS: Smoke batch complete. Output: out/smoke-envelopes.jsonl"
        ;;
    eval|--eval|evaluation)
        echo "================================================================================"
        echo " OrgTrace: Running Stage 10 Evaluation & Optimization Benchmark"
        echo "================================================================================"
        ${PYTHON_CMD} -m norway_company_agent.evaluation
        ;;
    test|--test)
        echo "================================================================================"
        echo " OrgTrace: Running Full Test Suite (254 tests)"
        echo "================================================================================"
        ${PYTHON_CMD} -m unittest tests.test_poc -v
        ;;
    replay|--replay)
        echo "================================================================================"
        echo " OrgTrace: Running Refresh Replay Demonstration"
        echo "================================================================================"
        mkdir -p out
        ${PYTHON_CMD} scripts/run_refresh_replay.py \
            --manifest tests/fixtures/refresh-snapshots.json \
            --output out/refresh-demo.json
        ;;
    manifest|--manifest)
        echo "================================================================================"
        echo " OrgTrace: Regenerating Reproducibility MANIFEST.json"
        echo "================================================================================"
        ${PYTHON_CMD} scripts/generate_manifest.py
        ;;
    help|--help|-h)
        echo "Usage: ./scripts/run_competition.sh [full|smoke|eval|test|replay|manifest]"
        echo ""
        echo "Modes:"
        echo "  full      Run 1,000-profile competition batch (default)"
        echo "  smoke     Run 10-profile smoke batch"
        echo "  eval      Run Stage 10 Evaluation & Optimization Harness"
        echo "  test      Run full 254-test suite"
        echo "  replay    Run deterministic refresh replay demonstration"
        echo "  manifest  Regenerate MANIFEST.json"
        ;;
    *)
        echo "Unknown mode: ${MODE}. Use './scripts/run_competition.sh --help' for usage." >&2
        exit 1
        ;;
esac
