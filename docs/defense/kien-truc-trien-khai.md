# Chương 4. Kiến trúc, triển khai và vận hành

> Bản nháp ngày 16/11/2026, sửa 17/11/2026 theo review của Khải và Long trên PR #134. Chủ trì: Tiến; review: Khải (pipeline), Tuấn (IAM/API), Long (rolling accuracy). Cơ sở: `origin/developer` @ `a6eef06` (16/11/2026); kết quả test2020 theo #131.
>
> Chương này tóm tắt và sắp xếp lại theo đề cương 4.1–4.6 của [khung báo cáo cuối](khung-bao-cao-cuoi.md). Chi tiết cấu hình, lệnh vận hành và bảng các lần deploy nằm ở [tài liệu triển khai và vận hành](trien-khai-van-hanh.md) (gọi tắt **TKVH**), dùng làm nguồn và phụ lục. Trạng thái là tại ngày viết; phần nào là kế hoạch thì ghi rõ. Không đưa Account ID, ARN, domain, email hay số liệu giá vào chương này.

## 4.1. Kiến trúc hiện trạng và đối chiếu với proposal

**Hình 4.1** là sơ đồ hiện trạng `docs/architecture/CPAWS-architecture-current.png` (bản ghi "as of 2026-11-13", PR [#125](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/125)). Mọi thành phần trên sơ đồ đã deploy và đang chạy. **Hình 4.2** là sơ đồ trong proposal `docs/architecture/CPAWS-architecture.jpg`, giữ lại để so sánh.

Toàn bộ hệ thống chạy trong một tài khoản AWS, region `ap-southeast-1`, môi trường `dev`, theo kiểu serverless: không máy chủ chạy liên tục, không VPC, không NAT Gateway. Sơ đồ chia ba nhóm:

1. **Thu thập và dự báo hằng ngày** (thứ Ba–thứ Bảy, 19:15 giờ VN): EventBridge Scheduler → Lambda ingest → S3 → Lambda predict → DynamoDB, kèm shadow S1a ghi lên S3.
2. **Đánh giá trên dữ liệu chạy thật** (20:45 giờ VN cùng các ngày): Lambda job accuracy tính `rolling_8w` vào bảng `cpaws-dev-accuracy`.
3. **Dịch vụ cho người dùng:** Amplify Hosting (web React) → Cognito → API Gateway → ba Lambda API (dự báo, độ tin cậy, chatbot) → DynamoDB và Amazon Bedrock.

Hạ tầng (trừ Amplify và vài tài nguyên tạo tay, TKVH §2.2) viết bằng AWS CDK (Python) trong `infra/`, gồm **5 stack** tại ngày viết:

| Stack | Vai trò |
|---|---|
| `CpawsData` | S3 data lake, ECR, Lambda ingest/predict/job accuracy, hai lịch EventBridge Scheduler |
| `CpawsServing` | 4 bảng DynamoDB on-demand: dự báo, nhãn tin, đếm lượt chat, độ tin cậy |
| `CpawsAuth` | Cognito User Pool và app client cho SPA |
| `CpawsApi` | REST API stage `dev`, Cognito authorizer, 3 Lambda API, CORS một origin |
| `CpawsOps` | SNS và 6 CloudWatch alarm gửi email |

Cấu hình chi tiết từng stack và thứ tự phụ thuộc: TKVH §2.1. Stack `CpawsNews` (collector tin, [#52](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/52)) chưa có trong `infra/app.py` tại ngày viết.

**Đối chiếu với proposal.** Kiến trúc thực tế giữ khung của proposal (Scheduler → Lambda → S3 → DynamoDB → API Gateway → web/chatbot) nhưng bỏ hoặc thay một số khối. Mỗi thay đổi đều có quyết định ghi lại:

| Proposal | Hiện trạng | Lý do / quyết định |
|---|---|---|
| Step Functions → SageMaker Training Job → Model Registry, retrain hằng tuần (bước 6–10) | Không có. Hai Lambda nối bằng Lambda destination; champion `baseline-q252` là mốc thống kê 252 phiên, không cần artifact mô hình; challenger S1a chạy shadow từ 04/11 | Các mô hình học sâu và CEEMDAN không vượt mốc trên validation 2019 ([ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md), [ADR-0012](../adr/0012-k4-fhs-gjr-result.md); Chương 1). Official test2020 (16/11, #131) cho S1a cải thiện có ý nghĩa thống kê ở bạc, WTI, Brent (không đủ bằng chứng với vàng), nhưng nhóm giữ `baseline-q252` cho cả 4 tài sản tới hết kỳ; đổi champion cần ADR mới (Chương 1, Chương 2 §9) |
| Bedrock batch inference gắn nhãn tin + Knowledge Bases (S3 Vectors) (bước 4–5, 18) | Không có. Tin demo gắn nhãn tay, đóng gói JSON trong Lambda chat | Gắn nhãn tự động không đạt ngưỡng chất lượng ([ADR-0013](../adr/0013-manual-news-labels-until-defense.md); Chương 3) |
| Nguồn: EIA, FRED, GPR, metals API, Guardian, NYT, RSS Việt Nam | Yahoo Finance (yfinance) cho giá và tỷ giá; EIA và NBP để đối chiếu | Phạm vi dữ liệu và điều khoản ([ADR-0003](../adr/0003-news-and-signal-sources.md), [ADR-0005](../adr/0005-price-data-sources.md)) |
| Secrets Manager (API key) | SSM Parameter Store SecureString | Chỉ một key (EIA); CDK chỉ nhận tên parameter |
| Bedrock chatbot có Guardrails | Bedrock Converse + tool use, **không bật Guardrails** | Chốt 11/11: bật sau benchmark official sẽ đổi hành vi bản đã đánh giá (Chương 3) |
| GitHub Actions CI/CD (bước 19) | Chỉ CI; deploy CDK và push image từ máy thành viên | GitHub không giữ quyền AWS; repo public |
| Amplify Hosting nối Git | Upload zip thủ công | Cần chạy trước buổi chạy thử 08/11; từ 16/11 giữ nguyên domain cho người chấm nên không nối Git (mục 4.3) |
| — (không có trong proposal) | Job `rolling_8w`, route `GET /accuracy/{asset}`, shadow S1a, 6 alarm, giới hạn lượt chat | Thêm trong quá trình làm để đo dự báo chạy thật và kiểm soát chi phí |

## 4.2. Luồng dữ liệu hằng ngày

Các số trong ngoặc là số bước trên Hình 4.1.

```text
19:15 VN  Scheduler (1) ─► Lambda ingest ─(2)─► Yahoo / EIA / NBP
                             └─(3)─► S3 raw/, clean/prices/
                             └─(4) OnSuccess hoặc OnFailure ─► Lambda predict
                                     ├─(5)─► S3 eval/shadow/ (S1a, không hiển thị)
                                     └─(6)─► DynamoDB cpaws-dev-forecasts (ghi có điều kiện)
20:45 VN  Scheduler (7) ─► Lambda job accuracy ─(8–9)─► DynamoDB cpaws-dev-accuracy
Người dùng (10–11) ─► Amplify + Cognito ─(12)─► API Gateway ─► forecasts-api (13)
                                                         ├─► chat-api (14–15) ─► Bedrock
                                                         └─► accuracy-api (16)
```

Những điểm thiết kế chính (chi tiết ở TKVH §3):

- **Giờ chạy khớp với backtest.** Lượt 19:15 giờ VN (12:15 UTC) từ thứ Ba đến thứ Bảy, sau các phiên Mỹ thứ Hai–thứ Sáu. Dữ liệu phiên D chỉ được coi là có từ 12:00 UTC ngày D+1, giống quy tắc trong backtest, nên production không dùng thông tin mà backtest không có.
- **Ingest lỗi vẫn gọi predict.** Predict phát hành tài sản đủ dữ liệu, bỏ qua và báo lỗi tài sản thiếu phiên mới nhất.
- **Chạy lại an toàn.** Predict ghi DynamoDB bằng `PutItem` có điều kiện, không ghi đè bản đã phát hành; job accuracy cũng ghi có điều kiện. Vì vậy predict để retry 0, ingest retry 1.
- **Shadow cô lập.** S1a lỗi không ảnh hưởng champion; lỗi được đếm bằng metric filter và có alarm riêng.
- **Web chỉ đọc kết quả tính sẵn.** API không chạy mô hình khi người dùng mở trang; chatbot lấy số qua tool `get_forecast` đọc cùng bảng với trang dự báo.

## 4.3. Triển khai, CI, rollback và giám sát

**Deploy.** Chỉ deploy từ `developer` sau khi PR đã merge, luôn chạy `cdk diff` trước, mỗi lệnh một stack, một người deploy tại một thời điểm và báo nhóm. Không deploy `CpawsData` trong khung 19:05–19:35. Image container gắn tag bằng SHA ngắn của commit merge, không dùng `latest`. Các tham số `-c` bắt buộc (email nhận alarm, origin CORS) phải truyền ở mọi lần deploy (TKVH §4).

**CI.** GitHub Actions chạy ở mọi push và PR: `ruff`, `pytest` (kể cả test synth CDK từ [#95](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/95)), và phần web `typecheck`, `test`, `build`. `developer` cần ít nhất 1 approve; thay đổi IAM/hạ tầng do Tuấn review. Pre-commit quét bí mật (gitleaks, detect-aws-credentials) vì repo public (TKVH §8).

**Rollback** bằng một lệnh deploy hoặc một lần upload web, không cần build lại image: tắt shadow, quay image predict/ingest cũ, tắt lịch job accuracy, đổi origin CORS, upload lại bản web trước hoặc build lại với cờ cũ. Dữ liệu không mất khi rollback: bucket bật versioning, bảng dự báo và User Pool để `RETAIN` (TKVH §5).

**Giám sát.** Sáu alarm (≥ 1 lỗi trong 5 phút) gửi email qua SNS: lỗi ingest, predict, shadow, job accuracy, chat (crash/timeout) và lỗi `500` của chat. Sau mỗi lượt 19:15 nhóm kiểm tay log `PREDICT_DONE`, `Duration`, số object shadow và trạng thái alarm (TKVH §6, Phụ lục A.3).

**Web và CORS.** Web build từ `developer` và upload zip lên Amplify; các cờ `VITE_*` đọc lúc build, nên đổi cờ chỉ cần build lại web. Commit của mỗi bản upload được ghi lại tay (TKVH §7, 5 lần đến 13/11). API chỉ cho một origin: từ 07/11 là domain Amplify. **Domain Amplify hiện tại là địa chỉ nộp cho người chấm**: giữ chạy tới khi chấm xong và không đổi domain, nên không nối Amplify với GitHub trong phạm vi dự án.

## 4.4. Rolling accuracy: job và API

Khối "Độ tin cậy" trên web hiển thị số đo `rolling_8w` của **dự báo chạy thật** (dự báo đã lưu trước khi biết giá), không phải backtest. Phương pháp ở Chương 2, Phụ lục A.

| Ngày | Bước | PR |
|---|---|---|
| 10/11 | Bảng `cpaws-dev-accuracy`; route `GET /accuracy/{asset}` (cần Cognito), Lambda chỉ đọc | [#87](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/87) |
| 11/11 | Lambda job accuracy (lịch tắt), alarm; dry-run 4 tài sản gọi tay | [#89](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89) |
| 12/11 | Bật lịch `cron(45 13 ? * TUE-SAT *)` UTC, 20:45 giờ VN; `cdk diff` chỉ đổi `State` | [#118](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/118) |
| 13/11 | Web bật khối "Độ tin cậy" (`VITE_ACCURACY_API=true`) | — |

Lượt theo lịch đầu tiên (12/11, 20:45) chạy xong cho cả 4 tài sản: run ở trạng thái `COMPLETED` và con trỏ kết quả đã cập nhật (`promoted`), 30,3 s, 297/1.024 MB, alarm OK; Long xác minh độc lập qua DynamoDB, API và web ([#89](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89)). Run hoàn tất **không** có nghĩa là số đo đã được công bố: khi số ngày cơ sở hợp lệ (khác nhau) chưa đủ 20, API vẫn trả `collecting`, chưa công bố giá trị `overall`, và web hiện "Đang thu thập (n/20)". Ngày 12/11 cả 4 tài sản ở mức 9/20. Nếu mỗi lượt thêm được một ngày cơ sở hợp lệ thì có thể đủ 20 vào khoảng cuối tháng 11; đây chỉ là ước lượng có điều kiện, vì số ngày tăng còn phụ thuộc giá thực tế đã có, điều kiện hợp lệ và provenance của từng ngày. Số hiển thị tại ngày đóng băng: `[CHỜ SỐ LIỆU: chụp 22/11]`.

`GET /accuracy/{asset}` chỉ phục vụ số đo của champion `baseline-q252`. Đánh giá cặp champion–S1a của shadow được job lưu riêng dưới `eval/shadow_eval/` trên S3, không ghi đè số đo champion và không đi qua API (Chương 2 §3.1).

## 4.5. Bằng chứng chạy thật

| Nội dung | Bằng chứng | Nguồn |
|---|---|---|
| Ingest → predict tự động | Lượt tự động đầu tiên 27/10; ba lượt đầu image `c61abdd` (04–06/11): `Duration` 3,25–3,29 s, shadow ghi 4/4, alarm OK | TKVH §3 |
| Ghi có điều kiện | Lượt đầu sau cutover image #48 (30/10): `written 4`, `already_published 0`, bản ghi có `input_snapshot_dt`; điều kiện ghi kiểm trong `DynamoSink.put` | TKVH §3; [#82](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/82) |
| Job accuracy | Dry-run 11/11 (23,7 s), lượt theo lịch 12/11 (30,3 s), `collecting` 9/20 | TKVH §9; [#89](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89) |
| API và CORS trên Amplify | Preflight đúng origin; `/forecasts`, `/accuracy` (4 tài sản) và `POST /chat` trả 200 trên domain Amplify | TKVH §7 |
| Chatbot sau cập nhật bộ tin | Deploy `CpawsApi` 13/11 15:57: `cdk diff` chỉ đổi gói code Lambda chat; hỏi tin WTI ra đúng hai tin EIA mới | TKVH §7; [#123](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/123) |
| Ảnh giao diện | Trang chủ, trang vàng (cơ bản/nâng cao, VND), khối quy đổi, khối "Độ tin cậy", khung chat | `[CHỜ ẢNH: chụp 22/11 sau đăng nhập, che email/token]` |

## 4.6. Giao diện web và quy tắc hiển thị

Web nằm trong `web/`: React + TypeScript + Vite + Tailwind, gọi API bằng TanStack Query, biểu đồ Recharts, đăng nhập bằng Amplify UI `Authenticator` trên Cognito User Pool có sẵn (không dùng Amplify backend). Mọi trang nằm sau đăng nhập. Web gửi ID token trong header `Authorization`; API trả 401 thì web đăng xuất và về màn đăng nhập.

**Các trang:** trang chủ (4 thẻ tài sản), trang tài sản (vàng, bạc, Brent, WTI), trang "Độ chính xác" (khối độ tin cậy của cả 4 tài sản và cách đọc chỉ số), trang "Giới thiệu" (cách đọc dự báo, phương pháp, nguồn dữ liệu).

**Trang tài sản**, từ trên xuống:

1. **7 thẻ kỳ hạn** h = 1…7 phiên. Mỗi thẻ có khoảng dự báo 80% và xác suất tăng, kèm nhãn hướng theo **quy tắc 60/40**: xác suất tăng (làm tròn) ≥ 60% là "Nghiêng tăng", ≤ 40% là "Nghiêng giảm", còn lại "Chưa rõ xu hướng". Nhãn và con số dùng cùng giá trị làm tròn để không mâu thuẫn.
2. **Khối quy đổi ra số tiền** ([#117](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/117), ADR-0005 mục (2)): người dùng nhập một số tiền giả định (đồng), web quy khoảng dự báo của kỳ hạn đang chọn ra khoảng giá trị tương ứng của số tiền đó.
3. **Biểu đồ quạt** của khoảng dự báo; **chế độ nâng cao** thêm bảng phân vị q10/q50/q90 (log return %) và khoảng giá theo từng h.
4. **Khối "Độ tin cậy"** (mục 4.4).
5. **Khung chat** gọi `POST /chat` theo tài sản đang xem (Chương 3).

**Quy tắc hiển thị:**

- Mô hình dự báo **log return** và phân vị, không dự báo mức giá. Web quy return ra khoảng giá bằng giá đóng cửa mới nhất, và luôn hiện khoảng kèm xác suất, không chỉ một con số.
- **USD/VND:** đổi theo tỷ giá đã công bố trong snapshot. Vàng, bạc tính theo VND/lượng (1 lượng = 37,5 g, 1 ounce troy = 31,1034768 g), dầu theo VND/thùng. Nhãn vàng ghi rõ đây là giá thế giới quy đổi, không phải giá vàng miếng trong nước.
- **Vàng, bạc** dùng chuỗi đại diện GLD, SLV quy về USD/oz (không phải giá giao ngay; trang "Giới thiệu" ghi rõ). Giá vàng, bạc hiển thị theo ADR-0005 phương án (a) khi bật cờ `VITE_SHOW_METAL_PRICES` (bật từ 07/11): chỉ sau đăng nhập, có dòng nguồn "Yahoo Finance, U.S. EIA", không có tính năng tải dữ liệu. Tắt cờ thì vàng, bạc chỉ hiện % thay đổi và xác suất.
- Mọi trang có câu "không phải lời khuyên đầu tư".
- **Chưa có biểu đồ lịch sử giá** (nhóm chốt bỏ ngày 13/11; TKVH §10).

**Cờ build đang dùng** (bản Amplify 13/11 từ `26399d0`): `VITE_AUTH_ENABLED=true`, `VITE_SHOW_METAL_PRICES=true`, `VITE_ACCURACY_API=true`.

**Tự đăng ký cho người chấm (kế hoạch, chưa triển khai).** Web đã có cờ `VITE_ALLOW_SIGNUP` (mặc định tắt; [#132](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/132), merge 16/11) để hiện màn đăng ký và nhập mã xác minh email của Amplify `Authenticator`. Chỉ bật sau khi `CpawsAuth` cho tự đăng ký kèm xác minh email, theo **ADR-0014 (mới) và một dòng bổ sung ở ADR-0005** (Tuấn; ADR-0006 không sửa). Cờ web chỉ ẩn/hiện giao diện, không chặn được ai: client ID là giá trị công khai, nên thứ chặn thật là cấu hình User Pool. Mốc tắt: trong 1 ngày sau khi mentor báo chấm xong, chậm nhất 10/12/2026 — tắt self sign-up trong `CpawsAuth` trước, rồi build web với cờ tắt, rồi disable/xóa các user tự tạo. Nếu không kịp trước 22/11, người chấm dùng một tài khoản riêng do Tuấn tạo. `[CẬP NHẬT sau khi deploy hoặc bỏ]`

## 4.7. Giới hạn và hướng phát triển

Chi tiết ở TKVH §10. Các điểm chính:

- **Một môi trường, deploy tay từ máy một người**; tham số `-c` không được lưu nên dễ quên.
- **Alarm không phát hiện việc lịch không chạy** (thiếu dữ liệu coi là bình thường). Hướng sửa: alarm trên `Invocations` của ingest, chu kỳ 1 ngày, báo khi 3 ngày liên tiếp không có lượt chạy.
- **CORS một origin**; **Amplify upload zip thủ công**, không có lịch sử build gắn commit.
- **ECR giữ 5 image**, image dùng để rollback có thể bị xóa nếu không theo dõi.
- Không có biểu đồ lịch sử giá; chatbot không bật Guardrails.

Hướng phát triển sau dự án: tách môi trường `dev`/`prod` và deploy qua pipeline (CD) với quyền AWS tạm thời (OIDC); alarm "không chạy"; nối Amplify với Git sau khi hết thời gian chấm; endpoint lịch sử giá nếu nguồn dữ liệu cho phép.

---

**Nguồn:** [trien-khai-van-hanh.md](trien-khai-van-hanh.md) §1–§11 và Phụ lục A; sơ đồ hiện trạng ([#125](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/125)) và sơ đồ proposal; `infra/app.py`, `infra/stacks/`; `web/`; `.github/workflows/ci.yml`; ADR-0003, 0005, 0011, 0012, 0013; [khung báo cáo cuối](khung-bao-cao-cuoi.md) mục Chương 4.
