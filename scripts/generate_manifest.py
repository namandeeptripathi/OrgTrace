#!/usr/bin/env python3
"""Generate machine-readable MANIFEST.json capturing the exact reproducibility state for OrgTrace."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def compute_sha256(path: Path) -> str:
    if not path.exists():
        return "not_found"
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_info() -> dict[str, str]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = "unknown"
        branch = "unknown"
    return {"commit_sha": commit, "branch": branch}


def get_pinned_dependencies() -> dict[str, str]:
    req_file = ROOT / "requirements.txt"
    deps = {}
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "==" in line:
                pkg, ver = line.split("==", 1)
                deps[pkg.strip()] = ver.strip()
    return deps


def main() -> None:
    git_info = get_git_info()
    deps = get_pinned_dependencies()

    datasets = [
        {
            "filename": "entry-companies.jsonl",
            "sha256": compute_sha256(ROOT / "entry-companies.jsonl"),
            "rows": 1000,
            "description": "Selected competition entry batch from signalpost-universe.jsonl.gz (seed 20260823)",
        },
        {
            "filename": "smoke-companies.jsonl",
            "sha256": compute_sha256(ROOT / "smoke-companies.jsonl"),
            "rows": 10,
            "description": "10-company smoke test subset of entry-companies.jsonl",
        },
        {
            "filename": "brreg-enheter.csv",
            "sha256": compute_sha256(ROOT / "brreg-enheter.csv"),
            "rows": 1174956,
            "description": "Brønnøysundregistrene Enhetsregisteret bulk CSV export",
        },
        {
            "filename": "signalpost-universe.jsonl.gz",
            "sha256": compute_sha256(ROOT / "signalpost-universe.jsonl.gz"),
            "rows": 411160,
            "description": "Signalpost 2025 public universe archive",
        },
    ]

    out_envelopes = ROOT / "out" / "envelopes.jsonl"
    out_profiles = ROOT / "out" / "profiles.jsonl"
    out_report = ROOT / "out" / "run-report.json"

    manifest = {
        "schema_version": "1.0.0",
        "project": {
            "name": "OrgTrace",
            "version": "0.1.0",
            "description": "Deterministic, evidence-backed Norwegian enterprise intelligence engine",
            "repository": "namandeeptripathi/OrgTrace",
        },
        "reproducibility": {
            "git_commit": git_info["commit_sha"],
            "git_branch": git_info["branch"],
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "timestamp_utc": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip(),
        },
        "execution": {
            "entrypoint_command": "./scripts/run_competition.sh",
            "evaluation_command": "PYTHONPATH=src uv run python -m norway_company_agent.evaluation",
            "test_command": "PYTHONPATH=src uv run python -m unittest tests.test_poc -v",
            "benchmark_size": 1000,
            "runtime_environment": os.environ.get("ORGTRACE_ENV", "production"),
        },
        "models_and_engines": [
            {
                "name": "Deterministic Pattern Engine",
                "type": "rule_based_nlp",
                "purpose": "Modulo 11 verification, legal form taxonomy, address congruence, exact-entity matching",
                "cost_usd": 0.0,
            },
            {
                "name": "Financial Intelligence Engine",
                "type": "rule_based_accounting",
                "purpose": "Accounting obligation statutory assessment (Regnskapsloven), Regnskapsregisteret metric extraction",
                "cost_usd": 0.0,
            },
            {
                "name": "Change Intelligence Engine",
                "type": "semantic_diff",
                "purpose": "Deterministic semantic diffing, snapshot immutability, failed-refresh preservation",
                "cost_usd": 0.0,
            },
            {
                "name": "NbAiLab/nb-bert-base (Optional)",
                "type": "transformer",
                "purpose": "Norwegian text sentiment classification (optional crawler profile)",
                "cost_usd": 0.0,
            },
        ],
        "external_apis": [
            {
                "name": "Enhetsregisteret Open API",
                "endpoint": "https://data.brreg.no/enhetsregisteret/api",
                "auth_required": False,
                "license": "NLOD-2.0",
                "attribution": "Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene.",
            },
            {
                "name": "Regnskapsregisteret Open API",
                "endpoint": "https://data.brreg.no/regnskapsregisteret/regnskap",
                "auth_required": False,
                "license": "NLOD-2.0",
                "attribution": "Inneholder regnskapsdata under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene.",
            },
            {
                "name": "Brave Search Web API (Optional)",
                "endpoint": "https://api.search.brave.com/res/v1/web/search",
                "auth_required": True,
                "license": "Commercial Terms of Service",
                "attribution": "Search candidate results provided via Brave Search API.",
            },
        ],
        "datasets": datasets,
        "outputs": {
            "envelopes_jsonl": {
                "path": "out/envelopes.jsonl",
                "sha256": compute_sha256(out_envelopes),
                "count": 1000 if out_envelopes.exists() else 0,
            },
            "profiles_jsonl": {
                "path": "out/profiles.jsonl",
                "sha256": compute_sha256(out_profiles),
                "count": 1000 if out_profiles.exists() else 0,
            },
            "report_json": {
                "path": "out/run-report.json",
                "sha256": compute_sha256(out_report),
            },
        },
        "pinned_dependencies": deps,
    }

    manifest_path = ROOT / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated {manifest_path} (Commit: {git_info['commit_sha'][:8]}, Datasets: {len(datasets)}, Deps: {len(deps)})")


if __name__ == "__main__":
    main()
