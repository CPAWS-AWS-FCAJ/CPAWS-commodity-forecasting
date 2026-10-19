# ADR-0004: Region và quyền truy cập Bedrock

* Ngày: <điền sau khi kiểm tra tuần 1>
* Trạng thái: Đang kiểm tra

## Bối cảnh

Hệ thống chạy ở ap-southeast-1. Claude Haiku 4.5 ở Singapore chỉ gọi qua global cross-region inference; Nova 2 Lite gọi qua inference profile. Trang region của Bedrock ghi Singapore "gated" cho Guardrails và Knowledge Bases. Embedding cho Knowledge Bases ở Singapore là Cohere Embed (không có Titan).

## Kết quả kiểm tra (điền)

|Hạng mục|Kết quả|Ghi chú|
|-|-|-|
|Nova 2 Lite qua inference profile|PASS|Profile ACTIVE; gọi thành công tại ap-southeast-1. Input 52, output 4 tokens; end\_turn.|
|Claude Haiku 4.5 qua global profile|PASS|Profile ACTIVE; gọi thành công tại ap-southeast-1. Input 16, output 8 tokens; end\_turn.|
|Tạo Guardrail|PASS|Tạo thành công tại ap-southeast-1 bằng AWS CLI. Guardrail ID: xbvoi83l51c0, version DRAFT.|
|Tạo Knowledge Base (S3 Vectors + Cohere Embed Multilingual v3)|CHƯA KIỂM THỬ END-TO-END|Chưa xác nhận tạo Knowledge Base, nạp dữ liệu và truy vấn thành công. Cohere Embed Multilingual v3 được AWS liệt kê hỗ trợ tại Singapore.|
|Batch inference (quota số bản ghi tối thiểu)|PASS|Nova 2 Lite: tối thiểu 100, tối đa 100.000 records/job. Claude Haiku 4.5: tối thiểu 100, tối đa 100.000 records/job.|

## Quyết định

Giữ các thành phần Bedrock đã kiểm thử tại Singapore. Trong MVP, chưa triển khai Knowledge Base; chatbot sử dụng công cụ get\_news(asset, from\_date, to\_date, min\_impact) để truy vấn tin tức đã gắn nhãn tài sản và cung cấp nguồn tham khảo khi giải thích dự báo. Xem xét Knowledge Base ở giai đoạn sau nếu cần.



## Lưu ý



Claude Haiku 4.5 sử dụng global cross-region inference profile, do đó không đảm bảo xử lý hoàn toàn trong Singapore. Chưa có kết quả kiểm thử end-to-end cho Knowledge Base.

