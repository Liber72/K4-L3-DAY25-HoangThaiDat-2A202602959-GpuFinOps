"""Bandwidth-aware inference right-sizing constrained by observed peak VRAM."""
from __future__ import annotations

import math


def analyze_rightsizing(summary: list[dict], telemetry: list[dict], catalog: dict,
                        mbu_target: float = 0.70, memory_headroom: float = 0.10,
                        days: float = 30) -> dict:
    """Propose cheaper GPUs for infer/embed workloads with MBU below target.

    Low MBU alone does not establish memory-bound execution. We use the known
    workload kind as an inference/decode scenario and require profiling before
    migration. Peak observed memory + headroom and peak observed bandwidth must
    fit; compute throughput, kernels and latency are not verified by this model.
    """
    if not math.isfinite(mbu_target) or not 0 < mbu_target <= 1:
        raise ValueError("mbu_target must be a finite fraction in (0, 1]")
    if any(not math.isfinite(value) or value < 0 for value in (memory_headroom, days)):
        raise ValueError("Headroom and days must be finite and nonnegative")
    peaks = {}
    for row in telemetry:
        peak = peaks.setdefault(row["gpu_id"], {"workload": row["workload"], "memory_gb": 0.0, "bw_tbs": 0.0})
        peak["memory_gb"] = max(peak["memory_gb"], float(row["mem_used_gb"]))
        peak["bw_tbs"] = max(peak["bw_tbs"], float(row["achieved_bw_tbs"]))
    catalog_metrics = [
        {"gpu_type": name, "hbm_gb": float(row["hbm_gb"]), "peak_bw_tbs": float(row["peak_bw_tbs"]),
         "on_demand_hr": float(row["on_demand_hr"]),
         "usd_per_gb_hr": float(row["on_demand_hr"]) / float(row["hbm_gb"])}
        for name, row in catalog.items()
    ]
    recommendations = []
    for gpu in summary:
        peak = peaks[gpu["gpu_id"]]
        if peak["workload"] not in ("infer", "embed") or gpu["mbu"] >= mbu_target:
            continue
        current = catalog[gpu["gpu_type"]]
        required_gb = peak["memory_gb"] * (1 + memory_headroom)
        required_bw = peak["bw_tbs"] / mbu_target
        cheaper = [candidate for candidate in catalog_metrics
                   if candidate["on_demand_hr"] < float(current["on_demand_hr"])]
        feasible = [candidate for candidate in cheaper
                    if candidate["hbm_gb"] >= required_gb and candidate["peak_bw_tbs"] >= required_bw]
        chosen = min(feasible, key=lambda candidate: (candidate["on_demand_hr"], candidate["usd_per_gb_hr"])) if feasible else None
        monthly_hours = max(0.0, 24 - gpu["idle_hours"]) * days
        old_cost = monthly_hours * float(current["on_demand_hr"])
        new_cost = monthly_hours * chosen["on_demand_hr"] if chosen else old_cost
        recommendations.append({
            "gpu_id": gpu["gpu_id"], "current_gpu": gpu["gpu_type"],
            "proposed_gpu": chosen["gpu_type"] if chosen else gpu["gpu_type"],
            "changed": chosen is not None, "mbu": gpu["mbu"],
            "required_memory_gb": required_gb, "required_peak_bw_tbs": required_bw,
            "current_peak_bw_tbs": float(current["peak_bw_tbs"]),
            "target_peak_bw_tbs": chosen["peak_bw_tbs"] if chosen else float(current["peak_bw_tbs"]),
            "current_usd_per_gb_hr": float(current["on_demand_hr"]) / float(current["hbm_gb"]),
            "target_usd_per_gb_hr": chosen["usd_per_gb_hr"] if chosen else float(current["on_demand_hr"]) / float(current["hbm_gb"]),
            "baseline_monthly": old_cost, "optimized_monthly": new_cost,
            "savings_monthly": old_cost - new_cost,
            "savings_pct": (1 - new_cost / old_cost) * 100 if old_cost else 0,
            "reason": "Cheaper GPU fits peak memory + headroom and target MBU bandwidth"
                      if chosen else "No cheaper GPU meets both memory and bandwidth constraints",
        })
    baseline = sum(row["baseline_monthly"] for row in recommendations)
    optimized = sum(row["optimized_monthly"] for row in recommendations)
    return {"catalog": catalog_metrics, "recommendations": recommendations,
            "mbu_target": mbu_target, "memory_headroom": memory_headroom, "days": days,
            "baseline_monthly": baseline, "optimized_monthly": optimized,
            "savings_monthly": baseline - optimized,
            "savings_pct": (1 - optimized / baseline) * 100 if baseline else 0}
