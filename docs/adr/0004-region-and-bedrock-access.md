# ADR-0004: Region and Bedrock Access

- **Date:** 2026-10-20
- **Status:** Chấp nhận cho MVP

## Bối cảnh

Dự án sử dụng Amazon Bedrock để triển khai chatbot và xử lý tin tức phục vụ dự báo giá Gold, Silver, Brent và WTI. Việc lựa chọn mô hình cần cân nhắc khả năng truy cập trong AWS Region, chất lượng phản hồi, khả năng sử dụng tool, độ trễ và chi phí.

Quá trình thử nghiệm cho thấy Nova 2 Lite có thể được gọi thông qua inference profile. Claude Haiku 4.5 cũng gọi được thông qua global cross-region inference profile. Điều này không đảm bảo mọi yêu cầu đều được xử lý hoàn toàn trong Singapore.

Claude Haiku 5.5 chưa sử dụng được do quota yêu cầu bị từ chối. Vì vậy, MVP không phụ thuộc vào mô hình này.

## Kết quả thử nghiệm

| Hạng mục | Trạng thái đã quan sát | Phạm vi xác minh / lưu ý |
|---|---|---|
| Amazon Nova 2 Lite | Gọi thử model thành công | Chỉ xác nhận được lời gọi thử qua inference profile; chưa chứng minh toàn bộ chatbot hoạt động end-to-end |
| Claude Haiku 4.5 | Gọi thử model thành công | Sử dụng global cross-region inference profile; không thể mặc định toàn bộ xử lý chỉ diễn ra tại Singapore |
| Claude Haiku 5.5 | Chưa sử dụng được | Yêu cầu quota bị từ chối |
| Bedrock Guardrails | Đã tạo bản nháp | Guardrail ở trạng thái `DRAFT`; chưa phải cấu hình production đã publish và xác minh trong luồng ứng dụng |
| Knowledge Base với Cohere | Chưa triển khai/xác minh end-to-end | Lần thử gặp `AccessDenied` liên quan đến Marketplace. Chưa xác minh đầy đủ quy trình tạo Knowledge Base, ingestion, truy xuất và tích hợp chatbot |
| Titan Text Embeddings V2 | Chưa xác nhận được | Không thấy khả dụng cho cấu hình Knowledge Base tại Singapore trong lần kiểm tra; chưa kết luận ngoài phạm vi lần kiểm tra đó |
| Batch inference | Đã kiểm tra giới hạn | Chưa chạy batch inference job end-to-end |

Chi tiết thử nghiệm được ghi tại [`docs/experiments/bedrock-model-test-2026-10.md`](../experiments/bedrock-model-test-2026-10.md).

Các kết quả trên cần được hiểu theo đúng phạm vi quan sát: gọi thử model thành công hoặc tạo được một tài nguyên riêng lẻ không đồng nghĩa với việc toàn bộ workflow chatbot đã được kiểm thử end-to-end. Chỉ đánh dấu một bước là đã xác minh khi có kết quả thử nghiệm thực tế tương ứng. Tại thời điểm cập nhật ADR này, Knowledge Base chưa được xác minh hoàn chỉnh từ tạo tài nguyên đến ingestion, truy xuất và tích hợp chatbot.

## Quyết định

### 1. Lựa chọn mô hình cho chatbot

MVP sử dụng chiến lược định tuyến mô hình như sau: Router sử dụng các luật xác định trước, không gọi LLM để phân loại yêu cầu. Nếu luật không xác định được nhánh xử lý phù hợp, hệ thống chuyển yêu cầu sang Claude Haiku 4.5.

- **Nova 2 Lite:** xử lý câu hỏi đơn giản, yêu cầu ngắn và các tác vụ phân loại tin tức.
- **Claude Haiku 4.5:** xử lý câu hỏi phức tạp hơn hoặc yêu cầu sử dụng tool.
- **Mặc định:** nếu router không đủ tự tin để phân loại yêu cầu, chuyển sang Claude Haiku 4.5.

Đây là quyết định thiết kế cho MVP, không phải bằng chứng rằng toàn bộ cơ chế định tuyến, fallback và sử dụng tool đã vượt qua kiểm thử end-to-end.

Chiến lược này nhằm cân bằng chi phí và chất lượng phản hồi. Việc sử dụng Haiku 4.5 làm phương án mặc định khi không chắc chắn giúp hạn chế định tuyến nhầm các yêu cầu phức tạp sang mô hình nhẹ hơn.

### 2. Gắn nhãn tin tức

Nova 2 Lite được sử dụng cho tác vụ gắn nhãn tin tức trong MVP.

Cấu hình dự kiến:

- Sử dụng tool use với JSON Schema để yêu cầu đầu ra có cấu trúc.
- Đặt `temperature = 0` nhằm giảm sự biến thiên giữa các lần chạy.
- Lưu phiên bản prompt và metadata của mô hình để hỗ trợ truy vết và đánh giá chất lượng nhãn.

Schema và quy tắc gắn nhãn được mô tả trong [`docs/prompts/news-labeling-v1.md`](../prompts/news-labeling-v1.md).

### 3. Cách gọi mô hình

Sử dụng Amazon Bedrock Converse API và ConverseStream API khi phù hợp với luồng xử lý của ứng dụng.

- Sử dụng Converse cho các tác vụ cần nhận kết quả hoàn chỉnh trước khi xử lý tiếp.
- Sử dụng ConverseStream cho chatbot cần hiển thị phản hồi theo từng phần.
- Cấu hình model ID hoặc inference profile thông qua cấu hình ứng dụng, tránh hardcode trực tiếp trong logic nghiệp vụ.

Giới hạn `max_tokens` ban đầu:

| Nhánh xử lý | `max_tokens` |
|---|---:|
| Câu hỏi đơn giản | 512 |
| Câu hỏi phức tạp hoặc có sử dụng tool | 1500 |

Các giới hạn trên là cấu hình khởi đầu cho MVP và cần được điều chỉnh dựa trên thử nghiệm thực tế.

### 4. Region và quyền truy cập

Ưu tiên triển khai tài nguyên trong `ap-southeast-1` (Singapore) khi dịch vụ và mô hình cần thiết được hỗ trợ.

Claude Haiku 4.5 hiện được gọi thông qua global cross-region inference profile. Với cấu hình này, không thể mặc định rằng mọi yêu cầu được xử lý hoàn toàn trong Singapore, dù ứng dụng hoặc các tài nguyên liên quan được đặt tại `ap-southeast-1`.

Trước khi sử dụng, cần kiểm tra cấu hình inference profile thực tế, tài liệu AWS áp dụng và yêu cầu về dữ liệu, quyền truy cập cũng như chính sách triển khai. Không đưa ra cam kết về data residency hoặc xử lý chỉ trong một Region nếu chưa có cơ sở xác minh cho đúng cấu hình đang dùng.

Claude Haiku 5.5 không nằm trong phạm vi triển khai MVP cho đến khi quota và quyền truy cập được xác nhận thành công.

#### Quyền IAM cho global inference profile

Khi sử dụng global cross-region inference profile, execution role cần có quyền gọi inference profile và các tài nguyên model liên quan theo yêu cầu của Amazon Bedrock.

Policy cần xem xét các tài nguyên:

- ARN của inference profile được ứng dụng sử dụng.
- ARN của foundation model tương ứng tại Region nguồn.
- ARN foundation model global tương ứng khi được yêu cầu bởi cấu hình global profile.

Với global inference profile, cần cho phép `aws:RequestedRegion = "unspecified"` trong điều kiện IAM phù hợp với yêu cầu của Bedrock.

Chỉ cấp quyền cho các model và inference profile cần thiết. ARN cụ thể phải lấy từ cấu hình triển khai thực tế và đối chiếu tài liệu IAM chính thức của AWS trước khi áp dụng policy.

### 5. Bedrock Guardrails

Guardrails cần được quản lý bằng AWS CDK thay vì tạo thủ công rồi phụ thuộc vào một ID cố định trong tài liệu.

- Định nghĩa cấu hình Guardrail trong CDK.
- Publish version trước khi sử dụng cho production.
- Đưa Guardrail ID và version vào CDK output hoặc cấu hình triển khai.
- Không hardcode Guardrail ID vào ADR hoặc logic nghiệp vụ.

Guardrail hiện tại vẫn ở trạng thái `DRAFT`, do đó chưa được xem là cấu hình production đã hoàn tất.

### 6. Knowledge Base

Knowledge Base chưa thuộc phạm vi bắt buộc của MVP.

Lý do:

- Cấu hình Cohere đã gặp lỗi `AccessDenied` liên quan đến Marketplace trong lần thử trước.
- Tài liệu AWS có thể xác nhận mức hỗ trợ của một embedding model tại Singapore, nhưng mức hỗ trợ được tài liệu nêu không chứng minh rằng Knowledge Base của dự án đã được tạo và chạy thành công trong tài khoản hiện tại.
- Titan Text Embeddings V2 chưa được xác nhận khả dụng cho cấu hình Knowledge Base tại Singapore trong lần kiểm tra.
- Chưa xác minh hoàn chỉnh quy trình end-to-end gồm tạo Knowledge Base, cấu hình data source, ingestion, truy xuất kết quả và tích hợp với chatbot.

MVP ưu tiên truy xuất tin tức từ nguồn dữ liệu đã thu thập và lưu trữ. Knowledge Base sẽ được xem xét lại sau khi xác minh quyền truy cập, tính khả dụng của embedding model và chi phí triển khai. Cho đến khi toàn bộ các bước được chạy và kiểm tra bằng bằng chứng thực tế, trạng thái Knowledge Base phải được ghi là chưa xác minh hoàn chỉnh, không phải đã triển khai thành công.

## Ước tính chi phí mô hình

Ước tính dưới đây chỉ tính chi phí token của mô hình theo các giả định lập kế hoạch, không phải hóa đơn thực tế.

### 1. Gắn nhãn tin tức

Giả định:

- 10.000 bài viết mỗi tháng.
- Mỗi bài sử dụng trung bình 1.500 input tokens và 200 output tokens.
- Giá tham chiếu Nova 2 Lite: 0,30 USD / 1 triệu input tokens và 2,50 USD / 1 triệu output tokens.

Ước tính:

- Input: 10.000 × 1.500 × 0,30 / 1.000.000 = 4,50 USD.
- Output: 10.000 × 200 × 2,50 / 1.000.000 = 5,00 USD.
- **Tổng chi phí gắn nhãn ước tính: 9,50 USD/tháng.**

### 2. Chatbot và định tuyến mô hình

Router của MVP sử dụng luật xác định trước, không gọi LLM và không phát sinh chi phí token.

Giả định lập kế hoạch:

- 1.000 yêu cầu mỗi tháng.
- Các yêu cầu đơn giản được Nova 2 Lite xử lý trực tiếp.
- Các yêu cầu phức tạp hoặc cần sử dụng tool được chuyển sang Claude Haiku 4.5.
- Giả định 30% yêu cầu được chuyển sang Haiku 4.5.
- Mỗi yêu cầu Haiku sử dụng trung bình 3.000 input tokens và 500 output tokens.
- Giá tham chiếu Haiku 4.5: 1 USD / 1 triệu input tokens và 5 USD / 1 triệu output tokens.

Chi phí Haiku 4.5 ước tính:

- Input: 1.000 × 30% × 3.000 × 1 / 1.000.000 = 0,90 USD/tháng.
- Output: 1.000 × 30% × 500 × 5 / 1.000.000 = 0,75 USD/tháng.
- Tổng Haiku 4.5: 1,65 USD/tháng.

Chi phí Nova 2 Lite phải được tính riêng cho số yêu cầu đơn giản thực sự được chuyển đến model, dựa trên token đầu vào và đầu ra đo được. Không tính chi phí token cho router theo luật.

Ước tính này chưa bao gồm retry, tool calls bổ sung hoặc các dịch vụ AWS khác.

### 3. Tổng chi phí token ước tính

Theo các giả định lập kế hoạch hiện tại:

- Gắn nhãn tin tức bằng Nova 2 Lite: khoảng **9,50 USD/tháng**.
- Chatbot sử dụng Claude Haiku 4.5: khoảng **1,65 USD/tháng** cho phần yêu cầu được chuyển sang Haiku, giả định tỷ lệ chuyển là 30%.
- Chatbot sử dụng Nova 2 Lite: **chưa đủ dữ liệu để ước tính**, cần đo số lượng yêu cầu đơn giản thực tế và lượng token đầu vào/đầu ra trung bình.

Do đó, **chưa thể chốt tổng chi phí token hằng tháng của MVP**. Tổng tạm tính của phần gắn nhãn tin tức và phần Haiku trong chatbot là 11,15 USD/tháng, chưa bao gồm chi phí Nova cho câu hỏi đơn giản.

Ước tính chưa bao gồm Guardrails, lưu trữ, thu thập tin tức, truyền dữ liệu, retry, logging hoặc các dịch vụ AWS khác. Giá thực tế cần được xác minh theo model, inference profile và bảng giá hiện hành tại thời điểm triển khai.

## Hệ quả

### Ưu điểm

- Có phương án triển khai MVP mà không phụ thuộc vào quota Haiku 5.5.
- Tách biệt tác vụ đơn giản và phức tạp để kiểm soát chi phí.
- Đầu ra gắn nhãn có cấu trúc, thuận lợi cho lưu trữ và đánh giá.
- Có thể thay đổi model ID hoặc inference profile thông qua cấu hình.

### Hạn chế và rủi ro

- Chất lượng định tuyến ảnh hưởng trực tiếp đến chất lượng phản hồi và chi phí.
- Global cross-region inference có thể không đáp ứng yêu cầu xử lý dữ liệu chỉ trong một Region.
- Chi phí thực tế phụ thuộc vào độ dài prompt, output, số lần gọi tool và retry.
- Guardrails và Knowledge Base chưa hoàn tất kiểm thử production.

### Việc cần hoàn thành trước production

- [ ] Xác minh quyền truy cập và model ID/inference profile trong môi trường triển khai.
- [ ] Đánh giá chất lượng router và cơ chế fallback.
- [ ] Kiểm thử đầu ra JSON Schema của tác vụ gắn nhãn.
- [ ] Triển khai Guardrails bằng CDK và publish version.
- [ ] Kiểm tra yêu cầu về Region và luồng dữ liệu.
- [ ] Đo chi phí thực tế bằng CloudWatch và AWS Cost Explorer.


