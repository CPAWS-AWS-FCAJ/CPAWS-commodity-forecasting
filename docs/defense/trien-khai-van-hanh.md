# Triển khai và vận hành CPAWS

> Bản nháp chương Triển khai và vận hành cho báo cáo cuối kỳ (trình bày trước hội đồng thực tập FCAJ-AWS), cập nhật ngày 06/11/2026. Trạng thái triển khai là tại ngày viết; cấu hình lấy từ code trong `infra/`, số đo lấy từ log CloudWatch của các lượt chạy thật. Phần nào là kế hoạch thì ghi rõ.

## 1. Mục tiêu và phạm vi

CPAWS chạy trong **một môi trường `dev`** trên tài khoản AWS của nhóm, region `ap-southeast-1` ([ADR-0004](../adr/0004-region-and-bedrock-access.md), [ADR-0006](../adr/0006-aws-account-and-access.md)). Toàn bộ hạ tầng, trừ web Amplify và một số tài nguyên tạo tay (mục 2.2), được viết bằng **AWS CDK (Python)** trong `infra/`. Có hai mục tiêu vận hành:

1. **Chạy tự động mỗi ngày, không cần người.** Cập nhật dữ liệu và phát hành dự báo theo lịch; lỗi thì gửi email.
2. **Hoàn tác được trong vài phút, không cần build lại image.** Mọi thay đổi có rủi ro (shadow, image, CORS, cờ web) đều có cách quay về bằng một lệnh deploy, hoặc một lần build và upload web.

Phạm vi chương: các stack, luồng chạy hằng ngày, quy trình deploy, rollback, giám sát, web và CORS, CI, giới hạn. Sơ đồ hiện trạng ở PR [#94](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/94). Các lựa chọn kiến trúc ở [tư liệu kiến trúc](lua-chon-kien-truc-va-mo-hinh.md). Chatbot ở [chương chatbot](chatbot.md).

## 2. Hạ tầng

### 2.1. Năm stack CDK

Điểm vào là [`infra/app.py`](../../infra/app.py). Mọi tài nguyên được gắn tag `Project=CPAWS`, `Owner`, `Env` (skill `aws-cost-guard`).

| Stack | Tài nguyên chính | Cấu hình đáng chú ý |
|---|---|---|
| `CpawsData` | S3 `cpaws-dev-lake`; ECR `cpaws-dev-ingest`, `cpaws-dev-predict`; Lambda `cpaws-dev-ingest`, `cpaws-dev-predict`; EventBridge Scheduler; metric filter cho shadow | Bucket bật versioning, phiên bản cũ giữ 30 ngày, `RETAIN`, chặn public, bắt buộc SSL. ECR giữ 5 image mới nhất. Ingest: container, 1.024 MB, 300 giây, retry bất đồng bộ 1 lần. Predict: container x86_64, 1.024 MB, 120 giây, retry 0. Không Lambda nào chạy trong VPC (không cần NAT Gateway) |
| `CpawsServing` | DynamoDB `cpaws-dev-forecasts`, `cpaws-dev-news-labels`, `cpaws-dev-chat-usage` | On-demand. `forecasts` và `news-labels` là `RETAIN`. `chat-usage` chỉ lưu bộ đếm lượt hỏi nên là `DESTROY` |
| `CpawsAuth` | Cognito User Pool `cpaws-dev-users`, app client cho SPA | Không cho tự đăng ký; tài khoản do nhóm tạo. `RETAIN` |
| `CpawsApi` | REST API stage `dev`; Lambda `cpaws-dev-forecasts-api` (256 MB, 10 giây) và `cpaws-dev-chat-api` (512 MB, 28 giây) | Cognito authorizer cho mọi route trừ `/health`. Throttling 10 request/giây, burst 20. CORS chỉ một origin (mục 7). Tin demo đóng gói trong Lambda chat ([ADR-0013](../adr/0013-manual-news-labels-until-defense.md)) |
| `CpawsOps` | SNS `cpaws-dev-alarms`, 5 CloudWatch alarm | Email nhận cảnh báo truyền lúc deploy, không ghi vào repo (mục 6) |

Phụ thuộc giữa các stack: `CpawsApi` dùng bảng của `CpawsServing` và User Pool của `CpawsAuth`, nên **`CpawsServing` phải deploy trước `CpawsApi`**. `CpawsOps` tham chiếu Lambda theo tên chứ không theo output của stack khác, nên deploy được độc lập. Log group của mọi Lambda giữ 1 tháng.

### 2.2. Tài nguyên ngoài CDK

| Tài nguyên | Lý do để ngoài CDK | Người quản lý |
|---|---|---|
| Amplify Hosting app `cpaws-dev-web` (mục 7) | Cần chạy được trước buổi chạy thử 08/11; deploy zip thủ công | Tiến |
| SSM Parameter Store SecureString chứa API key EIA | Giá trị bí mật không được vào repo. CDK chỉ nhận **tên** parameter | Tuấn |
| AWS Budgets (50 USD/tháng theo ADR-0006; trên tài khoản hiện có 2 budget) | Thuộc tài khoản, không thuộc ứng dụng | Tuấn |
| IAM user và group của thành viên | [ADR-0006](../adr/0006-aws-account-and-access.md) | Tuấn |

## 3. Luồng chạy hằng ngày

```
EventBridge Scheduler ── cron(15 12 ? * TUE-SAT *) UTC, retry 0
  └─► Lambda ingest (gọi bất đồng bộ, retry 1) ── ghi raw/, clean/ trên S3
        └─► OnSuccess hoặc OnFailure ─► Lambda predict (retry 0)
              ├─► DynamoDB cpaws-dev-forecasts (champion baseline-q252, ghi có điều kiện)
              └─► S3 eval/shadow/s1a-l094/dt=…/ (shadow S1a, không hiển thị)
```

- **Giờ chạy:** 12:15 UTC, tức **19:15 giờ Việt Nam, thứ Ba đến thứ Bảy**, sau các phiên Mỹ từ thứ Hai đến thứ Sáu. Dữ liệu phiên D chỉ được coi là có từ 12:00 UTC ngày D+1 (`PUBLISHED_AT_RULES`). Chạy theo đúng giờ này thì production dùng cùng mốc thông tin với backtest. Test kiểm hằng số trong `infra/stacks/shared.py` phải khớp `src/data/config.py`.
- **Ingest lỗi vẫn gọi predict:** khi một nguồn lỗi, ingest vẫn ghi snapshot cho các tài sản còn lại. Predict phát hành cho tài sản có đủ phiên mới nhất, tài sản thiếu thì bỏ qua và báo lỗi (`PredictFailed`).
- **Chạy lại không làm hỏng dữ liệu:** predict dùng `PutItem` có điều kiện. Bản đã phát hành cùng tài sản và cùng ngày cơ sở không bị ghi đè (`PREDICT_ALREADY_PUBLISHED`); chỉ bản mẫu (`is_sample = true`) được thay. Vì vậy predict để retry 0, ingest chỉ retry 1 để không gọi nguồn Yahoo nhiều lần khi nguồn đang lỗi.
- **Không dùng Step Functions và SageMaker:** hai Lambda nối nhau bằng destination ([ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md)). Champion `baseline-q252` là mốc thống kê 252 phiên, không cần artifact mô hình ([ADR-0012](../adr/0012-k4-fhs-gjr-result.md)).
- **Shadow cô lập:** shadow S1a lỗi hoặc cấu hình sai thì không làm hỏng lần phát hành champion. Lỗi được ghi log và đếm bằng metric filter ([kế hoạch S1a](../experiments/s1a-shadow-plan.md), mục 5 và 15).

Lượt predict tự động đầu tiên chạy ngày 27/10/2026. Từ 04/11, image `c61abdd` chạy champion kèm shadow S1a. Dưới đây là ba lượt đầu dùng image này, so với tiêu chí ở mục 7 của kế hoạch S1a (`Duration` lớn nhất của ba lượt đầu tăng dưới 2 giây so với mốc 2,9 giây):

| Lượt (19:15) | Duration | Max Memory | Shadow ghi | Alarm |
|---|---:|---:|---:|---|
| 04/11 | 3,29 s | — | 4/4 | OK |
| 05/11 | 3,25 s (Init 1,33 s) | 260 / 1.024 MB | 4/4 | OK |
| 06/11 | 3,27 s (Init 1,34 s) | 258 / 1.024 MB | 4/4 | OK |

`Duration` lớn nhất của ba lượt là 3,29 s, tăng 0,39 s so với mốc 2,9 s, nên **đạt** tiêu chí. Shadow giữ nguyên, không cần rollback.

## 4. Quy trình deploy

### 4.1. Nguyên tắc

- **Chỉ deploy từ `developer` sau khi PR đã merge**, và chạy `cdk diff` trước. Thay đổi về IAM và hạ tầng do Tuấn review ngay trong PR, trước khi merge.
- **Mỗi lệnh deploy một stack.** Mỗi lần chỉ một người deploy, và báo nhóm trước.
- **Không deploy `CpawsData` trong khung 19:05–19:35**, để không chồng lên lượt ingest/predict lúc 19:15.
- **Tham số `-c` không được lưu lại.** Lần deploy sau không truyền thì giá trị quay về mặc định trong `app.py`. Có hai tham số phải truyền ở **mọi** lần deploy:
  - `CpawsOps`: `-c alarm_email=…`. Thiếu tham số này thì subscription email bị gỡ.
  - `CpawsApi`: `-c allowed_origin=…` đang dùng. Thiếu thì CORS quay về `http://localhost:5173`.
- **Image container gắn tag bằng SHA ngắn của commit merge**, không dùng `latest`. Quy trình: build image → push lên ECR → sửa `DEFAULT_*_IMAGE_TAG` trong `app.py` qua PR → deploy `CpawsData`.

### 4.2. Thứ tự khi một thay đổi động tới nhiều stack

`CpawsServing` (bảng) → `CpawsData` (Lambda, Scheduler) → `CpawsOps` (alarm) → `CpawsApi` (route). Có nghĩa là tài nguyên được tạo trước, rồi mới có nơi đọc nó. Lệnh cụ thể ở [Phụ lục A](#phụ-lục-a--lệnh-vận-hành).

## 5. Rollback

| Tình huống | Cách hoàn tác | Cần build lại? |
|---|---|---|
| Shadow S1a lỗi, hoặc làm predict chậm quá ngưỡng | `cdk deploy CpawsData -c shadow_models=off` (đặt `SHADOW_MODELS` rỗng) | Không |
| Image predict mới lỗi | `cdk deploy CpawsData -c predict_image_tag=ce77bcb -c shadow_models=off` | Không (image cũ còn trong ECR) |
| Image ingest mới lỗi | `cdk deploy CpawsData -c ingest_image_tag=TAG_CU` | Không |
| Champion mới có vấn đề | Sửa `CHAMPION_MODEL_VERSIONS` và `DEFAULT_PREDICT_MODEL_VERSION` trong `app.py` qua PR, rồi deploy `CpawsData` | Không |
| Web không gọi được API trên Amplify | Deploy lại `CpawsApi` với origin cũ, khoảng 3 phút (mục 7) | Không |
| Bản web mới lỗi, hoặc phải tắt hiển thị giá vàng/bạc | Upload lại zip của bản trước, hoặc build lại với `VITE_SHOW_METAL_PRICES=false` | Chỉ build web |

Ba điểm làm cho rollback an toàn:

- **`MODEL_VERSION` luôn bằng mọi giá trị của `MODEL_VERSIONS`.** Image `ce77bcb` (bản #48) chỉ đọc `MODEL_VERSION`, còn image hiện tại đọc `MODEL_VERSIONS` theo tài sản. CDK chặn ngay lúc synth nếu hai biến lệch nhau. Nhờ vậy, khi quay về image cũ, Lambda vẫn chạy đúng champion. Cũng vì thế mà **đổi champion phải sửa `app.py` qua PR**: truyền riêng `-c predict_model_version` khác `baseline-q252` thì synth báo lỗi.
- **Dữ liệu không bị xóa:** bucket lake có versioning, giữ phiên bản cũ 30 ngày. Bảng `forecasts` và User Pool là `RETAIN`. Predict không ghi đè bản đã phát hành. Riêng repo ECR ở `dev` là `DESTROY`: xóa stack `CpawsData` thì mất luôn các image dùng để rollback.
- **Image rollback phải còn trong ECR.** ECR chỉ giữ 5 image mới nhất. Repo predict hiện có 4 tag: `ffeee05`, `ce77bcb`, `c61abdd`, `e31c928`. Theo thứ tự push, sau 2 lần push nữa thì `ce77bcb` sẽ bị xóa. Trước khi push image mới, cần chọn lại tag rollback hoặc nâng giới hạn.

## 6. Giám sát và cảnh báo

Năm alarm ở `CpawsOps` cùng một quy tắc: **≥ 1 trong 5 phút**, chu kỳ không có dữ liệu thì coi là bình thường. Khi báo, alarm gửi email qua SNS `cpaws-dev-alarms` (người nhận phải bấm Confirm sau lần deploy đầu).

| Alarm | Metric | Khi nào báo |
|---|---|---|
| `cpaws-dev-ingest-errors` | `AWS/Lambda Errors` của ingest | Một nguồn chính lỗi (`IngestSourceFailed`) hoặc Lambda crash |
| `cpaws-dev-predict-errors` | `AWS/Lambda Errors` của predict | Có tài sản bị bỏ qua (`PredictFailed`) hoặc Lambda crash |
| `cpaws-dev-predict-shadow-errors` | Metric filter trên log predict | `PREDICT_SHADOW_FAILED` hoặc `PREDICT_SHADOW_CONFIG_INVALID`. Champion vẫn phát hành bình thường, nên metric `Errors` không thấy lỗi này |
| `cpaws-dev-chat-api-errors` | `AWS/Lambda Errors` của chat | Timeout hoặc crash |
| `cpaws-dev-chat-api-internal-errors` | Metric filter trên log chat | Handler bắt lỗi không lường trước và trả `500`. Lỗi 4xx, 429 và lỗi Bedrock có mã riêng là hành vi đã thiết kế, nên không báo |

Ngoài alarm, nhóm **kiểm tay sau mỗi lượt 19:15** (lệnh ở Phụ lục A.3): log `PREDICT_DONE` (`written`, `already_published`), `Duration`, số object shadow trên S3, và trạng thái alarm. Về chi phí, nhóm theo dõi bằng AWS Budgets (mục 2.2). Không có tài nguyên nào tính tiền theo giờ: không endpoint, không NAT Gateway, không OpenSearch.

## 7. Web trên Amplify Hosting và CORS

**Web:** app `cpaws-dev-web`, nhánh `dev`, domain mặc định của Amplify. App được tạo tay ngày 04/11. Mỗi lần cập nhật, web được build từ `developer` (`npm run build`), nén `web/dist` thành zip rồi upload ở console. Có rewrite để mọi đường dẫn của SPA trả về `index.html`. Các biến `VITE_*` (region, User Pool ID, client ID, URL API, `VITE_SHOW_METAL_PRICES`, `VITE_ACCURACY_API`) được đọc **lúc build**, nên muốn đổi cờ thì build lại, không cần deploy API. Web không chứa bí mật: ID của User Pool và app client là giá trị công khai của SPA. Việc nối Amplify với GitHub để tự build để sau 08/11, vì nối GitHub sẽ tạo app và domain mới.

Vì zip upload tay không gắn với commit, bản đang chạy được ghi lại ở đây:

| Lần deploy | Commit `developer` | `VITE_SHOW_METAL_PRICES` | `VITE_ACCURACY_API` |
|---|---|---|---|
| 04/11 | `047189f` | `false` | `false` |
| 07/11 | `09dd1d4` | `false` (#91 chưa merge) | `false` |

**CORS:** `CpawsApi` nhận **một** origin qua `-c allowed_origin`, mặc định `http://localhost:5173`. Giá trị này được dùng ở ba chỗ: preflight `OPTIONS` của API Gateway, header của Lambda `forecasts-api` và `chat-api` (biến `ALLOWED_ORIGIN`), và `GatewayResponse` 4xx/5xx (để trình duyệt vẫn đọc được mã lỗi 401, 429, 504).

| Thời điểm | Origin | Ghi chú |
|---|---|---|
| Đến 07/11 | `http://localhost:5173` | Chạy web trên máy |
| Từ 07/11 | Domain Amplify nhánh `dev` | Deploy `CpawsApi` từ `09dd1d4`; lần deploy này cũng đưa bộ tin demo mới (#92) lên Lambda chat. Kiểm tra trên Amplify: preflight trả đúng origin, trang dự báo không lỗi CORS, `POST /chat` trả 200 và `get_news` trả tin |
| Dự phòng | `http://localhost:5173` | Nếu tập dượt trên Amplify còn lỗi lúc 19:00 ngày 07/11, deploy lại origin localhost (khoảng 3 phút) và chạy thử bằng localhost |

Vì chỉ có một origin, tại mỗi thời điểm chỉ Amplify **hoặc** localhost gọi được API. Hỗ trợ nhiều origin để sau 08/11.

## 8. CI và kiểm soát thay đổi

- GitHub Actions chạy ở mọi push và pull request: `ruff check`, `ruff format --check`, `pytest`. Phần web chạy `npm ci`, `typecheck`, `test`, `build`.
- Từ PR [#95](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/95) (merge 06/11), CI cài `aws-cdk-lib` để `tests/test_infra_*.py` chạy thật. Các test này kiểm synth: quyền IAM, biến môi trường, lịch Scheduler, alarm. Trước PR này, các test đó bị bỏ qua.
- **CI không deploy (không có CD).** GitHub không giữ quyền AWS. Repo public nên mọi thay đổi được quét Account ID, email và key (pre-commit: gitleaks, detect-aws-credentials).
- Nhánh `developer` cần ít nhất 1 approve để merge; nhóm dùng merge commit.

## 9. Đang triển khai: Rolling Accuracy

Bảng `cpaws-dev-accuracy` và API `/accuracy/{asset}` (PR [#87](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/87)), cùng job `rolling_8w` (PR [#89](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/89)), **chưa deploy** tại ngày viết. Thứ tự dự kiến:

1. `CpawsServing` (tạo bảng).
2. `CpawsData` và `CpawsOps` (job và alarm của job).
3. Chạy thử dry-run cho 4 tài sản và ghi lại thời gian, bộ nhớ.
4. Nhóm quyết định, rồi mới mở PR bật lịch.

Route `/accuracy` không deploy cùng lần deploy `CpawsApi` ngày 07/11. Phương pháp đánh giá ở [chương phương pháp đánh giá](phuong-phap-danh-gia.md), Phụ lục A.

## 10. Giới hạn

- **Một môi trường, deploy tay.** Không có staging hay prod. Deploy chạy từ máy một người. Tham số `-c` không được lưu, nên dễ lỡ quên `allowed_origin` hoặc `alarm_email`.
- **Alarm không phát hiện việc "không chạy".** Thiếu dữ liệu được coi là bình thường, nên nếu Scheduler không kích hoạt thì không có email báo. Hiện việc này chỉ được bắt bằng bước kiểm tay sau 19:15. Hướng sửa sau 22/11: alarm trên `Invocations` của Lambda ingest, chu kỳ 1 ngày, thiếu dữ liệu coi là vi phạm, và chỉ báo khi **3 ngày liên tiếp** không có lần chạy, vì Chủ nhật và thứ Hai (giờ UTC) vốn không có lịch.
- **CORS một origin**, nên localhost và Amplify không dùng được cùng lúc.
- **Amplify deploy zip thủ công.** Không có lịch sử build gắn với commit, nên commit nào đang chạy phải ghi lại bằng tay.
- **ECR giữ 5 image**, nên image rollback có thể bị xóa nếu không theo dõi (mục 5).
- Guardrails của chatbot chưa gắn vào Lambda, và Haiku gọi qua global inference profile ([chương chatbot](chatbot.md), mục 8).

## 11. Tóm tắt

CPAWS chạy serverless trên 5 stack CDK, không có tài nguyên tính tiền theo giờ. Lượt chạy hằng ngày lúc 19:15 (thứ Ba–thứ Bảy) đi theo chuỗi Scheduler → ingest → predict. Predict ghi có điều kiện nên chạy lại an toàn. Shadow S1a tách khỏi champion và có alarm riêng. Rollback cho shadow, image, CORS và cờ web đều chỉ cần một lệnh deploy hoặc một lần upload, không phải build lại image. Ràng buộc trong CDK (`MODEL_VERSION` khớp `MODEL_VERSIONS`) giữ cho image cũ vẫn chạy đúng champion. Năm alarm gửi email qua SNS. Phần còn yếu là vận hành tay: deploy từ một máy, CORS chỉ một origin, Amplify thủ công, và chưa có cảnh báo khi lượt chạy không diễn ra.

---

# Phụ lục A — Lệnh vận hành

Chạy trong thư mục `infra/`, môi trường ảo có `aws-cdk-lib`, profile AWS của người deploy. `EMAIL_NHAN_CANH_BAO`, `ORIGIN_WEB`, `TAG_CU` là chỗ cần điền.

## A.1. Deploy

| Việc | Lệnh |
|---|---|
| Xem thay đổi | `cdk diff TEN_STACK --profile cpaws-dev` |
| Bảng DynamoDB | `cdk deploy CpawsServing --profile cpaws-dev` |
| Lambda, Scheduler | `cdk deploy CpawsData --profile cpaws-dev` (ngoài 19:05–19:35) |
| Alarm | `cdk deploy CpawsOps -c alarm_email=EMAIL_NHAN_CANH_BAO --profile cpaws-dev` |
| API | `cdk deploy CpawsApi -c allowed_origin=ORIGIN_WEB --profile cpaws-dev` |

## A.2. Rollback

| Việc | Lệnh |
|---|---|
| Tắt shadow | `cdk deploy CpawsData -c shadow_models=off --profile cpaws-dev` |
| Quay về image predict #48 | `cdk deploy CpawsData -c predict_image_tag=ce77bcb -c shadow_models=off --profile cpaws-dev` |
| Quay về image ingest | `cdk deploy CpawsData -c ingest_image_tag=TAG_CU --profile cpaws-dev` |
| CORS về localhost | `cdk deploy CpawsApi -c allowed_origin=http://localhost:5173 --profile cpaws-dev` |

## A.3. Kiểm lượt 19:15

```
aws logs tail /aws/lambda/cpaws-dev-predict --since 90m --format short --profile cpaws-dev \
  --filter-pattern "?INIT_REPORT ?REPORT ?PREDICT_DONE ?PREDICT_SHADOW ?PREDICT_FAILED ?PREDICT_ALREADY_PUBLISHED ?PREDICT_SKIPPED"
aws s3 ls s3://cpaws-dev-lake/eval/shadow/s1a-l094/dt=YYYY-MM-DD/ --profile cpaws-dev
aws cloudwatch describe-alarms --profile cpaws-dev --query "MetricAlarms[].[AlarmName,StateValue]" --output text
```

Log `PREDICT_DONE` có giá phiên gần nhất và xác suất tăng, nên không dán nguyên dòng log vào repo public hay PR.

## A.4. Cập nhật web

`npm run build` trong `web/` (cờ `VITE_*` lấy từ `.env.local` lúc build) → nén `web/dist` thành `web-dist.zip` → console Amplify, app `cpaws-dev-web`, nhánh `dev`, **Deploy updates**, kéo file zip vào → mở domain, đăng nhập, kiểm tra trang dự báo và chatbot.
