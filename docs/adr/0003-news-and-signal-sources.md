# ADR-0003: Nguồn tin tức và tín hiệu sự kiện

* Ngày: 2026-10-19
* Trạng thái: Đề xuất (chốt sau khi đọc điều khoản tuần 1)

## Bối cảnh

GDELT gom tin từ rất nhiều trang chất lượng thấp, tín hiệu nhiễu; DOC API chỉ tìm được 3 tháng.

## Quyết định

* Đặc trưng mô hình: GPR (Caldara \& Iacoviello), OVX/GVZ/VIX (FRED), lịch FOMC/OPEC+/EIA và chỉ số mức độ ảnh hưởng của tin từ The Guardian và NYT, gắn nhãn bằng Bedrock. Giữ hoặc loại từng nhóm qua kiểm thử ablation.



* Nguồn tin cho chatbot: The Guardian, NYT, thông cáo chính thức và RSS báo Việt Nam.



* Cách truy xuất trong MVP: Sử dụng công cụ get\_news(asset, from\_date, to\_date, min\_impact) để truy vấn tin đã gắn nhãn theo tài sản, khoảng thời gian và mức độ ảnh hưởng. Chatbot cung cấp tiêu đề, ngày đăng, tóm tắt, liên kết nguồn và dùng tin tức làm bối cảnh giải thích dự báo.



* Knowledge Base/vector embedding: Chưa thuộc phạm vi MVP; xem xét triển khai ở giai đoạn sau.



* GDELT: Chỉ dùng làm nguồn phụ nếu cần, lọc theo danh sách domain uy tín.Hệ quả

## Hệ quả



* Các đặc trưng có lịch sử dài có thể hỗ trợ huấn luyện từ năm 2014 cùng dữ liệu giá, nhưng phải kiểm tra độ phủ và thời điểm dữ liệu thực sự khả dụng.



* Căn chỉnh dữ liệu theo thời điểm công bố; GPR cập nhật theo lịch phát hành của nguồn.



* Kiểm tra điều khoản sử dụng API và từng nguồn tin trước khi triển khai. Chỉ lưu tiêu đề, tóm tắt và liên kết khi điều khoản cho phép.



* Tin tức chỉ cung cấp bối cảnh tham khảo, không chứng minh là nguyên nhân gây ra biến động giá.



* MVP chưa sử dụng tìm kiếm ngữ nghĩa qua Knowledge Base.

