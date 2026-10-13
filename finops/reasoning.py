"""Reasoning traffic accounting and explicit, same-token routing scenarios.

No hidden reasoning-token prices or quality scores are present in the lab data.
USD uses the existing model prices; the 80x multiplier applies only to energy.
"""
from __future__ import annotations

import math
from finops import pricing, sustainability


def _cost(row: dict, model_prices: dict, tier: str | None = None) -> float:
    return pricing.inference_request_cost(row, model_prices, tier)


def analyze_reasoning_budget(rows: list[dict], model_prices: dict,
                             caps: tuple[float, ...] = (0.10, 0.05)) -> dict:
    """Compare current traffic with caps on reasoning requests / all requests.

    Retain the longest existing reasoning requests first (input + output tokens,
    source-row order as tie-breaker). This is a reproducible scenario proxy, not
    a measured complexity/quality rule. Requests beyond the cap use the small
    model without reasoning, with tokens, caching and batching held constant.
    Caps never promote an existing small-model request to a large model.
    """
    if any(not math.isfinite(cap) or not 0 <= cap <= 1 for cap in caps):
        raise ValueError("Reasoning caps must be finite fractions between 0 and 1")

    groups = {
        name: {"requests": 0, "tokens": 0, "cost_usd": 0.0, "energy_wh": 0.0}
        for name in ("reasoning", "standard")
    }
    reasoning_indices = []
    small_equivalent_usd = standard_equivalent_wh = 0.0
    for index, row in enumerate(rows):
        is_reasoning = bool(int(row["is_reasoning"]))
        tokens = int(row["input_tokens"]) + int(row["output_tokens"])
        group = groups["reasoning" if is_reasoning else "standard"]
        group["requests"] += 1
        group["tokens"] += tokens
        group["cost_usd"] += _cost(row, model_prices)
        group["energy_wh"] += sustainability.wh_per_query(tokens, is_reasoning=is_reasoning)
        if is_reasoning:
            reasoning_indices.append(index)
            small_equivalent_usd += _cost(row, model_prices, "small")
            standard_equivalent_wh += sustainability.wh_per_query(tokens)

    total_cost = sum(group["cost_usd"] for group in groups.values())
    total_wh = sum(group["energy_wh"] for group in groups.values())
    for group in groups.values():
        group["traffic_pct"] = 100 * group["requests"] / len(rows) if rows else 0.0
        group["cost_pct"] = 100 * group["cost_usd"] / total_cost if total_cost else 0.0
        group["energy_pct"] = 100 * group["energy_wh"] / total_wh if total_wh else 0.0

    ranked = sorted(reasoning_indices, key=lambda index: (
        -(int(rows[index]["input_tokens"]) + int(rows[index]["output_tokens"])), index,
    ))
    scenarios = []
    for cap in caps:
        kept = set(ranked[:math.floor(len(rows) * cap)])
        rerouted = []
        for index, row in enumerate(rows):
            was_reasoning = bool(int(row["is_reasoning"]))
            removed = was_reasoning and index not in kept
            if removed:
                rerouted.append(index + 1)  # 1-based data row, excluding CSV header
        # Calculate deltas only for changed rows; a no-op cap saves exactly zero.
        changed_rows = [rows[index - 1] for index in rerouted]
        saved_usd = math.fsum(_cost(row, model_prices) - _cost(row, model_prices, "small")
                              for row in changed_rows)
        saved_wh = math.fsum(
            sustainability.wh_per_query(int(row["input_tokens"]) + int(row["output_tokens"]),
                                        is_reasoning=True)
            - sustainability.wh_per_query(int(row["input_tokens"]) + int(row["output_tokens"]))
            for row in changed_rows
        )
        scenarios.append({
            "cap_fraction": cap, "retained_requests": len(kept),
            "rerouted_requests": len(rerouted), "rerouted_data_rows": rerouted,
            "traffic_pct": 100 * len(kept) / len(rows) if rows else 0.0,
            "cost_usd": total_cost - saved_usd, "energy_wh": total_wh - saved_wh,
            "savings_usd": saved_usd, "savings_wh": saved_wh,
            "cost_savings_pct": 100 * saved_usd / total_cost if total_cost else 0.0,
            "energy_savings_pct": 100 * saved_wh / total_wh if total_wh else 0.0,
        })

    return {
        "groups": groups, "total_requests": len(rows),
        "total_cost_usd": total_cost, "total_energy_wh": total_wh,
        "same_token_small_cost_usd": small_equivalent_usd,
        "same_token_standard_energy_wh": standard_equivalent_wh,
        "reasoning_extra_usd": groups["reasoning"]["cost_usd"] - small_equivalent_usd,
        "reasoning_extra_wh": groups["reasoning"]["energy_wh"] - standard_equivalent_wh,
        "scenarios": scenarios,
    }
