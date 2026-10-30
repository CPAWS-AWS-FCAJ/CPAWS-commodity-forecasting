# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** **RFC v4.5 — FINAL PROPOSED DESIGN để nhóm chốt ngày 30/10/2026**; chưa có hiệu lực contract trước khi Khải, Tuấn, Tiến thống nhất và PR contract được merge.  
> **Ngày cập nhật:** 2026-10-30 (v4.5: giữ nguyên kiến trúc v4.3 được Khải xác nhận, hợp nhất v4.4 và comment cuối của Khải: chính sách legacy 27/10, champion theo asset để hỗ trợ K4, tiêu chí 20 ngày có nhãn và owner/Scheduler; các quyết định chưa xác nhận được đánh dấu *chờ chốt*).  
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

**Chính sách MVP trình chốt 30/10:** cửa sổ 56 ngày UTC theo `base_date`; `created_at >= 2026-10-27T12:00:00Z`; forecast sau cutover PR #48 phải có conditional-write provenance và `input_snapshot_dt`. **Khải đề xuất chấp nhận legacy theo lượt chạy có lịch** trước cutover, miễn `input_snapshot_dt` nếu được kiểm tra/duyệt ở từng record; đây là *LEGACY_ACCEPT_WITH_EVIDENCE*, không phải chấp nhận mọi timestamp trong khung giờ. Nếu chưa duyệt hoặc thiếu bằng chứng, fallback *POST_CUTOVER_ONLY*. Không backfill. Calendar + TUE–SAT chỉ đếm expected/missing; không có CloudWatch/manifest gate với `COMPLETED`. **Champion authoritative là `MODEL_VERSIONS[asset]` trong CDK (mapping bốn tài sản, hiện đều baseline-q252)**, không phải `STATE`; thay đổi từng tài sản bằng ADR/deploy, theo mốc hiệu lực. `STATE` chỉ là con trỏ `LATEST_COMPLETED`. `prob_up` lệch >`1e-6` chỉ log; Dashboard hiển thị 4 metrics với ngưỡng 20 `base_date` **đã có nhãn hợp lệ**, không phải 20 phiên lịch. Khải nhận thêm `input_snapshot_dt` cho champion ở PR #48; PR #53 đã có trường này cho shadow. Shadow JSON vào `eval/shadow/`, paired report **Parquet `eval/shadow_eval/`**, không public API.

**Cập nhật bằng chứng 29/10 (Tiến):** kiểm tra `cpaws-dev-forecasts` trên cả 4 tài sản cho thấy `base_date=2026-10-26` có `created_at=2026-10-27T12:15:31Z` và `base_date=2026-10-27` có `created_at=2026-10-28T12:16:03Z`, cùng `model_version=baseline-q252`, `is_sample=false`. Theo Tiến, đây là hai lượt chạy theo lịch, không có lần chạy tay hay ghi đè được phát hiện. Điều này **ủng hộ `LEGACY_ACCEPT_WITH_EVIDENCE`**, nhưng timestamp đơn lẻ không chứng minh tuyệt đối tính bất biến trước PR #48; chấp nhận từng record legacy và miễn `input_snapshot_dt` vẫn chờ nhóm phê duyệt 30/10.

**Kiến trúc đề xuất v4.5:** một bảng `cpaws-<env>-accuracy`, item `STATE` theo asset **chỉ giữ** `latest_run_pk`/`latest_run_id`/`latest_run_order` (gọi chung là **`LATEST_COMPLETED`**); partition `RUN#asset#model#run_id` chứa `META` và 28 item `METRIC`; **không GSI, không Scan**. Champion lấy từ **`MODEL_VERSIONS[asset]` do CDK triển khai**, thay đổi theo tài sản bằng ADR/deploy, **không lưu champion hoặc generation trong `STATE`**. Writer ghi `METRIC` bất biến bằng conditional `PutItem`, chỉ promote pointer sau khi run đủ 28 metrics, snapshot/forecast eligibility hợp lệ; **không** phụ thuộc đầy đủ nhật ký lịch phát hành. IAM chỉ tách Rolling writer và API reader cho bảng Accuracy; Predict không đọc Accuracy; không có champion release operator MVP. Shadow đọc JSON tại `eval/shadow/s1a-l094/`, tính paired mask và lưu **Parquet nội bộ `eval/shadow_eval/run_id=<run_id>/`**. Các quyết định mới chỉ thành contract sau PR contract riêng được merge.

---

## 1. Mục tiêu và tiêu chí thành công

### 1.1. Bài toán

`baseline-q252` tạo phân phối dự báo bằng 7 phân vị cho từng `h=1..7`. Dashboard đã có thể hiển thị q10–q90 và `prob_up`, nhưng cần dữ liệu thực tế để người dùng xem: (a) nhãn có nằm trong khoảng dự báo không, (b) khoảng rộng bao nhiêu, (c) dự báo hướng có giá trị tham khảo thế nào so với tỷ lệ tăng thực tế.

### 1.2. Mục tiêu MVP

- Chấm forecast production đủ điều kiện **trước khi nhãn tương lai được biết**, dựa trên bản ghi `Forecasts` và cơ chế conditional immutability đã triển khai; truy vết model, target series và snapshot input nếu có, không coi `created_at` một mình chứng minh không leakage.
- Tính `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`, `n_obs` theo mỗi h và tổng hợp hợp lệ cho Dashboard.
- Phân biệt `status` tính toán trong Accuracy với `display_status` tại API; khi chưa đủ dữ liệu thì hiển thị số lần đo và trạng thái thay vì suy diễn tỷ lệ.
- Phân biệt lịch phát hành **dự kiến** (đếm theo calendar/schedule), bản ghi `Forecasts` **thực có** và các cặp có nhãn đủ điều kiện; ngày không có row chỉ đếm missing, không yêu cầu xác minh skip reason/log trong MVP.
- API chỉ sử dụng run **`COMPLETED` của `MODEL_VERSIONS[asset]` hiện đang deploy**, không trả kết quả của đời model cũ khi đổi champion; `LATEST_COMPLETED` chỉ là con trỏ run. Shadow evaluation không tác động pointer/API và không tự động đổi champion.

### 1.3. Ngoài phạm vi

- Không đánh giá lợi nhuận, không đưa MAPE/RMSE trên mức giá vào Accuracy Schema.
- **Không xây Step Functions/SageMaker AI Training Job/Model Registry trước bảo vệ** theo ADR-0011; không retrain K3/K3b/K4 trong RFC này hoặc thay logic DM-HAC; đổi champion chỉ sau ADR riêng. S1a là nhánh shadow với tham số đã chốt, không huấn luyện hoặc tinh chỉnh mới.
- Không backfill forecast lịch sử từ test 2020–2026, không sửa Validation 2019 hay ghi đè Parquet cũ.
- RFC này không triển khai Lambda, IAM, CDK, DynamoDB hoặc deploy AWS.

---

## 2. Nguồn dữ liệu, khóa ghép và tính toàn vẹn

### 2.1. Nguồn hiện có trong code

| Nguồn | Cấu trúc / vai trò |
|---|---|
| DynamoDB `Forecasts` | PK=`asset`, SK=`base_date`; `created_at`, `model_version`, `target_series`, `horizons[].{h,target_date,q,prob_up}`, `is_sample`; **dự kiến bổ sung** `input_snapshot_dt` cho champion trong PR #48 (Khải nhận làm, cần kiểm code/deploy) |
| S3 clean snapshot | `clean/prices/dt=YYYY-MM-DD/prices.parquet`, `rejected.parquet`, `quality.json` |
| **S3 S1a shadow (ADR-0011/PR #49)** | `eval/shadow/s1a-l094/dt=<ngày chạy UTC>/<asset>.json`, cấu trúc như Forecasts + `shadow` metadata; **không** ghi vào bảng `Forecasts` |
| `src/data/calendars.py`, `src/forecast/returns.py` | Lịch NYSE/CME và log return theo h phiên |
| `src/forecast/predict.py`, Lambda predict | Sinh Forecasts với `MODEL_VERSIONS[asset]` (CDK), ghi bằng conditional PutItem theo PR #48, kèm `created_at`; champion `input_snapshot_dt` là thay đổi Khải cam kết thêm trong PR #48, chưa có trong bản review; log chỉ để chẩn đoán, không là nguồn chặn `COMPLETED` MVP |
| `src/eval/metrics.py` | Các hàm đánh giá theo Accuracy Schema |

**Target:** `gold → GLD`, `silver → SLV`, `brent → BZ=F`, `wti → CL=F`. `horizons[].q` là **log return**, không phải giá. `last_price` quy đổi để hiển thị vàng/bạc **không** được dùng thay close GLD/SLV để tính nhãn.

### 2.2. Ghép forecast–nhãn

Mỗi cặp đánh giá dựa trên `(asset, base_date, h, model_version)` và `target_date` lưu trong forecast, được xác nhận theo calendar riêng tài sản:

`y(t,h) = ln(P_target(target_date) / P_target(base_date))`

- Hai endpoint phải hợp lệ theo ADR-0008; giá không dương (bao gồm trường hợp WTI bất thường) không được dùng trong log return không xác định.
- Thiếu phiên **ở giữa hai endpoint** không tự làm target vô hiệu nếu hai endpoint hợp lệ; ghi số phiên thiếu.
- `target_date` phải là phiên thứ `h` sau `base_date`, đã có giá hợp lệ tại lúc job chạy và `target_date <= target_cutoff_date` riêng từng asset.
- Metric cần baseline tuân theo common mask và điều kiện mẫu của Accuracy Schema; không tự thay đổi mask.

### 2.3. Forecast đủ điều kiện đánh giá [D02/D10/D18 — legacy là quyết định chờ chốt]

1. `is_sample=false`, asset/target/horizon hợp lệ; mỗi horizon đủ 7 phân vị hữu hạn, có thứ tự và `prob_up` trong miền cho phép. `model_version` phải khớp **`MODEL_VERSIONS[asset]`** đang có hiệu lực cho asset/base_date; không trộn model giữa các tài sản hoặc các đời champion của cùng asset.
2. `created_at` UTC **`>= 2026-10-27T12:00:00Z`**. Không buộc `base_date>=27/10`, vì lượt phát hành đầu 27/10 có thể có `base_date=26/10`. Loại mọi sample và record trước mốc dù `is_sample=false`.
3. `created_at < target_date T13:30:00Z` ở từng h, so UTC timestamp; xác nhận target h phiên, dữ liệu input chỉ đến `base_date`, `publication_as_of` và target endpoint/cutoff riêng asset. **Timestamp không tự chứng minh không leakage.**
4. **Record từ cutover PR #48 trở đi:** Forecasts production phải được ghi bằng conditional `PutItem` và mang `input_snapshot_dt=YYYY-MM-DD` lấy từ `snap.dt` của clean snapshot đã thực sự dùng; trường này phải được validate với snapshot/input-as-of, không chỉ kiểm chuỗi. Khải phụ trách code champion và Forecasts contract trong PR #48; **cutover là thời điểm triển khai thực tế có xác nhận**, không lấy ngày dự kiến 31/10 thay thế. Việc PR được approve/merge không tự chứng minh Lambda đã deploy.
5. **Record trước cutover — đề xuất chốt `LEGACY_ACCEPT_WITH_EVIDENCE`:** chỉ chấp nhận từng `(asset, base_date, model_version, created_at)` được Khải/Tiến kiểm chứng là lượt chạy lịch **12:15–13:30 UTC**, không chạy tay, không ghi đè/reissue, có cơ sở xác nhận input-as-of; được nhóm duyệt rõ ràng. **Miễn `input_snapshot_dt` chỉ cho những legacy được duyệt**; không bịa trường snapshot hoặc gắn nhãn `immutable_verified` như record sau PR #48. Danh sách/chứng cứ record được chấp nhận phải có tham chiếu có thể kiểm toán và fingerprint trong `META`/run provenance (không xây bảng manifest riêng). Khi bằng chứng không đủ, đánh dấu `legacy_unverified` và không chấm.
6. **Fallback `POST_CUTOVER_ONLY`:** nếu nhóm chưa phê duyệt ngoại lệ legacy ở cuộc họp 30/10, hoặc một record legacy không vượt checklist, chỉ chấm từ những record sau cutover đạt điểm 4. Không thay đổi dữ liệu phát hành cũ hoặc backfill. `first_eligible_base_date` là ngày gốc **có ít nhất một cặp thực sự được chấm**, không hardcode ngày 27/10.
7. Theo ADR/release, khi champion của một asset đổi thì job chỉ chấm forecast của **model mới từ `champion_effective_base_date[asset]`** (ngày hiệu lực ghi trong release/ADR), 56 ngày window vẫn giữ nguyên; asset khác không bị reset. Challenger S1a được xét riêng mục 3.5.

**Checklist phê duyệt legacy trước khi tính `n_obs`:** phạm vi các asset/base_date, `created_at` và lịch, bằng chứng không có manual/rewrite đã kiểm, nguồn kiểm `publication_as_of`/input-as-of, người xác nhận, thời điểm phê duyệt và fingerprint/run reference. Đây là *ngoại lệ nghiên cứu/vận hành có kiểm soát*, không được suy ngầm từ việc nhìn thấy timestamp đúng lịch. Không cần tái dựng CloudWatch 56 ngày để complete một run MVP.

#### Bằng chứng cập nhật — Kiểm tra Forecasts ngày 29/10/2026 (Tiến)

Tiến báo cáo kiểm tra bảng `cpaws-dev-forecasts` lúc **15:30 ngày 29/10**; cả **4 tài sản** có cùng giá trị `created_at` cho từng `base_date` dưới đây (timestamp trong bảng là **UTC**):

| `base_date` | `created_at` (UTC) | `is_sample` | `model_version` | Đánh giá theo RFC |
|---|---|---|---|---|
| `2026-10-16` | `2026-10-21T14:01:43Z` | `true` | `sample` | **Loại**: sample và trước D02 |
| `2026-10-23` | `2026-10-25T09:29:08Z` | `false` | `baseline-q252` | **Loại**: phát hành trước `2026-10-27T12:00:00Z` (lần thử deploy) |
| `2026-10-26` | `2026-10-27T12:15:31Z` | `false` | `baseline-q252` | **Ứng viên theo `LEGACY_ACCEPT_WITH_EVIDENCE`**: nằm trong khung 12:15–13:30 UTC |
| `2026-10-27` | `2026-10-28T12:16:03Z` | `false` | `baseline-q252` | **Ứng viên theo `LEGACY_ACCEPT_WITH_EVIDENCE`**: nằm trong khung 12:15–13:30 UTC |

Theo xác nhận của Tiến, hai lượt `base_date=26/10` và `27/10` được tạo theo lịch, mỗi lượt cả 4 tài sản cùng timestamp và **không phát hiện chạy tay/ghi đè**. Đây là bằng chứng vận hành ban đầu ủng hộ đề xuất của Khải; **không tự thay thế bằng chứng độc lập về lịch sử sửa bản ghi hoặc input-as-of** khi cơ chế conditional write của PR #48 chưa deploy. Các dòng ứng viên chỉ được tính vào `n_obs` sau khi nhóm **phê duyệt `LEGACY_ACCEPT_WITH_EVIDENCE`**, hoàn tất checklist tại §2.3 và nhãn thực tế hợp lệ theo từng `h`/asset. Không gán `verified` chỉ vì timestamp nằm trong khung giờ.

**Theo dõi:** Tiến sẽ kiểm tra tiếp lượt phát hành cho `base_date=2026-10-28` sau 19:15 ngày 29/10 (giờ Việt Nam) và kiểm tra lại trước cutover/deploy PR #48 dự kiến 31/10. Chỉ cập nhật kết luận khi có kết quả thực tế; không xem các lượt chưa kiểm là đã xác minh.

**Điểm phải chốt 30/10:** Khải đề xuất nhận legacy theo `LEGACY_ACCEPT_WITH_EVIDENCE` trên cơ sở Tiến kiểm tra ngày 29/10; **chưa phải nhóm đã phê duyệt**. Fallback `POST_CUTOVER_ONLY` dùng cho record không được duyệt/không đủ evidence. Trong comment cuối Khải gọi đề xuất nhận legacy là “phương án B”, còn RFC v4.4 từng gọi cùng nội dung là “phương án A”; từ v4.5 **bỏ ký hiệu A/B** để tránh chốt nhầm. `first_eligible_base_date` xuất phát từ record/horizon đủ điều kiện, có thể `null`. Theo Khải, **20/11** là mốc đạt 20 base_date *theo lịch* nếu chấp nhận legacy, **27/11** là dự kiến nếu chỉ sau cutover 31/10; **không phải ngày Dashboard chắc chắn `ready`** vì còn target maturity, cutoff, lần chạy job và dữ liệu thực tế. Không tự nâng evidence của legacy thành bằng chứng bất biến tuyệt đối.

### 2.4. Bảo vệ bản forecast đã phát hành [D04 — đồng bộ PR #48]

Theo PR #48, Predict dùng conditional `PutItem` ngay trên **PK=`asset`, SK=`base_date`** của bảng `Forecasts`, không mở bảng issuance riêng:

```python
ConditionExpression = "attribute_not_exists(asset) OR is_sample = :true"
# ExpressionAttributeValues={":true": True}
```

- Chưa có item thì ghi; item sample cũ có thể được thay bằng production; **production tồn tại thì bất biến** trước production mới, sample và retry.
- `ConditionalCheckFailedException`: **không `GetItem`, không so payload**, không yêu cầu quyền `dynamodb:GetItem` bổ sung cho Predict. Ghi `PREDICT_ALREADY_PUBLISHED`, giữ nguyên record cũ và xem đây là trạng thái **đã phát hành**, không phải một lần ghi thành công mới; không bật alarm lỗi giả khi chạy lại hợp lệ (kể cả cùng `base_date` do nghỉ lễ Mỹ hoặc rerun sau `INGEST_STALE`). Những lỗi ghi khác vẫn phải báo lỗi và retry theo chính sách riêng.
- Đổi champion `MODEL_VERSIONS[asset]` chỉ áp dụng từ `base_date` phiên kế tiếp **của asset đó**, không thay production đã công bố.
- PR #48 bảo vệ record **sau khi deploy**, không hồi tố chứng minh tính bất biến của record từ 27/10. Ngoại lệ legacy (nếu duyệt) thuộc mục 2.3, không được coi là hậu quả tự động của conditional write.

**Không nhầm lẫn với Accuracy METRIC:** `METRIC` của Rolling vẫn dùng conditional PutItem + read/compare fingerprint khi có collision theo mục 4.2. Chỉ **Predict Forecasts** không đọc/so payload sau conditional failure.

### 2.5. Issue #23.2 — Lịch kỳ vọng và bằng chứng phát hành tối thiểu [MVP theo review Khải — D14/D15]

**Quyết định MVP thay thế đề xuất v4.2:** **không tạo bảng manifest**, **không đọc CloudWatch ingest/predict logs** trong Rolling job, và **không yêu cầu log retention 90 ngày**. Mục tiêu 05/11 là chấm chính xác những forecast **thực có** và hợp lệ, không điều tra nguyên nhân của mọi kỳ thiếu.

1. **Expected count (thống kê vận hành):** suy từ trading calendar riêng từng asset, lịch chạy TUE–SAT và các ngoại lệ đã biết, từ kỳ 26/10/2026. Đây là mẫu đếm `expected_count`/`missing_count`, **không** là bằng chứng rằng Lambda thật sự chạy hoặc đã phát hành.
2. **Published/eligible count:** query bản ghi `Forecasts` theo `(asset,base_date)`; chỉ chấm record `is_sample=false`, model trùng `MODEL_VERSIONS[asset]` deploy và ngày hiệu lực tương ứng, `created_at` hợp lệ, có bảo vệ conditional write **hoặc legacy được duyệt theo `LEGACY_ACCEPT_WITH_EVIDENCE`**. Mốc `created_at` và tính bất biến record (hoặc evidence legacy riêng được chốt) là **bằng chứng phát hành tối thiểu cho từng cặp** theo quyết định MVP, không cần kèm log `PREDICT_DONE`/ingest.
3. **Missing:** kỳ expected không có row → tăng `missing_count`, **không chấm**, không giả tạo dự báo, **không** gọi chắc chắn `upstream_failure`, `invalid_input_window` hay `no_forecast_row` có nguyên nhân đã xác minh. Nếu có log có thể kiểm toán riêng sau MVP nhưng không dùng làm điều kiện `COMPLETED`.
4. **Quality/causality:** vẫn kiểm `target_date` đúng h phiên, actual endpoint hợp lệ, `target_cutoff_date`, input-as-of/`input_snapshot_dt` theo mức record có thể xác minh. `created_at` **không tự chứng minh** mô hình không nhìn trước; phải giữ safeguard ở Predict và không dùng record phát hành trước cutover PR #48 nếu không được xác minh riêng theo mục 2.3.

**Tách hai loại evidence:** `issuance_evidence_status` của các **cặp đã chấm** phải `verified_eligible_rows` (Forecasts + conditional-write provenance hoặc legacy verification được nhóm phê duyệt); `schedule_evidence_status` chỉ mô tả mức audit lịch kỳ vọng (`not_audited_mvp` khi không tra logs), **không là điều kiện completion**. `publication_completeness` chỉ là tỷ lệ/counters dự kiến–thực có, không đại diện cho tính hợp lệ của `n_obs`. Nếu `expected_count=0` hoặc có ngày thiếu row, job vẫn có thể `COMPLETED` với 28 metric rows (kể cả `undefined` nếu không có cặp), miễn mọi **cặp được tính** hợp lệ và snapshot evaluation nhất quán. Không dùng giá trị `verified` cho lịch phát hành khi không có chứng cứ log.

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

Ví dụ job **05/11/2026**: cửa sổ lý thuyết là **11/09–05/11/2026**; `first_eligible_base_date` được suy từ forecast **thật sự được chấm**, có thể là `26/10` nếu legacy được xác minh/duyệt, hoặc muộn hơn sau PR #48. Web hiển thị **“Kể từ <first_eligible_base_date>”**, tuyệt đối không hardcode 27/10; khi chưa có eligible row, trả `null` và không tạo mốc giả.

### 3.2. Luồng job `rolling_8w`

1. Khóa clean price snapshot/quality; xác định `target_cutoff_date` theo asset. Nhận cấu hình **`MODEL_VERSIONS[asset]`** từ một mapping authoritative trong `infra/app.py` CDK (Predict, Rolling và Accuracy API nhận **cùng mapping**); dùng `champion_effective_base_date[asset]` từ ADR/release để không trộn lịch sử khi đổi riêng một tài sản.
2. Dựng expected schedule từ trading calendar + TUE–SAT để **đếm** expected/missing, không gọi CloudWatch cho luồng MVP. Nếu nhóm duyệt `LEGACY_ACCEPT_WITH_EVIDENCE`, kiểm chứng **từng record** theo §2.3 trước khi nhận vào `n_obs`; không gọi tất cả legacy là verified chỉ vì `created_at` hợp lịch. Chỉ chọn bản ghi `Forecasts` production thực có, hợp lệ theo mục 2.3–2.5; không tạo forecast thay thế.
3. Ghép forecast với actual, tính đúng log return và 7 horizons; kiểm `created_at`, `is_sample`, model per-asset đang deploy, ngày hiệu lực theo asset, cutoff, `input_snapshot_dt` bắt buộc sau cutover, và bằng chứng conditional-write (hoặc legacy review được duyệt). **Đọc S1a từ S3 độc lập**, không dùng sự có mặt của S1a để quyết định champion eligibility.
4. Lưu counts expected/published/missing và lý do loại forecast/horizon quan sát được. Missing row không có log thì reason chỉ là `missing_record_unclassified`; không gán skip/upstream đã xác minh.
5. Kiểm shape 7 q và `prob_up` (mismatch >`1e-6` chỉ audit), calendar/valid endpoints; không sửa nguồn. Common mask theo Accuracy Schema; tính 4 metrics và `n_obs`, `n_base_dates` từng h/overall; tính `first_eligible_base_date` từ **base_date eligible đầu tiên** của model đang hiệu lực.
6. Ghi `METRIC` qua conditional PutItem, chốt `META` status/28 row hashes/`run_id`, snapshot/version, cutoff, `MODEL_VERSIONS[asset]` và effective date, eligible-pair evidence, counts và `undefined_reason` khi không có nhãn. Không yêu cầu log ref hay trạng thái full-schedule verified.
7. Chuyển `META` sang `COMPLETED` chỉ sau khi validation nội dung thành công. Sau đó conditional `UpdateItem` **`STATE`/`LATEST_COMPLETED`** theo `latest_run_order` tăng, tuyệt đối không công bố run dở.
8. **Nhánh ADR-0011:** chấm champion–S1a trên paired common mask và ghi **Parquet nội bộ `eval/shadow_eval/`** theo mục 4.6; shadow thiếu/lỗi không chặn champion `COMPLETED`, không cập nhật `STATE` và không xuất public API.

**Giới hạn rollout:** khi đổi champion qua ADR/CDK, cập nhật cấu hình API và rolling đồng bộ với predict; API chỉ trả run mà `META.model_version` trùng `MODEL_VERSIONS[asset]` hiện tại, nếu pointer cũ không phù hợp thì `not_ready`. Không phục hồi forecast lịch sử hoặc tính lại Validation 2019.

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

Ước tính cũ (05/11 có 7 base_date/28 cặp; 22/11 có 19 base_date) chỉ là phép đếm phụ thuộc chấp nhận legacy. Khải tính bằng lịch NYSE/CME: **20/11** có thể đạt 20 phiên/base_date trên lịch nếu nhận legacy, hoặc khoảng **27/11** nếu chỉ chấm sau deploy PR #48 dự kiến 31/10. **Không suy ra `ready` ngay ngày 20/11/27/11:** một `base_date` chỉ được đếm khi forecast đó đã được phát hành/duyệt, có ít nhất một horizon đã có target thực tế hợp lệ trước `target_cutoff_date` và **job tuần đã đánh giá**. Số 20 không là 20 quan sát thống kê độc lập; API trả `n_obs` và `n_base_dates` để diễn giải.

### 3.4. Champion **theo từng asset** trong CDK, đổi bằng ADR [D10]

**Nguồn champion authoritative cho MVP:** một **mapping** `MODEL_VERSIONS` trong `infra/app.py`, không phải một chuỗi chung cho cả dự án. Ví dụ cấu hình ban đầu (**minh họa, không phải quyết định đưa K4 lên production**):

```python
MODEL_VERSIONS = {
    "gold": "baseline-q252",
    "silver": "baseline-q252",
    "brent": "baseline-q252",
    "wti": "baseline-q252",
}
```

Predict, Rolling và Accuracy API phải nhận **cùng mapping và cùng release config**, có CDK test xác nhận từng asset và không thiếu asset. Với asset `a`, champion là `MODEL_VERSIONS[a]`; ADR/deploy có thể đổi **chỉ một asset** nếu K4 đạt ở asset đó, không kéo theo ba asset còn lại. Mốc `champion_effective_base_date[a]` được lưu trong ADR/release configuration và áp dụng từ phiên base_date đầu tiên có hiệu lực; không suy diễn từ Accuracy `STATE`. Trong giai đoạn tất cả cùng baseline, mapping có cùng giá trị nhưng contract vẫn dùng hình thức per-asset.

**Predict không đọc Accuracy**, không có `champion_release_operator` hoặc `champion_generation` trong `STATE`. Item `STATE` **chỉ** trỏ `LATEST_COMPLETED` (`latest_run_pk`, `latest_run_id`, `latest_run_order`). API cho `/accuracy/{asset}` chỉ đọc run `META.model_version == MODEL_VERSIONS[asset]` và `base_date >= champion_effective_base_date[asset]` đối với các cặp đã chấm của run. Nếu pointer còn trỏ run model cũ, **trả `not_ready`**, không công bố kết quả sai asset/model; job mới bắt đầu thống kê từ effective date của **asset đó**, không backfill model mới từ các forecast cũ. `evaluation_start/end` vẫn là cửa sổ 56 ngày, không tự co theo effective date.

**Đổi model và concurrent rollout:** `latest_run_order` ngăn rollback theo thời gian nhưng không tự giải quyết writer đời cũ chạy sau cùng với order mới hơn. Release phải đồng bộ CDK mapping ở Predict/Rolling/API, drain writer cũ theo asset trước khi publish mới, và kiểm thử fail-closed nếu các Lambda chưa đồng bộ. Condition của pointer phải bảo vệ chính run/order đã `COMPLETED`; không tuyên bố chỉ IAM/condition đủ làm release đồng bộ. Khi chuyển một asset, API ba asset còn lại vẫn có thể trả Accuracy của champion riêng mà không bị reset.

**Ranh giới S1a khi K4 được chọn:** `s1a-l094` theo ADR-0011/PR #49 là biến thể co giãn **phân vị `baseline-q252`**; nếu champion một asset chuyển sang K4, **không tự dùng K4 làm đầu vào nhưng vẫn gắn tên S1a**. Với asset đó, tạm không chấm paired S1a (`shadow_not_applicable_model_change`) hoặc phải có ADR/phiên bản challenger mới; nhánh champion Accuracy tiếp tục chạy độc lập. Các asset còn baseline vẫn có thể chấm S1a như cũ.

### 3.5. Chấm champion–challenger trên cùng tập quan sát [ADR-0011]

**Hai luồng tách biệt, chung lịch chạy:** (A) **Accuracy production** chấm *mọi* forecast champion đủ điều kiện theo mục 2–3 và ghi DynamoDB cho `/accuracy/{asset}`; (B) **shadow paired comparison** chỉ chấm phần giao champion–S1a cho báo cáo nội bộ. S1a không tham gia `STATE`, không cập nhật champion pointer, không ảnh hưởng ngưỡng 20 ngày của Dashboard. Khi ADR đổi champion tương lai được duyệt, phát hành production vẫn phải tuân theo contract Predict/Forecasts; không tự nâng bản shadow S3 thành forecast production.

**Khóa ghép chính xác:** một cặp có cùng `(asset, base_date, h, target_date, target_series)` và source/version/cutoff của nhãn; `model_version` khác là điều **mong muốn** (`baseline-q252` và `s1a-l094`). Chỉ chấm khi **cả hai** dự báo có provenance phát hành hợp lệ *trước nhãn*, mỗi bên đủ 7 phân vị, có actual log return hợp lệ và thỏa cùng `target_cutoff_date`/calendar. `paired_mask = champion_eligible & shadow_eligible & actual_valid & same_target_definition`; không nén hoặc thay thế những cặp còn thiếu shadow. `paired_n_obs` và số `base_date` ghép được ghi **riêng** với `n_obs` của Accuracy production.

**Metric tối thiểu của báo cáo shadow theo ADR-0011:** `pinball_skill`, `coverage_80`, `width_80` **cho cả hai model trên đúng paired mask**, tách h=1..7, kèm counts/coverage và tổng hợp có trọng số theo số cặp; `pinball_skill = 1 - PL(model) / PL(baseline-q252)` với PL (7 phân vị) tính **trên cùng paired mask**. Champion baseline đối chiếu với chính nó bằng 0 khi mẫu số dương; nếu không đủ cặp hoặc mẫu số bằng 0 → `undefined` có reason, không sinh NaN trong JSON. S1a giữ q50 của champion nên thống kê dựa trên dấu q50 (nếu có) là như nhau trên paired mask, nhưng **không** dùng điều đó thay cho kiểm tra thực tế. Không công bố shadow `pinball_skill` lên Dashboard.

**Thời điểm bắt đầu:** S1a chỉ được ghép từ lần phát hành S3 đầu tiên đã xác minh; cửa sổ thời gian chung `[max(window_start, first_verified_shadow_base_date), window_end]`, vẫn cần target đã trưởng thành. Đếm chính xác cặp chung thay vì lấy sẵn `overall` champion từ DynamoDB (vì hai mẫu quan sát khác nhau). Nếu shadow chưa deploy, không có cặp, object thiếu, provenance unverified **hoặc champion asset đã chuyển khỏi baseline-q252** → báo `shadow_not_ready`/`shadow_not_applicable_model_change` và counts, **champion Accuracy vẫn được phát hành độc lập**. Số liệu Validation 2019 và test lịch sử không làm nguồn cho paired shadow live.

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

`run_id` định danh evaluation run, không phải forecast run: `run_id = <job_utc_date>-<sha256(canonical(asset, MODEL_VERSIONS[asset], champion_effective_base_date[asset], job_date, revision, config_hash, immutable_snapshot_identity, target_cutoff_date, eligible_record_fingerprint))[:20]>`. Fingerprint lưu đầy đủ trong META để tránh phụ thuộc hash rút gọn. `run_order=<YYYYMMDD>#<revision_4_digits>`; correction sau run completed dùng revision tăng có audit và `run_id` mới; retry cùng run/input giữ nguyên revision. Cùng `run_order` khác run là **conflict**, không promote.

**Access patterns:**

1. `GET /accuracy/{asset}`: `GetItem(PK=ASSET#asset, SK=STATE, ConsistentRead=true)` → `Query(PK=latest_run_pk, ConsistentRead=true)` (phân trang tới hết), chỉ khi `latest_run_pk` có giá trị. API kiểm `META.status=COMPLETED`, `META.model_version == MODEL_VERSIONS[asset]` hiện deploy và 28 keys/hashes hợp lệ trước khi trả. 1 GetItem + 1 Query logic, 0 Scan/GSI.
2. Audit một run: `Query(PK=RUN#asset#model#run_id)` khi biết run identity; không public route audit ở MVP.
3. Idempotent run write: `GetItem(META)` + conditional PutItem cho từng `METRIC` (không Query xuyên run).
4. ADR/CDK champion change: API/deployment dùng `MODEL_VERSIONS[asset]` mới cho asset được đổi; `STATE` không được Predict hoặc release operator sửa. Pointer model cũ có thể tạm tồn tại, nhưng API trả `not_ready` cho đến khi có `COMPLETED` run của model mới.

**Ví dụ:**

```text
PK=ASSET#wti                                             SK=STATE
PK=RUN#wti#baseline-q252#20261105-a94e7b3d4d0c1fb8a5e0 SK=META
PK=RUN#wti#baseline-q252#20261105-a94e7b3d4d0c1fb8a5e0 SK=METRIC#all#rolling_8w#2026-09-11#2026-11-05#2026-11-04#H1#coverage_80
```

Khóa theo run cô lập model/run/asset, SK metric mã hóa đầy đủ `sample`, evaluation kind, window, cutoff, h và metric. `overall` nằm trong META, không tạo `h=0`.

### 4.2. Immutable metric writes, fingerprint và retry [D19]

- Lấy snapshot/champion `MODEL_VERSIONS[asset]` và mốc hiệu lực cấu hình của job, tạo `run_id`/full fingerprint theo mục 4.1. `META` bắt đầu `RUNNING` bằng conditional `PutItem(ConditionExpression=attribute_not_exists(PK))`. Nếu đã tồn tại: so toàn bộ fingerprint; giống và chưa completed → resume; giống và completed → chỉ xác nhận pointer/return idempotently; khác → `RUN_ID_CONFLICT`.
- `METRIC` dùng conditional `PutItem(ConditionExpression=attribute_not_exists(PK))` ở item khóa `(PK,SK)`. Conditional fail → consistent GetItem và so `payload_hash` cùng nội dung canonical; cùng payload → no-op; khác → `IMMUTABLE_METRIC_CONFLICT`. **Không dùng BatchWriteItem** (không có conditional expressions).
- `META` được phép chuyển `RUNNING→VALIDATING→COMPLETED`, hoặc `FAILED` khi lỗi, bằng conditional UpdateItem; fingerprint/config/snapshot/evidence và metric manifest giữ bất biến. `FAILED` terminal: chạy lại có revision mới. Run bị ngắt trước completed được resume chỉ với cùng fingerprint.
- `config_hash` hash nội dung canonical; `eligible_record_fingerprint` gồm khóa và định danh/`created_at` của **các record Forecasts đã đủ điều kiện**, cutover PR #48 hoặc mã verification legacy được duyệt, model, target cutoff và snapshot/quality version (nếu có). **Không cần `evidence_fingerprint` của CloudWatch schedule logs** để tạo run_id hoặc promote.
- Snapshot/cấu hình/evaluation correction tạo run mới; metric run cũ không bị ghi đè. Nếu snapshot không bảo đảm tính nhất quán ở thời điểm evaluation, không promote.

### 4.3. Run completion, `LATEST_COMPLETED` promotion và concurrent writers [D19]

**`COMPLETED` là trạng thái xử lý và kiểm tra nguồn của những cặp được chấm**, không có nghĩa đầy đủ lịch phát hành hoặc đủ ngưỡng hiển thị. MVP **không chặn completion do thiếu CloudWatch logs, manifest hoặc các ngày expected không có Forecasts row**.

Bốn điều kiện bắt buộc để `META.status=COMPLETED`:

1. `META` có fingerprint, model version bằng `MODEL_VERSIONS[asset]` của job khi tính, window/cutoff theo asset, `sample=all`, `evaluation_kind=rolling_8w`, snapshot và `input_snapshot_dt` (khi contract áp dụng) nhất quán. Không đếm forecast sample/backfill, record trước 27/10 12:00Z; record trước cutover PR #48 chỉ được đếm nếu **phương án legacy đã được duyệt và từng record có evidence tương đương**.
2. **Mọi cặp dùng trong `n_obs`** có bản ghi `Forecasts` production hợp lệ, `created_at` trong thời gian cho phép và conditional-write provenance theo PR #48 hoặc legacy verification đã được chốt, target/actual theo calendar & cutoff, q hợp lệ. Ngày expected **không có record** → chỉ tăng `missing_count`, không chặn completed; thiếu logs không biến lịch thành `verified`, cũng không làm cặp hợp lệ bị loại.
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

**API kiểm fail-closed:** `GetItem(STATE)` và `Query(run PK)` strongly consistent; kiểm `META.status=COMPLETED`, `META.model_version==MODEL_VERSIONS[asset]` của API/CDK đang chạy, run identity/order, 28 metric hashes và eligibility/cutoff. Đọc lại `STATE` để bắt concurrent promote; nếu pointer thay hoặc model mismatch trả `not_ready`/retry ngắn. Khi ADR đổi champion, job model cũ không có quyền sửa champion, nhưng có thể gây stale pointer nếu rollout chưa đồng bộ; API vẫn **không trả sai model**. Release quy định tránh chạy song song hai đời writer; trường hợp lỗi/không đồng bộ phải test và xử lý vận hành.

**Không nhầm IAM với conditional expressions:** IAM giới hạn resource, action và (khi phù hợp) PK/attributes; chỉ logic điều kiện ứng dụng mới chống retry khác payload và rollback pointer. Không cấp API quyền UpdateItem.

### 4.4. IAM — quyền tối thiểu của MVP [D20]

| Role / thành phần | Actions cần thiết | Tài nguyên / phạm vi |
|---|---|---|
| **Rolling writer** | Accuracy `dynamodb:GetItem`, `Query`, `PutItem`, `UpdateItem`; Forecasts `GetItem`, `Query`; S3 `GetObject` clean/shadow JSON và retry shadow_eval, `PutObject` **chỉ `eval/shadow_eval/*`**; `ListBucket` có `s3:prefix` hạn chế | Accuracy table ARN, Forecasts table ARN; S3 object prefixes `clean/*`, `eval/shadow/s1a-l094/*` (read), `eval/shadow_eval/*` (write và read nếu cần retry). `s3:ListBucket` trên **bucket ARN** với `StringLike s3:prefix` chỉ `clean/*`, `eval/shadow/s1a-l094/*` (thêm prefix thực sự cần nếu integration kiểm chứng); không mở ListBucket toàn lake. Không Scan/Delete/BatchWrite. `UpdateItem` STATE chỉ cho Rolling writer, giới hạn `dynamodb:LeadingKeys`/`dynamodb:Attributes` khi có thể và test IAM thực tế. |
| **Accuracy API reader** | Accuracy `dynamodb:GetItem`, `dynamodb:Query` | Chỉ bảng Accuracy; không Scan/ghi/Forecasts/S3; đọc cùng `MODEL_VERSIONS[asset]` CDK. |
| **Predict Lambda** | Forecasts `dynamodb:PutItem` có condition; S3 `s3:PutObject` shadow source khi bật | Theo PR #48/#53/#51; **không cần `dynamodb:GetItem` Forecasts cho nhánh conditional failure D04**, không đọc bảng Accuracy; role có `eval/shadow/*` **không ghi `eval/shadow_eval/*`**. |
| **Ingest Lambda** | Quyền ingest hiện hữu | Không được ghi Accuracy hoặc shadow_eval. |

**Lý do `ListBucket`:** khi caller không có `s3:ListBucket`, `GetObject` một key không tồn tại có thể trả 403 `AccessDenied` thay vì 404 `NoSuchKey`, khiến Rolling nhầm `shadow_missing` với lỗi quyền. Cấp `ListBucket` theo **request `s3:prefix`** đúng vùng dữ liệu và `GetObject` theo object ARN. **Không giả định** policy ListBucket có điều kiện prefix luôn khiến `GetObject` thiếu key trả 404: khi nhận 403 mơ hồ, adapter phải dùng `ListObjectsV2(Prefix=<key chính xác>)` trong prefix được phép để xác nhận object vắng, hoặc giữ trạng thái `shadow_unverified` nếu không xác minh được. 403 thực vẫn là lỗi IAM. Test cả missing/permission/prefix-outside với policy triển khai thực tế.

**Bảo vệ `STATE`:** không lưu champion/version/generation trong Accuracy; chỉ Rolling writer có quyền `UpdateItem` pointer. Dùng IAM scope action/resource/key/attribute khi triển khai, cộng conditional UpdateItem `latest_run_order` monotonic và API check model, không lấy một lớp làm thay lớp kia. Không có champion release operator.

`MODEL_VERSIONS` là **một mapping authoritative trong `infra/app.py`**, truyền cho Predict, Rolling và API, kèm CDK test bảo đảm từng asset có cùng version/effective date ở ba thành phần. Không lấy từ STATE. Log không phải dependency để complete rolling MVP; không đòi CloudWatch retention 90 ngày. `kms:Decrypt` chỉ khi mã hóa bằng customer-managed KMS.

### 4.5. Data integrity, TTL và rollback

- Không TTL cho item `STATE`, `META` completed hoặc `METRIC` trong MVP. Không xóa item đang được `LATEST_COMPLETED` tham chiếu.
- Dữ liệu `Forecasts` production dùng conditional write mục 2.4; `PREDICT_ALREADY_PUBLISHED` là trạng thái **đã có production** theo PR #48, không GetItem/so payload trong Predict; retry hợp lệ không gây alarm giả. Snapshot correction tạo evaluation run mới với revision/fingerprint, không sửa forecast gốc.
- `input_snapshot_dt` do Khải nhận bổ sung vào champion PR #48 là **metadata của Forecasts sau khi code và deploy**, không thay `created_at`, `base_date`, `target_date` hoặc bảo đảm as-of một mình; không suy provenance hồi tố chỉ từ timestamp.
- Run có conflict/snapshot không nhất quán → `FAILED`/không promote; **thiếu ngày expected nhưng không có row không làm run FAILED**. Không ghi nhãn hoặc forecast giả. Sửa metadata/champion cần ADR/CDK, **không có release workflow ghi STATE**.
- Nếu `MODEL_VERSIONS[asset]` thay đổi giữa các phiên bản triển khai, API phải fail-closed khi META của pointer không trùng với config hiện hành; phát hành champion mới theo ADR và không trộn forecast trước/sau hiệu lực.

### 4.6. Nơi lưu paired shadow Parquet — ngoài Accuracy [ADR-0011 / D21–D24]

**Theo PR #49 mục 14 và phản hồi Khải:** report so sánh champion–S1a là **Parquet nội bộ trên S3**, prefix **`s3://cpaws-<env>-lake/eval/shadow_eval/run_id=<run_id>/`**, tách hẳn input S1a **JSON** tại `eval/shadow/s1a-l094/dt=<UTC>/<asset>.json`. Định danh file theo asset + `comparison_id` để tránh đụng khóa khi một evaluation run tạo báo cáo nhiều asset; ví dụ **đường dẫn đề xuất bên trong prefix** `asset=<asset>/comparison_id=<fingerprint>.parquet` (cần đồng bộ với spec PR #49 nếu nêu tên file khác). `comparison_id` hash job/config, model `MODEL_VERSIONS[asset]` của run, shadow model, source ids/checksums, target cutoff/snapshot và paired common-mask hash; không có `champion_generation` trong metadata.

**Bất biến:** S3 `PutObject(IfNoneMatch="*")`; retry đúng payload đọc lại/check checksum và no-op; payload khác cùng object key → conflict, không overwrite. `GET` report (nếu cần cho retry) được cấp cho writer đúng `eval/shadow_eval/*`; public API/Read-only Accuracy Lambda **không** có quyền đọc report. **Tách biệt IAM:** Predict có quyền ghi `eval/shadow/*` theo PR #51 nhưng **không có quyền ghi prefix sibling `eval/shadow_eval/*`**. Không cập nhật `STATE`/`LATEST_COMPLETED` hoặc API do shadow report.

**Schema report tối thiểu:** `report_kind=paired_shadow_comparison`, `asset`, `run_id`, `comparison_id`, `job_utc_date`, window/cutoff, champion `model_version`, challenger `s1a-l094`, `source_refs` (Forecasts key + shadow S3 key/version/ETag + target snapshot), `first_verified_shadow_issued_at`, `common_pairs_hash`, counts `paired_n_obs_by_h` và `n_base_dates_paired`; `pinball_skill`, `coverage_80`, `width_80` cho **cả hai model trên cùng paired mask**, theo h=1..7 và overall theo tổng hợp hợp lệ. Cột Parquet có kiểu rõ ràng, null + `undefined_reason` cho undefined, không lưu `NaN` giả hay tự backfill S1a. Chỉ chấm shadow đã có S3 issuance evidence đủ điều kiện (S3 LastModified + created_at/cutoff); thiếu shadow không chặn champion completion.

**Không thay Accuracy Schema:** champion `rolling_8w` chính thức vẫn ở DynamoDB; Parquet shadow là artifact so sánh nội bộ, không phải `evaluation_kind=rolling_8w` ghi trên S3 theo nhánh champion, không thêm enum `sample`/`evaluation_kind`, không public endpoint. IAM mới của Rolling writer phải được review trước deploy; không tự cấp quyền Predict vào shadow_eval.

## 5. API `GET /accuracy/{asset}` [ĐỀ XUẤT]

### 5.1. Request

`GET /accuracy/wti`, với Cognito ID token như API hiện tại; asset thuộc `gold`, `silver`, `brent`, `wti`. MVP cố định `evaluation_kind=rolling_8w`, `sample=all` và **chỉ champion** theo `MODEL_VERSIONS[asset]` của CDK/API; `STATE` chỉ trỏ `LATEST_COMPLETED`. S1a shadow và paired reports không có route public và không nằm trong JSON Accuracy. Không hỗ trợ chọn model/run khác qua public query params trong MVP; request tham số không hỗ trợ bị từ chối hoặc bỏ qua theo hợp đồng API hiện có (ưu tiên từ chối để tránh hiểu nhầm).

### 5.2. JSON mẫu cho Tiến/Web (trước 02/11)

> **Fixtures minh họa giao diện, KHÔNG phải số liệu production.** Bản chính thức phải được duyệt trong PR contract. `by_horizon` có đủ h=1..7 và **bốn metrics/horizon**, được thu gọn mỗi horizon thành một dòng JSON để Tiến có thể copy làm fixture. Mỗi metric có `n_obs`, `status`; `coverage_80` theo horizon chỉ trả counts, không công bố tỷ lệ %. Các con số giả định chỉ để kiểm thử trạng thái, không suy ra rollout/mốc 20 ngày thực tế.

**Ví dụ `not_ready`**

```json
{
  "asset": "wti",
  "model_version": "baseline-q252",
  "evaluation_kind": "rolling_8w",
  "sample": "all",
  "run_id": null,
  "evaluated_at": null,
  "window": {
    "basis": "base_date",
    "days": 56,
    "window_start": null,
    "window_end": null,
    "target_cutoff_date": null,
    "first_eligible_base_date": null
  },
  "evaluation_evidence": {
    "schedule_basis": "trading_calendar_and_predict_schedule",
    "schedule_evidence_status": "not_audited_mvp",
    "issuance_evidence_status": "no_completed_run",
    "expected_count": null,
    "published_count": null,
    "missing_count": null
  },
  "overall": {
    "coverage_80": {
      "covered_count": 0,
      "n_obs": 0,
      "n_base_dates": 0,
      "min_display_base_dates": 20,
      "display_value": null,
      "status": "undefined",
      "display_status": "not_ready"
    },
    "width_80": {
      "value": null,
      "n_obs": 0,
      "unit": "log_return",
      "status": "undefined"
    },
    "sign_accuracy": {
      "value": null,
      "n_obs": 0,
      "status": "undefined"
    },
    "up_rate": {
      "value": null,
      "n_obs": 0,
      "status": "undefined"
    }
  },
  "by_horizon": [
    {"h": 1, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}},
    {"h": 2, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}},
    {"h": 3, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}},
    {"h": 4, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}},
    {"h": 5, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}},
    {"h": 6, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}},
    {"h": 7, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}}
  ],
  "data_status": "not_ready",
  "disclaimer": "Dự báo chỉ mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

**Ví dụ `collecting`**

```json
{
  "asset": "wti",
  "model_version": "baseline-q252",
  "evaluation_kind": "rolling_8w",
  "sample": "all",
  "run_id": "example-rolling-2026-11-05-wti",
  "evaluated_at": "2026-11-05T18:00:00Z",
  "window": {
    "basis": "base_date",
    "days": 56,
    "window_start": "2026-09-11",
    "window_end": "2026-11-05",
    "target_cutoff_date": "2026-11-04",
    "first_eligible_base_date": "2026-10-30"
  },
  "evaluation_evidence": {
    "schedule_basis": "trading_calendar_and_predict_schedule",
    "schedule_evidence_status": "not_audited_mvp",
    "issuance_evidence_status": "verified_eligible_rows",
    "expected_count": 8,
    "published_count": 4,
    "missing_count": 4
  },
  "overall": {
    "coverage_80": {
      "covered_count": 10,
      "n_obs": 14,
      "n_base_dates": 4,
      "min_display_base_dates": 20,
      "display_value": null,
      "status": "ok",
      "display_status": "insufficient_data"
    },
    "width_80": {
      "value": 0.025,
      "n_obs": 14,
      "unit": "log_return",
      "status": "ok"
    },
    "sign_accuracy": {
      "value": 0.375,
      "n_obs": 8,
      "status": "ok"
    },
    "up_rate": {
      "value": 0.357143,
      "n_obs": 14,
      "status": "ok"
    }
  },
  "by_horizon": [
    {"h": 1, "coverage_80": {"covered_count": 3, "n_obs": 4, "display_value": null, "display_status": "counts_only", "n_base_dates": 4, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 4, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.333333, "n_obs": 3, "status": "ok"}, "up_rate": {"value": 0.5, "n_obs": 4, "status": "ok"}},
    {"h": 2, "coverage_80": {"covered_count": 2, "n_obs": 3, "display_value": null, "display_status": "counts_only", "n_base_dates": 3, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 3, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.5, "n_obs": 2, "status": "ok"}, "up_rate": {"value": 0.333333, "n_obs": 3, "status": "ok"}},
    {"h": 3, "coverage_80": {"covered_count": 2, "n_obs": 3, "display_value": null, "display_status": "counts_only", "n_base_dates": 3, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 3, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.5, "n_obs": 2, "status": "ok"}, "up_rate": {"value": 0.333333, "n_obs": 3, "status": "ok"}},
    {"h": 4, "coverage_80": {"covered_count": 1, "n_obs": 2, "display_value": null, "display_status": "counts_only", "n_base_dates": 2, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 2, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.0, "n_obs": 1, "status": "ok"}, "up_rate": {"value": 0.5, "n_obs": 2, "status": "ok"}},
    {"h": 5, "coverage_80": {"covered_count": 1, "n_obs": 1, "display_value": null, "display_status": "counts_only", "n_base_dates": 1, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 1, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": 0.0, "n_obs": 1, "status": "ok"}},
    {"h": 6, "coverage_80": {"covered_count": 1, "n_obs": 1, "display_value": null, "display_status": "counts_only", "n_base_dates": 1, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 1, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": 0.0, "n_obs": 1, "status": "ok"}},
    {"h": 7, "coverage_80": {"covered_count": 0, "n_obs": 0, "display_value": null, "display_status": "counts_only", "n_base_dates": 0, "status": "undefined"}, "width_80": {"value": null, "n_obs": 0, "unit": "log_return", "status": "undefined"}, "sign_accuracy": {"value": null, "n_obs": 0, "status": "undefined"}, "up_rate": {"value": null, "n_obs": 0, "status": "undefined"}}
  ],
  "data_status": "collecting",
  "disclaimer": "Dự báo chỉ mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

**Ví dụ `ready`**

```json
{
  "asset": "wti",
  "model_version": "baseline-q252",
  "evaluation_kind": "rolling_8w",
  "sample": "all",
  "run_id": "example-rolling-2026-12-05-wti",
  "evaluated_at": "2026-12-05T18:00:00Z",
  "window": {
    "basis": "base_date",
    "days": 56,
    "window_start": "2026-10-11",
    "window_end": "2026-12-05",
    "target_cutoff_date": "2026-12-04",
    "first_eligible_base_date": "2026-10-26"
  },
  "evaluation_evidence": {
    "schedule_basis": "trading_calendar_and_predict_schedule",
    "schedule_evidence_status": "not_audited_mvp",
    "issuance_evidence_status": "verified_eligible_rows",
    "expected_count": 25,
    "published_count": 24,
    "missing_count": 1
  },
  "overall": {
    "coverage_80": {
      "covered_count": 114,
      "n_obs": 147,
      "n_base_dates": 24,
      "min_display_base_dates": 20,
      "display_value": 0.77551,
      "status": "ok",
      "display_status": "ready"
    },
    "width_80": {
      "value": 0.025,
      "n_obs": 147,
      "unit": "log_return",
      "status": "ok"
    },
    "sign_accuracy": {
      "value": 0.485714,
      "n_obs": 140,
      "status": "ok"
    },
    "up_rate": {
      "value": 0.489796,
      "n_obs": 147,
      "status": "ok"
    }
  },
  "by_horizon": [
    {"h": 1, "coverage_80": {"covered_count": 19, "n_obs": 24, "display_value": null, "display_status": "counts_only", "n_base_dates": 24, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 24, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.478261, "n_obs": 23, "status": "ok"}, "up_rate": {"value": 0.5, "n_obs": 24, "status": "ok"}},
    {"h": 2, "coverage_80": {"covered_count": 18, "n_obs": 23, "display_value": null, "display_status": "counts_only", "n_base_dates": 23, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 23, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.5, "n_obs": 22, "status": "ok"}, "up_rate": {"value": 0.478261, "n_obs": 23, "status": "ok"}},
    {"h": 3, "coverage_80": {"covered_count": 17, "n_obs": 22, "display_value": null, "display_status": "counts_only", "n_base_dates": 22, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 22, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.47619, "n_obs": 21, "status": "ok"}, "up_rate": {"value": 0.5, "n_obs": 22, "status": "ok"}},
    {"h": 4, "coverage_80": {"covered_count": 16, "n_obs": 21, "display_value": null, "display_status": "counts_only", "n_base_dates": 21, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 21, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.5, "n_obs": 20, "status": "ok"}, "up_rate": {"value": 0.47619, "n_obs": 21, "status": "ok"}},
    {"h": 5, "coverage_80": {"covered_count": 16, "n_obs": 20, "display_value": null, "display_status": "counts_only", "n_base_dates": 20, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 20, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.473684, "n_obs": 19, "status": "ok"}, "up_rate": {"value": 0.5, "n_obs": 20, "status": "ok"}},
    {"h": 6, "coverage_80": {"covered_count": 15, "n_obs": 19, "display_value": null, "display_status": "counts_only", "n_base_dates": 19, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 19, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.5, "n_obs": 18, "status": "ok"}, "up_rate": {"value": 0.473684, "n_obs": 19, "status": "ok"}},
    {"h": 7, "coverage_80": {"covered_count": 13, "n_obs": 18, "display_value": null, "display_status": "counts_only", "n_base_dates": 18, "status": "ok"}, "width_80": {"value": 0.025, "n_obs": 18, "unit": "log_return", "status": "ok"}, "sign_accuracy": {"value": 0.470588, "n_obs": 17, "status": "ok"}, "up_rate": {"value": 0.5, "n_obs": 18, "status": "ok"}}
  ],
  "data_status": "ready",
  "disclaimer": "Dự báo chỉ mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

### 5.3. Quy ước API

- `overall.coverage_80` gộp theo số cặp; `by_horizon` trả đủ h=1..7, mỗi metric có `n_obs` và trạng thái riêng; `n_base_dates` là số base date **khác nhau có cặp hợp lệ cho scope/metric tương ứng**, không phải số cặp; **`window.first_eligible_base_date` là trường bắt buộc** (ISO date hoặc `null`), tính từ base_date đầu tiên **có ít nhất một cặp được chấm**, của champion `MODEL_VERSIONS[asset]` hiện tại, không sớm hơn champion effective date. Web hiển thị “Kể từ <ngày>” động; không hardcode 27/10, không thay bằng timestamp phát hành.
- Dashboard MVP hiển thị `coverage_80`, `width_80`, `sign_accuracy`, `up_rate` **cho champion production**. Với `gold/silver`, ADR-0005 (b) cấm hiển thị chuỗi giá Yahoo; các chỉ số Accuracy và dự báo return %/xác suất tăng không phải chuỗi giá và tiếp tục được phép hiển thị. Không hiển thị `pinball_skill=0` của champion `baseline-q252` so với chính baseline, không trả S1a/paired report trong Accuracy API. Metric khác vẫn được lưu nếu tính được; shadow `pinball_skill` chỉ trong artifact nội bộ.
- `width_80` lưu log return; web/chatbot/slide cùng dùng **`display_width_pct = 100 × width_80`**, ví dụ `width_80=0.025` → **`2.5%` độ rộng trên thang log-return** (chính xác hơn gọi là 2.5 điểm phần trăm log-return). **Không** coi đây là độ rộng simple-return; nếu thật sự cần độ rộng simple-return cho một horizon, phải tính theo cặp phân vị `100 × (exp(q90) − exp(q10))`, sau đó mới lấy trung bình trên các cặp hợp lệ, không áp exp lên width trung bình. Frontend không tự dùng công thức thứ hai khi API đang trả metric log-width. `sign_accuracy` và `up_rate` luôn đi cặp nhưng không mặc định có cùng mẫu số.
- `coverage_80.display_value=null` khi chưa đạt ngưỡng hiển thị đã chốt; không sửa `status` nội bộ chỉ vì ngưỡng UX. Tránh đưa tỷ lệ bị ẩn lên web thông qua field phụ.
- `data_status=not_ready|collecting|ready`: **HTTP 200 + `not_ready`** (null metrics) nếu chưa có completed run của `MODEL_VERSIONS[asset]` hiện hành; `collecting` nếu completed nhưng chưa đủ 20 `base_date` hợp lệ; `ready` khi đạt ngưỡng hiển thị. API đọc `STATE`/`LATEST_COMPLETED` bằng GetItem rồi Query run META+metrics bằng PK, không Scan/GSI; kiểm `META.model_version==MODEL_VERSIONS[asset]` trong cấu hình API và kiểm lại pointer trước khi trả. `STATE` không cung cấp champion; sai model → `not_ready`. Asset/auth/hạ tầng theo error envelope hợp đồng hiện hành.
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

| Tình huống | Quy tắc MVP v4.5 |
|---|---|
| `is_sample=true` hoặc `created_at` trước 27/10 12:00Z | Loại khỏi rolling production |
| Forecast trước cutover PR #48 | **Đề xuất chưa chốt**: chỉ nhận 27/10+ đúng lượt 12:15–13:30 UTC, xác minh không run tay/overwrite và as-of; nếu không được duyệt hoặc không đủ evidence → `issuance_unverified`, loại khỏi `n_obs` |
| Phát hành 27/10 cho `base_date=26/10` | Vẫn xét nếu đáp ứng nguồn phát hành bất biến và các kiểm tra khác |
| `h=1` phát hành ngày target | So timestamp cutoff 13:30 UTC, không so ngày; bảo vệ input-as-of tại predict |
| Đã có production cùng `(asset, base_date)` | Predict conditional write không ghi đè; `ConditionalCheckFailedException` → log `PREDICT_ALREADY_PUBLISHED`, không `GetItem`/so payload/alarm giả; khác với Accuracy METRIC conflict |
| Một ngày theo calendar TUE–SAT không có Forecasts row | Tăng missing counter, không chấm, reason `missing_record_unclassified`; **không chặn `COMPLETED`**, không gán đã xác minh upstream/skip |
| Log CloudWatch thiếu/hết 30 ngày | Không dùng làm evidence hay gate completion MVP; không bắt buộc tăng retention 90 ngày |
| `prob_up` lệch >`1e-6` | Chỉ ghi `prob_up_mismatch`, không loại, không ghi đè q/`prob_up` |
| Target chưa published/chưa đến cutoff | Pending; không tăng `n_obs` |
| Giá endpoint thiếu/rejected/không dương | Loại cặp theo ADR-0008, không nội suy endpoint |
| Thiếu phiên giữa endpoints | Không tự loại nếu hai endpoint hợp lệ; ghi số phiên thiếu |
| `input_snapshot_dt` sai/thiếu ở champion sau cutover | Record ineligible; trước cutover chỉ được miễn nếu **legacy verification** được họp thông qua và record đã chứng minh eligible |
| `n_obs=0`, đủ 28 item undefined và dữ liệu nhất quán | Vẫn có thể `COMPLETED`; API `collecting` hoặc chưa đủ dữ liệu tùy run/pointer, không hiện tỷ lệ |
| Chưa đủ 20 base_date có cặp coverage | Chỉ X/Y và số ngày, không hiện overall %; API vẫn trả `first_eligible_base_date` hoặc null, web không hardcode ngày |
| Đổi champion một asset theo ADR/CDK `MODEL_VERSIONS[asset]` | Không cập nhật champion/generation ở STATE; API đối chiếu META model **per-asset**, mismatch → `not_ready`; job chỉ chấm từ release effective base_date của asset đó; các asset khác giữ nguyên |
| Writer đời cũ sau deploy, run_order mới hơn | Không có quyền đổi champion; pointer có thể bị đẩy sai model nhưng API fail-closed; quy trình release phải dừng writer cũ và có test cutover |
| Snapshot correction/run hỏng | New revision/run nếu cần correction; không overwrite metric/run đã hoàn thành |
| S1a chưa phát hành/thiếu/lỗi | Shadow paired không chặn champion Accuracy; không backfill |
| S3 shadow object ghi muộn | Check LastModified/target cutoff; nếu unverified thì loại paired mask. `ListBucket` theo prefix cho phép kiểm tra bổ sung bằng ListObjectsV2 khi 403 từ GetObject còn mơ hồ |
| S1a báo cáo | **Parquet `eval/shadow_eval/run_id=<run_id>/`**; writer riêng với input JSON `eval/shadow/s1a-l094/`; không API/DynamoDB |
| Validation/test lịch sử | Không lẫn rolling production, không backfill |

---

## 8. Ma trận quyết định v4.5 — final proposed design trình chốt 30/10

Khải xác nhận **v4.3 đáp ứng 5 yêu cầu trước đó** (shadow Parquet; champion CDK; bỏ CloudWatch/manifest gate; `LATEST_COMPLETED` pointer; bỏ release operator) và nhận xét v4.4 “ổn”. V4.5 chốt thành phương án đề xuất theo comment cuối: **legacy audit theo lượt chạy thật** và **mapping champion riêng cho mỗi asset để phù hợp trường hợp K4 chỉ thắng một số tài sản**. Các vấn đề về owners/Scheduler và phê duyệt ngoại lệ vẫn phải được nhóm xác nhận. D01–D24 là **đề xuất chờ contract**, không tự sửa ADR-0008/Accuracy Schema.

| ID | Quy tắc / kiến trúc v4.5 | Review chính |
|---|---|---|
| D01 | 56 ngày UTC inclusive theo `base_date`, evaluation_start/end giữ ranh giới cửa sổ | Khải/Long |
| D02 | Forecast `created_at >= 27/10/2026 12:00Z`; **đề xuất `LEGACY_ACCEPT_WITH_EVIDENCE`** cho từng record trước cutover PR #48 sau khi Khải/Tiến kiểm chứng, nhóm duyệt và có audit reference; record không xác minh được dùng `POST_CUTOVER_ONLY`. Loại sample/pre-D02. Bằng chứng 29/10 cho base 26/10/27/10 là ứng viên, không tự verified | Khải/Tiến/Long — chờ xác nhận chính sách |
| D03 | Job tuần sau snapshot/ingest hoàn tất, một evaluation run/asset; cần chốt **lịch Scheduler UTC, readiness/retry/timeout, owner CDK/alarm**; không suy ngầm job đã deploy | Long/Tuấn/Tiến — chờ phân công |
| D04 | PR #48: Forecasts conditional PutItem cho sample→production; production cũ giữ nguyên. Conditional fail → `PREDICT_ALREADY_PUBLISHED`, **không GetItem/so payload**, không alarm giả; Accuracy METRIC vẫn fingerprint conflict | Khải/Tiến/Tuấn |
| D05 | `cpaws-<env>-accuracy` `PK/SK`: STATE (`ASSET#asset/STATE`) chỉ pointer, RUN partition cho META/METRIC; không GSI/Scan/TTL | Tuấn |
| D06 | Overall coverage chỉ hiện % khi `n_base_dates>=20` hợp lệ; vẫn trả counts | Khải/Tiến |
| D07 | `/accuracy/{asset}`: 4 metrics, overall + h1–7, `first_eligible_base_date` ISO/null, 3 JSON fixtures `not_ready/collecting/ready` trước 02/11; HTTP 200 not_ready khi thiếu current completed | Tuấn/Tiến/Long |
| D08 | `/forecast-history/{asset}` riêng, phase chart sau MVP | Tuấn/Tiến/Khải |
| D09 | History pairs on-demand từ Forecasts + clean snapshot, không bảng history detail riêng | Tuấn/Long |
| **D10** | Champion là **mapping `MODEL_VERSIONS[asset]` ở `infra/app.py`**, truyền Predict/Rolling/API cùng effective date; có CDK test đồng bộ từng asset. Đổi một asset theo ADR không reset các asset khác; STATE chỉ pointer, API so META model với runtime theo asset; S1a không âm thầm áp dụng trên K4 | Khải/Tuấn/Tiến/Long — chờ chốt |
| D11 | Horizon chỉ X/Y; overall % khi ≥20 distinct `base_date` có **ít nhất một cặp đã chấm**; 20/11 hoặc 27/11 là ước tính theo lịch, **không phải ngày `ready`**; web dùng `first_eligible_base_date`, `width_80` = 100×log-width (%) | Khải/Tiến |
| D12 | Snapshot correction → revision/run mới; record cũ bất biến | Tuấn/Long |
| D13 | Validation 2019 tách phương pháp, không trộn rolling | Khải |
| **D14** | Calendar + TUE–SAT chỉ để đếm expected/missing; **Forecasts record `created_at` + PR #48 conditional writes** là issuance evidence cho cặp được chấm; **không manifest/logs bắt buộc** | Khải/Tuấn |
| **D15** | Missing Forecasts row chỉ đếm, không chấm; **không chặn COMPLETED**; CloudWatch/retention 90 ngày **ngoài MVP**; không báo schedule verified khi chưa audit | Khải/Tuấn |
| D16 | `prob_up` mismatch >`1e-6` chỉ log, không loại/overwrite | Khải/Tuấn/Long |
| D17 | External import provenance ngoài rolling MVP; không nới workflow khác | Khải/Tuấn |
| D18 | `created_at < target_date 13:30 UTC`, input-as-of; champion sau cutover PR #48 phải lưu `input_snapshot_dt=snap.dt`; legacy trước cutover chỉ miễn trường này nếu **nhóm duyệt `LEGACY_ACCEPT_WITH_EVIDENCE` và từng record được audit**, không chỉ dựa vào timestamp | Khải/Tiến/Long — xác nhận cutover/audit |
| **D19** | Run fingerprint bất biến, 28 metric items, `RUNNING→VALIDATING→COMPLETED`; `STATE` ba trường pointer là **`LATEST_COMPLETED`**, promote chỉ khi `latest_run_order` tăng hoặc same-run idempotent; không champion generation | Tuấn/Long |
| **D20** | Rolling writer Put/Update Accuracy, read clean/shadow, write `eval/shadow_eval/*`; thêm `s3:ListBucket` bucket ARN giới hạn `s3:prefix` cần thiết; API Get/Query; Predict không GetItem thêm ở Forecasts, không đọc Accuracy; không champion operator | Tuấn/Tiến |
| D21 | Champion Forecasts + S1a JSON `eval/shadow/s1a-l094/dt=<UTC>/<asset>.json`, không retrain | Khải/Long/Tiến |
| D22 | Paired common mask, pinball_skill/coverage_80/width_80 mỗi model, không backfill shadow | Long/Khải |
| **D23** | Comparison **S3 Parquet** tại `eval/shadow_eval/run_id=<run_id>/`, immutable checksum; không DynamoDB/API, không ghi `eval/shadow/reports/` | Long/Tuấn/Khải |
| D24 | Shadow lỗi/thiếu không chặn champion `COMPLETED`; ADR mới đổi champion, không auto-switch | Khải/Long/Tuấn |

**Hiệu lực:** chỉ sau approve và PR contract tương ứng merge. Issue #23 mục 2 đóng sau khi điều chỉnh Walk-forward contract và PR contract được merge; RFC #45 review-only, không merge vào `developer`. Nếu cần bổ sung guard cross-version ở deployment, phải chốt trong PR implementation, không ngầm biến STATE thành champion registry.

---

## 9. Acceptance criteria và kế hoạch kiểm thử — điều kiện phê duyệt kiến trúc

### 9.1. Contract/invariants bắt buộc

- [ ] Evaluation `rolling_8w` có đúng khóa logic Accuracy Schema, 7 horizons, 28 METRIC items, overall trong META; validation/test vẫn S3 Parquet `eval/`.
- [ ] `STATE` **chỉ giữ** ba trường `latest_run_pk`, `latest_run_id`, `latest_run_order` = **`LATEST_COMPLETED`**; không `champion_model_version`, `champion_generation`, `effective_base_date` hay item LATEST riêng. `META.model_version` phải trùng `MODEL_VERSIONS[asset]` của API/CDK lúc trả; ngày gốc đã chấm không sớm hơn effective date của asset.
- [ ] `Forecasts` production bất biến tại `(asset,base_date)` theo PR #48; conditional fail → `PREDICT_ALREADY_PUBLISHED` **không GetItem/so payload**, khác với Accuracy METRIC; legacy chỉ được chấm theo `LEGACY_ACCEPT_WITH_EVIDENCE` sau khi nhóm duyệt và từng record có audit reference. Không backfill.
- [ ] `run_id`/fingerprint khóa asset, model config, snapshot, eligible records, cutoff và revision; retry cùng payload no-op; khác payload conflict; metric chỉ conditional PutItem, không overwrite, không BatchWriteItem.
- [ ] `COMPLETED` cần đủ 28 METRIC rows, correct counts, snapshot/cutoff và issuance evidence **của cặp được chấm**; **không yêu cầu** CloudWatch logs, publication manifest, 90-day retention hoặc mọi kỳ expected có row. `n_obs=0`/undefined hợp lệ nếu đầy đủ 28 rows.
- [ ] Expected count dùng calendar/TUE–SAT; thiếu Forecasts row chỉ tăng `missing_count` và không khẳng định skip/upstream, không chặn completion. `schedule_evidence_status=not_audited_mvp`, tách khỏi `issuance_evidence_status=verified_eligible_rows`.
- [ ] `MODEL_VERSIONS` là **mapping per-asset tại `infra/app.py`** truyền Predict/Rolling/API, có CDK test đồng bộ mọi asset và effective date; Predict không gọi `STATE`/Accuracy, API fail-closed theo asset nếu META version khác. Một asset đổi K4 không làm reset ba asset khác; S1a không được đổi định nghĩa ngầm.
- [ ] API `/accuracy/{asset}` có 4 metrics, overall/by_horizon, `n_obs`,`n_base_dates`, **`first_eligible_base_date` ISO/null**, 20 ngày chỉ là UI; thống nhất `display_width_pct=100×width_80`, 3 JSON fixtures cho Tiến trước 02/11.
- [ ] IAM chỉ Rolling writer cập nhật STATE pointer (không field champion); API reader chỉ GetItem/Query. `s3:ListBucket` được scope bằng `s3:prefix` đúng clean/shadow, adapter phân biệt missing với IAM 403 qua scoped ListObjectsV2 nếu cần; ưu tiên PK/attributes IAM và deny tests. Không champion operator.
- [ ] Predict đọc/ghi source S1a tại `eval/shadow/s1a-l094/*` theo PR #49/#51; Rolling writer ghi **Parquet `eval/shadow_eval/*`**; quyền Predict `eval/shadow/*` không được ghi vào báo cáo so sánh, API không đọc report.
- [ ] Shadow trên paired mask, không tác động champion Accuracy/API và không auto-switch. Không SageMaker/Step Functions retrain. **Chốt owner hạ tầng và giờ UTC**: bảng `CpawsServing`, API `CpawsApi`, scheduler/handler/image/alarm trước 05/11; chỉ ghi nhận phân công khi người nhận xác nhận.

### 9.2. Functional tests — 48 trường hợp (T01–T48)

| ID test | Điều kiện thử | Expected v4.5 |
|---|---|---|
| T01 | Key metric khác `run_id`, asset, model, sample, kind, window, cutoff, h hoặc metric | Không va chạm PK/SK và đủ logical key |
| T02 | GET accuracy 4 asset; run có 28 METRIC và Query nhiều page | GetItem STATE + Query RUN, không Scan/GSI, chỉ current `MODEL_VERSIONS[asset]` |
| T03 | Crash sau 27/28 METRIC | Chưa completed, không promote pointer, API không đọc partial |
| T04 | Retry đúng run fingerprint/metric | No-op / resume, không overwrite |
| T05 | Cùng PK/SK khác payload hoặc cùng run_order khác run_id | Conflict, giữ record gốc, pointer không tự đổi |
| T06 | Hai writers complete trái thứ tự, run_order B>A | Pointer monotonic trỏ B; không rollback |
| T07 | ADR/CDK đổi champion **chỉ `gold`** từ baseline sang K4, ba asset khác giữ baseline, STATE gold còn pointer cũ | `/accuracy/gold` → `not_ready`, ba asset khác vẫn trả kết quả; gold không trộn model hoặc tự backfill trước effective date |
| T08 | Run đủ 28 rows nhưng không có cặp có nhãn hợp lệ | COMPLETED được phép với 28 undefined + reasons, counts đúng; display không giả % |
| T09 | Thiếu metric row hoặc hash/count không nhất quán | Không COMPLETED hoặc promote |
| T10 | Lịch có ngày expected nhưng Forecasts không có row | missing_count tăng, bỏ qua ngày; **không** block COMPLETED vì thiếu record |
| T11 | Record Forecasts hợp lệ nhưng không đọc được CloudWatch logs | Vẫn chấm theo record + conditional immutability, không đòi log |
| T12 | Lịch 56 ngày có logs thiếu/hết hạn 30 ngày | `schedule_evidence_status=not_audited_mvp`; 28 rows đủ và cặp có evidence → COMPLETED |
| T13 | Record trước 27/10 12Z, sample hoặc backfill; legacy đúng lịch nhưng không có approval | Loại khỏi scoring; legacy riêng được xét T37/T38, không tự cho phép bởi timestamp |
| T14 | h=1 phát hành cùng target date 12:15Z, >13:30Z, DST | So timestamp, kiểm input-as-of |
| T15 | `input_snapshot_dt` sai/missing **sau cutover** PR #48 | Ineligible; legacy chỉ miễn sau audit/duyệt `LEGACY_ACCEPT_WITH_EVIDENCE` tại T38 |
| T16 | `prob_up` sai lệch 0, 1e-6, >1e-6 | >ngưỡng chỉ log, không sửa/loại một mình |
| T17 | Endpoint invalid/missing; intermediate missing | Theo ADR-0008, không fill endpoint; thiếu giữa không tự invalid |
| T18 | Coverage overall, 0/19/20 base dates, nhiều horizons cùng base date | Pool hit/count, UX ẩn/hiện đúng |
| T19 | Sign zero-mask khác up_rate; width log return | Metric n_obs riêng, đúng đơn vị, không h=0 |
| T20 | IAM: API ghi/scan Accuracy; Predict đọc Accuracy; Rolling writer PutObject vào eval/shadow/*; writer sửa ngoài pointer fields | AccessDenied; quyền nguồn S3 phân biệt `ListBucket` trong T39 |
| T21 | API đang Query thì pointer đổi, hoặc **config mapping per-asset** không khớp `META.model_version` | Recheck STATE, fail-closed với asset sai model; không ảnh hưởng 3 asset còn lại |
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
| T35 | Forecasts đã có production tại đúng `(asset,base_date)` | Không overwrite; `ConditionalCheckFailedException` log `PREDICT_ALREADY_PUBLISHED` **không GetItem/so fingerprint**, không alarm giả dù `created_at` lần retry khác |
| T36 | Forecasts có sample trước, production replace rồi retry/holiday rerun | Sample→production một lần; lần sau giữ bản production, log `PREDICT_ALREADY_PUBLISHED`, không thêm IAM GetItem |
| T37 | Audit 29/10 bốn asset: base 26/10 issued 27/10T12:15:31Z, base 27/10 issued 28/10T12:16:03Z; base 23/10 (25/10) và sample 16/10 là đối chứng; thêm timestamps ngoài khung/manual overwrite giả lập | Hai lượt đầu **chỉ là ứng viên**; chỉ nhận khi `LEGACY_ACCEPT_WITH_EVIDENCE` được duyệt và có record audit; ngoài khung/manual/unverified và đối chứng luôn loại |
| T38 | Legacy base 26/10, 27/10 thiếu `input_snapshot_dt`, cờ policy và audit reference; record post-cutover thiếu/sai snapshot field | Legacy chỉ miễn khi đã duyệt và audit; fallback `POST_CUTOVER_ONLY` loại record không xác minh; sau cutover thiếu/sai field luôn loại |
| T39 | S3 GetObject key shadow vắng, IAM 403 và key trong/ngoài prefix | Scoped ListObjectsV2 xác nhận missing khi GetObject 403 mơ hồ; 403 IAM thật không bị gán missing; ngoài prefix denied |
| T40 | CDK `MODEL_VERSIONS` mapping + effective date cho Predict, Rolling và API, thử thay version chỉ gold | Assert cả ba nhận **cùng map và từng hiệu lực asset**; mismatch một asset fail-closed đúng asset; không ảnh hưởng asset khác |
| T41 | API `first_eligible_base_date` null/26-10/31-10 và Web khi có/lúc chưa có nhãn | ISO/null từ ngày gốc đầu **đã chấm**, không hardcode ngày phát hành, không sớm hơn champion effective date |
| T42 | `width_80=0.025` và khoảng q10/q90 bất đối xứng | Web/chatbot/slide hiển thị `2.5%` log-width; không nhầm với simple-return width `100×(exp(q90)−exp(q10))` |
| T43 | JSON fixtures `not_ready`, `collecting`, `ready`; 7 horizons và 4 metrics | Parse/schema/status nhất quán; API actual phải trả đủ metrics/h dù ví dụ rút gọn |
| T44 | CDK infra bảng, weekly Scheduler sau snapshot/ingest, image/handler, route, alarm; owner/giờ UTC chưa được nhóm xác nhận | Test wiring, retry khi snapshot chưa ready, IAM và monitoring; owner/giờ còn trống là blocker deploy 05/11, **không phải bằng chứng job đã có** |

| T45 | Champion mapping đổi **chỉ Brent**, effective base_date ở giữa rolling window, `RUN` cũ còn trong STATE | Chỉ chấm Brent champion mới kể từ effective date; không trộn phiên trước, `not_ready` nếu chưa có run mới; gold/silver/wti không reset |
| T46 | Một asset đổi K4, S1a object cũ vẫn tồn tại; asset khác vẫn baseline | Không dùng K4 làm input cho `s1a-l094`; `shadow_not_applicable_model_change` theo asset đổi, paired S1a của asset khác vẫn tính; champion run không block |
| T47 | Lịch có 20 base_date nhưng mới 19 có target đủ điều kiện; sau khi target thứ 20 mature nhưng job chưa chạy | Trước job hoàn tất `display_status=insufficient_data`; sau completed run mới có `n_base_dates>=20` mới được hiện overall %, không hứa ngày ready cố định |
| T48 | Legacy whitelist/fingerprint thiếu approval, sai input-as-of, cùng timestamp nhưng có manual update; cutover timestamp thực tế khác lịch dự kiến | Không chấm các record chưa đủ chứng cứ; chỉ nhận audit entries được duyệt; policy và effective cutover versioned trong META, không nâng schedule evidence thành immutable verified |

### 9.3. Nghiệm thu MVP 05/11

- API `/accuracy/{asset}` chỉ đọc completed run `META.model_version==MODEL_VERSIONS[asset]` hiện deploy, có 28 METRIC, dữ liệu forecast thực hợp lệ; trạng thái `not_ready` hợp lệ nếu chưa có completed run hiện hành, không bịa forecast.
- `COMPLETED` không đòi `n_base_dates>=20`/`n_obs>0`, không phụ thuộc logs/manifest/90-day retention. Đủ 28 METRIC, snapshot/eligible pairs đúng, `n_obs`/counts nhất quán; ngày expected thiếu row được đếm riêng, không chấm.
- `STATE` chỉ pointer ba trường `LATEST_COMPLETED`; IAM writer scoped pointer và `ListBucket` S3 theo prefix, API chỉ đọc; champion authoritative = mapping CDK `MODEL_VERSIONS[asset]`, đổi từng asset bằng ADR.
- S1a shadow xuất **S3 Parquet `eval/shadow_eval/run_id=<run_id>/`** trên paired mask và không chặn champion. Predict có thể ghi `eval/shadow/*` nhưng không ghi report.
- PR implementation chứng minh T01–T48 (shadow T25–T34 sau khi có S1a, Predict T35–T36 theo PR #48, legacy T37–T38 theo quyết định họp); IAM deny tests, correct payload/hash và không có giả lập dữ liệu production.
- Không backfill 2020–2026, không retrain hoặc sửa Validation 2019/ADR-0008.

## 10. Những quyết định cuối cần xác nhận, phân công và chuyển contract

**RFC v4.5 là tài liệu đề xuất sẵn để chốt, không tự coi cả nhóm đã approve.** Khải xác nhận kiến trúc v4.3 đạt 5 mục và nhận xét v4.4 “ổn”; phản hồi cuối ngày 30/10 ủng hộ legacy đúng lịch và yêu cầu D10 hỗ trợ champion per-asset. Hai điểm này còn cần xác nhận của Tuấn/Tiến và được ghi trong biên bản họp. Những phần khác (D01/D04/D05/D06/D14–D16/D19/D20/D21–D24) giữ theo phương án đã review, không mở lại nếu không có xung đột implementation.

### 10.1. Bảng chốt họp 30/10 (không suy diễn approval)

| Quyết định | Phương án v4.5 đề xuất | Điều kiện đóng |
|---|---|---|
| **Legacy từ 27/10** | `LEGACY_ACCEPT_WITH_EVIDENCE` theo đề xuất Khải; chỉ record trong khung chạy lịch 12:15–13:30 UTC đã được audit/duyệt, miễn `input_snapshot_dt` trước cutover; nếu thiếu evidence dùng `POST_CUTOVER_ONLY` | Khải, Tiến, Tuấn đồng ý tiêu chí kiểm record; Long ghi policy/record references và thời điểm PR #48 **thực tế deploy** vào contract/provenance |
| **Champion từng asset — D10** | `MODEL_VERSIONS = {gold, silver, brent, wti}` trong CDK, cùng mapping cho Predict/Rolling/API; từng asset có `champion_effective_base_date` theo ADR/release, không thay STATE | Khải, Tuấn, Tiến xác nhận rollout/owner và CDK fixture; không triển khai K4 làm champion nếu chưa có ADR riêng |
| **Hiển thị ngưỡng 20** | Chỉ tính ≥20 **distinct base_date đã có cặp được chấm**; 20/11/27/11 chỉ là ước tính ngày theo calendar, còn phụ thuộc cutoff và lần chạy job | Khải/Tiến xác nhận JSON và web logic; không hardcode ngày `ready` |
| **Hạ tầng 05/11** | Tuấn: Accuracy DynamoDB + API; Long: rolling core/job; Tiến: predict image/handler, CDK deploy/wiring với nhóm; Khải: PR #48 `input_snapshot_dt`. **Scheduler/CDK/alarm vẫn cần người nhận trực tiếp** | Người nhận xác nhận trách nhiệm, lịch UTC, trigger sau snapshot, retry/alert và IAM tại họp; không hiểu dòng đề xuất là đã nhận việc |

**Điều kiện nhận legacy tối thiểu:** Tiến cung cấp biên bản kiểm từ 29/10 và cập nhật trước cutover, Khải/nhóm xác nhận tính phù hợp của lịch, phương thức kiểm manual overwrite, kiểm input-as-of và danh sách `asset/base_date/created_at/model_version` được nhận; Long lưu `policy_id`/audit reference/hash vào `META`. **Bằng chứng timestamp đúng lịch không chứng minh tuyệt đối bất biến trước PR #48.** Không có xác nhận thì fail-closed, không chấm. Không xây store manifest mới.

**Cutover:** `predict_immutable_cutover_at` là timestamp UTC chính xác sau deploy **và smoke test** PR #48 có conditional PutItem + `input_snapshot_dt`; không mặc định 31/10 là đã triển khai. Forecasts sau cutover thiếu trường snapshot/conditional provenance là ineligible, trước cutover chỉ nhận theo policy legacy duyệt. Khải phụ trách thay đổi Predict, Tuấn/Tiến phối hợp CDK/release; lịch cụ thể cần được cập nhật sau khi deploy.

**Lịch chạy đề xuất để nhóm chọn:** job **mỗi tuần sau khi ingest 12:15 UTC và clean snapshot/quality được xác nhận READY**, một run per asset. Cuộc họp cần điền **thứ/ngày và giờ UTC chính xác**, scheduler owner, timeout/retry khi snapshot chưa ready, cơ chế không chạy trùng và nơi báo alarm. Không tự coi mọi thứ đã sẵn sàng khi chỉ có Lambda handler trong repo. Ngày/giờ không chốt là blocker production 05/11, nhưng không thay đổi thuật toán RFC.

### 10.2. Milestones và ownership

| Mốc | Đầu ra | Owner / trạng thái |
|---|---|---|
| **30/10/2026** | Chốt legacy policy, champion mapping per-asset, cutover verification, mapping release, Scheduler UTC/owner, role IAM | Khải/Tuấn/Tiến/Long — cần xác nhận trong họp |
| **31/10/2026 (dự kiến)** | Deploy PR #48 kèm `input_snapshot_dt` champion; ghi lại timestamp thật và smoke-test conditional write | Khải + người deploy của nhóm — chưa xác nhận deploy |
| **Sau họp** | PR riêng `docs/api/contract.md` + `docs/eval/walk-forward-contract.md` §7; không merge RFC #45 | Long, Tuấn/Khải/Tiến review |
| **Trước 02/11/2026** | JSON fixtures `not_ready`, `collecting`, `ready` theo champion per-asset để Tiến làm web | Long soạn, Tiến review |
| **05/11/2026** | MVP champion: rolling job + STATE/META/28 METRIC + `/accuracy/{asset}`, IAM/alarm/scheduler verified | Đề xuất Long job; Tuấn table/API; Tiến image/deploy; cần xác nhận |
| **02–06/11/2026** | Source S1a JSON PR #53, không chặn champion MVP | Khải/Tiến/Tuấn |
| **Sau khi S1a có nhãn** | Paired report **S3 Parquet `eval/shadow_eval/run_id=<run_id>/`** chỉ cho baseline champion, không public | Long + Khải/Tuấn review |
| **15/11/2026 (dự kiến)** | Web độ tin cậy phụ thuộc Accuracy JSON contract | Tiến + Long |
| **22/11/2026** | Đóng băng tính năng | Nhóm |

### 10.3. Các thay đổi chính thức trong PR contract sau khi approve RFC

1. **Forecast eligibility:** 56 ngày UTC, `created_at` min/target UTC cutoff, champion `MODEL_VERSIONS[asset]`, effective base date từng asset, `input_snapshot_dt` sau cutover và policy `LEGACY_ACCEPT_WITH_EVIDENCE` (có evidence reference, fallback và timestamp cutover thực tế).
2. **`docs/eval/walk-forward-contract.md` §7:** ngoại lệ `rolling_8w` MVP **không manifest/CloudWatch gate**; calendar expected chỉ đếm, dữ liệu thật mới chấm, không nới các quy tắc `validation`/`test`/import.
3. **API contract:** 4 metrics + per-metric `n_obs`, overall `n_base_dates`, `first_eligible_base_date` ISO/null, `display_width_pct=100×width_80`, JSON `not_ready/collecting/ready`, chỉ current champion **per-asset**; không công bố shadow. Ngưỡng 20 theo dữ liệu đã chấm.
4. **Accuracy storage:** STATE pointer `LATEST_COMPLETED`, META/METRIC immutable 28 rows, order/fingerprint, completion/promotion, API check champion map runtime per asset + fail-closed; không registry champion trong STATE.
5. **IAM/infra:** writer scoped Get/Put/Update Accuracy; API chỉ Get/Query; scoped `s3:ListBucket` cho clean/shadow khi cần, Forecasts Predict không `GetItem` bổ sung theo D04, S3 shadow JSON khác paired Parquet; lịch Scheduler/owner và alarm đã chốt.
6. **S1a/champion switch:** `s1a-l094` chỉ định nghĩa dựa trên baseline-q252; asset đổi K4 không tự được chấm cặp S1a cũ, chờ ADR hoặc challenger mới. Không tự đổi champion bằng Shadow.
7. **Data integrity:** `prob_up` >1e-6 chỉ log; import provenance ngoài MVP, không backfill, tách score theo horizon/asset/cutoff, cập nhật T01–T48 theo các quyết định đã approve.

**Quy trình:** RFC v4.5 → nhóm chốt/approve → PR contract riêng → implementation/tests/deploy. **PR #45 chỉ review/approval, KHÔNG MERGE `developer`**; sau khi contract PR merge, đóng RFC *Closed — Not Merged* và xử lý Issue #23 theo thỏa thuận.

**File đề xuất trên PR #45:** `docs/proposal/rolling-accuracy-design.md` (không phải `docs/proposals/`).

## Phụ lục A — Đối chiếu source code

- Theo review Khải, tài liệu ở GitHub dẫn commit **`a5f770c`** thay vì tên ZIP source. Khi chuyển sang contract, đối chiếu commit thực tế với nhánh đang deploy.
- `docs/api/contract.md`: `/accuracy/{asset}` chưa có JSON chính thức trong snapshot được review.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, `target_cutoff_date`, common mask và status.
- `docs/eval/walk-forward-contract.md`: hiện yêu cầu publication manifest; **v4.5** dùng Forecasts+conditional immutable write để xác minh **các cặp được chấm**, calendar/TUE–SAT chỉ đếm expected/missing; sửa mục 7 qua PR contract riêng, không bắt buộc CloudWatch hoặc 90-day retention MVP.
- `src/forecast/predict.py`/`to_forecast_record`: PR #48 đã được approve về conditional PutItem nhưng **bản được Tiến review chưa thêm `input_snapshot_dt` champion**; Khải mới **nhận bổ sung** và contract Forecasts trước khi deploy. PR #53 có `input_snapshot_dt` trên **S1a shadow**, không thay thế trường của champion. `MODEL_VERSIONS[asset]` từ CDK (đề xuất v4.5), Predict không truy cập STATE. Chỉ đánh giá tình trạng code/deploy sau khi xác minh commit.
- `src/eval/metrics.py`: có helper metrics; chưa có orchestration rolling hoàn chỉnh theo RFC.
- **PR #49** `docs/experiments/s1a-shadow-plan.md`: kế hoạch `src/forecast/vol_scale_core.py`, S1a input JSON `eval/shadow/s1a-l094/` và báo cáo paired shadow **Parquet `eval/shadow_eval/`**; PR #51 cấp quyền predict cho `eval/shadow/*` nên output phải nằm ngoài prefix đó. Tình trạng deploy cần xác minh riêng.
- **PR #46** ADR-0011: bỏ Step Functions/SageMaker retrain trước bảo vệ; bổ sung paired shadow weekly. ADR-0005 cũng chọn hiển thị (b), chỉ return %/xác suất cho vàng/bạc; **RFC Accuracy vẫn đo trên log return** và không dùng giá vàng/bạc quy đổi để tính nhãn.
- `infra/lambda/forecast_api/handler.py`: chưa hỗ trợ `/accuracy/{asset}` trong snapshot được review.

Các trạng thái code là từ snapshot đã dùng để soạn RFC, không xác nhận deployment AWS đang chạy.

## Phụ lục B — Tài liệu tham khảo

1. *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (chèn liên kết nội bộ chính thức khi được cung cấp).
2. [Issue #23 — Walk-forward phase 2](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).
3. `docs/adr/0008-target-quantiles-evaluation.md`, `docs/adr/0009-ceemdan-dlinear-k3-result.md`, `docs/adr/0010-k3b-volatility-scaling-result.md`, **[PR #46 — ADR-0011, ADR-0005](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/46)**, **[PR #49 — S1a shadow plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/49)**, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`.
4. [S3 GetObject: 404 khi có ListBucket, 403 khi thiếu quyền](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html), [DynamoDB PutItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html), [BatchWriteItem không hỗ trợ conditional expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_ConditionalBatchUpdate.html), [DynamoDB strong reads](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html), [IAM DynamoDB LeadingKeys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/specifying-conditions.html).
5. Dawid (1984), *The Prequential Approach*, DOI: https://doi.org/10.2307/2981683.
6. Gneiting et al. (2007), *Probabilistic Forecasts, Calibration and Sharpness*, DOI: https://doi.org/10.1111/j.1467-9868.2007.00587.x.

> **Trạng thái cuối v4.5:** Kiến trúc v4.3 đã đáp ứng 5 góp ý theo Khải; v4.4 được Khải nhận xét “ổn”; v4.5 bổ sung chính sách `LEGACY_ACCEPT_WITH_EVIDENCE` và D10 **champion per-asset** theo comment cuối. **Nhóm vẫn cần duyệt ngoại lệ legacy, mapping per-asset, giờ Scheduler/owner và cutover thực tế trước khi coi RFC đã chốt.** PR #45 **review-only, KHÔNG MERGE**; chỉ PR contract đã được duyệt và merge mới là chuẩn triển khai.
