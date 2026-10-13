"""Additional scenario checks; instructor-provided tests/ stays unchanged."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from finops import reasoning, sustainability
from missions import m2_inference_levers, m5_report

PRICES = {"small": (0.20, 0.40), "large": (3.0, 15.0)}


def request(tier="large", is_reasoning=1, input_tokens=1000, output_tokens=1000):
    return {"route_tier": tier, "is_reasoning": is_reasoning, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "cached_input_tokens": 0, "is_batch": 0}


def test_reasoning_uses_token_price_and_energy_multiplier_separately():
    result = reasoning.analyze_reasoning_budget([request(), request(is_reasoning=0)], PRICES)
    groups = result["groups"]
    # Same tier and tokens cost the same; energy alone differs by the modeled 80x.
    assert groups["reasoning"]["cost_usd"] == pytest.approx(0.018)
    assert groups["standard"]["cost_usd"] == pytest.approx(0.018)
    assert groups["reasoning"]["energy_wh"] == pytest.approx(48.0)
    assert groups["standard"]["energy_wh"] == pytest.approx(0.6)
    assert result["reasoning_extra_usd"] == pytest.approx(0.018 - 0.0006)


def test_reasoning_cap_retains_longest_without_promoting_small_model():
    rows = [request(output_tokens=500), request("small", output_tokens=3000), request(is_reasoning=0)]
    result = reasoning.analyze_reasoning_budget(rows, PRICES, caps=(1 / 3,))
    scenario = result["scenarios"][0]
    assert scenario["retained_requests"] == 1
    assert scenario["rerouted_data_rows"] == [1]
    # Row 1 demotes to small; row 2 stays small and reasoning; row 3 stays large.
    assert scenario["cost_usd"] == pytest.approx(0.0004 + 0.0014 + 0.018)
    assert scenario["energy_wh"] == pytest.approx(0.45 + 96.0 + 0.6)


def test_reasoning_caps_noop_zero_and_empty():
    rows = [request(), request(is_reasoning=0)]
    result = reasoning.analyze_reasoning_budget(rows, PRICES, caps=(1.0, 0.0))
    assert result["scenarios"][0]["rerouted_requests"] == 0
    assert result["scenarios"][0]["savings_wh"] == 0.0
    assert result["scenarios"][1]["retained_requests"] == 0
    assert result["scenarios"][1]["savings_wh"] == pytest.approx(47.4)
    empty = reasoning.analyze_reasoning_budget([], PRICES)
    assert empty["total_energy_wh"] == 0
    assert all(s["traffic_pct"] == 0 for s in empty["scenarios"])
    with pytest.raises(ValueError):
        reasoning.analyze_reasoning_budget(rows, PRICES, caps=(float("nan"),))


def test_carbon_job_duration_region_tradeoff_and_noninterruptible_exclusion():
    jobs = [
        {"job_id": "short", "kind": "train", "gpu_type": "H100", "num_gpus": 2,
         "hours_per_day": 10, "days": 3, "interruptible": 1},
        {"job_id": "online", "kind": "infer", "gpu_type": "H100", "num_gpus": 8,
         "hours_per_day": 24, "days": 30, "interruptible": 0},
    ]
    result = sustainability.carbon_aware_schedule(jobs, {"H100": {"watts": 700}})
    assert len(result["jobs"]) == 1
    assert result["energy_kwh"] == pytest.approx(42.0)
    assert result["baseline_carbon_g"] == pytest.approx(15960.0)
    assert result["target_carbon_g"] == pytest.approx(1260.0)
    assert result["carbon_saved_g"] == pytest.approx(14700.0)
    assert result["electricity_saved_usd"] == pytest.approx(1.26)
    assert result["cheapest_region"] == "us-east-wa"
    assert result["cleanest_region"] == "europe-north1"
    assert result["balanced_region"] == "us-east-wa"


def test_carbon_respects_window_and_empty_jobs():
    job = {"job_id": "long", "kind": "train", "gpu_type": "H100", "num_gpus": 1,
           "hours_per_day": 1, "days": 60, "interruptible": 1}
    result = sustainability.carbon_aware_schedule([job], {"H100": {"watts": 1000}}, window_days=7)
    assert result["energy_kwh"] == pytest.approx(7.0)
    assert sustainability.carbon_aware_schedule([], {})["carbon_saved_g"] == 0
    with pytest.raises(ValueError):
        sustainability.carbon_aware_schedule([], {}, window_days=-1)


def test_dataset_cap_ten_percent_is_noop_and_five_percent_reduces_energy():
    result = m2_inference_levers.run(verbose=False)
    budget = result["reasoning_budget"]
    loose, strict = budget["scenarios"]
    assert budget["total_cost_usd"] == pytest.approx(result["stages"][-1]["daily_usd"])
    assert loose["rerouted_requests"] == 0
    assert strict["retained_requests"] == 120
    assert strict["rerouted_requests"] == 81
    assert strict["savings_usd"] > 0 and strict["savings_wh"] > 0
    stages = result["stages"]
    assert all(a["daily_usd"] >= b["daily_usd"] for a, b in zip(stages, stages[1:]))


def test_report_artifacts_match_analysis_and_use_utf8():
    result = m5_report.run(verbose=False)
    with open(os.path.join(ROOT, "outputs", "analysis.json"), encoding="utf-8") as stream:
        evidence = json.load(stream)
    assert evidence["baseline_monthly_exact"] - sum(evidence["levers"].values()) == pytest.approx(
        evidence["optimized_monthly_exact"])
    assert result["baseline_monthly"] == round(evidence["baseline_monthly_exact"])
    allocation = evidence["allocation"]
    assert allocation["total_daily_usd"] == pytest.approx(evidence["inference"]["stages"][-1]["daily_usd"])
    assert sum(allocation["by_team_exact"].values()) == pytest.approx(allocation["total_daily_usd"])
    for filename in ("report.md", "writeup_suggested.md", "report_completion_guide.md"):
        with open(os.path.join(ROOT, "outputs", filename), encoding="utf-8") as stream:
            content = stream.read()
        assert "\ufffd" not in content
        assert "reasoning" in content
    with open(os.path.join(ROOT, "outputs", "report.md"), encoding="utf-8") as stream:
        content = stream.read()
    assert "$/1M-token" in content
    assert all(f"Extension {number}" in content for number in range(1, 6))
    assert "M4 — Phân bổ chi phí và FOCUS" in content
    assert f"{allocation['largest_team_share_pct']:.2f}%" in content
    assert f"{allocation['tag_coverage_exact']:.2%}" in content
    carbon_saving = evidence["purchasing"]["carbon_schedule"]["carbon_saved_g"] / 1000
    assert f"{carbon_saving:,.2f} kgCO2e" in content
    assert "Cheapest+cleanest" not in content
