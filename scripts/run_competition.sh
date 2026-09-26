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
shift || true

case "${MODE}" in
    full|--full)
        echo "================================================================================"
        echo " OrgTrace: Running 1,000-Profile Competition Batch"
        echo "================================================================================"
        if [ ! -f "brreg-enheter.csv" ]; then
            echo "Notice: 'brreg-enheter.csv' not found. Attempting download from BRREG open data..."
            if command -v curl >/dev/null 2>&1; then
                curl -fSL 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv || {
                    echo "WARNING: Automatic download failed. Proceeding with live API fallback." >&2
                }
            fi
        fi
        if [ ! -f "entry-companies.jsonl" ]; then
            if [ -f "signalpost-universe.jsonl.gz" ]; then
                echo "Notice: 'entry-companies.jsonl' not found. Generating from universe..."
                ${PYTHON_CMD} select_entry_batch.py --universe signalpost-universe.jsonl.gz --count 1000 --output entry-companies.jsonl
            else
                echo "ERROR: Neither 'entry-companies.jsonl' nor 'signalpost-universe.jsonl.gz' found." >&2
                exit 1
            fi
        fi
        mkdir -p out
        BULK_ARGS=()
        if [ -f "brreg-enheter.csv" ]; then
            BULK_ARGS=(--bulk brreg-enheter.csv)
        fi
        ${PYTHON_CMD} scripts/run_competition_batch.py \
            --organisations entry-companies.jsonl \
            "${BULK_ARGS[@]}" \
            --profiles-output out/profiles.jsonl \
            --output out/envelopes.jsonl \
            --report out/run-report.json \
            --run-id competition-final-001 \
            --expected-count 1000 \
            --max-requests 2000 \
            --max-cost 10.0 \
            --max-runtime 2700.0 \
            --modules registry,accounting_obligation,financials,roles,locations,website "$@"
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
        SMOKE_SRC="smoke-companies.jsonl"
        if [ ! -f "${SMOKE_SRC}" ]; then
            if [ -f "data/smoke-companies.jsonl" ]; then
                SMOKE_SRC="data/smoke-companies.jsonl"
            else
                echo "ERROR: No smoke company input file found." >&2
                exit 1
            fi
        fi
        mkdir -p out
        BULK_ARGS=()
        if [ -f "brreg-enheter.csv" ]; then
            BULK_ARGS=(--bulk brreg-enheter.csv)
        else
            echo "Notice: 'brreg-enheter.csv' not found. Using live Brreg open API fallback."
        fi
        ${PYTHON_CMD} scripts/run_competition_batch.py \
            --organisations "${SMOKE_SRC}" \
            "${BULK_ARGS[@]}" \
            --profiles-output out/smoke-profiles.jsonl \
            --output out/smoke-envelopes.jsonl \
            --report out/smoke-report.json \
            --run-id smoke-final-001 \
            --expected-count 10 \
            --max-requests 2000 \
            --max-cost 10.0 \
            --max-runtime 2700.0 \
            --modules registry,accounting_obligation "$@"
        echo ""
        echo "SUCCESS: Smoke batch complete. Output: out/smoke-envelopes.jsonl"
        ;;
    eval|--eval|evaluation)
        if [ -z "${1:-}" ]; then
            echo "Usage: ./scripts/run_competition.sh eval <path-to-100-company-file.jsonl>"
            exit 1
        fi
        EVAL_INPUT="$1"
        shift || true
        echo "================================================================================"
        echo " OrgTrace: Running 100-Company Evaluation Batch"
        echo "================================================================================"
        mkdir -p out
        BULK_ARGS=()
        if [ -f "brreg-enheter.csv" ]; then
            BULK_ARGS=(--bulk brreg-enheter.csv)
        fi
        OUT_PROFILES="${PROFILES_OUT:-out/profiles.jsonl}"
        OUT_ENVELOPES="${ENVELOPES_OUT:-out/envelopes.jsonl}"
        OUT_REPORT="${REPORT_OUT:-out/run-report.json}"
        ${PYTHON_CMD} scripts/run_competition_batch.py \
            --organisations "${EVAL_INPUT}" \
            "${BULK_ARGS[@]}" \
            --profiles-output "${OUT_PROFILES}" \
            --output "${OUT_ENVELOPES}" \
            --report "${OUT_REPORT}" \
            --run-id eval-100 \
            --expected-count 100 \
            --max-requests 2000 \
            --max-cost 10.0 \
            --max-runtime 2700.0 \
            --modules registry,accounting_obligation,financials,roles,locations,website "$@"
        echo ""
        echo "SUCCESS: 100-company evaluation batch complete."
        echo "  - Envelopes: ${OUT_ENVELOPES}"
        echo "  - Profiles:  ${OUT_PROFILES}"
        echo "  - Report:    ${OUT_REPORT}"
        ;;
    eval-legacy|--eval-legacy)
        echo "================================================================================"
        echo " OrgTrace: Running Stage 10 Evaluation Benchmark"
        echo "================================================================================"
        ${PYTHON_CMD} -m norway_company_agent.evaluation
        ;;
    test|--test)
        echo "================================================================================"
        echo " OrgTrace: Running Test Suite"
        echo "================================================================================"
        if ${PYTHON_CMD} -m pytest --version >/dev/null 2>&1; then
            ${PYTHON_CMD} -m pytest "$@"
        else
            ${PYTHON_CMD} -m unittest tests.test_poc -v
        fi
        ;;
    replay|--replay)
        echo "================================================================================"
        echo " OrgTrace: Running Refresh Replay Demonstration"
        echo "================================================================================"
        mkdir -p out
        ${PYTHON_CMD} scripts/run_refresh_replay.py \
            --manifest tests/fixtures/refresh-snapshots.json \
            --output out/refresh-demo.json "$@"
        ;;
    manifest|--manifest)
        echo "================================================================================"
        echo " OrgTrace: Regenerating Reproducibility MANIFEST.json"
        echo "================================================================================"
        ${PYTHON_CMD} scripts/generate_manifest.py "$@"
        ;;
    help|--help|-h)
        echo "Usage: ./scripts/run_competition.sh [full|smoke|eval|eval-legacy|test|replay|manifest]"
        echo ""
        echo "Modes:"
        echo "  full         Run 1,000-profile competition batch (default)"
        echo "  smoke        Run 10-profile smoke batch"
        echo "  eval         Run 100-company evaluation batch (<path-to-100-company-file.jsonl>)"
        echo "  eval-legacy  Run Stage 10 Evaluation & Optimization Harness"
        echo "  test         Run test suite (pytest or unittest)"
        echo "  replay       Run deterministic refresh replay demonstration"
        echo "  manifest     Regenerate MANIFEST.json"
        ;;
    *)
        echo "Unknown mode: ${MODE}. Use './scripts/run_competition.sh --help' for usage." >&2
        exit 1
        ;;
esac
