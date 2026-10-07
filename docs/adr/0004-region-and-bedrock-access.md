# ADR-0004: Region và quyền truy cập Bedrock

- Ngày: <điền sau khi kiểm tra tuần 1>
- Trạng thái: Đang kiểm tra

## Bối cảnh
Hệ thống chạy ở ap-southeast-1. Claude Haiku 4.5 ở Singapore chỉ gọi qua global cross-region inference; Nova gọi qua inference profile. Trang region của Bedrock ghi Singapore "gated" cho Guardrails và Knowledge Bases. Embedding cho Knowledge Bases ở Singapore là Cohere Embed (không có Titan).

## Kết quả kiểm tra (điền)
| Hạng mục | Kết quả | Ghi chú |
|---|---|---|
| Nova Lite qua inference profile | | |
| Claude Haiku 4.5 qua global profile | | |
| Tạo Guardrail | | |
| Tạo Knowledge Base (S3 Vectors + Cohere Embed Multilingual v3) | | |
| Batch inference (quota số bản ghi tối thiểu) | | |

## Quyết định
<giữ toàn bộ ở Singapore | chỉ phần Bedrock chạy ở region dự phòng: …>
