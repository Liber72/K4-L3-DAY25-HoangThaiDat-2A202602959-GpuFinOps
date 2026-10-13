"""Evidence tables for tier selection, MBU right-sizing and cache economics."""
from __future__ import annotations


def additional_extension_lines(analysis: dict) -> list[str]:
    purchasing = analysis["purchasing"]
    comparison = purchasing["policy_comparison"]
    sizing = analysis["audit"]["rightsizing"]
    cache = analysis["inference"]["cache_economics"]
    lines = [
        "", "## Extension 1 — Chính sách mua GPU", "",
        "Policy chọn phương án có chi phí thấp nhất trên toàn bộ thời gian nhu cầu dự kiến. "
        "Spot tính thêm 3% checkpoint và 0,5 giờ làm lại mỗi interruption. Reserved tính đủ "
        "24 giờ/ngày cho toàn bộ kỳ 365 hoặc 1.095 ngày, kể cả phần nhàn rỗi và gia hạn nguyên kỳ.",
        "", "Effective GPU-hours = productive GPU-hours × (1 + 0,03 + interruption_rate × 0,5). "
        "Phần giờ tăng thêm trả cho checkpoint và làm lại công việc mất khi spot bị thu hồi. "
        "Với H100 rate giả định 2%/giờ, multiplier là 1,04: cần thêm 4% GPU-hours, "
        "dù sản lượng công việc hữu ích giữ nguyên.",
        "", f"Giả định các workload inference không gián đoạn tiếp tục có nhu cầu "
        f"**{purchasing['recurring_inference_days']} ngày**; đây là tham số planning, không phải dữ kiện "
        "trong CSV. Job khác dùng days của dataset. Tiền trong cửa sổ 30 ngày dùng min(days,30); "
        "chi phí cả horizon/cam kết trình bày riêng, không coi là chi phí của một tháng.",
        "", "| Job | Ngày trong cửa sổ | Horizon nhu cầu (ngày) | Tier mới | Chi phí cửa sổ USD | Chi phí cả horizon/cam kết USD |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for job in purchasing["recommendations"]:
        lines.append(f"| {job['job_id']} | {job['actual_days']:g} | {job['planning_horizon_days']:g} | "
                     f"{job['purchase_option']} | {job['optimized_exact']:.2f} | {job['horizon_plan_cost_usd']:,.2f} |")
    lines += [
        "", f"So sánh policy trên cùng số ngày và cùng cách tính reserved đủ giờ calendar: "
        f"policy cũ **${comparison['legacy_window_usd']:,.2f} ({comparison['legacy_savings_pct']:.2f}% tiết kiệm)**; "
        f"policy mới **${comparison['improved_window_usd']:,.2f} ({comparison['improved_savings_pct']:.2f}%)**; "
        f"giảm thêm **${comparison['additional_savings_usd']:.2f}** trong cửa sổ này. "
        f"Cách prorate reserved theo giờ thực dùng trước đây còn bỏ sót "
        f"**${comparison['reserved_idle_cost_correction_usd']:.2f}** tiền GPU idle phải trả.",
        "", "| GPU | Interruption rate/giờ giả định |",
        "|---|---:|",
    ]
    for gpu, rate in purchasing["interruption_rates"].items():
        lines.append(f"| {gpu} | {rate:.0%} |")
    lines += [
        "", "Các rate là giả định thử nghiệm, không phải dữ liệu thu hồi spot đo được. "
        "[tier_policy_matrix.csv](tier_policy_matrix.csv) có "
        f"{len(purchasing['policy_matrix'])} tình huống GPU × duty cycle × interruptible × horizon.",
        "", "| Horizon inference giả định | Chi phí cửa sổ USD | Các tier inference online |",
        "|---|---:|---|",
    ]
    for scenario in purchasing["horizon_sensitivity"]:
        tiers = "; ".join(f"{job['job_id']}: {job['tier']}" for job in scenario["online_inference_tiers"])
        lines.append(f"| {scenario['recurring_inference_days']} ngày | {scenario['window_cost_usd']:,.2f} | {tiers} |")
    lines += [
        "", "Insight: horizon ngắn có thể chọn on-demand; 1 năm và 3 năm có mức cam kết khác nhau. "
        "Chỉ dùng giả định nhu cầu dài hạn khi có bằng chứng kinh doanh. Giá reserved thấp nhất "
        "theo giờ chưa đủ để kết luận tổng hợp đồng rẻ nhất.",
        "", "## Extension 2 — Right-sizing theo MBU", "",
        f"Xét workload infer/embed có MBU < {sizing['mbu_target']:.0%}. MBU thấp không tự chứng minh "
        "memory-bound; đây là kịch bản inference/decode cần xác nhận bằng profiler. "
        f"VRAM yêu cầu = peak mem_used_gb × {1+sizing['memory_headroom']:.2f}; "
        f"bandwidth yêu cầu = peak achieved_bw_tbs / {sizing['mbu_target']:.2f}. "
        "GPU đề xuất phải đủ cả hai và có giá giờ thấp hơn GPU hiện tại.",
        "", "| GPU catalog | VRAM GB | Peak TB/s | USD/GPU-giờ | USD/GB-VRAM-giờ |",
        "|---|---:|---:|---:|---:|",
    ]
    for gpu in sizing["catalog"]:
        lines.append(f"| {gpu['gpu_type']} | {gpu['hbm_gb']:g} | {gpu['peak_bw_tbs']:.2f} | "
                     f"{gpu['on_demand_hr']:.2f} | {gpu['usd_per_gb_hr']:.5f} |")
    lines += [
        "", "| GPU hiện tại | Đề xuất | VRAM cần GB | Peak BW cần TB/s | Peak BW GPU đề xuất | USD/GB trước → sau | Tiết kiệm USD/tháng | % |",
        "|---|---|---:|---:|---:|---|---:|---:|",
    ]
    for gpu in sizing["recommendations"]:
        lines.append(f"| {gpu['gpu_id']} ({gpu['current_gpu']}) | {gpu['proposed_gpu']} | "
                     f"{gpu['required_memory_gb']:.2f} | {gpu['required_peak_bw_tbs']:.3f} | "
                     f"{gpu['target_peak_bw_tbs']:.2f} | {gpu['current_usd_per_gb_hr']:.5f} → "
                     f"{gpu['target_usd_per_gb_hr']:.5f} | {gpu['savings_monthly']:.2f} | {gpu['savings_pct']:.1f}% |")
    lines += [
        "", f"Tổng các ứng viên inference/embedding: **${sizing['baseline_monthly']:,.2f} → "
        f"${sizing['optimized_monthly']:,.2f}/tháng**, giảm **${sizing['savings_monthly']:.2f} "
        f"({sizing['savings_pct']:.2f}%)** ở giá on-demand. Dòng không đổi GPU nghĩa là không có "
        "GPU rẻ hơn đáp ứng cả VRAM và bandwidth; không ép chọn GPU rẻ nhất.",
        "", "Cần benchmark throughput, p95 latency, kernels và độ chính xác trước khi migrate. "
        "M5 dùng khoản này một lần trong lever Right-size MBU candidates, không cộng lại ở "
        "phần extension. Vẫn cần mapping resource/job để loại trừ phần trùng với purchasing "
        "trước khi dự báo hóa đơn thực.",
        "", "## Extension 3 — Cache có đáng chi phí ghi?", "",
        "Dataset được sinh thêm cached_prefix_id và avg_cache_reads mà không thay đổi các cột "
        "token/tier gốc hoặc tiêu thụ thêm RNG. Prefix mô phỏng được nhóm theo team, tier và "
        "cửa sổ 12 request; avg_cache_reads là số request đọc prefix đó. Không có nội dung prompt "
        "để xác minh các prefix thực sự trùng nhau; metadata này là giả định có thể tái lập.",
        "", f"Một lần ghi được giả định tính {cache['write_multiplier']:.2f}× giá input thường, "
        "phân bổ trên số lần đọc. Cache read tính 10% giá input; batch giảm 50% phần request, "
        "không giảm chi phí ghi. Gate: reads × input_price_after_batch × 0,9 > write_price. "
        "Bằng đúng hòa vốn thì không áp cache.",
        "", "| Model tier | Reads trung bình/request | USD/1M-token ghi | Hòa vốn reads realtime | Hòa vốn reads batch | Request cache | Request bỏ cache |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for tier, group in cache["groups"].items():
        lines.append(f"| {tier} | {group['avg_cache_reads']:.3f} | {group['write_per_m']:.2f} | "
                     f"{group['break_even_reads']:.3f} | {group['batch_break_even_reads']:.3f} | "
                     f"{group['used']} | {group['skipped']} |")
    lines += [
        "", f"Có {cache['prefix_count']} prefix mô phỏng; **{cache['used_requests']} request áp cache**, "
        f"**{cache['skipped_requests']} request bỏ cache**. Ghi phân bổ **${cache['write_daily_usd']:.4f}/ngày**. "
        f"Không cache (vẫn cascade + batch): **${cache['no_cache_batched_daily_usd']:.4f}/ngày**; "
        f"gate + ghi: **${analysis['inference']['stages'][-1]['daily_usd']:.4f}/ngày**; "
        f"tiết kiệm cache ròng **${cache['net_cache_savings_daily_usd']:.4f}/ngày**.",
        "", f"Cách cũ áp cache cho mọi request và bỏ qua tiền ghi cho ra "
        f"**${cache['legacy_free_write_daily_usd']:.4f}/ngày**. Mô hình mới có thể đắt hơn con số "
        "đó vì bổ sung chi phí đã bị bỏ sót. M2, M4, FOCUS và reasoning dùng cùng hàm tính tiền "
        "để giữ số liệu nhất quán. Cache prefix có độ dài biến đổi được mô hình hóa theo chi phí "
        "ghi phân bổ/token; đây không phải mô phỏng cache byte-for-byte.",
    ]
    return lines
