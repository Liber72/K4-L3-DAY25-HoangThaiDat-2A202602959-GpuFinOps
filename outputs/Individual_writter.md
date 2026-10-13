# Bài phân tích Lab 25 GPU FinOps

**Họ tên / MSSV:** Hoàng Thái Đạt / 2A202602959

## 1. Kết quả baseline và optimized

Mô hình lab dự báo chi phí tháng giảm từ $18,005.62 xuống $9,661.62, tiết kiệm $8,344.00 (tương đương 46.34%).
Riêng inference trên 2,400 request và 7,533,027 token/ngày, $/1M-token giảm từ 6.4880 xuống 1.2384 (80.9%). Mẫu số input + output token giữ nguyên, giúp so sánh cùng sản lượng. Mua GPU dùng số ngày job thực tế trong cửa sổ 30 ngày.

## 2. Đòn bẩy tiết kiệm và GPU-Util lie

Purchasing đóng góp lớn nhất, $6,414/tháng, vì baseline mua GPU ($16,539.40) lớn hơn nhiều so với baseline tiền token inference ($1,466.22) trong cửa sổ 30 ngày. Cascade đóng góp lớn nhất trong phần inference. Cache và batch tính tuần tự sau cascade, có tiền ghi cache phân bổ; không cộng các tỷ lệ chiết khấu.

Hai GPU được flag: gpu-h100-4 (Util 98.2%, MFU 0.194); gpu-a10g-1 (Util 96.9%, MFU 0.268). GPU-Util chỉ phản ánh thời gian kernel hoạt động, trong khi MFU phản ánh FLOPs thực. Chờ bộ nhớ/overhead có thể làm MFU thấp; cần profiler xác nhận nguyên nhân. Right-sizing đáp ứng VRAM/bandwidth ở Extension 2 dự báo $144/tháng; tắt GPU idle giảm $600/tháng, chiếm 3.33% baseline M5.

Batch phù hợp với eval hoặc xử lý nền có thể chờ, không phù hợp với chat/truy vấn cần phản hồi tức thì. Trong mô hình discount_stack, input cache toàn bộ còn 10% giá, kết hợp batch còn 50%: 0,50 × 0,10 = 0,05, giảm 95% phần input đó. Output token và tiền ghi cache vẫn tính riêng; không suy ra toàn bộ hóa đơn giảm 95%.

## 3. Phân bổ chi phí và FOCUS

Team assistant tốn nhiều nhất, $3.0330/ngày, chiếm 32.51% tổng chi phí inference. Tag coverage đủ team/project là 91.79%, vượt ngưỡng 80% nên gate chargeback của lab được mở. Còn 197/2,400 request thiếu tag project cần bổ sung để phân bổ chi phí chính xác hơn.

FOCUS chuẩn hóa schema chi phí giữa các nhà cung cấp cloud, giúp tổng hợp và so sánh mà giảm công sức xử lý định dạng riêng. focus_export.csv của lab là mẫu 50 dòng đầu theo schema FOCUS-style đơn giản hóa.

## 4. Kết quả cả 5 phần mở rộng

**Extension 1 — Tier policy:** so sánh on-demand/spot/RI 1yr/3yr với interruption rate theo GPU và nghĩa vụ trả đủ giờ cam kết. Trên cùng basis, savings tăng từ 38.49% lên 38.78%, giảm thêm $47.21/cửa sổ. Horizon inference dài hạn 1095 ngày là giả định; có bảng sensitivity 30/365/1095 ngày và matrix 126 tình huống. Job ngắn có thể dùng on-demand, tránh chọn reserved chỉ vì giá giờ thấp.

Spot có effective hours cao hơn job hours do thời gian checkpoint và làm lại công việc bị mất khi gián đoạn. Công thức của mô hình: GPU-hours × (1 + 3% + interruption_rate × 0,5). H100 với rate giả định 2% có overhead 4%; phần giờ tăng thêm vẫn tính tiền spot.

**Extension 2 — MBU:** ràng buộc peak VRAM + 10% headroom và peak bandwidth/0,70 giữ lại các GPU không đủ điều kiện đổi. Tổng ứng viên giảm từ $4,593.60 xuống $4,449.60/tháng, tiết kiệm $144.00. Chỉ gpu-a10g-0 chuyển L4; A100 cần hơn 24GB, gpu-a10g-1 cần bandwidth vượt L4 theo target này. Giá/GB thấp không thay thế kiểm tra dung lượng, throughput và latency.

**Extension 3 — Cache:** metadata prefix được sinh theo team/tier/cửa sổ 12 request. Hòa vốn reads > 1,389 ở realtime, > 2,778 với batch; ghi tính 1,25× giá input và không được giảm giá batch. Gate áp cache cho 1840 request, bỏ 560 request; ghi phân bổ $0.3810/ngày. Cache tiết kiệm ròng $0.3296/ngày so với không cache trên cùng cascade + batch. Metadata là mô phỏng vì dataset không có nội dung prompt.

**Extension 4 — Reasoning:** Có 201 request reasoning/ngày, chiếm 8.375% traffic nhưng 15.09% chi phí và 94.04% năng lượng. Hệ số 80× chỉ dùng cho năng lượng. Cap 10% không thay đổi traffic; cap 5% chuyển 81 request sang small không reasoning, giảm $0.2401/ngày và 7612.01 Wh/ngày (24.03%). Token/cache/batch giữ nguyên, ưu tiên giữ request dài nhất chỉ là proxy. Cần kiểm tra chất lượng để quyết định request nào thật sự cần reasoning.

**Extension 5 — Carbon:** 5 job interruptible dùng 1,789.00 kWh theo công suất catalog và số ngày thực tế. Chuyển từ us-east-1 sang europe-north1 giảm carbon từ 679.82 xuống 53.67 kgCO2e, giảm 92.11%; phần điện ước tính giảm $53.67. Điện rẻ nhất là us-east-wa; phương án cân bằng 50/50 cũng là us-east-wa. Cần xét vị trí dữ liệu, phí truyền, GPU sẵn có và latency trước khi chọn vùng.

## 5. Ba hành động đầu tiên và giới hạn

1. Rà soát hợp đồng GPU và khả năng checkpoint, chọn spot/reserved theo duty cycle và thời hạn sử dụng, tránh cam kết dài khi nhu cầu chưa chắc chắn.
2. Áp dụng cascade/cache/batch với bộ eval chất lượng; theo dõi $/1M-token và reasoning quota.
3. Tắt GPU idle, profile GPU bị flag, thử right-size và chuyển job interruptible theo ưu tiên chi phí/carbon.

Tổng tiết kiệm theo mô hình M5 giả định 4 lever độc lập, nhưng telemetry và workloads chưa có mapping để loại trừ trùng lặp. M3 tính đủ reserved nhưng horizon dài hạn là giả định. MBU tính một lần trong tổng 4 lever; reasoning và tiền điện theo vùng được trình bày riêng. Năng lượng là ước tính, chưa gồm PUE/host/network hoặc overhead spot. Số liệu snapshot 6/2026 cần cập nhật trước khi áp dụng thực tế.
