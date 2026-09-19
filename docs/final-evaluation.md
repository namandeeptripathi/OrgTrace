# OrgTrace — Final Evaluation & Benchmark Report

This document records the empirical results of the complete test suite, the Stage 10 Evaluation Harness benchmark, and the 1,000-profile competition batch execution for **OrgTrace** (Stage 12 — Final Competition Submission).

---

## 1. Executive Summary

| Verification Area | Command | Scope / Workload | Result | Runtime | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Unit & Integration Tests** | `PYTHONPATH=src uv run python -m unittest tests.test_poc -v` | 254 test cases | **254 passed, 0 failed** | 0.470s | ✅ PASS |
| **Pytest Suite** | `uv run --with pytest pytest -q` | 254 tests + 5 subtests | **254 passed, 0 failed** | 1.410s | ✅ PASS |
| **Evaluation Harness** | `PYTHONPATH=src uv run python -m norway_company_agent.evaluation` | 9 benchmark cases | **9 passed (100.0%)** | 0.0005s | ✅ PASS |
| **1,000-Profile Batch** | `./scripts/run_competition.sh full` | 1,000 company profiles | **1,000 valid envelopes** | 15.58s | ✅ PASS |
| **Smoke Batch** | `./scripts/run_competition.sh smoke` | 10 company profiles | **10 valid envelopes** | 14.77s | ✅ PASS |
| **Deterministic Refresh Replay** | `./scripts/run_competition.sh replay` | Snapshot diff fixture | **100% semantic match** | 0.05s | ✅ PASS |

---

## 2. Stage 10 Evaluation & Optimization Benchmark

- **Execution Command**: `PYTHONPATH=src uv run python -m norway_company_agent.evaluation`
- **Dataset Version**: `1.0.0`
- **Total Cases Evaluated**: 9
- **Passed Cases**: 9 (100.0%)
- **Total Incurred Cost**: $0.000000 USD

### 2.1 Core Evaluation Metrics

| Metric | Measured Value | Competition Target | Status |
| :--- | :--- | :--- | :--- |
| **Usable Result Coverage** | **100.0%** | ≥ 95.0% | ✅ Pass |
| **Field Coverage** | **100.0%** | ≥ 90.0% | ✅ Pass |
| **Exact-Company Precision** | **100.0%** | 100.0% | ✅ Pass |
| **External Precision** | **100.0%** | ≥ 95.0% | ✅ Pass |
| **Recall** | **100.0%** | ≥ 90.0% | ✅ Pass |
| **Evidence Validity Rate** | **100.0%** | 100.0% | ✅ Pass |
| **Refresh Correctness** | **100.0%** | 100.0% | ✅ Pass |
| **False-Change Rate** | **0.0%** | 0.0% | ✅ Pass |

### 2.2 Per-Case Benchmark Results

| Case ID | Category | Verdict Status | Requests | Runtime | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `case-01-exact` | Exact company identity resolution | usable | 1 | 0.0 ms | ✅ PASS |
| `case-02-ambiguous` | Ambiguous name disambiguation | usable | 1 | 0.0 ms | ✅ PASS |
| `case-03-subsidiary` | Subsidiary distinction from parent | usable | 1 | 0.0 ms | ✅ PASS |
| `case-04-parent` | Parent entity with operating arms | usable | 1 | 0.0 ms | ✅ PASS |
| `case-05-similarly-named` | False-positive rejection of lookalikes | usable | 1 | 0.0 ms | ✅ PASS |
| `case-06-weak-web` | Weak web presence handling | usable | 1 | 0.0 ms | ✅ PASS |
| `case-07-missing-info` | Incomplete/missing data handling | usable | 1 | 0.0 ms | ✅ PASS |
| `case-08-changed-info` | Material vs cosmetic change detection | usable | 1 | 0.0 ms | ✅ PASS |
| `case-09-non-target` | Non-target external rejection | rejected | 1 | 0.0 ms | ✅ PASS |

---

## 3. 1,000-Profile Batch Execution Run

- **Execution Command**: `./scripts/run_competition.sh full`
- **Input Manifest**: `entry-companies.jsonl` (1,000 Norwegian organisation numbers sampled from `signalpost-universe.jsonl.gz`)
- **Bulk Registry Snapshot**: `brreg-enheter.csv` (1,174,956 rows scanned)
- **Output Artifacts**:
  - `out/envelopes.jsonl` (1,000 lines, 1 envelope per company)
  - `out/profiles.jsonl` (1,000 lines)
  - `out/run-report.json` (machine-readable run metadata)

### 3.1 Run Metrics (`out/run-report.json`)
```json
{
  "run_id": "test-1000",
  "started_at": "2026-09-19T19:58:30.683746Z",
  "completed_at": "2026-09-19T19:58:46.259903Z",
  "expected_count": 1000,
  "emitted_envelopes": 1000,
  "resumed_profiles": 0,
  "profiles_fetched_this_run": 1000,
  "modules": [
    "registry",
    "accounting_obligation"
  ],
  "registry": {
    "registry_snapshot_sha256": "5392f7a9b625594fdbd7aa21bbf2badc18201f0ec8956930bf47e3245166a455",
    "registry_rows_scanned": 1174956,
    "requested": 1000,
    "selected": 1000,
    "missing": 2
  },
  "operations": {
    "requests": 0,
    "bytes": 0,
    "p50_ms": null,
    "p95_ms": null
  },
  "validation": {
    "passed": true,
    "checks": {
      "exact_expected_count": true,
      "unique_organisation_numbers": true,
      "all_entity_states_terminal": true,
      "all_module_states_terminal": true,
      "zero_silent_drops": true
    },
    "invalid_states": []
  }
}
```

### 3.2 Key Batch Observations:
1. **Zero Silent Drops**: 1,000 input organisations produced exactly 1,000 terminal envelopes (`zero_silent_drops: true`).
2. **Deterministic Terminal States**: All 1,000 envelopes resolved to valid terminal states (`complete` or `not_found`).
3. **Graceful Handling of Dissolved Entities**: Two organisation numbers (`912695875` and `928987728`) present in the older competition universe but absent from the bulk snapshot were gracefully handled as `not_found` with complete provenance notes, avoiding unhandled crashes.
4. **Execution Throughput**: 1,000 profiles processed in 15.58 seconds (~64.2 companies/second) with zero external API fees.

---

## 4. Test Suite Breakdown (254 Tests)

The 254 tests in [`tests/test_poc.py`](file:///Users/apple/Downloads/signalpost-starter-kit/tests/test_poc.py) cover all implemented capabilities across Stages 0 through 11:

- **Stage 0 Baseline & Sampling**: `test_bulk_iterator`, `test_org_number_validation`, `test_read_organisation_inputs`.
- **Stage 1 Identity Engine**: `test_canonicalize_org_number`, `test_luhn_modulo11`, `test_exact_name_matching`, `test_legal_form_normalization`, `test_subsidiary_rejection`, `test_parent_company_rejection`.
- **Stage 2 Website Discovery**: `test_website_identity_gate`, `test_domain_tld_normalization`, `test_brave_search_candidate_selection`.
- **Stage 3 Profile Extraction**: `test_microdata_jsonld_extraction`, `test_leadership_contact_extraction`, `test_social_links_normalization`.
- **Stage 4 Financial Intelligence**: `test_accounting_obligation_assessment`, `test_regnskap_financial_parsing`, `test_financial_metrics_normalization`.
- **Stage 5 Evidence & Provenance Engine**: `test_evidence_creation_and_serialization`, `test_immutable_evidence_dataclass`, `test_provenance_sha256_hash_verification`.
- **Stage 6 External Research**: `test_external_footprint_scoring`, `test_external_task_dispatch`, `test_review_sentiment_integration`.
- **Stage 7 Change Intelligence & Snapshots**: `test_snapshot_immutability`, `test_semantic_value_normalization`, `test_material_change_detection`, `test_failed_refresh_preservation`.
- **Stage 8 Strategy Harness**: `test_strategy_registry`, `test_challenger_promotion_precision_first`, `test_configuration_fingerprinting`.
- **Stage 9 Competition Batch Engine**: `test_iter_company_inputs_streaming`, `test_shared_budget_tracker_race_conditions`, `test_result_cache_resumption`, `test_deterministic_ordering`.
- **Stage 10 Evaluation & Optimization**: `test_evaluation_harness_benchmark`, `test_field_coverage_breakdown`, `test_bottleneck_detection`.
- **Stage 11 Production Hardening**: `test_url_safety_ssrf_blocking`, `test_secret_redaction_logging`, `test_resilience_exponential_backoff`, `test_licensing_nlod_attribution`.

---

## 5. Known Operational Limitations

1. **Brreg Open API Latency**: When full live network enrichment (`modules: registry_live,financials,roles,locations,website`) is enabled for 1,000 companies, runtime is dominated by upstream HTTP response times. To avoid rate limits, concurrency is capped at 8 workers.
2. **Missing Accounts for Small Entities**: Sole proprietorships and holding companies legally exempt from filing accounts will legitimately have `financials: not_applicable`.
3. **Restricted Platforms**: No data is harvested from `proff.no`, `purehelp.no`, or `linkedin.com` to uphold platform terms of service and evaluator trust.
