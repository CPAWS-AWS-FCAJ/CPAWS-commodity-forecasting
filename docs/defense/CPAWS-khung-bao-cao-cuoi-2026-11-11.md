# CPAWS — Khung báo cáo cuối kỳ và phân công biên soạn

**Phiên bản:** DRAFT v0.2 — 11/11/2026 (cập nhật theo review PR #113)  
**Cơ sở:** `origin/developer` @ [`a5c1635`](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/commit/a5c16351026b882b0ee53a0119e16d2b6c7e9cc3) (11/11/2026); trạng thái triển khai cập nhật theo review của Khải và Tiến trên PR #113. Các kết quả phát sinh sau mốc này phải bổ sung bằng chứng riêng.  
**Mốc cần chốt:** khung báo cáo trước **15/11/2026**; ghép bản đầy đủ trước **27/11/2026**.  
**Trạng thái:** Đã điều chỉnh theo review Khải và Tiến trên PR #113, chờ approve/khóa khung. **Phân công và ngày bàn giao nội bộ bên dưới chưa phải cam kết đã được các thành viên chấp thuận.**

## 1. Mục tiêu và nguyên tắc

Báo cáo trình bày hệ thống CPAWS đã thực hiện: thu thập/kiểm soát chất lượng dữ liệu, dự báo phân vị lợi suất của vàng, bạc, WTI, Brent, đánh giá champion–challenger, giao diện/API, chatbot Bedrock, triển khai AWS, an toàn vận hành và chi phí.

- **Phân biệt ba loại bằng chứng:** `ĐÃ CÓ` (tài liệu/kết quả đã được dẫn nguồn hoặc xác nhận), `CHỜ XÁC NHẬN` (trạng thái vận hành/bản deploy cần thành viên xác thực), `CHƯA CÓ` (chưa có kết quả chính thức hoặc số đo); tuyệt đối không chuyển kế hoạch thành thành tựu.
- **Không tuyên bố mô hình học sâu đang chạy production.** Theo ADR-0011 và tài liệu vận hành, champion là `baseline-q252`; S1a (`s1a-l094`) là challenger shadow. Không triển khai pipeline retrain SageMaker/Step Functions trong phạm vi trước bảo vệ.
- **Không điền hoặc phân tích kết quả test2020 trước lần chạy official được duyệt**; một lần chạy, đúng protocol khóa ở `docs/experiments/test2020-plan.md`. Kết quả chỉ dùng báo cáo/bảo vệ, không tự đổi champion trước 22/11.
- **Không đánh đồng** validation 2019, replication 2017–2018, rolling accuracy thực tế và official test2020: mỗi tập có mục đích, giới hạn và bằng chứng riêng.
- Các tài liệu `docs/defense/*.md` tại mốc tham chiếu là **bản nháp và nguồn tư liệu**, không mặc nhiên là bản cuối được nhóm duyệt. Chi phí AWS phải dựa trên Cost Explorer/Budgets/Pricing Calculator với thời gian đo rõ ràng, không dùng con số ước tính như chi phí thực trả.

## 2. Cấu trúc đề xuất

Có thể giữ **5 chương nội dung chính** theo yêu cầu nhóm, thêm Mở đầu và Kết luận/Phụ lục. Mỗi chương cần ghi người phụ trách, trạng thái nguồn và bằng chứng đối chiếu.

| Phần | Nội dung trọng tâm | Chủ trì đề xuất | Phối hợp / xác nhận | Nguồn trong repo / PR |
|---|---|---|---|---|
| **Mở đầu** | Bài toán, phạm vi MVP, 4 tài sản, 1–7 phiên, mục tiêu giải thích và giới hạn không tư vấn đầu tư | **Khải** | Long, Phước | `README.md`; `docs/api/contract.md`; `docs/defense/chatbot.md` |
| **Chương 1 — Mô hình & dữ liệu** | Nguồn dữ liệu, calendar/target, chất lượng dữ liệu; lựa chọn baseline-q252 và S1a, các thử nghiệm DLinear/K3/K3b/K4; giải thích ADR-0011 | **Khải** (Research Lead) | **Long** (review), Tiến (deploy) | `docs/defense/lua-chon-kien-truc-va-mo-hinh.md`; bản nháp “Mô hình và đánh giá” theo Khải; ADR-0005, 0008–0012; `docs/eda/eda-prices-2026-10.md`; `docs/experiments/k3b-volatility-results-2026-10.md` |
| **Chương 2 — Phương pháp và kết quả đánh giá** | Split theo thời gian, log return và 7 quantile, pinball skill, calibration, common mask, thống kê; validation/rolling/test2020 phân biệt rõ | **Long** | **Khải** (review khoa học, biên tập/duyệt tính nhất quán), Tuấn/Tiến (rolling API/job) | `docs/defense/phuong-phap-danh-gia.md`; `docs/experiments/test2020-plan.md`; `docs/eval/walk-forward-contract.md`; `docs/api/accuracy-schema.md` |
| **Chương 3 — Chatbot & tương tác người dùng** | `POST /chat`, Bedrock, tool `get_forecast`/`get_news`, citation, guardrails, benchmark, hạn chế; vị trí chatbot trong website | **Phước** | **Tiến** (web/API), Khải (review), Long (đánh giá phương pháp) | `docs/defense/chatbot.md`; `docs/experiments/chatbot-benchmark-v2-2026-10.md`; `docs/demo/demo-chatbot-2026-11-08.md`; `docs/api/contract.md`; kết quả official Haiku v4 sau lần chạy theo [#84](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/84) |
| **Chương 4 — Kiến trúc, triển khai & vận hành** | Sơ đồ hiện trạng và đối chiếu proposal; các stack CDK tại ngày chốt; S3/DynamoDB/Lambda/Scheduler/Amplify, ingest→predict→API→web, monitoring, rollback, CI, rolling accuracy và giao diện web | **Tiến** | **Khải** (pipeline), **Tuấn** (IAM/API), Long (rolling accuracy) | `docs/defense/trien-khai-van-hanh.md`; `docs/architecture/CPAWS-architecture-current.drawio` / `.png` ([#94](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/94)); `docs/architecture/CPAWS-architecture.jpg` (proposal); `infra/app.py`; `infra/stacks/`; `.github/workflows/ci.yml`; `web/`; ADR-0005; `docs/api/contract.md` |
| **Chương 5 — Bảo mật, chi phí và giới hạn** | Cognito, IAM least privilege, SSM secrets, encryption, quotas; chi phí đo thực tế, ngân sách, trade-off với phương án khác; rủi ro/giới hạn và cải tiến | **Tuấn** | **Tiến** (usage/deploy), **Khải** (Cost Explorer/quyết định kiến trúc), Phước (chatbot cost) | ADR-0004, ADR-0006, ADR-0011; `docs/defense/trien-khai-van-hanh.md`; `docs/defense/lua-chon-kien-truc-va-mo-hinh.md`; `docs/defense/security-and-cost.md` (bản nháp [#116](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/116)); `infra/stacks/` |
| **Kết luận và phụ lục** | Phạm vi hoàn thành, bằng chứng thật, giới hạn, hướng phát triển; hình hệ thống, bảng metric, tài liệu tham khảo, phiên bản commit | **Khải** (biên tập/duyệt) | **Long** (ghép bản cuối), cả nhóm | Năm chương trên và các evidence đã duyệt |

> **Phân công cập nhật theo review:** Khải chủ trì Chương 1 (Research Lead), Long review Chương 1, chủ trì Chương 2 và ghép bản cuối theo `tasks.md` tuần 6–7; Khải biên tập và duyệt tính nhất quán. Các chủ trì/phối hợp còn lại tiếp tục xác nhận khi khóa khung 15/11.

### Chương 1 — Mô hình & dữ liệu (đề cương chi tiết)

1.1. Bài toán: vàng, bạc, WTI, Brent, các kỳ hạn 1–7 phiên; vì sao dự báo log return/phân vị thay cho sai số mức giá.  
1.2. Dữ liệu, nguồn, lịch tài sản, availability, quality flags, rejected rows và giới hạn dữ liệu lịch sử.  
1.3. Mốc tham chiếu `naive`; champion `baseline-q252` và 7 phân vị; cách suy ra `prob_up` xấp xỉ.  
1.4. Các hướng thử: DLinear, K3 CEEMDAN–DLinear, K3b, S1a, K4; phân biệt kết quả validation với kế hoạch replication CEEMDAN–LSTM (`docs/experiments/ceemdan-lstm-replication-plan.md`). **Replication hiện mới ở giai đoạn kế hoạch; chỉ trình bày kết quả nếu đã chạy xong và có bằng chứng.**  
1.5. Lý do chọn champion hiện tại và chạy S1a shadow; ADR-0011 thay thế retrain tuần bằng cập nhật cửa sổ trượt và giám sát champion/challenger.  
1.6. Giới hạn: dữ liệu, khả năng tổng quát hóa, không khẳng định dự báo chắc chắn.

### Chương 2 — Đánh giá (đề cương chi tiết)

2.1. Quy tắc thời gian: train 2014–2018, validation 2019, official test từ 2020-01-02 đến target cutoff 2026-10-23; chỉ dùng thông tin tại ngày gốc.  
2.2. Target log return, lịch NYSE/CME, endpoint validity và common mask.  
2.3. Metric chính `pinball_skill`, chỉ số bổ sung coverage/width/calibration/MAE-return/sign/Brier; không dùng RMSE/MAPE mức giá để chọn mô hình.  
2.4. Giao thức test2020 đã khóa: 4 tài sản × 7 horizon, bootstrap, Holm, mẫu dầu `all`/`excl_roll`, bất biến q50 của S1a.  
2.5. Rolling accuracy 56 ngày UTC cho **forecast đã phát hành**, tách biệt với test hồi cứu; giải thích trạng thái `not_ready`/`collecting` và provenance.  
2.6. **[CHƯA CÓ — chỉ bổ sung sau official run]** Bảng kết quả test2020, CI/p-value, loại mẫu và giới hạn; không sửa protocol sau khi thấy kết quả.  
2.7. Kết luận theo đúng phạm vi test, không tự đổi champion trước 22/11.

### Chương 3 — Chatbot (đề cương chi tiết)

3.1. Mục tiêu hỏi đáp và ranh giới giữa LLM với hệ thống phát hành forecast.  
3.2. Kiến trúc `POST /chat` → Bedrock/tool → câu trả lời; định danh và hạn mức người dùng.  
3.3. Tool forecast/news, dẫn nguồn, hạn chế tự bịa số liệu/tư vấn đầu tư.  
3.4. Các bộ benchmark và phương pháp đánh giá (v2, dev v3, official v4), ghi **đúng thời điểm và trạng thái**.  
3.5. **[CHỜ KẾT QUẢ]** Official Haiku v4 13–14/11: Phước điền từ bằng chứng lần chạy thực tế, không ước đoán.  
3.6. Độ trễ, chi phí gọi model, các giới hạn của fixture-vs-production và phương án cải tiến.

### Chương 4 — Kiến trúc/vận hành (đề cương chi tiết)

4.1. Sơ đồ **hiện trạng** tại `docs/architecture/CPAWS-architecture-current.drawio` / `.png` ([#94](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/94), bản chụp 08/11); đối chiếu với sơ đồ đề xuất `docs/architecture/CPAWS-architecture.jpg`. Mô tả **các stack CDK tại ngày chốt** từ `infra/app.py` (hiện 5 stack: `CpawsData`, `CpawsOps`, `CpawsServing`, `CpawsAuth`, `CpawsApi`); `CpawsNews` theo [#52](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/52) chưa có trong `infra/app.py` tại mốc review. Không cố định số stack cho ngày nghiệm thu.  
4.2. Pipeline Scheduler → Lambda ingest → S3 → Lambda predict → DynamoDB/S3 shadow → API → web/chatbot.  
4.3. Quy trình release/deploy, CI từ `.github/workflows/ci.yml`, kiểm tra cấu hình, logs/alarms, idempotency và rollback.  
4.4. Rolling accuracy job và API: `cpaws-dev-accuracy` và `GET /accuracy/{asset}` đã deploy 10/11 ([#87](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/87)); job `rolling_8w` và alarm đã deploy 11/11 ([#89](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89)), **Scheduler đang DISABLED**. Chỉ đánh dấu chạy theo lịch sau khi dry-run được review và PR bật Scheduler đã triển khai.  
4.5. Bằng chứng chạy thật (CloudWatch, API smoke, ảnh giao diện) và các giới hạn vận hành.
4.6. **Giao diện web và quy tắc hiển thị**: trang Amplify (`web/`), 7 thẻ horizon h=1…7 và nhãn 60/40, khối “Độ tin cậy” lấy từ `rolling_8w`, hiển thị giá vàng/bạc theo ADR-0005 (a), quy đổi khoảng dự báo ra số tiền theo ADR-0005 (2) và [#117](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/117). **Tiến chủ trì; Khải review cách hiển thị dự báo.** Không khẳng định chức năng quy đổi đã deploy khi #117 chưa merge và chưa build web lại. Nguồn: `web/`, ADR-0005, `docs/api/contract.md`.

### Chương 5 — Bảo mật/chi phí (đề cương chi tiết)

5.1. IAM user/role và chính sách tối thiểu, quyền S3 tách thao tác ghi/xóa; không công bố secrets, Account ID hoặc policy nhạy cảm trong báo cáo công khai.  
5.2. Cognito authorizer, SSM SecureString, S3 encryption/versioning, CORS, throttling, quota chatbot.  
5.3. Cấu trúc chi phí theo dịch vụ (Lambda, S3, DynamoDB, Bedrock, API Gateway, Amplify, CloudWatch); ghi nguồn và kỳ đo.  
5.4. Cost Explorer/Budgets/Pricing Calculator: phân biệt **chi phí thực tế**, **dự toán** và **budget**; cần ảnh hoặc số xuất chính thức từ tài khoản AWS.  
5.5. Quyết định không dùng SageMaker/Step Functions ở MVP và đánh đổi tính năng/chi phí; giới hạn và hướng mở rộng.

## 3. Bằng chứng đã có và còn thiếu

| Hạng mục | Trạng thái tại mốc review 11/11 | Cần người phụ trách bổ sung trước bản đầy đủ |
|---|---|---|
| Tài liệu phương pháp và thiết kế test2020 | **ĐÃ CÓ** — `docs/defense/phuong-phap-danh-gia.md`, `docs/experiments/test2020-plan.md` | Long cập nhật kết quả official sau run, gắn checksum và run provenance |
| Kết quả validation và thử nghiệm lịch sử | **ĐÃ CÓ** — ADR-0009–0012 và tài liệu `docs/experiments/*results*`; riêng CEEMDAN–LSTM **mới có kế hoạch**, chưa được ghi là kết quả replication | Khải/Long chọn bảng đã có chứng cứ, chú thích tập thời gian; chỉ đưa CEEMDAN–LSTM vào mục kết quả khi thực chạy xong |
| Kết quả official test2020 | **CHƯA CÓ** — chưa đến cửa sổ chạy chính thức 16–22/11; approval vận hành đã có ở #88 | Long chạy một lượt theo lịch 16/11 (dự phòng 17/11), cập nhật kết quả sau khi audit artifact |
| Mô tả luồng chatbot và benchmark v2 | **ĐÃ CÓ** — `docs/defense/chatbot.md`, tài liệu benchmark v2 | Phước rà soát bản chatbot cuối; cập nhật official v4 theo [#84](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/84) khi có output |
| Kết quả official benchmark Haiku v4 | **CHƯA CÓ** bằng chứng kết quả trong các tài liệu kiểm tra | Phước sau lần chạy dự kiến 13–14/11 |
| Kiến trúc/CDK/luồng vận hành | **ĐÃ CÓ** — `docs/defense/trien-khai-van-hanh.md`, `infra/`; sơ đồ **hiện trạng** drawio/png [#94](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/94) và JPG proposal để so sánh | Tiến/Khải đối chiếu trạng thái deploy và stack tại ngày chốt; mục 9 tài liệu vận hành cần cập nhật riêng |
| Rolling Accuracy job và GET `/accuracy/{asset}` | **ĐÃ DEPLOY — chưa chạy theo lịch**: bảng/API [#87](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/87) deploy 10/11; job/alarm [#89](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89) deploy 11/11; **Scheduler DISABLED** | Tiến đăng kết quả dry-run 4 tài sản tối 11/11 ở #89 và mở PR bật Scheduler trước 20/11; Tuấn review trước khi bật lịch; Long kiểm record/API sau lượt chạy thật đầu tiên |
| Giao diện web | **ĐÃ CÓ** — Amplify; nguồn triển khai tại mục 7 `docs/defense/trien-khai-van-hanh.md` | Tiến cập nhật ảnh bản deploy và đối chiếu `web/`/API, Khải review phần trình bày dự báo |
| Quy đổi khoảng dự báo ra số tiền | **CHỜ XÁC NHẬN** — theo ADR-0005 (2), [#117](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/117) | Tiến xác nhận #117 merge và web đã build/deploy lại trước khi ghi **ĐÃ TRIỂN KHAI** |
| Quyền và phương án bảo mật | **ĐÃ CÓ TÀI LIỆU** — ADR-0006, CDK, phần vận hành; bản nháp Chương 5 tại [#116](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/116) (`docs/defense/security-and-cost.md`) | Tuấn bổ sung bằng chứng đã kiểm duyệt, cập nhật trạng thái #116 khi merge, không để lộ dữ liệu nhạy cảm |
| Chi phí thực trả theo dịch vụ/kỳ | **CHƯA ĐỦ SỐ LIỆU ĐỂ KHẲNG ĐỊNH** từ tài liệu kiểm tra | Tuấn/Khải xuất số Cost Explorer; Tiến/Phước góp phần web/chatbot |
| Phần phân công và lịch biên soạn | **DỰ THẢO** (file này) | Cả nhóm chốt chủ trì và ngày bàn giao |

## 4. Lịch và bàn giao đề xuất

> **Mốc 15/11 và 27/11** lấy từ checklist công việc. Các mốc trung gian là **đề xuất để cả nhóm xác nhận**, không phải deadline đã giao chính thức.

| Hạn đề xuất | Công việc/đầu ra | Chủ trì | Phụ thuộc |
|---|---|---|---|
| **11–12/11** | Long mở PR #113; Khải/nhóm phản hồi cấu trúc, phân công, thiếu chương | Long → Khải/cả nhóm | Không có điều kiện kỹ thuật |
| **13/11** | Chốt chủ trì + reviewer từng phần và quy tắc dẫn nguồn/số liệu | Khải | Nhóm phản hồi |
| **15/11** | **Khóa khung báo cáo**: mục lục, người viết, hạn, danh sách bằng chứng cần bổ sung | Khải điều phối; Long cập nhật file | Xác nhận phân công |
| **16–19/11** | Nộp bản nháp Ch.1/3/4/5 từ bằng chứng hiện có; Ch.2 nộp phần phương pháp trước | **Khải (Ch.1)**, **Long (Ch.2)**, Phước, Tiến, Tuấn | Phước cần official chatbot v4 để chốt kết quả; kiến trúc/API cần trạng thái mới |
| **16–22/11** | Official test2020 một lượt **theo approval #88 và runbook**, audit artifact/hash; lịch chốt 16/11 (09:00–12:00 VN), dự phòng 17/11 | Long; Khải review | IAM chốt, preflight/pip và điều kiện approval #88 |
| **Trong 2 ngày sau official run** | Long thêm kết quả và giới hạn vào `docs/defense/phuong-phap-danh-gia.md`, PR riêng | Long; Khải review | Artifact test2020 đã kiểm chứng |
| **23–25/11** | **Long ghép bản cuối**; Khải biên tập/duyệt tính nhất quán; các chủ trì xử lý review, đối chiếu phiên bản/deploy/số đo, chuẩn hóa sơ đồ và nguồn | Long (ghép); Khải (biên tập/duyệt) | Bản nháp các chương, kết quả chính thức nếu có |
| **26/11** | Rà soát cuối: tính nhất quán metric, kiến trúc, số liệu chi phí, bảo mật và hạn chế | Cả nhóm; Khải quyết định chốt | Bản ghép hoàn chỉnh |
| **27/11** | **Bản ghép báo cáo cuối** và đầu vào cho slide/bảo vệ | **Long ghép bản cuối**; Khải duyệt | Hoàn thành review và bổ sung evidence |
| **23–29/11** | Xây dựng, đồng bộ và review slide bảo vệ theo nội dung báo cáo đã chốt | Cả nhóm, Khải điều phối | Chương đã review, bằng chứng và hình minh họa |

## 5. Quy định biên soạn và nghiệm thu

Mỗi chủ trì nộp tối thiểu: (1) mục tiêu và thiết kế; (2) điều đã triển khai; (3) bằng chứng gắn đường dẫn file/PR/ảnh/log và ngày đo; (4) kết quả kèm đơn vị, cửa sổ thời gian và tập đánh giá; (5) hạn chế; (6) kết luận không vượt quá bằng chứng.

- **Nội dung mâu thuẫn:** ưu tiên ADR đã chấp nhận + contract + code/evidence đúng phiên bản; báo Khải trước khi sửa nội dung khác nhau giữa proposal và triển khai.
- **Giá trị chưa xác minh:** ghi `[CHỜ SỐ LIỆU]` / `[CHỜ XÁC NHẬN]`; không tạo số giả hay ảnh giả.
- **Đánh giá mô hình:** không diễn giải S1a là production champion; không lấy validation làm official test; không gọi replication 2017–2018 là test2020; CEEMDAN–LSTM hiện là kế hoạch, không tuyên bố kết quả nếu thiếu evidence.
- **Chatbot:** không đánh đồng dev benchmark với official v4. Không sửa file thuộc locked benchmark trước khi lần official hoàn tất.
- **Bảo mật:** loại bỏ token/API key/địa chỉ email bí mật, thông tin nhận dạng tài khoản; chỉ trình bày IAM ở mức nguyên tắc và kiểm chứng phù hợp.
- **Trước khi merge:** 1 người viết + 1 reviewer khác người viết; Khải chốt tính nhất quán tổng thể.
- **Task này hoàn tất khi:** khung đã được nhóm xác nhận, mỗi chương có owner/reviewer/deadline, danh mục evidence thiếu rõ ràng, và có nơi lưu bản khung dùng chung. File hiện tại chỉ là **bản dự thảo sẵn để review**.

## 6. Danh mục nguồn chính (đường dẫn tương đối trong repo)

- `docs/defense/lua-chon-kien-truc-va-mo-hinh.md`
- `docs/defense/phuong-phap-danh-gia.md`
- `docs/defense/chatbot.md`
- `docs/defense/trien-khai-van-hanh.md`
- `docs/experiments/test2020-plan.md`, `docs/experiments/test2020-runbook.md`, `docs/experiments/ceemdan-lstm-replication-plan.md` (kế hoạch, chưa phải kết quả)
- `docs/adr/0005-price-data-sources.md`, `docs/adr/0008-target-quantiles-evaluation.md`
- `docs/adr/0009-ceemdan-dlinear-k3-result.md`, `docs/adr/0010-k3b-volatility-scaling-result.md`
- `docs/adr/0011-weekly-champion-challenger-instead-of-retrain.md`, `docs/adr/0012-k4-fhs-gjr-result.md`
- `docs/api/contract.md`, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`
- `docs/experiments/chatbot-benchmark-v2-2026-10.md`, `docs/demo/demo-chatbot-2026-11-08.md`, official v4 [#84](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/84) (bổ sung kết quả sau run)
- `docs/architecture/CPAWS-architecture-current.drawio`, `docs/architecture/CPAWS-architecture-current.png` (hiện trạng [#94](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/94)); `docs/architecture/CPAWS-architecture.jpg` (proposal); `.github/workflows/ci.yml`, `infra/app.py`, `infra/stacks/`, `web/`

---

**Đường dẫn file trong PR #113:** `docs/defense/khung-bao-cao-cuoi.md`. Chỉ cập nhật tài liệu khung; không sửa các file đã khóa của official Haiku v4 hay test2020.
