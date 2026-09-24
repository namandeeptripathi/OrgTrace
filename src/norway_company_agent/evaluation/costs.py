"""Stage 18: API & LLM Cost Accounting Module.

Tracks token consumption and API costs using configurable pricing models.
Explicitly emits status: unavailable when LLM usage is not present or untracked.
Never fabricates API costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CostEvaluation


@dataclass
class TokenPricingConfig:
    """Configurable pricing model per 1,000 tokens."""
    input_price_per_1k: float = 0.0015   # $0.0015 per 1K input tokens
    output_price_per_1k: float = 0.0020  # $0.0020 per 1K output tokens


def evaluate_company_cost(
    llm_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    pricing: TokenPricingConfig | None = None,
    is_available: bool = False,
) -> CostEvaluation:
    """Evaluate token usage and compute estimated cost if tracked."""
    if not is_available and llm_calls == 0 and input_tokens == 0 and output_tokens == 0:
        return CostEvaluation(
            status="unavailable",
            llm_calls=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost_usd=None,
        )

    cfg = pricing or TokenPricingConfig()
    total_tokens = input_tokens + output_tokens
    cost = (input_tokens / 1000.0 * cfg.input_price_per_1k) + (output_tokens / 1000.0 * cfg.output_price_per_1k)

    return CostEvaluation(
        status="available",
        llm_calls=llm_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(cost, 6),
    )
