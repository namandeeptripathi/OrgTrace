"""Stage 18: Monotonic Performance & Latency Evaluation.

Measures high-precision execution timing for individual companies and batches:
- total_runtime_ms
- average_runtime_ms
- median_runtime_ms
- p95_runtime_ms
- min_runtime_ms
- max_runtime_ms
Uses time.perf_counter() monotonic clocks and excludes report generation.
"""

from __future__ import annotations

import contextlib
import math
import time
from typing import Generator, Sequence


@contextlib.contextmanager
def measure_execution_ms() -> Generator[dict[str, float], None, None]:
    """Context manager measuring execution duration in milliseconds using monotonic clock."""
    result: dict[str, float] = {"elapsed_ms": 0.0}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["elapsed_ms"] = (time.perf_counter() - start) * 1000.0


def compute_runtime_statistics(latencies_ms: Sequence[float]) -> dict[str, float]:
    """Compute comprehensive latency distribution percentiles in milliseconds."""
    if not latencies_ms:
        return {
            "total_runtime_ms": 0.0,
            "average_runtime_ms": 0.0,
            "median_runtime_ms": 0.0,
            "p95_runtime_ms": 0.0,
            "min_runtime_ms": 0.0,
            "max_runtime_ms": 0.0,
        }

    sorted_vals = sorted(latencies_ms)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    avg = total / n

    # Median (50th percentile)
    if n % 2 == 1:
        median = sorted_vals[n // 2]
    else:
        median = (sorted_vals[(n // 2) - 1] + sorted_vals[n // 2]) / 2.0

    # 95th percentile
    idx_p95 = math.ceil(0.95 * n) - 1
    idx_p95 = max(0, min(idx_p95, n - 1))
    p95 = sorted_vals[idx_p95]

    return {
        "total_runtime_ms": round(total, 2),
        "average_runtime_ms": round(avg, 2),
        "median_runtime_ms": round(median, 2),
        "p95_runtime_ms": round(p95, 2),
        "min_runtime_ms": round(sorted_vals[0], 2),
        "max_runtime_ms": round(sorted_vals[-1], 2),
    }
