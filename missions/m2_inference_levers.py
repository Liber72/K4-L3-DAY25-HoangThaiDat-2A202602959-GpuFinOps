"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Run: python missions/m2_inference_levers.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num
from finops import pricing, reasoning

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    base_cost = opt_cost = 0.0
    cascade_cost = cached_cost = 0.0
    legacy_cost = no_cache_batched_cost = write_cost = 0.0
    cache_groups = {tier: {"requests": 0, "reads_sum": 0.0, "used": 0, "skipped": 0,
                           "write_usd": 0.0} for tier in MODEL_PRICES}
    total_tokens = 0
    for r in rows:
        inp, out = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        total_tokens += inp + out
        # BASELINE: naive deployment — everything on the large model, no cache, no batch
        lin, lout = MODEL_PRICES["large"]
        base_cost += pricing.request_cost(inp, out, lin, lout)
        # OPTIMIZED: cascade (route_tier), prompt caching, batch API
        pin, pout = MODEL_PRICES[r["route_tier"]]
        cascade_cost += pricing.request_cost(inp, out, pin, pout)
        reads = num(r.get("avg_cache_reads", 1))
        cache = pricing.cache_plan(min(cached, inp), reads, pin, is_batch)
        cached_cost += pricing.request_cost(inp, out, pin, pout, cached_in=cache["cached_tokens"]) + cache["write_usd"]
        opt_cost += pricing.inference_request_cost(r, MODEL_PRICES)
        legacy_cost += pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        no_cache_batched_cost += pricing.request_cost(inp, out, pin, pout, batch=is_batch)
        write_cost += cache["write_usd"]
        group = cache_groups[r["route_tier"]]
        group["requests"] += 1
        group["reads_sum"] += reads
        group["used" if cache["allowed"] else "skipped"] += 1
        group["write_usd"] += cache["write_usd"]

    base_pm = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0
    budget = reasoning.analyze_reasoning_budget(rows, MODEL_PRICES)
    for tier, group in cache_groups.items():
        pin = MODEL_PRICES[tier][0]
        group["avg_cache_reads"] = group.pop("reads_sum") / group["requests"] if group["requests"] else 0
        group["write_per_m"] = pin * pricing.CACHE_WRITE_MULTIPLIER
        group["break_even_reads"] = pricing.cache_break_even_reads(group["write_per_m"], pin)
        group["batch_break_even_reads"] = pricing.cache_break_even_reads(group["write_per_m"], pin * 0.5)
    cache_economics = {
        "groups": cache_groups, "write_multiplier": pricing.CACHE_WRITE_MULTIPLIER,
        "write_daily_usd": write_cost, "legacy_free_write_daily_usd": legacy_cost,
        "no_cache_batched_daily_usd": no_cache_batched_cost,
        "net_cache_savings_daily_usd": no_cache_batched_cost - opt_cost,
        "used_requests": sum(group["used"] for group in cache_groups.values()),
        "skipped_requests": sum(group["skipped"] for group in cache_groups.values()),
        "prefix_count": len({r.get("cached_prefix_id", str(i)) for i, r in enumerate(rows)}),
        "metadata_source": "synthetic team/tier/12-request-window prefix groups, seed=25",
    }
    stages = [
        {"name": name, "daily_usd": cost,
         "per_m": pricing.dollars_per_million(cost, total_tokens)}
        for name, cost in (("Baseline", base_cost), ("Cascade", cascade_cost),
                           ("Cascade + cache", cached_cost), ("Cascade + cache + batch", opt_cost))
    ]

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={len(rows)}  tokens={total_tokens:,}")
        print(f"baseline  : ${base_cost:,.2f}/day   ${base_pm:.3f}/1M-token")
        print(f"optimized : ${opt_cost:,.2f}/day   ${opt_pm:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + caching + batch)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")
        print(f"cache gate: {cache_economics['used_requests']} used, {cache_economics['skipped_requests']} skipped; "
              f"amortized writes ${write_cost:.4f}/day; net cache saving ${cache_economics['net_cache_savings_daily_usd']:.4f}/day")
        group = budget["groups"]["reasoning"]
        print(f"reasoning: {group['requests']} requests ({group['traffic_pct']:.3f}% traffic), "
              f"{group['cost_pct']:.1f}% cost, {group['energy_pct']:.1f}% energy")
        for scenario in budget["scenarios"]:
            print(f"  cap {scenario['cap_fraction']:.0%}: {scenario['rerouted_requests']} rerouted, "
                  f"save ${scenario['savings_usd']:.4f}/day + {scenario['savings_wh']:.2f} Wh/day "
                  "(same-token simulation)")

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3), "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1), "total_tokens": total_tokens,
        "request_count": len(rows), "stages": stages, "reasoning_budget": budget,
        "cache_economics": cache_economics,
    }


if __name__ == "__main__":
    run()
