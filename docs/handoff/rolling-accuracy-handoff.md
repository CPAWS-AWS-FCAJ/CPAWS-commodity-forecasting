# Production Rolling Accuracy v4.6 revision 3 — handoff offline

## Revision 3: sửa F2/F3 theo review và Contract PR #65 §7.6

Nguồn contract đọc cục bộ: `CPAWS-PR65-contract-files-only.zip`,
`docs/eval/walk-forward-contract.md` §7.6. Không truy cập PR/GitHub.

- F1 giữ nguyên: production không có provenance phù hợp → not_ready, không ghi DynamoDB.
- F2: `Evidence.require_configured(cfg, records)` nhận các record thực từ Query asset/window
  của run. Khi không có release evidence hợp lệ, phải có một record qua `validate_record(cfg)`
  và `for_record()` với policy LEGACY_ACCEPT_WITH_EVIDENCE. Kiểm asset/model/effective/window,
  exact record digest, approval và snapshot binding; approval gold không mở gate WTI,
  record ngoài window hoặc không có trong nguồn không mở gate. Query nguồn xảy ra trước gate;
  gate vẫn trước mọi Accuracy write. Release hợp lệ vẫn cho phép READY + zero eligible COMPLETED.
- F3: probe các ngày chạy TUE–SAT từ issuance đầu tiên của champion eligible đến ngày evaluation
  (kèm ngày issuance thực có), đọc key biết trước, không Scan/List toàn bucket. `dt` là ngày chạy;
  created_at có thể là timestamp champion ở ngày trước nhưng không được sau partition day.
  Gom candidates theo `(asset,base_date,h,target_date,target_series)`, kiểm input_snapshot_dt và
  identity snapshot khớp champion, provenance/LastModified trước nhãn, q50/baseline như cũ.
  Không có candidate hợp lệ → audit `shadow_missing`; không đếm pair hai lần.
  Nếu nhiều candidate đều hợp lệ và cùng snapshot, chọn issuance S3 sớm nhất, tie-break theo key
  để retry deterministic; đây là tie-break triển khai, không tuyên bố contract quy định thứ tự này.
  Provenance từng pair ghi object đã chọn; fingerprint giữ các candidate object đã đọc.
- Thêm test đầy đủ public projection collecting/ready với chính JSON fixtures PR #62 được cung cấp.
  Test này xác minh serialization/display/fields/values từ internal summary tương ứng; không tuyên bố
  tái tạo raw synthetic q/y đã dùng để soạn fixtures. Các test metric từ raw pairs vẫn độc lập.

Diff r2 → r3: chỉ `rolling_sources.py`, `rolling_job.py`, `rolling_shadow.py`,
`test_rolling_sources.py`, `test_rolling_job.py`, `test_rolling_shadow.py`,
`test_rolling_accuracy.py` và handoff này. Predict, Metrics/Walk-forward lịch sử, CDK, infrastructure
và fixtures không sửa. ZIP vẫn 14 file hoàn chỉnh; không ghi đè ZIP r2.

Đây là source để review/tích hợp trên developer (5), không phải bằng chứng đã deploy.
Không truy cập Git/GitHub, AWS hoặc nguồn từ xa trong phiên thực hiện. Dữ liệu test là synthetic;
không sử dụng Validation 2019 như kết quả production. Không thay đổi file có sẵn của developer (5).

## 1. File bàn giao và interface

| File mới | Trách nhiệm / interface chính |
|---|---|
| `src/eval/rolling_accuracy.py` | `Config`, `evaluate(records, actual, cfg, evidence_for)`, `summarize`, `baseline_at`, `response_payload`; calendar, common mask, metrics và identity thuần |
| `src/eval/rolling_sources.py` | `Sources(s3, bucket, forecasts, prefix)`, `Snapshot`, `Evidence`; Query Forecasts, snapshot/quality/rejected, kiểm provenance, immutable shadow output |
| `src/eval/rolling_store.py` | `AccuracyStore(table).publish(result, verify_sources, champion_guard)`; 28 rows, lifecycle, compare/hash, pointer monotonic |
| `src/eval/rolling_job.py` | `run_asset(cfg, sources, store, evidence_config, dry_run=False, champion_guard=..., shadow=True)`; readiness, champion publish rồi shadow độc lập |
| `src/eval/rolling_shadow.py` | `compare`, `parquet_bytes`, `publish_report`; paired mask, 2 model × 3 metrics × (7h + overall), Parquet nội bộ |
| `src/eval/lambda_accuracy.py` | `handler`, `execute`, `parse_config`; cấu hình, isolation theo asset, log lỗi và báo Lambda failure |
| `tests/test_rolling_accuracy.py` | Calendar, identity, metrics, gating, missing endpoints/intermediate và invalid numeric |
| `tests/test_rolling_sources.py` | Evidence, legacy binding, snapshot rewrite, paging, 403 và immutable S3 |
| `tests/test_rolling_store.py` | 28 rows, crashes, concurrent writers, conflicts, hashes, pointer |
| `tests/test_rolling_job.py` | End-to-end bốn asset bằng AWS fakes, dry-run, empty eligible, shadow failure, cửa sổ dài |
| `tests/test_rolling_shadow.py` | Paired subset, late issuance, model change, Parquet round-trip/retry |
| `tests/test_lambda_accuracy.py` | Event/env, handler orchestration, failure signaling, dependency import và evidence artifact |
| `tests/rolling_support.py` | Utility bổ sung cần thiết: dùng chung synthetic prices và behavioral AWS fakes; không credentials/network |
| `handoff/ROLLING_HANDOFF.md` | Tài liệu này |

`Sources` nhận low-level S3 client và boto3 DynamoDB **resource Table** cho Forecasts.
`AccuracyStore` nhận resource Table cho Accuracy. Tests inject fakes, không tạo SDK session thật.
`NotReady` nghĩa snapshot/actual chưa sẵn sàng: không promote. `Conflict` nghĩa payload/order bất nhất.
Core result giữ observations để writer kiểm lại aggregate; không lưu observations vào DynamoDB.
`response_payload` chỉ là helper thuần để phối hợp/kiểm thử, **không phải public API reader**.
Tuấn phải kiểm COMPLETED, model/effective date, manifest 28 hashes và pointer trước khi gọi projection.

## 2. Lambda và cấu hình

Handler: `src.eval.lambda_accuracy.handler`. Scheduler payload `{}`; tùy chọn `assets` là subset
không trùng của gold/silver/brent/wti. `dry_run` phải là bool. `job_utc_date` chỉ cho dry-run
chẩn đoán, không được ghi backfill. Không nhận evidence/model/cutover từ invocation event.

| Environment variable | Quy tắc |
|---|---|
| `MODEL_VERSIONS` | JSON object đúng đủ 4 asset, version là chuỗi không rỗng; bắt buộc |
| `CHAMPION_EFFECTIVE_BASE_DATES` | JSON object đúng đủ 4 asset, ISO date; bắt buộc |
| `LAKE_BUCKET` | Bucket thật do owner cấu hình, bắt buộc |
| `FORECASTS_TABLE` / `ACCURACY_TABLE` | Tên bảng thật, bắt buộc kể cả dry-run; dry-run không ghi |
| `LAKE_PREFIX` | Optional prefix chung, mặc định rỗng; không absolute path hoặc `..` |
| `ROLLING_REVISION` | Số nguyên 0..9999, mặc định 0; correction tăng revision có audit |
| `ROLLING_EVIDENCE_JSON` | JSON evidence do owner phê duyệt; mặc định `{}` fail-closed |
| `ROLLING_EVIDENCE_PATH` | Thay cho JSON env: file UTF-8 JSON được review và đóng trong image/layer; không dùng đồng thời cả hai |

File evidence là lựa chọn khi allowlist vượt tổng giới hạn env Lambda 4 KB. Không tạo file evidence
production trong gói này. Không fetch evidence qua CloudWatch/CloudFormation lúc runtime.

Logical `as_of` cố định **job UTC date T13:45:00Z**, nên retry trong ngày giữ identity nếu input/config
không đổi. Invocation trước mốc bị từ chối. Snapshot/object viết sau mốc không được dùng; correction
cần revision/run mới và nguồn phù hợp, hoặc lượt scheduled kế tiếp. Không dùng `datetime.now()`
trong core. `now` tại handler chỉ xác định job date; tests inject clock.

Run identity bind asset, model/effective date, revision, as-of/config hash, SHA-256 code,
calendar/library/publication rules, actual snapshot, input snapshots, record fingerprints,
audit/count inputs và hash **nội dung** evidence config. Không bịa Git commit.
Input không đổi nhưng revision đổi tạo run mới. Cùng ngày/order mà input thay đổi không được tự
promote: owner phải dùng revision có audit. Library/code đổi cũng đổi identity.

## 3. Evidence schema và trust boundary

Deployment owner cung cấp object với `release`, `legacy` (list), `shadow_release` (optional).
Các approval object cần `approved=true`, `approved_by`, `approved_at` UTC, `reference` có thể audit.
Approval không được sau evaluation. Đây là **trusted deployment configuration**, không phải
cryptographic verifier: không suy approved từ tên PR hoặc timestamp. Bảo vệ bằng release review/IAM.

- `release`: thêm `cutover_at` UTC thực tế, `conditional_write=true`, `input_asof_checked=true`.
  Reference phải trỏ evidence deploy/smoke thật đã được Khải/Tiến xác nhận. Không hardcode 30/31-10.
- Record sau cutover cần `input_snapshot_dt`; đọc snapshot đó, kiểm LastModified trước issuance,
  base hợp lệ, mọi published_at dùng cho input không sau created_at. Baseline cũng dùng snapshot
  issuance đã cắt tới base, không dùng dữ liệu tương lai/revision ở snapshot evaluation.
- `legacy[]`: bind **toàn bộ record** bằng `record_digest=rolling_accuracy.digest(record)`;
  `input_snapshot_dt`, `snapshot_digest=digest(snapshot.identity)`, approval/reference,
  `no_overwrite=true`, `scheduled_run=true`, `input_asof_checked=true`. Khi chưa có release cutover,
  thêm `pre_cutover_verified=true`. Chỉ đúng một entry khớp; khung Tue–Sat 12:15–13:30 UTC.
  Record thiếu/sai approval hoặc snapshot binding bị loại khỏi n_obs. Không tự thêm field vào nguồn.
- `shadow_release`: approval/reference, `deployed_at` UTC, `immutable_write=true`; nguồn S1a vẫn
  cần input provenance, q50 khớp champion ở precision q6, đúng target và S3 LastModified trước nhãn.
  Baseline champion q6 phải khớp baseline tái lập ở q6 trước paired comparison.

**Giới hạn quan trọng:** snapshot daily trong source có thể bị overwrite. Code fail-closed nếu
snapshot issuance hiện có được viết sau forecast, khác legacy binding hoặc đổi giữa read/publish.
Không tự tìm bản S3 version cũ, không khẳng định ETag chứng minh lịch sử chưa overwrite. Khả năng
tái lập lâu dài cần owner bảo toàn versions/artifacts đã fingerprint. HEAD trước publish phát hiện
rewrite trong lượt chạy nhưng không phải transaction khóa S3; invariant nguồn bất biến và quyền ghi
phải được xác minh khi triển khai. Late/missing nguồn không được biến thành verified provenance.

## 4. Evaluation, API và storage

Window `[job_date-55d, job_date]` inclusive theo base_date. Calendar NYSE/CME dùng code repository.
Expected count chỉ thống kê lịch; published_count là expected keys thực có, kể cả record sau đó bị
loại khỏi scoring. Missing không có nguyên nhân dùng `missing_record_unclassified`; không chặn
completion. `schedule_evidence_status=not_audited_mvp`; empty eligible dùng `no_eligible_rows`.

Common mask gồm actual endpoints, forecast hợp lệ và baseline khả dụng theo Accuracy Schema.
Thiếu giữa hai endpoints không tự loại cặp. Sign loại thêm y=0/q50=0. Width percent tính từng cặp
trước pooling, cùng mask/n_obs với width log. Mismatch prob_up chỉ ghi audit. Không DM/retrain/backfill.
Gating chung 20 distinct base dates coverage; mọi overall display field ẩn khi thiếu ngưỡng;
by-h luôn counts_only. Projection `not_ready` khớp chính xác fixture v3.1 được cung cấp, kể cả disclaimer
hiện hành không có chữ “chỉ”. Không sửa fixture/Contract/RFC.

Accuracy một bảng PK/SK, không Scan/GSI/BatchWrite/TTL:

- `ASSET#<asset>` / `STATE`: ngoài keys chỉ `latest_run_pk`, `latest_run_id`, `latest_run_order`.
- `RUN#<asset>#<model>#<run_id>` / `META`: config, full fingerprints, snapshot/evidence, counts,
  overall/by-h, derived width_80_pct và manifest 28 hashes, lifecycle.
- Cùng RUN PK / `METRIC#all#rolling_8w#<start>#<end>#<cutoff>#H<h>#<metric>`: 7h × 4 gốc.
  Dynamic components percent-encoded; không hàng width_pct thứ 29/h=0.

PutItem conditional, collision strong GetItem + canonical Decimal-safe compare. META
RUNNING→VALIDATING→COMPLETED; semantic conflict có thể FAILED terminal, revision mới mới thử lại.
Transport interruption giữ khả năng resume. Query strong phân trang xác nhận đúng META+28 rows;
promote sau complete, monotonic order YYYYMMDD#rrrr. Crash giữa complete/promote retry được;
same-order/different-run conflict. Snapshot/config guards kiểm trước write và trước complete.
Giới hạn META kiểm bảo thủ 350 KB canonical bytes, vượt thì không ghi/truncate. Test cửa sổ dài đạt.

`champion_guard` là hook tích hợp tùy caller; Lambda dùng snapshot env mapping, không gọi AWS để biết
mapping của deployment khác. **Không tuyên bố guard ngăn writer đời cũ bằng chính nó**. Drain writer
cũ, rollout cùng hai mappings Predict/Rolling/API và API fail-closed là phần bắt buộc của owners.

Shadow chạy sau champion publish. Missing/unverified/lỗi shadow không rollback/chặn champion;
K4 theo asset → `shadow_not_applicable_model_change`. Report lưu
`eval/shadow_eval/run_id=<run_id>/asset=<asset>/comparison_id=<hash>.parquet`, conditional S3 put,
retry cùng bytes no-op; khác payload conflict. Có typed rows và schema metadata provenance.
Không API/DynamoDB cho shadow; không auto-promote S1a. Kiểm q50 không thay audit thuật toán scaling
ở Predict: raw quantiles upstream cần Khải xác nhận để chứng minh đầy đủ S1a.

## 5. IAM, S3 và image — việc của Tuấn/Tiến

Rolling role cần:

- Accuracy: GetItem, Query, PutItem, UpdateItem; giới hạn bảng và pointer attributes/keys phù hợp.
- Forecasts: Query (strong, paginated). Adapter hiện không gọi GetItem Forecasts.
- S3 GetObject/HeadObject: `clean/prices/*`, `eval/shadow/s1a-l094/*`, đọc retry `eval/shadow_eval/*`.
  HeadObject dùng quyền IAM s3:GetObject. Write **chỉ** `eval/shadow_eval/*` qua IfNoneMatch.
- s3:ListBucket trên bucket ARN với `s3:prefix` đúng vùng đọc, khi GetObject 403 cần
  ListObjectsV2(Prefix=exact key) để phân biệt missing với permission. Không giả định 403 là missing.
- KMS decrypt chỉ nếu nguồn dùng customer-managed KMS; không yêu cầu CloudWatch Logs read,
  CloudFormation read, Scan/Delete/BatchWrite.

Predict không ghi shadow_eval; API reader chỉ GetItem/Query Accuracy, không S3/Forecasts/write.
IAM allow/deny tests với policy deploy thực vẫn pending.

Tiến cần COPY sáu module mới vào predict image cùng `src/__init__.py`, `src/eval/__init__.py`
và các module data/forecast có sẵn, override CMD handler mới; không đổi CMD Predict đang chạy.
Runtime dùng requirements-predict có sẵn: numpy, pandas, pyarrow, pandas-market-calendars, boto3;
không SciPy/torch/sklearn/statsmodels. Nếu dùng evidence file, COPY reviewed artifact hoặc layer.
Không sửa Docker/requirements/CDK trong gói này. Cần build/import test trên image Linux thật.

Scheduler `cron(45 13 ? * TUE-SAT *)` UTC, retry=0, timeout=300s, không reserved concurrency;
Errors→SNS. Asset lỗi thật được tiếp tục xử lý asset khác rồi raise AccuracyFailed để alarm;
NotReady log/return không promote. Shadow error log riêng không làm champion Lambda failure.

## 6. Kiểm thử và trạng thái

Python 3.11; chỉ local dependency có sẵn. Trước test contract fixture, đặt
`CPAWS_ACCURACY_FIXTURES_ZIP` thành đường dẫn tuyệt đối tới `accuracy-json-fixtures-v3-1-final.zip`.
Nếu fixtures đã được đưa vào `tests/fixtures/accuracy/`, không cần biến này. Thiếu cả hai nguồn thì
hai test fixture sẽ SKIP rõ ràng; ZIP không chứa bản sao fixtures theo giới hạn bàn giao. Lệnh tại root đã overlay các file mới:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=./.test-temp-v46 tests/test_rolling_accuracy.py tests/test_rolling_sources.py tests/test_rolling_store.py tests/test_rolling_job.py tests/test_rolling_shadow.py tests/test_lambda_accuracy.py tests/test_metrics.py tests/test_returns.py tests/test_returns_adr0008.py tests/test_baselines.py tests/test_requirements_predict.py
$files = @('src/eval/rolling_accuracy.py','src/eval/rolling_sources.py','src/eval/rolling_store.py','src/eval/rolling_job.py','src/eval/rolling_shadow.py','src/eval/lambda_accuracy.py','tests/rolling_support.py','tests/test_rolling_accuracy.py','tests/test_rolling_sources.py','tests/test_rolling_store.py','tests/test_rolling_job.py','tests/test_rolling_shadow.py','tests/test_lambda_accuracy.py')
ruff check @files
ruff format --check @files
```

Dùng basetemp mới trong workspace; không dùng cùng directory cho dữ liệu cần giữ (pytest có thể dọn).

| Kiểm tra | Kết quả |
|---|---|
| Core/source/store/job/shadow/Lambda mới, synthetic integration bốn asset | PASS offline |
| Metrics/Returns/Baselines/requirements-predict hồi quy | Đã chạy trong revision trước; không dùng kết quả đó để tuyên bố full CI revision 3 PASS |
| Targeted Rolling revision 3 (6 test modules) | 82 passed, 0 failed, 0 errors |
| Ruff lint toàn repository (`python -m ruff check .`) | PASS, exit 0 |
| Ruff format toàn repository (`python -m ruff format --check .`) | PASS, 177 files already formatted, exit 0 |
| Contract collecting/ready | PASS: full-response equality với hai JSON PR #62 thật, ngoài tests field sets/units/gating |
| Import Lambda khi chặn scipy/torch/sklearn/statsmodels | PASS |
| not_ready projection so với fixture v3.1 thật trong ZIP | PASS exact equality |
| Bảo toàn source developer (5) | PASS: 313 file gốc byte-identical |
| AWS IAM deny tests, concurrent writers DynamoDB thật, S3 condition thật | BLOCKED/pending owners và môi trường deploy; không chạy |
| Image/CDK/Scheduler/alarm/API reader integration | BLOCKED/pending Tuấn/Tiến; không chạy |
| Production legacy approvals, deploy cutover, snapshot retention | BLOCKED/pending evidence thật; không bịa |
| Full repository pytest suite revision 3 | BLOCKED: đã chạy, exit 2; 1 skipped, 2 collection errors vì thiếu `jsonschema` tại test_labeling_benchmark.py và test_labeling_v3.py; 20.33s |
| GitHub Actions / Web CI | Không chạy, không truy cập GitHub; không tuyên bố CI PASS |

Môi trường thực đo revision 3: Windows, Python 3.11.15; NumPy 2.4.6, pandas 3.0.6,
pyarrow 25.0.1, pandas_market_calendars 5.5.0, pytest 9.1.1, Ruff 0.16.10.
Các dependency Rolling khớp pins; môi trường **chưa đủ requirements-dev.txt** do thiếu
jsonschema==4.26.0. Đã thử `uv pip install --offline -r requirements-dev.txt` với cache cục bộ; resolver báo không có jsonschema==4.26.0 trong cache. Không tải dependency từ xa. CI chính thức dùng Ubuntu/Python3.11, nên local
checks không đồng nghĩa GitHub Actions thành công. Cần môi trường đủ requirements-dev để chạy lại full suite.

Lượt targeted revision 3 chỉ dùng sáu test modules Rolling trong lệnh trên,
`--basetemp=./.test-temp-r3-final`. Full suite dùng `pytest.main(['-q', '-p', 'no:cacheprovider',
'--basetemp=./.test-temp-r3-full'])` qua Python launcher, không chọn/bỏ test; socket connect bị chặn
để bảo đảm không gọi hệ thống từ xa. Đây là full-suite attempt offline, không phải lần chạy thành công.

Các lỗi phát hiện trong development đã sửa: đường dẫn code hash, identity phụ thuộc thứ tự source,
tuple quantiles khi tính pinball, invalid numeric fingerprint và thiếu audit mismatch/missing.
Một lượt pytest lỗi fixture tmp_path vì thư mục temp môi trường; lượt cuối dùng basetemp workspace.
Không tái sử dụng kết quả validation cũ. Không có claim T01–T48 đã đạt toàn bộ trên AWS.

## 7. Integration blockers và smoke test

1. Khải/Tiến cung cấp deploy event/smoke reference thật của PR #48, input-as-of assurance và danh sách
   legacy cụ thể đã duyệt. Cấu hình evidence thiếu → production not_ready, không ghi bất kỳ item nào.
   Chỉ evidence hợp lệ + nguồn READY mới có thể complete zero eligible.
2. Khải/Tiến xác nhận PR #53 shadow S3 write-once, thời điểm deploy, raw scaling và snapshots truy vết.
   Code developer (5) có input_snapshot_dt/conditional Predict; không chứng minh AWS đang chạy bản đó.
3. Tuấn thống nhất đọc META/28 hash manifest/derived structure, auth/error envelope, model/effective
   check và recheck pointer; không trả dữ liệu model cũ. Không dùng helper projection thay reader guard.
4. Tiến truyền cùng hai authoritative CDK mappings cho ba components, build CMD, scheduler/alarm,
   drain writer cũ, giới hạn quyền và đo runtime/memory/network trên full 56-day window (timeout300s).
5. Nguồn Predict lịch sử tên có `(1)` trong prompt không có đúng tên trên máy; chỉ bản không suffix
   được dùng làm reference lịch sử. Không overwrite Predict mới từ ZIP cũ.

Smoke sau deploy **do owners thực hiện**, không thực hiện trong phiên này:

- Import image và validate mappings/evidence; chạy dry_run trên forecast production thực đã phát hành,
  không seed synthetic rows/không backfill. Kiểm n_obs/audit/source hashes và eligibility bằng record thật.
- Chờ snapshot/actual READY và chạy scheduled thật với revision được duyệt; kiểm 28 rows, META COMPLETED,
  STATE đúng order/model, derived width, display fields. Retry cùng input không tăng/thay payload.
- Kiểm stale/not-ready không promote; kiểm shadow thiếu không chặn champion. Dùng bảng/bucket test tách
  biệt để inject crash/conflict/IAM denies, tuyệt đối không cố tình làm hỏng source production.
- API fail-closed khi pointer model cũ; thử đổi chỉ một asset ở staging, drain writer cũ và xác minh
  ba asset còn lại. Kiểm CloudWatch Errors→SNS, IAM deny/prefix và S3 403 ambiguity với policy thật.

ZIP này có đúng 14 file mới, không có toàn repository, contracts/fixtures, .git, cache, evidence thật,
credentials, dữ liệu production hoặc binaries. Chưa deploy hoặc thực hiện bất kỳ thao tác từ xa nào.
