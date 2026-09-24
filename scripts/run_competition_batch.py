#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from norway_company_agent.batch import compute_profile_status, profile_complete_for_modules, profiles_from_bulk, read_organisation_inputs, terminal_envelope, validate_envelopes  # noqa: E402
from norway_company_agent.change_intelligence import analyze_profile_changes  # noqa: E402
from norway_company_agent.discovery import choose_search_candidate  # noqa: E402
from norway_company_agent.evidence import evidence, utc_now  # noqa: E402
from norway_company_agent.explanations import explain_company_profile  # noqa: E402
from norway_company_agent.http import fetch_json  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.resilience import CompetitionExecutionGuard, FailureCategory, classify_failure  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402
from scripts.run_brave_discovery import brave_search  # noqa: E402


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator-owned Signalpost batch contract")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL, or text organisation-number list")
    parser.add_argument("--bulk", default=None, help="Frozen Brreg entity snapshot (optional)")
    parser.add_argument("--output", required=True, help="Terminal envelope JSONL")
    parser.add_argument("--profiles-output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,roles,group,locations,website")
    parser.add_argument("--max-requests", type=int, default=2000, help="Maximum external requests per execution")
    parser.add_argument("--max-cost", type=float, default=10.0, help="Maximum external API cost in USD")
    parser.add_argument("--max-runtime", type=float, default=2700.0, help="Maximum execution runtime in seconds (45 min = 2700s)")
    parser.add_argument("--reduced-mode-threshold", type=float, default=2400.0, help="Runtime in seconds to trigger reduced mode (40 min = 2400s)")
    parser.add_argument("--brave-api-key-env", default="BRAVE_SEARCH_API_KEY", help="Env var holding the Brave Search API key for discovery")
    parser.add_argument("--discovery-timeout", type=float, default=15.0)
    parser.add_argument("--discovery-count", type=int, default=10)
    parser.add_argument("--previous-profiles", default=None, help="Optional previous profiles JSONL for change intelligence")
    parser.add_argument("--changes-output", default=None, help="Optional change intelligence report output path")
    parser.add_argument("--explanations-output", default=None, help="Optional explanations report output path")
    args = parser.parse_args()

    brave_api_key = os.environ.get(args.brave_api_key_env, "").strip()

    started_at = utc_now()
    guard = CompetitionExecutionGuard(
        max_requests=args.max_requests,
        max_cost=args.max_cost,
        max_runtime_seconds=args.max_runtime,
        reduced_mode_threshold_seconds=args.reduced_mode_threshold,
    )

    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    if len(orgs) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} organisations, received {len(orgs)}")
    profiles, registry_metadata = profiles_from_bulk(args.bulk, orgs)
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]
    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", "website"}
    operations = {"requests": 0, "bytes": 0, "latencies_ms": []}

    def enrich(profile: dict) -> tuple[dict, dict]:
        try:
            records, metrics = fetch_official_modules(
                profile["organisation_number"],
                fetch_modules,
                fetcher=lambda u: fetch_json(u, guard=guard),
            )
            profile.setdefault("evidence", {}).update(records)
            website_metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
            if "website" in requested_modules:
                if profile.get("website"):
                    # Registry website exists — use the existing direct-fetch path.
                    website_record, website_metrics = fetch_website(profile.get("website"), guard=guard)
                    profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
                elif brave_api_key and not guard.is_reduced_mode():
                    # No registry website — attempt discovery fallback if budget permits.
                    allowed, reason = guard.acquire_request(cost=0.005)
                    if allowed:
                        search_results, search_op = brave_search(
                            profile, brave_api_key,
                            timeout=args.discovery_timeout, count=args.discovery_count,
                        )
                        website_metrics["requests"] += 1
                        website_metrics["bytes"] += search_op.get("bytes", 0)
                        if search_op.get("latency_ms"):
                            website_metrics["latencies_ms"].append(search_op["latency_ms"])
                        decision = choose_search_candidate(profile, search_results)
                        selected = decision.get("selected")
                        if selected:
                            website_record, crawl_metrics = fetch_website(selected["url"], guard=guard)
                            website_metrics["requests"] += crawl_metrics["requests"]
                            website_metrics["bytes"] += crawl_metrics["bytes"]
                            website_metrics["latencies_ms"].extend(crawl_metrics["latencies_ms"])
                            gated = apply_website_identity_gate(profile, website_record)
                            website = gated["website"]
                            assessment = gated.get("assessment")
                            website["source_type"] = "search_discovered_company_website"
                            if assessment and assessment.get("publishable") and website.get("status") == "available":
                                profile["evidence"]["website"] = website
                            else:
                                profile["evidence"]["website"] = evidence(
                                    "website", "not_found",
                                    "search_discovered_company_website", selected["url"],
                                    note="Search candidate crawled but exact-entity identity not verified",
                                )
                        else:
                            profile["evidence"]["website"] = evidence(
                                "website", "not_found",
                                "search_discovery", "https://api.search.brave.com/res/v1/web/search",
                                note="No search result passed the deterministic crawl-candidate gate",
                            )
                    else:
                        profile["evidence"]["website"] = evidence(
                            "website", "not_attempted",
                            "search_discovery", "https://api.search.brave.com/res/v1/web/search",
                            note=f"Search discovery skipped: {reason}",
                        )
                else:
                    note = "Search discovery skipped in reduced-enrichment mode" if guard.is_reduced_mode() else "No valid registry website URL"
                    profile["evidence"]["website"] = evidence(
                        "website", "not_found",
                        "registry_linked_company_website",
                        "https://data.brreg.no/enhetsregisteret/api/enheter",
                        note=note,
                    )
            metric = {
                "requests": len(metrics) + website_metrics["requests"],
                "bytes": sum(item.bytes_received for item in metrics) + website_metrics["bytes"],
                "latencies_ms": [item.elapsed_ms for item in metrics] + website_metrics["latencies_ms"],
            }
            profile["run_metrics"] = metric
            return profile, metric
        except Exception as exc:
            fail_cat = classify_failure(exc)
            profile.setdefault("errors", []).append({
                "error": str(exc),
                "category": fail_cat.value,
                "type": type(exc).__name__,
            })
            metric = {"requests": 0, "bytes": 0, "latencies_ms": []}
            profile["run_metrics"] = {**metric, "status": "failed", "error": str(exc), "category": fail_cat.value}
            guard.record_request_result(domain="unknown", status_code=0, failure_category=fail_cat)
            return profile, metric

    state: dict[str, dict] = {}
    resumed_profiles = 0
    profiles_output = Path(args.profiles_output)
    if args.resume and profiles_output.exists():
        prior = [json.loads(line) for line in profiles_output.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not set(item["organisation_number"] for item in prior).issubset(set(orgs)):
            raise SystemExit("Resume profile membership is not a subset of this batch")
        state = {
            item["organisation_number"]: item
            for item in prior
            if profile_complete_for_modules(item, requested_modules)
        }
        resumed_profiles = len(state)
    pending_profiles = [profile for profile in profiles if profile["organisation_number"] not in state]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich, profile): profile["organisation_number"] for profile in pending_profiles}
        for index, future in enumerate(as_completed(futures), 1):
            target_org = futures[future]
            try:
                profile, metric = future.result()
            except Exception as exc:
                fail_cat = classify_failure(exc)
                profile = next((p for p in pending_profiles if p["organisation_number"] == target_org), {
                    "organisation_number": target_org,
                    "name": "",
                    "legal_form": "",
                    "evidence": {},
                })
                profile.setdefault("errors", []).append({
                    "error": str(exc),
                    "category": fail_cat.value,
                })
                profile["run_metrics"] = {"requests": 0, "bytes": 0, "latencies_ms": [], "status": "failed", "error": str(exc)}
                metric = {"requests": 0, "bytes": 0, "latencies_ms": []}

            state[profile["organisation_number"]] = profile
            operations["requests"] += metric["requests"]
            operations["bytes"] += metric["bytes"]
            operations["latencies_ms"].extend(metric["latencies_ms"])

            # Check reduced-mode transition
            if guard.should_log_reduced_mode_entry():
                print("\n" + guard.format_execution_budget() + "\n\nEntering reduced-enrichment mode.\n")

            if index % args.checkpoint_every == 0 or index == len(pending_profiles):
                checkpoint = [state[org] for org in orgs if org in state]
                write_jsonl(profiles_output, checkpoint)

    completed_at = utc_now()
    ordered_profiles = [state[org] for org in orgs]

    # Stage 16: Freshness & Change Intelligence comparison
    previous_profiles_by_org: dict[str, dict] = {}
    if args.previous_profiles and Path(args.previous_profiles).exists():
        for line in Path(args.previous_profiles).read_text(encoding="utf-8").splitlines():
            line_str = line.strip()
            if line_str:
                p_data = json.loads(line_str)
                p_org = p_data.get("organisation_number")
                if p_org:
                    previous_profiles_by_org[p_org] = p_data

    change_reports = []
    for profile in ordered_profiles:
        p_org = profile["organisation_number"]
        prev_p = previous_profiles_by_org.get(p_org)
        try:
            ch_report = analyze_profile_changes(prev_p, profile, timestamp=completed_at)
            change_reports.append(ch_report.to_dict())
            profile["change_intelligence"] = ch_report.to_dict()
        except Exception as exc:
            profile["change_intelligence"] = {"status": "INITIAL_OBSERVATION", "material_changes": 0, "error": str(exc)}

    if args.changes_output:
        Path(args.changes_output).parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(Path(args.changes_output), change_reports)

    # Stage 17: Evidence-Grounded Explanations
    explanation_reports = []
    for profile in ordered_profiles:
        try:
            exp_report = explain_company_profile(profile)
            explanation_reports.append(exp_report.to_dict())
            profile["explanations"] = exp_report.to_dict()
        except Exception as exc:
            profile["explanations"] = {"summary": "Explanation generation failed", "error": str(exc), "metrics": {"grounded_rate": 1.0, "evidence_coverage": 0.0}}

    if args.explanations_output:
        Path(args.explanations_output).parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(Path(args.explanations_output), explanation_reports)

    # Calculate batch completion outcomes and assign frontend-ready profile status
    successful_count = 0
    partial_count = 0
    failed_count = 0
    for profile in ordered_profiles:
        status = compute_profile_status(profile)
        profile["status"] = status
        if status == "complete":
            successful_count += 1
        elif status == "partial":
            partial_count += 1
        else:
            failed_count += 1

    envelopes = [
        terminal_envelope(profile, run_id=args.run_id, modules=requested_modules, started_at=started_at, completed_at=completed_at)
        for profile in ordered_profiles
    ]
    validation = validate_envelopes(envelopes, args.expected_count)
    write_jsonl(profiles_output, ordered_profiles)
    write_jsonl(Path(args.output), envelopes)
    latencies = sorted(operations.pop("latencies_ms"))
    operations["p50_ms"] = latencies[len(latencies) // 2] if latencies else None
    operations["p95_ms"] = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None

    # Authoritative competition-facing request counting
    actual_external_requests = operations["requests"]
    guard.record_actual_external_requests(actual_external_requests)
    operations["actual_external_requests"] = actual_external_requests
    operations["tracked_requests"] = guard.tracked_requests

    report = {
        "run_id": args.run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "expected_count": args.expected_count,
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed_profiles,
        "profiles_fetched_this_run": len(pending_profiles),
        "modules": requested_modules,
        "registry": registry_metadata,
        "operations": operations,
        "request_budget": {
            "request_limit": guard.max_requests,
            "actual_external_requests": actual_external_requests,
            "tracked_requests": guard.tracked_requests,
            "request_budget_remaining": max(0, guard.max_requests - actual_external_requests),
            "request_budget_consumed_percent": round((actual_external_requests / guard.max_requests) * 100, 1) if guard.max_requests > 0 else 0.0,
        },
        "validation": validation,
        "batch_summary": {
            "attempted": len(orgs),
            "successful": successful_count,
            "partial": partial_count,
            "failed": failed_count,
        },
        "execution_guard": guard.to_dict(actual_external_requests=actual_external_requests),
        "change_intelligence": {
            "total_evaluated": len(change_reports),
            "with_material_changes": sum(1 for cr in change_reports if cr.get("material_changes", 0) > 0),
            "initial_observations": sum(1 for cr in change_reports if cr.get("status") == "INITIAL_OBSERVATION"),
        },
        "explanations": {
            "total_evaluated": len(explanation_reports),
            "avg_grounded_rate": round(
                sum(er["metrics"]["grounded_rate"] for er in explanation_reports) / len(explanation_reports), 3
            ) if explanation_reports else 1.0,
            "avg_evidence_coverage": round(
                sum(er["metrics"]["evidence_coverage"] for er in explanation_reports) / len(explanation_reports), 3
            ) if explanation_reports else 1.0,
        },
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Output formatted competition cards
    print("\n" + "=" * 60)
    print(guard.format_batch_summary(len(orgs), successful_count, partial_count, failed_count, actual_external_requests=actual_external_requests))
    print("-" * 60)
    print(guard.format_request_budget(actual_external_requests=actual_external_requests))
    print("-" * 60)
    print(guard.format_cost_budget())
    print("-" * 60)
    print(guard.format_execution_budget())
    print("=" * 60 + "\n")

    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()
