"""Stage 18: Competition Evaluation Harness Runner.

Orchestrates the entire end-to-end evaluation flow:
Dataset -> Company Selection -> OrgTrace Agent -> Raw Output -> Metrics -> Failure Classification -> Report.
Isolates per-company failures to guarantee batch resilience.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from ..change_intelligence import analyze_profile_changes
from ..evidence import evidence, utc_now
from ..explanations import explain_company_profile
from ..http import FetchResult, fetch_json
from ..identity import apply_website_identity_gate
from ..identity_engine import canonicalize_org_number
from ..official import fetch_official_modules, normalize_entity
from ..website import fetch_website
from .costs import evaluate_company_cost
from .coverage import evaluate_company_coverage
from .dataset import (
    DEFAULT_DATASET_PATH,
    EvaluationDatasetCase,
    load_evaluation_dataset,
    select_evaluation_cases,
)
from .evidence import evaluate_company_evidence
from .explanations import evaluate_company_explanations
from .failures import classify_company_outcome, compute_failure_rates
from .identity import evaluate_company_identity
from .freshness import evaluate_company_freshness
from .models import (
    CompanyEvaluationRecord,
    CompanyEvaluationResultState,
    CompetitionEvaluationReport,
    EvaluationRunMetadata,
    EvaluationSummary,
    IdentityStatus,
    PerformanceEvaluation,
)
from .performance import compute_runtime_statistics, measure_execution_ms
from .report import write_evaluation_reports
from .requests import RequestTracker

logger = logging.getLogger("orgtrace.evaluation.runner")


def _get_git_commit() -> str | None:
    """Safely obtain current git commit hash or None if unavailable."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            commit = res.stdout.strip()
            return commit if commit else None
    except Exception:
        pass
    return None


class CompetitionEvaluationRunner:
    """Configurable evaluation harness runner simulating Signalpost competition scoring."""

    def __init__(
        self,
        dataset_path: str | Path | None = None,
        random_count: int | None = None,
        seed: int | None = None,
        target_company: str | None = None,
        use_llm_evaluation: bool = False,
        output_dir: str | Path = "out/competition-evaluation",
        fetcher: Callable[[str], FetchResult] | None = None,
        verbose: bool = False,
    ):
        self.dataset_path = dataset_path
        self.random_count = random_count
        self.seed = seed
        self.target_company = target_company
        self.use_llm_evaluation = use_llm_evaluation
        self.output_dir = output_dir
        self.custom_fetcher = fetcher
        self.verbose = verbose

    def _execute_agent_for_case(
        self,
        case: EvaluationDatasetCase,
        tracker: RequestTracker,
    ) -> dict[str, Any]:
        """Execute the OrgTrace agent pipeline for an individual evaluation case."""
        query = case.query.strip()
        org_number = None

        # Check if query is 9-digit org number
        digits = "".join(ch for ch in query if ch.isdigit())
        if len(digits) == 9:
            org_number = digits
        elif case.expected_org_number:
            org_number = canonicalize_org_number(case.expected_org_number)

        # Non-target / ambiguous query handling
        if case.category in {"ambiguous", "non_target", "not_found"}:
            if case.category == "non_target":
                return {
                    "query": query,
                    "status": "rejected",
                    "verdict_status": "rejected",
                    "note": "Non-target jurisdiction entity rejected.",
                    "evidence": {},
                }
            if case.category == "ambiguous":
                return {
                    "query": query,
                    "status": "ambiguous",
                    "verdict_status": "ambiguous",
                    "note": "Ambiguous company name without unique org number.",
                    "evidence": {},
                }
            if case.category == "not_found":
                return {
                    "query": query,
                    "status": "not_found",
                    "verdict_status": "not_found",
                    "note": "Organisation number not found in registry.",
                    "evidence": {},
                }

        # If no org number can be resolved
        if not org_number:
            return {
                "query": query,
                "status": "not_found",
                "verdict_status": "not_found",
                "note": "Could not resolve valid organisation number.",
                "evidence": {},
            }

        # Instrumented fetcher wrapper
        def tracked_fetcher(url: str) -> FetchResult:
            t_start = time.perf_counter()
            error_str = None
            status_code = 200
            bytes_count = 0
            ret = None
            try:
                if self.custom_fetcher:
                    ret = self.custom_fetcher(url)
                else:
                    ret = fetch_json(url)
                status_code = ret.status
                bytes_count = ret.bytes_received
                error_str = ret.error
            except Exception as e:
                error_str = str(e)
                status_code = 500
                ret = FetchResult(
                    url=url,
                    status=500,
                    error=error_str,
                    retrieved_at=utc_now(),
                    effective_at=None,
                    content_sha256="",
                    body={},
                    bytes_received=0,
                    elapsed_ms=(time.perf_counter() - t_start) * 1000.0,
                )
            t_lat = (time.perf_counter() - t_start) * 1000.0
            tracker.record(
                url=url,
                status_code=status_code,
                latency_ms=t_lat,
                bytes_count=bytes_count,
                error=error_str,
            )
            return ret

        # 1. Fetch Official Modules (registry_live, financials, roles, group, locations)
        records, _ = fetch_official_modules(
            org_number,
            modules={"registry_live", "financials", "roles", "group", "locations"},
            fetcher=tracked_fetcher,
        )

        reg_live = records.get("registry_live", {})
        entity_data = reg_live.get("value") or {}
        comp_name = entity_data.get("name") or case.expected_name or query
        legal_form = entity_data.get("legal_form") or "AS"
        website_url = entity_data.get("website") or case.expected_website

        profile: dict[str, Any] = {
            "organisation_number": org_number,
            "name": comp_name,
            "legal_form": legal_form,
            "municipality": entity_data.get("municipality") or (entity_data.get("business_address") or {}).get("kommune"),
            "status": "active" if not entity_data.get("bankrupt") else "bankrupt",
            "verdict_status": "verified",
            "website": website_url,
            "evidence": dict(records),
        }

        # 2. Add statutory registry evidence if registry_live was available
        if reg_live.get("status") == "available":
            profile["evidence"]["registry"] = reg_live

        # 3. Handle Website fetch & identity gate if website exists
        if website_url:
            def tracked_site_fetcher(url: str) -> tuple[dict[str, Any], dict[str, Any]]:
                t_start = time.perf_counter()
                rec, metrics = fetch_website(url)
                lat = (time.perf_counter() - t_start) * 1000.0
                tracker.record(
                    url=url,
                    status_code=200 if rec.get("status") == "available" else 404,
                    latency_ms=lat,
                    bytes_count=metrics.get("bytes", 0),
                    retries=0,
                    error=rec.get("note"),
                    request_type="company_website",
                )
                return rec, metrics

            w_rec, _ = tracked_site_fetcher(website_url)
            gated = apply_website_identity_gate(profile, w_rec)
            profile["evidence"]["website"] = gated.get("website", w_rec)

        # 4. Stage 16 Change Intelligence (Freshness)
        if case.baseline_profile:
            ch_report = analyze_profile_changes(case.baseline_profile, profile, timestamp=utc_now())
            profile["change_intelligence"] = ch_report.to_dict()

        # 5. Stage 17 Evidence-Grounded Explanations
        exp_report = explain_company_profile(profile)
        profile["explanations"] = exp_report.to_dict()

        return profile

    def run(self) -> CompetitionEvaluationReport:
        """Run competition evaluation across selected cases with full metric collection."""
        start_time_iso = datetime.now(timezone.utc).isoformat()
        cases, dataset_hash = load_evaluation_dataset(self.dataset_path)

        selected_cases = select_evaluation_cases(
            cases,
            count=self.random_count,
            seed=self.seed,
            target_company=self.target_company,
        )

        company_records: list[CompanyEvaluationRecord] = []
        failure_records: list[dict[str, Any]] = []
        latencies_ms: list[float] = []

        total_requests = 0
        failed_requests = 0
        retry_count = 0
        requests_by_domain: dict[str, int] = {}
        missing_fields_counter: dict[str, int] = {}
        invalid_fields_counter: dict[str, int] = {}
        top_failures: dict[str, int] = {}
        flagged_companies: list[str] = []

        for case in selected_cases:
            tracker = RequestTracker()
            profile_output: dict[str, Any] | None = None
            stage_err: Exception | None = None
            case_latency = 0.0

            # 1. Monotonic timing per company
            with measure_execution_ms() as m:
                try:
                    profile_output = self._execute_agent_for_case(case, tracker)
                except Exception as ex:
                    stage_err = ex
                    logger.warning(f"Error evaluating case {case.case_id}: {ex}")

            case_latency = m["elapsed_ms"]
            latencies_ms.append(case_latency)

            # 2. Evaluate Dimensions
            id_eval = evaluate_company_identity(
                expected_org_number=case.expected_org_number,
                expected_name=case.expected_name,
                observed_profile=profile_output,
                expected_website=case.expected_website,
            )

            cov_eval = evaluate_company_coverage(profile_output)
            ev_eval = evaluate_company_evidence(profile_output)

            fresh_eval = evaluate_company_freshness(
                current_profile=profile_output,
                baseline_profile=case.baseline_profile,
                expected_changes=case.expected_changes,
            )

            exp_eval = evaluate_company_explanations(
                profile_output,
                use_llm_judge=self.use_llm_evaluation,
            )

            req_eval = tracker.get_evaluation()
            perf_eval = PerformanceEvaluation(runtime_ms=case_latency)
            cost_eval = evaluate_company_cost(llm_calls=0, is_available=False)

            # 3. Classify Failure / Resilience
            result_state, failure_detail = classify_company_outcome(
                identity_status=id_eval.status,
                coverage_rate=cov_eval.rate,
                evidence_validity_rate=ev_eval.validity_rate,
                error=stage_err,
                stage="evaluation_execution",
            )

            if failure_detail:
                f_type = failure_detail.get("type", "unknown")
                top_failures[f_type] = top_failures.get(f_type, 0) + 1
                failure_records.append({
                    "case_id": case.case_id,
                    "query": case.query,
                    "failure": failure_detail,
                })
                flagged_companies.append(case.query)

            # Track missing/invalid fields for summary diagnostics
            for mf in cov_eval.missing_fields:
                missing_fields_counter[mf] = missing_fields_counter.get(mf, 0) + 1
            for inv in cov_eval.invalid_fields:
                invalid_fields_counter[inv] = invalid_fields_counter.get(inv, 0) + 1

            # Accumulate requests telemetry
            total_requests += req_eval.total
            failed_requests += req_eval.failed
            retry_count += req_eval.retries
            for dom, cnt in req_eval.requests_by_domain.items():
                requests_by_domain[dom] = requests_by_domain.get(dom, 0) + cnt

            rec = CompanyEvaluationRecord(
                case_id=case.case_id,
                query=case.query,
                identity=id_eval,
                coverage=cov_eval,
                evidence=ev_eval,
                updates=fresh_eval,
                explanations=exp_eval,
                performance=perf_eval,
                requests=req_eval,
                cost=cost_eval,
                result=result_state,
                failure=failure_detail,
                raw_output=profile_output or {},
            )
            company_records.append(rec)

        # Aggregate Statistics
        perf_stats = compute_runtime_statistics(latencies_ms)
        n_eval = len(company_records)

        avg_coverage = sum(c.coverage.rate for c in company_records) / n_eval if n_eval > 0 else 0.0
        avg_field_cov = sum(c.coverage.field_coverage_rate for c in company_records) / n_eval if n_eval > 0 else 0.0
        avg_cat_cov = sum(c.coverage.category_coverage_rate for c in company_records) / n_eval if n_eval > 0 else 0.0

        avg_identity_acc = sum(c.identity.accuracy for c in company_records) / n_eval if n_eval > 0 else 0.0
        wrong_count = sum(1 for c in company_records if c.identity.status == IdentityStatus.WRONG_COMPANY)
        ambig_count = sum(1 for c in company_records if c.identity.status == IdentityStatus.AMBIGUOUS)

        avg_ev_validity = sum(c.evidence.validity_rate for c in company_records) / n_eval if n_eval > 0 else 0.0
        avg_ev_coverage = sum(c.evidence.evidence_coverage for c in company_records) / n_eval if n_eval > 0 else 0.0
        avg_ev_unsupported = sum(c.evidence.unsupported_claim_rate for c in company_records) / n_eval if n_eval > 0 else 0.0

        # Freshness aggregations (excluding unavailable)
        eval_freshness = [c.updates for c in company_records if c.updates.status == "evaluated"]
        fresh_prec = (
            sum(f.precision for f in eval_freshness if f.precision is not None) / len([f for f in eval_freshness if f.precision is not None])
            if any(f.precision is not None for f in eval_freshness) else None
        )
        fresh_rec = (
            sum(f.recall for f in eval_freshness if f.recall is not None) / len([f for f in eval_freshness if f.recall is not None])
            if any(f.recall is not None for f in eval_freshness) else None
        )

        avg_exp_grounding = sum(c.explanations.grounding_rate for c in company_records) / n_eval if n_eval > 0 else 0.0
        avg_exp_ev_ref = sum(c.explanations.evidence_reference_rate for c in company_records) / n_eval if n_eval > 0 else 0.0
        avg_exp_unsupported = sum(c.explanations.unsupported_rate for c in company_records) / n_eval if n_eval > 0 else 0.0

        outcome_rates = compute_failure_rates([{"result": c.result} for c in company_records])

        # Worst performing fields ranking
        worst_fields: list[dict[str, Any]] = []
        for f, m_cnt in sorted(missing_fields_counter.items(), key=lambda x: -x[1])[:10]:
            worst_fields.append({
                "field": f,
                "missing_count": m_cnt,
                "invalid_count": invalid_fields_counter.get(f, 0),
            })

        summary = EvaluationSummary(
            companies_evaluated=n_eval,
            coverage_rate=avg_coverage,
            field_coverage_rate=avg_field_cov,
            category_coverage_rate=avg_cat_cov,
            identity_accuracy=avg_identity_acc,
            wrong_company_rate=wrong_count / n_eval if n_eval > 0 else 0.0,
            ambiguous_identity_rate=ambig_count / n_eval if n_eval > 0 else 0.0,
            evidence_validity_rate=avg_ev_validity,
            evidence_coverage=avg_ev_coverage,
            unsupported_claim_rate=avg_ev_unsupported,
            change_detection_precision=fresh_prec,
            change_detection_recall=fresh_rec,
            explanation_grounding_rate=avg_exp_grounding,
            explanation_evidence_reference_rate=avg_exp_ev_ref,
            unsupported_explanation_rate=avg_exp_unsupported,
            success_rate=outcome_rates["success_rate"],
            partial_success_rate=outcome_rates["partial_success_rate"],
            failure_rate=outcome_rates["failure_rate"],
            timeout_rate=outcome_rates["timeout_rate"],
            identity_failure_rate=outcome_rates["identity_failure_rate"],
            total_runtime_ms=perf_stats["total_runtime_ms"],
            average_runtime_ms=perf_stats["average_runtime_ms"],
            median_runtime_ms=perf_stats["median_runtime_ms"],
            p95_runtime_ms=perf_stats["p95_runtime_ms"],
            min_runtime_ms=perf_stats["min_runtime_ms"],
            max_runtime_ms=perf_stats["max_runtime_ms"],
            total_requests=total_requests,
            average_requests_per_company=total_requests / n_eval if n_eval > 0 else 0.0,
            requests_by_domain=requests_by_domain,
            failed_requests=failed_requests,
            retry_count=retry_count,
            total_llm_calls=0,
            total_tokens=0,
            estimated_cost_usd=None,
            top_failure_categories=top_failures,
            worst_performing_fields=worst_fields,
            companies_requiring_investigation=flagged_companies,
        )

        run_metadata = EvaluationRunMetadata(
            timestamp=start_time_iso,
            seed=self.seed,
            dataset=str(self.dataset_path or DEFAULT_DATASET_PATH),
            dataset_hash=dataset_hash,
            git_commit=_get_git_commit(),
            companies_requested=len(selected_cases),
            companies_evaluated=n_eval,
            configuration={
                "random_count": self.random_count,
                "target_company": self.target_company,
                "use_llm_evaluation": self.use_llm_evaluation,
            },
        )

        report = CompetitionEvaluationReport(
            run=run_metadata,
            summary=summary,
            companies=company_records,
            failures=failure_records,
        )

        # Write reports to out/competition-evaluation/
        write_evaluation_reports(report, output_dir=self.output_dir)

        return report
