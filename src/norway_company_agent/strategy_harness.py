"""Stage 8: Learning & Strategy Harness.

Provides strategy registration, versioning, attempt recording, precision-first
promotion criteria, challenger evaluation, runtime/cost tracking, and frozen
production strategy enforcement.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .evidence import utc_now


# ============================================================================
# 1. ENUMS & DATA MODELS
# ============================================================================

class StrategyStatus(str, Enum):
    """Lifecycle status of an enrichment strategy."""
    CHALLENGER = "challenger"
    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    FROZEN = "frozen"
    RETIRED = "retired"


def compute_dict_fingerprint(data: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 fingerprint for a dictionary."""
    if not data:
        return "empty"
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class StrategyDefinition:
    """Represents an enrichment strategy with configuration, version, and lifecycle state."""
    strategy_id: str
    version: str
    description: str
    configuration: dict[str, Any] = field(default_factory=dict)
    status: StrategyStatus = StrategyStatus.CANDIDATE
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.strategy_id}@{self.version}"

    @property
    def config_fingerprint(self) -> str:
        return compute_dict_fingerprint(self.configuration)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "description": self.description,
            "configuration": dict(self.configuration),
            "status": self.status.value,
            "created_at": self.created_at,
            "config_fingerprint": self.config_fingerprint,
            "metadata": dict(self.metadata),
        }


@dataclass
class StrategyAttempt:
    """Record of a single strategy execution on a company/profile."""
    strategy_id: str
    strategy_version: str
    profile_id: str
    attempt_id: str
    input_fingerprint: str
    output_fingerprint: str
    terminal_state: str
    success: bool
    reason: str | None = None
    request_count: int = 0
    runtime_ms: float = 0.0
    cost: float = 0.0
    timestamp: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "profile_id": self.profile_id,
            "attempt_id": self.attempt_id,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "terminal_state": self.terminal_state,
            "success": self.success,
            "reason": self.reason,
            "request_count": self.request_count,
            "runtime_ms": round(self.runtime_ms, 3),
            "cost": round(self.cost, 5),
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass
class StrategyMetrics:
    """Aggregate evaluation metrics for a strategy over an evaluation set."""
    strategy_id: str
    strategy_version: str
    total_attempts: int
    successful_attempts: int
    failed_attempts: int
    precision: float
    coverage: float
    error_rate: float
    total_requests: int
    avg_requests_per_attempt: float
    total_runtime_ms: float
    avg_runtime_ms: float
    total_cost: float
    avg_cost_per_attempt: float
    terminal_state_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "total_attempts": self.total_attempts,
            "successful_attempts": self.successful_attempts,
            "failed_attempts": self.failed_attempts,
            "precision": round(self.precision, 4),
            "coverage": round(self.coverage, 4),
            "error_rate": round(self.error_rate, 4),
            "total_requests": self.total_requests,
            "avg_requests_per_attempt": round(self.avg_requests_per_attempt, 2),
            "total_runtime_ms": round(self.total_runtime_ms, 2),
            "avg_runtime_ms": round(self.avg_runtime_ms, 2),
            "total_cost": round(self.total_cost, 5),
            "avg_cost_per_attempt": round(self.avg_cost_per_attempt, 5),
            "terminal_state_counts": dict(self.terminal_state_counts),
        }


@dataclass
class PromotionCriteria:
    """Configurable gates for promoting a challenger strategy to production."""
    min_precision: float = 0.95
    max_precision_drop: float = 0.0  # Precision is primary constraint: 0.0 means no degradation allowed
    min_coverage_gain: float = 0.0   # Must at least maintain coverage
    max_request_increase_ratio: float = 1.25  # Maximum 25% increase in requests
    max_runtime_increase_ratio: float = 1.50  # Maximum 50% increase in runtime
    max_cost_increase_ratio: float = 1.50     # Maximum 50% increase in cost
    require_zero_wrong_entities: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_precision": self.min_precision,
            "max_precision_drop": self.max_precision_drop,
            "min_coverage_gain": self.min_coverage_gain,
            "max_request_increase_ratio": self.max_request_increase_ratio,
            "max_runtime_increase_ratio": self.max_runtime_increase_ratio,
            "max_cost_increase_ratio": self.max_cost_increase_ratio,
            "require_zero_wrong_entities": self.require_zero_wrong_entities,
        }


@dataclass
class PromotionDecision:
    """Explainable outcome of comparing a challenger against baseline."""
    promoted: bool
    reason: str
    baseline_metrics: StrategyMetrics
    challenger_metrics: StrategyMetrics
    gate_checks: dict[str, bool]
    comparison_deltas: dict[str, float]
    decided_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "promoted": self.promoted,
            "reason": self.reason,
            "baseline_metrics": self.baseline_metrics.to_dict(),
            "challenger_metrics": self.challenger_metrics.to_dict(),
            "gate_checks": dict(self.gate_checks),
            "comparison_deltas": {k: round(v, 4) for k, v in self.comparison_deltas.items()},
            "decided_at": self.decided_at,
        }


# ============================================================================
# 2. STRATEGY REGISTRY
# ============================================================================

class StrategyRegistry:
    """Central registry managing strategy definitions, lifecycle states, and frozen production state."""

    def __init__(self):
        self._strategies: dict[str, StrategyDefinition] = {}  # key: "strategy_id@version"
        self._frozen_key: str | None = None

    def register_strategy(self, strategy: StrategyDefinition) -> None:
        """Register a new strategy. Re-registering identical key updates or raises if frozen."""
        key = strategy.key
        if key in self._strategies:
            existing = self._strategies[key]
            if existing.status == StrategyStatus.FROZEN:
                raise ValueError(f"Cannot overwrite frozen strategy '{key}'")
        self._strategies[key] = copy.deepcopy(strategy)

    def get_strategy(self, strategy_id: str, version: str | None = None) -> StrategyDefinition | None:
        """Retrieve a strategy by ID and optional version. If version is None, returns latest registered."""
        if version:
            return self._strategies.get(f"{strategy_id}@{version}")
        # Find all versions of strategy_id
        matches = [s for s in self._strategies.values() if s.strategy_id == strategy_id]
        if not matches:
            return None
        # Return the most recently registered
        return matches[-1]

    def list_strategies(self) -> list[StrategyDefinition]:
        """List all registered strategies."""
        return [copy.deepcopy(s) for s in self._strategies.values()]

    def get_frozen_strategy(self) -> StrategyDefinition | None:
        """Retrieve the currently frozen production strategy, if any."""
        if not self._frozen_key or self._frozen_key not in self._strategies:
            return None
        return copy.deepcopy(self._strategies[self._frozen_key])

    def set_frozen_strategy(self, strategy_id: str, version: str) -> None:
        """Explicitly freeze a registered strategy as the production strategy."""
        key = f"{strategy_id}@{version}"
        if key not in self._strategies:
            raise KeyError(f"Strategy '{key}' not found in registry")
        # Unfreeze previous if any
        if self._frozen_key and self._frozen_key in self._strategies:
            self._strategies[self._frozen_key].status = StrategyStatus.RETIRED

        target = self._strategies[key]
        target.status = StrategyStatus.FROZEN
        self._frozen_key = key


# ============================================================================
# 3. METRICS AGGREGATION & EVALUATION
# ============================================================================

def evaluate_strategy_attempts(
    attempts: list[StrategyAttempt],
    total_eligible_profiles: int | None = None,
) -> StrategyMetrics:
    """Aggregate individual attempts into precision, coverage, cost, and runtime metrics.

    Definitions:
    - total_attempts: len(attempts)
    - successful_attempts: count of attempt.success is True
    - precision: successful_attempts / total_attempts (if total_attempts > 0 else 0.0)
    - coverage: successful_attempts / total_eligible_profiles (if provided else total_attempts)
    - error_rate: failed_attempts / total_attempts
    """
    total = len(attempts)
    if total == 0:
        return StrategyMetrics(
            strategy_id="unknown",
            strategy_version="unknown",
            total_attempts=0,
            successful_attempts=0,
            failed_attempts=0,
            precision=0.0,
            coverage=0.0,
            error_rate=0.0,
            total_requests=0,
            avg_requests_per_attempt=0.0,
            total_runtime_ms=0.0,
            avg_runtime_ms=0.0,
            total_cost=0.0,
            avg_cost_per_attempt=0.0,
            terminal_state_counts={},
        )

    strategy_id = attempts[0].strategy_id
    strategy_version = attempts[0].strategy_version

    successful = sum(1 for a in attempts if a.success)
    failed = total - successful

    eligible = total_eligible_profiles if (total_eligible_profiles and total_eligible_profiles > 0) else total
    precision = successful / total if total > 0 else 0.0
    coverage = successful / eligible if eligible > 0 else 0.0
    error_rate = failed / total if total > 0 else 0.0

    total_requests = sum(a.request_count for a in attempts)
    total_runtime = sum(a.runtime_ms for a in attempts)
    total_cost = sum(a.cost for a in attempts)

    state_counts: dict[str, int] = {}
    for a in attempts:
        state_counts[a.terminal_state] = state_counts.get(a.terminal_state, 0) + 1

    return StrategyMetrics(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        total_attempts=total,
        successful_attempts=successful,
        failed_attempts=failed,
        precision=precision,
        coverage=coverage,
        error_rate=error_rate,
        total_requests=total_requests,
        avg_requests_per_attempt=total_requests / total,
        total_runtime_ms=total_runtime,
        avg_runtime_ms=total_runtime / total,
        total_cost=total_cost,
        avg_cost_per_attempt=total_cost / total,
        terminal_state_counts=state_counts,
    )


def compare_strategies(
    baseline: StrategyMetrics,
    challenger: StrategyMetrics,
) -> dict[str, float]:
    """Calculate metric deltas between baseline and challenger (challenger - baseline)."""
    return {
        "precision_delta": challenger.precision - baseline.precision,
        "coverage_delta": challenger.coverage - baseline.coverage,
        "error_rate_delta": challenger.error_rate - baseline.error_rate,
        "requests_delta": float(challenger.total_requests - baseline.total_requests),
        "requests_ratio": (challenger.avg_requests_per_attempt / baseline.avg_requests_per_attempt) if baseline.avg_requests_per_attempt > 0 else 1.0,
        "runtime_ratio": (challenger.avg_runtime_ms / baseline.avg_runtime_ms) if baseline.avg_runtime_ms > 0 else 1.0,
        "cost_ratio": (challenger.avg_cost_per_attempt / baseline.avg_cost_per_attempt) if baseline.avg_cost_per_attempt > 0 else 1.0,
    }


# ============================================================================
# 4. PRECISION-FIRST PROMOTION ENGINE
# ============================================================================

def evaluate_promotion(
    baseline: StrategyMetrics,
    challenger: StrategyMetrics,
    criteria: PromotionCriteria | None = None,
) -> PromotionDecision:
    """Evaluate whether a challenger strategy qualifies for promotion over baseline.

    Strict Invariants:
    1. Precision is the primary constraint. Higher coverage cannot compensate for precision loss.
    2. Precision must meet minimum threshold AND not drop beyond max_precision_drop.
    3. Coverage must meet or exceed baseline by at least min_coverage_gain.
    4. Request, runtime, and cost increases must remain within configured bounds.
    """
    crit = criteria or PromotionCriteria()
    deltas = compare_strategies(baseline, challenger)

    gate_checks: dict[str, bool] = {}

    # Gate 1: Absolute minimum precision
    gate_checks["min_precision"] = challenger.precision >= crit.min_precision

    # Gate 2: Precision preservation (no drop exceeding max_precision_drop)
    # E.g., if max_precision_drop=0.0, challenger.precision must be >= baseline.precision
    gate_checks["precision_preserved"] = deltas["precision_delta"] >= (-crit.max_precision_drop)

    # Gate 3: Coverage improvement or preservation
    gate_checks["coverage_improved"] = deltas["coverage_delta"] >= crit.min_coverage_gain

    # Gate 4: Request budget constraint
    gate_checks["requests_bounded"] = deltas["requests_ratio"] <= crit.max_request_increase_ratio

    # Gate 5: Runtime constraint
    gate_checks["runtime_bounded"] = deltas["runtime_ratio"] <= crit.max_runtime_increase_ratio

    # Gate 6: Cost constraint
    gate_checks["cost_bounded"] = deltas["cost_ratio"] <= crit.max_cost_increase_ratio

    all_passed = all(gate_checks.values())

    failed_reasons = []
    if not gate_checks["min_precision"]:
        failed_reasons.append(f"Precision {challenger.precision:.3f} below minimum {crit.min_precision:.3f}")
    if not gate_checks["precision_preserved"]:
        failed_reasons.append(f"Precision dropped by {-deltas['precision_delta']:.3f} (max drop allowed: {crit.max_precision_drop:.3f})")
    if not gate_checks["coverage_improved"]:
        failed_reasons.append(f"Coverage change {deltas['coverage_delta']:+.3f} below required gain {crit.min_coverage_gain:+.3f}")
    if not gate_checks["requests_bounded"]:
        failed_reasons.append(f"Request ratio {deltas['requests_ratio']:.2f}x exceeds limit {crit.max_request_increase_ratio:.2f}x")
    if not gate_checks["runtime_bounded"]:
        failed_reasons.append(f"Runtime ratio {deltas['runtime_ratio']:.2f}x exceeds limit {crit.max_runtime_increase_ratio:.2f}x")
    if not gate_checks["cost_bounded"]:
        failed_reasons.append(f"Cost ratio {deltas['cost_ratio']:.2f}x exceeds limit {crit.max_cost_increase_ratio:.2f}x")

    reason = "All precision-first promotion criteria satisfied" if all_passed else "; ".join(failed_reasons)

    return PromotionDecision(
        promoted=all_passed,
        reason=reason,
        baseline_metrics=baseline,
        challenger_metrics=challenger,
        gate_checks=gate_checks,
        comparison_deltas=deltas,
    )
