# Gợi ý hoàn thiện và nộp report

Code đã triển khai cả 5 extension: tier policy, right-sizing MBU, cache economics, reasoning budget và carbon-aware scheduling. report.md và writeup_suggested.md được tạo từ cùng kết quả trong analysis.json.

## Những việc học viên cần hoàn thiện

- Sao chép writeup_suggested.md thành writeup_final.md, điền họ tên/MSSV rồi chỉnh diễn giải và 3 khuyến nghị theo hiểu biết của bạn. File suggested được tạo lại mỗi lần chạy M5.
- Đọc bảng cascade/cache/batch và giải thích đòn bẩy nào giảm $/1M-token nhiều nhất.
- So sánh policy cũ/mới trên cùng cách tính reserved đủ giờ calendar; giải thích vì sao horizon 30/365/1095 ngày có thể cho tier khác nhau.
- Giải thích vì sao A100 không được chuyển xuống GPU 24GB, và vì sao một A10G không đủ bandwidth để chuyển L4 dù cùng 24GB VRAM.
- Nêu rõ avg_cache_reads là metadata prefix mô phỏng; giải thích hòa vốn cache realtime/batch và tiền ghi không được giảm giá batch.
- Giải thích vì sao cap reasoning 10% không tiết kiệm trên dataset này; nêu điều kiện kiểm tra chất lượng trước khi thử 5%.
- Giải thích vùng điện rẻ nhất khác vùng carbon thấp nhất; chọn ưu tiên của NimbusAI và lý do. Trọng số 50/50 là giả định có thể thay đổi.
- Phân biệt số ngày job trong cửa sổ 30 ngày với horizon nhu cầu dài hạn để mua reserved.
- Giữ các giới hạn về dữ liệu tổng hợp, điện ước tính, horizon reserved và khả năng savings trùng lặp; không coi mô hình là dự báo hóa đơn thực.
- Xem savings.png, đối chiếu số liệu với report.md; biểu đồ gồm baseline, 4 lever, optimized.

## Chạy lại và kiểm tra

```powershell
.\.venv\Scripts\python.exe -X utf8 data/generate.py
.\.venv\Scripts\python.exe -X utf8 missions/run_all.py
.\.venv\Scripts\python.exe -X utf8 verify.py
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider tests
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider extension_tests
```

Mục tiêu: verify 11/11, 15 test gốc pass và các test extension pass. Test mới nằm ở extension_tests/, giữ nguyên tests/ được cung cấp.

## File nộp

- outputs/report.md
- outputs/savings.png
- outputs/focus_export.csv
- Bài viết đã cá nhân hóa từ outputs/writeup_suggested.md (.md hoặc .pdf, 1–2 trang).

Kèm code extension khi nộp qua repository để người chấm có thể chạy lại. analysis.json chứa số liệu và các dòng dữ liệu được chuyển tuyến trong kịch bản reasoning; tier_policy_matrix.csv chứa matrix chọn tier. Có thể giữ làm bằng chứng tái lập.
