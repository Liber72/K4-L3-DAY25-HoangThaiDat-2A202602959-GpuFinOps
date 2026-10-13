"""M5 — Optimization Report: combine M1-M4 into baseline-vs-optimized (deck §1/§11).

Run: python missions/m5_report.py   ->  outputs/report.md + outputs/savings.png
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import json
import os
from missions._common import ROOT
from finops import report, sustainability
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation

DAYS = 30


def run(verbose: bool = True) -> dict:
    r1 = m1_efficiency_audit.run(verbose=False)
    r2 = m2_inference_levers.run(verbose=False)
    r3 = m3_purchasing.run(verbose=False)
    r4 = m4_allocation.run(verbose=False)

    # --- buckets ---
    infer_baseline = r2["stages"][0]["daily_usd"] * DAYS
    infer_optimized = r2["stages"][-1]["daily_usd"] * DAYS
    infer_savings = infer_baseline - infer_optimized
    purchasing_savings = r3["on_demand_monthly_exact"] - r3["optimized_monthly_exact"]

    idle_savings = r1["idle_waste_daily"] * DAYS
    rightsize_savings = r1["rightsizing"]["savings_monthly"]

    levers = {
        "Inference (cascade/cache/batch)": round(infer_savings),
        "Purchasing (spot/reserved)": round(purchasing_savings),
        "Right-size MBU candidates": round(rightsize_savings),
        "Kill idle GPUs": round(idle_savings),
    }
    baseline = infer_baseline + r3["on_demand_monthly_exact"]
    optimized = baseline - sum(levers.values())
    total_pct = sum(levers.values()) / baseline * 100 if baseline else 0.0

    # --- sustainability snapshot ---
    budget = r2["reasoning_budget"]
    wh = budget["total_energy_wh"] / r2["request_count"] if r2["request_count"] else 0.0
    sust = {
        "wh_per_query": wh,
        "carbon_g": sustainability.carbon_g(wh, "us-east-1"),
        "best_region": min(sustainability.REGION_CARBON, key=sustainability.REGION_CARBON.get),
        "cheapest_region": min(sustainability.REGION_PRICE_KWH, key=sustainability.REGION_PRICE_KWH.get),
    }

    analysis = {
        "period_days": DAYS, "audit": r1, "inference": r2, "purchasing": r3, "allocation": r4,
        "baseline_monthly_exact": baseline, "optimized_monthly_exact": optimized,
        "levers": levers, "total_savings_pct": total_pct, "sustainability": sust,
    }
    md = report.build_report(baseline, optimized, levers, sustainability=sust, analysis=analysis)
    out_md = os.path.join(ROOT, "outputs", "report.md")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(ROOT, "outputs", "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    drafts = {
        "writeup_suggested.md": report.build_writeup(analysis, baseline, optimized, levers),
        "report_completion_guide.md": report.build_completion_guide(),
    }
    for filename, content in drafts.items():
        with open(os.path.join(ROOT, "outputs", filename), "w", encoding="utf-8") as f:
            f.write(content)
    png = report.savings_waterfall(levers, os.path.join(ROOT, "outputs", "savings.png"), baseline)

    if verbose:
        print("== M5 Optimization Report ==")
        print(md)
        print("\nWritten: outputs/report.md, analysis.json, writeup_suggested.md, report_completion_guide.md"
              + (" + savings.png" if png else " (matplotlib absent: PNG skipped)"))

    return {"baseline_monthly": round(baseline), "optimized_monthly": round(optimized),
            "levers": levers, "total_savings_pct": round(total_pct, 1), "analysis": analysis}


if __name__ == "__main__":
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(encoding="utf-8")
    run()
