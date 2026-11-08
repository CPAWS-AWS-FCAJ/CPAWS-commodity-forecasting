# Bộ câu giữ riêng cho router (held-out v1)

- Người soạn: Claude (theo yêu cầu của Khải); người duyệt độc lập: Gemini (lượt chấm không mù, vì đã thấy file nhãn); người chốt: Khải, 4/11/2026.
- File: `router_heldout_v1.jsonl`, 30 câu (12 simple, 18 complex). SHA-256: `da914c2d96d72c89e2b82325d1ccea5a91eb9f9d53cde7b9235c41ed4ba663aa`.
- Không trùng nguyên văn câu nào với benchmark v1, v2, 8 câu loại A, 83 câu phát triển `tests/router/cases.jsonl` và kịch bản demo #77; độ giống cao nhất 0,74.

## Quy tắc gán nhãn

- **simple** (Nova 2 Lite, không tool): chào hỏi, hỏi về chatbot; khái niệm và phương pháp khi không hỏi con số hiện tại; ngoài phạm vi sản phẩm (vàng nhẫn, SJC, xăng, crypto, cổ phiếu); kỳ hạn **dưới 1 phiên** (trong ngày); chỉ xin tư vấn đầu tư; việc không liên quan.
- **complex** (Haiku 4.5, có `get_forecast`, `get_news`): hỏi dự báo, xác suất, khoảng, con số hiện tại của 4 tài sản; so sánh; tin tức hoặc lý do; câu vừa hỏi dự báo vừa xin tư vấn; câu hỗn hợp có phần ngoài phạm vi nhưng vẫn hỏi tài sản trong phạm vi; kỳ hạn **trên 7 phiên** với tài sản trong phạm vi (trả lời bằng mốc 7 phiên kèm giới hạn); câu cụt chỉ có tên tài sản.
- Không chắc thì complex. Router chỉ đọc câu hiện tại.
- `severity_if_wrong`: `costly` = câu complex bị đưa sang simple; `cost_only` = ngược lại.

## Ngưỡng (chốt trước khi chạy, theo `docs/experiments/chatbot-router-proposal.md` mục 4)

- Đúng ≥ 27/30 và tối đa 1 lỗi `costly`.

## Quy trình

1. Không đưa bộ này cho người viết luật router trước khi luật được khóa ở một commit cụ thể.
2. Khi luật đã khóa: commit file vào `tests/router/heldout_v1.jsonl` cùng PR chạy, ghi commit của luật và SHA-256 trên.
3. Chạy một lần, báo kết quả theo ngưỡng; không sửa luật rồi chạy lại trên cùng bộ.

## Thay đổi sau duyệt của Gemini (4/11)

- Nhận: RH-003 thành bẫy từ khóa EIA + WTI (simple); RH-013 thành câu cực ngắn "Dự báo vàng" (complex); RH-014, RH-015 (gõ sai "bren"), RH-021 viết tự nhiên hơn; RH-030 thành câu hỗn hợp SJC + "bắt đáy"; RH-027 ghi rõ quy tắc kỳ hạn trên 7 phiên; RH-028 bỏ lịch sử, kiểm fallback của câu cụt.
- Không nhận: đổi RH-011 (chỉ xin tư vấn) sang complex, vì trái quyết định đã chốt ở loại A và kịch bản demo câu 5.
