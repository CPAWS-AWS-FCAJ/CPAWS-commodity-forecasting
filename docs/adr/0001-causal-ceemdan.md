# ADR-0001: CEEMDAN theo cửa sổ trượt thay vì trên toàn chuỗi

- Ngày: 2026-09-28
- Trạng thái: Đã chấp nhận

## Bối cảnh
Decompose toàn chuỗi rồi mới chia train/test làm IMF chứa thông tin tương lai (spline dùng điểm hai phía). Kiểm tra trên dữ liệu EC của nhóm: IMF cao tần tính trên cả đoạn tương quan với thay đổi 1–6 bước tới mạnh gấp khoảng hai lần so với khi chỉ dùng dữ liệu quá khứ. Khi vận hành, hệ thống chỉ có IMF ở mép chuỗi.

## Các phương án
1. CEEMDAN toàn chuỗi — nhanh, nhưng rò rỉ và lệch giữa huấn luyện và vận hành.
2. CEEMDAN theo cửa sổ kết thúc tại mỗi origin — chậm hơn, không rò rỉ, khớp vận hành.

## Quyết định
Phương án 2, cài trong `src/forecast/decomposition.py`, bảo vệ bằng `tests/test_no_leakage.py`.

## Hệ quả
Tốn thời gian tính hơn → cache và chạy song song. Kết quả có thể kém bài báo dùng cách 1, nhưng trung thực và đúng khi chạy thật.
