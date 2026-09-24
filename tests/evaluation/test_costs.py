"""Tests for Stage 18 API & LLM Cost Accounting."""

from __future__ import annotations

import unittest

from norway_company_agent.evaluation.costs import (
    TokenPricingConfig,
    evaluate_company_cost,
)


class TestCostEvaluation(unittest.TestCase):
    """Verify token usage, pricing models, and unavailable state handling."""

    def test_cost_unavailable_when_no_llm_calls(self):
        res = evaluate_company_cost(llm_calls=0, input_tokens=0, output_tokens=0, is_available=False)
        self.assertEqual(res.status, "unavailable")
        self.assertIsNone(res.estimated_cost_usd)
        self.assertEqual(res.total_tokens, 0)

    def test_cost_calculation_with_custom_pricing(self):
        pricing = TokenPricingConfig(input_price_per_1k=0.002, output_price_per_1k=0.004)
        res = evaluate_company_cost(
            llm_calls=2,
            input_tokens=1000,
            output_tokens=500,
            pricing=pricing,
            is_available=True,
        )
        self.assertEqual(res.status, "available")
        self.assertEqual(res.total_tokens, 1500)
        # Expected cost: (1000/1000 * 0.002) + (500/1000 * 0.004) = 0.002 + 0.002 = 0.004
        self.assertAlmostEqual(res.estimated_cost_usd, 0.004, places=5)


if __name__ == "__main__":
    unittest.main()
