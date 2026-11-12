# Bảo mật và kiểm soát chi phí CPAWS

> Bản cập nhật chương báo cáo cuối kỳ ngày 11/11/2026. Nội dung phân biệt giữa biện pháp đã triển khai, bằng chứng đã kiểm chứng và rủi ro còn tồn tại. Không xem kế hoạch hoặc cấu hình đang chờ phê duyệt là kết quả hoàn tất.

## 1. Phạm vi bảo mật

CPAWS sử dụng một môi trường AWS `dev` tại `ap-southeast-1`. Các biện pháp bảo mật tập trung vào năm nhóm:

1. Kiểm soát tài khoản và quyền truy cập AWS.
2. Bảo vệ dữ liệu, bí mật và tài nguyên lưu trữ.
3. Kiểm soát quyền ghi, xóa và tính bất biến của artifact đánh giá.
4. Bảo vệ API và chatbot.
5. Theo dõi chi phí và cảnh báo bất thường.

Các biện pháp này giảm thiểu rủi ro vận hành trong phạm vi đồ án; không đồng nghĩa hệ thống đã đạt chứng nhận hoặc tiêu chuẩn an toàn thông tin độc lập.

## 2. Quản lý tài khoản và quyền truy cập

### 2.1. Đăng nhập và xác thực

- Nhóm sử dụng một tài khoản AWS chính để quản lý tài nguyên và chi phí.
- Root account đã bật MFA, chỉ dùng cho các thao tác quản trị cấp tài khoản và billing cần thiết.
- Thành viên đăng nhập CLI bằng `aws login --profile cpaws-dev`, sử dụng thông tin xác thực ngắn hạn.
- MFA đã bật cho cả năm thành viên.
- Không lưu access key dài hạn trong repository hoặc file `.env`.

### 2.2. Phân quyền

Nhóm phân quyền thông qua IAM user và group:

| Nhóm | Phạm vi quyền chính |
|---|---|
| `cpaws-admins` | Quản trị tài khoản và IAM |
| `cpaws-platform` | Vận hành và triển khai hạ tầng; không có quyền quản trị IAM |
| `cpaws-ml` | Truy cập tài nguyên phục vụ dữ liệu và ML |
| `cpaws-genai` | Truy cập Bedrock và tài nguyên GenAI |
| `cpaws-developers` | Quyền đọc phục vụ phát triển và kiểm tra |

Chỉ người phụ trách quản trị được phép thay đổi IAM policy. Các thay đổi IAM và hạ tầng phải được review qua Pull Request trước khi triển khai.

**Giới hạn đã ghi nhận:** `ReadOnlyAccess` gắn với group `cpaws-developers` có phạm vi rộng hơn nhu cầu đọc một số prefix cụ thể. Nhóm quyết định giữ nguyên quyền hiện tại trước và trong cửa sổ test2020 từ ngày 16–22/11/2026 để Long có thể đọc artifact phục vụ audit. Quyền đọc không thay thế quyền ghi hoặc xóa; các thao tác xóa trên prefix test2020 được kiểm soát riêng bằng explicit deny. Nhóm sẽ đánh giá lại phạm vi `ReadOnlyAccess` sau khi kết thúc cửa sổ chạy.

## 3. Bảo vệ dữ liệu, bí mật và API

### 3.1. S3 và dữ liệu dự án

Bucket dữ liệu `cpaws-dev-lake` có các biện pháp:

- Chặn truy cập công khai.
- Bắt buộc kết nối SSL.
- Bật versioning và giữ phiên bản cũ trong 30 ngày.
- Chính sách `RETAIN` để tránh xóa bucket ngoài ý muốn khi thay đổi stack.
- Không commit dữ liệu thực vào Git; dữ liệu mẫu nhỏ được quản lý riêng.

S3 là nơi lưu trữ chính của data lake. Nhóm có bản sao lưu Google Drive theo quy trình thủ công; code pipeline không tự truy cập Drive.

**Rủi ro ghi đè artifact:** Đối với prefix `eval/shadow_eval/*` do role job accuracy sử dụng, cơ chế ngăn ghi đè hiện chưa được cưỡng chế đầy đủ ở cấp IAM hoặc bucket policy. Luồng ghi dựa vào conditional write `IfNoneMatch="*"` trong application code và các kiểm thử tương ứng. PR #115 bổ sung kiểm thử cho cơ chế này. Job role phục vụ chạy đánh giá không được cấp quyền xóa object. Prefix `eval/test2020/` được kiểm soát riêng: user và runner bị explicit deny quyền xóa object, runner sử dụng conditional write `IfNoneMatch="*"` để tránh ghi đè.

Versioning giúp giữ lại phiên bản cũ khi object bị ghi đè, nhưng lifecycle chỉ giữ phiên bản cũ trong 30 ngày. Vì vậy, khả năng khôi phục do ghi đè không được bảo đảm sau thời hạn này.

**Rủi ro còn lại và hướng cải thiện:** Nếu application code bỏ qua conditional write hoặc có luồng ghi khác không tuân thủ hợp đồng, object vẫn có nguy cơ bị ghi đè. Nhóm đề xuất bổ sung điều kiện `s3:if-none-match` trong bucket policy để cưỡng chế conditional write ở tầng lưu trữ. Đây là hướng cải thiện, không mô tả như cấu hình đã triển khai.

### 3.2. Quản lý API key

API key EIA được lưu trong AWS Systems Manager Parameter Store dưới dạng `SecureString`. Repository chỉ chứa tên parameter, không chứa giá trị bí mật.

Không đưa API key, mật khẩu, mã MFA, access token hoặc thông tin đăng nhập vào Git. Khi cần kiểm tra cấu hình, chỉ kiểm tra tên và quyền truy cập secret, không in giá trị bí mật ra terminal hoặc log.

### 3.3. API và người dùng

- Cognito User Pool quản lý tài khoản người dùng; không cho phép tự đăng ký.
- API Gateway dùng Cognito authorizer cho các route nghiệp vụ, ngoại trừ `/health`.
- API có throttling 10 request/giây, burst 20.
- CORS giới hạn một origin web được cấu hình.
- Các Lambda có log group với thời gian lưu một tháng.

Các cấu hình trên giảm bề mặt truy cập công khai, nhưng không thay thế việc kiểm thử bảo mật định kỳ hoặc rà soát quyền theo nguyên tắc least privilege.

### 3.4. Chatbot và kiểm soát đầu vào

Chatbot CPAWS được cung cấp qua endpoint `/chat` và sử dụng Cognito authorizer để xác thực người dùng. Các biện pháp kiểm soát gồm:

- Giới hạn mức sử dụng theo người dùng thông qua bảng `chat-usage`.
- Dữ liệu số liệu trong câu trả lời phải lấy từ các công cụ/dữ liệu của hệ thống, không tự tạo số liệu thị trường.
- Lambda `/chat` chỉ ghi log mức `WARNING` với mã `citation_link_mismatch` khi câu trả lời chứa URL lạ; cơ chế này không chặn câu trả lời (PR #104). Benchmark chấm trượt câu trả lời có URL lạ (PR #109).
- Người dùng cần đăng nhập trước khi sử dụng route chatbot.

**Giới hạn đã ghi nhận:** Theo quyết định ngày 11/11/2026, nhóm không bật Guardrails của Amazon Bedrock trong phạm vi đồ án. Chủ đề tư vấn đầu tư và prompt attack hiện được kiểm soát bằng các quy tắc trong prompt và bộ benchmark có kiểm tra chính sách. Guardrails là hướng cải tiến sau đồ án, không phải biện pháp đã triển khai.

## 4. Bảo vệ artifact đánh giá test2020

Runner test2020 cần ghi artifact vào prefix `eval/test2020/`, nhưng không được tự xóa hoặc ghi đè artifact đã tạo.

Chính sách IAM áp dụng:

- Cho phép `s3:PutObject` trong prefix được chỉ định.
- Explicit deny `s3:DeleteObject` và `s3:DeleteObjectVersion`.
- Runner sử dụng conditional write `IfNoneMatch="*"`.
- Không xóa claim hoặc artifact để mở lại lượt chạy đã được ghi nhận.

### 4.1. Kết quả kiểm chứng ngày 04/11 và 11/11/2026

**Bằng chứng ngày 04/11/2026:** Long thực hiện kiểm tra bằng AWS CLI với profile `cpaws-dev` và phiên đăng nhập MFA. Kết quả ghi nhận:

| Thử nghiệm | Kết quả | Ý nghĩa |
|---|---|---|
| PutObject với `IfNoneMatch="*"` | PASS | Ghi object mới thành công |
| Ghi lại cùng key | PASS | Bị từ chối với HTTP 412 |
| DeleteObject | PASS | Bị explicit deny, trả AccessDenied |
| DeleteObjectVersion | Chưa kiểm chứng thực tế | Mới kiểm tra bằng IAM Policy Simulator |

**Bằng chứng bổ sung ngày 11/11/2026:** Long kiểm tra từ Codespaces bằng principal `user/long`, đăng nhập qua `aws login --remote`. Object kiểm tra sử dụng key `eval/test2020/_iam-check-2026-11-11.txt`.

| Thử nghiệm | Kết quả | Ý nghĩa |
|---|---|---|
| PutObject với `IfNoneMatch="*"` | PASS | Ghi object mới thành công |
| Ghi lại cùng key | PASS | Nhận HTTP 412, không ghi đè object |
| DeleteObject | PASS | Bị từ chối với AccessDenied |

Cùng ngày, Tuấn chạy IAM Policy Simulator cho IAM user `user/long`:

| Thao tác | Kết quả Policy Simulator |
|---|---|
| `s3:PutObject` | Allowed |
| `s3:DeleteObject` | ExplicitDeny |
| `s3:DeleteObjectVersion` | ExplicitDeny |

Đối với `DeleteObjectVersion`, nhóm chỉ xác minh bằng IAM Policy Simulator; không cố ý thực hiện thao tác xóa version thật trên prefix chính thức. Quyền IAM hiện tại được giữ nguyên trong và trước cửa sổ test2020 từ ngày 16–22/11/2026.

Object kiểm tra được giữ lại trên S3 vì quyền xóa bị chặn. Đây là object kiểm tra riêng, không phải artifact của lượt chạy test2020 chính thức.

**Kết luận:** Đã có bằng chứng thực tế cho conditional write, ngăn ghi đè cùng key và chặn `DeleteObject`. Quyền `DeleteObjectVersion` đã được xác minh bằng Policy Simulator nhưng chưa được kiểm chứng bằng thao tác thực tế. Test2020 chính thức dự kiến chạy từ 16–22/11/2026, sau khi hoàn tất phê duyệt và preflight.

## 5. Kiểm soát chi phí AWS

### 5.1. Nguyên tắc thiết kế tiết kiệm

CPAWS ưu tiên tài nguyên có thể chạy theo nhu cầu thay vì duy trì dịch vụ tính phí liên tục:

- Lambda chạy theo lịch hoặc khi có sự kiện.
- DynamoDB sử dụng chế độ on-demand.
- Không duy trì SageMaker endpoint thường trực.
- Lambda không chạy trong VPC, do đó không cần NAT Gateway cho luồng hiện tại.
- ECR giới hạn số image được giữ.
- CloudWatch log group giới hạn thời gian lưu một tháng.

Đây là các lựa chọn giúp hạn chế chi phí nền khi hệ thống không có người dùng hoặc không chạy pipeline.

### 5.2. Ngân sách và cảnh báo

| Cơ chế | Cấu hình / trạng thái |
|---|---|
| AWS Budgets | Ngân sách 50 USD/tháng |
| Cost Anomaly Detection | Monitor mặc định, kiểm tra hằng ngày |
| Ngưỡng cảnh báo bất thường | Mức tuyệt đối từ 100 USD và mức tương đối từ 40%, theo cấu hình đã ghi nhận |
| Thông báo | Email subscription đã xác nhận |

Cấu hình Cost Anomaly Detection đã được tạo trên AWS. PR #114 ghi nhận cấu hình này và **đã được merge**. Đây là cơ chế phát hiện biến động chi phí và gửi cảnh báo, không phải cơ chế tự động giới hạn hoặc ngắt dịch vụ khi vượt ngân sách. AWS Budgets cũng không bảo đảm mọi khoản chi đều bị chặn khi chạm ngưỡng.

### 5.3. Theo dõi chi phí thực tế và dự toán tạm thời

Số liệu tạm tính tại ngày 11/11/2026:

| Hạng mục | Số tiền ước tính | Ghi chú |
|---|---:|---|
| Chi phí thực tế từ 12/10 đến 11/11 | Khoảng 5,28 USD | Được credit AWS hiện có bao phủ |
| Dự báo chi phí từ 12/11 đến 29/11 | Khoảng 1,14 USD | Dự toán, chưa phải chi phí phát sinh thực tế |
| Credit còn lại tại ngày 11/11 | Khoảng 194,67 USD | Số dư ước tính tại thời điểm ghi nhận |

Các số liệu trên là số liệu tạm thời phục vụ theo dõi trong quá trình thực hiện đồ án; không thay thế báo cáo billing chốt kỳ. Credit còn lại không được dùng để suy luận chi phí tiêu thụ.

Sau ngày 30/11/2026, nhóm cần cập nhật báo cáo cuối kỳ bằng số liệu AWS Cost Explorer hoặc Billing, bao gồm:

- Chi phí thực tế theo dịch vụ.
- Chi phí Amazon Bedrock, đặc biệt các lượt gọi chatbot.
- Chi phí Lambda, S3, DynamoDB, CloudWatch và các dịch vụ liên quan.
- Credit còn lại và thời hạn sử dụng.
- Chênh lệch giữa chi phí thực tế và ngân sách.

## 6. Rủi ro dữ liệu và điều khoản nhà cung cấp

### 6.1. Rủi ro Yahoo Finance / yfinance

Năm chuỗi dữ liệu chính GLD, SLV, CL=F, BZ=F và VND=X hiện phụ thuộc vào yfinance, một thư viện không chính thức truy cập dữ liệu Yahoo Finance.

Nhóm ghi nhận các rủi ro:

1. Thu thập tự động dữ liệu qua endpoint của Yahoo.
2. Lưu dữ liệu giá trên S3 và bản sao lưu Google Drive.
3. Hiển thị dữ liệu hoặc kết quả dẫn xuất cho người dùng khác.
4. Nguồn có thể bị chặn hoặc thay đổi định dạng mà không báo trước.

Nhóm không có giấy phép của Yahoo cho các hoạt động trên. Việc giảng viên đồng ý sử dụng dữ liệu trong đồ án không đồng nghĩa Yahoo đã cấp phép. Đây là rủi ro đã biết và được nhóm chấp nhận trong phạm vi đồ án, không phải xác nhận tuân thủ điều khoản của nhà cung cấp.

Biện pháp giảm thiểu hiện tại gồm ghi nguồn dữ liệu, giới hạn phạm vi sử dụng, không cung cấp tính năng tải hoặc xuất dữ liệu giá và duy trì phương án tắt hiển thị giá kim loại bằng `VITE_SHOW_METAL_PRICES=false`.

Các biện pháp này chỉ thu hẹp phạm vi sử dụng, không loại bỏ rủi ro điều khoản.

### 6.2. Nguồn thay thế và phương án xử lý

EIA API v2 cung cấp dữ liệu công khai để đối chiếu dầu WTI và Brent, nhưng dữ liệu phát hành trễ khoảng một tuần và không thay thế đầy đủ năm chuỗi Yahoo.

Nếu nhà cung cấp yêu cầu ngừng sử dụng:

1. Dừng hiển thị chuỗi dữ liệu liên quan.
2. Tắt chức năng hiển thị giá kim loại nếu cần bằng `VITE_SHOW_METAL_PRICES=false`.
3. Xử lý dữ liệu đã lưu theo chính sách sử dụng dữ liệu.
4. Cập nhật ADR và đánh giá nguồn thay thế trước khi tiếp tục thu thập.

## 7. Tổng kết trạng thái và công việc còn lại

| Hạng mục | Trạng thái tại 11/11/2026 |
|---|---|
| MFA cho thành viên | Đã bật |
| CLI dùng credentials ngắn hạn | Đã áp dụng |
| Quản lý secret bằng SSM SecureString | Đã triển khai |
| S3 chặn public, bắt buộc SSL, bật versioning | Đã cấu hình |
| Conditional write test2020 | Đã kiểm chứng thực tế ngày 04/11 và 11/11 |
| Chặn ghi đè cùng key test2020 | Đã kiểm chứng thực tế, nhận HTTP 412 |
| Chặn DeleteObject | Đã kiểm chứng thực tế |
| Chặn DeleteObjectVersion | Đã kiểm tra bằng Policy Simulator; chưa thử xóa version thật |
| Ngăn ghi đè ở tầng bucket policy cho `eval/shadow_eval/*` | Chưa triển khai; đang dựa vào application conditional write và kiểm thử |
| Thu hẹp quyền ReadOnlyAccess | Đánh giá lại sau cửa sổ test2020 |
| Chatbot `/chat` dùng Cognito và quota | Đã triển khai theo cấu hình hiện tại |
| Bedrock Guardrails | Chưa bật theo quyết định ngày 11/11 |
| AWS Budgets 50 USD/tháng | Đã cấu hình |
| Cost Anomaly Detection | Đã cấu hình AWS; PR #114 đã merge |
| Rủi ro điều khoản Yahoo | Đã ghi nhận và chấp nhận; chưa loại bỏ |
| Tổng hợp chi phí cuối kỳ | Chờ số liệu chốt sau ngày 30/11 |

CPAWS đã triển khai các biện pháp cơ bản để kiểm soát truy cập, bảo vệ dữ liệu, hạn chế ghi đè/xóa artifact và theo dõi chi phí. Tuy nhiên, nhóm vẫn cần tiếp tục rà soát least privilege, hoàn tất kiểm chứng quyền xóa version theo phương pháp phù hợp, đánh giá khả năng cưỡng chế conditional write ở tầng bucket policy và tổng hợp chi phí thực tế trước khi kết thúc đồ án. Guardrails được ghi nhận là hướng cải tiến sau đồ án theo quyết định ngày 11/11/2026.

## Tài liệu đối chiếu

- [ADR-0006: Tài khoản AWS, quyền truy cập và credit](../adr/0006-aws-account-and-access.md)
- [ADR-0005: Nguồn dữ liệu giá](../adr/0005-price-data-sources.md)
- [Runbook test2020](../experiments/test2020-runbook.md)
- [Triển khai và vận hành CPAWS](trien-khai-van-hanh.md)
- [PR #75: Kế hoạch gốc test2020](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/75)
- [PR #88: Cập nhật snapshot, lineage test2020 và approval chạy official](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/88)
- [PR #89: Job accuracy rolling_8w và shadow evaluation](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89)
- [PR #104: Kiểm tra liên kết chatbot](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/104)
- [PR #109: Bổ sung kiểm tra liên kết](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/109)
- [PR #114: Ghi nhận cấu hình Cost Anomaly Detection](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/114)
- [PR #115: Kiểm thử conditional write](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/115)
