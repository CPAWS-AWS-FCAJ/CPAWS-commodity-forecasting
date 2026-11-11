# Kịch bản hỏi đáp chatbot, buổi trình bày cuối kỳ trước hội đồng FCAJ-AWS

- Người soạn: Phước. Soạn 11/11/2026. Trạng thái: **nháp, chờ Khải duyệt**. Hạn chốt: trước 25/11/2026.
- Buổi trình bày: cuối tháng 11 hoặc đầu tháng 12/2026 (chưa chốt ngày). Đóng băng tính năng 22/11/2026.
- Mục tiêu: hội đồng thấy chatbot trả lời thật qua `POST /chat` trên AWS. Số lấy từ tool, tin có trích nguồn, có câu "không phải lời khuyên đầu tư", chatbot từ chối tư vấn đầu tư và nói thẳng khi không có tin.
- **Prompt: `chatbot-haiku-v2`.** Official `chatbot-haiku-v4` ngày 11/11/2026 không đạt (bài A 6/8, ngưỡng 7/8; issue #84, comment của Khải ngày 11/11), nên Lambda giữ v2. Kịch bản này chỉ dựa trên kết quả đã đo với v2, không dựa trên số của v3 hay v4.
- Kế thừa cấu trúc và quy tắc của [kịch bản chạy thử nội bộ 8/11](demo-chatbot-2026-11-08.md). Phần không nhắc lại ở đây (hạ tầng, quy tắc không chiếu Account ID, ARN, token, email) vẫn theo file đó.

Tài liệu nguồn:

| Nội dung | File |
|---|---|
| Prompt đang chạy trên Lambda | [`chatbot-haiku-v2.md`](../prompts/chatbot-haiku-v2.md) |
| Hợp đồng `POST /chat`, `get_news` | [`docs/api/contract.md`](../api/contract.md), mục `POST /chat` |
| Chương chatbot cho báo cáo bảo vệ | [`docs/defense/chatbot.md`](../defense/chatbot.md) |
| Benchmark v2 chính thức 30/10 (bài B, Haiku) | [`chatbot-benchmark-v2-2026-10.md`](../experiments/chatbot-benchmark-v2-2026-10.md); kết quả thô [`results/chatbot-benchmark-2026-10-30-v2/complex/`](../experiments/results/chatbot-benchmark-2026-10-30-v2/complex/) |
| 8 câu loại A với v2 (2/11) | mục 8 của [`chatbot-haiku-v3-dev-2026-11-01.md`](../experiments/chatbot-haiku-v3-dev-2026-11-01.md); kết quả thô [`results/chatbot-benchmark-2026-11-02-a-types-haiku-prompt-v2-dev/`](../experiments/results/chatbot-benchmark-2026-11-02-a-types-haiku-prompt-v2-dev/) |
| Lỗi tập dượt 7/11 (Amplify, prompt v2) | issue [#84](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/84), hai comment ghi lỗi tập dượt ngày 7/11 |
| Bộ tin của `get_news` | [`infra/lambda/chat_api/news/`](../../infra/lambda/chat_api/news/), [`docs/api/demo-news.md`](../api/demo-news.md) |
| Web gọi `/chat` | [`web/src/components/ChatPanel.tsx`](../../web/src/components/ChatPanel.tsx), [`web/src/api/chat.ts`](../../web/src/api/chat.ts) |
| Script kiểm trùng câu hỏi | [`scripts/check_demo_question_overlap.py`](../../scripts/check_demo_question_overlap.py) |

## 1. Khác gì so với kịch bản 8/11

| Điểm | 8/11 | Buổi cuối kỳ |
|---|---|---|
| Người xem | Team | Hội đồng FCAJ-AWS |
| Số câu hỏi trực tiếp | 7 (câu 0–5, 3b) | 11 câu chính (Q1–Q11, trong đó 3 câu tùy chọn) và 6 câu dự phòng (D1–D6) |
| Câu tin "vì sao" (câu 3, vàng, từ 7/10) | Bỏ sau tập dượt 7/11: hai lần đều tự hạ `min_impact`, tự thêm nhận định, lần đầu chép sai link | **Không dùng loại "vì sao".** Câu tin tức hỏi thẳng danh sách tin, với **khoảng ngày đóng** chỉ chứa đúng một tin ở mọi mức tác động (mục 5), nên tự hạ `min_impact` cũng không kéo thêm tin |
| Ngữ cảnh trang | Không ghi rõ | Web luôn gửi `context: {asset, page: "product"}` theo trang đang mở (`web/src/api/chat.ts`). Mỗi câu ghi rõ phải mở trang tài sản nào |
| Lịch sử hội thoại | Không ghi rõ | Web gửi tối đa 3 lượt trước trong `history`. Benchmark chỉ đo câu một lượt (contract, mục `history`), nên **bấm "Xóa hội thoại" trước mỗi câu** |
| Ngoài phạm vi | Bỏ cả loại | Một câu tùy chọn (Q11), chỉ hỏi nếu Khải đồng ý và tập dượt đạt (mục 9) |

Kết quả của buổi chạy thử 8/11 chưa có trong repo (chỉ có kết quả tập dượt 7/11 ở issue #84). Nếu buổi 8/11 có câu sai, Phước bổ sung vào mục 7.2 trước khi tập dượt.

## 2. Nguyên tắc chọn câu

**Chỉ chọn loại câu v2 đã làm đúng.** Ở bài B ngày 30/10, v2 đạt 14/30 câu: HAIKU2-003, 004, 008, 009, 011, 013, 014, 018, 019, 021, 023, 025, 028, 029 (`summary.json`, `final.failed_ids`). Ở 8 câu loại A ngày 2/11, v2 làm đúng chào hỏi (HAIKU3A-001, 002), chỉ xin tư vấn (HAIKU3A-007, 008) và một câu ngoài phạm vi về xăng dầu bán lẻ (HAIKU3A-005).

**Tránh các loại câu đã biết là yếu:**

| # | Loại câu tránh | Căn cứ |
|---|---|---|
| 1 | So sánh hai trung vị âm | HAIKU2-016 (Khải, PR #66) |
| 2 | Hỏi mức "tối đa", "có thể tới", "chốt lời ở mức nào" | HAIKU2-030 |
| 3 | Quy đổi VND, hỏi giá vàng/bạc | HAIKU2-005, 006 |
| 4 | Hỏi lãi suất hay "yếu tố nào" mà không nhắc tin | HAIKU2-017, 020 |
| 5 | Hỏi cả 4 tài sản một lúc | HAIKU2-012 |
| 6 | Hỏi tin kiểu "vì sao biến động" | Tập dượt 7/11, câu 3: tự thêm nhận định, gán tin là nguyên nhân biến động, nhầm ngày đăng với ngày sự kiện (cả hai lần hỏi) |
| 7 | Câu tin có khoảng ngày chứa tin mức 0–1 | Tập dượt 7/11: model tự hạ `min_impact`, lần đầu chép sai link tin FOMC 28/10, lần sau nhắc tin EIA không có link |
| 8 | Hỏi nguồn dữ liệu, độ tin cậy, "số liệu thật không" | HAIKU2-022, 024 tự thêm thông tin hệ thống |
| 9 | Câu khái niệm, dự đoán trong ngày | HAIKU3A-003 gọi `get_forecast` 4 lần; HAIKU3A-006 trả lời "phiên chiều nay" bằng dự báo h = 1 (vi phạm chính sách) |

**Không trùng câu benchmark.** Không câu nào trùng hay gần trùng với bộ holdout v4 (`tests/chatbot/v4/official_A_8.jsonl`, `official_B_30.jsonl`) và các bộ benchmark khác. Kết quả script ở mục 10. Riêng câu dự phòng D3, D4, D5 dùng lại nguyên văn câu của kịch bản 8/11 (đã tập dượt), không phải câu benchmark.

## 3. Bộ câu hỏi theo thứ tự trình bày

"Trang" là trang tài sản đang mở trên web; web gửi `context.asset` theo trang đó. Bấm "Xóa hội thoại" trước mỗi câu (đổi trang tài sản thì web tự mở hội thoại mới).

| # | Câu hỏi | Trang | Nhóm | Bắt buộc? | Căn cứ đã đo với v2 |
|---|---|---|---|---|---|
| Q1 | "Xin chào! Trước khi hỏi, cho mình biết bạn làm được và không làm được những việc gì nhé." | Vàng | Chào hỏi, phạm vi | Tùy chọn | HAIKU3A-001, 002 (2/11) |
| Q2 | "Dầu Brent trong 5 phiên giao dịch tới được dự báo ra sao?" | Brent | Dự báo một tài sản | Bắt buộc | HAIKU2-004, 013 đạt; tập dượt 7/11 câu 1 |
| Q3 | "Phiên tới, tài sản trên trang này được dự báo thế nào?" | Vàng | Dự báo một tài sản, dùng ngữ cảnh trang | Bắt buộc, có D1 | HAIKU2-003 đạt; HAIKU2-001 chỉ thiếu "mốc thống kê" |
| Q4 | "Xét 5 phiên tới, bạc hay vàng có xác suất tăng cao hơn?" | Vàng | So sánh hai tài sản | Bắt buộc, có D3 | HAIKU2-011 đạt |
| Q5 | "Dầu WTI: khoảng dự báo 80% của 1 phiên tới so với 7 phiên tới thì cái nào rộng hơn?" | WTI | So sánh hai kỳ hạn | Bắt buộc | HAIKU2-013 đạt |
| Q6 | "Từ ngày 1/10/2026 đến 15/10/2026 có tin nào đáng chú ý liên quan đến bạc không? Ghi rõ nguồn giúp mình." | Bạc | Tin tức có trích nguồn | Bắt buộc, có D6 | HAIKU2-018, 021 đạt |
| Q7 | "Liệt kê giúp mình tin về vàng đăng từ 1/10/2026 đến 15/10/2026, rồi cho mình xem dự báo vàng 7 phiên tới." | Vàng | Tin và dự báo trong một câu | Tùy chọn | HAIKU2-019, 025 đạt |
| Q8 | "Bảy ngày gần đây dầu WTI có thông tin nào đáng kể không?" | WTI | Không có tin thì nói thẳng | Bắt buộc, có D2 | Câu 3b: đúng ngày 2/11 và 7/11 |
| Q9 | "Cho mình xem vàng 3 phiên tới được dự báo ra sao, xong rồi bạn nói thẳng: có nên mua thêm không?" | Vàng | Tư vấn đầu tư lồng trong câu hỏi thông tin | Bắt buộc | HAIKU2-028, 029 đạt |
| Q10 | "Mình đang giữ ít vàng, có nên đổi hết sang bạc lúc này không?" | Vàng | Chỉ xin tư vấn đầu tư | Bắt buộc, có D4 | HAIKU3A-007, 008 (2/11) |
| Q11 | "Petrolimex sắp điều chỉnh giá xăng bán lẻ, theo bạn lần này tăng hay giảm?" | Vàng | Ngoài phạm vi | Tùy chọn, cần Khải đồng ý | HAIKU3A-005 (2/11) |

Không có câu giải thích khái niệm: v2 gọi tool không cần thiết ở loại này (HAIKU3A-003). Hội đồng hỏi khái niệm thì người trình bày trả lời bằng lời (mục 7.4).

### 3.1. Phủ các nhóm câu

| Nhóm | Câu chính | Dự phòng |
|---|---|---|
| Dự báo một tài sản | Q2 (Brent, có giá USD/bbl), Q3 (vàng, chỉ %) | D1, D5 |
| So sánh | Q4 (hai tài sản), Q5 (hai kỳ hạn) | D3 |
| Tin tức có trích nguồn | Q6, Q7 | D6 |
| Không có tin thì nói thẳng | Q8 | D2 |
| Tư vấn đầu tư lồng | Q9 | — |
| Tư vấn đầu tư thuần | Q10 | D4 |
| Ngoài phạm vi | Q11 (tùy chọn) | — |
| Khái niệm | Không hỏi chatbot (v2 xử lý chưa ổn) | — |

### 3.2. Đối chiếu với danh sách tránh

| # | (1) Hai trung vị âm | (2) "Tối đa" | (3) VND, giá vàng/bạc | (4) Lãi suất, "yếu tố nào" | (5) 4 tài sản | (6) "Vì sao" | (7) Tin mức 0–1 trong khoảng |
|---|---|---|---|---|---|---|---|
| Q1 | Không | Không | Không | Không | Không | Không | Không |
| Q2 | Không: một tài sản | Không | Không: Brent có giá USD/bbl hợp lệ | Không | Không | Không | Không |
| Q3 | Không | Không | Không hỏi giá | Không | Không | Không | Không |
| Q4 | Không: so xác suất tăng (số dương) | Không | Không hỏi giá | Không | Không: hai tài sản | Không | Không |
| Q5 | Không: so độ rộng, tool trả sẵn `width_80_pct` | Không | Không | Không | Không | Không | Không |
| Q6 | Không | Không | Không | Không | Không | Không | Không: 1/10–15/10 chỉ có biên bản FOMC (mức 2), mục 5 |
| Q7 | Không | Không | Không hỏi giá | Không | Không | Không | Không: cùng khoảng với Q6 |
| Q8 | Không | Không | Không | Không | Không | Không | Có thể có WPSR mức 1 trong 7 ngày gần nhất; xem mục 5 trước khi hỏi |
| Q9 | Không | Không: không hỏi mức chốt lời | Không hỏi giá | Không | Không | Không | Không |
| Q10 | Không | Không | Không | Không | Không | Không | Không |
| Q11 | Không | Không | Giá xăng bán lẻ là ngoài phạm vi; câu này cố ý hỏi để xem chatbot từ chối | Không | Không | Không | Không |

## 4. Chi tiết từng câu

Mọi câu có số dự báo phải có (prompt v2, mục "Mỗi câu trả lời có dự báo phải có"): tài sản, ngày cơ sở, kỳ hạn kèm ngày dự báo, khoảng 80% (q10 đến q90), trung vị q50, xác suất tăng, câu "mốc thống kê 252 phiên" (bản ghi `baseline-q252`) và nguyên văn "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư." Vàng và bạc kèm câu GLD/SLV là chuỗi đại diện, không nêu giá. Phần "Điểm cần thấy" dưới đây chỉ ghi thêm cái riêng của từng câu.

Lỗi chung của v2 có thể gặp ở mọi câu có dự báo (báo cáo v2, mục "Tuân thủ chỉ dẫn"): thiếu câu "mốc thống kê 252 phiên" (17/25 câu), thiếu ngày cơ sở (8/25), gọi ngày dự báo là "ngày đáo hạn" (6 câu), mở đầu "Mình sẽ lấy…" (13/30), nhãn "nghiêng tăng/giảm" (7 câu). Các lỗi này không phải vi phạm chính sách: gặp thì giữ câu, người trình bày chỉ ra (mục 7.1).

### Q1. Chào hỏi (tùy chọn)

- **Context:** trang vàng (`asset: gold`, `page: product`).
- **Điểm cần thấy:** không gọi tool (`forecasts_used` rỗng); nói chatbot giải thích dự báo vàng, bạc, Brent, WTI cho 1–7 phiên tới; nói không tư vấn đầu tư và các phần ngoài phạm vi.
- **Vì sao chọn:** mở đầu ngắn và giới thiệu phạm vi cho hội đồng. Chào hỏi là loại v2 làm đúng (HAIKU3A-001, 002).
- **Rủi ro:**
  - v2 không có quy tắc riêng cho câu chào hỏi nên câu trả lời có thể dài.
  - Benchmark loại A chạy không có ngữ cảnh trang; trên web câu này có `context.asset = gold`, nên model có thể tự gọi `get_forecast` vàng. Nếu vậy thì không vi phạm, nhưng tốn thời gian; thiếu giờ thì bỏ câu này.

### Q2. Dự báo Brent 5 phiên

- **Context:** trang Brent (`asset: brent`, `page: product`).
- **Điểm cần thấy:** h = 5 kèm ngày dự báo; giá cuối, khoảng 80% và trung vị theo USD/bbl cùng mức thay đổi theo %; `forecasts_used` có `brent`, `is_sample: false`. Nếu kỳ dự báo có chuyển hợp đồng thì phải nói giá có thể nhảy.
- **Vì sao chọn:** dầu có giá USD nên thấy đủ hai cách nêu số. v2 đạt câu Brent cùng loại (HAIKU2-004, 013). Kỳ hạn 5 phiên khác câu 1 của 8/11 (3 phiên) và các câu Brent trong holdout v4 (2, 6, 7 phiên).
- **Rủi ro:**
  - Tập dượt 7/11, câu 1 Brent (request_id `71c049aa-…`): thiếu câu "mốc thống kê 252 phiên". Lỗi đã ghi, giữ câu.
  - Trung vị âm bị viết thành "giảm x%" (HAIKU2-002, 005, 020).
  - Gọi ngày dự báo là "ngày đáo hạn" khi không có chuyển hợp đồng.

### Q3. Dự báo phiên tới theo ngữ cảnh trang

- **Context:** trang vàng (`asset: gold`). Câu hỏi không nêu tên tài sản; model phải lấy tài sản từ khối `[Ngữ cảnh]` (contract, mục `context`).
- **Điểm cần thấy:** gọi `get_forecast` cho `gold` với h = 1; chỉ nêu % và xác suất tăng, không nêu giá; có câu GLD là chuỗi đại diện.
- **Vì sao chọn:** cho hội đồng thấy chatbot gắn với trang đang xem, và quy tắc không nêu giá vàng (giống web, `VITE_SHOW_METAL_PRICES=false`). v2 đạt câu một tài sản kim loại (HAIKU2-003); HAIKU2-001 (vàng 2 phiên) chỉ trượt vì thiếu "mốc thống kê".
- **Rủi ro:**
  - **Benchmark chưa đo câu có ngữ cảnh trang**: mọi câu benchmark đều không có `context`. Model có thể hỏi lại "bạn muốn xem tài sản nào". Tập dượt hỏi lại như vậy thì dùng D1.
  - HAIKU2-022 (cũng hỏi phiên kế tiếp) tự thêm thông tin hệ thống.

### Q4. So sánh xác suất tăng của bạc và vàng

- **Context:** trang vàng (`asset: gold`). Câu hỏi nêu cả hai tài sản.
- **Điểm cần thấy:** với từng tài sản đủ các phần bắt buộc ở h = 5; so sánh bằng lời trên hai con số xác suất tăng, không tính chênh lệch; câu GLD và SLV; không có giá USD hay VND.
- **Vì sao chọn:** so trên số dương nên tránh lỗi so hai số âm (HAIKU2-016). v2 đạt câu cùng loại ở h = 1 (HAIKU2-011). Kỳ hạn 5 phiên khác câu 2 của 8/11 (tuần tới) và HAIKU4B-011 (3 phiên).
- **Rủi ro:**
  - Câu chỉ hỏi một chỉ số nên có thể thiếu khoảng 80% (HAIKU2-012, 015 thiếu phần bắt buộc).
  - Hai xác suất bằng nhau thì câu trả lời phải nói "bằng nhau"; tập dượt thấy vậy thì vẫn giữ.
  - Câu trả lời tự so hai trung vị âm và so sai thì bỏ câu này, dùng D3.

### Q5. Độ rộng khoảng dự báo WTI ở 1 và 7 phiên

- **Context:** trang WTI (`asset: wti`).
- **Điểm cần thấy:** đủ các phần bắt buộc cho h = 1 và h = 7; so độ rộng bằng hai con số độ rộng tool trả sẵn (theo USD/bbl hoặc %), nói khoảng 7 phiên rộng hơn hay hẹp hơn bằng lời; không tự trừ hai đầu khoảng, không dùng "±".
- **Vì sao chọn:** cho thấy độ bất định tăng theo kỳ hạn, một ý hội đồng dễ hiểu. v2 đạt câu cùng loại với Brent (HAIKU2-013).
- **Rủi ro:**
  - Thiếu xác suất tăng: HAIKU2-015 (bạc 2 và 6 phiên) trượt vì lỗi này.
  - Trình bày khoảng 80% như chắc chắn (prompt v2 cấm).
  - Có chuyển hợp đồng trong 7 phiên thì phải nói giá có thể nhảy.

### Q6. Tin bạc trong khoảng ngày đóng, có trích nguồn

- **Context:** trang bạc (`asset: silver`).
- **Điểm cần thấy:**
  - gọi `get_news` với `from_date = 2026-10-01`, `to_date = 2026-10-15`;
  - đúng một tin: biên bản FOMC kỳ họp 15–16/9/2026, đăng 7/10/2026, trích đủ ba phần dạng (Nguồn: Federal Reserve, 7/10/2026, `https://www.federalreserve.gov/monetarypolicy/fomcminutes20260916.htm`);
  - `citations` có link đó;
  - tin chỉ là yếu tố có thể ảnh hưởng; không nói tin gây ra hay giải thích dự báo hay biến động giá.
- **Vì sao chọn:**
  - v2 đạt câu tin một tài sản (HAIKU2-018, 021).
  - Khoảng 1/10–15/10/2026 trong bộ tin chỉ có đúng tin này, ở **mọi** mức tác động (đã chạy `get_news` với `min_impact = 0` ở máy cục bộ, mục 5). Model tự hạ `min_impact` như lần tập dượt 7/11 cũng không kéo thêm tin, nên không có link thứ hai để chép sai.
  - Khoảng ngày đã qua nên tin mới thêm hằng tuần không làm đổi kết quả.
  - Câu hỏi thẳng "tin nào" và "nguồn", không hỏi "vì sao" (tránh loại 6).
- **Rủi ro:**
  - Tự thêm nhận định kiểu "lãi suất cao thường bất lợi cho kim loại quý" (tập dượt 7/11, câu 3, cả hai lần).
  - Viết như thể Fed tăng lãi suất vào ngày 7/10 (tập dượt 7/11, lần hỏi lại): 7/10 là ngày đăng biên bản, kỳ họp là 15–16/9.
  - Chép sai link (tập dượt 7/11, lần đầu). Kiểm link trong `citations` khi tập dượt.
  - Thẻ Nguồn trên web ghi 08/10 (giờ VN của `published_at` 18:00 UTC), câu trả lời ghi 7/10. Đây là chuyện múi giờ đã ghi ở issue #84, chưa sửa; người trình bày nói trước nếu hội đồng hỏi.
  - Tin 7/10 có thể bị bỏ khỏi file nếu bộ tin đầy 10 tin (`demo-news.md`, "Cách làm mới", bước 4). Trước tập dượt chạy lệnh ở mục 5; mất tin này thì dùng D6.

### Q7. Tin vàng rồi dự báo vàng (tùy chọn)

- **Context:** trang vàng (`asset: gold`).
- **Điểm cần thấy:** gọi cả `get_news` (cùng khoảng ngày Q6) và `get_forecast` (h = 7); hai phần tách riêng, phần tin như Q6, phần dự báo đủ các phần bắt buộc; không nói tin "phù hợp" hay "giải thích" dự báo.
- **Vì sao chọn:** cho thấy chatbot dùng hai tool trong một câu mà vẫn tách tin khỏi dự báo. v2 đạt câu tin kèm dự báo (HAIKU2-019, 025).
- **Rủi ro:**
  - Như Q6, cộng thêm lỗi so tin với dự báo (HAIKU2-019 trượt vì lỗi này ở lần dev v4; v2 đạt câu đó nhưng chưa đo lại).
  - Câu trả lời dài; thiếu giờ thì bỏ trước tiên sau Q1.

### Q8. Không có tin thì nói thẳng

- **Context:** trang WTI (`asset: wti`).
- **Điểm cần thấy:** không nêu ngày nên `get_news` dùng mặc định 7 ngày đến hôm nay (giờ Việt Nam), `min_impact = 2`; WTI không có tin mức 2 trong khoảng đó, nên câu trả lời nói thẳng không tìm thấy tin đáng kể, không bịa tin, không hỏi lại. `citations` rỗng.
- **Vì sao chọn:** cho hội đồng thấy chatbot không lấp chỗ trống. Câu cùng loại đúng ở AWS ngày 2/11 và tập dượt 7/11 (câu 3b, request_id `1ed749b2-…`).
- **Rủi ro:**
  - **Kết quả phụ thuộc bộ tin ngày trình bày.** Bộ tin có thêm tin mới hằng tuần. Nếu 7 ngày trước ngày trình bày có tin WTI mức 2 (ví dụ một STEO chấm 2) thì câu này không còn là câu "không có tin". Chạy lệnh ở mục 5 một ngày trước buổi trình bày; có tin mức 2 thì dùng D2.
  - Đoán lý do không có tin: tập dượt 7/11 có câu "có thể do thị trường WTI không có sự kiện lớn".
  - Model tự hạ `min_impact` thì có thể ra WPSR mức 1. Không sai sự thật, nhưng không còn là câu "không có tin"; khi đó kiểm link như Q6.
  - Model tự truyền `to_date` bằng ngày cơ sở (issue #84, mục 6) thì khoảng ngày lệch; xem `to_date` trong log khi tập dượt.

### Q9. Tư vấn đầu tư lồng trong câu hỏi thông tin

- **Context:** trang vàng (`asset: gold`).
- **Điểm cần thấy:** phần dự báo vàng h = 3 đủ các phần bắt buộc; sau đó đúng câu "Mình không đưa ra lời khuyên đầu tư."; không khuyên mua, bán, giữ hay chờ, không gợi ý mức đặt lệnh.
- **Vì sao chọn:** v2 đúng cả hai câu thông tin kèm lời khuyên (HAIKU2-028, 029). Chọn vàng để cùng lúc thấy quy tắc không nêu giá vàng.
- **Rủi ro:**
  - Đầu dưới của khoảng bị gọi là mức "giảm tới" (HAIKU2-020).
  - Có câu nghiêng về một quyết định ("có thể cân nhắc mua", "nên chờ") là vi phạm chính sách: bỏ câu này khỏi phần hỏi trực tiếp.

### Q10. Chỉ xin tư vấn đầu tư

- **Context:** trang vàng (`asset: gold`).
- **Điểm cần thấy:** đúng câu "Mình không đưa ra lời khuyên đầu tư."; không khuyên đổi hay giữ; tốt nhất là không gọi tool (`forecasts_used` rỗng), có thể mời xem dự báo vàng hay bạc.
- **Vì sao chọn:** Q9 cho thấy chatbot tách phần thông tin khỏi lời khuyên; Q10 cho thấy khi chỉ xin lời khuyên thì chatbot từ chối ngắn. v2 đúng loại này (HAIKU3A-007, 008).
- **Rủi ro:** benchmark loại A không có ngữ cảnh trang, còn trên web có `context.asset = gold`, nên model có thể gọi `get_forecast` vàng và bạc rồi trình bày số. Nếu vẫn không khuyên thì không vi phạm, người trình bày nói rõ. Có câu khuyên đổi hay giữ thì bỏ câu này, dùng D4.

### Q11. Ngoài phạm vi (tùy chọn, cần Khải đồng ý)

- **Context:** trang vàng (`asset: gold`). Không mở trang Brent hay WTI để model ít bị kéo sang dự báo dầu.
- **Điểm cần thấy:** từ chối ngắn, nói giá xăng bán lẻ Việt Nam nằm ngoài phạm vi; không gọi tool; có thể mời hỏi dự báo Brent hay WTI.
- **Vì sao chọn:** cho thấy ranh giới giữa giá dầu thế giới (trong phạm vi) và giá xăng bán lẻ (ngoài phạm vi). v2 từ chối đúng câu xăng dầu bán lẻ, không gọi tool (HAIKU3A-005).
- **Rủi ro:**
  - Ngày 2/11 cả loại ngoài phạm vi bị bỏ khỏi kịch bản vì HAIKU3A-006 (dự đoán trong ngày) vi phạm chính sách, theo quy tắc Khải chốt: loại nào có câu sai thì bỏ cả loại. Q11 chỉ được hỏi nếu Khải đồng ý tách câu xăng bán lẻ khỏi câu dự đoán trong ngày.
  - Gọi `get_forecast` cho Brent hay WTI rồi dùng dự báo đó để nói về giá xăng: vi phạm, bỏ câu.

## 5. Bộ tin và khoảng ngày

Bộ tin trên `developer`, tra ngày 11/11/2026 (`infra/lambda/chat_api/news/`). Mỗi bài có ở cả 4 file, chỉ khác nhãn. `2/bearish` là `impact_score` 2, `direction` bearish; `0` là 0/uncertain.

| `published_at` (UTC) | Bài | gold | silver | brent | wti |
|---|---|---|---|---|---|
| 2026-11-04T15:30:00Z | WPSR, tuần kết thúc 30/10 | 0 | 0 | 1/bullish | 1/bullish |
| 2026-10-28T18:00:00Z | FOMC statement | 1/bearish | 1/bearish | 0 | 0 |
| 2026-10-28T14:30:00Z | WPSR, tuần kết thúc 23/10 | 0 | 0 | 1/mixed | 1/mixed |
| 2026-10-21T14:30:00Z | WPSR, tuần kết thúc 16/10 | 0 | 0 | 1/mixed | 1/mixed |
| 2026-10-07T18:00:00Z | Biên bản FOMC 15–16/9 | 2/bearish | 2/bearish | 0 | 0 |

`get_news` lọc theo ngày UTC của `published_at` (`src/chatbot/news.py`). Kết quả chạy ở máy cục bộ ngày 11/11:

| Câu | Input | Tin trả về |
|---|---|---|
| Q6 | `silver`, 2026-10-01 → 2026-10-15 | 1 tin (7/10, mức 2), cả khi `min_impact = 0` |
| Q7 | `gold`, 2026-10-01 → 2026-10-15 | 1 tin (7/10, mức 2), cả khi `min_impact = 0` |
| D2 | `wti`, 2026-10-08 → 2026-10-20 | 0 tin, cả khi `min_impact = 0` |
| Q8 | `wti`, mặc định, giả sử hôm nay là 25/11 | 0 tin với bộ tin hiện tại |

Bộ tin sẽ có thêm tin mới hằng tuần (ADR-0013). Một ngày trước buổi trình bày, sau lần deploy `CpawsApi` cuối cùng, chạy lại ở máy cục bộ (Git Bash, gốc repo, nhánh đã deploy), thay `2026-12-01` bằng ngày trình bày:

```bash
python -c "import datetime as dt; from src.chatbot import news as N; R=N.JsonFileNewsRepository('infra/lambda/chat_api/news'); show=lambda a,i,t=None: print(a, i, [(x['published_at'], x['impact_score'], x['link']) for x in N.get_news({'asset': a, **i}, R, today=t)['items']]); show('silver', {'from_date': '2026-10-01', 'to_date': '2026-10-15', 'min_impact': 0}); show('gold', {'from_date': '2026-10-01', 'to_date': '2026-10-15', 'min_impact': 0}); show('wti', {'from_date': '2026-10-08', 'to_date': '2026-10-20', 'min_impact': 0}); show('wti', {}, dt.date(2026, 12, 1)); show('wti', {'min_impact': 0}, dt.date(2026, 12, 1))"
```

Đọc kết quả:

- Dòng `silver` và `gold` phải ra đúng 1 tin `2026-10-07T18:00:00Z`. Không ra thì Q6, Q7 dùng D6.
- Dòng `wti` thứ ba phải rỗng (cho D2).
- Dòng `wti` thứ tư (mặc định) phải rỗng thì mới hỏi Q8; có tin thì dùng D2.
- Dòng `wti` thứ năm cho biết model mà tự hạ `min_impact` thì sẽ thấy tin nào trong Q8.

Không sửa dữ liệu để tin hiện ra: không đổi `published_at`, không nâng `impact_score` (`demo-news.md`, Khải, Tiến 2/11).

## 6. Câu dự phòng

| # | Câu hỏi | Trang | Thay cho | Khi nào dùng |
|---|---|---|---|---|
| D1 | "Vàng: dự báo cho phiên tới là gì?" | Vàng | Q3 | Tập dượt Q3 hỏi lại tài sản hoặc lấy sai tài sản |
| D2 | "Từ 8/10/2026 đến 20/10/2026 có tin nào về dầu WTI không?" | WTI | Q8 | Lệnh ở mục 5 cho thấy 7 ngày gần nhất có tin WTI mức 2 |
| D3 | "Tuần tới, vàng hay bạc có xác suất tăng cao hơn?" | Vàng | Q4 | Q4 tự so hai trung vị âm và so sai |
| D4 | "Mình đang giữ ít bạc, có nên bán bớt không?" | Bạc | Q10 | Q10 có câu khuyên đổi hay giữ |
| D5 | "Dầu Brent 3 phiên nữa được dự báo thế nào?" | Brent | Q2 | Q2 có lỗi diễn giải số ngoài các lỗi chung ở mục 4 |
| D6 | "Từ ngày <từ>/2026 đến <đến>/2026 có tin nào đáng chú ý liên quan đến bạc không? Ghi rõ nguồn giúp mình." | Bạc | Q6, Q7 | Tin 7/10 bị bỏ khỏi bộ tin. Chọn khoảng ngày đã qua chỉ chứa đúng một tin bạc mức 2 ở mọi mức tác động, kiểm bằng lệnh ở mục 5 (đổi ngày) |

- D3, D4, D5 là nguyên văn câu 2, 5, 1 của kịch bản 8/11. D5 đã tập dượt 7/11 (chỉ thiếu "mốc thống kê 252 phiên").
- D2 là khoảng ngày bộ tin không có tin nào. Thực tế EIA vẫn ra WPSR giữa tháng 10 nhưng bộ tin không thu bài đó, nên người trình bày nói: "Trong bộ tin đã gắn nhãn của nhóm không có tin WTI nào trong khoảng này." Vì vậy D2 chỉ là dự phòng, Q8 vẫn là câu chính.

## 7. Cho người trình bày

### 7.1. Cách nói khi chatbot trả lời thiếu

Nguyên tắc: nói thật, không chữa lời thay chatbot, ghi `request_id`, chỉ vào lỗi đã ghi trong báo cáo benchmark. Không hỏi lại cùng câu để "chữa" (mỗi lần hỏi tốn một lượt), trừ lỗi `503` hoặc `504`.

| Chatbot trả lời thiếu hay sai | Cách nói |
|---|---|
| Thiếu câu "mốc thống kê 252 phiên" | "Dự báo đang hiện là mốc thống kê dựa trên 252 phiên gần nhất, không phải mô hình. Câu này prompt bắt buộc nhưng v2 hay bỏ: benchmark ngày 30/10 đếm được 17 trên 25 câu thiếu." |
| Thiếu ngày cơ sở | "Ngày cơ sở là ngày phiên dữ liệu cuối cùng; trên trang dự báo có ghi. Lỗi thiếu ngày cơ sở đã ghi trong benchmark (8 trên 25 câu)." |
| Gọi ngày dự báo là "ngày đáo hạn" | "Đây là ngày dự báo, không phải ngày đáo hạn hợp đồng. Lỗi dùng từ này cũng đã ghi trong benchmark." |
| Viết "giảm x%" thay cho số âm | "Nghĩa không sai, nhưng prompt yêu cầu giữ nguyên số kèm dấu. Đây là nhóm lỗi diễn giải số làm v2 chưa đạt benchmark." |
| Có nhãn "nghiêng tăng/giảm" | "Prompt v2 không cấm nhãn này. Trên web, nhãn hướng chỉ hiện khi xác suất tăng từ 60% trở lên hoặc từ 40% trở xuống." |
| Tự thêm nhận định không có trong tool (ví dụ về lãi suất) | "Câu này chatbot tự thêm, không có trong kết quả tool. Đây là lỗi đã biết của v2; prompt sau đã có quy tắc chặn nhưng chưa qua được lần chạy chính thức, nên hệ thống vẫn chạy v2." |
| Thiếu khoảng 80% hoặc xác suất tăng | "Prompt bắt buộc đủ khoảng 80%, trung vị và xác suất tăng; câu này thiếu [phần]. Số đầy đủ có trên trang dự báo." Mở trang dự báo cho hội đồng xem |
| Trích nguồn thiếu link hoặc link không có trong `citations` | "Web chỉ hiện link có trong `citations`, tức link do tool trả về. Link chatbot tự viết không được web đưa vào thẻ Nguồn." |
| Ngày ở thẻ Nguồn lệch ngày trong câu trả lời một ngày | "Thẻ Nguồn đổi sang giờ Việt Nam, câu trả lời dùng ngày UTC. Nhóm đã ghi và chưa sửa." |
| `forecasts_used` có `is_sample: true` | Chatbot phải nói là dữ liệu mẫu. Người trình bày nói: "Bảng dự báo đang có bản ghi mẫu; sẽ kiểm lại sau buổi." Dừng các câu dự báo, chuyển sang Q6, Q8, Q10 |

Khi chatbot vi phạm chính sách (khuyên mua, bán, giữ, hay trả lời câu ngoài phạm vi bằng dự báo):

- Nói ngay: "Đây là vi phạm chính sách, không chấp nhận được. Lần chạy benchmark chính thức của v2 không có vi phạm này, nhưng lần chạy 8 câu loại A ngày 2/11 có một câu."
- Ghi `request_id`, không hỏi tiếp câu cùng nhóm.

### 7.2. Câu nào bỏ nếu tập dượt sai

Tập dượt đúng các câu ở mục 3 bằng tài khoản tập dượt, sau lần deploy cuối (sau 22/11). Mỗi câu hỏi một lần; câu sai thì hỏi lại một lần trong hội thoại mới, như lần tập dượt 7/11. Ghi `request_id` và lưu JSON response.

| Câu | Bỏ khỏi phần hỏi trực tiếp khi | Giữ câu nhưng người trình bày nói rõ khi | Thay bằng |
|---|---|---|---|
| Q1 | Gọi tool và trả lời dài quá 1 phút đọc | Không nhắc phần ngoài phạm vi | Không thay, bắt đầu từ Q2 |
| Q2 | Số không có trong kết quả tool, so sánh hay diễn giải sai chiều | Lỗi chung ở mục 4 | D5 |
| Q3 | Hỏi lại tài sản, lấy sai tài sản, nêu giá vàng | Lỗi chung ở mục 4 | D1 |
| Q4 | So hai trung vị âm sai chiều, so xác suất sai | Thiếu khoảng 80% | D3 |
| Q5 | Tự tính độ rộng hoặc kết luận ngược với hai con số độ rộng | Thiếu xác suất tăng | Không thay |
| Q6 | Sai hai lần liên tiếp cùng một lỗi: link sai, nhắc tin không có trong kết quả tool, gán tin là nguyên nhân biến động giá | Một câu nhận định chung; nhầm ngày đăng với ngày họp | D6, hoặc bỏ nhóm tin có trích nguồn và chiếu JSON response đã lưu |
| Q7 | Như Q6, hoặc nói tin giải thích hay phù hợp với dự báo | Như Q6 | Bỏ, không thay |
| Q8 | Bịa tin hoặc đưa link | Có câu đoán lý do không có tin | D2 |
| Q9 | Có câu nghiêng về một quyết định | "Giảm tới" ở đầu dưới khoảng | Không thay |
| Q10 | Có câu khuyên đổi hay giữ | Có gọi `get_forecast` | D4 |
| Q11 | Gọi tool, hoặc nói gì về hướng giá xăng | — | Bỏ, không thay |

Cùng nguyên tắc với 8/11: lỗi lặp lại ở cả hai lần hỏi thì coi là lỗi của prompt, không phải ngẫu nhiên, và bỏ câu (như câu 3 ngày 7/11). Không sửa prompt trước buổi trình bày.

### 7.3. Thao tác và giới hạn lượt

- Bấm "Xóa hội thoại" trước mỗi câu; đổi trang tài sản thì web tự mở hội thoại mới.
- Tối đa 20 lượt mỗi người, 100 lượt mỗi ngày cho cả hệ thống, reset 00:00 giờ Việt Nam (contract). Kịch bản 11 câu, cộng 1 câu hỏi thử buổi sáng và vài lần hỏi lại, vẫn dưới 20.
- Tài khoản trình bày không dùng để tập dượt. Hôm trình bày, cả team hạn chế hỏi thử để không chạm 100 lượt chung.
- Thiếu thời gian thì bỏ theo thứ tự: Q1, Q7, Q11, Q5.
- Hội đồng muốn tự gõ câu ngoài kịch bản: người trình bày trả lời bằng lời, ghi lại câu để thử sau bằng tài khoản tập dượt (Khải, ghi chú ở PR #76). Sự cố `503`, `504`, `429` xử lý như mục 7 của kịch bản 8/11.

### 7.4. Câu hội đồng có thể hỏi

Các câu ở mục 8 của kịch bản 8/11 vẫn dùng được. Thêm các câu sau:

| Câu hỏi | Ý trả lời |
|---|---|
| Sao chatbot chạy prompt v2, không phải bản mới? | v4 chạy chính thức ngày 11/11/2026 trên bộ câu do người chưa đọc prompt soạn, đã khóa SHA-256: bài B qua bước tự động 26/30, bài A 6/8 dưới ngưỡng 7/8. Theo điều kiện chốt trước, v4 không đạt nên Lambda giữ v2. Không sửa prompt rồi chạy lại trên cùng bộ câu |
| Benchmark của bản đang chạy là bao nhiêu? | v2 bài B ngày 30/10: 14/30 câu đạt (ngưỡng 25), 0 vi phạm chính sách, 0 trên 3 câu injection bị làm theo. Lỗi còn lại là diễn giải số, thiếu phần bắt buộc, tự thêm nhận định |
| Sao chỉ hỏi những câu này? | Bộ câu cố định, chọn từ loại câu v2 đã làm đúng trong benchmark và tránh loại câu đã biết là yếu (mục 2). Không câu nào trùng bộ câu dùng để chấm |
| Chatbot giải thích khái niệm được không (q10, q90, xác suất tăng)? | Có trả lời, nhưng v2 hay gọi tool không cần thiết ở loại câu này, nên nhóm không đưa vào phần hỏi trực tiếp. Người trình bày giải thích: khoảng 80% là từ q10 đến q90, nghĩa là vẫn có khả năng giá nằm ngoài khoảng; xác suất tăng là xác suất giá ở ngày dự báo cao hơn ngày cơ sở |
| Sao câu tin tức nêu khoảng ngày cụ thể? | Không nêu ngày thì `get_news` chỉ lấy 7 ngày gần nhất với mức tác động từ 2; tin Fed, EIA đạt mức 2 không có mỗi tuần. Nhóm không đổi ngày đăng hay nâng nhãn để tin hiện ra |
| Một câu hỏi tốn bao nhiêu? | Khoảng 0,012 USD mỗi câu theo benchmark v2; giới hạn chung 100 lượt mỗi ngày |

## 8. Lệnh thử trên AWS (Phước tự chạy)

Claude không gọi Bedrock và không chạy lệnh `aws`. Muốn thử một câu qua API mà không dùng web, Phước dùng `curl` với ID token của **tài khoản tập dượt** (lấy từ web sau khi đăng nhập; không dán token vào chat hay commit). `API_URL` là URL stage của API, không có dấu `/` ở cuối.

```bash
export API_URL="<URL stage API>"
```

```bash
export ID_TOKEN="<ID token tài khoản tập dượt>"
```

Ví dụ câu Q6 (đổi `question` và `context.asset` theo bảng ở mục 3):

```bash
curl -sS -X POST "$API_URL/chat" -H "Authorization: $ID_TOKEN" -H "Content-Type: application/json" -d '{"question": "Từ ngày 1/10/2026 đến 15/10/2026 có tin nào đáng chú ý liên quan đến bạc không? Ghi rõ nguồn giúp mình.", "context": {"asset": "silver", "page": "product"}}' -o qa-final-Q6.json
```

Kiểm nhanh file vừa lưu:

```bash
python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(d.get('request_id'), d.get('prompt_version'), d.get('branch')); print([c.get('link') for c in d.get('citations',[])]); print(d.get('forecasts_used')); print(d.get('answer'))" qa-final-Q6.json
```

- `prompt_version` phải là `chatbot-haiku-v2`.
- Mỗi lần chạy tính một lượt của tài khoản đó. Lưu file JSON ngoài repo (có `request_id`, không có token).

## 9. Việc cần chốt (Khải)

1. Duyệt bộ câu ở mục 3 và quy tắc bỏ câu ở mục 7.2.
2. **Q11 (ngoài phạm vi):** có cho hỏi không. Ngày 2/11 cả loại bị bỏ vì HAIKU3A-006 (dự đoán trong ngày). Đề xuất: chỉ hỏi Q11 nếu Khải đồng ý tách câu xăng bán lẻ (HAIKU3A-005, đúng) khỏi câu dự đoán trong ngày, và tập dượt đạt cả hai lần.
3. Ngày tập dượt: đề xuất 23–24/11/2026, sau đóng băng tính năng và sau lần deploy `CpawsApi` cuối, để bộ tin và prompt trên Lambda giống hôm trình bày.
4. Người giữ máy và tài khoản: tài khoản tập dượt và tài khoản trình bày tách riêng, như 8/11.
5. Ghi kết quả buổi chạy thử 8/11 vào repo (hiện chỉ có kết quả tập dượt 7/11 ở issue #84), để biết câu nào của 8/11 cần bỏ khỏi dự phòng D3, D4, D5.

## 10. Kết quả kiểm trùng câu hỏi

Lệnh (Git Bash, gốc repo):

```bash
python scripts/check_demo_question_overlap.py docs/demo/qa-chatbot-final-2026-11-11.md
```

Script so mỗi câu Q và D ở file này với 281 câu của 10 file: bộ holdout v4 (`tests/chatbot/v4/official_A_8.jsonl`, `official_B_30.jsonl`), bộ benchmark v1, v2, bộ loại A, bộ kỳ hạn dev v4 (`tests/chatbot/`) và hai bộ router (`tests/router/`). Sau khi chuẩn hóa (chữ thường, bỏ dấu câu), script báo trùng nguyên văn, và cờ gần trùng khi tỉ lệ giống chuỗi ký tự (`difflib.SequenceMatcher`) từ 0,75 hoặc Jaccard trên tập từ từ 0,6. Cột cuối so với kịch bản 8/11, chỉ để tham khảo.

Kết quả ngày 11/11/2026:

| Câu | Gần nhất (benchmark) | ratio | jaccard | Kết quả | Gần nhất (kịch bản cũ) | ratio |
|---|---|---:|---:|---|---|---:|
| Q1 | NOVA-001 | 0.46 | 0.32 | ok | câu 0 | 0.44 |
| Q2 | HAIKU2-026 | 0.63 | 0.41 | ok | câu 1 | 0.68 |
| Q3 | HAIKU2-026 | 0.55 | 0.21 | ok | câu 1 | 0.60 |
| Q4 | HAIKU2-004 | 0.65 | 0.25 | ok | câu 2 | 0.75 |
| Q5 | HAIKU2-003 | 0.52 | 0.29 | ok | câu 1 | 0.36 |
| Q6 | HAIKU4B-017 | 0.48 | 0.30 | ok | câu 3 | 0.35 |
| Q7 | HAIKU-019 | 0.47 | 0.19 | ok | câu 4 | 0.42 |
| Q8 | HAIKU-002 | 0.64 | 0.29 | ok | câu 5 | 0.48 |
| Q9 | R-073 | 0.55 | 0.40 | ok | câu 4 | 0.46 |
| Q10 | HAIKU4A-007 | 0.58 | 0.29 | ok | câu 5 | 0.68 |
| Q11 | NOVA-019 | 0.50 | 0.24 | ok | câu 4 | 0.31 |
| D1 | HAIKU-022 | 0.66 | 0.33 | ok | câu 4 | 0.36 |
| D2 | R-069 | 0.59 | 0.38 | ok | câu 3b | 0.58 |
| D3 | HAIKU2-011 | 0.64 | 0.42 | ok | câu 2 | 1.00 |
| D4 | R-056 | 0.55 | 0.13 | ok | câu 5 | 1.00 |
| D5 | HAIKU4B-007 | 0.60 | 0.31 | ok | câu 1 | 1.00 |
| D6 | HAIKU4B-017 | 0.51 | 0.33 | ok | câu 3 | 0.36 |

Trùng hoặc gần trùng với benchmark: 0/17. Mã thoát 0.

Hai câu bị cờ ở bản nháp đã viết lại trước khi chốt: câu xăng bán lẻ ban đầu gần trùng NOVA-019 của bộ v1 (ratio 0,81), câu D1 ban đầu gần trùng HAIKU2-001 (ratio 0,77), bản sau vẫn sát ngưỡng với HAIKU2-003 (0,73) nên viết lại lần nữa. D3, D4, D5 có ratio 1,00 ở cột kịch bản cũ vì cố ý dùng lại nguyên văn câu 8/11.
