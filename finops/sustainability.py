"""Sustainability economics — energy and carbon as governed cost levers (deck §11).

Region selection cuts $ and carbon together; reasoning queries are an energy bomb.
"""
from __future__ import annotations
import math

# Grid carbon intensity (gCO2 / kWh) — illustrative 2026 snapshot.
REGION_CARBON = {
    "us-east-1": 380,
    "us-west-2": 120,   # Oregon hydro
    "europe-north1": 30,  # Norway
    "europe-central2": 660,  # Poland (dirtiest)
    "us-east-wa": 90,
}
# Electricity price (USD / kWh) — illustrative.
REGION_PRICE_KWH = {
    "us-east-1": 0.12,
    "us-west-2": 0.07,
    "europe-north1": 0.09,
    "europe-central2": 0.18,
    "us-east-wa": 0.055,
}

REASONING_ENERGY_MULTIPLIER = 80.0  # deck: reasoning ~74-86x a small-model query


def wh_per_query(total_tokens: int, wh_per_1k_tokens: float = 0.30, is_reasoning: bool = False) -> float:
    """Energy for one query. Median Gemini prompt ~0.24 Wh; reasoning ~74-86x."""
    base = (total_tokens / 1000.0) * wh_per_1k_tokens
    return base * (REASONING_ENERGY_MULTIPLIER if is_reasoning else 1.0)


def carbon_g(wh: float, region: str = "us-east-1") -> float:
    """Grams CO2 for an energy amount in a region."""
    gco2_kwh = REGION_CARBON.get(region, 400)
    return (wh / 1000.0) * gco2_kwh


def energy_cost_usd(wh: float, region: str = "us-east-1") -> float:
    """Electricity cost of an energy amount in a region."""
    return (wh / 1000.0) * REGION_PRICE_KWH.get(region, 0.12)


def tokens_per_watt(total_tokens: int, wh: float, seconds: float = 1.0) -> float:
    """Energy efficiency of serving: tokens per watt (higher is better)."""
    watts = (wh * 3600.0) / seconds if seconds > 0 else 0.0
    return total_tokens / watts if watts > 0 else 0.0


def carbon_aware_schedule(workloads: list[dict], catalog: dict, window_days: float = 30,
                          baseline_region: str = "us-east-1",
                          carbon_weight: float = 0.5) -> dict:
    """Compare relocating interruptible jobs over their actual job duration.

    Energy = catalog watts * GPUs * hours/day * min(job days, window days).
    Uses nameplate GPU power, excluding host/PUE, transfers and spot rework.
    Electricity is an indicative component, not an additional cloud bill saving.
    Balanced score weights electricity and carbon relative to the baseline.
    """
    if not math.isfinite(window_days) or window_days < 0:
        raise ValueError("window_days must be finite and nonnegative")
    if not math.isfinite(carbon_weight) or not 0 <= carbon_weight <= 1:
        raise ValueError("carbon_weight must be a finite fraction between 0 and 1")
    if baseline_region not in REGION_CARBON or baseline_region not in REGION_PRICE_KWH:
        raise ValueError("Unknown baseline region")
    cleanest = min(REGION_CARBON, key=REGION_CARBON.get)
    cheapest = min(REGION_PRICE_KWH, key=REGION_PRICE_KWH.get)
    jobs = []
    for job in workloads:
        if not bool(int(job["interruptible"])):
            continue
        days = min(max(0.0, float(job["days"])), window_days)
        gpu_hours = max(0.0, float(job["hours_per_day"])) * days * max(0, int(job["num_gpus"]))
        wh = gpu_hours * float(catalog[job["gpu_type"]]["watts"])
        baseline_carbon = carbon_g(wh, baseline_region)
        target_carbon = carbon_g(wh, cleanest)
        jobs.append({
            "job_id": job["job_id"], "kind": job["kind"], "gpu_type": job["gpu_type"],
            "days": days, "gpu_hours": gpu_hours, "energy_kwh": wh / 1000,
            "baseline_carbon_g": baseline_carbon, "target_carbon_g": target_carbon,
            "carbon_saved_g": baseline_carbon - target_carbon,
        })
    total_wh = sum(job["energy_kwh"] for job in jobs) * 1000
    base_usd = energy_cost_usd(total_wh, baseline_region)
    base_carbon = carbon_g(total_wh, baseline_region)
    regions = []
    for region, intensity in REGION_CARBON.items():
        # Ratios of rates keep region selection meaningful even for an empty workload.
        score = ((1 - carbon_weight) * REGION_PRICE_KWH[region] / REGION_PRICE_KWH[baseline_region]
                 + carbon_weight * intensity / REGION_CARBON[baseline_region])
        cost = energy_cost_usd(total_wh, region)
        carbon = carbon_g(total_wh, region)
        regions.append({
            "region": region, "price_kwh": REGION_PRICE_KWH[region],
            "carbon_g_per_kwh": intensity, "electricity_usd": cost,
            "carbon_g": carbon, "electricity_saved_usd": base_usd - cost,
            "carbon_saved_g": base_carbon - carbon, "balanced_score": score,
        })
    target = next(row for row in regions if row["region"] == cleanest)
    return {
        "baseline_region": baseline_region, "window_days": window_days,
        "jobs": jobs, "energy_kwh": total_wh / 1000, "regions": regions,
        "cheapest_region": cheapest, "cleanest_region": cleanest,
        "balanced_region": min(regions, key=lambda row: row["balanced_score"])["region"],
        "carbon_weight": carbon_weight,
        "baseline_carbon_g": base_carbon, "target_carbon_g": target["carbon_g"],
        "carbon_saved_g": target["carbon_saved_g"],
        "carbon_savings_pct": 100 * target["carbon_saved_g"] / base_carbon if base_carbon else 0.0,
        "electricity_saved_usd": target["electricity_saved_usd"],
    }
