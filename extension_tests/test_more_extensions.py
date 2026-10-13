"""Economic boundary cases and feasibility checks for Extensions 1-3."""
import csv
import os
import sys
from collections import Counter

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from finops import pricing, rightsizing
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation
from missions._common import load_csv

H100 = {"on_demand_hr": 2.5, "spot_hr": 1.5, "reserved_1yr_hr": 2.0, "reserved_3yr_hr": 1.4}
MODELS = {"small": (0.2, 0.4), "large": (3.0, 15.0)}


def test_policy_respects_full_commitment_duration_and_idle_hours():
    short = pricing.purchasing_plan(24, False, "H100", 30, H100)
    assert short["tier"] == "on_demand"
    assert short["options_usd"]["reserved_1yr"] == pytest.approx(365 * 24 * 2.0)
    assert short["options_usd"]["reserved_3yr"] == pytest.approx(1095 * 24 * 1.4)
    assert pricing.recommend_tier(24, False, gpu_type="H100", job_days=365, catalog=H100) == "reserved_1yr"
    assert pricing.recommend_tier(24, False, gpu_type="H100", job_days=1095, catalog=H100) == "reserved_3yr"
    low_duty = pricing.purchasing_plan(4, False, "H100", 365, H100)
    assert low_duty["tier"] == "on_demand"
    # More than a full term requires another full term, not fractional commitment.
    renewal = pricing.purchasing_plan(24, False, "H100", 366, H100)
    assert renewal["options_usd"]["reserved_1yr"] == pytest.approx(2 * 365 * 24 * 2.0)


def test_interruption_rate_can_make_spot_more_expensive_than_on_demand():
    prices = {"on_demand_hr": 1, "spot_hr": 0.95, "reserved_1yr_hr": 10, "reserved_3yr_hr": 10}
    quiet = pricing.purchasing_plan(1, True, "H100", 30, prices, interrupt_rate=0)
    risky = pricing.purchasing_plan(1, True, "H100", 30, prices, interrupt_rate=0.2)
    assert quiet["tier"] == "spot"
    assert quiet["cost_usd"] == pytest.approx(30 * 0.95 * 1.03)
    assert risky["tier"] == "on_demand"
    assert "spot" not in pricing.purchasing_plan(1, False, "H100", 30, prices)["options_usd"]
    assert pricing.purchasing_plan(0, True, "H100", 30, prices)["cost_usd"] == 0
    with pytest.raises(ValueError):
        pricing.purchasing_plan(25, False, "H100", 30, prices)


def test_cache_requires_strictly_more_than_break_even_reads():
    threshold = pricing.cache_break_even_reads(3.75, 3.0)
    assert threshold == pytest.approx(1.25 / 0.9)
    assert not pricing.cache_is_worth_it(threshold, 3.75, price_in_per_m=3.0)
    assert not pricing.cache_is_worth_it(1, 3.75, price_in_per_m=3.0)
    assert pricing.cache_is_worth_it(2, 3.75, price_in_per_m=3.0)
    assert not pricing.cache_is_worth_it(100, 0, read_discount=1)
    with pytest.raises(ValueError):
        pricing.cache_is_worth_it(float("nan"), 0.25)


def test_cache_write_does_not_receive_batch_discount():
    row = {"route_tier": "large", "input_tokens": 1000, "output_tokens": 0,
           "cached_input_tokens": 1000, "is_batch": 0, "avg_cache_reads": 2}
    assert pricing.inference_request_cost(row, MODELS) == pytest.approx(0.0003 + 0.00375 / 2)
    row["is_batch"] = 1
    # Two reads would lose money with batch, so no caching or write is charged.
    assert pricing.inference_request_cost(row, MODELS) == pytest.approx(0.0015)
    row["avg_cache_reads"] = 3
    assert pricing.inference_request_cost(row, MODELS) == pytest.approx(0.0003 * 0.5 + 0.00375 / 3)
    row["avg_cache_reads"] = 0
    assert pricing.inference_request_cost(row, MODELS) == pytest.approx(0.0015)


def test_rightsizing_rejects_cheapest_gpu_when_memory_or_bandwidth_cannot_fit():
    catalog = {
        "current": {"hbm_gb": 80, "peak_bw_tbs": 2, "on_demand_hr": 2},
        "cheap_small": {"hbm_gb": 32, "peak_bw_tbs": 2, "on_demand_hr": 0.5},
        "cheap_slow": {"hbm_gb": 80, "peak_bw_tbs": 0.3, "on_demand_hr": 1},
        "fits": {"hbm_gb": 80, "peak_bw_tbs": 1, "on_demand_hr": 1.5},
    }
    summary = [{"gpu_id": "gpu-1", "gpu_type": "current", "mbu": 0.2, "idle_hours": 0}]
    telemetry = [{"gpu_id": "gpu-1", "workload": "infer", "mem_used_gb": 60, "achieved_bw_tbs": 0.35}]
    result = rightsizing.analyze_rightsizing(summary, telemetry, catalog)
    proposal = result["recommendations"][0]
    assert proposal["proposed_gpu"] == "fits"
    assert proposal["required_memory_gb"] == pytest.approx(66)
    assert proposal["required_peak_bw_tbs"] == pytest.approx(0.5)
    assert proposal["savings_monthly"] == pytest.approx(360)
    blocked = rightsizing.analyze_rightsizing(summary, telemetry, catalog, memory_headroom=0.5)
    assert blocked["savings_monthly"] == 0
    telemetry[0]["workload"] = "train"
    assert rightsizing.analyze_rightsizing(summary, telemetry, catalog)["recommendations"] == []
    assert rightsizing.analyze_rightsizing([], [], catalog)["savings_monthly"] == 0


def test_all_extensions_integrate_with_allocation_and_reproducible_metadata():
    r1 = m1_efficiency_audit.run(False)
    r2 = m2_inference_levers.run(False)
    r3 = m3_purchasing.run(False)
    r4 = m4_allocation.run(False)
    proposals = {row["gpu_id"]: row for row in r1["rightsizing"]["recommendations"]}
    assert proposals["gpu-a10g-0"]["proposed_gpu"] == "L4"
    assert proposals["gpu-a10g-1"]["changed"] is False
    assert r1["rightsizing"]["savings_monthly"] == pytest.approx(144)
    cache = r2["cache_economics"]
    assert cache["used_requests"] + cache["skipped_requests"] == r2["request_count"]
    assert cache["net_cache_savings_daily_usd"] > 0
    assert cache["write_daily_usd"] > 0
    assert sum(r4["by_team"].values()) == pytest.approx(r2["optimized_daily"], abs=0.03)
    rows = load_csv("token_usage.csv")
    counts = Counter(row["cached_prefix_id"] for row in rows)
    assert all(int(row["avg_cache_reads"]) == counts[row["cached_prefix_id"]] for row in rows)
    assert len(r3["policy_matrix"]) == 126
    assert {row["tier"] for row in r3["policy_matrix"]} == {"spot", "on_demand", "reserved_1yr", "reserved_3yr"}
    for proposal in r3["recommendations"]:
        options = proposal["horizon_options_per_gpu_usd"]
        assert options[proposal["purchase_option"]] == pytest.approx(min(options.values()))
    with open(os.path.join(ROOT, "outputs", "tier_policy_matrix.csv"), newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == len(r3["policy_matrix"])
