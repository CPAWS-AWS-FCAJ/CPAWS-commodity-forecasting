# ADR-0014: Mở tự đăng ký Cognito trong thời gian chấm đồ án

- Ngày: 2026-11-16
- Trạng thái: Đề xuất
- Người viết: Tuấn; người duyệt: Khải (chờ review PR)

## Bối cảnh

Theo xác nhận của mentor ngày 13/11/2026, đồ án không tổ chức buổi bảo vệ trực tiếp. Giảng viên chấm bài độc lập bằng cách truy cập Production thông qua portal. Vì vậy, cần cho phép giảng viên tự tạo tài khoản để truy cập ứng dụng trong thời gian chấm.

Hiện tại, Cognito User Pool `cpaws-dev-users` đang tắt tự đăng ký (`self_sign_up_enabled=False`). Web có cờ `VITE_ALLOW_SIGNUP`, nhưng đây chỉ là điều khiển giao diện, không phải ranh giới bảo mật: Cognito App Client ID là thông tin công khai và người dùng có thể gọi trực tiếp API SignUp nếu User Pool cho phép.

User Pool đang sử dụng `COGNITO_DEFAULT`. Hạn mức gửi email và phạm vi áp dụng phụ thuộc cấu hình, quota hiện hành của Amazon Cognito. Nhóm phải kiểm tra quota thực tế trong AWS Service Quotas và cấu hình Cognito trước khi mở đăng ký; ADR này không mặc định một con số hoặc giờ reset chưa được xác minh.

## Các phương án

1. Giữ tắt tự đăng ký, nhóm tạo riêng tài khoản cho giảng viên — kiểm soát tốt hơn nhưng gây thêm thao tác cấp phát và bàn giao tài khoản.
2. Mở tự đăng ký có thời hạn phục vụ chấm đồ án — thuận tiện cho giảng viên, nhưng tăng đối tượng có thể truy cập dữ liệu và tiêu thụ quota chatbot.

## Quyết định

Chọn phương án 2, với các điều kiện:

- Hoàn thành ADR trước, sau đó tạo PR CDK riêng cho `CpawsAuth`.
- Chỉ thay đổi `self_sign_up_enabled`, `auto_verify` email, `password_policy` và `user_verification`; kiểm tra `cdk diff` không có Replacement. Tiến review PR CDK.
- Deploy `CpawsAuth` trước, sau đó build web với `VITE_ALLOW_SIGNUP=true`. PR web #132 đã được thực hiện.
- Yêu cầu xác minh email khi đăng ký.
- Áp dụng quota chatbot đã triển khai: 20 lượt/người/ngày và 100 lượt/ngày toàn hệ thống (PR #55, #63; `CpawsApi` deploy ngày 02/11/2026). Hai giới hạn có unit test; bộ đếm đã được quan sát khi gọi API thật, nhưng chưa có kiểm thử thực tế tới ngưỡng bị chặn và trả `429 rate_limited`. Quota toàn hệ thống được chia sẻ; người ngoài có thể sử dụng hết quota trong ngày chấm. Quota reset lúc 00:00 giờ Việt Nam.
- Web không cung cấp chức năng tải dữ liệu giá; luôn hiển thị nguồn dữ liệu.
- Tạo riêng một tài khoản grader để bàn giao. Thông tin đăng nhập chỉ gửi qua kênh riêng, không đưa vào Git repository hoặc website Hugo.
- Chỉ mở đăng ký sau khi hoàn thành các bước và trước ngày 21/11/2026; không thực hiện trong khoảng 19:05–19:35.
- Nếu không hoàn tất trước thời điểm freeze 22/11/2026, không mở đăng ký; chỉ sử dụng tài khoản grader được nhóm tạo riêng.

## Rủi ro và biện pháp giảm thiểu

- **Truy cập dữ liệu Yahoo:** bất kỳ ai có email hợp lệ đều có thể đăng ký và xem giá vàng/bạc được chuyển đổi từ dữ liệu Yahoo. Việc yêu cầu xác minh email, không cung cấp tính năng tải dữ liệu và hiển thị nguồn chỉ giảm thiểu rủi ro, không loại bỏ vấn đề về điều khoản sử dụng dữ liệu.
- **Cạn quota chatbot:** giới hạn 100 lượt/ngày dùng chung cho toàn hệ thống; người ngoài có thể tiêu thụ hết quota trước giảng viên. Theo dõi mức sử dụng trong thời gian chấm.
- **Giới hạn email:** Cognito có quota gửi email phụ thuộc cấu hình và phạm vi áp dụng của dịch vụ. Trước khi mở đăng ký, kiểm tra quota thực tế trong AWS Service Quotas và cấu hình email của User Pool; nếu không đủ khả năng gửi email xác minh cho người chấm, không mở đăng ký.
- **Đóng đăng ký:** trong vòng một ngày sau khi mentor xác nhận hoàn tất chấm, phải tắt tự đăng ký ở Cognito, build lại web với `VITE_ALLOW_SIGNUP=false`, sau đó vô hiệu hóa/xóa các tài khoản tự đăng ký; giữ lại tài khoản của nhóm và tài khoản grader.
- **Hạn chót đóng:** nếu chưa có thông báo hoàn tất chấm, ngày 10/12/2026 là hạn chót tuyệt đối để đóng tự đăng ký.

## Hệ quả

Giảng viên có thể chủ động tạo tài khoản trong thời gian chấm mà không cần nhóm cấp từng tài khoản. Đổi lại, phạm vi người có thể truy cập ứng dụng và sử dụng quota chatbot tăng lên. Việc mở và đóng đăng ký phải được thực hiện theo đúng thứ tự triển khai, có PR review và lưu lại bằng chứng.

ADR-0005 được cập nhật để ghi nhận việc mở đăng ký làm suy yếu lớp giới hạn người xem dữ liệu Yahoo; xem ADR-0014.
