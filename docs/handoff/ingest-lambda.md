# Bàn giao: Lambda `ingest` (giá vàng, bạc, dầu, USD/VND)

- Người viết: Trịnh Tiến Khải, 11/10/2026; cập nhật 15/10/2026 (image container dựng sẵn).
- Người nhận: Châu Trần Mạnh Tiến (CDK, stack `CpawsData`). Người review IAM: Huỳnh Ngọc Tuấn.
- Code đã chạy và có test ở local (moto cho S3). **Image `docker/ingest/Dockerfile` đã build và chạy thử bằng RIE ở local** (mục 2). Chưa đẩy lên ECR, chưa tạo tài nguyên AWS. Image và Dockerfile là bản nháp để Tiến review; hạ tầng chính thức vẫn viết bằng CDK.
- Nguồn và quy tắc dữ liệu: ADR-0005.

## 1. Entrypoint và đóng gói

| Mục | Giá trị |
|---|---|
| Handler | `src.data.lambda_ingest.handler` |
| Runtime | Python 3.12, base image `public.ecr.aws/lambda/python:3.12` (Amazon Linux 2023). Lý do ở mục 2.1 |
| Thư viện | **`requirements-ingest.txt`** (không dùng `requirements.txt`): numpy, pandas, pyarrow, requests, boto3, yfinance, pandas_market_calendars, cố định `==` giống `requirements.txt`. Không có torch, EMD-signal, scikit-learn, statsmodels, python-dotenv. `tests/test_requirements_ingest.py` kiểm tra file này đủ cho mọi import của `src/data/` |
| Đóng gói | **Container image** (ECR), `docker/ingest/Dockerfile`. Gói zip không đủ chỗ: riêng numpy, pandas và pyarrow đã sát giới hạn 250 MB (giải nén) |
| Kiến trúc | Ngoài VPC, không NAT Gateway (gọi Yahoo, EIA, NBP qua Internet công cộng của Lambda) |
| Region | `ap-southeast-1` |

## 2. Image container (dựng sẵn, đã thử ở local)

### 2.1 Vì sao chọn `python:3.12`, không phải 3.11

- **Kỹ thuật:** base `public.ecr.aws/lambda/python:3.11` chạy Amazon Linux 2 (glibc 2.26). `numpy==2.4.6` không có wheel cho glibc ≤ 2.26 (bản cuối có là 2.2.6); pandas 3.0 và pyarrow 25 cũng cần glibc ≥ 2.28. Vì vậy pip không cài được các phiên bản đã cố định. Base 3.12 chạy Amazon Linux 2023 (glibc 2.34), cài đủ trên cả x86_64 lẫn aarch64 (kiểm tra bằng `pip install --dry-run --platform manylinux_2_34_* --python-version 3.12`).
- **Vòng đời:**
  - Amazon Linux 2 hết vòng đời 30/6/2026.
  - Runtime `python3.11` của Lambda bị deprecate 30/6/2027.
  - `python3.12` được hỗ trợ tới 31/10/2028, sau khi nhóm bảo vệ xong.
- Skill `aws-serverless-platform` vốn đã ghi Lambda dùng Python 3.12.
- **Lệch phiên bản Python:** CI và môi trường local đang là 3.11. Đã chạy test trong container 3.12 (mục 2.4), nhưng cần thêm 3.12 vào CI (xem mục 12).

### 2.2 Build

Chạy từ gốc repo. `.dockerignore` chỉ cho vào `requirements-ingest.txt`, `src/__init__.py`, `src/data/`; không có `data/`, `tests/`, `.env`.

```bash
docker buildx build --platform linux/amd64 --provenance=false \
  -f docker/ingest/Dockerfile -t cpaws-ingest:dev .
```

`--provenance=false` là bắt buộc để image dùng được với Lambda (theo tài liệu AWS). Tag `3.12` của base thay đổi khi AWS vá lỗi. Lần build 15/10/2026 dùng index `public.ecr.aws/lambda/python:3.12@sha256:bc8bad2dd10b59ad2032d61f916f81e238ec546128092b65140bdc3a9d77d5f2`. Khi image được duyệt, nên ghim digest này trong `FROM`.

### 2.3 Dung lượng (build 15/10/2026, linux/amd64)

| Đo | Giá trị |
|---|---|
| Docker báo (nén) | khoảng 325 MB |
| Hệ thống file sau giải nén (`du -sx /`) | khoảng 909 MB, dưới xa giới hạn 10 GB của Lambda |
| Thư viện Python (`site-packages`) | 421 MB; lớn nhất: pyarrow 156, pandas 72, numpy 70 (gồm `numpy.libs`), curl_cffi 38, botocore 31 |
| Code (`/var/task`) | khoảng 1 MB |

### 2.4 Chạy thử ở local

**Test trong container 3.12** (repo mount chỉ đọc; pytest và moto chỉ cài vào container tạm, không vào image):

```bash
docker run --rm --platform linux/amd64 -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD":/work:ro -w /work \
  --entrypoint /bin/sh cpaws-ingest:dev -c \
  "pip install -q pytest==9.1.1 'moto[s3]==5.2.3' && python -m pytest -q -p no:cacheprovider \
   tests/test_data_clean_quality.py tests/test_data_ingest.py tests/test_data_sources.py \
   tests/test_lambda_ingest.py tests/test_requirements_ingest.py tests/test_returns.py"
```

Kết quả 15/10/2026 (Python 3.12.15):
- **76 qua, 3 bỏ qua**: 3 test của CLI local cần python-dotenv, mà image không có.
- Thêm python-dotenv vào container thì **79/79 qua**.
- Các test CEEMDAN (`test_no_leakage`, `test_ceemdan_cache`) không chạy trong image này vì image không có PyEMD.

**dry_run qua Runtime Interface Emulator** (RIE có sẵn trong base image):

```bash
docker run --rm -d --platform linux/amd64 -p 9000:8080 --memory 1024m cpaws-ingest:dev
curl -s "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{"dry_run": true}'
```

Trên Windows dùng Git Bash thì thêm `MSYS_NO_PATHCONV=1` trước các lệnh `docker run` có đường dẫn Linux.

Kết quả 15/10/2026 (gọi Yahoo thật từ máy local, không ghi gì): GLD, SLV, CL=F, BZ=F, VND=X đều trả về **10 dòng (01–14/10) và không lỗi**. Init mất 0,62 s, lần gọi mất 2,8 s. Lưu ý:
- dry_run chỉ đếm thanh, không loại thanh của phiên đang chạy, nên dòng 14/10 có thể chưa chốt.
- RIE không đo bộ nhớ: dòng `Max Memory Used` trong log RIE không có ý nghĩa.
- Kết quả này chỉ chứng minh image chạy được. **Yahoo có chặn IP của AWS hay không vẫn phải thử bằng dry_run trên Lambda thật.**

### 2.5 x86_64 hay arm64

- Mặc định **linux/amd64 (x86_64)**: đã build và chạy thử.
- **arm64 (Graviton)** có đơn giá rẻ hơn (xem trang giá Lambda). Với ingest khoảng 3–12 s mỗi ngày, khoản tiết kiệm không đáng kể, nên chỉ chuyển nếu nhóm thống nhất dùng arm64 cho mọi Lambda.
- Điều kiện để chuyển:
  - mọi wheel có bản aarch64 (đã kiểm tra bằng pip cho cp312 manylinux aarch64: có đủ, gồm curl_cffi 0.16.3 và pyarrow 25.0.1);
  - build lại với `--platform linux/arm64` và chạy lại test, dry_run (chưa làm);
  - đặt `Architectures = arm64` khi tạo Lambda.

## 3. Lịch chạy

- `src/data/config.py`: `INGEST_SCHEDULE_EXPRESSION = "cron(15 12 ? * TUE-SAT *)"`, `INGEST_SCHEDULE_TIMEZONE = "UTC"`. Dùng nguyên hai hằng số này khi tạo EventBridge Scheduler.
- Lý do: dữ liệu phiên D chỉ được coi là có sẵn từ 12:00 UTC ngày D+1 (`PUBLISHED_AT_RULES`). Chạy sớm hơn thì production dùng dữ liệu sớm hơn so với backtest giả định. Có test bắt lỗi nếu hai hằng số lệch nhau.
- Lambda `predict` chạy **sau** ingest, nối tiếp trong Step Functions; không đặt một giờ riêng.

## 4. Biến môi trường

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `LAKE_BUCKET` | Có | Ví dụ `cpaws-dev-lake`. Nếu thiếu, code tự suy ra `cpaws-<CPAWS_ENV>-lake` |
| `LAKE_PREFIX` | Không | Tiền tố key trong bucket, mặc định là gốc bucket |
| `CPAWS_ENV` | Không | `dev` hoặc `prod` |
| `EIA_SECRET_ID` | Không | Tên secret chứa EIA key. Thiếu hoặc chưa cài phần đọc secret thì pipeline **bỏ đối chiếu EIA**, log `WARNING INGEST_REFERENCE_FAILED`, vẫn chạy bình thường |
| `YF_CACHE_DIR` | Không | Mặc định `/tmp/yfinance-cache` (Dockerfile đã đặt sẵn). Trong Lambda chỉ `/tmp` ghi được; handler tự chuyển cache của yfinance sang đây |

**EIA key**: chỉ lấy qua `src/data/secret_store.py::get_eia_api_key()`. Hai bạn chọn Secrets Manager hay SSM Parameter Store (SecureString), rồi điền nhánh TODO trong hàm này. Không đặt key thật vào biến môi trường, và code không in key ra log.

## 5. Quyền IAM tối thiểu (Tuấn review)

- `s3:GetObject`, `s3:PutObject` trên `arn:aws:s3:::<LAKE_BUCKET>/<LAKE_PREFIX>raw/*` và `.../<LAKE_PREFIX>clean/*`.
- `s3:ListBucket` trên `arn:aws:s3:::<LAKE_BUCKET>`, có điều kiện `s3:prefix` thuộc `<LAKE_PREFIX>raw/*` hoặc `<LAKE_PREFIX>clean/*`. Code dùng `ListObjectsV2` để tìm `dt=` mới nhất và kiểm tra file có tồn tại không.
- Đọc secret EIA, chỉ trên đúng ARN:
  - Secrets Manager: `secretsmanager:GetSecretValue`;
  - SSM: `ssm:GetParameter`, cộng `kms:Decrypt` nếu dùng CMK.
- Ghi log: managed policy `AWSLambdaBasicExecutionRole`.
- Không cần quyền vào `features/`, DynamoDB hay Bedrock.

## 6. Sự kiện (event) và kết quả

| Event | Hành vi |
|---|---|
| `{}` | Chạy thường lệ: tải lại 5 phiên gần nhất, ghi `raw/` và `clean/` |
| `{"start": "2012-01-01"}` | Nạp lịch sử lần đầu (bucket còn trống) |
| `{"dry_run": true}` | Chỉ tải GLD, SLV, CL=F, BZ=F, VND=X cho 10 phiên gần nhất, **không ghi gì**, trả về số dòng và lỗi của từng mã |

**Chạy `dry_run` ngay sau lần deploy đầu**, để kiểm tra Yahoo có chặn IP của AWS không:

```bash
aws lambda invoke --function-name cpaws-dev-ingest --profile cpaws-dev \
  --cli-binary-format raw-in-base64-out --payload '{"dry_run": true}' out.json && cat out.json
```

Kết quả tốt: cả 5 mã có `rows` = 10 (hoặc gần 10 nếu có ngày nghỉ) và `error` = null. Nếu có mã bị lỗi (HTTP 429/403, rỗng), báo Khải trước khi bật lịch chạy.

Ghi lên S3 (ví dụ chạy ngày D):

```text
raw/yfinance/dt=D/{GLD,SLV,CL_F,BZ_F,VND_X,GC_F,SI_F}.csv.gz
raw/eia/dt=D/..., raw/nbp/dt=D/...
clean/prices/dt=D/{prices.parquet, rejected.parquet, quality.json}
clean/reference_prices/dt=D/reference.parquet
clean/display_factors/dt=D/display_factors.parquet
clean/display_fx/dt=D/display_fx.parquet
```

Chạy lại trong cùng ngày thì ghi đè đúng các file đó (idempotent).

## 7. Lỗi và cảnh báo

- **Nguồn của một tài sản chính lỗi** (vàng, bạc, WTI, Brent, USD/VND):
  - Các tài sản khác vẫn cập nhật và bản clean mới vẫn được ghi; tài sản lỗi giữ dữ liệu cũ với `flag=stale_source`.
  - Handler log dòng `ERROR INGEST_SOURCE_FAILED asset=... symbol=...`, rồi **raise `IngestSourceFailed`**, nên Lambda tính là lỗi (metric `Errors`). Handler không dùng `sys.exit`.
  - Lần chạy thành công sau đó tự tải bù khoảng trống (có test với trường hợp nguồn lỗi 7 phiên liên tiếp).
- **Nguồn tham chiếu lỗi** (EIA, GC=F, SI=F, NBP): chỉ log `WARNING INGEST_REFERENCE_FAILED`, Lambda vẫn trả về thành công. Thiếu EIA thì `quality.json` có `xcheck_skipped` với `reason = source_unavailable`, kèm log `WARNING XCHECK_SKIPPED`. Mục `reference_pending` (EIA trễ date+7) là bình thường, không cần cảnh báo.
- **Alarm đề xuất** (stack `CpawsOps`):
  1. `AWS/Lambda Errors` của hàm ingest ≥ 1 trong 1 ngày.
  2. Metric filter trên log group với mẫu `INGEST_SOURCE_FAILED`, alarm khi ≥ 1. Alarm này cho biết tài sản nào bị lỗi.
  3. (Tùy chọn) Metric filter `INGEST_REFERENCE_FAILED` hoặc `XCHECK_SKIPPED ... source_unavailable`, để biết khi mất đối chiếu EIA (không cần báo động gấp).
- **Retry**: chạy lại trong cùng ngày là an toàn (ghi đè theo khóa). Nên giới hạn retry của lần gọi bất đồng bộ (ví dụ 1 lần) để không tải Yahoo nhiều lần khi nguồn đang lỗi. Cần kiểm tra cả retry policy của Scheduler lẫn cấu hình async invocation của Lambda trong tài liệu AWS khi viết CDK.

## 8. Bộ nhớ và thời gian (đo ở local 11/10/2026)

`scripts/measure_ingest.py`, Windows, Python 3.11, mạng thật, ghi vào thư mục tạm:

| Lần chạy | Thời gian | Bộ nhớ đỉnh (RSS) | Request |
|---|---|---|---|
| Cập nhật hằng ngày (tải lại từ 02/10, có sẵn bản clean cũ) | 11,4 s | 149 MB | 11 |
| Nạp lịch sử từ 2012 (bucket trống) | 41,8 s | 144 MB | 119 |

RSS sau khi import là khoảng 90 MB. **Đề xuất**: memory 1.024 MB (Lambda cấp CPU theo bộ nhớ; bộ nhớ thực cần dưới 200 MB), timeout 300 s (gấp hơn 7 lần lần nạp lịch sử, để chừa chỗ cho mạng chậm và retry của yfinance). Sau lần chạy thật đầu tiên, đọc dòng `REPORT` trong CloudWatch (`Max Memory Used`, `Duration`) rồi chỉnh lại: có thể hạ xuống 512 MB nếu `Duration` vẫn dưới 60 s.

## 9. Ghi chú cho Lambda `predict`

- Đọc `clean/prices/dt=<mới nhất>/quality.json`. Nếu `stale_sources` có tài sản X, thì **ngày gốc dự báo của X là `stale_sources[X].last_date`** (ngày dữ liệu cuối), không phải ngày chạy. Hiển thị kèm ghi chú dữ liệu cũ; không dự báo như thể có dữ liệu mới.
- `published_at` của mỗi dòng giá là 12:00 UTC ngày D+1. Chỉ dùng các dòng có `published_at` ≤ thời điểm dự báo.
- Các cờ `xcheck_*` chỉ để đánh dấu chất lượng: **không dùng làm đặc trưng và không dùng để lọc dòng** (ADR-0005; RWTC có `published_at` = D+7).
- Tỷ giá hiển thị đọc từ `clean/display_fx/dt=<mới nhất>/display_fx.parquet`. Cờ `pending_confirm` hoặc `stale_source` thì hiển thị ghi chú tương ứng.
- Cache IMF CEEMDAN (ADR-0007) nằm ở `features/ceemdan/...`. Việc cập nhật cache hằng ngày (`ceemdan_cache.update_recent`) là của bước predict hoặc một bước riêng sau ingest, không phải của Lambda ingest. Quyền S3 cho prefix `features/` cấp cho hàm đó.

## 10. Chạy thử ở local

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests/test_lambda_ingest.py           # moto, không gọi AWS thật
python -m src.data.ingest_prices --dest local            # ghi data/lake/
LAKE_BUCKET=cpaws-dev-lake python -m src.data.ingest_prices --dest s3   # khi đã có bucket và profile
```

## 11. Việc Tiến làm trên AWS (danh sách, Khải không chạy)

Theo thứ tự; mọi tài nguyên gắn tag `Project=CPAWS`, `Owner=Tien`, `Env=dev`, region `ap-southeast-1`.

1. [ ] Tạo ECR repo `cpaws-dev-ingest` (scan on push), nằm trong stack `CpawsData` hoặc `CpawsInference`. Đặt **lifecycle policy chỉ giữ 3 image gần nhất**: mỗi image khoảng 325 MB (nén) và ECR tính phí lưu trữ cho mọi bản đã đẩy.
2. [ ] Build image theo mục 2.2 (ghim digest base nếu đã duyệt), tag theo commit, đẩy lên ECR.
3. [ ] Tạo execution role theo mục 5 (S3 `raw/`, `clean/`, secret EIA, `AWSLambdaBasicExecutionRole`); Tuấn review.
4. [ ] Tạo Lambda `cpaws-dev-ingest` từ image: package type Image, x86_64, **memory 1.024 MB, timeout 300 s**, ngoài VPC, biến môi trường `LAKE_BUCKET=cpaws-dev-lake`, `LAKE_PREFIX` (để trống), `CPAWS_ENV=dev`, `EIA_SECRET_ID` (khi đã có secret).
5. [ ] Gọi thử `{"dry_run": true}` (mục 6). Nếu có mã lỗi thì báo Khải và dừng ở đây.
6. [ ] Gọi `{"start": "2012-01-01"}` một lần để nạp lịch sử; đọc dòng `REPORT` (`Max Memory Used`, `Duration`) rồi chỉnh memory/timeout nếu cần (mục 8).
7. [ ] Tạo EventBridge Scheduler với `INGEST_SCHEDULE_EXPRESSION = cron(15 12 ? * TUE-SAT *)`, múi giờ `UTC`; giới hạn retry (mục 7).
8. [ ] Tạo alarm theo mục 7 (Errors và metric filter `INGEST_SOURCE_FAILED`).
9. [ ] Khi đổi code: build lại, đẩy image mới, rồi `update-function-code` (Lambda không tự lấy image mới dù cùng tag).

## 12. Việc phát sinh

| Việc | Người | Ghi chú |
|---|---|---|
| Thêm Python 3.12 vào CI (`.github/workflows/ci.yml`, ma trận 3.11 + 3.12 hoặc chuyển hẳn sang 3.12) | Phước (chủ file CI) | Khải không tự sửa `ci.yml`. Lambda chạy 3.12 trong khi CI chỉ test 3.11 |
| Cân nhắc chuyển môi trường local sang Python 3.12 | Cả nhóm | Lưu ý: cache CEEMDAN gắn với phiên bản numpy và EMD-signal (ADR-0007), không gắn với phiên bản Python; vẫn cần thử lại một vài cửa sổ để chắc kết quả giống từng bit |
| Ghim digest base image trong `FROM` khi image được duyệt | Tiến | Mục 2.2 |
| Build và thử arm64 nếu nhóm chọn Graviton | Tiến | Mục 2.5 |
