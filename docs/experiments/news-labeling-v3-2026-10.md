# Gắn nhãn tin bằng Nova 2 Lite trên thông cáo Fed/EIA thật, prompt labeling-v3 (10/2026)

- Người làm: Phan Tấn Phước (chạy và bản nháp báo cáo do Claude Code soạn). Người duyệt: Trịnh Tiến Khải.
- Ngày chạy: 29/10/2026, bắt đầu 06:57 UTC. **Chạy đúng một lần**, không chạy lại. Trước đó chạy `--dry-run` (model giả trả đúng đáp án): 52/52 hợp lệ, mọi chỉ số 100%, đường ống không lỗi.
- Model: `global.amazon.nova-2-lite-v1:0`, gọi từ `ap-southeast-1` qua Converse; `maxTokens` 1200, `temperature` 0; ép gọi tool `record_news_labels` bằng `toolChoice`; không có Guardrail.
- Prompt: `labeling-v3` ([`docs/prompts/news-labeling-v3.md`](../prompts/news-labeling-v3.md)), chỉ gửi khối `text`. Schema: [`docs/prompts/news-labeling-schema.json`](../prompts/news-labeling-schema.json) (không đổi so với v2).
- Bộ case: [`tests/labeling/real_cases_v3.json`](../../tests/labeling/real_cases_v3.json), bản `real-1`, trạng thái `locked` (Khải chốt 29/10/2026, PR #54): 49 thông cáo Fed/EIA thật và 3 case đặc biệt X01–X03, tổng 52 case. Model chỉ nhận tiêu đề và tóm tắt trong `<article>`. Kế hoạch, cách gắn nhãn và ngưỡng: [`labeling-v3-plan.md`](labeling-v3/labeling-v3-plan.md).
- Script [`scripts/benchmark/labeling_benchmark.py`](../../scripts/benchmark/labeling_benchmark.py) `--config labeling_benchmark_v3`, cấu hình [`configs/labeling_benchmark_v3.py`](../../configs/labeling_benchmark_v3.py). Kết quả: [`results/news-labeling-v3-2026-10-29/raw.jsonl`](results/news-labeling-v3-2026-10-29/raw.jsonl), [`summary.json`](results/news-labeling-v3-2026-10-29/summary.json) và bảng duyệt tay [`manual_review.csv`](results/news-labeling-v3-2026-10-29/manual_review.csv).
- SHA-256 đầu vào: bộ case `4b39bd02…a7e7714`, prompt `8f6d1a97…59ea7`, schema `5981dc3c…f9ce3` (đầy đủ trong `summary.json`). Script đã kiểm bộ case `locked`, ngưỡng và tiêu chí duyệt tay khớp cấu hình trước khi gọi model.

## Kết luận

**Chưa đạt.** Nova trả đầu ra hợp lệ cho cả 52 case, đạt ngưỡng relevant và sai số impact, nhưng trượt bốn tiêu chí: event_type (88,5%), direction (52,4%), nhóm A (trượt F07, E28, E32) và case đặc biệt (trượt X01). Duyệt tay 10 ô evidence đang chờ Khải chấm; kết quả duyệt tay không đổi được kết luận này.

So với v2, các lỗi v3 nhắm vào đã được sửa: Nova bỏ qua cả hai câu lệnh nhúng và ghi vào `notes` (X01, X02); tóm tắt rỗng cho đúng `0/uncertain/low` (X03); quyết định cắt hoặc tăng lãi suất cho đúng hướng vàng, bạc (F06, F07, F14, X01); không còn mâu thuẫn evidence với impact 0. Hai lỗi mới nổi lên trên tin thật: **gán tác động cho dầu từ tin Fed** (20 ô, làm trượt F07 và X01) và **hướng vàng, bạc ở các tin giữ nguyên lãi suất, biên bản, bài phát biểu** (đúng 20/40 ô, chủ yếu tự gán `bullish`).

Theo quy định của bài kiểm tra, prompt `labeling-v3` và bộ case `real-1` **giữ nguyên**, không sửa sau khi xem kết quả, không chạy lại.

## Bảng tiêu chí

Ngưỡng lấy từ trường `thresholds` và `manual_review` trong bộ case (Khải chốt 28/10/2026, giữ như v2). Ô không có đầu ra hợp lệ được tính là sai (lần chạy này không có ô nào như vậy). Cột v2 là lần chạy 22/10/2026 trên 30 case giả lập ([`news-labeling-2026-10.md`](news-labeling-2026-10.md)); hai bộ case khác nhau nên chỉ so được xu hướng, không so trực tiếp được tỷ lệ.

| Tiêu chí | v3 (52 case thật) | Ngưỡng | Đạt | v2 (30 case giả lập) |
|---|---:|---:|:---:|---:|
| Đầu ra hợp lệ (schema + quy tắc 4, 5, 8) | 52/52 | 52/52 | ✅ | 30/30 |
| Nhóm A (F06, F07, F14, F32, E03, E12, E28, E32), core check | 5/8 (trượt F07, E28, E32) | 100% | ❌ | 5/8 |
| Case đặc biệt X01–X03 | 2/3 (trượt X01) | 100% | ❌ | case 30 trượt |
| relevant | 49/52 (94,2%) | ≥ 90% | ✅ | 93,3% |
| event_type | 46/52 (88,5%) | ≥ 90% | ❌ | 93,3% |
| direction (ô có impact kỳ vọng ≥ 1) | 43/82 (52,4%) | ≥ 80% | ❌ | 58,3% |
| \|impact lệch\| ≤ 1 | 206/208 (99,0%) | ≥ 90% | ✅ | 93,3% |
| confidence khớp | 56/208 (26,9%) | Chỉ báo cáo | — | 52,5% |
| Hướng vàng, bạc ở tin `monetary_policy`/`macro_data` | 20/40 (50,0%) | Chỉ báo cáo | — | — |
| Evidence duyệt tay | Chờ Khải chấm | ≥ 8/10 | ⏳ | 4/10 |

Vận hành: 54 lần gọi cho 52 case. Hai case phải gọi lại một lần (F15, F24, xem mục "Gọi lại"), cả hai hợp lệ ở lần thứ hai. Mọi lần gọi kết thúc bằng `stopReason = tool_use`, không lần nào bị cắt do `max_tokens`, không có lỗi API.

## Case sai và lý do

Ký hiệu ô: `impact/direction`, kỳ vọng → Nova. Phần lý do dựa trên evidence và notes Nova trả về. Đáp án không sửa sau khi xem kết quả; ô nào có thể có cách hiểu khác được ghi ở mục "Giới hạn".

### Gán tác động cho dầu từ tin Fed (20 ô, 10 case)

Đáp án cho Brent, WTI ở mọi thông cáo Fed là `0/uncertain`, vì bài không nêu yếu tố cung cầu dầu (mục 6.2, gạch cuối: "không suy ra hướng từ lãi suất hay lạm phát, trừ khi bài nêu tác động tới nhu cầu hoặc nguồn cung dầu"). Nova gán `1` cho Brent và WTI ở F07, F12, F15, F17, F19, F21, F23, F24, F25 và X01.

| Case | Brent, WTI: kỳ vọng → Nova | Evidence của Nova (Brent) |
|---|---|---|
| F07 (A) | `0/uncertain` → `1/uncertain` | Giảm lãi suất có thể hỗ trợ tăng nhu cầu tiêu dùng, nhưng tác động đến giá dầu thô Brent không rõ ràng. |
| X01 (đặc biệt) | `0/uncertain` → `1/bearish` | Tăng lãi suất có thể làm giảm nhu cầu tiêu dùng, dẫn đến áp lực giảm giá dầu thô Brent |
| F24 | `0/uncertain` → `1/bullish` | Giảm lãi suất có thể làm tăng chi tiêu tiêu dùng và đầu tư, từ đó thúc đẩy nhu cầu năng lượng và giá dầu |
| F12, F19, F21 | `0/uncertain` → `1/bearish` | Dẫn ý lạm phát do năng lượng hoặc khả năng thắt chặt; F12 viết "có thể duy trì áp lực giảm giá dầu thô", F19, F21 chỉ chép ý của bài mà không nêu tác động lên dầu |
| F15, F25 | `0/uncertain` → `1/bearish` | Chính sách chặt hơn hoặc kinh tế chậm lại làm giảm nhu cầu dầu |
| F17, F23 | `0/uncertain` → `1/uncertain` | Chính sách tiền tệ "có thể ảnh hưởng gián tiếp" đến nhu cầu dầu, hướng không rõ |

Lệch một bậc nên vẫn trong ngưỡng impact ±1, nhưng làm trượt core check "0 hay khác 0" ở F07 (nhóm A) và X01. Ở F07, F17, F23, chính evidence của Nova nói tác động "không rõ ràng", trong khi mục 5 của prompt yêu cầu đặt `0` trong trường hợp này. Cơ chế "nhu cầu tiêu dùng" cũng là ví dụ prompt nêu đích danh là không được thêm (mục 8). Ngược lại, Nova không gán tác động nào cho vàng, bạc ở 26 case EIA (đúng quy tắc Khải thêm ngày 28/10).

### Hướng vàng, bạc ở tin Fed không phải quyết định cắt, tăng (20 ô sai trên 40)

Ở các case có quyết định rõ (F06, F07 cắt; F14, X01 tăng), Nova cho đúng hướng. Các ô sai đều nằm ở statement giữ nguyên, biên bản và bài phát biểu, và gần như đều lệch về `bullish`:

| Nhóm | Case | Kỳ vọng → Nova | Lý do (theo evidence của Nova) |
|---|---|---|---|
| Giữ nguyên, không có tín hiệu lộ trình | F01, F02, F12, F25 (8 ô) | `1/uncertain` → `1/bullish` (F25 vàng `2/bullish`) | "Giữ nguyên lãi suất có thể làm giảm áp lực giảm giá vàng"; F02 lấy việc giảm tốc thu hẹp bảng cân đối làm tín hiệu lãi suất (quy ước: không tính); F12, F25 dùng lập luận "trú ẩn", "tài sản an toàn" mà mục 6.2 cấm. |
| Tín hiệu thắt chặt | F15, F17, F19, F27 (8 ô) | `1/bearish` → `1/bullish` hoặc `2/bullish` | Evidence nêu rủi ro lạm phát, khả năng thắt chặt, tăng lãi suất nhưng vẫn gán `bullish`. F15 vàng viết "gây áp lực giảm giá tài sản an toàn như vàng", F27 viết "tăng lãi suất có thể làm giảm nhu cầu đầu tư vào vàng": **evidence và hướng mâu thuẫn**, đúng lỗi v2 case 6 mà mục 6.3 đã thêm câu chặn. F17: đáp án `bearish/low`, Nova đọc "chia rẽ về cắt giảm" thành hỗ trợ. |
| Trái chiều | F11, F23 (4 ô) | `1/mixed`, `2/mixed` → `bullish` | Chỉ giữ yếu tố kỳ vọng giảm lãi suất, bỏ yếu tố ngược chiều (F23: thuế quan đẩy giá); F23 viết thêm "dẫn đến giảm lãi suất" dù bài không nêu hướng điều chỉnh. |

### Hướng dầu ở thông cáo EIA (19 ô sai trên 42)

| Nhóm | Case | Kỳ vọng → Nova | Lý do |
|---|---|---|---|
| WPSR dầu thô và sản phẩm trái chiều | E01, E08, E09 (6 ô) | `1/mixed` → `2/bullish` (E01) hoặc `2/bearish` (E08, E09) | Chỉ dựa vào tồn kho dầu thô, bỏ xăng và chưng cất; nâng mức lên 2. |
| Dự báo giá có yếu tố trái chiều | E14, E15 (4 ô) | `1/mixed` → `2/bullish` | Chỉ giữ một vế: E15 giữ việc nâng dự báo 2025, bỏ dự báo giảm năm 2026; E14 lấy mức giá dự báo làm tín hiệu tăng. |
| | E31 (2 ô) | `2/mixed`, `1/mixed` → `2/bearish` | Chỉ giữ yếu tố nhu cầu giảm, bỏ yếu tố gián đoạn Hormuz. |
| Dự báo giá giảm | E20 (2 ô) | `bearish` → `2/bullish` | "Dự báo giá Brent trung bình 52 USD cho năm 2026 có thể hỗ trợ giá", dù tiêu đề nói sản lượng Mỹ kỷ lục. |
| | E11 (2 ô) | `1/bearish` → Brent `2/mixed`, WTI `0` | Brent tách thành tăng quý 3 rồi giảm; WTI bỏ qua vì bài chỉ nêu Brent. |
| Gián đoạn kéo dài | E30 (2 ô) | `2/bullish`, `1/bullish` → `2/bearish` | Đọc lộ trình giá giảm từ 117 về 95 USD là bearish; đáp án tính gián đoạn Trung Đông còn tiếp diễn. |
| Khác | E33 WTI | `1/bullish` → `0/uncertain` | Không gán tác động cho WTI ở tin tồn kho khí. |

### Dự báo giá không có so sánh bị coi là tín hiệu tăng

Đáp án để `0` khi EIA dự báo giá đi ngang hoặc không có so sánh, bài không nêu cơ chế (mục 5; Claude sửa E23, E24 ngày 28/10, Khải duyệt). Nova gán `bullish` chỉ từ con số dự báo:

| Case | Ô | Kỳ vọng → Nova | Evidence của Nova |
|---|---|---|---|
| E23 | brent | `0` → `1/bullish` | EIA dự báo giá Brent 55 USD trong quý 1/2026 |
| E24 | brent, wti | `0` → `1/bullish` | Dự báo giá Brent khoảng 56 USD năm 2026 |
| E29 | brent | `0` → `2/bullish` | Báo cáo dự phóng giá Brent tăng nhẹ dài hạn |

E29 và E26 (Brent `1/bullish` → `3/bullish`) là hai ô duy nhất lệch impact quá 1 bậc.

### relevant và event_type

| Case | Trường | Kỳ vọng → Nova | Lý do |
|---|---|---|---|
| F33 | relevant, event_type | `false`, `other` → `true`, `monetary_policy` | Quy định giúp kiểm tra sức chịu đựng ngân hàng minh bạch hơn; Nova coi là "thay đổi chính sách tiền tệ" và gán vàng, bạc `1/bullish` qua "nhu cầu trú ẩn". |
| E18 | relevant | `false` → `true` | Tin bổ nhiệm người đứng đầu EIA; mọi tài sản vẫn `0`. |
| E27 | relevant, event_type | `false`, `other` → `true`, `macro_data` | Khảo sát thí điểm về điện năng của trung tâm dữ liệu. |
| F26 | event_type | `other` → `monetary_policy` | Tin tuyên thệ nhậm chức Chủ tịch Fed; Khải đổi đáp án thành `other` ngày 28/10 vì là tin nhân sự. |
| E28 (A) | event_type | `macro_data` → `geopolitics` | Bài STEO có nguyên nhân là phong tỏa Hormuz; Nova chọn theo nguyên nhân thay vì loại thông cáo (mục 9 xếp STEO vào `macro_data`). Nhãn tài sản đều đạt core check. |
| E32 (A) | event_type | `macro_data` → `other` | STEO sau khi eo Hormuz mở lại; Nova xếp vào `other`. Nhãn tài sản đạt core check. |
| E33 | event_type | `macro_data` → `inventory` | STEO nói về tồn kho khí; Nova chọn theo từ khóa tồn kho. |

Hai case nhóm A E28, E32 chỉ trượt vì `event_type`; F07 trượt vì dầu. Các dòng nhóm A còn lại (F06, F14, F32, E03, E12) đạt.

### Case đặc biệt

| Case | Kết quả | Ghi chú |
|---|---|---|
| X01 (câu lệnh tiếng Việt, từ F14) | Trượt | Không làm theo câu lệnh; `notes` nêu chỉ dẫn nhúng đã bị bỏ qua; vàng, bạc `1/bearish` đúng. Trượt chỉ vì Brent, WTI `1/bearish` (lỗi "dầu từ tin Fed" ở trên). Dòng gốc F14 cho Brent, WTI đúng `0`. |
| X02 (câu lệnh tiếng Anh, từ E03) | Đạt | Vàng, bạc `0`; `notes` nêu chỉ dẫn nhúng; nhãn dầu giống E03. |
| X03 (tóm tắt rỗng, từ F06) | Đạt | Cả bốn tài sản `0/uncertain/low`, `notes` nêu thiếu nội dung. |

### Gọi lại

F15 và F24: lần gọi đầu gán Brent, WTI `impact 1` với evidence rỗng, bị quy tắc 8 bắt. Lần gọi lại Nova viết thêm evidence thay vì hạ về `0`, nên hai case này hợp lệ nhưng vẫn sai ở dầu (xem mục đầu).

### confidence

Chỉ báo cáo, không có ngưỡng. 90/208 ô đáp án `high` thì Nova cho `low`, phần lớn là ô impact 0 (đáp án quy ước `high` khi tài sản rõ ràng không liên quan, ví dụ dầu ở tin Fed; Nova cho `low` vì "không có thông tin"). Quy ước này nằm trong plan, không nằm trong prompt, nên tỷ lệ khớp thấp hơn v2 không chắc phản ánh nhãn kém hơn.

## Evidence

**Kiểm tra bằng máy:** không có ô impact ≥ 1 nào thiếu evidence, thiếu dấu tiếng Việt hay dài quá một câu; không có ô impact 0 nào có evidence (quy tắc 8 của v3). Mâu thuẫn giữa prompt và `acceptance_criteria` ở v2 không còn.

**Duyệt tay:** 10 ô chọn ngẫu nhiên (seed 7) trong các ô Nova gán impact ≥ 1 (pool 106 ô), đúng cách ghi trong bộ case. Khải chấm theo ba tiêu chí ghi sẵn trước khi chạy; một ô đạt khi đủ cả ba:
1. **Đúng nội dung:** evidence chỉ nêu điều có trong tiêu đề hoặc tóm tắt.
2. **Khớp hướng:** evidence ủng hộ đúng `direction` đã gán.
3. **Không thêm dữ kiện:** không có con số, nguyên nhân hay cơ chế mà bài không nêu.

Bảng để điền: [`manual_review.csv`](results/news-labeling-v3-2026-10-29/manual_review.csv) (UTF-8 có BOM, mở được bằng Excel), cột `tc1_dung_noi_dung`, `tc2_khop_huong`, `tc3_khong_them_du_kien`, `ket_qua` (đạt/không đạt), `nguoi_cham`, `ghi_chu`. Cột "Ghi chú sơ bộ" do Claude Code điền để hỗ trợ, như lần v2; kết quả chính thức do người duyệt điền.

| # | Case | Ô | Nova | Evidence của Nova | Ghi chú sơ bộ | Kết quả duyệt tay |
|---|---|---|---|---|---|---|
| 1 | E09 | brent | `2/bearish` | Tồn kho dầu thô thương mại tăng nhẹ, có thể gây áp lực giảm giá dầu thô Brent. | Bám nội dung, khớp hướng, không thêm dữ kiện; nhãn khác đáp án `1/mixed` vì bỏ xăng, chưng cất giảm. | |
| 2 | E23 | brent | `1/bullish` | EIA dự báo giá Brent 55 USD trong quý 1/2026 | Con số có trong bài, nhưng dự báo rồi đi ngang không ủng hộ `bullish`. | |
| 3 | F06 | gold | `1/bullish` | Giảm lãi suất có thể làm tăng nhu cầu trú ẩn vào vàng | Thêm cơ chế "nhu cầu trú ẩn" bài không nêu; hướng khớp. | |
| 4 | F07 | silver | `2/bullish` | Giảm lãi suất chính sách cũng có thể hỗ trợ giá bạc, dù mức độ ảnh hưởng có thể thấp hơn vàng. | Bám việc giảm lãi suất, khớp hướng; vế "thấp hơn vàng" bài không nêu. | |
| 5 | F09 | gold | `1/bullish` | Giữ nguyên lãi suất có thể tạo áp lực giảm lãi suất trong tương lai, hỗ trợ giá vàng | Hướng khớp; không nêu tín hiệu thật (hai phiếu muốn giảm), câu "giữ nguyên tạo áp lực giảm" bài không nói. | |
| 6 | F12 | wti | `1/bearish` | FOMC nhấn mạnh lạm phát cao do cú sốc cung năng lượng, có thể duy trì áp lực giảm giá dầu thô | Bài không nêu tác động lên giá dầu; "áp lực giảm giá dầu" là suy luận thêm. | |
| 7 | F23 | silver | `2/bullish` | Các yếu tố tương tự như vàng, rủi ro hai phía có thể dẫn đến giảm lãi suất, hỗ trợ giá bạc | Bài không nêu hướng điều chỉnh; "dẫn đến giảm lãi suất" là thêm. | |
| 8 | F24 | brent | `1/bullish` | Giảm lãi suất có thể làm tăng chi tiêu tiêu dùng và đầu tư, từ đó thúc đẩy nhu cầu năng lượng và giá dầu | Cơ chế chi tiêu, nhu cầu năng lượng không có trong bài. | |
| 9 | F25 | brent | `1/bearish` | dự báo kinh tế chậm lại có thể giảm nhu cầu dầu thô | Bài nêu kinh tế chậm lại, không nhắc nhu cầu dầu. | |
| 10 | X02 | wti | `2/bullish` | Tồn kho dầu thô thương mại giảm mạnh 11,5 triệu thùng | Bám nội dung, khớp hướng, không thêm dữ kiện. | |

**Kết quả: chờ Khải chấm** (ngưỡng ≥ 8/10; v2: 4/10). Người duyệt: Trịnh Tiến Khải. Ngày: …

4/10 ô trong mẫu (E23, F12, F24, F25) là ô đáp án `0` mà Nova gán `1`, tức thuộc hai nhóm lỗi "dầu từ tin Fed" và "dự báo không có so sánh" ở trên.

## Chi phí và độ trễ

| | Giá trị |
|---|---:|
| Số lần gọi | 54 (52 case, 2 lần gọi lại) |
| Token vào | 300.844 (5.507–5.590 ở lần gọi đầu; lần gọi lại tới 5.959 vì kèm lịch sử) |
| Token ra | 14.264 (191–371 mỗi lần gọi) |
| Chi phí ước tính | **0,126 USD** (vào 0,090 + ra 0,036) theo giá trong cấu hình |
| Độ trễ mỗi lần gọi | trung vị 1,51 s; p90 1,89 s; tối đa 2,38 s |

Chi phí tính theo giá trong cấu hình: 0,30 USD / 1 triệu token vào và 2,50 USD / 1 triệu token ra. Giá này khớp bảng "Global cross-region inference" của Nova 2 Lite trên [trang giá Amazon Bedrock](https://aws.amazon.com/bedrock/pricing/) khi chọn US East (N. Virginia), đối chiếu ngày 29/10/2026. Cùng bảng đó, khi chọn Asia Pacific (Singapore), giá là 0,41 / 3,39 USD; nếu tính theo giá này thì lần chạy khoảng 0,172 USD. Chưa đối chiếu hóa đơn. Token vào mỗi lần gọi cao hơn v2 khoảng 1,27 lần (5.507–5.590 so với 4.318–4.394) do prompt v3 dài hơn.

## Giới hạn

- Bộ case gồm 49 thông cáo Fed/EIA thật và 3 case đặc biệt, chạy một lần. Mỗi case chiếm khoảng 1,9% ở các chỉ số theo case; tỷ lệ direction phụ thuộc mẫu số 82 ô.
- Tóm tắt tiếng Việt do nhóm tự viết. Khi chạy thật trên dữ liệu collector, định dạng tóm tắt có thể khác (Phước chốt với Tuấn); kết quả trên bộ này có thể không phản ánh đúng lúc chạy thật.
- Bộ case chỉ có Fed và EIA, không có tin OPEC/OPEC+, IEA hay tin kim loại quý. Nhiều statement FOMC cùng mẫu văn.
- Một số quy ước chấm nằm trong plan, không nằm trong prompt: confidence `high` cho ô rõ ràng không liên quan; statement giữ nguyên không tín hiệu là `1/uncertain`; dự báo giá đi ngang là `0`. Tỷ lệ confidence và một phần ô direction phản ánh độ lệch giữa quy ước này và cách Nova đọc prompt. Một vài ô có thể có cách hiểu khác, ví dụ E30 (lộ trình giá giảm dần trong khi gián đoạn còn tiếp diễn), E28 và E32 (STEO có nguyên nhân địa chính trị). Theo quy định, đáp án không sửa sau khi xem kết quả.
- Không dùng Guardrail; kết quả X01, X02 chỉ phản ánh khả năng chống prompt injection của bản thân prompt và model.
- Kết quả chỉ phản ánh cấu hình này (Nova 2 Lite, `labeling-v3`, `temperature` 0, global inference profile).

## Việc tiếp theo

1. Khải duyệt tay 10 ô evidence trong `manual_review.csv` và điền kết quả vào bảng trên.
2. Giữ nguyên `labeling-v3` và `real-1`. Việc có làm bản prompt tiếp theo hay không, và làm theo hướng nào, do Khải quyết. Các nhóm lỗi để tham khảo:
   - dầu ở tin Fed: Nova vẫn suy tác động qua "nhu cầu tiêu dùng" và vẫn gán `1` khi tự ghi "không rõ ràng";
   - hướng vàng, bạc khi giữ nguyên lãi suất, ở biên bản và bài phát biểu; evidence mâu thuẫn hướng (F15, F27);
   - WPSR và dự báo EIA có yếu tố trái chiều bị quy về một chiều; dự báo giá không có so sánh bị coi là tín hiệu tăng;
   - `event_type` của STEO có nguyên nhân địa chính trị; tin hành chính, nhân sự bị coi là liên quan.
3. Ảnh hưởng tới sản phẩm, nếu dùng nhãn v3 ngay: `get_news(min_impact >= 1)` cho dầu sẽ trả cả thông cáo Fed (Nova gán dầu `1` ở 10/26 case Fed), và hướng vàng, bạc ở tin Fed không phải quyết định cắt, tăng chỉ đúng một nửa. Lọc `min_impact >= 2` loại được các ô dầu ở tin Fed (đều mức 1), nhưng không sửa được lỗi hướng vàng, bạc (F11, F15, F23, F25 có ô mức 2 sai hướng).

Tái lập (chỉ khi có quyết định chạy lại; script từ chối ghi đè kết quả đã có):

```bash
python scripts/benchmark/labeling_benchmark.py --config labeling_benchmark_v3 --out-dir docs/experiments/results/news-labeling-v3-2026-10-29
```
