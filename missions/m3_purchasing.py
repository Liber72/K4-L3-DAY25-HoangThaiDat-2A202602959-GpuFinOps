"""M3 — Purchasing Strategy: break-even, tier choice, spot-checkpoint sim (deck §4).

Run: python missions/m3_purchasing.py
"""
from __future__ import annotations
import csv
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num, catalog_by_type, ROOT
from finops import pricing, sustainability

DAYS = 30


def _window_cost(tier: str, catalog: dict, hours_per_day: float, active_days: float,
                 num_gpus: int, interrupt_rate: float) -> float:
    if tier == "spot":
        return hours_per_day * active_days * num_gpus * num(catalog["spot_hr"]) * (1.03 + interrupt_rate * 0.5)
    if tier.startswith("reserved_"):
        # A reserved GPU is paid for every calendar hour, even during daily idle.
        return 24 * active_days * num_gpus * num(catalog[tier + "_hr"])
    return hours_per_day * active_days * num_gpus * num(catalog["on_demand_hr"])


def _policy_matrix(catalog: dict) -> list[dict]:
    rows = []
    for gtype, prices in catalog.items():
        for hours in (4, 16, 24):
            for interruptible in (False, True):
                for horizon in (30, 365, 1095):
                    plan = pricing.purchasing_plan(hours, interruptible, gtype, horizon, prices)
                    rows.append({"gpu_type": gtype, "hours_per_day": hours,
                                 "interruptible": int(interruptible), "horizon_days": horizon,
                                 "tier": plan["tier"], "cost_usd": round(plan["cost_usd"], 2),
                                 "on_demand_usd": round(plan["options_usd"]["on_demand"], 2),
                                 "interrupt_rate": plan["interrupt_rate"]})
    return rows


def _horizon_sensitivity(jobs: list[dict], catalog: dict) -> list[dict]:
    scenarios = []
    for recurring_days in (30, 365, 1095):
        cost = 0.0
        tiers = []
        for job in jobs:
            interruptible = bool(int(job["interruptible"]))
            horizon = recurring_days if job["kind"] == "infer" and not interruptible else num(job["days"])
            c = catalog[job["gpu_type"]]
            plan = pricing.purchasing_plan(num(job["hours_per_day"]), interruptible,
                                           job["gpu_type"], horizon, c)
            cost += _window_cost(plan["tier"], c, num(job["hours_per_day"]),
                                 min(num(job["days"]), DAYS), int(job["num_gpus"]), plan["interrupt_rate"])
            if job["kind"] == "infer" and not interruptible:
                tiers.append({"job_id": job["job_id"], "tier": plan["tier"]})
        scenarios.append({"recurring_inference_days": recurring_days,
                          "window_cost_usd": cost, "online_inference_tiers": tiers})
    return scenarios


def run(verbose: bool = True, recurring_inference_days: int = 1095) -> dict:
    jobs = load_csv("workloads.csv")
    cat = catalog_by_type()
    on_demand_monthly = optimized_monthly = legacy_monthly = legacy_prorated = 0.0
    recs = []
    for j in jobs:
        gtype = j["gpu_type"]
        ngpu = int(num(j["num_gpus"]))
        hpd = num(j["hours_per_day"])
        interruptible = bool(int(num(j["interruptible"])))
        c = cat[gtype]
        active_days = min(num(j["days"]), DAYS)
        # An explicit planning assumption for steady online inference, not an input fact.
        horizon = recurring_inference_days if j["kind"] == "infer" and not interruptible else num(j["days"])
        gpu_hours = hpd * active_days * ngpu
        od = num(c["on_demand_hr"])
        on_demand_cost = gpu_hours * od

        plan = pricing.purchasing_plan(hpd, interruptible, gtype, horizon, c)
        option = pricing.recommend_tier(hpd, interruptible, gpu_type=gtype, job_days=horizon, catalog=c)
        tier = "reserved" if option.startswith("reserved_") else option  # retain verify.py schema
        opt_cost = _window_cost(option, c, hpd, active_days, ngpu, plan["interrupt_rate"])
        old_tier = pricing.recommend_tier(hpd, interruptible)
        old_option = "reserved_3yr" if old_tier == "reserved" else old_tier
        old_cost = _window_cost(old_option, c, hpd, active_days, ngpu, 0.05)
        old_prorated_cost = (gpu_hours * num(c["reserved_3yr_hr"])) if old_tier == "reserved" else old_cost

        on_demand_monthly += on_demand_cost
        optimized_monthly += opt_cost
        legacy_monthly += old_cost
        legacy_prorated += old_prorated_cost
        recs.append({"job_id": j["job_id"], "gpu_type": gtype, "tier": tier,
                     "purchase_option": option, "actual_days": active_days,
                     "planning_horizon_days": horizon, "interrupt_rate": plan["interrupt_rate"],
                     "horizon_plan_cost_usd": plan["cost_usd"] * ngpu,
                     "on_demand": round(on_demand_cost), "optimized": round(opt_cost),
                     "on_demand_exact": on_demand_cost, "optimized_exact": opt_cost,
                     "legacy_option": old_option, "legacy_monthly_usd": old_cost,
                     "horizon_options_per_gpu_usd": plan["options_usd"]})

    savings = on_demand_monthly - optimized_monthly
    savings_pct = savings / on_demand_monthly * 100 if on_demand_monthly else 0.0
    carbon_schedule = sustainability.carbon_aware_schedule(jobs, cat, window_days=DAYS)
    matrix = _policy_matrix(cat)
    matrix_path = _os.path.join(ROOT, "outputs", "tier_policy_matrix.csv")
    _os.makedirs(_os.path.dirname(matrix_path), exist_ok=True)
    with open(matrix_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(matrix[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(matrix)
    comparison = {
        "baseline_window_usd": on_demand_monthly, "legacy_window_usd": legacy_monthly,
        "improved_window_usd": optimized_monthly,
        "legacy_savings_pct": 100 * (1 - legacy_monthly / on_demand_monthly) if on_demand_monthly else 0,
        "improved_savings_pct": savings_pct, "additional_savings_usd": legacy_monthly - optimized_monthly,
        "legacy_prorated_window_usd": legacy_prorated,
        "reserved_idle_cost_correction_usd": legacy_monthly - legacy_prorated,
    }

    if verbose:
        print("== M3 Purchasing Strategy ==")
        print(f"legacy break-even example @ 45% reserved discount = {pricing.break_even_utilization(0.45):.0%}; "
              "new policy compares full plan costs")
        print(f"{'job':18}{'gpu':7}{'tier':15}{'on-demand':>12}{'optimized':>12}")
        for r in recs:
            print(f"{r['job_id']:18}{r['gpu_type']:7}{r['purchase_option']:15}${r['on_demand']:>11,}${r['optimized']:>11,}")
        print(f"\nmonthly: on-demand ${on_demand_monthly:,.0f} -> optimized ${optimized_monthly:,.0f}  ({savings_pct:.1f}% saved)")
        print(f"policy comparison (same full-calendar RI billing): "
              f"{comparison['legacy_savings_pct']:.2f}% -> {savings_pct:.2f}%; "
              f"additional ${comparison['additional_savings_usd']:.2f}/window")
        print(f"  planning horizon for recurring inference: {recurring_inference_days} days (assumption)")
        print(f"  policy matrix -> outputs/tier_policy_matrix.csv ({len(matrix)} scenarios)")
        print(f"carbon scheduling: {len(carbon_schedule['jobs'])} interruptible jobs, "
              f"{carbon_schedule['energy_kwh']:,.2f} kWh over actual job days")
        print(f"  cleanest={carbon_schedule['cleanest_region']}, "
              f"cheapest={carbon_schedule['cheapest_region']}, balanced={carbon_schedule['balanced_region']}")
        print(f"  relocation to cleanest saves {carbon_schedule['carbon_saved_g']/1000:,.2f} kgCO2e "
              f"({carbon_schedule['carbon_savings_pct']:.1f}%)")

    return {"recommendations": recs, "on_demand_monthly": round(on_demand_monthly),
            "optimized_monthly": round(optimized_monthly), "savings_pct": round(savings_pct, 1),
            "on_demand_monthly_exact": on_demand_monthly,
            "optimized_monthly_exact": optimized_monthly, "carbon_schedule": carbon_schedule,
            "policy_comparison": comparison, "policy_matrix": matrix,
            "recurring_inference_days": recurring_inference_days,
            "interruption_rates": pricing.INTERRUPTION_RATES,
            "horizon_sensitivity": _horizon_sensitivity(jobs, cat)}


if __name__ == "__main__":
    run()
