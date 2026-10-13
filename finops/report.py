"""Report assembly — the lab's deliverable: baseline vs optimized + savings chart."""
from __future__ import annotations
from finops.extension_reports import additional_extension_lines


def build_report(baseline_usd: float, optimized_usd: float, levers: dict,
                 sustainability: dict | None = None, period: str = "monthly",
                 analysis: dict | None = None) -> str:
    """Return a markdown cost-optimization report."""
    savings = baseline_usd - optimized_usd
    pct = (savings / baseline_usd * 100.0) if baseline_usd > 0 else 0.0
    lines = [
        "# NimbusAI — GPU Cost Optimization Report",
        "",
        f"**Period:** {period}",
        "",
        f"**Baseline spend:** ${baseline_usd:,.2f}",
        "",
        f"**Optimized spend:** ${optimized_usd:,.2f}",
        "",
        f"**Projected savings:** ${savings:,.0f}  (**{pct:.0f}%**; chi tiết {pct:.2f}%)",
        "",
        "## Savings by lever",
        "",
        "| Lever | Savings (USD) |",
        "|---|---|",
    ]
    for name, amount in levers.items():
        lines.append(f"| {name} | ${amount:,.0f} |")
    if sustainability:
        lines += [
            "",
            "## Sustainability",
            "",
            f"- Energy per query (modeled traffic average): {sustainability.get('wh_per_query', 0):.2f} Wh",
            f"- Carbon per query (us-east-1): {sustainability.get('carbon_g', 0):.3f} gCO2e",
            f"- Lowest-carbon region: {sustainability.get('best_region', 'n/a')}",
            f"- Cheapest electricity region: {sustainability.get('cheapest_region', 'n/a')}",
        ]
    if analysis:
        lines += _analysis_lines(analysis, levers)
    lines += ["", "_Figures are June-2026 as-of snapshots; re-baseline before acting._"]
    return "\n".join(lines)


def savings_waterfall(levers: dict, path: str, baseline_usd: float | None = None) -> str:
    """Write savings bars, or a cumulative baseline-to-optimized waterfall."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return ""
    names = list(levers.keys())
    vals = [levers[n] for n in names]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    if baseline_usd is None:
        ax.bar(names, vals, color="#2e548a")
        ax.set_ylabel("Savings (USD / month)")
    else:
        labels = ["Baseline"] + names + ["Optimized"]
        remaining = baseline_usd
        bottoms, heights = [0.0], [baseline_usd]
        for value in vals:
            remaining -= value
            bottoms.append(remaining)
            heights.append(value)
        bottoms.append(0.0)
        heights.append(remaining)
        bars = ax.bar(labels, heights, bottom=bottoms,
                      color=["#2e548a"] + ["#26845b"] * len(vals) + ["#2e548a"])
        for index, bar in enumerate(bars):
            value = heights[index]
            prefix = "-" if 0 < index < len(bars) - 1 else ""
            ax.text(bar.get_x() + bar.get_width() / 2, bottoms[index] + value + baseline_usd * 0.015,
                    f"{prefix}${value:,.0f}", ha="center", fontsize=9)
            if index < len(bars) - 1:
                level = baseline_usd if index == 0 else bottoms[index]
                ax.plot([index + 0.4, index + 0.6], [level, level], color="#999", linewidth=1)
        ax.set_ylim(0, baseline_usd * 1.12)
        ax.set_ylabel("Modeled spend (USD / month)")
    ax.set_title("NimbusAI: baseline to optimized GPU cost")
    ax.grid(axis="y", alpha=0.15)
    ax.set_axisbelow(True)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def _analysis_lines(analysis: dict, levers: dict) -> list[str]:
    """Render measured evidence supplied by missions; never recalculate bill totals."""
    inference = analysis["inference"]
    budget = inference["reasoning_budget"]
    schedule = analysis["purchasing"]["carbon_schedule"]
    stages = inference["stages"]
    allocation = analysis["allocation"]
    idle_pct = levers["Kill idle GPUs"] / analysis["baseline_monthly_exact"] * 100 if analysis["baseline_monthly_exact"] else 0.0
    lines = [
        "", "## Phạm vi và phương pháp", "",
        "Dữ liệu tổng hợp seed=25, snapshot tháng 6/2026; quy đổi một ngày traffic thành 30 ngày. "
        "Đây là mô hình lập kế hoạch của lab. M3 và phần carbon dùng số ngày thực tế của từng job, "
        "giới hạn trong cửa sổ 30 ngày. Chọn tier reserved còn cần horizon nhu cầu dài hạn "
        "được khai báo riêng trong Extension 1. "
        "M5 làm tròn tiết kiệm mỗi lever tới USD trước khi cộng tổng; baseline không làm tròn sớm. "
        "Năng lượng/truy vấn là trung bình theo toàn bộ traffic, bao gồm reasoning, thay cho "
        "mẫu cố định 800 token trước đây.",
        "", "## Chi phí inference theo $/1M-token", "",
        f"Phân tích {inference['request_count']:,} request/ngày, {inference['total_tokens']:,} token/ngày. "
        "Mẫu số gồm toàn bộ input + output token, kể cả input được cache; giữ nguyên ở mọi bước. "
        "Chi phí training/mua GPU được trình bày riêng, không đưa vào mẫu số token inference.",
        "", "| Bước áp dụng | USD/ngày | $/1M-token | Tiết kiệm tăng thêm USD/ngày |",
        "|---|---:|---:|---:|",
    ]
    previous = stages[0]["daily_usd"]
    for stage in stages:
        lines.append(f"| {stage['name']} | {stage['daily_usd']:.4f} | {stage['per_m']:.4f} | "
                     f"{previous - stage['daily_usd']:.4f} |")
        previous = stage["daily_usd"]
    lines += [
        "", f"Inference giảm **{inference['savings_pct']:.1f}%**. Các khoản tiết kiệm tăng thêm "
        "tính tuần tự cascade → cache → batch, tránh cộng trùng phần chiết khấu.",
        "", "Trong mô hình discount_stack, input cache toàn bộ còn 10% giá, rồi batch còn 50%: "
        "0,50 × 0,10 = 0,05, tương đương giảm 95% phần input này. Output token và tiền ghi cache "
        "vẫn phải tính riêng; 95% không phải mức giảm toàn bộ hóa đơn của dataset. "
        "Batch phù hợp với eval/xử lý nền có thể chờ, không phù hợp với chat hoặc truy vấn "
        "có yêu cầu latency thấp và phản hồi tức thì.",
        "", "## Kiểm toán GPU-Util lie", "",
        "| GPU | GPU-Util | MFU | MBU |",
        "|---|---:|---:|---:|",
    ]
    for gpu in analysis["audit"]["lies"]:
        lines.append(f"| {gpu['gpu_id']} | {gpu['gpu_util_pct']:.1f}% | {gpu['mfu']:.3f} | {gpu['mbu']:.3f} |")
    lines += [
        "", "GPU-Util đo tỷ lệ thời gian có kernel chạy, còn MFU đo FLOPs đạt được so với peak. "
        "GPU bận có thể vẫn sử dụng ít năng lực tính toán do chờ bộ nhớ, kernel nhỏ hoặc overhead. "
        "Telemetry này phát hiện triệu chứng; cần profiler để xác nhận nguyên nhân.",
        "", f"M5 dùng right-sizing đáp ứng VRAM/bandwidth ở Extension 2, tiết kiệm "
        f"**${levers['Right-size MBU candidates']:,.0f}/tháng**. Không suy ra khả năng hạ GPU chỉ từ MFU thấp. "
        f"GPU idle gây lãng phí **${analysis['audit']['idle_waste_daily']:.2f}/ngày**, "
        f"tương đương **${levers['Kill idle GPUs']:,.0f}/tháng**, chiếm **{idle_pct:.2f}% baseline M5**. "
        "GPU thay thế cần kiểm tra VRAM, "
        "băng thông, throughput và latency trước khi thực hiện.",
        *_allocation_lines(allocation),
        *additional_extension_lines(analysis),
        "", "## Extension 4 — Ngân sách reasoning", "",
        "| Nhóm | Request/ngày | % traffic | USD/ngày | % chi phí | Wh/ngày | % năng lượng |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, group in budget["groups"].items():
        lines.append(f"| {name} | {group['requests']} | {group['traffic_pct']:.3f}% | "
                     f"{group['cost_usd']:.4f} | {group['cost_pct']:.2f}% | "
                     f"{group['energy_wh']:.2f} | {group['energy_pct']:.2f}% |")
    lines += [
        "", "Chi phí USD dùng route_tier, số token, cache và batch thực tế. "
        "Hệ số 80× của lab chỉ áp dụng cho năng lượng; không nhân giá token với 80. "
        "Số output token reasoning đã dài hơn trong dataset, không nhân thêm lần nữa.",
        "", f"Nếu cùng các token reasoning chạy trên model small không reasoning, chi phí là "
        f"${budget['same_token_small_cost_usd']:.4f}/ngày và năng lượng {budget['same_token_standard_energy_wh']:.2f} Wh/ngày. "
        f"Chênh lệch hiện tại là **${budget['reasoning_extra_usd']:.4f}/ngày** và "
        f"**{budget['reasoning_extra_wh']:.2f} Wh/ngày**. Đây là so sánh cùng số token, chưa đo chất lượng.",
        "", "| Giới hạn reasoning / tổng traffic | Request giữ lại | Request chuyển small | USD/ngày sau | USD/ngày tiết kiệm | Wh/ngày tiết kiệm |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for scenario in budget["scenarios"]:
        lines.append(f"| {scenario['cap_fraction']:.0%} | {scenario['retained_requests']} | "
                     f"{scenario['rerouted_requests']} | {scenario['cost_usd']:.4f} | "
                     f"{scenario['savings_usd']:.4f} | {scenario['savings_wh']:.2f} |")
    lines += [
        "", "Giữ request reasoning có tổng token dài nhất trước, dùng thứ tự dòng làm tie-breaker. "
        "Request vượt giới hạn chuyển sang small, tắt reasoning và giữ nguyên token/cache/batch. "
        "Độ dài chỉ là proxy cho kịch bản; dữ liệu không có complexity score hoặc nhãn chất lượng.",
        "", "Quy tắc đề xuất: chỉ bật reasoning cho task cần suy luận nhiều bước khi model small "
        "chưa đạt ngưỡng chất lượng; theo dõi quota theo ngày. Giới hạn 10% là guardrail; thử nghiệm 5% trên eval "
        "và kiểm tra chất lượng trước khi áp dụng. Kịch bản không tăng model small lên large.",
        "", "## Extension 5 — Lịch chạy theo carbon", "",
        "Chỉ xét job interruptible=1. Công thức: kWh = watts × số GPU × giờ/ngày × "
        "min(days, 30) / 1000; gCO2e = kWh × cường độ carbon vùng. Công suất dùng catalog, "
        "chưa gồm máy chủ, PUE, truyền dữ liệu và overhead checkpoint/rework.",
        "", "| Job | Số ngày | GPU-giờ | kWh | kgCO2e hiện tại | kgCO2e vùng sạch | kgCO2e giảm |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for job in schedule["jobs"]:
        lines.append(f"| {job['job_id']} | {job['days']:g} | {job['gpu_hours']:g} | "
                     f"{job['energy_kwh']:.2f} | {job['baseline_carbon_g']/1000:.2f} | "
                     f"{job['target_carbon_g']/1000:.2f} | {job['carbon_saved_g']/1000:.2f} |")
    lines += [
        "", f"Tổng {len(schedule['jobs'])} job, **{schedule['energy_kwh']:,.2f} kWh**. "
        f"Chuyển từ {schedule['baseline_region']} sang {schedule['cleanest_region']} "
        f"giảm **{schedule['carbon_saved_g']/1000:,.2f} kgCO2e ({schedule['carbon_savings_pct']:.2f}%)** "
        f"và giảm phần điện ước tính **${schedule['electricity_saved_usd']:.2f}** trong cửa sổ job này.",
        "", "| Vùng | USD/kWh | gCO2e/kWh | Tiền điện USD | Carbon kgCO2e | Điểm cân bằng |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for region in schedule["regions"]:
        lines.append(f"| {region['region']} | {region['price_kwh']:.3f} | {region['carbon_g_per_kwh']} | "
                     f"{region['electricity_usd']:.2f} | {region['carbon_g']/1000:.2f} | "
                     f"{region['balanced_score']:.3f} |")
    lines += [
        "", f"Điện rẻ nhất: **{schedule['cheapest_region']}**; carbon thấp nhất: "
        f"**{schedule['cleanest_region']}**; phương án cân bằng: **{schedule['balanced_region']}**. "
        "Điểm cân bằng = 0,5 × (giá điện / giá điện baseline) + 0,5 × "
        "(carbon intensity / carbon intensity baseline), thấp hơn tốt hơn; đây là trọng số giả định. "
        "Chọn vùng còn phụ thuộc GPU sẵn có, thời hạn job, vị trí dữ liệu, phí truyền và latency.",
        "", "## Ba hành động ưu tiên", "",
        f"1. Rà soát mua spot/reserved vì đóng góp ${levers['Purchasing (spot/reserved)']:,.0f}/tháng, "
        "lớn nhất trong mô hình; xác nhận checkpoint, duty cycle và thời hạn cam kết.",
        "2. Áp dụng cascade → cache → batch cho request phù hợp; dùng $/1M-token và chất lượng "
        "làm chỉ số đánh giá, theo dõi reasoning quota trên traffic eval.",
        "3. Tự động tắt GPU idle, profile hai GPU bị flag, rồi thử right-size và chuyển job "
        "interruptible sang vùng phù hợp ưu tiên carbon/điện.",
        "", "## Giả định và giới hạn của tổng tiết kiệm", "",
        "Tổng 4 lever giữ cách tổng hợp của M5. Telemetry không có khóa liên kết với workloads, "
        "nên mô hình giả định right-size/idle độc lập với purchasing; chưa chứng minh các savings "
        "không trùng nhau trên một hóa đơn thực. M3 đã tính đủ cam kết reserved, nhưng horizon "
        "nhu cầu inference dài hạn là giả định; cần xác minh trước khi mua. Cần dựng baseline theo từng "
        "resource/job trước khi dự báo chi phí thực tế.",
        "", "Right-sizing MBU đã tính một lần trong 4 lever. Kịch bản reasoning và phần tiền điện theo vùng được trình bày bổ sung, "
        "không cộng vào 4 lever để tránh cộng trùng hoặc coi tiền điện là khoản giảm hóa đơn cloud. "
        "Năng lượng/carbon là ước tính mô hình, không phải số đo điện thực tế. Tất cả giá/vùng "
        "sử dụng hằng số trong repo, không phải bảng giá hiện hành.",
        "", "## Tái lập kết quả", "",
        "```powershell",
        r".\.venv\Scripts\python.exe -X utf8 missions/run_all.py",
        r".\.venv\Scripts\python.exe -X utf8 verify.py",
        r".\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider tests extension_tests",
        "```", "",
        "Dữ liệu chi tiết: [analysis.json](analysis.json). Bài viết gợi ý: "
        "[writeup_suggested.md](writeup_suggested.md). Checklist hoàn thiện: "
        "[report_completion_guide.md](report_completion_guide.md).",
        "", "![Waterfall tiết kiệm theo 4 lever, làm tròn tới USD](savings.png)",
    ]
    return lines


def _allocation_lines(allocation: dict) -> list[str]:
    total = allocation["total_daily_usd"]
    lines = ["", "## M4 — Phân bổ chi phí và FOCUS", "",
             "| Team | USD/ngày | Tỷ lệ chi phí inference |", "|---|---:|---:|"]
    for team, cost in sorted(allocation["by_team_exact"].items(), key=lambda item: -item[1]):
        share = cost / total * 100 if total else 0.0
        lines.append(f"| {team} | {cost:.4f} | {share:.2f}% |")
    ready = "đủ" if allocation["chargeback_ready"] else "chưa đủ"
    lines += [
        "", f"Team **{allocation['largest_team']}** tốn nhiều nhất: "
        f"**${allocation['largest_team_daily_usd']:.4f}/ngày ({allocation['largest_team_share_pct']:.2f}%)**. "
        f"Tag coverage (đủ team và project) là **{allocation['tag_coverage_exact']:.2%}**, "
        f"{ready} ngưỡng 80% để chargeback theo gate của lab. Còn "
        f"**{allocation['untagged_requests']} / {allocation['requests']} request** thiếu tag bắt buộc; "
        "cần bổ sung để phân bổ chi phí theo project chính xác hơn.",
        "", "FOCUS chuẩn hóa tên cột, đơn vị tiền và thông tin kỳ tính phí giữa các nhà cung cấp, "
        "giúp tổng hợp/so sánh chi phí nhiều cloud mà giảm công sức xử lý schema riêng. "
        f"focus_export.csv của lab là mẫu **{allocation['focus_export_rows']} dòng đầu**, theo "
        "schema FOCUS-style đơn giản hóa; không phải toàn bộ 2.400 request hay chứng nhận "
        "tuân thủ đầy đủ một phiên bản FOCUS.",
    ]
    return lines


def build_writeup(analysis: dict, baseline_usd: float, optimized_usd: float, levers: dict) -> str:
    """Generate a concise Vietnamese draft from the same measured mission results."""
    inference = analysis["inference"]
    budget = inference["reasoning_budget"]
    group = budget["groups"]["reasoning"]
    cap = next(s for s in budget["scenarios"] if s["cap_fraction"] == 0.05)
    schedule = analysis["purchasing"]["carbon_schedule"]
    policy = analysis["purchasing"]["policy_comparison"]
    sizing = analysis["audit"]["rightsizing"]
    cache = inference["cache_economics"]
    pct = (baseline_usd - optimized_usd) / baseline_usd * 100 if baseline_usd else 0
    gpu_text = "; ".join(f"{g['gpu_id']} (Util {g['gpu_util_pct']:.1f}%, MFU {g['mfu']:.3f})"
                         for g in analysis["audit"]["lies"])
    stages = inference["stages"]
    allocation = analysis["allocation"]
    idle_pct = levers["Kill idle GPUs"] / baseline_usd * 100 if baseline_usd else 0.0
    return "\n".join([
        "# Bài phân tích gợi ý — Lab 25 GPU FinOps", "",
        "> Bản nháp sinh từ kết quả chạy code. Điền thông tin học viên và chỉnh lập luận theo "
        "hiểu biết của bạn trước khi nộp. Số liệu chi tiết nằm trong report.md và analysis.json.",
        "", "**Họ tên / MSSV:** [Điền thông tin]", "",
        "## 1. Kết quả baseline và optimized", "",
        f"Mô hình lab dự báo chi phí tháng giảm từ ${baseline_usd:,.2f} xuống ${optimized_usd:,.2f}, "
        f"tiết kiệm ${baseline_usd-optimized_usd:,.2f}, tương đương {pct:.2f}%. Riêng inference trên "
        f"{inference['request_count']:,} request và {inference['total_tokens']:,} token/ngày, "
        f"$/1M-token giảm từ {stages[0]['per_m']:.4f} xuống {stages[-1]['per_m']:.4f} "
        f"({inference['savings_pct']:.1f}%). Mẫu số input + output token giữ nguyên, "
        "giúp so sánh cùng sản lượng. Mua GPU dùng số ngày job thực tế trong cửa sổ 30 ngày.",
        "", "## 2. Đòn bẩy tiết kiệm và GPU-Util lie", "",
        f"Purchasing đóng góp lớn nhất, ${levers['Purchasing (spot/reserved)']:,.0f}/tháng, "
        "vì baseline mua GPU lớn hơn nhiều so với tiền token inference. "
        "Cascade đóng góp lớn nhất trong phần inference. Cache và batch tính tuần tự "
        "sau cascade, có tiền ghi cache phân bổ; không cộng các tỷ lệ chiết khấu.",
        "", f"Hai GPU được flag: {gpu_text}. GPU-Util chỉ phản ánh thời gian kernel hoạt động, "
        "trong khi MFU phản ánh FLOPs thực. Chờ bộ nhớ/overhead có thể làm MFU thấp; "
        "cần profiler xác nhận nguyên nhân. "
        f"Right-sizing đáp ứng VRAM/bandwidth ở Extension 2 dự báo ${levers['Right-size MBU candidates']:,.0f}/tháng; tắt GPU idle "
        f"giảm ${levers['Kill idle GPUs']:,.0f}/tháng, chiếm {idle_pct:.2f}% baseline M5.",
        "", "Batch phù hợp với eval/xử lý nền có thể chờ, không phù hợp với chat cần phản hồi "
        "tức thì. discount_stack với input cache toàn bộ: 0,50 × 0,10 = 0,05, giảm 95% "
        "phần input đó; output token và tiền ghi cache vẫn tính riêng.",
        "", "## 3. Phân bổ chi phí và FOCUS", "",
        f"Team {allocation['largest_team']} tốn nhiều nhất, ${allocation['largest_team_daily_usd']:.4f}/ngày "
        f"({allocation['largest_team_share_pct']:.2f}% chi phí inference). Tag coverage đủ team/project "
        f"là {allocation['tag_coverage_exact']:.2%}, vượt ngưỡng chargeback 80% của lab; "
        f"còn {allocation['untagged_requests']} request thiếu tag cần bổ sung. FOCUS chuẩn hóa schema "
        "chi phí giữa các cloud để tổng hợp và so sánh. Export của lab là mẫu 50 dòng FOCUS-style.",
        "", "## 4. Kết quả cả 5 phần mở rộng", "",
        f"**Extension 1 — Tier policy:** so sánh on-demand/spot/RI 1yr/3yr với interruption rate "
        f"theo GPU và nghĩa vụ trả đủ giờ cam kết. Trên cùng basis, savings tăng từ "
        f"{policy['legacy_savings_pct']:.2f}% lên {policy['improved_savings_pct']:.2f}%, giảm thêm "
        f"${policy['additional_savings_usd']:.2f}/cửa sổ. Horizon inference dài hạn "
        f"{analysis['purchasing']['recurring_inference_days']} ngày là giả định; có bảng sensitivity "
        "30/365/1095 ngày và matrix 126 tình huống. Job ngắn có thể dùng on-demand, tránh "
        "chọn reserved chỉ vì giá giờ thấp.",
        "", "Spot có effective hours lớn hơn job hours vì checkpoint và làm lại phần công việc "
        "bị gián đoạn: GPU-hours × (1 + 3% + interruption_rate × 0,5). "
        "H100 với rate giả định 2% có overhead 4%; phần giờ tăng thêm vẫn tính tiền spot.",
        "", f"**Extension 2 — MBU:** ràng buộc peak VRAM + 10% headroom và peak bandwidth/0,70 "
        f"giữ lại các GPU không đủ điều kiện đổi. Tổng ứng viên giảm từ "
        f"${sizing['baseline_monthly']:,.2f} xuống ${sizing['optimized_monthly']:,.2f}/tháng, "
        f"tiết kiệm ${sizing['savings_monthly']:.2f}. Chỉ gpu-a10g-0 chuyển L4; A100 cần hơn 24GB, "
        "gpu-a10g-1 cần bandwidth vượt L4 theo target này. Giá/GB thấp không thay thế kiểm tra "
        "dung lượng, throughput và latency.",
        "", f"**Extension 3 — Cache:** metadata prefix được sinh theo team/tier/cửa sổ 12 request. "
        "Hòa vốn reads > 1,389 ở realtime, > 2,778 với batch; ghi tính 1,25× giá input và "
        f"không được giảm giá batch. Gate áp cache cho {cache['used_requests']} request, "
        f"bỏ {cache['skipped_requests']} request; ghi phân bổ ${cache['write_daily_usd']:.4f}/ngày. "
        f"Cache tiết kiệm ròng ${cache['net_cache_savings_daily_usd']:.4f}/ngày so với không cache "
        "trên cùng cascade + batch. Metadata là mô phỏng vì dataset không có nội dung prompt.",
        "", "**Extension 4 — Reasoning:** "
        f"Có {group['requests']} request reasoning/ngày, chiếm {group['traffic_pct']:.3f}% traffic "
        f"nhưng {group['cost_pct']:.2f}% chi phí và {group['energy_pct']:.2f}% năng lượng. "
        "Hệ số 80× chỉ dùng cho năng lượng. Cap 10% không thay đổi traffic; cap 5% chuyển "
        f"{cap['rerouted_requests']} request sang small không reasoning, giảm "
        f"${cap['savings_usd']:.4f}/ngày và {cap['savings_wh']:.2f} Wh/ngày "
        f"({cap['energy_savings_pct']:.2f}%). Token/cache/batch giữ nguyên, ưu tiên giữ request dài nhất "
        "chỉ là proxy. Cần kiểm tra chất lượng để quyết định request nào thật sự cần reasoning.",
        "", f"**Extension 5 — Carbon:** {len(schedule['jobs'])} job interruptible dùng "
        f"{schedule['energy_kwh']:,.2f} kWh theo công suất catalog và số ngày thực tế. Chuyển từ "
        f"{schedule['baseline_region']} sang {schedule['cleanest_region']} giảm carbon từ "
        f"{schedule['baseline_carbon_g']/1000:.2f} xuống {schedule['target_carbon_g']/1000:.2f} kgCO2e, "
        f"giảm {schedule['carbon_savings_pct']:.2f}%; phần điện ước tính giảm "
        f"${schedule['electricity_saved_usd']:.2f}. Điện rẻ nhất là {schedule['cheapest_region']}; "
        f"phương án cân bằng 50/50 cũng là {schedule['balanced_region']}. Cần xét vị trí dữ liệu, "
        "phí truyền, GPU sẵn có và latency trước khi chọn vùng.",
        "", "## 5. Ba hành động đầu tiên và giới hạn", "",
        "1. Rà soát hợp đồng GPU và khả năng checkpoint, chọn spot/reserved theo duty cycle "
        "và thời hạn sử dụng, tránh cam kết dài khi nhu cầu chưa chắc chắn.",
        "2. Áp dụng cascade/cache/batch với bộ eval chất lượng; theo dõi $/1M-token và reasoning quota.",
        "3. Tắt GPU idle, profile GPU bị flag, thử right-size và chuyển job interruptible "
        "theo ưu tiên chi phí/carbon.",
        "", "Tổng tiết kiệm theo mô hình M5 giả định 4 lever độc lập, nhưng telemetry và workloads "
        "chưa có mapping để loại trừ trùng lặp. M3 tính đủ reserved nhưng horizon dài hạn là giả định. "
        "MBU tính một lần trong tổng 4 lever; reasoning và tiền điện theo vùng được trình bày riêng. "
        "Năng lượng là ước tính, chưa gồm PUE/host/network hoặc overhead spot. "
        "Số liệu snapshot 6/2026 cần cập nhật trước khi áp dụng thực tế.", "",
    ])


def build_completion_guide() -> str:
    return "\n".join([
        "# Gợi ý hoàn thiện và nộp report", "",
        "Code đã triển khai cả 5 extension: tier policy, right-sizing MBU, cache economics, "
        "reasoning budget và carbon-aware scheduling. "
        "report.md và writeup_suggested.md được tạo từ cùng kết quả trong analysis.json.",
        "", "## Những việc học viên cần hoàn thiện", "",
        "- Sao chép writeup_suggested.md thành writeup_final.md, điền họ tên/MSSV rồi chỉnh "
        "diễn giải và 3 khuyến nghị theo hiểu biết của bạn. File suggested được tạo lại mỗi lần chạy M5.",
        "- Đọc bảng cascade/cache/batch và giải thích đòn bẩy nào giảm $/1M-token nhiều nhất.",
        "- So sánh policy cũ/mới trên cùng cách tính reserved đủ giờ calendar; "
        "giải thích vì sao horizon 30/365/1095 ngày có thể cho tier khác nhau.",
        "- Giải thích vì sao A100 không được chuyển xuống GPU 24GB, và vì sao một A10G "
        "không đủ bandwidth để chuyển L4 dù cùng 24GB VRAM.",
        "- Nêu rõ avg_cache_reads là metadata prefix mô phỏng; giải thích hòa vốn cache "
        "realtime/batch và tiền ghi không được giảm giá batch.",
        "- Giải thích vì sao cap reasoning 10% không tiết kiệm trên dataset này; "
        "nêu điều kiện kiểm tra chất lượng trước khi thử 5%.",
        "- Giải thích vùng điện rẻ nhất khác vùng carbon thấp nhất; "
        "chọn ưu tiên của NimbusAI và lý do. Trọng số 50/50 là giả định có thể thay đổi.",
        "- Phân biệt số ngày job trong cửa sổ 30 ngày với horizon nhu cầu dài hạn để mua reserved.",
        "- Giữ các giới hạn về dữ liệu tổng hợp, điện ước tính, horizon reserved "
        "và khả năng savings trùng lặp; không coi mô hình là dự báo hóa đơn thực.",
        "- Xem savings.png, đối chiếu số liệu với report.md; biểu đồ gồm baseline, 4 lever, optimized.",
        "", "## Chạy lại và kiểm tra", "", "```powershell",
        r".\.venv\Scripts\python.exe -X utf8 data/generate.py",
        r".\.venv\Scripts\python.exe -X utf8 missions/run_all.py",
        r".\.venv\Scripts\python.exe -X utf8 verify.py",
        r".\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider tests",
        r".\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider extension_tests",
        "```", "",
        "Mục tiêu: verify 11/11, 15 test gốc pass và các test extension pass. "
        "Test mới nằm ở extension_tests/, giữ nguyên tests/ được cung cấp.",
        "", "## File nộp", "",
        "- outputs/report.md", "- outputs/savings.png", "- outputs/focus_export.csv",
        "- Bài viết đã cá nhân hóa từ outputs/writeup_suggested.md (.md hoặc .pdf, 1–2 trang).",
        "", "Kèm code extension khi nộp qua repository để người chấm có thể chạy lại. "
        "analysis.json chứa số liệu và các dòng dữ liệu được chuyển tuyến trong kịch bản reasoning; "
        "tier_policy_matrix.csv chứa matrix chọn tier. Có thể giữ làm bằng chứng tái lập.", "",
    ])
