# Router theo luật cho chatbot: thiết kế, kết quả và ngưỡng đề xuất

- Ngày: 25/10/2026
- Người soạn: Phước
- Người duyệt: Khải
- Trạng thái: **Chờ duyệt** (ngưỡng và các quyết định ở mục 5)
- Căn cứ: ADR-0004 mục 1 (router dùng luật, không gọi LLM; không chắc thì sang Claude Haiku 4.5)
- Code: `src/chatbot/router.py`, cụm từ ở `configs/chatbot_router.py`, test ở `tests/test_router.py`, bộ câu ở `tests/router/cases.jsonl`

## 1. Cách hoạt động

`route(question)` trả `RouteDecision(branch, rule)`: `simple` (Nova 2 Lite, không có tool) hoặc `complex` (Claude Haiku 4.5, có `get_forecast`/`get_news`), kèm tên luật đã quyết định để ghi log.

Luật xét theo thứ tự, luật đầu tiên khớp sẽ quyết định:

| # | Luật | Nhánh |
|---|---|---|
| 1 | Dự đoán trong ngày ("chiều nay", "giờ tới"…), kể cả có tên tài sản | simple |
| 1b | Ngoài phạm vi sản phẩm (xăng, vàng miếng/nhẫn, SJC, bitcoin, cổ phiếu…); nếu sau khi xóa cụm đó câu vẫn hỏi dự báo một tài sản trong phạm vi thì là câu hỗn hợp | simple / complex |
| 2 | Việc không liên quan (chuyện cười, code, dịch…) và không có tài sản | simple |
| 3 | Xin tư vấn đầu tư: kèm phân tích/dự báo/tin → complex; chỉ xin tư vấn → simple | complex / simple |
| 4 | Có tài sản và hỏi tin tức hay lý do | complex |
| 5 | Hỏi khái niệm ("là gì", "nghĩa là", "khác nhau", "có phải"…) khi không có kỳ hạn, không hỏi con số và không hỏi "dự báo" của tài sản | simple |
| 6 | Có tài sản kèm ý dự báo, kỳ hạn hoặc hỏi con số | complex |
| 7 | Không có tài sản và không có kỳ hạn: hỏi về chatbot, chào hỏi, hoặc chỉ nhắc khái niệm | simple |
| 8 | Còn lại (không chắc) | complex |

- Cụm từ viết có dấu. Câu có dấu so với cụm có dấu, nên "đầu tư" không bị nhầm thành "dầu". Câu người dùng gõ không dấu được so với bản đã bỏ dấu.
- Kỳ hạn dạng số chỉ tính 1–7 phiên, đúng các kỳ hạn của sản phẩm, để "252 phiên" (mốc thống kê) không bị hiểu là kỳ hạn.
- Câu hỏi giá hoặc dự báo cụ thể ("giá vàng ngày mai bao nhiêu") được định tuyến sang **complex**, vì cần số liệu từ tool. Nhóm `number_trap` trong benchmark chỉ kiểm tra hành vi của Nova **khi bị định tuyến nhầm**; nhãn đúng của router cho các câu đó là complex.

## 2. Bộ câu phát triển (`tests/router/cases.jsonl`)

- 83 câu mới (41 simple, 42 complex) thuộc 9 nhóm: chào hỏi và câu về chatbot, khái niệm, ngoài phạm vi, chỉ xin tư vấn, dự báo, nhiều ý, tin tức, tư vấn lồng trong phân tích, câu mơ hồ.
- Có câu không dấu, tiếng Anh, tiếng lóng, câu một từ, câu hỏi nối tiếp.
- Test bắt buộc **không trùng nguyên văn câu nào** với hai bộ benchmark chatbot. Test này đã bắt được 3 câu trùng, và các câu đó đã được viết lại.
- **Kết quả: 83/83 đúng, 0 câu cần Haiku bị đưa sang Nova.** Con số này **không phải ước lượng độ chính xác thật**, vì luật và bộ câu được viết cùng lúc, bởi cùng một người.

## 3. Phép thử trên bộ benchmark (không dùng để sửa luật)

Đã chạy router trên 120 câu của hai bộ benchmark (v1, v2). Nhãn kỳ vọng: câu bài Haiku là complex; câu bài Nova là simple, trừ nhóm `number_trap` là complex. **Không sửa luật theo kết quả này**, để nó còn là phép đo độc lập.

| Bộ | Đúng | Cần Haiku nhưng sang Nova (lỗi đắt) | Đơn giản nhưng sang Haiku (tốn thêm chi phí) |
|---|---|---|---|
| v1 | 59/60 | 0 | 1 (NOVA-026) |
| v2 | 54/60 | **2** (HAIKU2-029, HAIKU2-030) | 4 (NOVA2-004, 006, 016, 024) |

**Phân tích lỗi:**
- **HAIKU2-029, 030** ("kỳ hạn 3 phiên, nên đặt lệnh mua cái nào?", "tuần tới thế nào? … chốt lời ở mức nào?"): luật 3 chỉ coi là có phần phân tích khi có cụm như "phân tích", "so sánh", "nghiêng". Kỳ hạn và "thế nào" chưa được tính. Đây là lỗi thiết kế, sửa được theo nguyên tắc chung (mục 5, quyết định 1).
- **NOVA-026, NOVA2-016, NOVA2-024:** câu có tên tài sản kèm từ như "giá", "dự báo", nhưng thực chất hỏi phân bổ vốn, hỏi khái niệm hoặc nhờ dịch. Đi sang Haiku chỉ tốn thêm chi phí; Haiku vẫn trả lời đúng chính sách.
- **NOVA2-004** ("dự báo được giá cho 1 tháng tới không?") và **NOVA2-006** (tạm biệt kiểu "mai hỏi tiếp"): không khớp luật nào nên đi theo mặc định sang Haiku, đúng như ADR-0004 quy định khi không chắc.

## 4. Ngưỡng đề xuất (chờ Khải chốt)

1. **Bộ phát triển** (`tests/test_router.py`, chạy trong CI): độ chính xác ≥ 95% và **0** câu cần Haiku bị đưa sang Nova. Hiện đạt 100% và 0.
2. **Bộ giữ riêng (held-out):** một người **không viết luật** (đề xuất Khải) soạn khoảng 30 câu mới. Router phải đạt độ chính xác ≥ 90% và tối đa 1 câu cần Haiku bị đưa sang Nova. Bộ này mới đo được chất lượng thật của router.

## 5. Cần quyết định

1. **Sửa luật tư vấn lồng phân tích:** coi câu là tư vấn kèm phân tích (→ complex) khi có tài sản **và** có kỳ hạn hoặc hỏi con số, không chỉ khi có cụm "phân tích/so sánh". Hệ quả: câu chỉ xin chiến lược có kèm kỳ hạn ("chiến lược lướt sóng WTI tuần này") sẽ sang Haiku. Không sao, vì Haiku cũng từ chối tư vấn, chỉ tốn chi phí hơn. Đề xuất: **sửa**, vì lỗi đắt (thiếu số liệu) quan trọng hơn chi phí.
2. Ngưỡng ở mục 4, và ai soạn bộ giữ riêng.
3. Router đặt trong Lambda `api` của `POST /chat`; tên luật (`rule`) ghi vào log để theo dõi tỷ lệ định tuyến thực tế sau demo.
