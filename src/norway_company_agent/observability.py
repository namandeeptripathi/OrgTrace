"""Stage 11: Production Observability & Lightweight Metrics.

Provides thread-safe internal observability and telemetry:
- Operation counters and latency tracking
- Success, failure, and retry rates
- Error category distribution
- Refresh outcome tracking
- Metrics snapshot API for health checks and status reporting
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionMetricsCollector:
    """Thread-safe in-memory observability metrics collector."""

    _instance: ProductionMetricsCollector | None = None
    _lock = threading.Lock()

    def __init__(self):
        self._mutex = threading.Lock()
        self._start_time: float = time.monotonic()
        self._start_iso: str = _utc_now_iso()
        self._operation_counts: dict[str, int] = {}
        self._operation_durations: dict[str, float] = {}
        self._status_counts: dict[str, int] = {"success": 0, "failure": 0}
        self._error_categories: dict[str, int] = {}
        self._request_counts: dict[str, int] = {"total": 0, "failed": 0, "retries": 0, "duplicates": 0}
        self._refresh_outcomes: dict[str, int] = {}

    @classmethod
    def get_instance(cls) -> ProductionMetricsCollector:
        """Singleton accessor for global telemetry."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def record_operation(
        self,
        engine: str,
        operation: str,
        duration_seconds: float,
        status: str = "success",
        error_category: str | None = None,
    ) -> None:
        """Record an operation execution with timing and status."""
        key = f"{engine}:{operation}"
        with self._mutex:
            self._operation_counts[key] = self._operation_counts.get(key, 0) + 1
            self._operation_durations[key] = self._operation_durations.get(key, 0.0) + max(0.0, duration_seconds)

            if status in ("success", "complete", "verified", "usable"):
                self._status_counts["success"] = self._status_counts.get("success", 0) + 1
            else:
                self._status_counts["failure"] = self._status_counts.get("failure", 0) + 1

            if error_category:
                self._error_categories[error_category] = self._error_categories.get(error_category, 0) + 1

    def record_request(
        self,
        engine: str,
        status_code: int = 200,
        is_retry: bool = False,
        is_failed: bool = False,
        is_duplicate: bool = False,
    ) -> None:
        """Record network request telemetry."""
        with self._mutex:
            self._request_counts["total"] = self._request_counts.get("total", 0) + 1
            if is_failed or status_code >= 400:
                self._request_counts["failed"] = self._request_counts.get("failed", 0) + 1
            if is_retry:
                self._request_counts["retries"] = self._request_counts.get("retries", 0) + 1
            if is_duplicate:
                self._request_counts["duplicates"] = self._request_counts.get("duplicates", 0) + 1

    def record_refresh_outcome(self, outcome: str) -> None:
        """Record outcomes of snapshot refresh operations."""
        with self._mutex:
            self._refresh_outcomes[outcome] = self._refresh_outcomes.get(outcome, 0) + 1

    def get_metrics_snapshot(self) -> dict[str, Any]:
        """Export an immutable telemetry snapshot."""
        with self._mutex:
            uptime = time.monotonic() - self._start_time
            total_ops = sum(self._operation_counts.values())
            success_count = self._status_counts.get("success", 0)
            failure_count = self._status_counts.get("failure", 0)
            success_rate = (success_count / (success_count + failure_count)) if (success_count + failure_count) > 0 else 1.0

            return {
                "started_at": self._start_iso,
                "uptime_seconds": round(uptime, 3),
                "total_operations": total_ops,
                "success_rate": round(success_rate, 4),
                "status_counts": dict(self._status_counts),
                "operations": dict(self._operation_counts),
                "durations_seconds": {k: round(v, 4) for k, v in self._operation_durations.items()},
                "requests": dict(self._request_counts),
                "error_categories": dict(self._error_categories),
                "refresh_outcomes": dict(self._refresh_outcomes),
            }

    def reset(self) -> None:
        """Reset all metrics to initial state."""
        with self._mutex:
            self._start_time = time.monotonic()
            self._start_iso = _utc_now_iso()
            self._operation_counts.clear()
            self._operation_durations.clear()
            self._status_counts = {"success": 0, "failure": 0}
            self._error_categories.clear()
            self._request_counts = {"total": 0, "failed": 0, "retries": 0, "duplicates": 0}
            self._refresh_outcomes.clear()
