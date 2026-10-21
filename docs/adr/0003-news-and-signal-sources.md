# ADR-0003: News and Signal Sources

- **Date:** 2026-10-20
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

MVP ưu tiên các nguồn chính thức có thể truy xuất, xác minh nội dung và xác định thời điểm công bố:

- **Federal Reserve (Fed):** FOMC statements và FOMC minutes để theo dõi quyết định chính sách tiền tệ và thông tin liên quan.
- **U.S. Energy Information Administration (EIA):** Weekly Petroleum Status Report và Today in Energy để theo dõi tồn kho, cung cầu dầu và các diễn biến thị trường năng lượng.
- **The Guardian:** tạm thời chưa đưa vào pipeline gắn nhãn bằng LLM cho đến khi xác minh được quyền sử dụng phù hợp.
- **New York Times (NYT):** loại khỏi MVP. Không đưa nội dung bài viết NYT vào Bedrock hoặc pipeline xử lý bằng LLM; không lưu nội dung bài viết.
- **OPEC:** chưa sử dụng trong MVP cho đến khi kiểm tra và ghi nhận điều khoản sử dụng chính thức.

GDELT chỉ được xem xét như nguồn bổ sung khi có bộ lọc hoặc danh sách domain đáng tin cậy.

### Điều khoản sử dụng và lưu trữ nguồn tin

Trước khi đưa nguồn vào pipeline, cần kiểm tra chính sách bản quyền và điều khoản sử dụng chính thức của nguồn. Không mặc định rằng nội dung truy cập công khai hoặc quyền truy cập API đồng nghĩa với quyền đưa nội dung vào LLM.

Đối với dữ liệu Fed và EI A được chọn cho MVP:

- Chỉ lưu tiêu đề, phần tóm tắt do nhóm tự viết và đường dẫn nguồn.
- Ghi nhận nguồn và thời điểm công bố để có thể truy xuất, đối chiếu lại thông tin gốc.
- Kiểm tra từng trang nguồn trước khi đưa tin vào bộ dữ liệu; không sử dụng đường dẫn do mô hình tự tạo nếu chưa xác minh.
- Chỉ sử dụng nội dung phù hợp với chính sách bản quyền của nguồn; không mặc định quyền sử dụng đối với ảnh, biểu đồ hoặc nội dung của bên thứ ba.

Đối với Guardian, tiếp tục chờ xác nhận về quyền sử dụng cho mục đích gắn nhãn bằng LLM. Trong thời gian chờ, không đưa bài Guardian vào LLM. NYT bị loại khỏi phạm vi MVP và không được sử dụng làm đầu vào cho Bedrock.

### 3. Phạm vi MVP

MVP cung cấp hàm `get_news(asset, from_date, to_date, min_impact)` để truy xuất tin tức theo tài sản, khoảng thời gian và ngưỡng tác động tối thiểu.

MVP chưa yêu cầu xây dựng Knowledge Base hoặc embedding vector cho toàn bộ tin tức. Trước tiên, hệ thống tập trung vào việc thu thập, gắn nhãn và truy xuất các bài viết có liên quan.
### Điều khoản sử dụng nguồn tin

### Điều khoản sử dụng nguồn tin

Trước khi thu thập và đưa nội dung tin tức vào pipeline gắn nhãn bằng LLM, phải kiểm tra điều khoản sử dụng của từng nguồn và phạm vi quyền được cấp. Quyền truy cập website hoặc API không mặc nhiên cho phép sử dụng nội dung với dịch vụ AI bên thứ ba.

- **Guardian Open Platform:** Loại khỏi pipeline thu thập và gắn nhãn bằng LLM trong MVP. Ngày 21/10/2026, Guardian News & Media xác nhận qua email rằng use case được đề xuất không được phép theo điều khoản Open Platform hiện hành. Điều khoản 6(g) hạn chế việc sử dụng nội dung cho mục đích AI/ML, text and data mining và tạo nội dung bằng công nghệ AI. Chỉ xem xét lại nếu nhóm có được quyền sử dụng riêng bằng văn bản. Tham khảo: https://www.theguardian.com/open-platform/terms-and-conditions.
- **NYT Developer API:** Loại khỏi MVP. Không đưa nội dung bài viết NYT vào Bedrock hoặc pipeline xử lý bằng LLM, và không lưu nội dung bài viết cho mục đích của pipeline này.
- **Nguồn thay thế đã chọn:** Ưu tiên tài liệu chính thức từ Federal Reserve, gồm FOMC statements và minutes, cùng U.S. Energy Information Administration (EIA), gồm Weekly Petroleum Status Report và Today in Energy. Trước khi sử dụng, kiểm tra điều khoản bản quyền và các giới hạn áp dụng cho từng tài liệu; với Federal Reserve, thông tin trên website nhìn chung thuộc phạm vi public domain trừ khi có ghi chú khác hoặc chứa tài liệu của bên thứ ba. Tham khảo:
  - Federal Reserve copyright disclaimer: https://www.federalreserve.gov/disclaimer.htm
  - FOMC statements và minutes: https://www.federalreserve.gov/monetarypolicy.htm
  - EIA copyright and reuse: https://www.eia.gov/about/copyrights_reuse.php
  - EIA Weekly Petroleum Status Report: https://www.eia.gov/petroleum/supply/weekly/
  - EIA Today in Energy: https://www.eia.gov/todayinEnergy/
- **OPEC:** Chưa đưa vào pipeline cho đến khi kiểm tra điều khoản sử dụng chính thức và ghi nhận kết luận trong ADR.
- **Nguyên tắc lưu trữ và xử lý:** Chỉ lưu tiêu đề, phần tóm tắt do nhóm tự viết và đường dẫn nguồn, sau khi xác minh các trường này được phép sử dụng. Không mặc định rằng quyền truy cập API đồng nghĩa với quyền sao chép, lưu trữ lâu dài hoặc gửi nội dung cho dịch vụ AI bên thứ ba. Khi chatbot trích dẫn tin, phải kiểm tra URL và nội dung nguồn thực tế trước khi trả lời.

**Trạng thái:** Guardian và NYT bị loại khỏi pipeline gắn nhãn bằng LLM trong MVP. Bộ 50 tin thật dự kiến được xây dựng từ các nguồn chính thức đã chọn, ưu tiên Federal Reserve và EIA, sau khi kiểm tra điều khoản áp dụng cho từng nguồn và tài liệu. Không sử dụng nội dung Guardian, NYT hoặc OPEC trong pipeline khi chưa có quyền sử dụng phù hợp.

### 4. Schema gắn nhãn tin tức

Mỗi bài viết có trường `relevant` ở cấp bài viết để xác định bài đó có liên quan đến phạm vi dự án hay không.

Mức độ tác động được đánh giá riêng cho từng tài sản:

- `asset`: `gold`, `silver`, `brent` hoặc `wti`, thống nhất với mã tài sản và partition key `asset` của bảng `NewsLabels`.
- `impact_score`: số nguyên từ 0 đến 3. Giá trị 0 bao gồm trường hợp không có ảnh hưởng đáng kể hoặc bài viết không liên quan.
- `direction`: `bullish`, `bearish`, `mixed` hoặc `uncertain`.
- `confidence`: `high`, `medium` hoặc `low`.
- `event_type`: loại sự kiện chính.
- `prompt_version`: phiên bản prompt đã dùng để gắn nhãn.

Metadata bổ sung gồm `published_at`, `fetched_at`, `labeled_at` và `model_id`. Prompt gắn nhãn được quản lý tại [`docs/prompts/news-labeling-v1.md`](../prompts/news-labeling-v1.md).

Nhãn phản ánh nội dung và đánh giá của mô hình tại thời điểm xử lý, không khẳng định bài viết đã gây ra biến động giá.

### 5. Xử lý thời điểm công bố và point-in-time integrity

Mỗi bài viết phải giữ `published_at` theo thời điểm công bố gốc và múi giờ nguồn nếu có. Khi lưu trữ hoặc so sánh giữa các nguồn, ứng dụng nên chuẩn hóa timestamp về UTC, đồng thời giữ lại thông tin thời gian gốc để truy vết.

Với một dự báo được tạo tại thời điểm cutoff `t`, chỉ được sử dụng tin có `published_at <= t`. Tin được công bố sau cutoff không được đưa vào feature, tập tin truy xuất cho dự báo, hoặc dữ liệu đầu vào của benchmark tại thời điểm đó, kể cả khi tin và dự báo cùng ngày theo lịch.

Cutoff phải khớp với kịch bản dự báo thực tế. Ví dụ, nếu dự báo được tạo trước khi phiên giao dịch mở cửa, không được sử dụng tin xuất hiện sau thời điểm cutoff đó. Không ghép tin chỉ dựa trên ngày lịch.

Việc gán tin vào phiên giao dịch phải dựa trên lịch giao dịch của từng tài sản, bao gồm múi giờ, giờ mở cửa/đóng cửa, cuối tuần và ngày nghỉ của thị trường. Tin công bố sau giờ đóng cửa được xem xét cho phiên tiếp theo theo lịch tương ứng, nhưng vẫn phải tuân thủ cutoff của lần dự báo đang đánh giá.

Nếu `published_at` bị thiếu, không hợp lệ hoặc không đủ chính xác để xác định tin đã khả dụng trước cutoff hay chưa, phải loại tin đó khỏi đánh giá forecasting nhạy theo thời gian hoặc đánh dấu rõ thời điểm công bố là không xác định. Không được mặc định rằng tin đã tồn tại trước timestamp ghi nhận.

Benchmark lịch sử phải tái tạo thông tin có thể biết tại từng cutoff. Không sử dụng tin tức tương lai, giá tương lai hoặc nhãn được tạo từ kết quả tương lai làm đầu vào của dự báo. Quy tắc này nhằm tránh look-ahead bias và data leakage.

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

Đánh giá hiệu quả của tín hiệu tin tức bằng thí nghiệm ablation trên tập validation năm 2019. So sánh mô hình có và không có tín hiệu tin tức, đồng thời đảm bảo dữ liệu đầu vào chỉ chứa thông tin đã khả dụng tại cutoff của từng dự báo. Cần kiểm tra timestamp của tin trước khi ghép với mẫu dữ liệu; không dùng ngày lịch làm điều kiện duy nhất.

Không kết luận quan hệ nhân quả chỉ dựa trên tương quan giữa tin tức và biến động giá.
