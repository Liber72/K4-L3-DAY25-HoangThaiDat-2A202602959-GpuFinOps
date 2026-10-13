"""Pricing & purchasing economics — measure in $/1M-token, not $/GPU-hr.

Figures are June-2026 as-of snapshots from the deck's RESEARCH dossier; treat
live prices as fast-moving (re-baseline before each cohort).
"""
from __future__ import annotations
import math

# Scenario assumptions, not observed spot-market statistics.
INTERRUPTION_RATES = {"H100": 0.02, "H200": 0.02, "A100": 0.06,
                      "A10G": 0.12, "L4": 0.08, "B200": 0.03, "MI300X": 0.05}
CACHE_WRITE_MULTIPLIER = 1.25


def request_cost(
    input_tok: int,
    output_tok: int,
    price_in_per_m: float,
    price_out_per_m: float,
    cached_in: int = 0,
    cache_discount: float = 0.10,   # Anthropic cached-read ~0.1x (=-90%)
    batch: bool = False,
    batch_discount: float = 0.50,   # Batch API ~ -50%
) -> float:
    """USD cost of a single request. Cached input billed at cache_discount x price."""
    cached_in = min(max(0, cached_in), input_tok)
    uncached_in = input_tok - cached_in
    cost = (
        (uncached_in / 1e6) * price_in_per_m
        + (cached_in / 1e6) * price_in_per_m * cache_discount
        + (output_tok / 1e6) * price_out_per_m
    )
    if batch:
        cost *= batch_discount
    return cost


def dollars_per_million(total_cost_usd: float, total_tokens: int) -> float:
    """Aggregate unit economics: $ per 1,000,000 tokens served."""
    if total_tokens <= 0:
        return 0.0
    return total_cost_usd / (total_tokens / 1e6)


def discount_stack(
    batch: bool = False,
    cache_hit_frac: float = 0.0,
    batch_discount: float = 0.50,
    cache_discount: float = 0.10,
) -> float:
    """Effective fraction of the naive bill after stacking discounts (input-heavy view).

    Discounts MULTIPLY: cache applies to the cached share of input, batch to the
    whole bill. batch + 100% cache-hit -> 0.5 * 0.1 = 0.05 (~95% off).
    """
    cache_mult = cache_hit_frac * cache_discount + (1.0 - cache_hit_frac)
    batch_mult = batch_discount if batch else 1.0
    return cache_mult * batch_mult


def break_even_utilization(discount_frac: float) -> float:
    """Utilization at which a commitment pays off ~= 1 - discount.

    A 45% reserved discount needs ~55% utilization (~13.2h/day) to beat on-demand.
    """
    return max(0.0, min(1.0, 1.0 - discount_frac))


def recommend_tier(hours_per_day: float, interruptible: bool, reserved_discount: float = 0.45,
                   *, gpu_type: str | None = None, job_days: float | None = None,
                   catalog: dict | None = None) -> str:
    """Pick a purchasing tier from a workload's duty cycle + interruptibility.

    DOCUMENTED simple policy (instructor extension point — swap in your own):
      - interruptible & not 24/7  -> 'spot'      (checkpoint and ride the discount)
      - duty cycle >= break-even  -> 'reserved'  (steady, high utilization)
      - otherwise                 -> 'on_demand' (spiky / low duty)
    """
    # Preserve the original API for instructor tests. With a catalog and horizon,
    # choose the least expensive complete plan including commitment obligations.
    if catalog is not None:
        if job_days is None or gpu_type is None:
            raise ValueError("Catalog-based policy requires gpu_type and job_days")
        return purchasing_plan(hours_per_day, interruptible, gpu_type, job_days, catalog)["tier"]
    duty = max(0.0, hours_per_day) / 24.0
    be = break_even_utilization(reserved_discount)
    if interruptible and hours_per_day < 24:
        return "spot"
    if duty >= be:
        return "reserved"
    return "on_demand"


def purchasing_plan(hours_per_day: float, interruptible: bool, gpu_type: str,
                    job_days: float, catalog: dict, interrupt_rate: float | None = None) -> dict:
    """One-GPU costs over a known demand horizon, including full RI terms.

    Reserved is charged 24h/day for entire 365/1095-day terms, including renewals.
    Spot includes checkpoint overhead (3%) and expected lost work (0.5h/event).
    No resale, sharing idle reserved capacity, or mixed renewal plans is assumed.
    """
    if not math.isfinite(hours_per_day) or not 0 <= hours_per_day <= 24:
        raise ValueError("hours_per_day must be finite and between 0 and 24")
    if not math.isfinite(job_days) or job_days < 0:
        raise ValueError("job_days must be finite and nonnegative")
    prices = {name: float(catalog[name]) for name in
              ("on_demand_hr", "spot_hr", "reserved_1yr_hr", "reserved_3yr_hr")}
    if any(not math.isfinite(price) or price < 0 for price in prices.values()):
        raise ValueError("Prices must be finite and nonnegative")
    rate = INTERRUPTION_RATES.get(gpu_type, 0.05) if interrupt_rate is None else interrupt_rate
    if not math.isfinite(rate) or not 0 <= rate <= 1:
        raise ValueError("interrupt_rate must be finite and between 0 and 1")
    used_hours = hours_per_day * job_days
    options = {"on_demand": used_hours * prices["on_demand_hr"]}
    if used_hours > 0:
        if interruptible:
            options["spot"] = used_hours * prices["spot_hr"] * (1.03 + rate * 0.5)
        for tier, term in (("reserved_1yr", 365), ("reserved_3yr", 1095)):
            committed_days = math.ceil(job_days / term) * term
            options[tier] = committed_days * 24 * prices[tier + "_hr"]
    tier = min(options, key=options.get)
    return {"tier": tier, "cost_usd": options[tier], "options_usd": options,
            "job_days": job_days, "gpu_type": gpu_type, "interrupt_rate": rate,
            "spot_overhead_multiplier": 1.03 + rate * 0.5}


def cache_break_even_reads(write_cost_per_m: float, price_in_per_m: float = 1.0,
                           read_discount: float = 0.10) -> float:
    """Reads needed to recover one cache write, in USD / 1M prefix tokens.

    price_in_per_m is the normal input rate after any batch discount; cache
    writes are billed separately and do not receive a batch discount.
    """
    if any(not math.isfinite(value) or value < 0
           for value in (write_cost_per_m, price_in_per_m)):
        raise ValueError("Cache prices must be finite and nonnegative")
    if not math.isfinite(read_discount) or not 0 <= read_discount <= 1:
        raise ValueError("read_discount must be finite and between 0 and 1")
    saving_per_read = price_in_per_m * (1 - read_discount)
    return write_cost_per_m / saving_per_read if saving_per_read > 0 else math.inf


def cache_is_worth_it(avg_reads: float, write_cost: float, read_discount: float = 0.10,
                      *, price_in_per_m: float = 1.0) -> bool:
    """True only when read savings strictly exceed the full cache write cost.

    write_cost and price_in_per_m have matching USD/1M-token units. The default
    input rate 1.0 also supports a write cost expressed as a relative multiplier.
    """
    if not math.isfinite(avg_reads) or avg_reads < 0:
        raise ValueError("avg_reads must be finite and nonnegative")
    return avg_reads > cache_break_even_reads(write_cost, price_in_per_m, read_discount)


def cache_plan(cached_tokens: int, avg_reads: float, price_in_per_m: float,
               batch: bool = False, write_multiplier: float = CACHE_WRITE_MULTIPLIER) -> dict:
    """Amortize one modeled prefix write over its reads; gate with batch economics."""
    batch_mult = 0.5 if batch else 1.0
    write_per_m = price_in_per_m * write_multiplier
    allowed = cached_tokens > 0 and cache_is_worth_it(
        avg_reads, write_per_m, price_in_per_m=price_in_per_m * batch_mult,
    )
    return {"allowed": allowed, "cached_tokens": cached_tokens if allowed else 0,
            "write_usd": cached_tokens / 1e6 * write_per_m / avg_reads if allowed else 0.0,
            "break_even_reads": cache_break_even_reads(write_per_m, price_in_per_m * batch_mult)}


def inference_request_cost(row: dict, model_prices: dict, tier: str | None = None) -> float:
    """Shared M2/M4/reasoning billing, with cache gating and amortized writes."""
    pin, pout = model_prices[tier or row["route_tier"]]
    inp, out = int(row["input_tokens"]), int(row["output_tokens"])
    cached = min(max(0, int(row["cached_input_tokens"])), inp)
    batch = bool(int(row["is_batch"]))
    cache = cache_plan(cached, float(row.get("avg_cache_reads", 1)), pin, batch)
    return request_cost(inp, out, pin, pout, cached_in=cache["cached_tokens"], batch=batch) + cache["write_usd"]


def spot_checkpoint_cost(
    job_hours: float,
    spot_hr: float,
    on_demand_hr: float,
    interrupt_rate: float = 0.05,      # per-hour chance (H100 spot ~<5%)
    ckpt_overhead_frac: float = 0.03,  # steady cost of writing checkpoints
    rework_hours_per_interrupt: float = 0.5,
) -> dict:
    """Effective cost of running a checkpointable job on spot vs on-demand.

    Interruptions waste the compute since the last checkpoint (rework); checkpointing
    adds a small steady overhead. Spot still wins for interruptible jobs.
    """
    expected_interrupts = job_hours * interrupt_rate
    rework_hours = expected_interrupts * rework_hours_per_interrupt
    effective_hours = job_hours * (1.0 + ckpt_overhead_frac) + rework_hours
    spot_cost = effective_hours * spot_hr
    on_demand_cost = job_hours * on_demand_hr
    savings_pct = (1.0 - spot_cost / on_demand_cost) * 100.0 if on_demand_cost > 0 else 0.0
    return {
        "spot_effective_hours": round(effective_hours, 2),
        "spot_cost": round(spot_cost, 2),
        "on_demand_cost": round(on_demand_cost, 2),
        "savings_pct": round(savings_pct, 1),
    }
