# ADR-0013: Gắn nhãn tin bằng tay tới khi bảo vệ

- Ngày: 2026-10-30
- Trạng thái: Đã chấp nhận (họp 30/10/2026, điểm 17 trong báo cáo tuần 3)
- Người viết: Phan Tấn Phước; người duyệt: Trịnh Tiến Khải

## Bối cảnh

Kiến trúc 19 bước có bước "Bedrock gắn nhãn tin": collector lấy thông cáo Fed/EIA, Nova 2 Lite gắn nhãn, kết quả ghi vào bảng `NewsLabels` để tool `get_news` của chatbot đọc. ADR-0004 mục 2 chọn Nova 2 Lite cho việc này. Trước khi đưa lên production, prompt phải đạt toàn bộ ngưỡng chốt trước khi chạy. Hai lần kiểm đều chưa đạt.

**labeling-v2 (22/10/2026), 30 case giả lập** ([`news-labeling-2026-10.md`](../experiments/news-labeling-2026-10.md)). Chạy một lần. Trượt direction (28/48 = 58,3%, ngưỡng ≥ 80%), nhóm A (trượt case 6, 7, 30) và case 30 (Nova làm theo câu lệnh nhúng). Evidence duyệt tay 4/10.

**labeling-v3 (29/10/2026), 49 thông cáo Fed/EIA thật và 3 case đặc biệt** ([`news-labeling-v3-2026-10.md`](../experiments/news-labeling-v3-2026-10.md), PR #58). Bộ case `real-1` đã khóa trước khi chạy (PR #54). Chạy đúng một lần, model `global.amazon.nova-2-lite-v1:0`.

| Tiêu chí | Kết quả v3 | Ngưỡng | Đạt |
|---|---:|---:|:---:|
| Đầu ra hợp lệ | 52/52 | 52/52 | ✅ |
| relevant | 49/52 (94,2%) | ≥ 90% | ✅ |
| \|impact lệch\| ≤ 1 | 206/208 (99,0%) | ≥ 90% | ✅ |
| event_type | 46/52 (88,5%) | ≥ 90% | ❌ |
| direction | 43/82 (52,4%) | ≥ 80% | ❌ |
| Nhóm A | 5/8 (trượt F07, E28, E32) | 100% | ❌ |
| Case đặc biệt X01–X03 | 2/3 (trượt X01) | 100% | ❌ |
| Evidence duyệt tay (Khải chấm) | 2/10 | ≥ 8/10 | ❌ |

v3 sửa được các lỗi v2 nhắm tới (bỏ qua câu lệnh nhúng, tóm tắt rỗng, hướng vàng/bạc khi Fed cắt hoặc tăng lãi suất). Hai lỗi mới nổi lên trên tin thật:

- Nova gán tác động cho Brent, WTI từ tin Fed (20 ô ở 10 case), làm trượt F07 và X01.
- Hướng vàng, bạc ở tin giữ nguyên lãi suất, biên bản và bài phát biểu chỉ đúng 20/40 ô, phần lớn tự gán `bullish`.

Theo Khải, 7/8 ô evidence trượt do Nova tự thêm cơ chế kinh tế mà bài không nêu, giống lỗi chính của v2.

Nếu dùng nhãn v3 ngay, `get_news(min_impact >= 1)` cho dầu sẽ trả cả thông cáo Fed, còn hướng vàng, bạc ở tin Fed không phải quyết định cắt, tăng chỉ đúng một nửa (mục "Việc tiếp theo" của báo cáo v3). Chatbot sẽ đưa lý do sai cho người dùng.

Ràng buộc: còn ít thời gian tới bảo vệ; lượng tin cần cho demo nhỏ (2–3 thông cáo mỗi tuần); bộ 49 thông cáo v3 là bộ kiểm duy nhất trên tin thật, mỗi lần chạy lại để thử prompt mới làm giảm giá trị của nó như một bộ kiểm độc lập.

## Các phương án

1. **Viết prompt v4 và chạy lại trước bảo vệ.** Ưu: giữ được bước gắn nhãn tự động. Nhược: phải soạn prompt, duyệt, chạy và duyệt tay evidence lại, không kịp lịch; không chắc đạt, vì lỗi thêm cơ chế lặp lại qua hai phiên bản; mỗi lần chạy lại trên bộ 49 thông cáo là thêm một lần "nhìn" bộ case, kết quả lần sau khó coi là kiểm độc lập. Bỏ.
2. **Gắn nhãn tay, nhưng để Nova viết tóm tắt tiếng Việt.** Ưu: Phước bớt việc. Nhược: tóm tắt là đầu vào của nhãn và là chữ chatbot đưa cho người dùng; Nova đang tự thêm dữ kiện ở evidence nên chưa tin được ở tóm tắt; vẫn cần quyền `bedrock:InvokeModel` cho collector. Bỏ tới khi bước gắn nhãn tự động đạt.
3. **Gắn nhãn tay toàn bộ (tóm tắt và nhãn), collector không gọi Bedrock.** Ưu: nhãn đúng quy ước đã được Khải duyệt; không tốn token; collector bớt một quyền. Nhược: phụ thuộc người, chỉ làm được vài bài mỗi tuần; trễ từ lúc công bố tới lúc có nhãn. Chọn.

## Quyết định

Chọn phương án 3. Bước "Bedrock gắn nhãn tin" **không chạy trên production tới khi bảo vệ**. Nhãn tin do Phước gắn tay.

### Phạm vi tin

Phước gắn 2–3 bài mỗi tuần, chỉ từ các loại sau:

- Fed: FOMC statement, FOMC minutes.
- EIA: Weekly Petroleum Status Report (WPSR), STEO và các bài dự báo, Today in Energy (chỉ bài về dầu).

### Luồng dữ liệu

1. Collector (PR #52, Tuấn) lấy bài và ghi vào hàng chờ S3 `pending/<article_id>.json`. Collector **không gọi Bedrock**.
2. Phước đọc bài gốc, viết tóm tắt tiếng Việt (1–2 câu, tối đa 300 ký tự, tự viết, không chép đoạn văn gốc) và nhãn, rồi ghi file `labels/<article_id>.json`.
3. Lần chạy sau, collector thấy file nhãn thì `PutItem` vào bảng `NewsLabels`. File trong S3 là marker cho biết bài đã có nhãn (theo góp ý của Tiến ở #52).

Định dạng `labels/<article_id>.json` theo đúng schema của một phần tử `cases` trong [`tests/labeling/real_cases_v3.json`](../../tests/labeling/real_cases_v3.json): `source`, `release_type`, `published_at_utc`, `url`, `title`, `summary`, và `expected` gồm `relevant`, `event_type`, `notes`, `asset_labels` cho cả bốn tài sản (`impact_score`, `direction`, `confidence`, `evidence`). Khóa định danh là `article_id` thay cho `case_id`; trường `group` chỉ dùng cho benchmark. Thêm trường `labeled_at_utc` (thời điểm ghi file nhãn, ISO 8601 UTC); trường này chỉ có trong file trên S3, không đổi schema `NewsLabels`. Nhãn tay mang `prompt_version = "manual-v3"` để chatbot và báo cáo phân biệt với nhãn Nova. Cách ánh xạ còn lại sang item `NewsLabels` (ví dụ chuẩn hóa `published_at` về dạng `YYYY-MM-DDTHH:MM:SSZ` của contract) chốt với Tuấn trong #52.

### Quyền IAM

- Phước có `s3:GetObject` trên `pending/*`, `s3:ListBucket` có điều kiện `s3:prefix = pending/` (để biết bài nào đang chờ) và `s3:PutObject` trên `labels/*` của bucket hàng chờ (Tuấn cấp, chốt trong comment #52 ngày 30/10). Không có quyền ghi `NewsLabels`.
- Role của collector bỏ `bedrock:InvokeModel`.

### Quy ước gắn nhãn

- Theo [`labeling-v3-plan.md`](../experiments/labeling-v3/labeling-v3-plan.md), mục "Gắn nhãn" (bảng quy ước vàng/bạc, Brent/WTI và mức `confidence`) và các quy tắc của prompt `labeling-v3` mà plan dẫn tới.
- Chỉ gắn theo nội dung thông cáo. **Không nhìn giá sau ngày công bố**, để nhãn không mang thông tin tương lai (ADR-0003 mục 5). Đây chỉ là cố gắng: nhãn tay viết sau khi công bố, có khi vài ngày, nên người gắn khó tránh biết diễn biến giá.

### Point-in-time khi dùng nhãn cho mô hình

- Với chatbot, nhãn được dùng như hiện có, không cần điều chỉnh.
- Nếu sau này dùng nhãn làm đặc trưng hoặc trong backtest, thời điểm nhãn khả dụng là `max(published_at, labeled_at_utc)`, không phải `published_at`.
- Nhãn tay **không dùng để đánh giá dự báo** trước khi bảo vệ.

### Quan hệ với ADR khác

Không sửa ADR-0003 và ADR-0004. Tới khi bảo vệ, ADR này thay thế các phần sau:

- **ADR-0003 mục 4:** câu "Nhãn phản ánh nội dung và đánh giá của mô hình tại thời điểm xử lý" và câu nói prompt hiện hành là `labeling-v2`. Nhãn trên production là nhãn tay theo quy ước v3; metadata `model_id` không áp dụng. Phần còn lại của mục 4 (các trường `relevant`, `asset`, `impact_score`, `direction`, `confidence`, `event_type`) giữ nguyên.
- **ADR-0003 mục 3:** "thu thập, gắn nhãn và truy xuất" vẫn đúng, nhưng bước gắn nhãn là gắn tay.
- **ADR-0004 mục 2:** "Nova 2 Lite được sử dụng cho tác vụ gắn nhãn tin tức trong MVP" tạm dừng. Phần ước tính chi phí gắn nhãn (9,50 USD/tháng) không phát sinh.

Nguồn tin (ADR-0003 mục 2), quy tắc lưu trữ (chỉ tiêu đề, tóm tắt tự viết, link) và point-in-time (mục 5) giữ nguyên.

## Hệ quả

**Dễ hơn**

- Chatbot `get_news` đọc nhãn tay qua bảng `NewsLabels`, cùng schema 7 trường trong [`docs/api/contract.md`](../api/contract.md). Lambda chat không phải đổi gì.
- Nhãn trên production theo đúng quy ước Khải đã duyệt; không có lỗi "dầu từ tin Fed" hay evidence tự thêm cơ chế.
- Collector không cần quyền Bedrock, không tốn token gắn nhãn.
- Slide bảo vệ trình bày v2 và v3 như kết quả âm có kiểm soát: đáp án và ngưỡng chốt trước, chạy một lần, không sửa sau khi xem kết quả, và nhóm đổi thiết kế dựa trên kết quả đó.

**Khó hơn và rủi ro**

- Số tin ít (2–3 bài mỗi tuần) và có độ trễ tới khi Phước gắn nhãn. Ngoài khung giờ đó, `get_news` có thể trả rỗng; chatbot phải nói không tìm thấy tin đáng kể (contract đã quy định).
- Phụ thuộc một người. Nếu Phước không gắn được trong tuần, bài nằm trong `pending/` và không lên chatbot.
- Một người gắn nhãn, không có người duyệt độc lập cho từng bài như bộ case v3. Rủi ro sai nhãn; Phước ghi `notes` cho bài khó.
- Kiến trúc 19 bước trên slide phải ghi rõ bước gắn nhãn chạy bằng tay tới khi bảo vệ.

**Điều kiện quay lại gắn nhãn tự động**

Chỉ khi một prompt mới đạt **toàn bộ** ngưỡng trên bộ 49 thông cáo v3 đã khóa (`real-1`, gồm cả nhóm A, case đặc biệt và evidence duyệt tay ≥ 8/10), và phải có ADR mới thay thế ADR này.
