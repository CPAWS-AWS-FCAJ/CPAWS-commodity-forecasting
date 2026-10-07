# ADR-0003: Nguồn tin tức và tín hiệu sự kiện

- Ngày: 2026-10-04
- Trạng thái: Đề xuất (chốt sau khi đọc điều khoản tuần 1)

## Bối cảnh
GDELT gom tin từ rất nhiều trang chất lượng thấp, tín hiệu nhiễu; DOC API chỉ tìm được 3 tháng.

## Quyết định
- Đặc trưng mô hình: GPR (Caldara & Iacoviello), OVX/GVZ/VIX (FRED), lịch FOMC/OPEC+/EIA, chỉ số mức độ ảnh hưởng của tin The Guardian và NYT (gắn nhãn bằng Bedrock; giữ hay bỏ theo ablation).
- Chatbot trích dẫn: Guardian, NYT, thông cáo chính thức và RSS báo Việt Nam.
- GDELT chỉ là nguồn phụ, lọc theo danh sách domain uy tín nếu dùng.

## Hệ quả
Tín hiệu có lịch sử dài (huấn luyện từ 2014 cùng giá). Phải căn theo thời điểm công bố (GPR cập nhật thứ Hai). API báo dành cho mục đích phi thương mại; chỉ lưu tiêu đề, tóm tắt, link.
