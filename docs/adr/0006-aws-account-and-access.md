# ADR-0006: Tài khoản AWS, quyền truy cập và credit

- Ngày: 2026-10-12 (cập nhật 2026-10-15)
- Trạng thái: Đã chấp nhận
- Người viết: Trịnh Tiến Khải; người duyệt: Huỳnh Ngọc Tuấn

> Repo đang ở chế độ **Public**: không ghi access key, mật khẩu, mã MFA, số thẻ, email cá nhân hay đầy đủ Account ID vào file này (chỉ ghi 4 số cuối). Chỗ còn `<...>` là thông tin chưa xác nhận.

## Bối cảnh

- Nhóm 5 người cần một môi trường AWS chung ở `ap-southeast-1` trong 7 tuần xây dựng và 2 tuần bảo vệ (12/10–13/12/2026).
- Credit thực có khoảng 200 USD (Free Tier và Explore AWS credits), thấp hơn mức 200–400 USD dự kiến trong proposal.
- Chatbot dùng model Anthropic trên Amazon Bedrock. Theo điều khoản credit của AWS, credit không áp cho phí AWS Marketplace trừ khi AWS cho phép; gói Free của AWS cũng giới hạn một số sản phẩm Marketplace.
- Thay đổi IAM và hạ tầng phải có Tuấn (IA) review (CLAUDE.md).

## Các phương án

| # | Hạng mục | Phương án | Ưu | Nhược | Kết luận |
|---|---|---|---|---|---|
| 1 | Tài khoản | Một tài khoản chính (Tuấn), một tài khoản dự phòng (Tiến) | Một nơi quản lý chi phí, quyền, tag | Phụ thuộc người giữ root và quyền admin | Chọn: tài khoản Tuấn là tài khoản chính; Tiến vận hành theo quyền IAM được cấp |
| 2 | Tài khoản | Mỗi người một tài khoản | Tách biệt | Khó dùng chung S3, DynamoDB; credit rải rác | Loại |
| 3 | Gom credit | AWS Organizations gom credit tài khoản dự phòng vào tài khoản chính | Dùng được cả hai khoản credit | Theo FAQ của AWS, nâng lên gói Paid bằng cách tham gia AWS Organizations làm Free Tier credit hết hạn ngay | Chưa dùng; chỉ xem lại khi AWS Support xác nhận bằng văn bản credit không bị mất |
| 4 | Đăng nhập | IAM user + group | Đơn giản, Tuấn đã tạo | Rủi ro access key dài hạn nếu dùng | Chọn; CLI đăng nhập bằng `aws login`, không tạo access key dài hạn |
| 5 | Đăng nhập | IAM Identity Center | Thông tin đăng nhập tạm thời, AWS khuyến nghị | Thêm bước cấu hình | Chưa dùng; xem lại nếu `aws login` không đáp ứng |

## Quyết định

### Tài khoản

| Mục | Giá trị |
|---|---|
| Tài khoản chính | Chủ: Tuấn; Account ID: `****1679` |
| Tài khoản dự phòng | Chủ: Tiến; Account ID: `****6242`; dùng khi tài khoản chính gặp sự cố hoặc cần người khác tiếp quản |
| Gói tài khoản (chính) | Free |
| AWS Organizations | Không dùng (xem phương án 3) |
| Region | `ap-southeast-1`; Bedrock gọi model qua cross-region inference profile |
| Root | MFA đã bật; chỉ dùng cho billing, đổi gói tài khoản, đóng tài khoản và việc bắt buộc root |

### Người dùng và quyền

Đăng nhập bằng **IAM user + group**. CLI dùng `aws login --profile cpaws-dev` (thông tin đăng nhập ngắn hạn).

| Group | Thành viên | Policy chính | Phạm vi |
|---|---|---|---|
| cpaws-admins | Tuấn | AdministratorAccess | Toàn bộ tài khoản, gồm IAM |
| cpaws-platform | Tiến | PowerUserAccess, SignInLocalDevelopmentAccess, AWSBillingReadOnlyAccess, policy tùy chỉnh | Mọi dịch vụ trừ IAM; triển khai bằng `cdk deploy` qua các role do `cdk bootstrap` tạo |
| cpaws-ml + cpaws-developers | Khải, Long | ReadOnlyAccess, cpaws-ml | S3 `cpaws-<env>-lake` (raw/, clean/, features/), SageMaker AI, Model Registry |
| cpaws-genai + cpaws-developers | Phước | ReadOnlyAccess, cpaws-genai, CPAWS-Bedrock-Four-Models | Bedrock (gọi model qua inference profile `global.*` và `apac.*` đã duyệt), Knowledge Bases, Guardrails |

- MFA bắt buộc và đã bật cho Tuấn, Tiến, Khải, Long, Phước.
- Không tạo access key dài hạn. Nếu bắt buộc phải có (công cụ không hỗ trợ `aws login`): chỉ lưu trong `~/.aws/credentials`, không để trong `.env` hay repo, xoay vòng mỗi 90 ngày, xóa ngay khi lộ.
- Chỉ Tuấn có quyền IAM. Vì vậy `cdk bootstrap` (tạo IAM role) và mọi thay đổi policy do Tuấn làm.
- Policy `CPAWS-Bedrock-Four-Models` chỉ cho gọi model qua đúng các inference profile đã duyệt ở `ap-southeast-1`. Hiện gắn trực tiếp vào user của Phước; nên chuyển sang group `cpaws-genai` để người khác trong nhóm chatbot dùng chung.

### Chi phí và cảnh báo

| Mục | Giá trị |
|---|---|
| AWS Budgets | 50 USD/tháng; gửi tới email của Tuấn |
| Cost Anomaly Detection | Monitor: <tên>; ngưỡng: <USD>; gửi tới email của Tuấn |
| Tag bắt buộc | `Project=CPAWS`, `Owner=<tên>`, `Env=dev\|prod` |

### Credit

| Mục | Giá trị |
|---|---|
| Nguồn credit | AWS Free Tier và Explore AWS credits |
| Số tiền | Còn lại 199,98 USD (kiểm tra ngày 12/10/2026) |
| Hạn dùng credit | 14/09/2027 |
| Gói Free kết thúc (nếu đang ở gói Free) | <ngày> |
| Dịch vụ áp dụng | Amazon Bedrock, AmazonBedrockFoundationModels, Amazon SageMaker, Amazon S3, AWS Lambda và các dịch vụ khác trong danh sách Applicable products |
| Áp cho model Anthropic (AWS Marketplace)? |Chưa xác nhận|

### Bedrock

| Mục | Giá trị |
|---|---|
| Model chatbot (đang dùng) | Claude Haiku 4.5, `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Model chatbot (dự kiến) | Claude Haiku 5.5, `global.anthropic.claude-haiku-5-5`; chờ AWS Support, đổi bằng `modelId` khi được duyệt |
| Model gắn nhãn tin | Nova 2 Lite, `global.amazon.nova-2-lite-v1:0` (Phước xác nhận trong ADR-0004) |
| Form First Time Use của Anthropic | Đã gửi (Tuấn); Haiku 4.5 gọi được từ 13/10/2026 |
| Gọi thử thành công | Haiku 4.5, Nova 2 Lite, Nova Micro: 13–14/10/2026, Phước |
| Quota | Tài khoản mới có thể bị đặt quota Bedrock gần 0; kiểm tra trong Service Quotas và xin tăng cùng case support Haiku 5.5 |

## Hệ quả

- **Nếu tài khoản đang ở gói Free:** một số sản phẩm Marketplace (có thể gồm model Anthropic) bị chặn cho tới khi nâng lên gói Paid; tài khoản tự đóng khi hết 6 tháng hoặc hết credit. Nhóm phải chọn giữa giữ gói Free (không bao giờ bị trừ tiền) và nâng lên Paid (credit còn lại vẫn áp; hết credit thì trừ vào thẻ của Tuấn).
- **Nếu credit không áp cho model Anthropic:** mọi lượt gọi Haiku tính vào thẻ của Tuấn. Khi đó đặt Budget riêng cho phần này ở mức <USD>, giữ giới hạn lượt hỏi chatbot, dùng Nova cho câu đơn giản và gắn nhãn tin.
- **Một người giữ quyền IAM là điểm nghẽn:** ngày 12–13/10, khi Tuấn vắng, nhóm không cấp được quyền Bedrock cho Phước và không chạy được `cdk bootstrap`. Thống nhất Tuấn xử lý yêu cầu IAM trong vòng 24 giờ; cân nhắc cấp cho Tiến quyền IAM giới hạn (chỉ sửa policy của các group `cpaws-*`).
- Credit hết hạn 14/09/2027, sau buổi bảo vệ; giới hạn thực tế là số tiền (khoảng 200 USD).
- Nếu đổi tài khoản, đổi cách đăng nhập hoặc đổi gói tài khoản: cập nhật ADR này và báo Tiến (CDK), cả nhóm (profile CLI).

## Việc cần làm

- [ ] Kiểm tra gói tài khoản (Free/Paid), ghi vào bảng Tài khoản (Tuấn)
- [ ] Xác nhận credit có áp cho model Anthropic không qua Bills (Tuấn), ghi vào bảng Credit
- [ ] Kiểm tra Service Quotas cho Bedrock, xin tăng nếu gần 0 (Tuấn)
- [ ] Điền Cost Anomaly Detection (Tuấn)
- [ ] Chuyển policy `CPAWS-Bedrock-Four-Models` sang group `cpaws-genai` (Tuấn)
- [ ] `cdk bootstrap` ở `ap-southeast-1` (Tuấn), sau đó Tiến `cdk deploy` stack `CpawsData`
- [ ] Ghi kết quả test model vào ADR-0004 (Phước)
