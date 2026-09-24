"""Tests for Stage 18 Performance Timing and Percentile Calculations."""

from __future__ import annotations

import time
import unittest

from norway_company_agent.evaluation.performance import (
    compute_runtime_statistics,
    measure_execution_ms,
)


class TestPerformanceEvaluation(unittest.TestCase):
    """Verify monotonic latency measurement and statistical distributions."""

    def test_measure_execution_ms(self):
        with measure_execution_ms() as m:
            time.sleep(0.01)  # 10ms
        self.assertGreater(m["elapsed_ms"], 5.0)

    def test_compute_runtime_statistics(self):
        # 10 synthetic latency measurements
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        stats = compute_runtime_statistics(latencies)

        self.assertEqual(stats["total_runtime_ms"], 550.0)
        self.assertEqual(stats["average_runtime_ms"], 55.0)
        self.assertEqual(stats["median_runtime_ms"], 55.0)
        self.assertEqual(stats["min_runtime_ms"], 10.0)
        self.assertEqual(stats["max_runtime_ms"], 100.0)
        self.assertGreaterEqual(stats["p95_runtime_ms"], 90.0)

    def test_empty_latencies_handles_safely(self):
        stats = compute_runtime_statistics([])
        self.assertEqual(stats["total_runtime_ms"], 0.0)
        self.assertEqual(stats["average_runtime_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
