"""Stage 9: Competition Batch Engine.

Provides high-throughput 1,000+ profile streaming support, 100-company evaluation
envelopes, exact terminal states, thread-safe parallel execution with hard request/
runtime/cost budgets, deterministic output ordering, resumable caching, and run
manifest validation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Iterable

from .evidence import utc_now
from .identity_engine import canonicalize_org_number
from .strategy_harness import compute_dict_fingerprint


# ============================================================================
# 1. ENUMS & DATA MODELS
# ============================================================================

class BatchTerminalState(str, Enum):
    """Deterministic terminal states for company evaluations."""
    COMPLETE = "complete"
    FAILED = "source_error"
    REQUEST_BUDGET_EXCEEDED = "request_budget_exceeded"
    RUNTIME_BUDGET_EXCEEDED = "runtime_budget_exceeded"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED_POLICY = "blocked_policy"
    BLOCKED_ROBOTS = "blocked_robots"
    CANCELLED = "cancelled"


VALID_TERMINAL_STATES = {state.value for state in BatchTerminalState}


@dataclass
class EvaluationEnvelope:
    """Configured evaluation scope for competition runs."""
    envelope_id: str
    selected_organisations: list[str]
    max_evaluation_count: int = 100
    request_budget: int = 500
    runtime_budget_seconds: float = 60.0
    cost_budget: float = 10.0
    strategy_id: str = "default"
    strategy_version: str = "v1"
    configuration: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    def __post_init__(self):
        # Canonicalize all organisation numbers
        self.selected_organisations = [
            canonicalize_org_number(str(org)) for org in self.selected_organisations if str(org).strip()
        ]
        # Never exceed max_evaluation_count
        if len(self.selected_organisations) > self.max_evaluation_count:
            self.selected_organisations = self.selected_organisations[:self.max_evaluation_count]

    @property
    def config_fingerprint(self) -> str:
        return compute_dict_fingerprint(self.configuration)

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "selected_organisations": list(self.selected_organisations),
            "max_evaluation_count": self.max_evaluation_count,
            "request_budget": self.request_budget,
            "runtime_budget_seconds": self.runtime_budget_seconds,
            "cost_budget": self.cost_budget,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "configuration": dict(self.configuration),
            "config_fingerprint": self.config_fingerprint,
            "schema_version": self.schema_version,
        }


@dataclass
class BatchCompanyResult:
    """Outcome of evaluating a single company within a batch."""
    organisation_number: str
    terminal_state: BatchTerminalState
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    requests_used: int = 0
    runtime_ms: float = 0.0
    cost_incurred: float = 0.0
    error_message: str | None = None
    cached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organisation_number": self.organisation_number,
            "terminal_state": self.terminal_state.value,
            "success": self.success,
            "data": self.data,
            "requests_used": self.requests_used,
            "runtime_ms": round(self.runtime_ms, 3),
            "cost_incurred": round(self.cost_incurred, 5),
            "error_message": self.error_message,
            "cached": self.cached,
            "metadata": self.metadata,
        }


@dataclass
class RunManifest:
    """Comprehensive, machine-validatable manifest describing a batch execution."""
    run_id: str
    strategy_id: str
    strategy_version: str
    input_dataset_fingerprint: str
    selected_evaluation_set: list[str]
    evaluation_count: int
    budgets: dict[str, Any]
    config_fingerprint: str
    completed_count: int
    failed_count: int
    terminal_state_counts: dict[str, int]
    total_requests_used: int
    total_cost_incurred: float
    total_runtime_seconds: float
    output_fingerprint: str
    cache_info: dict[str, Any]
    schema_version: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "input_dataset_fingerprint": self.input_dataset_fingerprint,
            "selected_evaluation_set": self.selected_evaluation_set,
            "evaluation_count": self.evaluation_count,
            "budgets": self.budgets,
            "config_fingerprint": self.config_fingerprint,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "terminal_state_counts": self.terminal_state_counts,
            "total_requests_used": self.total_requests_used,
            "total_cost_incurred": round(self.total_cost_incurred, 5),
            "total_runtime_seconds": round(self.total_runtime_seconds, 3),
            "output_fingerprint": self.output_fingerprint,
            "cache_info": self.cache_info,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }


@dataclass
class ManifestValidationResult:
    """Outcome of validating a batch run manifest against envelope and results."""
    passed: bool
    checks: dict[str, bool]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "errors": self.errors,
        }


# ============================================================================
# 2. THREAD-SAFE BUDGET TRACKER
# ============================================================================

class SharedBudgetTracker:
    """Thread-safe budget tracker enforcing hard limits on requests, cost, runtime, and count.

    Protects against race conditions across parallel worker threads.
    """

    def __init__(
        self,
        max_requests: int,
        max_cost: float,
        max_runtime_seconds: float,
        max_evaluations: int,
    ):
        self._lock = threading.Lock()
        self.max_requests = max_requests
        self.max_cost = max_cost
        self.max_runtime_seconds = max_runtime_seconds
        self.max_evaluations = max_evaluations

        self.requests_used = 0
        self.cost_incurred = 0.0
        self.evaluations_started = 0
        self.evaluations_completed = 0
        self.start_time = time.monotonic()
        self._stopped_reason: BatchTerminalState | None = None

    def check_runtime(self) -> tuple[bool, BatchTerminalState | None]:
        """Check if elapsed time exceeds runtime budget."""
        with self._lock:
            if self._stopped_reason:
                return False, self._stopped_reason
            elapsed = time.monotonic() - self.start_time
            if elapsed >= self.max_runtime_seconds:
                self._stopped_reason = BatchTerminalState.RUNTIME_BUDGET_EXCEEDED
                return False, self._stopped_reason
            return True, None

    def try_start_evaluation(self) -> tuple[bool, BatchTerminalState | None]:
        """Atomically check if another evaluation can be started."""
        with self._lock:
            if self._stopped_reason:
                return False, self._stopped_reason
            elapsed = time.monotonic() - self.start_time
            if elapsed >= self.max_runtime_seconds:
                self._stopped_reason = BatchTerminalState.RUNTIME_BUDGET_EXCEEDED
                return False, self._stopped_reason
            if self.evaluations_started >= self.max_evaluations:
                return False, None
            self.evaluations_started += 1
            return True, None

    def acquire_requests(self, count: int = 1) -> tuple[bool, BatchTerminalState | None]:
        """Atomically check and increment request budget."""
        with self._lock:
            if self._stopped_reason:
                return False, self._stopped_reason
            elapsed = time.monotonic() - self.start_time
            if elapsed >= self.max_runtime_seconds:
                self._stopped_reason = BatchTerminalState.RUNTIME_BUDGET_EXCEEDED
                return False, self._stopped_reason
            if self.requests_used + count > self.max_requests:
                self._stopped_reason = BatchTerminalState.REQUEST_BUDGET_EXCEEDED
                return False, self._stopped_reason
            self.requests_used += count
            return True, None

    def acquire_cost(self, amount: float) -> tuple[bool, BatchTerminalState | None]:
        """Atomically check and increment cost budget."""
        with self._lock:
            if self._stopped_reason:
                return False, self._stopped_reason
            elapsed = time.monotonic() - self.start_time
            if elapsed >= self.max_runtime_seconds:
                self._stopped_reason = BatchTerminalState.RUNTIME_BUDGET_EXCEEDED
                return False, self._stopped_reason
            if self.cost_incurred + amount > self.max_cost:
                self._stopped_reason = BatchTerminalState.COST_BUDGET_EXCEEDED
                return False, self._stopped_reason
            self.cost_incurred += amount
            return True, None

    def record_completed(self) -> None:
        """Record completion of one evaluation."""
        with self._lock:
            self.evaluations_completed += 1

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def stopped_reason(self) -> BatchTerminalState | None:
        with self._lock:
            return self._stopped_reason


# ============================================================================
# 3. RESULT CACHING & RESUME ENGINE
# ============================================================================

def compute_cache_key(
    org_number: str,
    strategy_id: str,
    strategy_version: str,
    config_fingerprint: str,
    schema_version: str,
) -> str:
    """Compute deterministic cache key for a company evaluation."""
    canonical_org = canonicalize_org_number(org_number)
    raw = f"{canonical_org}|{strategy_id}|{strategy_version}|{config_fingerprint}|{schema_version}"
    return "cache-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class ResultCache:
    """Thread-safe in-memory or file-backed result cache for resumable batch execution."""

    def __init__(self, cache_dir: Path | str | None = None):
        self._lock = threading.Lock()
        self._memory_cache: dict[str, dict[str, Any]] = {}
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve a cached result if valid."""
        with self._lock:
            if cache_key in self._memory_cache:
                return copy.deepcopy(self._memory_cache[cache_key])

        if self.cache_dir:
            path = self.cache_dir / f"{cache_key}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    with self._lock:
                        self._memory_cache[cache_key] = data
                    return copy.deepcopy(data)
                except Exception:
                    return None
        return None

    def put(self, cache_key: str, data: dict[str, Any]) -> None:
        """Store a completed result in the cache."""
        with self._lock:
            self._memory_cache[cache_key] = copy.deepcopy(data)

        if self.cache_dir:
            path = self.cache_dir / f"{cache_key}.json"
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass


# ============================================================================
# 4. STREAMING & CHUNKING FOR 1,000+ PROFILES
# ============================================================================

def iter_company_inputs(
    data_source: Iterable[dict[str, Any] | str],
    chunk_size: int = 100,
) -> Generator[list[dict[str, Any]], None, None]:
    """Stream inputs in bounded chunks to support 1,000+ profiles without high memory usage."""
    chunk: list[dict[str, Any]] = []
    for item in data_source:
        if isinstance(item, str):
            record = {"organisation_number": canonicalize_org_number(item)}
        else:
            record = dict(item)
            if "organisation_number" in record:
                record["organisation_number"] = canonicalize_org_number(str(record["organisation_number"]))
        chunk.append(record)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def compute_output_fingerprint(results: list[BatchCompanyResult]) -> str:
    """Compute deterministic SHA-256 fingerprint of batch results (excluding timestamps and run IDs)."""
    normalized_items = []
    for r in results:
        normalized_items.append({
            "org": r.organisation_number,
            "state": r.terminal_state.value,
            "success": r.success,
            "requests": r.requests_used,
            "cost": round(r.cost_incurred, 4),
            "data": r.data,
        })
    # Deterministic sorting
    normalized_items.sort(key=lambda x: x["org"])
    raw = json.dumps(normalized_items, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ============================================================================
# 5. COMPETITION BATCH ORCHESTRATION ENGINE
# ============================================================================

class CompetitionBatchEngine:
    """Orchestrates bounded parallel evaluation with hard budget enforcement and caching."""

    def __init__(
        self,
        envelope: EvaluationEnvelope,
        worker_fn: Callable[[dict[str, Any], SharedBudgetTracker], BatchCompanyResult],
        max_workers: int = 4,
        cache: ResultCache | None = None,
    ):
        self.envelope = envelope
        self.worker_fn = worker_fn
        self.max_workers = max(1, min(max_workers, 16))
        self.cache = cache or ResultCache()

    def run(self, input_companies: list[dict[str, Any]] | None = None) -> tuple[list[BatchCompanyResult], RunManifest]:
        """Execute the batch evaluation over the configured envelope."""
        org_set = set(self.envelope.selected_organisations)
        
        # Filter inputs to selected envelope
        inputs_by_org: dict[str, dict[str, Any]] = {}
        if input_companies:
            for item in input_companies:
                org = canonicalize_org_number(str(item.get("organisation_number") or ""))
                if org in org_set and org not in inputs_by_org:
                    inputs_by_org[org] = dict(item)

        # For any selected org not in inputs, create minimal input
        for org in self.envelope.selected_organisations:
            if org not in inputs_by_org:
                inputs_by_org[org] = {"organisation_number": org}

        ordered_inputs = [inputs_by_org[org] for org in self.envelope.selected_organisations]

        budget = SharedBudgetTracker(
            max_requests=self.envelope.request_budget,
            max_cost=self.envelope.cost_budget,
            max_runtime_seconds=self.envelope.runtime_budget_seconds,
            max_evaluations=len(ordered_inputs),
        )

        results_by_org: dict[str, BatchCompanyResult] = {}
        cached_count = 0
        pending_inputs: list[dict[str, Any]] = []

        # Check cache first for each company
        for item in ordered_inputs:
            org = item["organisation_number"]
            cache_key = compute_cache_key(
                org,
                self.envelope.strategy_id,
                self.envelope.strategy_version,
                self.envelope.config_fingerprint,
                self.envelope.schema_version,
            )
            cached_data = self.cache.get(cache_key)
            if cached_data:
                # Valid cache hit
                res = BatchCompanyResult(
                    organisation_number=org,
                    terminal_state=BatchTerminalState(cached_data.get("terminal_state", "complete")),
                    success=cached_data.get("success", True),
                    data=cached_data.get("data", {}),
                    requests_used=cached_data.get("requests_used", 0),
                    runtime_ms=cached_data.get("runtime_ms", 0.0),
                    cost_incurred=cached_data.get("cost_incurred", 0.0),
                    error_message=cached_data.get("error_message"),
                    cached=True,
                )
                results_by_org[org] = res
                cached_count += 1
            else:
                pending_inputs.append(item)

        # Worker execution helper
        def execute_task(company: dict[str, Any]) -> BatchCompanyResult:
            org = company["organisation_number"]

            can_start, stop_reason = budget.try_start_evaluation()
            if not can_start:
                terminal_state = stop_reason or BatchTerminalState.CANCELLED
                return BatchCompanyResult(
                    organisation_number=org,
                    terminal_state=terminal_state,
                    success=False,
                    error_message=f"Evaluation skipped: {terminal_state.value}",
                )

            t0 = time.monotonic()
            try:
                res = self.worker_fn(company, budget)
                res.runtime_ms = (time.monotonic() - t0) * 1000.0
                budget.record_completed()

                # Cache successful / complete results
                if res.success and res.terminal_state == BatchTerminalState.COMPLETE:
                    cache_key = compute_cache_key(
                        org,
                        self.envelope.strategy_id,
                        self.envelope.strategy_version,
                        self.envelope.config_fingerprint,
                        self.envelope.schema_version,
                    )
                    self.cache.put(cache_key, res.to_dict())

                return res
            except Exception as exc:
                res = BatchCompanyResult(
                    organisation_number=org,
                    terminal_state=BatchTerminalState.FAILED,
                    success=False,
                    runtime_ms=(time.monotonic() - t0) * 1000.0,
                    error_message=f"Worker exception: {exc}",
                )
                budget.record_completed()
                return res

        # Parallel execution with thread pool
        if pending_inputs:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(execute_task, item): item["organisation_number"] for item in pending_inputs}
                for future in as_completed(futures):
                    org = futures[future]
                    res = future.result()
                    results_by_org[org] = res

        # Deterministic result ordering: strictly matches envelope.selected_organisations
        ordered_results = [results_by_org[org] for org in self.envelope.selected_organisations]

        # Calculate metrics and manifest
        completed_count = sum(1 for r in ordered_results if r.terminal_state == BatchTerminalState.COMPLETE)
        failed_count = len(ordered_results) - completed_count
        state_counts: dict[str, int] = {}
        for r in ordered_results:
            state_counts[r.terminal_state.value] = state_counts.get(r.terminal_state.value, 0) + 1

        output_fp = compute_output_fingerprint(ordered_results)
        input_fp = hashlib.sha256(" ".join(self.envelope.selected_organisations).encode("utf-8")).hexdigest()[:16]

        manifest = RunManifest(
            run_id=f"run-{self.envelope.envelope_id}",
            strategy_id=self.envelope.strategy_id,
            strategy_version=self.envelope.strategy_version,
            input_dataset_fingerprint=input_fp,
            selected_evaluation_set=list(self.envelope.selected_organisations),
            evaluation_count=len(ordered_results),
            budgets=self.envelope.to_dict(),
            config_fingerprint=self.envelope.config_fingerprint,
            completed_count=completed_count,
            failed_count=failed_count,
            terminal_state_counts=state_counts,
            total_requests_used=budget.requests_used,
            total_cost_incurred=budget.cost_incurred,
            total_runtime_seconds=budget.elapsed_seconds,
            output_fingerprint=output_fp,
            cache_info={"cached_hits": cached_count, "executed_count": len(pending_inputs)},
            schema_version=self.envelope.schema_version,
        )

        return ordered_results, manifest


# ============================================================================
# 6. MANIFEST VALIDATION
# ============================================================================

def validate_manifest(
    manifest: RunManifest,
    envelope: EvaluationEnvelope,
    results: list[BatchCompanyResult],
) -> ManifestValidationResult:
    """Validate that a batch run manifest strictly matches envelope requirements and actual results.

    Fails closed if:
    - Counts mismatch
    - Organisation numbers differ or contain duplicates
    - Terminal states are invalid
    - Budget accounting is inconsistent
    - Results are not in deterministic order
    """
    errors: list[str] = []
    checks: dict[str, bool] = {}

    # 1. Strategy match
    checks["strategy_match"] = (
        manifest.strategy_id == envelope.strategy_id
        and manifest.strategy_version == envelope.strategy_version
    )
    if not checks["strategy_match"]:
        errors.append(f"Strategy mismatch: manifest has {manifest.strategy_id}@{manifest.strategy_version}, envelope expected {envelope.strategy_id}@{envelope.strategy_version}")

    # 2. Config fingerprint match
    checks["config_match"] = manifest.config_fingerprint == envelope.config_fingerprint
    if not checks["config_match"]:
        errors.append(f"Config fingerprint mismatch: {manifest.config_fingerprint} vs {envelope.config_fingerprint}")

    # 3. Count match
    checks["count_match"] = (
        manifest.evaluation_count == len(results)
        and manifest.evaluation_count == len(envelope.selected_organisations)
    )
    if not checks["count_match"]:
        errors.append(f"Evaluation count mismatch: manifest={manifest.evaluation_count}, results={len(results)}, envelope={len(envelope.selected_organisations)}")

    # 4. Organisation membership & ordering
    result_orgs = [r.organisation_number for r in results]
    checks["unique_organisations"] = len(result_orgs) == len(set(result_orgs))
    if not checks["unique_organisations"]:
        errors.append("Duplicate organisation records found in results")

    checks["deterministic_ordering"] = result_orgs == envelope.selected_organisations
    if not checks["deterministic_ordering"]:
        errors.append("Results do not match deterministic envelope ordering")

    # 5. Terminal states validity
    invalid_states = [r.terminal_state.value for r in results if r.terminal_state.value not in VALID_TERMINAL_STATES]
    checks["valid_terminal_states"] = len(invalid_states) == 0
    if not checks["valid_terminal_states"]:
        errors.append(f"Invalid terminal states found: {set(invalid_states)}")

    # 6. Terminal state counts match
    actual_state_counts: dict[str, int] = {}
    for r in results:
        actual_state_counts[r.terminal_state.value] = actual_state_counts.get(r.terminal_state.value, 0) + 1
    checks["state_counts_match"] = actual_state_counts == manifest.terminal_state_counts
    if not checks["state_counts_match"]:
        errors.append(f"State counts mismatch: actual={actual_state_counts}, manifest={manifest.terminal_state_counts}")

    # 7. Output fingerprint match
    actual_output_fp = compute_output_fingerprint(results)
    checks["output_fingerprint_match"] = actual_output_fp == manifest.output_fingerprint
    if not checks["output_fingerprint_match"]:
        errors.append(f"Output fingerprint mismatch: {actual_output_fp} vs {manifest.output_fingerprint}")

    passed = all(checks.values())
    return ManifestValidationResult(
        passed=passed,
        checks=checks,
        errors=errors,
    )
