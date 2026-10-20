# ADR-0003: News and Signal Sources

- **Date:** 2026-10-19
- **Status:** Chấp nhận cho MVP

## Bối cảnh

Dự án cần dữ liệu tin tức và các tín hiệu thị trường để hỗ trợ phân tích biến động giá Gold, Silver, Brent và WTI. Nguồn dữ liệu phải có thể truy cập bằng API, có thời gian công bố rõ ràng và phù hợp với quy mô MVP.

GDELT có độ phủ rộng nhưng chứa nhiều tin nhiễu. DOC API cũng có giới hạn về khoảng thời gian truy vấn, nên không phù hợp làm nguồn duy nhất cho toàn bộ dữ liệu lịch sử. Ngoài ra, tin tức cần được gắn nhãn theo từng tài sản để chatbot và các thành phần phân tích có thể truy xuất thông tin phù hợp.

## Quyết định

### 1. Nguồn dữ liệu tín hiệu thị trường

Ưu tiên các nguồn sau:

- **GPR:** chỉ số Geopolitical Risk để theo dõi rủi ro địa chính trị.
- **FRED:** các chuỗi OVX, GVZ và VIX để theo dõi biến động kỳ vọng của thị trường dầu, vàng và chứng khoán.
- **Lịch sự kiện chính thức:** lịch FOMC, OPEC+ và EIA để xác định các sự kiện có khả năng ảnh hưởng đến thị trường.

Các nguồn này cung cấp tín hiệu bổ sung cho dữ liệu giá, không được xem là bằng chứng trực tiếp về quan hệ nhân quả với biến động giá.

### 2. Nguồn tin tức

Ưu tiên các nguồn có thể truy xuất và xác định thời điểm công bố:

- Guardian API.
- New York Times API.
- Thông báo chính thức từ các tổ chức liên quan.
- RSS tiếng Việt phù hợp với nhu cầu của chatbot.

GDELT chỉ được dùng làm nguồn bổ sung khi có bộ lọc hoặc danh sách domain đáng tin cậy nhằm hạn chế tin nhiễu.

### 3. Phạm vi MVP

MVP cung cấp hàm `get_news(asset, from_date, to_date, min_impact)` để truy xuất tin tức theo tài sản, khoảng thời gian và ngưỡng tác động tối thiểu.

MVP chưa yêu cầu xây dựng Knowledge Base hoặc embedding vector cho toàn bộ tin tức. Trước tiên, hệ thống tập trung vào việc thu thập, gắn nhãn và truy xuất các bài viết có liên quan.

### 4. Schema gắn nhãn tin tức

Mỗi bài viết có trường `relevant` ở cấp bài viết để xác định bài đó có liên quan đến phạm vi dự án hay không.

Mức độ tác động được đánh giá riêng cho từng tài sản:

- `asset`: Gold, Silver, Brent hoặc WTI.
- `impact_score`: số nguyên từ 0 đến 3.
- `direction`: hướng tác động được đánh giá, chẳng hạn `positive`, `negative`, `mixed` hoặc `neutral`.
- `confidence`: mức độ tin cậy của nhãn.
- `event_type`: loại sự kiện.
- `prompt_version`: phiên bản prompt đã dùng để gắn nhãn.

Metadata bổ sung gồm `published_at`, `labeled_at` và `model_id`. Prompt gắn nhãn được quản lý tại [`docs/prompts/news-labeling-v1.md`](../prompts/news-labeling-v1.md).

Nhãn phản ánh nội dung và đánh giá của mô hình tại thời điểm xử lý, không khẳng định bài viết đã gây ra biến động giá.

### 5. Xử lý thời điểm công bố

Tin được công bố sau giờ đóng cửa của thị trường tương ứng sẽ được xem xét cho phiên giao dịch kế tiếp. Quy tắc này cần được triển khai trong logic ứng dụng dựa trên lịch giao dịch của từng tài sản, tránh sử dụng thông tin chưa khả dụng tại thời điểm dự báo.

### 6. Lưu trữ và truy xuất nhãn

Đề xuất sử dụng bảng DynamoDB `NewsLabels` với cấu trúc khóa:

- Partition key (PK): `asset`.
- Sort key (SK): `published_at#article_id`.

Cấu trúc này là đề xuất cho MVP và cần được xác nhận với `@hngtuan2kar5-prog` trước khi chốt thiết kế triển khai.

## Hệ quả

### Ưu điểm

- Có nguồn tin và tín hiệu thị trường được xác định rõ ràng.
- Giảm sự phụ thuộc vào một nguồn tin duy nhất.
- Cho phép truy xuất tin theo tài sản, thời gian và mức độ tác động.
- Có thể theo dõi phiên bản prompt để đánh giá tính nhất quán của nhãn.

### Hạn chế và rủi ro

- API có thể có giới hạn truy cập, quota hoặc yêu cầu xác thực.
- Chất lượng nhãn phụ thuộc vào nội dung bài viết và mô hình được sử dụng.
- Các nguồn tin khác nhau có thể trùng lặp hoặc đưa ra thông tin không đồng nhất.
- Cần xử lý múi giờ, giờ đóng cửa và ngày nghỉ của từng thị trường để tránh leakage.

### Kiểm chứng

Đánh giá hiệu quả của tín hiệu tin tức bằng thí nghiệm ablation trên tập validation năm 2019. So sánh mô hình có và không có tín hiệu tin tức, đồng thời đảm bảo dữ liệu đầu vào chỉ chứa thông tin đã khả dụng tại thời điểm dự báo.

Không kết luận quan hệ nhân quả chỉ dựa trên tương quan giữa tin tức và biến động giá.