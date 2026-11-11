# Router theo luật cho chatbot: thiết kế, kết quả và ngưỡng đề xuất

- Ngày: 25/10/2026
- Người soạn: Phước
- Người duyệt: Khải
- Trạng thái: **Không đạt bộ giữ riêng** (26/30, ngưỡng ≥ 90%; mục 6.1). Luật khóa ngày 4/11/2026 ở commit `984d3fe`; Khải chạy bộ giữ riêng một lần cùng ngày. `/chat` giữ mọi câu đi Haiku. Tùy chọn làm lại ở mục 6.2 **không thực hiện** (Khải chốt 10/11/2026)
- Căn cứ: ADR-0004 mục 1 (router dùng luật, không gọi LLM; không chắc thì sang Claude Haiku 4.5)
- Code: `src/chatbot/router.py`, cụm từ ở `configs/chatbot_router.py`, test ở `tests/test_router.py`, bộ câu ở `tests/router/cases.jsonl`, script chấm bộ giữ riêng ở `scripts/eval_router.py`, bộ giữ riêng ở `tests/router/heldout_v1.jsonl`, output lần chạy ở `docs/experiments/results/router-heldout-2026-11-04/eval_output.txt`
- Phạm vi: code router có trên repo để chạy lại được, nhưng **không nối vào Lambda `/chat`** (`choose_branch()` trong `src/chatbot/chat.py` vẫn trả `complex` cho mọi câu). Demo 8/11 không dùng router (Khải, PR #66)

## 1. Cách hoạt động

`route(question)` trả `RouteDecision(branch, rule)`: `simple` (Nova 2 Lite, không có tool) hoặc `complex` (Claude Haiku 4.5, có `get_forecast`/`get_news`), kèm tên luật đã quyết định để ghi log.

Luật xét theo thứ tự, luật đầu tiên khớp sẽ quyết định:

| # | Luật | Nhánh |
|---|---|---|
| 1 | Dự đoán trong ngày ("chiều nay", "giờ tới"…), kể cả có tên tài sản | simple |
| 1b | Ngoài phạm vi sản phẩm (xăng, vàng miếng/nhẫn, SJC, bitcoin, cổ phiếu…); nếu sau khi xóa cụm đó câu vẫn hỏi dự báo một tài sản trong phạm vi thì là câu hỗn hợp | simple / complex |
| 2 | Việc không liên quan (chuyện cười, code, dịch…) và không có tài sản | simple |
| 3 | Xin tư vấn đầu tư: có tài sản và kèm phân tích/dự báo/tin, kỳ hạn hoặc hỏi con số → complex; chỉ xin tư vấn → simple | complex / simple |
| 4 | Có tài sản và hỏi tin tức hay lý do | complex |
| 5 | Hỏi khái niệm ("là gì", "nghĩa là", "khác nhau", "có phải"…) khi không có kỳ hạn, không hỏi con số và không hỏi "dự báo" của tài sản | simple |
| 6 | Có tài sản kèm ý dự báo, kỳ hạn hoặc hỏi con số | complex |
| 7 | Không có tài sản và không có kỳ hạn: hỏi về chatbot, chào hỏi, hoặc chỉ nhắc khái niệm | simple |
| 8 | Còn lại (không chắc) | complex |

- Cụm từ viết có dấu. Câu có dấu so với cụm có dấu, nên "đầu tư" không bị nhầm thành "dầu". Câu người dùng gõ không dấu được so với bản đã bỏ dấu.
- Kỳ hạn dạng số chỉ tính 1–7 phiên, đúng các kỳ hạn của sản phẩm, để "252 phiên" (mốc thống kê) không bị hiểu là kỳ hạn.
- Câu hỏi giá hoặc dự báo cụ thể ("giá vàng ngày mai bao nhiêu") được định tuyến sang **complex**, vì cần số liệu từ tool. Nhóm `number_trap` trong benchmark chỉ kiểm tra hành vi của Nova **khi bị định tuyến nhầm**; nhãn đúng của router cho các câu đó là complex.

## 2. Bộ câu phát triển (`tests/router/cases.jsonl`)

- 83 câu mới (40 simple, 43 complex) thuộc 9 nhóm: chào hỏi và câu về chatbot, khái niệm, ngoài phạm vi, chỉ xin tư vấn, dự báo, nhiều ý, tin tức, tư vấn lồng trong phân tích, câu mơ hồ.
- Có câu không dấu, tiếng Anh, tiếng lóng, câu một từ, câu hỏi nối tiếp.
- Test bắt buộc **không trùng nguyên văn câu nào** với hai bộ benchmark chatbot. Test này đã bắt được 3 câu trùng, và các câu đó đã được viết lại.
- **Kết quả: 83/83 đúng, 0 câu cần Haiku bị đưa sang Nova.** Con số này **không phải ước lượng độ chính xác thật**, vì luật và bộ câu được viết cùng lúc, bởi cùng một người.
- Khi khóa luật (4/11), R-040 ("chiến lược lướt sóng WTI tuần này") đổi nhãn từ simple sang complex và chuyển sang nhóm `embedded_advice`, theo quyết định 1 ở mục 5.

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

**Sau khi sửa luật 3 theo quyết định 1 (4/11):** v1 vẫn 59/60. v2 thành 55/60, **0** câu cần Haiku bị đưa sang Nova: HAIKU2-029, 030 đã đúng, NOVA2-027 ("chiến lược lướt sóng WTI trong tuần này") chuyển sang Haiku (chỉ tốn thêm chi phí). Vì bản sửa được rút ra từ chính HAIKU2-029, 030, hai câu này **không còn là phép đo độc lập**. Bộ giữ riêng ở mục 6 mới đo được chất lượng thật.

## 4. Ngưỡng

1. **Bộ phát triển** (`tests/test_router.py`, chạy trong CI): độ chính xác ≥ 95% và **0** câu cần Haiku bị đưa sang Nova. Hiện đạt 100% và 0.
2. **Bộ giữ riêng (held-out):** Khải (**không viết luật**) soạn khoảng 30 câu mới và giữ riêng tới khi luật đã khóa. Router phải đạt độ chính xác ≥ 90% và tối đa 1 câu cần Haiku bị đưa sang Nova. Bộ này mới đo được chất lượng thật của router. Ngưỡng nằm trong `scripts/eval_router.py` (`MIN_ACCURACY`, `MAX_COMPLEX_TO_SIMPLE`).

## 5. Quyết định

1. **Sửa luật tư vấn lồng phân tích: đã sửa khi khóa luật (Phước, 4/11).** Câu xin tư vấn được coi là kèm phân tích (→ complex) khi có tài sản **và** có cụm phân tích/tin, kỳ hạn hoặc hỏi con số. Hệ quả: câu chỉ xin chiến lược có kèm kỳ hạn ("chiến lược lướt sóng WTI tuần này") sang Haiku. Không sao, vì Haiku cũng từ chối tư vấn, chỉ tốn chi phí hơn; lỗi đắt (thiếu số liệu) quan trọng hơn chi phí.
2. Ngưỡng ở mục 4; Khải phụ trách và giữ bộ giữ riêng (cách soạn ở mục 6.1).
3. **Không đưa router vào `/chat`** vì không đạt bộ giữ riêng (mục 6.1); mọi câu đi Haiku. Tùy chọn làm lại ở mục 6.2 không thực hiện (Khải chốt 10/11/2026).

## 6. Chạy bộ giữ riêng (một lần)

1. Checkout đúng commit luật đã khóa trên `exp/chatbot-router`.
2. Ghi bộ câu vào một file JSONL **ngoài repo** (không commit trước khi chạy), mỗi dòng: `{"id": "H-001", "question": "...", "expected_branch": "simple"}` (`simple` hoặc `complex`; thêm `group`, `note` tùy ý). Nhãn theo cùng quy ước mục 1: câu cần số liệu dự báo hoặc tin → `complex`.
3. Chạy: `python scripts/eval_router.py <đường dẫn file>`. Script không gọi mạng, in SHA-256 của file câu hỏi và hai file luật, độ chính xác, số câu cần Haiku bị đưa sang Nova, từng câu sai kèm tên luật, và ĐẠT/KHÔNG ĐẠT theo ngưỡng mục 4.
4. Chỉ chạy một lần, không sửa luật theo kết quả. Ghi kết quả (cả các mã SHA-256) vào tài liệu này hoặc vào PR router nếu có.

### 6.1. Kết quả lần chạy ngày 4/11/2026

Bộ 30 câu (`tests/router/heldout_v1.jsonl`, 12 simple, 18 complex) do Khải phụ trách: Claude soạn theo yêu cầu của Khải, Gemini duyệt (không mù, đã thấy nhãn), Khải chốt ngày 4/11. Người viết luật không thấy bộ câu trước khi luật khóa. Quy tắc gán nhãn và các thay đổi sau duyệt ở [`heldout_v1.md`](../../tests/router/heldout_v1.md). Khải chạy một lần trên commit `984d3fe`. Output nguyên văn: [`eval_output.txt`](results/router-heldout-2026-11-04/eval_output.txt).

| Chỉ số | Kết quả | Ngưỡng | Đạt |
|---|---:|---:|:---:|
| Độ chính xác | 26/30 (86,7%) | ≥ 90% | Không |
| Câu cần Haiku bị đưa sang Nova | 0 | ≤ 1 | Có |
| Câu đơn giản bị đưa sang Haiku | 4 | — | |

SHA-256 (nội dung đã đổi xuống dòng về LF) in trong output, đã đối chiếu khớp với commit `984d3fe`:

| File | SHA-256 |
|---|---|
| `router_heldout_v1.jsonl` (bộ câu) | `da914c2d96d72c89e2b82325d1ccea5a91eb9f9d53cde7b9235c41ed4ba663aa` |
| `src/chatbot/router.py` | `c29073a79721ab95cbd87a4d69e0e4f941da7d8a050ddaa1a3ccb1d68d0d4101` |
| `configs/chatbot_router.py` | `0f5589b2a120585b3cd53b321c3a278a1c94cc530b23dbe16ea9c7f85168cdb3` |

4 câu sai, đều là câu đơn giản bị đưa sang Haiku (chỉ tốn thêm chi phí, không câu nào mất số liệu):

| ID | Câu hỏi | Luật đã quyết định | Vì sao sai |
|---|---|---|---|
| RH-003 | Tại sao hệ thống lại dùng tin của EIA khi nói về dầu WTI? | `news` (luật 4) | "tại sao" + tài sản bị hiểu là hỏi lý do biến động giá, thực ra hỏi về cách hệ thống hoạt động |
| RH-004 | Pinball loss là cái gì vậy? | `default_uncertain` (luật 8) | "là cái gì" và "pinball loss" không có trong danh sách cụm khái niệm |
| RH-007 | GLD là quỹ gì, sao lại dùng để dự báo vàng? | `forecast` (luật 6) | Có tài sản và chữ "dự báo" nên luật khái niệm bị bỏ qua |
| RH-012 | Viết giúp mình một bài thơ về mùa thu | `default_uncertain` (luật 8) | "bài thơ" không có trong danh sách việc không liên quan |

**Router không đạt.** Không sửa luật rồi chấm lại trên bộ này: bộ đã được xem, chấm lại sẽ cho kết quả lạc quan. Kết quả cũng cho thấy 100% trên bộ phát triển là quá lạc quan, đúng như cảnh báo ở mục 2.

### 6.2. Tùy chọn sau kết quả (không thực hiện)

**Không thực hiện (Khải chốt 10/11/2026):** ưu tiên official v4 13–14/11 và đổi prompt trước 18/11; `/chat` giữ mọi câu đi Haiku.

Lý do: lần chạy 4/11 có 4 câu sai, đều là câu đơn giản bị đưa sang Haiku (RH-003, RH-004, RH-007, RH-012), và 0 câu cần Haiku bị đưa sang Nova (mục 6.1). Vì vậy cho mọi câu đi Haiku chỉ tốn thêm chút chi phí, không mất chất lượng hay số liệu.

Các tùy chọn đã cân nhắc (giữ lại làm dấu vết):

Nếu nhóm còn thời gian:

1. Sửa luật, chỉ dựa trên bộ phát triển (có thể thêm câu dev mới cùng loại lỗi, do người viết luật tự soạn, không chép từ `heldout_v1`).
2. Một người **chưa đọc luật** soạn bộ giữ riêng **mới**, giữ ngoài repo tới khi luật mới khóa.
3. Chạy một lần trước **18/11** với cùng ngưỡng ở mục 4.
4. Đạt thì đưa router vào `/chat` trước khi đóng băng code **22/11**; không đạt hoặc không kịp thì giữ mọi câu đi Haiku.

`heldout_v1` từ nay chỉ là bằng chứng của lần chạy này, không dùng để đo luật mới.
