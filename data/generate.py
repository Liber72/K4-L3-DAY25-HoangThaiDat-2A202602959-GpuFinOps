"""Deterministic synthetic-data generator for Lab 25.

Run:  python data/generate.py
Produces price_catalog.csv, gpu_telemetry.csv, token_usage.csv, workloads.csv.
Seeded (fixed) so every student/grader gets identical data. Figures are June-2026
illustrative snapshots aligned with the deck's RESEARCH dossier.
"""
from __future__ import annotations
import csv
import os
import random
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 25

# ---- GPU price catalog (neocloud-ish 2026 $/GPU-hr; peak TFLOPs/BW illustrative) ----
PRICE_CATALOG = [
    # gpu_type, provider_class, on_demand_hr, spot_hr, r1yr_hr, r3yr_hr, hbm_gb, fp16_tflops, fp4_tflops, bw_tbs, watts
    ("H100", "neocloud",   2.50, 1.50, 2.00, 1.40,  80,  990,    0, 3.35, 700),
    ("H200", "neocloud",   3.95, 2.60, 3.20, 2.40, 141,  990,    0, 4.80, 700),
    ("A100", "neocloud",   1.79, 1.10, 1.40, 1.00,  80,  312,    0, 2.00, 400),
    ("A10G", "neocloud",   1.00, 0.40, 0.80, 0.60,  24,  125,    0, 0.60, 150),
    ("L4",   "neocloud",   0.80, 0.35, 0.60, 0.45,  24,  121,    0, 0.30,  72),
    ("B200", "neocloud",   5.09, 2.68, 4.20, 3.20, 192, 2250, 9000, 8.00,1000),
    ("MI300X","neocloud",  1.95, 1.20, 1.60, 1.20, 192, 1307,    0, 5.30, 750),
]
CATALOG_HEADER = ["gpu_type","provider_class","on_demand_hr","spot_hr","reserved_1yr_hr",
                  "reserved_3yr_hr","hbm_gb","peak_tflops_fp16","peak_tflops_fp4","peak_bw_tbs","watts"]

# Per-GPU profiles for telemetry. (mfu_target drives achieved_tflops; util may LIE.)
FLEET = [
    # gpu_id, gpu_type, workload, util_pct, mfu_target, idle_overnight
    ("gpu-h100-0", "H100", "train",  95, 0.42, False),
    ("gpu-h100-1", "H100", "train",  96, 0.41, False),
    ("gpu-h100-2", "H100", "train",  94, 0.40, False),
    ("gpu-h100-3", "H100", "train",  93, 0.43, False),
    ("gpu-h100-4", "H100", "train",  98, 0.20, False),  # THE LIE: 98% util, MFU 0.20
    ("gpu-h100-5", "H100", "train",  90, 0.38, True),   # idle overnight -> wasted $
    ("gpu-a100-0", "A100", "infer",  32, 0.26, False),
    ("gpu-a100-1", "A100", "infer",  28, 0.24, False),
    ("gpu-a10g-0", "A10G", "infer",  25, 0.22, False),
    ("gpu-a10g-1", "A10G", "infer",  97, 0.27, False),  # another util-lie candidate
    ("gpu-l4-0",   "L4",   "embed",  40, 0.30, False),
]


def _catalog_map():
    return {row[0]: row for row in PRICE_CATALOG}


def gen_price_catalog():
    with open(os.path.join(HERE, "price_catalog.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CATALOG_HEADER)
        w.writerows(PRICE_CATALOG)


def gen_telemetry(rng):
    cat = _catalog_map()
    rows = []
    for gpu_id, gtype, workload, util, mfu_t, idle in FLEET:
        peak_fp16 = cat[gtype][7]
        peak_bw = cat[gtype][9]
        watts = cat[gtype][10]
        for hour in range(24):
            night = hour < 8
            if idle and night:
                u = rng.uniform(1, 5)
                ach = peak_fp16 * 0.01
                bw = peak_bw * 0.02
                pw = watts * 0.15
            else:
                u = max(1.0, min(100.0, util + rng.uniform(-3, 3)))
                mfu = max(0.02, mfu_t + rng.uniform(-0.03, 0.03))
                ach = peak_fp16 * mfu
                bw = peak_bw * max(0.05, min(0.95, mfu + rng.uniform(-0.05, 0.1)))
                pw = watts * (0.5 + 0.5 * u / 100.0)
            rows.append([
                f"2026-06-15T{hour:02d}:00:00", gpu_id, gtype,
                round(u, 1), round(u * rng.uniform(0.9, 1.0), 1),
                round(min(u, ach / peak_fp16 * 100), 1), round(bw / peak_bw * 100, 1),
                round(pw, 0), round(cat[gtype][6] * rng.uniform(0.4, 0.85), 1),
                round(ach, 1), round(bw, 3), workload,
            ])
    with open(os.path.join(HERE, "gpu_telemetry.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts","gpu_id","gpu_type","gpu_util_pct","sm_active_pct","tensor_active_pct",
                    "dram_active_pct","power_w","mem_used_gb","achieved_tflops","achieved_bw_tbs","workload"])
        w.writerows(rows)


TEAMS = ["search", "rag", "assistant", "eval"]
PROJECTS = {"search": "web-search", "rag": "doc-qa", "assistant": "chat", "eval": "nightly-eval"}


def gen_token_usage(rng, n=2400):
    rows = []
    for i in range(n):
        team = rng.choices(TEAMS, weights=[3, 3, 4, 2])[0]
        # eval traffic is batchable + reasoning-heavy; chat has cacheable system prompts
        is_batch = (team == "eval")
        is_reasoning = (team == "eval" and rng.random() < 0.5)
        # 80% of requests are easy -> small model is enough (cascading opportunity)
        route_tier = "small" if rng.random() < 0.8 else "large"
        model = "small" if route_tier == "small" else "large"
        inp = rng.randint(400, 4000)
        # chat/rag share a big static system prompt -> high cache-hit potential
        cacheable = inp * (0.7 if team in ("assistant", "rag") else 0.1)
        cached = int(cacheable * rng.uniform(0.5, 0.95))
        out = rng.randint(80, 1200) * (6 if is_reasoning else 1)  # reasoning tax
        rows.append([
            f"2026-06-15T{rng.randint(0,23):02d}:{rng.randint(0,59):02d}:00", model, team,
            PROJECTS[team] if rng.random() > 0.08 else "",  # ~8% untagged
            route_tier, inp, out, cached, int(is_batch), int(is_reasoning),
            rng.randint(80, 4000),
        ])
    # Extra deterministic cache metadata without consuming RNG or changing tokens.
    # Prompt contents are unavailable: prefix IDs are an explicit synthetic proxy,
    # grouped by team/model and a 12-request arrival window, not verified text matches.
    prefix_ids = [f"{row[2]}:{row[4]}:window-{index // 12}" for index, row in enumerate(rows)]
    reads = Counter(prefix_ids)
    for row, prefix_id in zip(rows, prefix_ids):
        row.extend([prefix_id, reads[prefix_id]])
    with open(os.path.join(HERE, "token_usage.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ts","model","team","project","route_tier","input_tokens","output_tokens",
                    "cached_input_tokens","is_batch","is_reasoning","latency_ms",
                    "cached_prefix_id","avg_cache_reads"])
        w.writerows(rows)


def gen_workloads():
    rows = [
        ("job-train-llm",   "rag",       "train",  20, 14, 1, "H100", 8),
        ("job-train-embed", "search",    "train",  10,  5, 1, "A100", 4),
        ("job-finetune",    "assistant", "train",   6,  3, 1, "H100", 2),
        ("job-infer-chat",  "assistant", "infer",  24, 30, 0, "A10G", 6),
        ("job-infer-rag",   "rag",       "infer",  24, 30, 0, "A100", 3),
        ("job-infer-search","search",    "infer",  18, 30, 0, "L4",   4),
        ("job-dev-sandbox", "eval",      "dev",     8, 22, 1, "A10G", 2),
        ("job-batch-eval",  "eval",      "infer",   3, 30, 1, "H100", 1),
    ]
    with open(os.path.join(HERE, "workloads.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["job_id","team","kind","hours_per_day","days","interruptible","gpu_type","num_gpus"])
        w.writerows(rows)


def main():
    rng = random.Random(SEED)
    gen_price_catalog()
    gen_telemetry(rng)
    gen_token_usage(rng)
    gen_workloads()
    print("Generated: price_catalog.csv, gpu_telemetry.csv, token_usage.csv, workloads.csv")


if __name__ == "__main__":
    main()
