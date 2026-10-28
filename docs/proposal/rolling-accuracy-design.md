# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** RFC v4.3 — **ĐỀ XUẤT ĐỒNG BỘ REVIEW KHẢI/TUẤN VÀ ADR-0011** (chưa được cả nhóm approve, chưa phải API contract chính thức)  
> **Ngày cập nhật:** 2026-10-28 (v4.3: cập nhật 3 điểm Khải và 2 điểm Tuấn tại PR #45; Shadow report S3 Parquet, champion theo `MODEL_VERSION`/CDK, Forecasts-issuance evidence không phụ thuộc CloudWatch, thống nhất `LATEST_COMPLETED`, phân quyền writer/API; chờ chốt 30/10/2026)  
> **Người đề xuất:** Long — nhóm CPAWS  
> **Người review:** Khải (đánh giá/hiển thị), Tuấn (API, DynamoDB, IAM), Tiến (Predict, Web)  
> **Mục tiêu:** Chốt thiết kế MVP trước khi cập nhật `docs/api/contract.md` bằng PR riêng; nếu thay đổi quy tắc Walk-forward/Accuracy Schema thì cập nhật tài liệu tương ứng theo review.  
> **Tham chiếu:** `docs/api/contract.md`, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`, ADR-0008, ADR-0009, ADR-0010, **ADR-0011 (PR #46)**; kế hoạch S1a Shadow (PR #49); source tại commit `a5f770c` theo review của Khải; *Spec dashboard dự báo và độ tin cậy* (27/10/2026); [Issue #23](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).

> **Quy trình PR #45:** PR tài liệu này chỉ dùng để review và approve, **KHÔNG MERGE vào `developer`**. Sau khi chốt, chuyển các quyết định được duyệt sang `docs/api/contract.md` và các contract liên quan bằng PR riêng, rồi đóng PR RFC với trạng thái *Closed — Not Merged*.

## Tóm tắt quyết định và phạm vi

RFC đề xuất hai chức năng phục vụ Dashboard CPAWS:

1. Job `rolling_8w` chấm forecast **champion production** đã phát hành thật, có nhãn hợp lệ; lưu Accuracy chính thức trong DynamoDB cho Dashboard.
2. **Theo ADR-0011**, cùng job hằng tuần có nhánh **so sánh champion với challenger S1a (`s1a-l094`)** trên các cặp forecast–actual giao nhau; chỉ lưu báo cáo **shadow nội bộ**, không thay đổi champion và không công khai S1a qua Accuracy API.
3. `GET /accuracy/{asset}` trả chỉ số champion tổng hợp và theo 7 horizons; `GET /forecast-history/{asset}` là endpoint riêng cho biểu đồ “dự báo cũ so với thực tế” giai đoạn sau.

**Các quy tắc giữ nguyên:** bốn asset `gold/silver/brent/wti`; horizons `h=1..7` theo **phiên giao dịch của tài sản**; nhãn và các phân vị dự báo là **log return**; không tạo ngược forecast cho dữ liệu test 2020–2026; `validation/test` lưu S3 Parquet `eval/`, `rolling_8w` lưu DynamoDB; `overall.coverage_80` gộp theo số cặp hợp lệ, không lấy trung bình ngang các tỷ lệ của 7 horizons; `sign_accuracy` luôn hiển thị cùng `up_rate`.

**Chính sách MVP cập nhật theo review Khải/Tuấn (chờ chốt toàn RFC):** cửa sổ 56 ngày UTC theo `base_date`; `created_at >= 2026-10-27T12:00:00Z`; conditional write tại `Forecasts` để không ghi đè forecast thật; **chỉ chấm forecast có record production đủ điều kiện và cơ chế bất biến đã có hiệu lực**, không backfill. Calendar + lịch TUE–SAT chỉ dùng **đếm expected/missing**, không cần CloudWatch để xác minh ngày không có record và **không** chặn `COMPLETED` vì thiếu logs. `MODEL_VERSION` trong CDK là nguồn champion; `STATE` chỉ là con trỏ `LATEST_COMPLETED`. `prob_up` lệch >`1e-6` chỉ ghi nhận, không loại. Dashboard có 4 metrics, `n_obs` và `n_base_dates`; ngưỡng 20 `base_date` chỉ dành cho hiển thị. Forecasts production mới có `input_snapshot_dt` theo PR predict. Shadow input là JSON; **paired shadow output là Parquet tại S3 `eval/shadow_eval/`**, không nằm trong Accuracy API.

**Kiến trúc đề xuất v4.3:** một bảng `cpaws-<env>-accuracy`, item `STATE` theo asset **chỉ giữ** `latest_run_pk`/`latest_run_id`/`latest_run_order` (gọi chung là **`LATEST_COMPLETED`**); partition `RUN#asset#model#run_id` chứa `META` và 28 item `METRIC`; **không GSI, không Scan**. Champion lấy từ **`MODEL_VERSION` do CDK triển khai**, thay đổi bằng ADR/deploy, **không lưu champion hoặc generation trong `STATE`**. Writer ghi `METRIC` bất biến bằng conditional `PutItem`, chỉ promote pointer sau khi run đủ 28 metrics, snapshot/forecast eligibility hợp lệ; **không** phụ thuộc đầy đủ nhật ký lịch phát hành. IAM chỉ tách Rolling writer và API reader cho bảng Accuracy; Predict không đọc Accuracy; không có champion release operator MVP. Shadow đọc JSON tại `eval/shadow/s1a-l094/`, tính paired mask và lưu **Parquet nội bộ `eval/shadow_eval/run_id=<run_id>/`**. Các quyết định mới chỉ thành contract sau PR contract riêng được merge.

---

## 1. Mục tiêu và tiêu chí thành công

### 1.1. Bài toán

`baseline-q252` tạo phân phối dự báo bằng 7 phân vị cho từng `h=1..7`. Dashboard đã có thể hiển thị q10–q90 và `prob_up`, nhưng cần dữ liệu thực tế để người dùng xem: (a) nhãn có nằm trong khoảng dự báo không, (b) khoảng rộng bao nhiêu, (c) dự báo hướng có giá trị tham khảo thế nào so với tỷ lệ tăng thực tế.

### 1.2. Mục tiêu MVP

- Chấm forecast production đủ điều kiện **trước khi nhãn tương lai được biết**, dựa trên bản ghi `Forecasts` và cơ chế conditional immutability đã triển khai; truy vết model, target series và snapshot input nếu có, không coi `created_at` một mình chứng minh không leakage.
- Tính `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`, `n_obs` theo mỗi h và tổng hợp hợp lệ cho Dashboard.
- Phân biệt `status` tính toán trong Accuracy với `display_status` tại API; khi chưa đủ dữ liệu thì hiển thị số lần đo và trạng thái thay vì suy diễn tỷ lệ.
- Phân biệt lịch phát hành **dự kiến** (đếm theo calendar/schedule), bản ghi `Forecasts` **thực có** và các cặp có nhãn đủ điều kiện; ngày không có row chỉ đếm missing, không yêu cầu xác minh skip reason/log trong MVP.
- API chỉ sử dụng run **`COMPLETED` của `MODEL_VERSION` hiện đang deploy**, không trả kết quả của đời model cũ khi đổi champion; `LATEST_COMPLETED` chỉ là con trỏ run. Shadow evaluation không tác động pointer/API và không tự động đổi champion.

### 1.3. Ngoài phạm vi

- Không đánh giá lợi nhuận, không đưa MAPE/RMSE trên mức giá vào Accuracy Schema.
- **Không xây Step Functions/SageMaker AI Training Job/Model Registry trước bảo vệ** theo ADR-0011; không retrain hoặc thay K3/K3b/K4, không thay logic DM-HAC. S1a là nhánh shadow với tham số đã chốt, không huấn luyện hoặc tinh chỉnh mới.
- Không backfill forecast lịch sử từ test 2020–2026, không sửa Validation 2019 hay ghi đè Parquet cũ.
- RFC này không triển khai Lambda, IAM, CDK, DynamoDB hoặc deploy AWS.

---

## 2. Nguồn dữ liệu, khóa ghép và tính toàn vẹn

### 2.1. Nguồn hiện có trong code

| Nguồn | Cấu trúc / vai trò |
|---|---|
| DynamoDB `Forecasts` | PK=`asset`, SK=`base_date`; `created_at`, `model_version`, `target_series`, `horizons[].{h,target_date,q,prob_up}`, `is_sample`; **bổ sung** `input_snapshot_dt` trong PR predict |
| S3 clean snapshot | `clean/prices/dt=YYYY-MM-DD/prices.parquet`, `rejected.parquet`, `quality.json` |
| **S3 S1a shadow (ADR-0011/PR #49)** | `eval/shadow/s1a-l094/dt=<ngày chạy UTC>/<asset>.json`, cấu trúc như Forecasts + `shadow` metadata; **không** ghi vào bảng `Forecasts` |
| `src/data/calendars.py`, `src/forecast/returns.py` | Lịch NYSE/CME và log return theo h phiên |
| `src/forecast/predict.py`, Lambda predict | Sinh Forecasts với `MODEL_VERSION` (CDK), ghi bằng conditional PutItem (PR #48), kèm `created_at` và `input_snapshot_dt` theo contract; log chỉ để chẩn đoán, không là nguồn chặn `COMPLETED` MVP |
| `src/eval/metrics.py` | Các hàm đánh giá theo Accuracy Schema |

**Target:** `gold → GLD`, `silver → SLV`, `brent → BZ=F`, `wti → CL=F`. `horizons[].q` là **log return**, không phải giá. `last_price` quy đổi để hiển thị vàng/bạc **không** được dùng thay close GLD/SLV để tính nhãn.

### 2.2. Ghép forecast–nhãn

Mỗi cặp đánh giá dựa trên `(asset, base_date, h, model_version)` và `target_date` lưu trong forecast, được xác nhận theo calendar riêng tài sản:

`y(t,h) = ln(P_target(target_date) / P_target(base_date))`

- Hai endpoint phải hợp lệ theo ADR-0008; giá không dương (bao gồm trường hợp WTI bất thường) không được dùng trong log return không xác định.
- Thiếu phiên **ở giữa hai endpoint** không tự làm target vô hiệu nếu hai endpoint hợp lệ; ghi số phiên thiếu.
- `target_date` phải là phiên thứ `h` sau `base_date`, đã có giá hợp lệ tại lúc job chạy và `target_date <= target_cutoff_date` riêng từng asset.
- Metric cần baseline tuân theo common mask và điều kiện mẫu của Accuracy Schema; không tự thay đổi mask.

### 2.3. Forecast đủ điều kiện đánh giá [ĐỀ XUẤT MVP]

1. `is_sample=false`, asset/target/horizon hợp lệ; mỗi horizon có 7 phân vị hữu hạn, đúng thứ tự và `prob_up` trong miền cho phép.
2. `created_at` UTC **`>= 2026-10-27T12:00:00Z`**. Loại các bản ghi trước mốc này, kể cả `is_sample=false` của test deploy. Không lọc bằng `base_date >= 27/10`: forecast đầu tiên có thể phát hành 27/10 cho `base_date=26/10`.
3. Đề xuất điều kiện thời gian: **`created_at < 13:30:00 UTC` trong `target_date`** (so timestamp, không so ngày). Với `h=1`, phát hành lúc 12:15 UTC cùng ngày đích vẫn có thể hợp lệ.
4. Dự báo chỉ dùng thông tin đến `base_date`/input-as-of. Forecast production mới theo PR predict phải có `input_snapshot_dt=YYYY-MM-DD` (ngày `dt=` của clean snapshot đã dùng); kiểm tra hình thức trường này, tính nhất quán với `base_date` và quy tắc `publication_as_of` khi có metadata tương ứng. **Không yêu cầu CloudWatch logs** để chấm/hoàn thành MVP. Thiếu hoặc sai snapshot metadata có thể làm **record đó** không đủ điều kiện theo contract phát hành, nhưng không cản completion của các cặp hợp lệ khác. `created_at < 13:30 UTC` là cutoff bảo thủ, **không tự chứng minh no-leakage** hay settlement dầu; chỉ thu nhận các record đúng thời điểm và có cơ chế phát hành bất biến được xác minh.
5. **Nhánh Accuracy production** chỉ chấm forecast champion trong giai đoạn hiệu lực; không trộn model khi champion thay đổi. **Nhánh shadow nội bộ** là phép so sánh cặp champion–S1a riêng theo mục 3.5, không làm S1a thành production forecast.
6. Giá target phải thực sự được công bố và hợp lệ tại thời điểm evaluation; sample, backfill/test và forecast không thể xác minh điều kiện phát hành được loại hoặc ghi trạng thái theo policy được duyệt.

**Ranh giới evidence phát hành MVP:** `created_at` là timestamp ghi trong record, được dùng cùng **đảm bảo conditional write đang có hiệu lực** tại bảng `Forecasts` (PR #48), khóa `(asset,base_date)`, và các kiểm tra `is_sample=false`, model, cutoff. Bản ghi có `created_at` trước khi cơ chế ghi bất biến được triển khai/kiểm chứng **không tự động thành verified** chỉ nhờ timestamp; nếu không thể xác nhận nguồn phát hành hợp lệ thì loại khỏi `n_obs`, ghi `issuance_unverified`. Không phát minh provenance hồi tố hoặc đòi truy vấn CloudWatch để hợp thức hóa record. Trường `input_snapshot_dt` vẫn phải được triển khai ở Forecasts theo PR predict; kiểm tra input-as-of dựa trên metadata trong record và chính sách snapshot ở tầng predict, không dựa vào log như điều kiện chặn run.

### 2.4. Bảo vệ bản forecast đã phát hành [ĐỀ XUẤT MVP — D04]

Bảng `Forecasts` hiện có thể bị thay bản ghi cùng PK/SK khi `PutItem` không có điều kiện; **S1a không ghi vào bảng này**, dùng immutable S3 object theo mục 2.8. Đề xuất **phương án B — conditional write**, không tạo bảng issuance archive cho MVP:

```python
ConditionExpression = "attribute_not_exists(asset) OR is_sample = :true"
# ExpressionAttributeValues={":true": True}
```

- Điều kiện trên được DynamoDB đánh giá **tại đúng item khóa ghép `(PK=asset, SK=base_date)`** của bảng `Forecasts`: chưa có item thì ghi mới; item hiện có là sample thì bản production hợp lệ có thể thay thế; **item production (`is_sample=false`) đã tồn tại không thể bị ghi đè bởi sample mới, production mới hoặc bất kỳ retry nào**. Không dựa vào việc payload mới tự khai `is_sample` để cho phép ghi đè production.
- Khi `ConditionalCheckFailedException`, phải `GetItem` lại đúng `(asset,base_date)` (consistent read) và kiểm item hiện hữu là production hợp lệ, đồng thời đối chiếu danh tính dự báo/issuance (`model_version`, `created_at`, nội dung horizons hoặc fingerprint tương đương). **Chỉ retry cùng bản phát hành** mới được log `PREDICT_ALREADY_PUBLISHED` như kết quả idempotent; payload khác → báo conflict, không sửa bản cũ hoặc coi như publish thành công. Những lỗi ghi thật vẫn phải báo lỗi.
- Logic `run_predict()`/kết quả Lambda cần thống nhất trạng thái retry để không phát sinh alarm giả.
- Đổi champion chỉ áp dụng từ `base_date` kế tiếp; giữ forecast đã phát hành của model trước.
- Cần kiểm tra dữ liệu/log production từ 27/10 vì điều kiện ghi mới không khôi phục được bản đã bị ghi đè trước khi áp dụng.

Khải phụ trách PR predict riêng sau khi Tuấn/Tiến đồng ý; phần này chưa được coi là đã triển khai.

### 2.5. Issue #23.2 — Lịch kỳ vọng và bằng chứng phát hành tối thiểu [MVP theo review Khải — D14/D15]

**Quyết định MVP thay thế đề xuất v4.2:** **không tạo bảng manifest**, **không đọc CloudWatch ingest/predict logs** trong Rolling job, và **không yêu cầu log retention 90 ngày**. Mục tiêu 05/11 là chấm chính xác những forecast **thực có** và hợp lệ, không điều tra nguyên nhân của mọi kỳ thiếu.

1. **Expected count (thống kê vận hành):** suy từ trading calendar riêng từng asset, lịch chạy TUE–SAT và các ngoại lệ đã biết, từ kỳ 26/10/2026. Đây là mẫu đếm `expected_count`/`missing_count`, **không** là bằng chứng rằng Lambda thật sự chạy hoặc đã phát hành.
2. **Published/eligible count:** query bản ghi `Forecasts` theo `(asset,base_date)`; chỉ chấm record `is_sample=false`, model trùng `MODEL_VERSION` deploy, `created_at` hợp lệ và nằm trong giai đoạn conditional write bảo vệ production đã được áp dụng. Mốc `created_at` và tính bất biến record là **bằng chứng phát hành tối thiểu cho từng cặp** theo quyết định MVP, không cần kèm log `PREDICT_DONE`/ingest.
3. **Missing:** kỳ expected không có row → tăng `missing_count`, **không chấm**, không giả tạo dự báo, **không** gọi chắc chắn `upstream_failure`, `invalid_input_window` hay `no_forecast_row` có nguyên nhân đã xác minh. Nếu có log có thể kiểm toán riêng sau MVP nhưng không dùng làm điều kiện `COMPLETED`.
4. **Quality/causality:** vẫn kiểm `target_date` đúng h phiên, actual endpoint hợp lệ, `target_cutoff_date`, input-as-of/`input_snapshot_dt` theo mức record có thể xác minh. `created_at` **không tự chứng minh** mô hình không nhìn trước; phải giữ safeguard ở Predict và không dùng record phát hành trước khi fix bất biến có hiệu lực mà không có evidence tương đương.

**Tách hai loại evidence:** `issuance_evidence_status` của các **cặp đã chấm** phải `verified_eligible_rows` (Forecasts + conditional-write provenance); `schedule_evidence_status` chỉ mô tả mức audit lịch kỳ vọng (`not_audited_mvp` khi không tra logs), **không là điều kiện completion**. `publication_completeness` chỉ là tỷ lệ/counters dự kiến–thực có, không đại diện cho tính hợp lệ của `n_obs`. Nếu `expected_count=0` hoặc có ngày thiếu row, job vẫn có thể `COMPLETED` với 28 metric rows (kể cả `undefined` nếu không có cặp), miễn mọi **cặp được tính** hợp lệ và snapshot evaluation nhất quán. Không dùng giá trị `verified` cho lịch phát hành khi không có chứng cứ log.

**Phụ thuộc contract:** `docs/eval/walk-forward-contract.md` mục 7 hiện có quy định manifest/log chặt hơn. Sau họp, PR contract riêng phải quy định rõ **ngoại lệ cho rolling_8w MVP này**: không manifest, không log-retention guard, chấm theo record phát hành hợp lệ; không tự nới lỏng tiêu chuẩn `validation`/`test` hoặc workflow import. Các mã audit nguyên nhân thiếu từ v4.2 chỉ là **giai đoạn sau**, không được tạo thành verified claims trong MVP.

### 2.6. Issue #23.1 — So khớp `prob_up` nguồn đã làm tròn [ĐỀ XUẤT MVP]

Với dữ liệu lưu Decimal 6 chữ số, đề xuất kiểm tra nhanh `abs(prob_up_stored − prob_up_recomputed(q_stored)) <= 1e-6` sau khi xác minh đủ 7 phân vị/horizon, thứ tự, miền giá trị và clipping. Sai khác trong dung sai được chấp nhận là tương thích với làm tròn; **giữ nguyên q và `prob_up` đã lưu**, không ghi đè bằng giá trị nội suy lại.

Nếu vượt ngưỡng, chỉ ghi event `prob_up_mismatch` với độ lệch và nguồn tham chiếu; **không loại forecast chỉ vì mismatch, không sửa q/`prob_up` nguồn**. Quy tắc kiểm tra shape, miền và tính hợp lệ của q là kiểm tra độc lập và vẫn bắt buộc. Kiểm thử cần có trường hợp gần 0, tie, khoảng phân vị hẹp, clip và dữ liệu thật sự không nhất quán. Kiểm tra chuyên sâu hơn có thể triển khai sau MVP.

### 2.7. Issue #23.3 — Provenance import [KHÔNG THUỘC LUỒNG ROLLING MVP]

Theo phạm vi Khải mô tả, forecast rolling production do Lambda CPAWS phát hành, không có import dữ liệu ngoài. Vì vậy MVP không xây pipeline nhập dữ liệu hoặc hệ phân loại migration riêng. Với workflow import/historical sau này, nguyên tắc `external_unverified` của Walk-forward vẫn được giữ; `created_at` một mình không chứng minh provenance của dữ liệu import. Cần Tuấn/Tiến xác nhận phạm vi dữ liệu bảng production và các đường ghi thủ công/test trước triển khai.


### 2.8. Nguồn S1a shadow: định dạng, thời điểm phát hành và provenance [ADR-0011 / PR #49]

- **Nguồn duy nhất của challenger MVP:** S1a `model_version=s1a-l094`, do cùng lần chạy Lambda predict sinh ra **chỉ khi champion dự báo thành công**. S1a sử dụng chính các phân vị thô của champion, cùng `base_date`, input đã cắt đến `base_date`, danh sách ngày bị loại và `publication_as_of`; giữ nguyên thuật toán, tham số đã chốt tại K3b, không nhìn lại Validation 2019. Nếu `k_t` không hợp lệ hoặc shadow lỗi, champion vẫn phát hành bình thường.
- **Object bất biến:** `eval/shadow/s1a-l094/dt=<ngày chạy UTC>/<asset>.json`; `dt=` là **ngày predict chạy UTC**, **không phải** `base_date`/`target_date`. Nội dung có `asset`, `base_date`, `model_version`, `target_series`, `horizons[h=1..7]` (7 q/h), `created_at`, `is_sample=false`, `input_snapshot_dt` khi contract/code hỗ trợ và `shadow.{k,sigma_short,sigma_long,champion_model_version}`. Đối chiếu schema/target series/horizon trước khi chấm; không chấp nhận mặc định rằng thiếu trường quan trọng vẫn verified.
- **Ghi một lần:** PR #49 đề xuất S3 `PutObject` với `IfNoneMatch="*"`; object tồn tại thì log `PREDICT_SHADOW_ALREADY_PUBLISHED`, không ghi đè. Định danh và checksum/object version (nếu bật versioning), S3 key/LastModified là dấu vết artifact; log shadow chỉ giúp audit vận hành **nếu có**, không phải nguồn chặn completion của champion.
- **Không suy thời điểm phát hành shadow từ `created_at` đơn lẻ:** PR #49 dùng `created_at` giống champion, nhưng object chỉ được phát hành khi ghi thành công S3. Khi so sánh, đối chiếu S3 `LastModified`/object identity với `target_date`, `created_at` và input-as-of; nếu không đủ chứng cứ thì `shadow_unverified`/skip khỏi paired mask. Không bắt buộc CloudWatch log cho nhánh shadow, không chặn champion completion.
- **Truy xuất:** dựng các candidate `dt=` từ lịch predict trong cửa sổ và `GetObject` theo key biết trước; không suy `base_date` từ S3 key, không mặc nhiên cần `ListBucket`. Một ngày chỉ có shadow cho subset asset là khả năng bình thường; thiếu, lỗi hoặc skip shadow được thống kê riêng (`shadow_missing`, `shadow_skipped`, `shadow_failed`, `shadow_unverified`), **không** nhập chung `no_forecast_row` của champion.
- **Không backfill:** S1a chỉ có dữ liệu kể từ lần deploy bật `SHADOW_MODELS=s1a-l094` và phát hành thành công. Không tái tạo từ forecast lịch sử, K3b/Validation 2019 hoặc test 2020–2026; một shadow object phát hành muộn sau khi biết nhãn không được nhận vào paired comparison chỉ vì `created_at` bằng champion.

**Ranh giới tài liệu:** PR #49 không đổi public Forecasts/API contract chỉ để thêm S1a shadow. RFC #45 quy định **đầu vào và kết quả đánh giá nội bộ**; phần thông số về shadow report sẽ đi vào contract đánh giá/nội bộ sau khi nhóm duyệt, không thêm model shadow vào public `/accuracy/{asset}`.

---

## 3. Rolling window và quy tắc evaluation

### 3.1. Cửa sổ 8 tuần [D01/D02]

| Trường | Quy tắc đề xuất |
|---|---|
| `evaluation_kind` | `rolling_8w` |
| `window_days` | **56 ngày lịch**, bao gồm cả hai biên |
| `window_anchor` | Ngày job chạy theo UTC |
| `window_basis` | `base_date` |
| `window_start/window_end` | `[run_utc_date − 55d, run_utc_date]` |
| `issued_at_min` | `2026-10-27T12:00:00Z` |
| `target_cutoff_date` | Ngày target giá hợp lệ và đã công bố cuối cùng, tính riêng từng asset |
| Tần suất | Chạy hàng tuần sau ingest/snapshot hoàn tất; mỗi asset một evaluation run riêng |

**Quy ước cuối:** `evaluation_start=window_start=job_utc_date−55 ngày`, `evaluation_end=window_end=job_utc_date` (hai biên inclusive), **không** co hẹp theo ngày đầu/cuối thật sự có forecast. Metadata riêng `first_eligible_base_date`, `last_eligible_base_date` nếu có; `target_cutoff_date` riêng từng asset và có thể sớm hơn `evaluation_end`.

Ví dụ job **05/11/2026**: cửa sổ lý thuyết là **11/09–05/11/2026**, còn forecast thực được phát hành từ 27/10 (có thể có `base_date=26/10`). Dashboard dùng câu **“Kể từ 27/10”**, không nói đã đánh giá đủ 8 tuần.

### 3.2. Luồng job `rolling_8w`

1. Khóa clean price snapshot/quality; xác định `target_cutoff_date` theo asset. Nhận cấu hình `MODEL_VERSION` từ deployment CDK làm champion hiện hành.
2. Dựng expected schedule từ trading calendar + TUE–SAT để **đếm** expected/missing, không gọi CloudWatch. Chỉ chọn bản ghi `Forecasts` production thực có, hợp lệ theo mục 2.3–2.5; không tạo forecast thay thế.
3. Ghép forecast với actual, tính đúng log return và 7 horizons; kiểm `created_at`, `is_sample`, model đang deploy, cutoff, `input_snapshot_dt` khi có, và bằng chứng conditional-write đã triển khai. **Đọc S1a từ S3 độc lập**, không dùng sự có mặt của S1a để quyết định champion eligibility.
4. Lưu counts expected/published/missing và lý do loại forecast/horizon quan sát được. Missing row không có log thì reason chỉ là `missing_record_unclassified`; không gán skip/upstream đã xác minh.
5. Kiểm shape 7 q và `prob_up` (mismatch >`1e-6` chỉ audit), calendar/valid endpoints; không sửa nguồn. Common mask theo Accuracy Schema; tính 4 metrics và `n_obs`, `n_base_dates` từng h/overall.
6. Ghi `METRIC` qua conditional PutItem, chốt `META` status/28 row hashes/`run_id`, snapshot/version, cutoff, `MODEL_VERSION`, eligible-pair evidence, counts và `undefined_reason` khi không có nhãn. Không yêu cầu log ref hay trạng thái full-schedule verified.
7. Chuyển `META` sang `COMPLETED` chỉ sau khi validation nội dung thành công. Sau đó conditional `UpdateItem` **`STATE`/`LATEST_COMPLETED`** theo `latest_run_order` tăng, tuyệt đối không công bố run dở.
8. **Nhánh ADR-0011:** chấm champion–S1a trên paired common mask và ghi **Parquet nội bộ `eval/shadow_eval/`** theo mục 4.6; shadow thiếu/lỗi không chặn champion `COMPLETED`, không cập nhật `STATE` và không xuất public API.

**Giới hạn rollout:** khi đổi champion qua ADR/CDK, cập nhật cấu hình API và rolling đồng bộ với predict; API chỉ trả run mà `META.model_version` trùng `MODEL_VERSION` hiện tại, nếu pointer cũ không phù hợp thì `not_ready`. Không phục hồi forecast lịch sử hoặc tính lại Validation 2019.

### 3.3. Metric và `n_obs`

| Metric | Định nghĩa | Ghi chú |
|---|---|---|
| `coverage_80` | `mean(q10 <= y <= q90)` trên cặp return hợp lệ | Đếm số hit/tổng số cặp; mục tiêu danh nghĩa 80% |
| `width_80` | `mean(q90 − q10)` | Lưu log return; nếu hiển thị dạng %, ghi đúng đơn vị chuyển đổi |
| `sign_accuracy` | Dấu của q50 đúng dấu y, loại trường hợp dấu bằng 0 theo schema | Chỉ hiển thị cùng `up_rate` |
| `up_rate` | `mean(y>0)` trên common mask | Có thể có `n_obs` khác sign accuracy |
| Các metric khác | Theo Accuracy Schema | Lưu khi có đủ dữ liệu; không bắt buộc hiển thị trên web MVP |

`overall.coverage_80` = tổng số hit ở tất cả h / tổng số cặp đủ điều kiện. Không lấy trung bình không trọng số của 7 tỷ lệ và không tạo hàng `h=0` trong Accuracy. Các horizons có thể cùng `base_date`, nên `n_obs` cặp không phải số ngày quan sát độc lập.

**Ngưỡng hiển thị đã được Khải đồng ý (D06/D11):** tối thiểu **20 `base_date` khác nhau có ít nhất một cặp đã có nhãn và được tính cho `overall.coverage_80`**. Trước ngưỡng: giữ metric nội bộ nếu tính được, API `display_value=null`, `display_status=insufficient_data`, web hiển thị X/Y và “từ N ngày dự báo” thay cho phần trăm. Từng h chỉ hiển thị X/Y, không hiện tỷ lệ %. Trường hợp `n_obs=0` có `status=undefined` và giá trị null.

Khải ước tính nếu đủ lần phát hành và nhãn: 05/11 có 7 `base_date` / 28 cặp; 15/11: 14 / 77; 22/11: 19 / 112; 30/11: 23 / 140. Đây là **số dự kiến**, không phải số rolling production đã đo. Ngưỡng 20 ngày chỉ là quy tắc hiển thị UX.

### 3.4. Champion theo `MODEL_VERSION` trong CDK, đổi bằng ADR [D10]

**Nguồn champion duy nhất của MVP là cấu hình `MODEL_VERSION` được CDK deploy** vào Predict, Rolling job và API (cùng release/version). **Predict không đọc bảng Accuracy**; không tồn tại `champion_release_operator` và `champion_generation` lưu trong `STATE`. Việc đổi champion phải có quyết định ADR/release theo quy trình nhóm, áp dụng từ `base_date` phiên kế tiếp. Không tự động promote S1a dựa vào shadow.

Bảng Accuracy `STATE` **không quyết định model**; chỉ lưu con trỏ `LATEST_COMPLETED` (`latest_run_pk`, `latest_run_id`, `latest_run_order`). `META.model_version` của run phải khớp `MODEL_VERSION` của deployment khi API trả kết quả. Khi đổi champion, pointer tạm trỏ run model cũ thì **API trả `not_ready`**, không coi là current; job của model mới chỉ chấm các bản ghi mới từ `effective_base_date` đã được quyết định trong release/ADR, không trộn đời model. Giữ `evaluation_start/end` theo 56 ngày; metadata `champion_effective_base_date` có thể được lấy từ release configuration, **không suy ra từ STATE**.

**Giới hạn concurrent deployment cần kiểm thử:** `latest_run_order` tăng đơn điệu ngăn run cũ theo thời gian rollback pointer, nhưng **không tự ngăn một writer còn chạy với `MODEL_VERSION` cũ ghi một run có `run_order` lớn hơn** khi triển khai chưa đồng bộ. Do đó (a) release phải thay/đóng writer cũ trước khi đánh giá đời mới, (b) writer sử dụng phiên bản được deploy, (c) API fail-closed bằng việc so `META.model_version` với `MODEL_VERSION` đang chạy; nếu không khớp, trả `not_ready`. Đây là guard để không hiển thị nhầm champion, **không khẳng định IAM hoặc `run_order` một mình bảo đảm liveness/đồng bộ rollout**.

### 3.5. Chấm champion–challenger trên cùng tập quan sát [ADR-0011]

**Hai luồng tách biệt, chung lịch chạy:** (A) **Accuracy production** chấm *mọi* forecast champion đủ điều kiện theo mục 2–3 và ghi DynamoDB cho `/accuracy/{asset}`; (B) **shadow paired comparison** chỉ chấm phần giao champion–S1a cho báo cáo nội bộ. S1a không tham gia `STATE`, không cập nhật champion pointer, không ảnh hưởng ngưỡng 20 ngày của Dashboard. Khi ADR đổi champion tương lai được duyệt, phát hành production vẫn phải tuân theo contract Predict/Forecasts; không tự nâng bản shadow S3 thành forecast production.

**Khóa ghép chính xác:** một cặp có cùng `(asset, base_date, h, target_date, target_series)` và source/version/cutoff của nhãn; `model_version` khác là điều **mong muốn** (`baseline-q252` và `s1a-l094`). Chỉ chấm khi **cả hai** dự báo có provenance phát hành hợp lệ *trước nhãn*, mỗi bên đủ 7 phân vị, có actual log return hợp lệ và thỏa cùng `target_cutoff_date`/calendar. `paired_mask = champion_eligible & shadow_eligible & actual_valid & same_target_definition`; không nén hoặc thay thế những cặp còn thiếu shadow. `paired_n_obs` và số `base_date` ghép được ghi **riêng** với `n_obs` của Accuracy production.

**Metric tối thiểu của báo cáo shadow theo ADR-0011:** `pinball_skill`, `coverage_80`, `width_80` **cho cả hai model trên đúng paired mask**, tách h=1..7, kèm counts/coverage và tổng hợp có trọng số theo số cặp; `pinball_skill = 1 - PL(model) / PL(baseline-q252)` với PL (7 phân vị) tính **trên cùng paired mask**. Champion baseline đối chiếu với chính nó bằng 0 khi mẫu số dương; nếu không đủ cặp hoặc mẫu số bằng 0 → `undefined` có reason, không sinh NaN trong JSON. S1a giữ q50 của champion nên thống kê dựa trên dấu q50 (nếu có) là như nhau trên paired mask, nhưng **không** dùng điều đó thay cho kiểm tra thực tế. Không công bố shadow `pinball_skill` lên Dashboard.

**Thời điểm bắt đầu:** S1a chỉ được ghép từ lần phát hành S3 đầu tiên đã xác minh; cửa sổ thời gian chung `[max(window_start, first_verified_shadow_base_date), window_end]`, vẫn cần target đã trưởng thành. Đếm chính xác cặp chung thay vì lấy sẵn `overall` champion từ DynamoDB (vì hai mẫu quan sát khác nhau). Nếu shadow chưa deploy, không có cặp, object thiếu hoặc provenance unverified → báo `shadow_not_ready`/counts, **champion Accuracy vẫn được phát hành độc lập**. Số liệu Validation 2019 và test lịch sử không làm nguồn cho paired shadow live.

**Đổi champion:** theo ADR-0008/ADR-0009 mục 4, phải có đánh giá/ADR và người duyệt; **không tự động switch** chỉ vì vài tuần live shadow. ADR-0011 thay thế hạ tầng retrain hàng tuần bằng **chấm champion/challenger hàng tuần**, không đổi tiêu chuẩn promote.

---

## 4. Accuracy Storage — kiến trúc vật lý cuối đề xuất

**Ranh giới schema đã chốt:** `validation`/`test` → S3 Parquet `eval/`; Accuracy **chính thức của champion** `rolling_8w` → DynamoDB. **Báo cáo so sánh shadow** là artifact thực nghiệm nội bộ trên S3 (mục 4.6), **không** tạo thêm hàng `sample=shadow` hay enum `evaluation_kind` trong Accuracy Schema. Giữ nguyên khóa logic `(run_id, model_version, asset, sample, evaluation_kind, evaluation_start, evaluation_end, target_cutoff_date, h, metric)` của `docs/api/accuracy-schema.md`. `overall` là aggregate trong run `META`, không phải hàng metric `h=0`; mọi hàng metric h=1..7 giữ nguyên schema logic.

### 4.1. Bảng, PK/SK và `LATEST_COMPLETED` access patterns [D05/D10]

**Bảng:** `cpaws-<env>-accuracy`, một bảng `PK` (String) / `SK` (String), **không GSI/LSI/Scan** trong MVP, không TTL cho record đã công bố. Phần động của key phải canonical-encode/length-prefix để không gây collision dấu `#`.

| Item | `PK` | `SK` | Nội dung chính |
|---|---|---|---|
| `STATE` (= **`LATEST_COMPLETED`**) | `ASSET#<asset>` | `STATE` | **Chỉ** con trỏ `latest_run_pk`, `latest_run_id`, `latest_run_order`; không có champion version/generation hoặc quyền release operator |
| `META` | `RUN#<asset>#<model_version>#<run_id>` | `META` | Run status, model version của **run** (không nguồn champion), fingerprints, window/cutoff, snapshot/evidence của các cặp được chấm, 28 expected metric keys, aggregate/counts |
| `METRIC` | **Cùng PK với META** | `METRIC#<sample>#<evaluation_kind>#<evaluation_start>#<evaluation_end>#<target_cutoff_date>#H<h>#<metric>` | Một item theo h/metric và khóa logic; có `payload_hash` |

**Thuật ngữ thống nhất:** `latest_run_pk`, `latest_run_id`, `latest_run_order` trong `STATE` **chính là cơ chế `LATEST_COMPLETED` của MVP**. Không có item `SK=LATEST`, partition champion riêng, hay bảng champion khác. `STATE` là tên kỹ thuật của item; `LATEST_COMPLETED` là vai trò của ba trường pointer.

`run_id` định danh evaluation run, không phải forecast run: `run_id = <job_utc_date>-<sha256(canonical(asset, MODEL_VERSION, job_date, revision, config_hash, immutable_snapshot_identity, target_cutoff_date, eligible_record_fingerprint))[:20]>`. Fingerprint lưu đầy đủ trong META để tránh phụ thuộc hash rút gọn. `run_order=<YYYYMMDD>#<revision_4_digits>`; correction sau run completed dùng revision tăng có audit và `run_id` mới; retry cùng run/input giữ nguyên revision. Cùng `run_order` khác run là **conflict**, không promote.

**Access patterns:**

1. `GET /accuracy/{asset}`: `GetItem(PK=ASSET#asset, SK=STATE, ConsistentRead=true)` → `Query(PK=latest_run_pk, ConsistentRead=true)` (phân trang tới hết), chỉ khi `latest_run_pk` có giá trị. API kiểm `META.status=COMPLETED`, `META.model_version == MODEL_VERSION` hiện deploy và 28 keys/hashes hợp lệ trước khi trả. 1 GetItem + 1 Query logic, 0 Scan/GSI.
2. Audit một run: `Query(PK=RUN#asset#model#run_id)` khi biết run identity; không public route audit ở MVP.
3. Idempotent run write: `GetItem(META)` + conditional PutItem cho từng `METRIC` (không Query xuyên run).
4. ADR/CDK champion change: API/deployment dùng `MODEL_VERSION` mới; `STATE` không được Predict hoặc release operator sửa. Pointer model cũ có thể tạm tồn tại, nhưng API trả `not_ready` cho đến khi có `COMPLETED` run của model mới.

**Ví dụ:**

```text
PK=ASSET#wti                                             SK=STATE
PK=RUN#wti#baseline-q252#20261105-a94e7b3d4d0c1fb8a5e0 SK=META
PK=RUN#wti#baseline-q252#20261105-a94e7b3d4d0c1fb8a5e0 SK=METRIC#all#rolling_8w#2026-09-11#2026-11-05#2026-11-04#H1#coverage_80
```

Khóa theo run cô lập model/run/asset, SK metric mã hóa đầy đủ `sample`, evaluation kind, window, cutoff, h và metric. `overall` nằm trong META, không tạo `h=0`.

### 4.2. Immutable metric writes, fingerprint và retry [D19]

- Lấy snapshot/champion `MODEL_VERSION` cấu hình của job, tạo `run_id`/full fingerprint theo mục 4.1. `META` bắt đầu `RUNNING` bằng conditional `PutItem(ConditionExpression=attribute_not_exists(PK))`. Nếu đã tồn tại: so toàn bộ fingerprint; giống và chưa completed → resume; giống và completed → chỉ xác nhận pointer/return idempotently; khác → `RUN_ID_CONFLICT`.
- `METRIC` dùng conditional `PutItem(ConditionExpression=attribute_not_exists(PK))` ở item khóa `(PK,SK)`. Conditional fail → consistent GetItem và so `payload_hash` cùng nội dung canonical; cùng payload → no-op; khác → `IMMUTABLE_METRIC_CONFLICT`. **Không dùng BatchWriteItem** (không có conditional expressions).
- `META` được phép chuyển `RUNNING→VALIDATING→COMPLETED`, hoặc `FAILED` khi lỗi, bằng conditional UpdateItem; fingerprint/config/snapshot/evidence và metric manifest giữ bất biến. `FAILED` terminal: chạy lại có revision mới. Run bị ngắt trước completed được resume chỉ với cùng fingerprint.
- `config_hash` hash nội dung canonical; `eligible_record_fingerprint` gồm khóa và định danh/`created_at` của **các record Forecasts đã đủ điều kiện**, mốc rollout conditional-write, model, target cutoff và snapshot/quality version (nếu có). **Không cần `evidence_fingerprint` của CloudWatch schedule logs** để tạo run_id hoặc promote.
- Snapshot/cấu hình/evaluation correction tạo run mới; metric run cũ không bị ghi đè. Nếu snapshot không bảo đảm tính nhất quán ở thời điểm evaluation, không promote.

### 4.3. Run completion, `LATEST_COMPLETED` promotion và concurrent writers [D19]

**`COMPLETED` là trạng thái xử lý và kiểm tra nguồn của những cặp được chấm**, không có nghĩa đầy đủ lịch phát hành hoặc đủ ngưỡng hiển thị. MVP **không chặn completion do thiếu CloudWatch logs, manifest hoặc các ngày expected không có Forecasts row**.

Bốn điều kiện bắt buộc để `META.status=COMPLETED`:

1. `META` có fingerprint, model version bằng `MODEL_VERSION` của job khi tính, window/cutoff theo asset, `sample=all`, `evaluation_kind=rolling_8w`, snapshot và `input_snapshot_dt` (khi contract áp dụng) nhất quán. Không đếm forecast sample, backfill, record trước mốc 27/10 12:00Z hoặc trước cutover bảo vệ immutable nếu không có chứng cứ tương đương.
2. **Mọi cặp dùng trong `n_obs`** có bản ghi `Forecasts` production hợp lệ, `created_at` trong thời gian cho phép và conditional-write provenance có thể xác nhận theo PR #48, target/actual theo calendar & cutoff, q hợp lệ. Ngày expected **không có record** → chỉ tăng `missing_count`, không chặn completed; thiếu logs không biến lịch thành `verified`, cũng không làm cặp hợp lệ bị loại.
3. Đủ **28 item METRIC** = 7 horizons × (`coverage_80`, `width_80`, `sign_accuracy`, `up_rate`); mỗi item có count/hash và `status=ok` hoặc `undefined/not_applicable` có reason hợp lệ. Chỉ chấm quan sát đủ điều kiện, `n_obs`, `n_base_dates`, overall pooled hit/count và expected/published/missing counters nhất quán. `overall` trong META, không có `h=0`.
4. Không còn lỗi đọc snapshot, tính toán, conflict hoặc ghi metric chưa xử lý; strong read xác nhận 28 keys/hashes đúng trước khi complete.

**`COMPLETED` không yêu cầu `n_obs>=1` hoặc `n_base_dates>=20`.** Run với `n_obs=0` được `COMPLETED` nếu đã ghi 28 metric rows `undefined` và đúng số đếm, không bịa nhãn. `display_status=insufficient_data` khi chưa đủ 20 `base_date` có cặp hợp lệ; `ready` là UX, không phải run status. `issuance_evidence_status=verified_eligible_rows` chỉ áp dụng khi có **các cặp đã chấm**; nếu `n_obs=0`, dùng `no_eligible_rows`, không gắn nhãn verified cho dữ liệu không tồn tại; `schedule_evidence_status=not_audited_mvp` không có nghĩa kỳ phát hành nào cũng được xác minh.

**Conditional writes minh họa:**

```python
metric_put_condition = "attribute_not_exists(PK)"  # PutItem trên (PK, SK)
meta_complete_condition = "#s = :validating AND config_hash = :config_hash"
state_promote_condition = (
    "attribute_not_exists(latest_run_order) OR latest_run_order < :new_order "
    "OR (latest_run_order = :new_order AND latest_run_pk = :same_run_pk)"
)
```

`STATE` **không** chứa model/generation để Rolling writer có thể thay champion. Nếu item chưa có, writer dùng conditional `PutItem` tạo đúng item pointer; sau đó `UpdateItem` có điều kiện trên thứ tự/cùng pointer. Khi cùng `run_order` nhưng khác `run_pk`, phải báo conflict. `latest_run_order` có định dạng canonical cố định để so thứ tự lexicographic. Cần đọc lại pointer và run hash khi retry để không nhận nhầm payload.

**Publish protocol:** A. ghi đầy đủ METRIC, META `VALIDATING` và strong-read xác nhận 28 rows/evidence → B. conditional META→`COMPLETED` → C. conditional `UpdateItem` STATE/LATEST_COMPLETED (`latest_run_pk`, `latest_run_id`, `latest_run_order`) với order tăng (hoặc same-run idempotent). Nếu crash giữa B/C, run completed nhưng chưa visible; retry C. Nếu crash trước B, pointer không đổi. Không mặc định dùng multi-item transaction; chỉ bổ sung nếu xuất hiện invariant nguyên tử mới.

**API kiểm fail-closed:** `GetItem(STATE)` và `Query(run PK)` strongly consistent; kiểm `META.status=COMPLETED`, `META.model_version==MODEL_VERSION` của API/CDK đang chạy, run identity/order, 28 metric hashes và eligibility/cutoff. Đọc lại `STATE` để bắt concurrent promote; nếu pointer thay hoặc model mismatch trả `not_ready`/retry ngắn. Khi ADR đổi champion, job model cũ không có quyền sửa champion, nhưng có thể gây stale pointer nếu rollout chưa đồng bộ; API vẫn **không trả sai model**. Release quy định tránh chạy song song hai đời writer; trường hợp lỗi/không đồng bộ phải test và xử lý vận hành.

**Không nhầm IAM với conditional expressions:** IAM giới hạn resource, action và (khi phù hợp) PK/attributes; chỉ logic điều kiện ứng dụng mới chống retry khác payload và rollback pointer. Không cấp API quyền UpdateItem.

### 4.4. IAM — quyền tối thiểu của MVP [D20]

| Role / thành phần | Actions cần thiết | Tài nguyên / phạm vi |
|---|---|---|
| **Rolling writer** | Accuracy: `dynamodb:GetItem`, `Query`, `PutItem`, `UpdateItem`; Forecasts: `dynamodb:GetItem`, `Query`; S3: `s3:GetObject` clean & shadow source; `s3:GetObject` shadow_eval chỉ khi verify retry; `s3:PutObject` **chỉ shadow_eval output** | Accuracy table ARN, Forecasts table ARN; S3 `clean/*`, `eval/shadow/s1a-l094/*` (read), **`eval/shadow_eval/*`** (write and optional read); không `Scan/DeleteItem/BatchWriteItem`. Chia IAM statements cho `RUN#...` và `ASSET#...` theo `dynamodb:LeadingKeys` khi có thể; `UpdateItem` trên `STATE` chỉ cấp cho **Rolling writer**, scope pointer attributes `latest_run_pk`, `latest_run_id`, `latest_run_order` cùng `PK/SK` bằng `dynamodb:Attributes` nếu đáp ứng được cách gọi AWS SDK, kiểm chứng bằng IAM tests. Không cấp quyền cập nhật champion (không có field champion trong STATE). |
| **Accuracy API reader** | `dynamodb:GetItem`, `dynamodb:Query` | **Chỉ** bảng Accuracy; read-only, không `Scan`, `PutItem`, `UpdateItem`, `DeleteItem`, không đọc Forecasts/S3/logs. Model hiện hành lấy từ `MODEL_VERSION` của deployment API, **không** từ STATE. |
| **Predict Lambda** | Forecasts: `dynamodb:PutItem` với conditional write; S3 `s3:PutObject` cho source S1a khi bật shadow | Giữ quyền theo PR #48/#49/#51; **không cấp quyền đọc/ghi bảng Accuracy**. `MODEL_VERSION` của Predict do CDK cung cấp, không phụ thuộc `STATE`. Predict role có thể được cấp `eval/shadow/*` theo PR #51 nhưng **không được ghi `eval/shadow_eval/*`**. |
| **Ingest Lambda** | Quyền ingest hiện hữu | Không ghi Accuracy hoặc shadow_eval reports. |

**Bảo vệ `STATE` ngoài tầng ứng dụng:** không có champion/version/generation trong bảng Accuracy để writer có thể thay đổi quyết định model. IAM chỉ cấp `UpdateItem` trên bảng Accuracy cho Rolling writer; phân tách statements theo `dynamodb:LeadingKeys` và giới hạn `dynamodb:Attributes` cho pointer UpdateItem khi CDK/SDK hỗ trợ; tests phải chứng minh writer không thể thay ngoài pointer fields hoặc ngoài bảng, và API/Predict không thể cập nhật STATE. **Giới hạn quyền theo attributes không tự chứng minh tính đúng của giá trị**; conditional UpdateItem và API model-match vẫn bắt buộc. Không thêm champion release operator vào MVP.

Không yêu cầu `logs:FilterLogEvents`, `logs:DescribeLogStreams`, `logs:GetLogEvents` hay nâng CloudWatch retention lên 90 ngày như **điều kiện rolling MVP**. Log vận hành vẫn có thể dùng theo nhu cầu observability qua role riêng, nhưng không được dùng làm gate `COMPLETED` 05/11. `kms:Decrypt` chỉ khi S3 objects dùng customer-managed KMS; IAM S3 ARN/bucket account/environment phải cụ thể và shadow_eval tách prefix khỏi `eval/shadow/*`.

### 4.5. Data integrity, TTL và rollback

- Không TTL cho item `STATE`, `META` completed hoặc `METRIC` trong MVP. Không xóa item đang được `LATEST_COMPLETED` tham chiếu.
- Dữ liệu `Forecasts` production dùng conditional write mục 2.4; `PREDICT_ALREADY_PUBLISHED` chỉ idempotent sau GetItem so đúng payload. Snapshot correction tạo evaluation run mới với revision/fingerprint, không sửa forecast gốc.
- `input_snapshot_dt` từ PR predict là **metadata của Forecasts**, không thay `created_at`, `base_date`, `target_date` hoặc bảo đảm as-of một mình; không suy provenance hồi tố chỉ từ timestamp.
- Run có conflict/snapshot không nhất quán → `FAILED`/không promote; **thiếu ngày expected nhưng không có row không làm run FAILED**. Không ghi nhãn hoặc forecast giả. Sửa metadata/champion cần ADR/CDK, **không có release workflow ghi STATE**.
- Nếu MODEL_VERSION thay đổi giữa các phiên bản triển khai, API phải fail-closed khi META của pointer không trùng với config hiện hành; phát hành champion mới theo ADR và không trộn forecast trước/sau hiệu lực.

### 4.6. Nơi lưu paired shadow Parquet — ngoài Accuracy [ADR-0011 / D21–D24]

**Theo PR #49 mục 14 và phản hồi Khải:** report so sánh champion–S1a là **Parquet nội bộ trên S3**, prefix **`s3://cpaws-<env>-lake/eval/shadow_eval/run_id=<run_id>/`**, tách hẳn input S1a **JSON** tại `eval/shadow/s1a-l094/dt=<UTC>/<asset>.json`. Định danh file theo asset + `comparison_id` để tránh đụng khóa khi một evaluation run tạo báo cáo nhiều asset; ví dụ **đường dẫn đề xuất bên trong prefix** `asset=<asset>/comparison_id=<fingerprint>.parquet` (cần đồng bộ với spec PR #49 nếu nêu tên file khác). `comparison_id` hash job/config, model `MODEL_VERSION` của run, shadow model, source ids/checksums, target cutoff/snapshot và paired common-mask hash; không có `champion_generation` trong metadata.

**Bất biến:** S3 `PutObject(IfNoneMatch="*")`; retry đúng payload đọc lại/check checksum và no-op; payload khác cùng object key → conflict, không overwrite. `GET` report (nếu cần cho retry) được cấp cho writer đúng `eval/shadow_eval/*`; public API/Read-only Accuracy Lambda **không** có quyền đọc report. **Tách biệt IAM:** Predict có quyền ghi `eval/shadow/*` theo PR #51 nhưng **không có quyền ghi prefix sibling `eval/shadow_eval/*`**. Không cập nhật `STATE`/`LATEST_COMPLETED` hoặc API do shadow report.

**Schema report tối thiểu:** `report_kind=paired_shadow_comparison`, `asset`, `run_id`, `comparison_id`, `job_utc_date`, window/cutoff, champion `model_version`, challenger `s1a-l094`, `source_refs` (Forecasts key + shadow S3 key/version/ETag + target snapshot), `first_verified_shadow_issued_at`, `common_pairs_hash`, counts `paired_n_obs_by_h` và `n_base_dates_paired`; `pinball_skill`, `coverage_80`, `width_80` cho **cả hai model trên cùng paired mask**, theo h=1..7 và overall theo tổng hợp hợp lệ. Cột Parquet có kiểu rõ ràng, null + `undefined_reason` cho undefined, không lưu `NaN` giả hay tự backfill S1a. Chỉ chấm shadow đã có S3 issuance evidence đủ điều kiện (S3 LastModified + created_at/cutoff); thiếu shadow không chặn champion completion.

**Không thay Accuracy Schema:** champion `rolling_8w` chính thức vẫn ở DynamoDB; Parquet shadow là artifact so sánh nội bộ, không phải `evaluation_kind=rolling_8w` ghi trên S3 theo nhánh champion, không thêm enum `sample`/`evaluation_kind`, không public endpoint. IAM mới của Rolling writer phải được review trước deploy; không tự cấp quyền Predict vào shadow_eval.

## 5. API `GET /accuracy/{asset}` [ĐỀ XUẤT]

### 5.1. Request

`GET /accuracy/wti`, với Cognito ID token như API hiện tại; asset thuộc `gold`, `silver`, `brent`, `wti`. MVP cố định `evaluation_kind=rolling_8w`, `sample=all` và **chỉ champion** theo `MODEL_VERSION` của CDK/API; `STATE` chỉ trỏ `LATEST_COMPLETED`. S1a shadow và paired reports không có route public và không nằm trong JSON Accuracy. Không hỗ trợ chọn model/run khác qua public query params trong MVP; request tham số không hỗ trợ bị từ chối hoặc bỏ qua theo hợp đồng API hiện có (ưu tiên từ chối để tránh hiểu nhầm).

### 5.2. Ví dụ JSON response

> **Chỉ minh họa định dạng, không phải số liệu CPAWS đã chạy.** `by_horizon` dưới đây rút gọn; API thực tế trả đủ 7 h. Khuôn dữ liệu này là **đề xuất của RFC v4.3**, có hiệu lực khi PR contract được duyệt.

```json
{
  "asset": "wti",
  "model_version": "baseline-q252",
  "evaluation_kind": "rolling_8w",
  "sample": "all",
  "run_id": "example-eval-rolling-2026-11-05-wti",
  "evaluated_at": "2026-11-05T18:00:00Z",
  "window": {
    "basis": "base_date",
    "days": 56,
    "window_start": "2026-09-11",
    "window_end": "2026-11-05",
    "target_cutoff_date": "2026-11-04",
    "first_real_issuance_at": "2026-10-27T12:00:00Z"
  },
  "evaluation_evidence": {
    "schedule_basis": "trading_calendar_and_predict_schedule",
    "schedule_evidence_status": "not_audited_mvp",
    "issuance_evidence_basis": "forecast_record_conditional_write",
    "issuance_evidence_status": "verified_eligible_rows",
    "publication_completeness": "partial",
    "expected_count": 28,
    "published_count": 24,
    "missing_count": 4
  },
  "overall": {
    "coverage_80": {
      "covered_count": 14,
      "n_obs": 18,
      "n_base_dates": 7,
      "min_display_base_dates": 20,
      "display_value": null,
      "status": "ok",
      "display_status": "insufficient_data"
    },
    "width_80": {"value": 0.025, "n_obs": 18, "unit": "log_return", "status": "ok"},
    "sign_accuracy": {"value": 0.5, "n_obs": 16, "status": "ok"},
    "up_rate": {"value": 0.555556, "n_obs": 18, "status": "ok"}
  },
  "by_horizon": [
    {"h": 1, "coverage_80": {"covered_count": 5, "n_obs": 7, "n_base_dates": 7, "display_status": "counts_only"}},
    {"h": 2, "coverage_80": {"covered_count": 4, "n_obs": 6, "n_base_dates": 6, "display_status": "counts_only"}}
  ],
  "data_status": "collecting",
  "disclaimer": "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

### 5.3. Quy ước API

- `overall.coverage_80` gộp theo số cặp; `by_horizon` trả đủ h=1..7, mỗi metric có `n_obs` và trạng thái riêng; `n_base_dates` là số base date **khác nhau có cặp hợp lệ cho scope/metric tương ứng**, không phải số cặp.
- Dashboard MVP hiển thị `coverage_80`, `width_80`, `sign_accuracy`, `up_rate` **cho champion production**. Với `gold/silver`, ADR-0005 (b) cấm hiển thị chuỗi giá Yahoo; các chỉ số Accuracy và dự báo return %/xác suất tăng không phải chuỗi giá và tiếp tục được phép hiển thị. Không hiển thị `pinball_skill=0` của champion `baseline-q252` so với chính baseline, không trả S1a/paired report trong Accuracy API. Metric khác vẫn được lưu nếu tính được; shadow `pinball_skill` chỉ trong artifact nội bộ.
- `width_80` lưu log return; frontend đổi sang % và ghi rõ cách đổi. `sign_accuracy` và `up_rate` luôn đi cặp nhưng không mặc định có cùng mẫu số.
- `coverage_80.display_value=null` khi chưa đạt ngưỡng hiển thị đã chốt; không sửa `status` nội bộ chỉ vì ngưỡng UX. Tránh đưa tỷ lệ bị ẩn lên web thông qua field phụ.
- `data_status=not_ready|collecting|ready`: **HTTP 200 + `not_ready`** (null metrics) nếu chưa có completed run của `MODEL_VERSION` hiện hành; `collecting` nếu completed nhưng chưa đủ 20 `base_date` hợp lệ; `ready` khi đạt ngưỡng hiển thị. API đọc `STATE`/`LATEST_COMPLETED` bằng GetItem rồi Query run META+metrics bằng PK, không Scan/GSI; kiểm `META.model_version==MODEL_VERSION` trong cấu hình API và kiểm lại pointer trước khi trả. `STATE` không cung cấp champion; sai model → `not_ready`. Asset/auth/hạ tầng theo error envelope hợp đồng hiện hành.
- Không công bố là đã kiểm chứng đầy đủ lịch phát hành chỉ vì có forecast được chấm; `schedule_evidence_status=not_audited_mvp` và publication counters tách khỏi coverage. Không đưa logs/credentials hoặc thông tin nội bộ nhạy cảm ra API.

---

## 6. API biểu đồ “dự báo cũ so với thực tế” [ĐỀ XUẤT]

### 6.1. Kiến trúc endpoint lịch sử (giai đoạn sau 05/11)

**Chọn endpoint riêng** `GET /forecast-history/{asset}` thay vì nhúng chi tiết vào `/accuracy/{asset}`; đưa vào giai đoạn chart (dự kiến 15/11), **không là điều kiện chặn giao MVP Accuracy 05/11**. Hỗ trợ `h=1..7`, `limit<=30`, cursor opaque dựa trên last evaluated key; chỉ Query bảng Forecasts theo PK=asset và SK=base_date, không Scan. Không lưu cặp history trong bảng Accuracy và không giả tạo forecast quá khứ.

Nguồn actual: clean snapshot có chứng cứ (tốt nhất sử dụng snapshot ref của evaluation run được công bố khi có nhãn; nếu không có nhãn đã published → `pending`). History Lambda/role riêng có quyền `Query` Forecasts và `GetObject` đối với đúng clean snapshot; **không mở rộng quyền của Accuracy API reader**. Trả cả forecast đã phát hành thật (kể cả các model champion cũ), có `model_version` rõ ràng; cùng target series/log return và phiên giao dịch. Không đính kèm forecast import chưa verified dưới danh nghĩa production. Do cần tích hợp và kiểm thử riêng, route này được thông qua như **kiến trúc giai đoạn 2**, việc triển khai thuộc PR riêng.

### 6.2. JSON phác thảo

`GET /forecast-history/wti?h=3&limit=30` (Cognito ID token; route triển khai giai đoạn 2):

```json
{
  "asset": "wti",
  "h": 3,
  "items": [
    {
      "base_date": "2026-10-26",
      "target_date": "2026-10-29",
      "created_at": "2026-10-27T12:15:00Z",
      "model_version": "baseline-q252",
      "target_series": "CL=F",
      "forecast_return": {"q10": -0.035, "q50": 0.001, "q90": 0.036},
      "actual": {"log_return": 0.012, "status": "observed"},
      "inside_80": true
    }
  ],
  "next_cursor": null
}
```

Giá trị chỉ minh họa, `target_date` phải xác nhận theo trading calendar. Với `pending`, `actual.log_return=null`, `inside_80=null`. Không tạo forecast mới khi GET. Chart mặc định biểu diễn return % để tránh nhầm GLD/SLV với giá spot; nếu biểu diễn giá, phải chuyển cả dự báo lẫn thực tế về cùng chuỗi và đơn vị. Cursor phải bảo đảm phân trang ổn định theo `base_date`; snapshot correction chỉ làm thay đổi nhãn trên một phiên bản API/đánh giá mới có provenance, không sửa forecast gốc.

---

## 7. Edge cases và vận hành

| Tình huống | Quy tắc MVP v4.3 |
|---|---|
| `is_sample=true` hoặc `created_at` trước 27/10 12:00Z | Loại khỏi rolling production |
| Forecast record có trước khi PR #48 immutable-write được áp dụng | Không tự coi là verified chỉ nhờ `created_at`; thiếu bằng chứng tương đương thì loại khỏi `n_obs` |
| Phát hành 27/10 cho `base_date=26/10` | Vẫn xét nếu đáp ứng nguồn phát hành bất biến và các kiểm tra khác |
| `h=1` phát hành ngày target | So timestamp cutoff 13:30 UTC, không so ngày; bảo vệ input-as-of tại predict |
| Đã có production cùng `(asset, base_date)` | Conditional write không ghi đè; retry chỉ no-op sau khi kiểm payload giống |
| Một ngày theo calendar TUE–SAT không có Forecasts row | Tăng missing counter, không chấm, reason `missing_record_unclassified`; **không chặn `COMPLETED`**, không gán đã xác minh upstream/skip |
| Log CloudWatch thiếu/hết 30 ngày | Không dùng làm evidence hay gate completion MVP; không bắt buộc tăng retention 90 ngày |
| `prob_up` lệch >`1e-6` | Chỉ ghi `prob_up_mismatch`, không loại, không ghi đè q/`prob_up` |
| Target chưa published/chưa đến cutoff | Pending; không tăng `n_obs` |
| Giá endpoint thiếu/rejected/không dương | Loại cặp theo ADR-0008, không nội suy endpoint |
| Thiếu phiên giữa endpoints | Không tự loại nếu hai endpoint hợp lệ; ghi số phiên thiếu |
| `input_snapshot_dt` sai/thiếu tại record thuộc contract mới | Ghi lý do record ineligible; không bịa metadata, không buộc CloudWatch để complete các cặp khác |
| `n_obs=0`, đủ 28 item undefined và dữ liệu nhất quán | Vẫn có thể `COMPLETED`; API `collecting` hoặc chưa đủ dữ liệu tùy run/pointer, không hiện tỷ lệ |
| Chưa đủ 20 base_date có cặp coverage | Chỉ X/Y và số ngày, không hiện overall % |
| Đổi champion theo ADR/CDK `MODEL_VERSION` | Không cập nhật champ/generation ở STATE; API đối chiếu META model hiện hành, mismatch → `not_ready`; job chỉ chấm đời mới từ release effective date |
| Writer đời cũ sau deploy, run_order mới hơn | Không có quyền đổi champion; pointer có thể bị đẩy sai model nhưng API fail-closed; quy trình release phải dừng writer cũ và có test cutover |
| Snapshot correction/run hỏng | New revision/run nếu cần correction; không overwrite metric/run đã hoàn thành |
| S1a chưa phát hành/thiếu/lỗi | Shadow paired không chặn champion Accuracy; không backfill |
| S3 shadow object ghi muộn | Check LastModified/target cutoff; nếu unverified thì loại paired mask |
| S1a báo cáo | **Parquet `eval/shadow_eval/run_id=<run_id>/`**; writer riêng với input JSON `eval/shadow/s1a-l094/`; không API/DynamoDB |
| Validation/test lịch sử | Không lẫn rolling production, không backfill |

---

## 8. Ma trận quyết định v4.3 — review Khải/Tuấn, chốt tại họp 30/10

Các quyết định D01–D24 bên dưới là **đề xuất v4.3**, chưa phải contract đã merge. Các điểm điều chỉnh từ comment mới nhất của Khải/Tuấn: D10 nguồn `MODEL_VERSION`; D14/D15 evidence từ Forecasts, không CloudWatch; D19 `LATEST_COMPLETED` pointer; D20 không champion release operator; D23 S3 shadow_eval Parquet. **D16/D17 giữ nguyên** theo Tuấn và Khải.

| ID | Quy tắc / kiến trúc v4.3 | Review chính |
|---|---|---|
| D01 | 56 ngày UTC inclusive theo `base_date`, evaluation_start/end giữ ranh giới cửa sổ | Khải/Long |
| D02 | Chỉ forecast thật `created_at >= 2026-10-27T12:00Z`, có conditional immutability đã hiệu lực; không backfill | Khải/Tiến |
| D03 | Job hàng tuần sau clean snapshot, mỗi asset một evaluation run | Long/Tuấn |
| D04 | Forecasts `(PK=asset,SK=base_date)` conditional PutItem: sample→production, không overwrite production, retry kiểm payload | Khải/Tiến/Tuấn |
| D05 | `cpaws-<env>-accuracy` `PK/SK`: STATE (`ASSET#asset/STATE`) chỉ pointer, RUN partition cho META/METRIC; không GSI/Scan/TTL | Tuấn |
| D06 | Overall coverage chỉ hiện % khi `n_base_dates>=20` hợp lệ; vẫn trả counts | Khải/Tiến |
| D07 | `/accuracy/{asset}`: 4 metrics champion, overall + h1–7, HTTP 200 `not_ready` khi thiếu current completed run | Tuấn/Tiến/Long |
| D08 | `/forecast-history/{asset}` riêng, phase chart sau MVP | Tuấn/Tiến/Khải |
| D09 | History pairs on-demand từ Forecasts + clean snapshot, không bảng history detail riêng | Tuấn/Long |
| **D10** | Champion authoritative **`MODEL_VERSION` (CDK)**, đổi qua ADR/deploy; Predict không đọc Accuracy, STATE không lưu champion/generation; API so META model với runtime model | Khải/Tuấn/Tiến |
| D11 | Mỗi h chỉ X/Y, overall % theo ngưỡng 20 base_date | Khải/Tiến |
| D12 | Snapshot correction → revision/run mới; record cũ bất biến | Tuấn/Long |
| D13 | Validation 2019 tách phương pháp, không trộn rolling | Khải |
| **D14** | Calendar + TUE–SAT chỉ để đếm expected/missing; **Forecasts record `created_at` + PR #48 conditional writes** là issuance evidence cho cặp được chấm; **không manifest/logs bắt buộc** | Khải/Tuấn |
| **D15** | Missing Forecasts row chỉ đếm, không chấm; **không chặn COMPLETED**; CloudWatch/retention 90 ngày **ngoài MVP**; không báo schedule verified khi chưa audit | Khải/Tuấn |
| D16 | `prob_up` mismatch >`1e-6` chỉ log, không loại/overwrite | Khải/Tuấn/Long |
| D17 | External import provenance ngoài rolling MVP; không nới workflow khác | Khải/Tuấn |
| D18 | `created_at < 13:30 UTC` trên `target_date` và input-as-of; Forecasts mới có `input_snapshot_dt` | Khải/Tiến |
| **D19** | Run fingerprint bất biến, 28 metric items, `RUNNING→VALIDATING→COMPLETED`; `STATE` ba trường pointer là **`LATEST_COMPLETED`**, promote chỉ khi `latest_run_order` tăng hoặc same-run idempotent; không champion generation | Tuấn/Long |
| **D20** | IAM chỉ Rolling writer (Put/Update Accuracy, read sources, **write `eval/shadow_eval/*`**) và API reader (Get/Query); Predict không đọc Accuracy; **không champion release operator** | Tuấn/Tiến |
| D21 | Champion Forecasts + S1a JSON `eval/shadow/s1a-l094/dt=<UTC>/<asset>.json`, không retrain | Khải/Long/Tiến |
| D22 | Paired common mask, pinball_skill/coverage_80/width_80 mỗi model, không backfill shadow | Long/Khải |
| **D23** | Comparison **S3 Parquet** tại `eval/shadow_eval/run_id=<run_id>/`, immutable checksum; không DynamoDB/API, không ghi `eval/shadow/reports/` | Long/Tuấn/Khải |
| D24 | Shadow lỗi/thiếu không chặn champion `COMPLETED`; ADR mới đổi champion, không auto-switch | Khải/Long/Tuấn |

**Hiệu lực:** chỉ sau approve và PR contract tương ứng merge. Issue #23 mục 2 đóng sau khi điều chỉnh Walk-forward contract và PR contract được merge; RFC #45 review-only, không merge vào `developer`. Nếu cần bổ sung guard cross-version ở deployment, phải chốt trong PR implementation, không ngầm biến STATE thành champion registry.

---

## 9. Acceptance criteria và kế hoạch kiểm thử — điều kiện phê duyệt kiến trúc

### 9.1. Contract/invariants bắt buộc

- [ ] Evaluation `rolling_8w` có đúng khóa logic Accuracy Schema, 7 horizons, 28 METRIC items, overall trong META; validation/test vẫn S3 Parquet `eval/`.
- [ ] `STATE` **chỉ giữ** ba trường `latest_run_pk`, `latest_run_id`, `latest_run_order` = **`LATEST_COMPLETED`**; không `champion_model_version`, `champion_generation`, `effective_base_date` hay item LATEST riêng. `META.model_version` phải trùng `MODEL_VERSION` của API/CDK lúc trả.
- [ ] `Forecasts` production bất biến tại `(asset,base_date)` theo PR #48; record từ trước khi fix có hiệu lực không tự verified nếu thiếu bằng chứng tương đương. Không backfill forecast.
- [ ] `run_id`/fingerprint khóa asset, model config, snapshot, eligible records, cutoff và revision; retry cùng payload no-op; khác payload conflict; metric chỉ conditional PutItem, không overwrite, không BatchWriteItem.
- [ ] `COMPLETED` cần đủ 28 METRIC rows, correct counts, snapshot/cutoff và issuance evidence **của cặp được chấm**; **không yêu cầu** CloudWatch logs, publication manifest, 90-day retention hoặc mọi kỳ expected có row. `n_obs=0`/undefined hợp lệ nếu đầy đủ 28 rows.
- [ ] Expected count dùng calendar/TUE–SAT; thiếu Forecasts row chỉ tăng `missing_count` và không khẳng định skip/upstream, không chặn completion. `schedule_evidence_status=not_audited_mvp`, tách khỏi `issuance_evidence_status=verified_eligible_rows`.
- [ ] Champion từ `MODEL_VERSION` CDK/ADR; Predict không gọi `STATE`/Accuracy, API và Rolling dùng cùng cấu hình release, fail-closed nếu META version khác.
- [ ] API `/accuracy/{asset}` có 4 metrics, overall/by_horizon, `n_obs`,`n_base_dates`, 20 ngày chỉ là UI; `not_ready` đúng khi run hiện tại khác model/pointer thiếu.
- [ ] IAM chỉ Rolling writer cập nhật STATE pointer (không field champion); API reader chỉ GetItem/Query. Giới hạn bảng/prefix, ưu tiên PK/attributes IAM với các test quyền từ chối. Không champion release operator.
- [ ] Predict đọc/ghi source S1a tại `eval/shadow/s1a-l094/*` theo PR #49/#51; Rolling writer ghi **Parquet `eval/shadow_eval/*`**; quyền Predict `eval/shadow/*` không được ghi vào báo cáo so sánh, API không đọc report.
- [ ] Shadow trên paired mask, không tác động champion Accuracy/API và không auto-switch. Không SageMaker/Step Functions retrain.

### 9.2. Functional tests — 36 trường hợp (T01–T36)

| ID test | Điều kiện thử | Expected v4.3 |
|---|---|---|
| T01 | Key metric khác `run_id`, asset, model, sample, kind, window, cutoff, h hoặc metric | Không va chạm PK/SK và đủ logical key |
| T02 | GET accuracy 4 asset; run có 28 METRIC và Query nhiều page | GetItem STATE + Query RUN, không Scan/GSI, chỉ current MODEL_VERSION |
| T03 | Crash sau 27/28 METRIC | Chưa completed, không promote pointer, API không đọc partial |
| T04 | Retry đúng run fingerprint/metric | No-op / resume, không overwrite |
| T05 | Cùng PK/SK khác payload hoặc cùng run_order khác run_id | Conflict, giữ record gốc, pointer không tự đổi |
| T06 | Hai writers complete trái thứ tự, run_order B>A | Pointer monotonic trỏ B; không rollback |
| T07 | ADR/CDK đổi MODEL_VERSION trong khi run cũ tồn tại | STATE không đổi champion, API so META.model_version với runtime MODEL_VERSION, mismatch→not_ready; không trộn đời |
| T08 | Run đủ 28 rows nhưng không có cặp có nhãn hợp lệ | COMPLETED được phép với 28 undefined + reasons, counts đúng; display không giả % |
| T09 | Thiếu metric row hoặc hash/count không nhất quán | Không COMPLETED hoặc promote |
| T10 | Lịch có ngày expected nhưng Forecasts không có row | missing_count tăng, bỏ qua ngày; **không** block COMPLETED vì thiếu record |
| T11 | Record Forecasts hợp lệ nhưng không đọc được CloudWatch logs | Vẫn chấm theo record + conditional immutability, không đòi log |
| T12 | Lịch 56 ngày có logs thiếu/hết hạn 30 ngày | `schedule_evidence_status=not_audited_mvp`; 28 rows đủ và cặp có evidence → COMPLETED |
| T13 | Record trước 27/10 12Z, sample, hoặc historical backfill | Không được chấm |
| T14 | h=1 phát hành cùng target date 12:15Z, >13:30Z, DST | So timestamp, kiểm input-as-of |
| T15 | input_snapshot_dt sai/missing cho record theo contract mới | Record ineligible với reason; không tự backfill, không bắt cả run fail nếu còn các record hợp lệ |
| T16 | `prob_up` sai lệch 0, 1e-6, >1e-6 | >ngưỡng chỉ log, không sửa/loại một mình |
| T17 | Endpoint invalid/missing; intermediate missing | Theo ADR-0008, không fill endpoint; thiếu giữa không tự invalid |
| T18 | Coverage overall, 0/19/20 base dates, nhiều horizons cùng base date | Pool hit/count, UX ẩn/hiện đúng |
| T19 | Sign zero-mask khác up_rate; width log return | Metric n_obs riêng, đúng đơn vị, không h=0 |
| T20 | IAM: API ghi/scan Accuracy; Predict đọc Accuracy; writer PutObject vào eval/shadow/*; writer sửa ngoài pointer fields | AccessDenied / no permissions; IAM statements scoped đúng |
| T21 | API đang Query thì pointer đổi hoặc MODEL_VERSION không khớp | Check lại STATE, fail-closed, không trả champion cũ |
| T22 | Snapshot correction cùng ngày, revision mới | New run_id/order, old run immutable; chỉ newer eligible promote |
| T23 | Historical Validation/test, external import | Không lẫn rolling; không sửa Parquet lịch sử |
| T24 | Retention CloudWatch vẫn 30 ngày | **Không là blocker**; job không gọi logs API và không cần guard retention 90 ngày |
| T25 | Shadow JSON `dt=<UTC>` khác base_date, các assets | Đọc đúng key theo lịch chạy, ghép từ base_date trong JSON |
| T26 | Champion 10 eligible pairs, S1a 7 chung | Champion n_obs 10, paired n_obs mỗi model 7 trên common mask |
| T27 | Shadow missing, invalid_k, failure | Không chặn champion COMPLETED/API |
| T28 | Shadow created_at giống champion nhưng S3 LastModified sau cutoff | Loại khỏi paired mask, không cần CloudWatch làm gate |
| T29 | Shadow chưa deploy, đề nghị backfill từ historical | Không backfill; shadow_not_ready độc lập champion |
| T30 | pinball_skill, coverage, width hai model trên common mask, PL baseline=0 | Cùng denominator/mask; undefined reason, không NaN |
| T31 | Retry Parquet shadow report cùng key/payload và khác payload | `IfNoneMatch=*`, checksum confirm same no-op, different conflict; verify Parquet round-trip/schema |
| T32 | API Accuracy khi S1a tốt hơn hoặc thiếu shadow | Chỉ current champion, không S1a/pinball shadow, không auto-switch |
| T33 | Predict PutObject vào `eval/shadow/*`, Rolling PutObject vào `eval/shadow_eval/*`, gọi ngược | Chính sách S3 tách prefix; truy cập trái role/prefix AccessDenied |
| T34 | Shadow deploy sau champion MVP 05/11 | Champion Accuracy vẫn đủ điều kiện, paired chỉ sau khi S1a thật có nhãn |
| T35 | Forecasts đã có production tại đúng `(asset,base_date)` | Không overwrite bởi sample/production/retry; same retry GetItem+fingerprint no-op, khác conflict |
| T36 | Forecasts có sample trước, production replace rồi retry | Replace sample một lần, production immutable, retry đúng không alarm giả |

### 9.3. Nghiệm thu MVP 05/11

- API `/accuracy/{asset}` chỉ đọc completed run `META.model_version==MODEL_VERSION` hiện deploy, có 28 METRIC, dữ liệu forecast thực hợp lệ; trạng thái `not_ready` hợp lệ nếu chưa có completed run hiện hành, không bịa forecast.
- `COMPLETED` không đòi `n_base_dates>=20`/`n_obs>0`, không phụ thuộc logs/manifest/90-day retention. Đủ 28 METRIC, snapshot/eligible pairs đúng, `n_obs`/counts nhất quán; ngày expected thiếu row được đếm riêng, không chấm.
- `STATE` chỉ pointer ba trường `LATEST_COMPLETED`; IAM writer scoped cho pointer, API chỉ đọc; champion authoritative = CDK `MODEL_VERSION`, đổi bằng ADR.
- S1a shadow xuất **S3 Parquet `eval/shadow_eval/run_id=<run_id>/`** trên paired mask và không chặn champion. Predict có thể ghi `eval/shadow/*` nhưng không ghi report.
- PR implementation chứng minh T01–T36 (test nhóm shadow T25–T34 theo lịch S1a và Predict T35–T36 ở PR #48); IAM deny tests, correct payload/hash và không có giả lập dữ liệu production.
- Không backfill 2020–2026, không retrain hoặc sửa Validation 2019/ADR-0008.

## 10. Phân công, mốc thời gian và cách cập nhật contract

| Mốc | Đầu ra | Chủ trì / review |
|---|---|---|
| **28–29/10/2026** | RFC v4.3 sửa 3 điểm Khải và 2 điểm Tuấn, đồng bộ shadow Parquet | Long; Khải/Tuấn/Tiến |
| **30/10/2026** | Họp chốt D01–D24, nhất là D05/D10/D14/D15/D19/D20/D23 và IAM pointer | Khải + nhóm |
| **Sau họp/duyệt** | PR `docs/api/contract.md` và `docs/eval/walk-forward-contract.md` mục 7; `input_snapshot_dt`, evidence Forecasts+conditional writes, không yêu cầu log/manifest; giữ logical schema cũ | Long, Tuấn/Khải review |
| **05/11/2026** | Champion MVP: `rolling_8w` + Accuracy STATE/META/METRIC + `/accuracy/{asset}`; không chặn bởi shadow/CloudWatch | Long; Tuấn (API/IAM), Tiến (Web), Khải (predict) |
| **02–06/11/2026 (kế hoạch PR #49)** | S1a source JSON trong `eval/shadow/s1a-l094/` cùng predict; triển khai provenance và IAM source theo PR #49/#51 | Khải/Tiến/Tuấn |
| **Sau khi S1a có cặp trưởng thành** | Paired S1a/champion report Parquet tại `eval/shadow_eval/run_id=<run_id>/`; không public | Long; Khải/Tuấn review |
| **15/11/2026 (dự kiến)** | Biểu đồ lịch sử forecast–actual, giai đoạn sau | Long + Tiến |
| **22/11/2026** | Đóng băng tính năng | Nhóm |

**Quy trình:** RFC v4.3 → review/approve → PR contract → implementation/tests/deploy. **PR #45 review-only, không merge**; sau khi contract được merge, đóng PR #45 ở trạng thái Closed–Not Merged, giải quyết Issue #23 theo thỏa thuận nhóm. Không tự cập nhật code production trong PR RFC.

**File RFC trên branch PR #45:** `docs/proposal/rolling-accuracy-design.md` (không phải `docs/proposals/`).

### Phần cần đưa vào contract sau khi nhóm duyệt

1. Cửa sổ rolling, mốc `created_at`, `target_date` cutoff, `MODEL_VERSION`/ADR champion, `input_snapshot_dt` và eligible record policy.
2. `docs/eval/walk-forward-contract.md` mục 7: **ngoại lệ rolling_8w MVP** không manifest/CloudWatch, expected chỉ để đếm, completion chỉ căn cứ Forecasts+conditional write và record eligibility; không mở rộng cho validation/test/import.
3. `GET /accuracy/{asset}` JSON: 4 metrics, n_obs, n_base_dates, status/display_status, `not_ready`/`collecting`/`ready`; evidence metadata phải không tự gọi schedule verified.
4. `STATE` (`LATEST_COMPLETED`) ba pointer, `META/METRIC`, run_id/order, 28 metrics, immutable writes, completion/promotion, API compare runtime `MODEL_VERSION`.
5. IAM: Rolling writer update STATE pointer, API chỉ GetItem/Query, Predict không đọc Accuracy; tách S3 shadow input `eval/shadow/*` với paired output Parquet `eval/shadow_eval/*`; không champion release operator.
6. `prob_up` tolerance D16, import ngoài MVP D17, không backfill, ADR-0011 shadow paired, pinball/coverage/width report internal.
7. `/forecast-history/{asset}` chỉ là giai đoạn sau, không blocker Accuracy MVP.

---

## Phụ lục A — Đối chiếu source code

- Theo review Khải, tài liệu ở GitHub dẫn commit **`a5f770c`** thay vì tên ZIP source. Khi chuyển sang contract, đối chiếu commit thực tế với nhánh đang deploy.
- `docs/api/contract.md`: `/accuracy/{asset}` chưa có JSON chính thức trong snapshot được review.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, `target_cutoff_date`, common mask và status.
- `docs/eval/walk-forward-contract.md`: hiện yêu cầu publication manifest; **v4.3** dùng Forecasts+conditional immutable write để xác minh **các cặp được chấm**, calendar/TUE–SAT chỉ đếm expected/missing; sửa mục 7 qua PR contract riêng, không bắt buộc CloudWatch hoặc 90-day retention MVP.
- `src/forecast/predict.py`: snapshot đã dùng khi review chưa bảo đảm conditional write; PR #48 bảo vệ bản production bằng conditional PutItem và thêm `input_snapshot_dt` theo contract; `MODEL_VERSION` từ CDK, **Predict không truy cập STATE**.
- `src/eval/metrics.py`: có helper metrics; chưa có orchestration rolling hoàn chỉnh theo RFC.
- **PR #49** `docs/experiments/s1a-shadow-plan.md`: kế hoạch `src/forecast/vol_scale_core.py`, S1a input JSON `eval/shadow/s1a-l094/` và báo cáo paired shadow **Parquet `eval/shadow_eval/`**; PR #51 cấp quyền predict cho `eval/shadow/*` nên output phải nằm ngoài prefix đó. Tình trạng deploy cần xác minh riêng.
- **PR #46** ADR-0011: bỏ Step Functions/SageMaker retrain trước bảo vệ; bổ sung paired shadow weekly. ADR-0005 cũng chọn hiển thị (b), chỉ return %/xác suất cho vàng/bạc; **RFC Accuracy vẫn đo trên log return** và không dùng giá vàng/bạc quy đổi để tính nhãn.
- `infra/lambda/forecast_api/handler.py`: chưa hỗ trợ `/accuracy/{asset}` trong snapshot được review.

Các trạng thái code là từ snapshot đã dùng để soạn RFC, không xác nhận deployment AWS đang chạy.

## Phụ lục B — Tài liệu tham khảo

1. *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (chèn liên kết nội bộ chính thức khi được cung cấp).
2. [Issue #23 — Walk-forward phase 2](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).
3. `docs/adr/0008-target-quantiles-evaluation.md`, `docs/adr/0009-ceemdan-dlinear-k3-result.md`, `docs/adr/0010-k3b-volatility-scaling-result.md`, **[PR #46 — ADR-0011, ADR-0005](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/46)**, **[PR #49 — S1a shadow plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/49)**, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`.
4. [DynamoDB PutItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html), [BatchWriteItem không hỗ trợ conditional expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_ConditionalBatchUpdate.html), [DynamoDB strong reads](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html), [IAM DynamoDB LeadingKeys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/specifying-conditions.html).
5. Dawid (1984), *The Prequential Approach*, DOI: https://doi.org/10.2307/2981683.
6. Gneiting et al. (2007), *Probabilistic Forecasts, Calibration and Sharpness*, DOI: https://doi.org/10.1111/j.1467-9868.2007.00587.x.

> **Trạng thái cuối:** RFC v4.3 đã cập nhật các phản hồi mới nhất của Khải và Tuấn cùng định dạng S3 Parquet của PR #49. Đây vẫn là **đề xuất chờ chốt tại họp 30/10**, không phải contract chính thức. PR #45 **review-only, không merge**; chỉ PR contract được duyệt và merge mới là chuẩn triển khai.
