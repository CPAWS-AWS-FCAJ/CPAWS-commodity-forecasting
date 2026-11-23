# ADR-0014: Mở tự đăng ký Cognito trong thời gian chấm đồ án

- Ngày: 2026-11-16
- Trạng thái: Chấp nhận phương án 2 (giữ tự đăng ký có thời hạn) từ 23/11/2026 16:44 giờ Việt Nam, theo quyết định của Data & Security Lead trên PR #148; không áp dụng hồi tố. Việc mở ngày 22/11/2026 21:07 vẫn là sai lệch.
- Người có thẩm quyền quyết định: Data & Security Lead (Tuấn).
- Người viết: Tuấn (bản gốc 16/11/2026); Khải (mục "Cập nhật 23/11/2026").
- Người review: Khải (bản gốc); Data & Security Lead (bản sửa đổi); Tiến (mọi PR CDK `CpawsAuth` đi kèm).

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

## Cập nhật 23/11/2026: mở sau thời hạn và quyết định xử lý

**Diễn biến thực tế.** PR CDK `CpawsAuth` (#141) merge ngày 19/11/2026, nhưng deploy (Tiến, từ `production` tag `v1.0.0`) diễn ra lúc 21:07 ngày 22/11/2026, cùng lượt release v1.0.0; web Amplify Deployment 6 build với `VITE_ALLOW_SIGNUP=true` lúc 21:27. Mục "Quyết định" ở trên yêu cầu mở trước 21/11 và không mở nếu chưa xong trước freeze 22/11, nên đây là **sai lệch so với điều kiện đã thống nhất**, không phải ngoại lệ đã được duyệt. Ngày 23/11 Data & Security Lead đã nêu sai lệch này trong review PR #145.

**Tác động đã biết tới 23/11:** nhóm đã đăng ký thử tài khoản mới ngày 23/11; chưa có số liệu đầy đủ về số tài khoản tự tạo, cần Data & Security Lead kiểm trong Cognito. Chi phí: Cognito Lite/Essentials miễn phí tới 10.000 MAU/tháng; chatbot bị chặn ở 100 lượt/ngày toàn hệ thống (ước tính khoảng 1,2 USD/ngày nếu dùng hết; xem cách tính ở bảng giám sát bên dưới); email xác minh dùng `COGNITO_DEFAULT` nên số email mỗi ngày bị giới hạn ở mức thấp.

**Quyết định (23/11/2026 16:44 giờ Việt Nam, Data & Security Lead, comment trên PR #148):** chấp thuận **phương án 2** với các điều kiện ở dưới. Quyết định có hiệu lực từ thời điểm đó, **không áp dụng hồi tố**: khoảng từ 22/11/2026 21:07 tới 23/11/2026 16:44 vẫn ghi là sai lệch so với điều kiện "mở trước 21/11". Chấp thuận quyết định không thay thế review, approve và merge các PR liên quan.

Hai phương án đã xem xét:

1. **Đóng ngay** (đề nghị của Data & Security Lead ngày 23/11), mỗi bước qua PR riêng có review:
   1. PR CDK tắt `self_sign_up_enabled` (Tiến review CDK, Data & Security Lead duyệt) → merge → release → deploy `CpawsAuth`, kiểm `cdk diff` chỉ sửa tại chỗ.
   2. Build web với `VITE_ALLOW_SIGNUP=false`, upload Amplify.
   3. **Xử lý tài khoản đã đăng ký** (tắt self-signup không tự động xử lý tài khoản đã có):
      - kiểm kê toàn bộ user của `cpaws-dev-users` (username, ngày tạo, trạng thái); danh sách lưu ngoài repo, chỉ chia sẻ qua kênh riêng của nhóm;
      - đối chiếu với danh sách được phép: tài khoản 5 thành viên và tài khoản grader;
      - tài khoản ngoài danh sách: vô hiệu hóa ngay (`AdminDisableUser`), xóa sau khi nhóm xác nhận không còn cần (`AdminDeleteUser`); không xóa tài khoản nhóm hay grader;
      - ghi số lượng tài khoản đã vô hiệu hóa và ngày thực hiện vào Chương 4 (không ghi email hay tên người dùng).
   4. Người chấm và người dùng thử dùng tài khoản do Data & Security Lead tạo tay (`AdminCreateUser`), gửi qua kênh riêng.
2. **Giữ mở có thời hạn (được chọn)** cho người chấm và đợt dùng thử của bạn bè, người thân nhóm. Điều kiện:
   - **giới hạn người dùng thử theo từng thành viên:** mỗi thành viên mời tối đa 8 người (5 thành viên, tối đa 40 người), gửi link riêng qua tin nhắn cá nhân, không đăng công khai (mạng xã hội, nhóm đông người, README, trang Hugo); mỗi thành viên giữ danh sách người mình đã mời (chỉ tên gọi, không ghi lên repo) để đối chiếu khi Data & Security Lead kiểm số tài khoản;
   - giám sát theo bảng bên dưới;
   - **đóng ngay** theo các bước của phương án 1 khi chạm một ngưỡng trong bảng, hoặc khi Yahoo, mentor hay hội đồng yêu cầu;
   - mốc đóng: trong 1 ngày sau khi mentor xác nhận chấm xong, **chậm nhất 10/12/2026**; khi đóng làm đủ bước 1–3 của phương án 1;
   - vẫn tạo riêng tài khoản grader, phòng khi hết hạn mức email.

**Cách tính ngưỡng 50 tài khoản.** Chỉ đếm **tài khoản tự đăng ký của người ngoài nhóm**: user được tạo bằng **tự đăng ký** sau 22/11/2026 21:07 giờ Việt Nam **và không thuộc danh sách được phép**. Lưu ý múi giờ: `UserCreateDate` của Cognito và thời gian sự kiện CloudTrail trả theo UTC, nên mốc này là `2026-11-22T14:07:00Z`. `ListUsers` không cho biết tài khoản được tạo bằng cách nào; nguồn tạo xác định bằng CloudTrail: tự đăng ký là sự kiện `SignUp` (không có `errorCode`), tài khoản do nhóm tạo là `AdminCreateUser`. CloudTrail ghi `UserSub` thay cho username, nên đối chiếu với `ListUsers` theo thuộc tính `sub`. Danh sách được phép gồm tài khoản 5 thành viên (kể cả tài khoản thử thành viên tự tạo) và tài khoản grader; danh sách này do Data & Security Lead giữ ngoài repo. Tài khoản tạo trước 22/11 21:07 (do nhóm tạo khi pool còn đóng) không tính. Với hạn mức mời 40 người, ngưỡng 50 chừa chỗ cho người được mời tạo lại tài khoản khi nhập sai email.

**Giám sát** (người phụ trách: Data & Security Lead; giờ Việt Nam, UTC+7):

| Chỉ số | Nguồn dữ liệu | Chu kỳ | Ngưỡng đóng sớm |
|---|---|---|---|
| Số tài khoản tự đăng ký | CloudTrail Event history, sự kiện `SignUp` thành công của `cognito-idp` từ `2026-11-22T14:07:00Z`, đối chiếu `UserSub` với `ListUsers` (thuộc tính `sub`) để loại tài khoản trong danh sách được phép | Mỗi ngày lúc 09:00, 13:00 và 21:00 | Vượt 50 tài khoản |
| Tài khoản ngoài danh sách mời | `ListUsers`, so thuộc tính `email` của các tài khoản tự đăng ký với danh sách mời (cách đối chiếu ở dưới) | Mỗi ngày lúc 09:00, 13:00 và 21:00; và ngay khi nhận thông báo đăng ký mới | Có **một** tài khoản tự đăng ký không thuộc danh sách mời |
| Dùng chatbot | Bảng DynamoDB `cpaws-dev-chat-usage`, dòng `pk = global`, `sk = day#<ngày>`: `request_count` và `updated_at` lúc đạt 100 | Mỗi ngày lúc 09:00 (xem ngày hôm trước) | Đạt 100 lượt trước 12:00 hai ngày liên tiếp |
| Lỗi hạn mức email | CloudTrail Event history của Cognito, sự kiện `SignUp`/`ResendConfirmationCode` có `errorCode = LimitExceededException` | Mỗi ngày lúc 09:00 | Xuất hiện ở 2 ngày trở lên |
| Đăng ký bất thường | Cùng nguồn với dòng đầu: số tài khoản tạo trong 1 giờ | Mỗi ngày lúc 09:00 | Từ 10 tài khoản trong 1 giờ |

Kết quả mỗi lần kiểm ghi ngắn (ngày, số liệu, quyết định) vào kênh nhóm; không ghi email hay tên người dùng.

**Đối chiếu danh sách mời mà không đưa thông tin cá nhân lên repo.** Mỗi thành viên gửi riêng cho người giám sát **email** mà người được mời dùng để đăng ký (không cần tên thật), qua tin nhắn cá nhân. Người giám sát giữ danh sách trong một file riêng ngoài repo, chỉ nhóm truy cập được, và xóa file khi đóng đăng ký. Đối chiếu theo thuộc tính `email` trả về từ `ListUsers` (Cognito username do người dùng tự đặt nên không dùng để đối chiếu). Repo và kênh chung chỉ ghi **số lượng** (đã mời, đã đăng ký, ngoài danh sách), không ghi email hay username.

**Phát hiện sớm tài khoản ngoài danh sách.** Kiểm định kỳ chỉ phát hiện sau tối đa vài giờ. Để đáp ứng điều kiện "đóng ngay", thêm hai lớp:
- **Ngay lập tức (đề xuất PR riêng):** thêm Cognito trigger *Post confirmation* (Lambda nhỏ) gửi thông báo có `sub` của tài khoản vừa xác minh lên SNS topic cảnh báo hiện có, để người giám sát nhận email ngay khi có người đăng ký xong. Đây là thay đổi CDK `CpawsAuth`/`CpawsOps`, phải qua PR riêng có Tiến review và Data & Security Lead approve; ADR này không thay thế PR đó.
- **Trong lúc chưa có trigger:** kiểm 3 lần mỗi ngày (09:00, 13:00, 21:00) như bảng trên, và mỗi thành viên báo người giám sát khi người mình mời đăng ký xong.

**Quy trình khi chạm ngưỡng hoặc tới hạn đóng:** Data & Security Lead báo nhóm và quyết định đóng → mở PR CDK tắt `self_sign_up_enabled` (Tiến review) → merge, release → Tiến deploy `CpawsAuth` (ngoài 19:05–19:35 và 20:40–21:00) → build web `VITE_ALLOW_SIGNUP=false` → kiểm kê và vô hiệu hóa tài khoản ngoài danh sách được phép theo bước 3 của phương án 1 → ghi lại ngày, số tài khoản đã vô hiệu hóa vào Chương 4. Nếu cần chặn gấp trước khi PR kịp merge, Data & Security Lead quyết định và ghi lại lý do; thay đổi tay phải được đưa về CDK bằng PR ngay sau đó để `cdk diff` không lệch.

**Bằng chứng kiểm tra (đọc, không đổi cấu hình):**
- Giới hạn chatbot: `infra/stacks/cpaws_api_stack.py` đặt biến môi trường `CHAT_USER_DAILY_LIMIT=20` và `CHAT_GLOBAL_DAILY_LIMIT=100` cho Lambda `cpaws-<env>-chat-api`; `tests/test_infra_chat_api.py` khóa hai giá trị này. Kiểm trên AWS: `aws lambda get-function-configuration --function-name cpaws-dev-chat-api --query "Environment.Variables.[CHAT_USER_DAILY_LIMIT,CHAT_GLOBAL_DAILY_LIMIT]"` phải ra `20` và `100`. Bộ đếm: `src/chatbot/quota.py`, bảng `cpaws-dev-chat-usage`.
- Số tài khoản: `aws cognito-idp list-users --user-pool-id <id pool cpaws-dev-users> --query "Users[].[Username,UserCreateDate,UserStatus,Enabled]" --output table` (lấy id bằng `aws cognito-idp list-user-pools --max-results 20`); không dán kết quả có email hay tên người dùng vào repo hay kênh chung.

**Cách tính 1,2 USD/ngày:** lấy chi phí thật của lần chạy dev 26/10/2026 (prompt và tool v2): 0,35 USD cho 30 câu Haiku 4.5, khoảng 0,012 USD mỗi câu `complex` (`docs/api/contract.md`, mục giới hạn `POST /chat`; đơn giá tham chiếu ở ADR-0004). Giả định cả 100 lượt/ngày đều là câu `complex` gọi Haiku, mỗi câu có số token tương đương lần chạy đó: 100 × 0,012 ≈ 1,2 USD/ngày. Con số là ước tính từ chi phí đo được, chưa tách theo token đầu vào và đầu ra; câu dài hơn hoặc gọi nhiều tool hơn sẽ tốn hơn.


## Hệ quả

Giảng viên có thể chủ động tạo tài khoản trong thời gian chấm mà không cần nhóm cấp từng tài khoản. Đổi lại, phạm vi người có thể truy cập ứng dụng và sử dụng quota chatbot tăng lên. Việc mở và đóng đăng ký phải được thực hiện theo đúng thứ tự triển khai, có PR review và lưu lại bằng chứng.

ADR-0005 được cập nhật để ghi nhận việc mở đăng ký làm suy yếu lớp giới hạn người xem dữ liệu Yahoo; xem ADR-0014.
