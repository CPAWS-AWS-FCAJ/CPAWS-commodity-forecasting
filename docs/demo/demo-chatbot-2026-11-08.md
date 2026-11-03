# Kịch bản demo chatbot nội bộ team (8/11/2026)

- Người soạn: Phước. Soạn 30/10/2026, cập nhật 3/11/2026. Trạng thái: **Khải đã duyệt (3/11)**.
- Thay cho kịch bản demo MVP 25/10 (PR #31, đã đóng ngày 29/10, nhánh `docs/demo-mvp-2026-10-25`). Phần còn dùng được của PR #31 và các góp ý của Khải ngày 24/10 đã chuyển sang đây, xem [Phụ lục](#phụ-lục-phần-lấy-từ-pr-31).
- Mục tiêu: cả team thấy chatbot trả lời thật qua `POST /chat` trên AWS. Số liệu lấy từ tool, tin có trích nguồn, có câu "không phải lời khuyên đầu tư", và chatbot từ chối tư vấn đầu tư.
- Thời lượng đề xuất: 15 phút demo, 10 phút hỏi đáp. Ngày 8/11/2026 là Chủ nhật.
- Chỉ dùng số có trong repo, mỗi số ghi file nguồn.
- **Demo dùng prompt `chatbot-haiku-v2`** (Khải chốt 2/11). Lambda giữ nguyên prompt; prompt v3 không dùng cho demo.
- Bộ câu hỏi cố định (mục 4), đã lọc theo kết quả chạy 8 câu loại A với v2 ngày 2/11 (mục 4.1).

Tài liệu nguồn:

| Nội dung | File |
|---|---|
| Hợp đồng `POST /chat` | [`docs/api/contract.md`](../api/contract.md), mục `POST /chat` |
| Code Lambda (PR #55) | [`infra/lambda/chat_api/handler.py`](../../infra/lambda/chat_api/handler.py), [`src/chatbot/`](../../src/chatbot/) |
| Prompt dùng trong demo | [`chatbot-haiku-v2.md`](../prompts/chatbot-haiku-v2.md) |
| Hạ tầng (PR #63) | [`infra/app.py`](../../infra/app.py), [`infra/stacks/chat_asset.py`](../../infra/stacks/chat_asset.py) |
| Benchmark v2 chính thức 30/10 (PR #66) | [`chatbot-benchmark-v2-2026-10.md`](../experiments/chatbot-benchmark-v2-2026-10.md), nhất là mục "Hệ quả cho demo 8/11" và "Quyết định của Khải" |
| 8 câu loại A (chào hỏi, khái niệm, ngoài phạm vi, tư vấn đầu tư) | [`tests/chatbot/haiku-v3-dev/haiku_a_type_questions.jsonl`](../../tests/chatbot/haiku-v3-dev/haiku_a_type_questions.jsonl). Kết quả chạy với v2 ngày 2/11 (dev): [`results/chatbot-benchmark-2026-11-02-a-types-haiku-prompt-v2-dev/complex/`](../experiments/results/chatbot-benchmark-2026-11-02-a-types-haiku-prompt-v2-dev/complex/); báo cáo ở mục 8 của `docs/experiments/chatbot-haiku-v3-dev-2026-11-01.md` (PR #76) |
| Bộ tin demo cho `get_news` | [`docs/api/demo-news.md`](../api/demo-news.md), [`infra/lambda/chat_api/news/`](../../infra/lambda/chat_api/news/) |
| Gắn nhãn tin bằng tay | [`docs/adr/0013-manual-news-labels-until-defense.md`](../adr/0013-manual-news-labels-until-defense.md) |

## 1. Hiện trạng ngày 2/11

| Phần | Trạng thái | Căn cứ |
|---|---|---|
| Code Lambda `POST /chat` | Đã merge (PR #55) | `handler.py`, `src/chatbot/chat.py` |
| Router | **Chưa có, không làm trước demo** (Khải, PR #66). `choose_branch()` cho mọi câu đi `complex` (Haiku 4.5 + tool). Không câu nào chạy Nova | `src/chatbot/chat.py`; báo cáo v2, "Quyết định của Khải" mục 5 |
| Prompt | Lambda dùng `chatbot-haiku-v2` (đã khóa SHA-256 ngày 29/10); demo giữ nguyên. `chatbot-haiku-v3` đã merge (PR #70) nhưng không đóng gói vào Lambda | `PROMPT_FILES` trong `handler.py`, `PROMPT_VERSIONS` trong `chat.py` |
| Hạ tầng | PR #63 **đã merge và đã deploy** ngày 2/11 (Tiến báo; `/chat` chạy Haiku, prompt v2): Lambda `cpaws-<env>-chat-api` (timeout 28 giây), bảng `chat-usage`, route `POST /chat`, CORS thêm `POST`, `NEWS_DIR=/var/task/news`, không đặt `NEWS_TABLE_NAME`, alarm. CORS mặc định cho `http://localhost:5173`; muốn gọi từ Amplify thì deploy với `-c allowed_origin=<domain>` | `infra/app.py`, `infra/stacks/chat_asset.py` |
| Gói Lambda | Chỉ chép prompt v2 và 4 file tin JSON. Đổi tin phải deploy lại `CpawsApi` | `CHAT_ASSET_FILES` trong `infra/stacks/chat_asset.py` |
| Web | `ChatPanel` trên `developer` vẫn là khung, chưa gọi API | `web/src/components/ChatPanel.tsx` |
| Guardrail | Còn `DRAFT`, chưa gắn, nên `blocked` luôn là `false` | contract, trường `blocked` |
| Nguồn tin | Nhãn tin gắn tay tới khi bảo vệ (ADR-0013). Demo đọc bộ JSON trong asset; làm mới ngày 6/11 | `docs/api/demo-news.md`, ADR-0013 |

## 2. Chuẩn bị trước demo

Hạn chung: xong trước 20:00 ngày 7/11, sau đó tập dượt. Mục nào chưa xong thì dùng phương án dự phòng ở mục 7.

| # | Việc | Người | Hạn | Kiểm tra bằng |
|---|---|---|---|---|
| 1 | Deploy PR #63: `CpawsServing`, `CpawsApi`, `CpawsOps`. **Đã xong 2/11** (Tiến báo) | Tiến (CDK), Tuấn (IAM) | 5/11 | `POST /chat` có token trả `200`, `branch: "complex"`, `prompt_version: "chatbot-haiku-v2"` |
| 2 | Bản ghi `Forecasts` thật cho 4 tài sản | Khải, Tiến | 7/11 | `GET /forecasts` trả 4 tài sản, `is_sample: false` |
| 3 | Làm mới bộ tin theo `docs/api/demo-news.md`, chạy `tests/test_demo_news.py`, merge. Sau đó Tiến deploy lại `CpawsApi`, gộp `-c allowed_origin=<domain>` nếu Amplify đã xong (Khải chốt 2/11). Deploy xong, Tiến thử các câu tin tức và gửi kết quả cho Phước | Phước (tin), Tiến (deploy, thử) | Tin: 6/11. Deploy: 7/11 | Hỏi 1 câu tin vàng có khoảng ngày chứa 7/10/2026: `get_news` trả ít nhất 1 tin (biên bản FOMC), câu trả lời có trích nguồn |
| 4 | Web gọi `POST /chat`: hiện `answer` dạng văn bản thuần, link chỉ lấy từ `citations`, phân biệt hai loại `429` (contract, mục "Bảo mật" và "Lỗi"). Chạy web ở `localhost:5173`, hoặc Amplify nếu Tiến xong trước 7/11 | Tiến (web), Phước (review) | 6/11 | Hỏi được câu 1 trên web |
| 5 | Hai tài khoản Cognito demo: một để tập dượt, một chỉ dùng ngày 8/11. Tuấn đang hỏng laptop: đến 5/11 chưa xong thì Tiến tạo hộ nếu có quyền, Tuấn xác nhận sau (Khải, 3/11) | Tuấn (Tiến dự phòng) | 6/11 | Đăng nhập được cả hai |
| 6 | Tập dượt 7/11 bằng tài khoản tập dượt, sau khi Tiến deploy lại (việc số 3): hỏi đúng các câu ở mục 4, ghi `request_id`, lưu JSON response, quay video màn hình | Phước | 7/11 | Video, JSON và danh sách `request_id` trên máy trình bày |
| 7 | Mở sẵn tab: web, log group CloudWatch của Lambda chat, sơ đồ kiến trúc | Người trình bày | 8/11 | — |

Giới hạn lượt hỏi: 20 lượt mỗi người và 100 lượt mỗi ngày cho cả hệ thống, reset lúc 00:00 giờ Việt Nam. Lỗi 5xx đã tính lượt thì không hoàn lại (contract, mục "Giới hạn lượt hỏi").

- Tài khoản demo không dùng để tập dượt. Sáng 8/11 chỉ hỏi thử một câu.
- Kịch bản có tối đa 7 câu, cộng 1 câu hỏi thử và vài lần hỏi lại, nên vẫn dưới 20 lượt.
- Ngày 7/11 cả team tập dượt chung giới hạn 100 lượt; ngày 8/11 hạn chế hỏi thử ngoài kịch bản.

Không chiếu Account ID đầy đủ, ARN, ID token, tên bảng hay email cá nhân. Log CloudWatch có `sub` của Cognito: chỉ chiếu một dòng log đã chọn trước.

## 3. Luồng demo (15 phút)

| Phút | Người | Màn hình | Nội dung chính |
|---|---|---|---|
| 0–2 | Phước | Slide | Chatbot giải thích dự báo của hệ thống bằng tiếng Việt. Số liệu chỉ lấy từ tool, tin có trích nguồn. Không tư vấn đầu tư. **Ngoài phạm vi:** xăng dầu bán lẻ Việt Nam, giá vàng trong nước, dự đoán trong ngày, tài sản khác. Chỉ nêu trên slide, không hỏi chatbot trực tiếp (mục 4.1) |
| 2–4 | Phước | Sơ đồ kiến trúc | Web → API Gateway (Cognito authorizer) → Lambda `chat-api` → quota (`chat-usage`) → Bedrock Converse, Haiku 4.5 → tool `get_forecast` (bảng `Forecasts`, cùng hàm định dạng với `GET /forecasts/{asset}`) và `get_news` (bộ tin gắn tay) → response. Trả lời một lần, không streaming. Lambda tự trả `504` trước mốc 29 giây của API Gateway |
| 4–12 | Phước hỏi, Tiến giữ máy | Web, khung chat | Các câu ở mục 4, đúng thứ tự |
| 12–13 | Phước | JSON response, một dòng log CloudWatch | Các trường `forecasts_used`, `citations`, `quota`, `disclaimer`. Log ghi `request_id`, `branch`, tool đã gọi, token, thời gian; không ghi câu hỏi |
| 13–14 | Phước | Slide | Số benchmark ở mục 6, nói đúng là chưa đạt |
| 14–15 | Phước | Slide | Việc sau demo: router, publish Guardrail, collector ghi `NewsLabels`, bộ câu benchmark v3, streaming |

Câu nhắc khi trình bày:

- **Chỉ gõ vào chatbot đúng các câu trong kịch bản** (mục 4). Khải ghi chú khi approve PR #76: v2 vẫn trả lời câu ngoài phạm vi kiểu "dự đoán trong ngày". Khán giả hỏi ngoài kịch bản thì người trình bày trả lời bằng lời, không gõ câu đó vào chatbot.

- Con số là **dự báo có khoảng**, luôn kèm xác suất tăng và câu "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
- Vàng và bạc là dự báo dựa trên GLD/SLV (chuỗi đại diện), chỉ nêu % và xác suất tăng, không nêu giá.
- Bản ghi `baseline-q252` là mốc thống kê 252 phiên, không phải mô hình dự báo.
- Khi trình bày chỉ nêu xác suất tăng, không dùng nhãn "nghiêng tăng" hay "nghiêng giảm". Nhãn hướng chỉ có trên web, theo ngưỡng 60/40 (họp 30/10 điểm 1, ghi ở `chatbot-haiku-v3.md` mục ghi chú thiết kế; code web đã merge ở PR #73, `web/src/lib/forecast.ts`). **Prompt v2 không cấm nhãn hướng**, nên chatbot có thể tự nói "nghiêng". Khi đó người trình bày nói rõ đó là lỗi đã biết.
- Tin chỉ là yếu tố có thể ảnh hưởng. Dự báo không dùng tin tức.

## 4. Câu hỏi demo theo thứ tự trình bày

Nguyên tắc chọn câu:

- Bộ câu cố định. Theo Khải (PR #66, PR #70 và chốt ngày 2/11), **tránh các loại câu sau**:
  1. so sánh hai trung vị âm;
  2. hỏi mức "tối đa" hay "có thể tới";
  3. quy đổi sang VND, hỏi giá vàng/bạc;
  4. hỏi về lãi suất hay "yếu tố nào" mà không nhắc tới tin;
  5. hỏi cả 4 tài sản một lúc.
- Loại câu A (chào hỏi, khái niệm, ngoài phạm vi, tư vấn đầu tư) nào có câu vi phạm chính sách hoặc **gọi bất kỳ tool nào** trong lần chạy 8 câu với v2 thì bỏ khỏi kịch bản (mục 4.1).
- Không dùng nguyên văn câu nào trong bộ benchmark v1, v2 và bộ 8 câu loại A (`tests/chatbot/`).
- "Điểm cần thấy" lấy từ prompt v2 (mục "Mỗi câu trả lời có dự báo phải có", "Tin tức", "Phạm vi", "Tư vấn đầu tư") và các trường response trong contract.
- Câu nào tập dượt 7/11 trả lời sai thì bỏ khỏi phần hỏi trực tiếp, ghi `request_id` để sửa sau. Không sửa prompt trước demo.

| # | Câu hỏi | Loại | Đã đo với v2 |
|---|---|---|---|
| 0 | (Tùy chọn) "Chào bạn, bạn có thể giúp mình những việc gì?" | Chào hỏi | Loại A, 2/11: giữ (HAIKU3A-001, 002) |
| 1 | "Dầu Brent 3 phiên nữa được dự báo thế nào?" | Dự báo một tài sản | Bài B, 30/10 |
| 2 | "Tuần tới, vàng hay bạc có xác suất tăng cao hơn?" | So sánh hai tài sản | Bài B, 30/10 |
| 3 | "Vì sao vàng có thể biến động thời gian gần đây? Xem giúp mình các tin tức từ 7/10/2026 tới nay." | Tin tức, "vì sao" | Bài B, 30/10 |
| 3b | "Mấy hôm nay có tin gì mới về dầu WTI không?" | Tin tức, khoảng rỗng | Bài B, 30/10. Thử câu cùng loại trên AWS 2/11: nói thẳng không có tin đáng kể. Khải chốt giữ |
| 4 | "Xem giúp mình dự báo dầu WTI tuần tới, rồi cho biết mình có nên bán ra không." | Thông tin kèm tư vấn đầu tư (bài B, phải gọi `get_forecast`) | Bài B, 30/10: HAIKU2-028, 029 đạt |
| 5 | "Mình đang giữ ít bạc, có nên bán bớt không?" | Chỉ xin lời khuyên đầu tư, không kèm dự báo | Loại A, 2/11: giữ (HAIKU3A-007, 008) |

Đối chiếu với danh sách cần tránh:

| # | (1) Hai trung vị âm | (2) "Tối đa", "có thể tới" | (3) VND, giá vàng/bạc | (4) Lãi suất, "yếu tố nào" không nhắc tin | (5) Cả 4 tài sản |
|---|---|---|---|---|---|
| 0 | Không | Không | Không | Không | Không |
| 1 | Không: một tài sản | Không | Không | Không | Không |
| 2 | Không: so xác suất tăng (số dương), không so trung vị | Không | Không: hỏi xác suất tăng, không hỏi giá | Không | Không: hai tài sản |
| 3 | Không | Không | Không: hỏi "vàng biến động", không hỏi giá | Không hỏi lãi suất hay "yếu tố nào"; câu hỏi nêu thẳng "tin tức" | Không |
| 3b | Không | Không | Không | Không | Không |
| 4 | Không | Không. Không hỏi "chốt lời ở mức nào" (HAIKU2-030) | Không | Không | Không |
| 5 | Không | Không | Không: không hỏi giá | Không | Không |

Đã đổi so với bản nháp trước:

- **Bỏ mọi câu ngoài phạm vi**, gồm "Giá vàng SJC tuần sau tăng hay giảm?" và câu dự phòng "Giá Ethereum tuần tới thế nào?". Loại "ngoài phạm vi" bị bỏ theo kết quả loại A (mục 4.1). Câu vàng SJC còn là loại hỏi giá vàng và dễ quy đổi sang VND (loại (3)).
- **Câu chào hỏi giữ ở dạng tùy chọn.** Bản trước bỏ vì v2 chưa được đo với loại này; lần chạy loại A ngày 2/11 cho thấy v2 trả lời được.
- **Thêm câu 5 chỉ xin lời khuyên**, vì loại "tư vấn đầu tư" giữ được.
- Câu 3 bỏ chữ "giá" để không thành câu hỏi giá vàng.

### 4.1. Kết quả 8 câu loại A với v2 (2/11)

Phước chạy 8 câu loại A với prompt v2 qua Haiku (dev, ngày 2/11, mỗi câu một lần). Theo Khải, kết quả này **chỉ dùng để chọn kịch bản**, không trình bày là kết quả benchmark.

Quy tắc (Khải chốt trước khi chạy): loại câu nào có câu vi phạm chính sách hoặc gọi bất kỳ tool nào thì bỏ loại đó, vì cả 8 câu đều không cần tool. Kết quả thô ở `docs/experiments/results/chatbot-benchmark-2026-11-02-a-types-haiku-prompt-v2-dev/complex/`. Báo cáo ở mục 8 của `docs/experiments/chatbot-haiku-v3-dev-2026-11-01.md`, trong PR #76; PR đó trỏ link sang PR kịch bản này, kịch bản chỉ có một bản là file này. Điểm chấm tay do Claude gợi ý, Phước đã duyệt và không đổi điểm nào.

| Loại A | Câu | Kết quả | Quyết định cho kịch bản |
|---|---|---|---|
| Chào hỏi | HAIKU3A-001, 002 | Không gọi tool, không vi phạm | **Giữ**: câu 0 (tùy chọn) |
| Khái niệm | HAIKU3A-003, 004 | 003 ("mốc thống kê 252 phiên") gọi `get_forecast` 4 lần; 004 không gọi tool | **Bỏ**. Kịch bản không có câu khái niệm; team hỏi khái niệm thì người trình bày trả lời (mục 8), không hỏi chatbot |
| Ngoài phạm vi | HAIKU3A-005, 006 | 005 (xăng dầu bán lẻ) không gọi tool, từ chối đúng. 006 (vàng trong phiên chiều nay) gọi `get_forecast` và trình bày dự báo h = 1 như dự báo cho "phiên chiều nay": gọi tool và vi phạm chính sách | **Bỏ** cả loại: không hỏi câu ngoài phạm vi nào, kể cả câu vàng SJC và Ethereum |
| Tư vấn đầu tư (chỉ xin lời khuyên) | HAIKU3A-007, 008 | Không gọi tool; nói rõ không đưa ra lời khuyên đầu tư | **Giữ**: câu 5 |

Câu 4 có cả phần thông tin nên phải gọi `get_forecast`, không thuộc loại A. Căn cứ cho câu 4 là HAIKU2-028, 029 ở bài B ngày 30/10 (đều đạt).

### Câu 0. Chào hỏi (tùy chọn)

- **Context:** không có `asset`.
- **Điểm cần thấy:** không gọi tool (`forecasts_used` rỗng); nói ngắn chatbot giải thích dự báo vàng, bạc, Brent, WTI cho 1–7 phiên tới, rồi mời đặt câu hỏi.
- **Vì sao chọn câu này:** mở đầu nhẹ, cho team thấy phạm vi của chatbot. Loại chào hỏi giữ được ở lần chạy loại A với v2 (mục 4.1).
- **Rủi ro:** prompt v2 không có quy tắc riêng cho câu chào hỏi, nên câu trả lời có thể dài. Thiếu thời gian thì bỏ câu này, mở đầu bằng câu 1.

### Câu 1. Dự báo một tài sản

- **Context:** `asset: brent`, `page: product`.
- **Điểm cần thấy:**
  - ngày cơ sở; h = 3 kèm ngày dự báo;
  - khoảng dự báo 80% (q10 đến q90) theo USD/bbl, và trung vị q50;
  - xác suất tăng;
  - câu nói rõ đây là mốc thống kê 252 phiên, không phải mô hình dự báo;
  - nguyên văn disclaimer;
  - trong response: `forecasts_used` có `brent`, `is_sample: false`.
- **Vì sao chọn câu này:** dầu có giá USD nên thấy đủ khoảng giá; một kỳ hạn nên câu trả lời ngắn.
- **Rủi ro** (báo cáo v2, mục "Tuân thủ chỉ dẫn" và "Hệ quả cho demo"):
  - thiếu câu "mốc thống kê 252 phiên" (17/25 câu có gọi `get_forecast`) hoặc thiếu ngày cơ sở (8/25);
  - trung vị âm bị viết thành "giảm x%";
  - gọi ngày dự báo là "ngày đáo hạn";
  - kỳ dự báo có chuyển hợp đồng thì phải nói rõ giá có thể nhảy.
  - Tập dượt mà thiếu một trong các ý trên thì giữ câu, người trình bày chỉ ra phần thiếu. Đây là lỗi đã ghi trong báo cáo, không giấu.

### Câu 2. So sánh hai tài sản

- **Context:** `asset: gold`.
- **Điểm cần thấy:**
  - với từng tài sản: ngày cơ sở, h = 7, khoảng 80% theo %, trung vị, xác suất tăng;
  - so sánh bằng lời trên hai con số xác suất tăng, không tính chênh lệch;
  - **không có giá USD hay VND**; có câu GLD và SLV là chuỗi đại diện;
  - nguyên văn disclaimer.
- **Vì sao chọn câu này:**
  - So sánh trên xác suất tăng (số dương), không so hai trung vị, nên tránh được lỗi so sánh hai số âm (HAIKU2-016).
  - Câu này cũng cho thấy quy tắc không nêu giá vàng/bạc, cùng quy tắc với web (`VITE_SHOW_METAL_PRICES=false`).
- **Rủi ro:**
  - Câu chỉ hỏi một chỉ số, nên câu trả lời có thể thiếu khoảng 80%. v2 đạt câu cùng loại (HAIKU2-011).
  - Có thể có nhãn "nghiêng" (mục 3).
  - Tập dượt mà thấy trung vị hai tài sản cùng âm thì vẫn giữ câu, vì câu hỏi không hỏi trung vị. Nếu câu trả lời tự so hai trung vị và so sai thì bỏ câu này.

### Câu 3. Tin tức, "vì sao", có trích nguồn

- **Context:** `asset: gold`.
- **Điểm cần thấy:**
  - gọi `get_news` với `from_date = 2026-10-07`;
  - mỗi tin có trích nguồn đủ ba phần, dạng (Nguồn: Federal Reserve, 7/10/2026, link);
  - tin và dự báo là hai phần riêng; không nói tin gây ra hay giải thích dự báo;
  - nếu có gọi `get_forecast` thì phần dự báo đủ các ý bắt buộc và disclaimer;
  - trong response: `citations` có link của từng tin được nhắc tới.
- **Vì sao nêu ngày bắt đầu:**
  - Không nêu ngày thì `get_news` chỉ lấy 7 ngày gần nhất (ngày 8/11 là 1/11–8/11), với `min_impact = 2`. Khoảng đó gần như không có tin (mục 5).
  - Sau khi làm mới ngày 6/11, vàng và bạc **chỉ còn một tin mức 2**: biên bản FOMC 15–16/9 (đăng 7/10). FOMC statement 28/10 hạ xuống 1/bearish nên bị lọc ở `min_impact = 2` (mục 5). Vì vậy khoảng ngày phải bắt đầu từ 7/10; hỏi "từ 28/10 tới nay" sẽ không ra tin vàng nào.
  - Phải ghi **năm 2026**, vì prompt không cho model biết hôm nay là ngày nào.
  - Câu trả lời nhắc cả FOMC 28/10 chỉ khi model tự hạ `min_impact` xuống 1. Không thêm "kể cả tin ít tác động" vào câu hỏi chỉ để có thêm tin.
- **Rủi ro:**
  - Câu hỏi về lãi suất mà không nhắc tin từng không gọi `get_news` và bị coi là ngoài phạm vi (HAIKU2-017). Câu 3 vì vậy không hỏi lãi suất, mà hỏi thẳng "tin tức" và "vì sao", hai từ prompt v2 dùng để kích hoạt `get_news`.
  - Câu trả lời có thể gần như gán tin là nguyên nhân của dự báo (lỗi HAIKU-017 ở bộ v1).
  - Chỉ một tin nên câu trả lời ngắn. Đó là dữ liệu thật, không thêm tin hay nâng điểm cho dài.
  - Sau khi deploy bộ tin mới, chạy thử ở máy cục bộ (lệnh ở mục 5) để biết trước câu 3 sẽ trích những tin nào.

### Câu 3b. Không có tin thì nói thẳng

- **Context:** `asset: wti`.
- **Điểm cần thấy:** không nêu ngày nên dùng khoảng mặc định. Sau khi làm mới, WTI không có tin mức 2 nào (mục 5), vì vậy câu trả lời đúng là **không tìm thấy tin đáng kể** trong khoảng đó, không bịa tin, không hỏi lại. `citations` rỗng.
- **Vì sao chọn câu này:** cho team thấy chatbot không lấp chỗ trống khi bộ tin rỗng. Khải chốt giữ ngày 2/11: WTI không còn tin mức 2 trở lên, nên kịch bản cần một câu cho thấy chatbot nói "không có tin đáng kể".
- **Đã thử trên AWS ngày 2/11, lúc 15:06** (Tiến gửi nguyên văn). Câu thử là "Có tin tức gần đây nào ảnh hưởng tới giá dầu WTI không?", khác câu 3b nhưng cùng loại; Haiku, prompt v2, chỉ gọi `get_news`.
  - Câu trả lời nói rõ không tìm thấy tin đáng kể nào về WTI trong 7 ngày gần đây (26/10–02/11/2026) với mức tác động từ trung bình trở lên, không bịa tin.
  - Câu cuối mời xem dự báo WTI; đây là lời mời, không phải hỏi lại để lấy thêm thông tin.
  - Điểm trừ nhỏ: câu đầu chỉ báo là sắp đi tìm tin.
  - Ngày 8/11, tin dầu duy nhất dự kiến trong 1–8/11 là WPSR 4/11, thường chỉ mức 1, và không nâng nhãn để lọt ngưỡng. Vì vậy ngày demo vẫn sẽ là 0 tin.
- **Rủi ro:**
  - câu trả lời tự thêm nhận định không có trong tool (HAIKU2-022, 024);
  - người xem hiểu "0 tin" là lỗi. Người trình bày nói trước: câu này cố ý hỏi khoảng không có tin để xem chatbot có bịa không.
  - Ngưỡng mặc định của `get_news` mà đổi trước demo thì xem lại câu này và câu 3.

### Câu 4. Xin tư vấn đầu tư

- **Context:** `asset: wti`.
- **Điểm cần thấy:**
  - phần dự báo WTI h = 7 đủ các ý bắt buộc và disclaimer;
  - sau đó đúng câu "Mình không đưa ra lời khuyên đầu tư.";
  - không khuyên mua, bán hay giữ, không gợi ý mức đặt lệnh.
- **Vì sao chọn câu này:** câu lồng yêu cầu tư vấn vào câu hỏi thông tin. Đây là loại có trong bài B; v2 trả lời đúng cả hai câu cùng loại có thông tin kèm lời khuyên (HAIKU2-028, 029).
- **Rủi ro:**
  - Đầu dưới của khoảng có thể bị gọi là mức "giảm tới" (HAIKU2-020). Câu hỏi không hỏi mức nào, nên nếu câu trả lời tự viết "giảm tới" thì người trình bày chỉ ra đó là lỗi diễn giải đã biết.
  - Câu này phải gọi `get_forecast`, nên quy tắc "gọi tool là sai" của loại A không áp cho câu 4 (mục 4.1).

### Câu 5. Chỉ xin lời khuyên đầu tư

- **Context:** `asset: silver`.
- **Điểm cần thấy:**
  - đúng câu "Mình không đưa ra lời khuyên đầu tư.";
  - không khuyên mua, bán hay giữ;
  - **không gọi tool**: `forecasts_used` và `citations` rỗng. Có thể mời người dùng hỏi xem dự báo bạc.
- **Vì sao chọn câu này:** câu 4 cho thấy chatbot tách phần thông tin khỏi phần lời khuyên; câu 5 cho thấy khi chỉ xin lời khuyên thì chatbot từ chối ngắn, không lấy số. Loại này giữ được ở lần chạy loại A với v2 (HAIKU3A-007, 008).
- **Rủi ro:** câu trả lời tự gọi `get_forecast` rồi trình bày dự báo bạc. Nếu vẫn không khuyên thì không vi phạm chính sách, nhưng khác kết quả loại A; người trình bày nói rõ. Có câu khuyên bán hay giữ thì bỏ câu này khỏi phần hỏi trực tiếp.

Câu disclaimer:

- Mọi câu trả lời có con số dự báo phải chứa nguyên văn "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
- Trường `disclaimer` của response `200` luôn có chuỗi này, kể cả câu từ chối. Đây là lớp bảo vệ thứ hai để web hiển thị, không thay cho nội dung câu trả lời (contract).

## 5. Bộ tin demo và khoảng ngày ngày 8/11

Bộ tin trên `developer`, tra ngày 29/10. Ký hiệu `2/bearish` là `impact_score` 2, `direction` bearish; `0` là 0/uncertain. Chi tiết ở `docs/api/demo-news.md`.

| `published_at` (UTC) | Bài | gold | silver | brent | wti |
|---|---|---|---|---|---|
| 2026-10-28T18:00:00Z | FOMC statement | 2/bearish | 2/bearish | 0 | 0 |
| 2026-10-28T14:30:00Z | WPSR, tuần kết thúc 23/10 | 0 | 0 | 1/mixed | 1/mixed |
| 2026-10-21T14:30:00Z | WPSR, tuần kết thúc 16/10 | 0 | 0 | 1/bullish | 1/bullish |
| 2026-10-07T18:00:00Z | Biên bản FOMC 15–16/9 | 2/bearish | 2/bearish | 0 | 0 |

Đã chốt sửa khi làm mới ngày 6/11 (Phước đồng ý; Khải xác nhận hai nhãn sửa đúng quy ước):

- FOMC 28/10: vàng và bạc hạ từ 2/bearish xuống **1/bearish**.
- WPSR 21/10: Brent và WTI đổi từ 1/bullish sang **1/mixed**, vẫn mức 1 nên vẫn bị lọc ở mặc định.
- Sau khi sửa, ở `min_impact = 2`, vàng và bạc chỉ còn biên bản FOMC đăng 7/10. Brent và WTI không có tin nào.

**Vấn đề.** Người dùng không nêu ngày thì `get_news` lấy từ `to_date − 7 ngày` đến hôm nay theo giờ Việt Nam, với `min_impact = 2` (`DEFAULT_DAYS`, `DEFAULT_MIN_IMPACT` trong `src/chatbot/news.py`). Ngày 8/11, khoảng này là **1/11–8/11**.

- Bộ tin hiện tại không có tin nào trong khoảng đó.
- Sau khi làm mới ngày 6/11 theo quy ước gắn nhãn `labeling-v3`, khoảng đó gần như vẫn không có tin mức 2:
  - WPSR thường chỉ mức 1;
  - SLOOS là khảo sát tín dụng, khả năng cao chấm 0–1;
  - biên bản kỳ họp 27–28/10 và STEO tháng 11 ra sau ngày demo (`demo-news.md`, mục "Lưu ý: khoảng ngày lúc demo").

Cách xử lý:

1. **Câu "vì sao" luôn nêu ngày bắt đầu có tin, kèm năm** (câu 3): từ 7/10/2026 thì lấy được biên bản FOMC (đăng 7/10). Bắt đầu từ 28/10 trở đi thì không còn tin vàng, bạc nào ở mức 2.
2. **Trả rỗng là kết quả đúng** (câu 3b): câu trả lời phải nói thẳng là không có tin đáng kể, không bịa tin. Lần thử trên AWS ngày 2/11 cho kết quả đúng như vậy.
3. **Không sửa dữ liệu để tin hiện ra:** không đổi `published_at`, không nâng `impact_score`. Làm vậy là sai sự thật. **Giữ ngưỡng mặc định** `min_impact = 2` và 7 ngày; câu hỏi tin tức nêu rõ khoảng ngày (Tiến, Khải đồng ý 2/11).
4. Làm mới bộ tin xong phải **deploy lại `CpawsApi`** (Tiến, 7/11), vì file JSON nằm trong gói Lambda. Sau deploy, hỏi 1 câu tin vàng có khoảng ngày chứa 7/10/2026 trên AWS: `get_news` phải trả ít nhất 1 tin. Kiểm trước bằng lệnh chạy ở máy cục bộ (Git Bash, gốc repo):

   ```bash
   python -c "from src.chatbot import news as N; print(N.get_news({'asset': 'gold', 'from_date': '2026-10-07'}, N.JsonFileNewsRepository('infra/lambda/chat_api/news')))"
   ```

Prompt v2 ghi "Mặc định lấy 7 ngày đến base_date", trong khi code và contract lấy 7 ngày đến hôm nay theo giờ Việt Nam. Nếu model tự truyền `to_date` bằng ngày cơ sở thì khoảng ngày lệch đi vài ngày. Câu 3 nêu `from_date` nên không bị ảnh hưởng; câu 3b thì xem lại `to_date` trong log khi tập dượt.

## 6. Số liệu benchmark (chỉ từ file trong repo)

**Lần chạy chính thức bộ v2 ngày 30/10: chưa đạt** ([`chatbot-benchmark-v2-2026-10.md`](../experiments/chatbot-benchmark-v2-2026-10.md), mục "Kết luận", "Bảng tiêu chí", "Hiệu năng và chi phí"; kết quả thô ở [`results/chatbot-benchmark-2026-10-30-v2/`](../experiments/results/chatbot-benchmark-2026-10-30-v2/)). Bài B chính là cấu hình chạy trong demo: Haiku, prompt v2, tool v2, nhưng chạy trên fixture.

| Chỉ số | Bài B (Haiku, prompt v2) |
|---|---|
| Câu đạt (qua kiểm tra tự động và rubric) | 14/30 (ngưỡng ≥ 25) |
| Vi phạm chính sách (tư vấn đầu tư, ngoài phạm vi) | 0 |
| Làm theo injection trong tin | 0 trên 3 |
| Gọi đúng tool | 28/30 |
| Số không có nguồn / nêu giá vàng/bạc / gắn sai nhãn "khoảng 80%" | 0 / 0 / 0 |
| Tổng thời gian mỗi câu, trung vị / p90 | 4.023 / 5.733 ms |
| Chi phí ước tính 30 câu | 0,368 USD |

- Bài A (Nova, 21/30) **không áp dụng cho demo**, vì mọi câu đi Haiku.
- Lỗi chính của bài B: diễn giải số sai (bỏ dấu âm, so sánh hai số âm ngược chiều, gọi q90 là "tăng tối đa"), thiếu phần bắt buộc, tự thêm nhận định, có câu không gọi tool cần thiết. Các loại câu ở mục 4 được chọn để tránh những lỗi này.
- Prompt v3 không dùng cho demo nên không trình bày số dev của v3. Kết quả 8 câu loại A với v2 (mục 4.1) chỉ dùng để chọn câu, không đưa lên slide benchmark.
- **Chi phí khi demo:** khoảng 0,012 USD mỗi câu (báo cáo v2, "Quyết định của Khải" mục 5). Giới hạn chung 100 lượt/ngày nên tối đa khoảng 1,2 USD/ngày (contract, mục "Giới hạn lượt hỏi").

Không so sánh Nova với Haiku: hai model làm hai việc khác nhau, chạy trên hai bộ câu hỏi khác nhau.

## 7. Phương án dự phòng

| Sự cố | Cách xử lý |
|---|---|
| PR #63 chưa deploy, hoặc `POST /chat` lỗi | Chiếu video tập dượt 7/11 và JSON response đã lưu, nói rõ là bản ghi lại |
| Web chưa gọi được API | Gọi `POST /chat` bằng `curl` với ID token của tài khoản demo (không chiếu token), chiếu JSON response |
| `503 model_unavailable` (Bedrock lỗi hoặc throttling sau khi Lambda đã tự thử lại) | Chờ khoảng 10 giây, hỏi lại một lần. Lambda không tự chuyển sang Nova (contract). Vẫn lỗi thì chuyển sang video cho câu đó, rồi thử tiếp câu sau |
| `504 timeout` | Hỏi lại một lần. Lượt đã tính không được hoàn lại. Vẫn lỗi thì chuyển sang video |
| `429` hết lượt của tài khoản (`error: rate_limited`) | Đăng nhập tài khoản tập dượt nếu còn lượt; hết thì chuyển sang video |
| `429` hết giới hạn chung 100 lượt/ngày | Không đổi được bằng tài khoản khác. Chuyển sang video. Nâng `CHAT_GLOBAL_DAILY_LIMIT` chỉ khi Tuấn đồng ý (chi phí), và đó là đổi cấu hình Lambda, Tiến làm |
| `429` do throttling của stage (thân lỗi mặc định của API Gateway) | Chờ vài giây rồi hỏi lại |
| Câu 3 không có trích nguồn | Kiểm biến môi trường của Lambda: `NEWS_TABLE_NAME` phải trống, `NEWS_DIR=/var/task/news`; kiểm bộ tin đã deploy bằng lệnh ở mục 5. Không sửa được tại chỗ thì chiếu video |
| Vàng/bạc trễ phiên (GLD/SLV chưa có phiên mới) | Chạy lại ingest tay sau vài giờ, khi nguồn đã có phiên mới; vẫn chưa có thì giữ bản ghi cũ. Chatbot phải nêu đúng ngày cơ sở, và nói dữ liệu chưa cập nhật nếu `stale_sources` khác rỗng |
| Câu trả lời sai (bỏ dấu âm, thiếu phần bắt buộc, nhãn "nghiêng") | Nói thật, ghi `request_id`, chỉ vào mục 6: đây là loại lỗi benchmark đã ghi. Không chữa lời thay chatbot |
| Mất mạng | Video tập dượt |
| Khán giả muốn hỏi thử câu ngoài kịch bản | Không gõ câu đó vào chatbot. Người trình bày trả lời bằng lời (mục 8), ghi lại câu hỏi để thử sau buổi bằng tài khoản tập dượt (Khải, ghi chú ở PR #76) |

## 8. Câu hỏi team có thể hỏi

| Câu hỏi | Ý trả lời |
|---|---|
| Sao mọi câu đi Haiku? | Router chưa có và không làm trước demo (Khải, PR #66). Đắt hơn Nova nhưng đúng chính sách; khoảng 0,012 USD/câu |
| Sao demo dùng prompt v2, không dùng v3? | Khải chốt ngày 2/11: Lambda giữ nguyên v2 đã khóa. v3 đã merge (PR #70) nhưng chưa đóng gói vào Lambda |
| Sao không hỏi thử câu ngoài phạm vi hay câu khái niệm? | Lần chạy dev 8 câu loại A với v2 ngày 2/11: câu dự đoán trong phiên chiều nay vẫn gọi `get_forecast` và trả lời bằng dự báo h = 1; câu "mốc thống kê 252 phiên" gọi `get_forecast` 4 lần. Theo cách Khải chốt, hai loại này bỏ khỏi demo. Lúc demo chỉ gõ câu trong kịch bản; câu ngoài kịch bản, kể cả câu khái niệm, người trình bày trả lời bằng lời (Khải, ghi chú ở PR #76) |
| Sao không có chữ chạy dần (streaming)? | Chọn trả một lần (Tiến, Tuấn chốt 27/10) để giữ Cognito authorizer và Lambda Python. p90 của bài B ngày 30/10 là 5.733 ms, xa dưới mốc 29 giây |
| Chatbot lấy số từ đâu? | Chỉ từ `get_forecast`, đọc thẳng bảng `Forecasts` bằng cùng hàm định dạng với `GET /forecasts/{asset}`, nên số khớp trang dự báo. `forecasts_used` cho web biết bản ghi nào đã dùng |
| Link trong câu trả lời có tin được không? | `citations` chỉ gồm tin do `get_news` trả trong lượt đó và có link xuất hiện trong `answer`. Server không lấy link từ chữ model tự viết |
| Tin có làm thay đổi dự báo không? | Không. Dự báo hiện không dùng tin tức; chatbot trình bày tin và dự báo thành hai phần riêng |
| Sao nhãn tin gắn tay? | `labeling-v3` chạy ngày 29/10 chưa đạt (direction 43/82, ngưỡng 80%; evidence 2/10, ngưỡng 8/10), nên nhãn gắn tay tới khi bảo vệ (ADR-0013) |
| Tin có chỉ dẫn độc hại thì sao? | Nội dung tin là dữ liệu không tin cậy, chỉ vào model dưới dạng kết quả tool. Bài B ngày 30/10: 0 trên 3 câu injection bị làm theo |
| Guardrail ở đâu? | Còn `DRAFT`, chưa gắn. Publish rồi mới thêm quyền `bedrock:ApplyGuardrail` và bật bộ lọc prompt attack |
| Vì sao vàng/bạc không có giá? Có giá vàng trong nước không? | Dự báo dựa trên GLD/SLV, không phải giá giao ngay. Tool không trả giá vàng/bạc; web cũng chỉ hiện % và xác suất tăng (`VITE_SHOW_METAL_PRICES=false`). Giá vàng trong nước nằm ngoài phạm vi |
| Sao không báo độ chính xác theo % giá? | Không dùng MAPE: MAPE trên mức giá luôn rất thấp vì giá mai gần bằng giá nay, nên trông như chính xác 99%. Nhóm đo bằng pinball skill so với mốc 252 phiên, độ phủ khoảng 80%, Brier skill (ADR-0008) |
| Benchmark chưa đạt mà vẫn demo? | Có, và nói rõ là chưa đạt. Lỗi chưa đạt chủ yếu là diễn giải số và thiếu ý, không có vi phạm chính sách. Bộ câu demo cố định để tránh các loại câu đã biết là yếu |

## 9. Việc cần chốt

1. ~~Khải duyệt bộ câu sau khi lọc theo loại A (PR #76)~~: **đã duyệt** (Khải, 3/11): bỏ câu ngoài phạm vi, giữ câu 0 (tùy chọn), thêm câu 5.
2. ~~Có dùng câu 0 không~~: **tùy thời lượng**; thiếu giờ thì cắt câu 0 đầu tiên (Khải, 3/11).
3. ~~Giữ hay bỏ câu 3b~~: **đã chốt giữ** (Khải, 2/11). WTI không còn tin mức 2 trở lên, nên kịch bản cần một câu cho thấy chatbot nói "không có tin đáng kể".
4. ~~Đổi ngưỡng mặc định của `get_news`~~: **đã chốt giữ** `min_impact = 2`; câu hỏi tin tức nêu rõ khoảng ngày (Tiến, Khải, 2/11).
5. ~~Người trình bày~~: **đã chốt** Phước trình bày, Tiến giữ máy như mục 3 (Khải, 3/11).
6. ~~Web chạy ở `localhost:5173` hay Amplify~~: **đã chốt** mặc định `localhost:5173`; chỉ dùng Amplify nếu Tiến deploy và thử xong trước 7/11 (Khải, 3/11). Amplify thì deploy `CpawsApi` với `-c allowed_origin=<domain>`.

## Phụ lục: phần lấy từ PR #31

PR #31 là kịch bản demo MVP 25/10. Khải đề nghị đóng (comment ngày 29/10) và chuyển phần còn dùng sang kịch bản này. Cách áp dụng 6 góp ý của Khải ngày 24/10:

| Góp ý ngày 24/10 | Trong kịch bản này |
|---|---|
| 1. EIA key ghi "sẽ lưu ở SSM (chưa cấu hình)"; "14 bảng ghi" thành `written=14` | Không nhắc, vì buổi này không trình bày ingest |
| 2. Số benchmark chỉ lấy từ file đã có trong repo | Áp dụng cho mọi số ở mục 6, có dẫn file. Không dùng số dev của v3, vì demo dùng v2 |
| 3. Câu về MAPE, bỏ RMSE | Áp dụng ở mục 8, dùng đúng câu Khải viết |
| 4. `VITE_SHOW_METAL_PRICES=false` | Chatbot cùng quy tắc với web: vàng/bạc chỉ nêu % và xác suất tăng (câu 2, mục 8). Sau PR #73, `web/.env.example` đã để `false`. Tiến chỉ cần kiểm `.env.local` của máy demo không bật lại `true` |
| 5. Xóa bản ghi mẫu không gấp, vì bản thật có `base_date` mới hơn sẽ che bản mẫu | Áp dụng gián tiếp: `forecasts_used` phải có `is_sample: false` (câu 1). Thấy `true` thì chatbot phải nói "dữ liệu mẫu" và cần kiểm lại bảng `Forecasts` |
| 6. Ingest tay khi GLD/SLV trễ phiên | Áp dụng ở mục 7 |

Phần khác lấy từ PR #31: bố cục chuẩn bị → luồng → dự phòng → hỏi đáp; quy tắc không chiếu Account ID, ARN, token và email; các câu trả lời về GLD/SLV và mốc 252 phiên.
