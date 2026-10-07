# ADR-0002: Dự đoán phân vị log return thay vì mức giá

- Ngày: 2026-10-04
- Trạng thái: Đã chấp nhận

## Bối cảnh
Giá ngày mai gần bằng giá hôm nay, nên mô hình chỉ lặp lại giá hôm nay đã có sai số khoảng 1% ("độ chính xác 99%" ảo). Người dùng cần biết giá lên hay xuống, khoảng bao nhiêu và chắc đến đâu.

## Quyết định
Target là log return h ngày (h = 1…7), mô hình xuất phân vị 10/50/90 bằng quantile loss. Khi hiển thị: quy đổi thành khoảng giá (`P_now · e^r`) và xác suất tăng (`returns.prob_up`). CEEMDAN vẫn tách chuỗi giá (theo cửa sổ trượt) làm đầu vào.

## Hệ quả
Đánh giá bằng MASE so với naive (return = 0), tỷ lệ đúng chiều, coverage, Brier score; bỏ MAPE trên giá. Giá ≤ 0 (WTI 20/4/2020) cho return NaN, bị loại khỏi huấn luyện.
