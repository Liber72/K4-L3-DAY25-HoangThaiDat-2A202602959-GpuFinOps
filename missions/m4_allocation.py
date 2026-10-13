"""M4 — Cost Allocation: tag -> showback -> chargeback + FOCUS export (deck §10).

Run: python missions/m4_allocation.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import csv
import os
from missions._common import load_csv, ROOT
from finops import allocation
from missions.m2_inference_levers import MODEL_PRICES
from finops import pricing

TAGS = ["team", "project"]


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    priced = []
    for r in rows:
        cost = pricing.inference_request_cost(r, MODEL_PRICES)
        priced.append({"team": r["team"], "project": r["project"],
                       "service": "gpu-inference", "cost": cost})

    by_team = allocation.cost_by_tag(priced, "team")
    by_project = allocation.cost_by_tag(priced, "project")
    coverage = allocation.tag_coverage(priced, TAGS)
    ready = allocation.chargeback_ready(coverage)
    largest_team = max(by_team, key=by_team.get) if by_team else "n/a"
    total_daily = sum(by_team.values())

    # write a FOCUS-style export (first 50 rows as a sample)
    focus = allocation.to_focus_rows(priced[:50])
    out_path = os.path.join(ROOT, "outputs", "focus_export.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["BillingAccountId", "ChargePeriodStart", "ServiceCategory",
                    "ServiceName", "ResourceId", "BilledCost", "BillingCurrency", "team", "project"])
        for fr in focus:
            w.writerow([fr["BillingAccountId"], fr["ChargePeriodStart"], fr["ServiceCategory"],
                        fr["ServiceName"], fr["ResourceId"], fr["BilledCost"], fr["BillingCurrency"],
                        fr["Tags"]["team"], fr["Tags"]["project"]])

    if verbose:
        print("== M4 Cost Allocation ==")
        print("cost by team ($/day):")
        for k, v in sorted(by_team.items(), key=lambda x: -x[1]):
            print(f"  {k:12} ${v:8.2f}")
        print(f"tag coverage: {coverage:.0%}  ->  chargeback ready? {ready}")
        print(f"FOCUS export -> outputs/focus_export.csv ({len(focus)} rows)")

    return {"by_team": {k: round(v, 2) for k, v in by_team.items()},
            "by_project": {k: round(v, 2) for k, v in by_project.items()},
            "tag_coverage": round(coverage, 3), "chargeback_ready": ready,
            "by_team_exact": by_team, "tag_coverage_exact": coverage,
            "largest_team": largest_team, "total_daily_usd": total_daily,
            "largest_team_daily_usd": by_team.get(largest_team, 0.0),
            "largest_team_share_pct": by_team.get(largest_team, 0.0) / total_daily * 100 if total_daily else 0.0,
            "requests": len(priced), "untagged_requests": sum(not all(r.get(tag) for tag in TAGS) for r in priced),
            "focus_export_rows": len(focus)}


if __name__ == "__main__":
    run()
