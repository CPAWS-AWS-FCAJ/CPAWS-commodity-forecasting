# Bàn giao: Lambda `ingest` (giá vàng, bạc, dầu, USD/VND)

- Người viết: Trịnh Tiến Khải (bản nháp do Claude Code soạn), 11/10/2026.
- Người nhận: Châu Trần Mạnh Tiến (CDK, stack `CpawsData`). Người review IAM: Huỳnh Ngọc Tuấn.
- Code đã chạy và có test ở local (moto cho S3). Chưa deploy, chưa tạo tài nguyên AWS: nhóm chưa có tài khoản (chờ ADR-0006).
- Nguồn và quy tắc dữ liệu: ADR-0005.

## 1. Entrypoint và đóng gói

| Mục | Giá trị |
|---|---|
| Handler | `src.data.lambda_ingest.handler` |
| Runtime | Python 3.12 (quy ước dự án). Code mới chạy thử trên 3.11, nên lần deploy đầu cần chạy `dry_run` |
| Thư viện | `requirements.txt`, nhưng **ingest không cần `torch`, `EMD-signal`, `scikit-learn`, `statsmodels`**. Cần: numpy, pandas, pyarrow, requests, python-dotenv, yfinance, pandas_market_calendars (boto3 có sẵn trong runtime) |
| Đóng gói | Đề xuất **container image** (ECR). Trên máy local, riêng numpy, pandas và pyarrow đã khoảng 215 MB, sát giới hạn 250 MB (giải nén) của gói zip |
| Kiến trúc | Ngoài VPC, không NAT Gateway (gọi Yahoo, EIA, NBP qua Internet công cộng của Lambda) |
| Region | `ap-southeast-1` |

## 2. Lịch chạy

- `src/data/config.py`: `INGEST_SCHEDULE_EXPRESSION = "cron(15 12 ? * TUE-SAT *)"`, `INGEST_SCHEDULE_TIMEZONE = "UTC"`. Dùng nguyên hai hằng số này khi tạo EventBridge Scheduler.
- Lý do: dữ liệu phiên D chỉ được coi là có sẵn từ 12:00 UTC ngày D+1 (`PUBLISHED_AT_RULES`). Chạy sớm hơn thì production dùng dữ liệu sớm hơn so với backtest giả định. Có test bắt lỗi nếu hai hằng số lệch nhau.
- Lambda `predict` chạy **sau** ingest, nối tiếp trong Step Functions; không đặt một giờ riêng.

## 3. Biến môi trường

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `LAKE_BUCKET` | Có | Ví dụ `cpaws-dev-lake`. Nếu thiếu, code tự suy ra `cpaws-<CPAWS_ENV>-lake` |
| `LAKE_PREFIX` | Không | Tiền tố key trong bucket, mặc định là gốc bucket |
| `CPAWS_ENV` | Không | `dev` hoặc `prod` |
| `EIA_SECRET_ID` | Không | Tên secret chứa EIA key. Thiếu hoặc chưa cài phần đọc secret thì pipeline **bỏ đối chiếu EIA**, log `WARNING INGEST_REFERENCE_FAILED`, vẫn chạy bình thường |
| `YF_CACHE_DIR` | Không | Mặc định `/tmp/yfinance-cache`. Trong Lambda chỉ `/tmp` ghi được; handler tự chuyển cache của yfinance sang đây |

**EIA key**: chỉ lấy qua `src/data/secret_store.py::get_eia_api_key()`. Hai bạn chọn Secrets Manager hay SSM Parameter Store (SecureString), rồi điền nhánh TODO trong hàm này. Không đặt key thật vào biến môi trường, và code không in key ra log.

## 4. Quyền IAM tối thiểu (Tuấn review)

- `s3:GetObject`, `s3:PutObject` trên `arn:aws:s3:::<LAKE_BUCKET>/<LAKE_PREFIX>raw/*` và `.../<LAKE_PREFIX>clean/*`.
- `s3:ListBucket` trên `arn:aws:s3:::<LAKE_BUCKET>`, có điều kiện `s3:prefix` thuộc `<LAKE_PREFIX>raw/*` hoặc `<LAKE_PREFIX>clean/*`. Code dùng `ListObjectsV2` để tìm `dt=` mới nhất và kiểm tra file có tồn tại không.
- Đọc secret EIA, chỉ trên đúng ARN:
  - Secrets Manager: `secretsmanager:GetSecretValue`;
  - SSM: `ssm:GetParameter`, cộng `kms:Decrypt` nếu dùng CMK.
- Ghi log: managed policy `AWSLambdaBasicExecutionRole`.
- Không cần quyền vào `features/`, DynamoDB hay Bedrock.

## 5. Sự kiện (event) và kết quả

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

## 6. Lỗi và cảnh báo

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

## 7. Bộ nhớ và thời gian (đo ở local 11/10/2026)

`scripts/measure_ingest.py`, Windows, Python 3.11, mạng thật, ghi vào thư mục tạm:

| Lần chạy | Thời gian | Bộ nhớ đỉnh (RSS) | Request |
|---|---|---|---|
| Cập nhật hằng ngày (tải lại từ 02/10, có sẵn bản clean cũ) | 11,4 s | 149 MB | 11 |
| Nạp lịch sử từ 2012 (bucket trống) | 41,8 s | 144 MB | 119 |

RSS sau khi import là khoảng 90 MB. **Đề xuất**: memory 1.024 MB (Lambda cấp CPU theo bộ nhớ; bộ nhớ thực cần dưới 200 MB), timeout 300 s (gấp hơn 7 lần lần nạp lịch sử, để chừa chỗ cho mạng chậm và retry của yfinance). Sau lần chạy thật đầu tiên, đọc dòng `REPORT` trong CloudWatch (`Max Memory Used`, `Duration`) rồi chỉnh lại: có thể hạ xuống 512 MB nếu `Duration` vẫn dưới 60 s.

## 8. Ghi chú cho Lambda `predict`

- Đọc `clean/prices/dt=<mới nhất>/quality.json`. Nếu `stale_sources` có tài sản X, thì **ngày gốc dự báo của X là `stale_sources[X].last_date`** (ngày dữ liệu cuối), không phải ngày chạy. Hiển thị kèm ghi chú dữ liệu cũ; không dự báo như thể có dữ liệu mới.
- `published_at` của mỗi dòng giá là 12:00 UTC ngày D+1. Chỉ dùng các dòng có `published_at` ≤ thời điểm dự báo.
- Các cờ `xcheck_*` chỉ để đánh dấu chất lượng: **không dùng làm đặc trưng và không dùng để lọc dòng** (ADR-0005; RWTC có `published_at` = D+7).
- Tỷ giá hiển thị đọc từ `clean/display_fx/dt=<mới nhất>/display_fx.parquet`. Cờ `pending_confirm` hoặc `stale_source` thì hiển thị ghi chú tương ứng.
- Cache IMF CEEMDAN (ADR-0007) nằm ở `features/ceemdan/...`. Việc cập nhật cache hằng ngày (`ceemdan_cache.update_recent`) là của bước predict hoặc một bước riêng sau ingest, không phải của Lambda ingest. Quyền S3 cho prefix `features/` cấp cho hàm đó.

## 9. Chạy thử ở local

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests/test_lambda_ingest.py           # moto, không gọi AWS thật
python -m src.data.ingest_prices --dest local            # ghi data/lake/
LAKE_BUCKET=cpaws-dev-lake python -m src.data.ingest_prices --dest s3   # khi đã có bucket và profile
```
