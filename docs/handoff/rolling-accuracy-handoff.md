# Production Rolling Accuracy v4.6 — handoff

Hướng dẫn vận hành và tích hợp cho PR #71. API Contract và Walk-forward Contract §7
là nguồn chuẩn; tài liệu này không thay đổi eligibility, metric, storage hoặc hash rules.
Kiểm thử offline không chứng minh AWS đã deploy hoặc evidence production đã được duyệt.

Gate production yêu cầu release evidence hợp lệ hoặc legacy approval gắn với record thực
đúng asset/model/window/effective date. READY với common mask rỗng vẫn có thể COMPLETED;
thiếu provenance configuration không được publish. Shadow chọn candidate có snapshot khớp
champion và issuance hợp lệ, không chấm trùng base_date/h; shadow thiếu không chặn champion.

## 1. File bàn giao và interface

| File | Trách nhiệm / interface chính |
|---|---|
| `src/eval/rolling_evidence.py` | CLI offline tạo candidate legacy evidence, không tự phê duyệt |
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
| `docs/handoff/rolling-accuracy-handoff.md` | Tài liệu này |

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
production tự động. Không fetch evidence qua CloudWatch/CloudFormation lúc runtime.

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
  Lượt shadow sau `deployed_at` nhưng trước `approved_at` vẫn được tính: `approved_at` là duyệt vận
  hành (cổng `approved_at <= as_of`), không phải mốc dữ liệu. Khải chốt 11/11/2026 (#89).

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
by-h luôn counts_only. Projection `not_ready` khớp chính xác fixture v3.1 trong repository, kể cả disclaimer
hiện hành không có chữ “chỉ”. Nguồn chuẩn: API Contract và Walk-forward Contract §7.5; không định nghĩa schema mới ở đây.

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
Cần owner cấu hình Docker/requirements/CDK và build/import test trên image Linux thật.

Scheduler `cron(45 13 ? * TUE-SAT *)` UTC, retry=0, timeout=300s, không reserved concurrency;
Errors→SNS. Asset lỗi thật được tiếp tục xử lý asset khác rồi raise AccuracyFailed để alarm;
NotReady log/return không promote. Shadow error log riêng không làm champion Lambda failure.

## 6. Tạo candidate legacy evidence offline

`src/eval/rolling_evidence.py` chỉ đọc file cục bộ; không tạo AWS client, không ghi DynamoDB/S3.
Người vận hành được cấp quyền chuẩn bị dữ liệu gốc ở kho riêng, ngoài repository:

1. Export **toàn bộ** DynamoDB item, không ProjectionExpression, không lọc/redact trước hash.
   File `forecasts-full.json` là envelope có `format` (`dynamodb-attribute-values` hoặc
   `resource-json`), `full_items: true`, `projection_used: false`, `Items: [...]`.
   Hai cờ là xác nhận của người export, không phải bằng chứng công cụ có thể tự chứng minh.
   Dữ liệu AttributeValue được deserialize về Decimal; trường bổ sung vẫn tham gia hash.
   Export chỉ có asset/base_date/created_at/model_version/is_sample không đủ để tính digest.
2. Chuẩn bị `issuances.json` với `issuances: [...]`. Mỗi entry phải khớp chính xác
   asset/base_date/model_version/created_at và có input_snapshot_dt lấy từ evidence lượt chạy,
   reference là audit ID không nhạy cảm (chữ/số hoặc `_.:-`, tối đa 120 ký tự).
   `dry_run: false`, `written: true` là xác nhận **riêng record**, không sao chép số tổng
   written của log thành boolean. Các cờ no_overwrite/scheduled_run/input_asof_checked/
   pre_cutover_verified chỉ được đặt true sau khi owner kiểm bằng chứng; không suy từ timestamp.
   Có thể cung cấp snapshot_digest đã lưu độc lập để đối chiếu. Không đưa raw logs vào file này.
3. Chuẩn bị `snapshot-bundle.json`: bucket, prefix (nếu có), objects. Mỗi object có key S3 gốc,
   path tương đối trong thư mục bundle, `etag`, `version_id`, `last_modified` UTC **gốc** và
   SHA-256 của **bytes gốc**. Bundle phải chứa đủ `quality.json`, `prices.parquet` và
   `rejected.parquet` tại các key `clean/prices/dt=...` mà `Sources.snapshot()` đọc.
   Không lấy timestamp file tải xuống thay `LastModified`, không bịa ETag/VersionId hoặc sửa bytes.
   Công cụ kiểm SHA-256 bytes rồi dùng cùng cấu trúc identity của `Sources.snapshot()` để tính digest.

   **Bắt buộc đối với `cpaws-dev-lake` đang bật S3 Versioning:** lấy chính xác `ETag`,
   `VersionId` và `LastModified` của **từng object thực tế** bằng `aws s3api head-object`.
   Không điền `version_id: null` như một giá trị mặc định hoặc chỉ vì chưa tra metadata.
   Giữ `etag` **bao gồm cặp dấu ngoặc kép** trong giá trị S3 trả về; khi viết JSON, escape
   dấu ngoặc kép bên trong chuỗi (ví dụ `"etag": "\"abc123\""`). Bỏ dấu ngoặc kép
   hoặc thay `VersionId` bằng `null` sẽ đổi `snapshot.identity`, làm
   `snapshot_digest` khác digest Lambda tính và loại record bằng
   `legacy_snapshot_binding_mismatch`.

   Lệnh lấy metadata cho từng key (thay `<DT>` và `<object>` bằng giá trị thực):

   ```bash
   aws s3api head-object \
     --bucket cpaws-dev-lake \
     --key 'clean/prices/dt=<DT>/<object>' \
     --query '{ETag:ETag,VersionId:VersionId,LastModified:LastModified}' \
     --output json
   ```

   Lặp lại cho `quality.json`, `prices.parquet`, `rejected.parquet` của **mỗi** snapshot
   được tham chiếu. `head-object` không có `--version-id` chỉ trả bản hiện hành: nếu object
   đã bị ghi đè, phải đối chiếu audit và lịch sử phiên bản để xác định **đúng VersionId**
   của snapshot phát hành, không coi bản hiện tại là bản cũ. Với source runtime hiện hành,
   việc đọc snapshot mặc định không tự chọn một VersionId lịch sử; nếu không đối chiếu được
   identity của bundle với snapshot mà Lambda thật sự đọc thì **fail-closed**, không approve.

   **Retention:** `cpaws-dev-lake` có `noncurrent_version_expiration = 30 ngày`.
   Nếu snapshot gốc của base_date 26–28/10 bị overwrite, bản cũ có thể bị xóa sau khoảng
   30 ngày **kể từ khi trở thành noncurrent**, không phải mặc định 30 ngày từ base_date.
   Xuất bundle, lưu bytes và metadata gốc trong kho riêng có retention phù hợp **sớm**;
   kiểm tra quyền truy xuất bản cũ trước khi hết hạn. Không commit bundle vào repository.

Ví dụ hình dạng manifest (placeholder, không phải evidence đã xác minh; thêm các object còn lại):

```json
{
  "bucket": "cpaws-dev-lake",
  "objects": [
    {
      "key": "clean/prices/dt=<issued-snapshot-date>/quality.json",
      "path": "quality.json",
      "etag": "\"<original-etag-without-surrounding-quotes>\"",
      "version_id": "<actual-VersionId-from-head-object>",
      "last_modified": "<original-UTC-timestamp>",
      "sha256": "<raw-object-sha256>"
    }
  ]
}
```

Chạy trong môi trường Python của repository, sau khi đã được cấp dữ liệu:

```bash
python -m src.eval.rolling_evidence --asset gold --from 2026-10-26 --to 2026-10-28 --forecasts /private/forecasts-full.json --issuance-evidence /private/issuances.json --snapshot-bundle /private/snapshot-bundle.json --output /private/gold-candidates.json
```

Đổi asset/output tương ứng cho silver/brent/wti. Các đường dẫn trên là placeholder;
output phải chưa tồn tại. Phạm vi candidate chỉ 4 asset × base 26–28/10/2026;
16/10 sample, 23/10 và base 29/10 hậu cutover không được tự đưa vào legacy allowlist.
Không suy snapshot_dt từ base_date. Snapshot bị overwrite hoặc có LastModified sau issuance
sẽ bị đánh dấu unverified; cần artifact/version lịch sử đúng, không dùng snapshot hiện tại giả thay.

`record_digest` gọi đúng digest(record) trên item đầy đủ trước mọi lựa chọn trường;
`snapshot_digest` gọi digest(snapshot.identity). SHA-256 bytes trong bundle chỉ kiểm file nguồn,
không thay hai digest production. Output không chứa giá, q, payload gốc hoặc raw logs.

Output có kind=legacy_evidence_candidates, production_ready=false. Mỗi candidate có
status pending_review/unverified/excluded, reasons và evidence với các field mà Evidence.for_record
sử dụng. approved luôn false; approved_by/approved_at luôn null, kể cả input khai đã approved.
Exit 0 chỉ nghĩa đã xuất báo cáo, không nghĩa evidence đủ điều kiện production.
Người có thẩm quyền phải xác minh dữ liệu gốc và phê duyệt riêng trước khi chuyển entry phù hợp
vào legacy[] của release configuration; không nạp nguyên candidate report vào Lambda.
CLI không thể chứng minh một export thiếu unknown attributes hay lời khai vận hành là đúng.

Giữ log Predict gốc, full items và snapshot trong S3 private do owner quản lý, có quyền đọc hạn chế
và retention/version phù hợp. Chỉ chia sẻ audit reference/digest đã kiểm tra. Không commit dữ liệu
giá, q, raw Predict logs, credentials hoặc bundle production trong docs/eval/evidence/ hay nơi khác.
Digest của bản log đã lọc không phải digest của DynamoDB item đầy đủ.

## 7. Dry-run trước deployment

**Thứ tự thực hiện để đo được mismatch** (không yêu cầu legacy approval trước bước đo):

1. **Duyệt `release` trước**, với bằng chứng triển khai/smoke và `cutover_at` thật, đúng
   schema §3 (`approved`, `approved_by`, `approved_at`, `reference`, `conditional_write=true`,
   `input_asof_checked=true`). Release đã duyệt cho phép kiểm provenance các record hậu
   cutover (ví dụ base_date từ 29/10), **không** tự approve record legacy.
2. **Chạy dry-run đủ bốn asset** với release evidence hợp lệ, thu các diagnostics và đo
   `base_price_revision_mismatch` trên các record hậu cutover vượt qua provenance. Với
   evidence `{}`, `records_passing_provenance=0`, mẫu số bằng 0 và `rate=null`:
   kết quả này **không trả lời** câu hỏi về tỷ lệ mismatch. Không được diễn giải `null`
   thành 0% hoặc kết luận không có revision mismatch.
3. **Xử lý legacy evidence sau**: xuất bundle/metadata §6, kiểm toàn bộ item và nguồn gốc
   của những record base_date 26–28/10, duyệt riêng từng entry hợp lệ vào `legacy[]`.
   Khi đủ evidence có thể chạy lại chẩn đoán theo một **run có identity khác**, có kiểm soát
   as-of/revision và audit, không ghi đè kết quả đã công bố.
4. **Trước khi bật Scheduler**, nhóm Khải/Tuấn/Tiến/Long xem số mismatch và quyết định
   xử lý nguồn nếu cần. Scheduler do Tiến tạo ở trạng thái **disabled** và chỉ kích hoạt
   sau dry-run bốn asset, kiểm IAM/image/resources và thống nhất phương án mismatch.

**Điều kiện thời gian:** mỗi approval phải có `approved_at <= cfg.as_of`, với
`cfg.as_of = job_utc_date T13:45:00Z`. Nếu release được duyệt trong ngày D thì
chỉ dùng job_utc_date **không sớm hơn D** và thực thi sau **13:45 UTC**
(20:45 Việt Nam) để tránh `release_provenance_unverified`. Với approval sau
13:45 UTC ngày D, lượt D không đủ điều kiện; chọn ngày đánh giá sau đó. Không
sửa lùi `approved_at` hoặc dùng dữ liệu đến sau `as_of` để ép vượt điều kiện.

Owner chuẩn bị hai champion mappings, release evidence đã duyệt và image/handler theo
§2–3 trước khi chạy. Event cho handler hiện có (chỉ vận hành sau khi được cấp quyền):

```json
{"assets":["gold","silver","brent","wti"],"dry_run":true}
```

`job_utc_date` chỉ dùng chẩn đoán ngày đã qua; snapshot phải tồn tại đúng as-of 13:45 UTC.
Dry-run không publish Accuracy, không promote STATE và không ghi shadow report.
Đọc diagnostics của từng asset trong kết quả/ACCURACY_DONE:

- records_read: records nguồn đọc được; records_passing_provenance: qua xác thực record/evidence.
- records_with_scored_pairs: record có ít nhất một cặp được chấm; n_obs: số cặp coverage.
- reason_counts và record_exclusions/pair_exclusions/warnings/schedule tách cấp đếm.
  Không cộng các loại này để suy số record bị loại; prob_up_mismatch chỉ là cảnh báo.
- base_price_revision_mismatch.count là số cặp bị loại vì lý do đó; denominator là
  **7 × records_passing_provenance**: bao gồm các horizon chưa mature/target pending,
  nhưng **không bao gồm** record bị loại ngay ở bước provenance.
  rate=count/denominator; null khi denominator=0 hoặc chưa đánh giá được nguồn.
  Đây không phải tỷ lệ lỗi trên riêng các target mature.
- source_status/evidence_status cho biết readiness riêng; số chưa thể tính giữ null.
  Exception không thuộc mã audit cố định được gộp other_validation_error, không in payload nhạy cảm.

Checklist cho đủ bốn asset: lưu báo cáo counts/reasons, kiểm READY và mapping/effective/cutover,
kiểm kỳ missing riêng với forecast bị loại, đối chiếu tỷ lệ mismatch và snapshot identity gốc.
Nếu mismatch đáng kể, dừng kết luận sẵn sàng, đưa Khải/Tuấn/Tiến xem provenance và revisions;
nhóm phải quyết định cách xử lý nguồn trước deployment. Không tự đặt tolerance, sửa forecast,
đổi common mask hoặc backfill để tăng n_obs. Không đặt ngưỡng tỷ lệ mới trong handoff.
Diagnostics chỉ nằm ở kết quả dry-run, không thêm field vào META/METRIC/public API.
Trong lần dry-run đầu, ghi thêm **Duration** và **Max Memory Used** từ Lambda/CloudWatch:
`Sources` được dựng riêng theo asset và có thể phải đọc nhiều snapshot đầu vào (ước tính
khoảng 40 snapshot/asset khi window đủ 56 ngày). Cấu hình 1024 MB / 300 giây cần đo
trên dữ liệu thật, không coi việc import image/test offline là xác nhận hiệu năng.

## 8. Kiểm thử và ownership

Dùng Python 3.11 và dependencies của repository. Fixtures đọc trực tiếp từ
`tests/fixtures/accuracy/{not_ready,collecting,ready}.json`, không cần nguồn ngoài.
Test projection đối chiếu toàn bộ response với fixtures; test raw pairs xác minh metric độc lập.

```bash
python -m pytest -q tests/test_rolling_evidence.py tests/test_rolling_accuracy.py tests/test_rolling_sources.py tests/test_rolling_store.py tests/test_rolling_job.py tests/test_rolling_shadow.py tests/test_lambda_accuracy.py
python -m ruff check src/eval/rolling_evidence.py src/eval/rolling_accuracy.py src/eval/rolling_job.py tests/test_rolling_evidence.py tests/test_rolling_accuracy.py tests/test_rolling_job.py
python -m ruff format --check src/eval/rolling_evidence.py src/eval/rolling_accuracy.py src/eval/rolling_job.py tests/test_rolling_evidence.py tests/test_rolling_accuracy.py tests/test_rolling_job.py
```

Synthetic tests/fakes không thay staging integration, IAM deny tests hoặc full repository CI.

| Owner | Việc cần xác minh trước deploy |
|---|---|
| Long | CLI candidate, diagnostics, regression tests; phối hợp đánh giá mismatch, không tự duyệt evidence |
| Khải/Tiến | Full legacy items và audit 12 record; snapshot gốc/binding; approval thực; release cutover/smoke và hai mappings đồng bộ |
| Tuấn | API reader theo hai Contract, META/METRIC hashes/derived và integrity failure; DynamoDB/IAM/concurrency staging |
| Tiến | Image COPY nguyên `src/eval/`, handler riêng; Scheduler để disabled đến sau dry-run và quyết định mismatch; đo Duration/Max Memory thực tế (1024 MB/300 s chưa được xác nhận), timeout/retry/alarm, S3 permissions/403 và snapshot retention |

Release config phải theo evidence deploy/smoke đã được duyệt; mốc trong Contract không tự biến
candidate thành approved. Production dry-run bốn asset, IAM/S3/DynamoDB thật và deployment vẫn
cần owners thực hiện; các lệnh offline trên không thực hiện các bước đó.
