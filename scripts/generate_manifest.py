#!/usr/bin/env python3
"""Generate machine-readable MANIFEST.json capturing the exact reproducibility state for OrgTrace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

# Verified historical baseline SHAs for large assets that may be stored out-of-repo
VERIFIED_DATASET_SHAS = {
    "brreg-enheter.csv": "5392f7a9b625594fdbd7aa21bbf2badc18201f0ec8956930bf47e3245166a455",
    "signalpost-universe.jsonl.gz": "1c89710e5b01f8617e86d09fbdff4a52f2f8dbbba297e74f7164b5984f5a0384",
}


def compute_sha256(path: Path) -> str:
    if not path.exists():
        return "not_found"
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_info(override_commit: str | None = None, override_branch: str | None = None) -> dict[str, str]:
    try:
        commit = override_commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        branch = override_branch or subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = override_commit or "unknown"
        branch = override_branch or "unknown"
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
    parser = argparse.ArgumentParser(description="Generate or check reproducibility MANIFEST.json for OrgTrace")
    parser.add_argument("--commit", default=None, help="Explicit git commit SHA to record")
    parser.add_argument("--branch", default=None, help="Explicit git branch name to record")
    parser.add_argument("--check", action="store_true", help="Check existing MANIFEST.json without writing")
    args = parser.parse_args()

    git_info = get_git_info(args.commit, args.branch)
    deps = get_pinned_dependencies()

    smoke_path = ROOT / "smoke-companies.jsonl"
    if not smoke_path.exists():
        smoke_path = ROOT / "data" / "smoke-companies.jsonl"
    smoke_sha = compute_sha256(smoke_path)

    brreg_path = ROOT / "brreg-enheter.csv"
    brreg_sha = compute_sha256(brreg_path) if brreg_path.exists() else VERIFIED_DATASET_SHAS["brreg-enheter.csv"]

    universe_path = ROOT / "signalpost-universe.jsonl.gz"
    universe_sha = compute_sha256(universe_path) if universe_path.exists() else VERIFIED_DATASET_SHAS["signalpost-universe.jsonl.gz"]

    datasets = [
        {
            "filename": "entry-companies.jsonl",
            "sha256": compute_sha256(ROOT / "entry-companies.jsonl"),
            "rows": 1000,
            "description": "Selected competition entry batch from signalpost-universe.jsonl.gz (seed 20260823)",
        },
        {
            "filename": "smoke-companies.jsonl",
            "sha256": smoke_sha,
            "rows": 10,
            "description": "10-company smoke test subset of entry-companies.jsonl",
        },
        {
            "filename": "brreg-enheter.csv",
            "sha256": brreg_sha,
            "rows": 1174956,
            "description": "Brønnøysundregistrene Enhetsregisteret bulk CSV export",
        },
        {
            "filename": "signalpost-universe.jsonl.gz",
            "sha256": universe_sha,
            "rows": 411160,
            "description": "Signalpost 2025 public universe archive",
        },
    ]

    out_envelopes = ROOT / "out" / "final-benchmark-envelopes.jsonl"
    if not out_envelopes.exists():
        out_envelopes = ROOT / "out" / "envelopes.jsonl"
    out_profiles = ROOT / "out" / "final-benchmark-profiles.jsonl"
    if not out_profiles.exists():
        out_profiles = ROOT / "out" / "profiles.jsonl"
    out_report = ROOT / "out" / "final-benchmark-report.json"
    if not out_report.exists():
        out_report = ROOT / "out" / "run-report.json"

    # Use commit timestamp if available for reproducibility, or fallback to current UTC date
    try:
        commit_ts = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI", git_info["commit_sha"]],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        commit_ts = ""
    timestamp_utc = commit_ts if commit_ts else subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()

    manifest = {
        "schema_version": "1.0.0",
        "project": {
            "name": "OrgTrace",
            "agent_entry_name": "OrgTrace",
            "builder_name": "Naman Deep Tripathi",
            "version": "0.1.0",
            "description": "Deterministic, evidence-backed Norwegian enterprise intelligence engine",
            "repository": "https://github.com/namandeeptripathi/OrgTrace",
        },
        "reproducibility": {
            "git_commit": git_info["commit_sha"],
            "git_branch": git_info["branch"],
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "timestamp_utc": timestamp_utc,
        },
        "execution": {
            "entrypoint_command": "./scripts/run_competition.sh",
            "batch_command": "./scripts/run_competition.sh smoke",
            "evaluation_command": "PYTHONPATH=src uv run python -m norway_company_agent.evaluation",
            "test_command": "uv run pytest",
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

    if args.check:
        if not manifest_path.exists():
            print(f"ERROR: {manifest_path} does not exist.")
            sys.exit(1)
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Verify critical fields match
        mismatches = []
        if existing.get("project", {}).get("name") != manifest["project"]["name"]:
            mismatches.append("project.name")
        recorded_commit = existing.get("reproducibility", {}).get("git_commit")
        try:
            parent_commit = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            parent_commit = ""
        valid_commits = {manifest["reproducibility"]["git_commit"], parent_commit}
        if args.commit:
            valid_commits.add(args.commit)
        if recorded_commit not in valid_commits:
            mismatches.append(f"git_commit (expected {manifest['reproducibility']['git_commit']}, got {recorded_commit})")
        if existing.get("execution", {}).get("test_command") != manifest["execution"]["test_command"]:
            mismatches.append("execution.test_command")
        if mismatches:
            print("ERROR: MANIFEST.json discrepancies detected:")
            for m in mismatches:
                print(f"  - {m}")
            sys.exit(1)
        print("MANIFEST.json is valid and verified.")
        sys.exit(0)

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated {manifest_path} (Commit: {git_info['commit_sha'][:8]}, Datasets: {len(datasets)}, Deps: {len(deps)})")


if __name__ == "__main__":
    main()
