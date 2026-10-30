# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** **RFC v4.6 — DECISIONS LOCKED theo kết luận họp 30/10/2026 (Khải xác nhận trên PR #45); REVIEW-ONLY, chưa có hiệu lực contract trước PR contract được review/merge. Không đồng nghĩa đã có approving review GitHub từ tất cả thành viên hoặc đã deploy.**  
> **Ngày cập nhật:** 2026-10-30 (v4.6: đồng bộ comment của Tiến và kết luận họp do Khải đăng ngày 30/10: `width_80_pct`, gating mọi metric overall, job TUE–SAT 13:45 UTC, legacy có bằng chứng, cutover, CDK mappings/owners; giữ nguyên kiến trúc v4.5).  
> **Người đề xuất:** Long — nhóm CPAWS  
> **Người review:** Khải (đánh giá/hiển thị), Tuấn (API, DynamoDB, IAM), Tiến (Predict, Web)  
> **Mục tiêu:** Ghi lại quyết định thiết kế đã chốt để chuyển sang PR riêng cập nhật `docs/api/contract.md` và ngoại lệ `rolling_8w` trong `docs/eval/walk-forward-contract.md` §7; không sửa ngầm Accuracy Schema/ADR ngoài phạm vi được duyệt.  
> **Tham chiếu:** `docs/api/contract.md`, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`, ADR-0008, ADR-0009, ADR-0010, **ADR-0011 (PR #46)**; kế hoạch S1a Shadow (PR #49); source tại commit `a5f770c` theo review của Khải; *Spec dashboard dự báo và độ tin cậy* (27/10/2026); [Issue #23](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).

> **Quy trình PR #45:** PR tài liệu này chỉ dùng để review và approve, **KHÔNG MERGE vào `developer`**. Sau khi chốt, chuyển các quyết định được duyệt sang `docs/api/contract.md` và các contract liên quan bằng PR riêng, rồi đóng PR RFC với trạng thái *Closed — Not Merged*.

## Tóm tắt quyết định và phạm vi

RFC đề xuất hai chức năng phục vụ Dashboard CPAWS:

1. Job `rolling_8w` chấm forecast **champion production** đã phát hành thật, có nhãn hợp lệ; lưu Accuracy chính thức trong DynamoDB cho Dashboard.
2. **Theo ADR-0011**, cùng job chạy hằng ngày sau predict có nhánh **so sánh champion với challenger S1a (`s1a-l094`)** trên các cặp forecast–actual giao nhau; chỉ lưu báo cáo **shadow nội bộ**, không thay đổi champion và không công khai S1a qua Accuracy API.
3. `GET /accuracy/{asset}` trả chỉ số champion tổng hợp và theo 7 horizons; `GET /forecast-history/{asset}` là endpoint riêng cho biểu đồ “dự báo cũ so với thực tế” giai đoạn sau.

**Các quy tắc giữ nguyên:** bốn asset `gold/silver/brent/wti`; horizons `h=1..7` theo **phiên giao dịch của tài sản**; nhãn và các phân vị dự báo là **log return**; không tạo ngược forecast cho dữ liệu test 2020–2026; `validation/test` lưu S3 Parquet `eval/`, `rolling_8w` lưu DynamoDB; `overall.coverage_80` gộp theo số cặp hợp lệ, không lấy trung bình ngang các tỷ lệ của 7 horizons; `sign_accuracy` luôn hiển thị cùng `up_rate`.

**Chính sách MVP đã được Khải chốt theo họp 30/10:** cửa sổ 56 ngày UTC theo `base_date`; `created_at >= 2026-10-27T12:00:00Z`; nhận *legacy trước PR #48* **chỉ khi xác minh từng record** (lịch chạy, `model_version`, `is_sample=false`, không overwrite, input-as-of), còn lại loại khỏi `n_obs`. Tiến sẽ xuất bằng chứng CloudWatch `PREDICT_DONE`/Invocations và `created_at` cho base 26–29/10 (cộng 30/10 nếu trước cutover) **trước 02/11**; bằng chứng này là audit ngoại lệ legacy, **không** trở thành CloudWatch/manifest gate cho mỗi run Rolling. Có `input_snapshot_dt` → ứng viên hậu cutover, vẫn cần kiểm provenance và thời gian deploy; thiếu trường → ứng viên legacy, **không tự được chấm** nếu không nằm trong danh sách đã duyệt. Cutover production thật dự kiến lượt predict 19:15 giờ Việt Nam ngày 31/10 (12:15 UTC), **chưa được coi là đã deploy** cho đến khi xác nhận CloudFormation/smoke test; `dry_run` không ghi DynamoDB. Job hằng ngày theo `cron(45 13 ? * TUE-SAT *)` UTC (20:45 Việt Nam), không promote khi snapshot/actual chưa ready. `MODEL_VERSIONS` và `CHAMPION_EFFECTIVE_BASE_DATES` per-asset cùng định nghĩa tại `infra/app.py`, truyền qua môi trường cho Predict/Rolling/API; Predict giữ fallback `MODEL_VERSION` ở giai đoạn chuyển đổi. `STATE` chỉ là con trỏ `LATEST_COMPLETED`. Dashboard có 4 metric nền (`coverage_80`, `width_80`, `sign_accuracy`, `up_rate`) **và** derived `width_80_pct`; tất cả metric overall có `display_value`/`display_status` theo ≥20 distinct `base_date` có cặp được chấm. **Web chỉ hiển thị `width_80_pct`**, tuyệt đối không tự `exp` hay lấy `100×width_80`. `width_80_pct` tính từng cặp `100×(exp(q90)−exp(q10))` rồi lấy trung bình. Không tăng số item 28 METRIC. Không cam kết `ready` trước 22/11; DM gap được hoãn sau 22/11, **không sửa DM-HAC/fingerprint K4**.

**Bằng chứng vận hành sẵn có ngày 29/10 (Tiến):** kiểm tra `cpaws-dev-forecasts` trên cả 4 tài sản cho thấy `base_date=2026-10-26` có `created_at=2026-10-27T12:15:31Z` và `base_date=2026-10-27` có `created_at=2026-10-28T12:16:03Z`, cùng `model_version=baseline-q252`, `is_sample=false`. Theo Tiến, đây là hai lượt chạy theo lịch, không có lần chạy tay hay ghi đè được phát hiện. Điều này **ủng hộ `LEGACY_ACCEPT_WITH_EVIDENCE`**, nhưng timestamp đơn lẻ không chứng minh tuyệt đối tính bất biến trước PR #48; chính sách legacy đã được Khải chốt *có điều kiện*, nhưng **các record cụ thể chưa được mặc nhiên duyệt**; danh sách chứng cứ sẽ được Tiến xuất trước 02/11 và cần ghi rõ bản ghi được chấp nhận trước khi chấm.

**Kiến trúc giữ nguyên từ v4.5:** một bảng `cpaws-<env>-accuracy`, item `STATE` theo asset **chỉ giữ** `latest_run_pk`/`latest_run_id`/`latest_run_order` (gọi chung là **`LATEST_COMPLETED`**); partition `RUN#asset#model#run_id` chứa `META` và 28 item `METRIC`; **không GSI, không Scan**. Champion lấy từ **`MODEL_VERSIONS[asset]` do CDK triển khai**, thay đổi theo tài sản bằng ADR/deploy, **không lưu champion hoặc generation trong `STATE`**. Writer ghi `METRIC` bất biến bằng conditional `PutItem`, chỉ promote pointer sau khi run đủ 28 metrics, snapshot/forecast eligibility hợp lệ; **không** phụ thuộc đầy đủ nhật ký lịch phát hành. IAM chỉ tách Rolling writer và API reader cho bảng Accuracy; Predict không đọc Accuracy; không có champion release operator MVP. Shadow đọc JSON tại `eval/shadow/s1a-l094/`, tính paired mask và lưu **Parquet nội bộ `eval/shadow_eval/run_id=<run_id>/`**. Các quyết định cuộc họp sẽ thành contract chính thức **chỉ sau khi PR contract riêng được review và merge**.

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

### 2.3. Forecast đủ điều kiện đánh giá [D02/D10/D18 — legacy được chốt có điều kiện]

1. `is_sample=false`, asset/target/horizon hợp lệ; mỗi horizon đủ 7 phân vị hữu hạn, có thứ tự và `prob_up` trong miền cho phép. `model_version` phải khớp **`MODEL_VERSIONS[asset]`** đang có hiệu lực cho asset/base_date; không trộn model giữa các tài sản hoặc các đời champion của cùng asset.
2. `created_at` UTC **`>= 2026-10-27T12:00:00Z`**. Không buộc `base_date>=27/10`, vì lượt phát hành đầu 27/10 có thể có `base_date=26/10`. Loại mọi sample và record trước mốc dù `is_sample=false`.
3. `created_at < target_date T13:30:00Z` ở từng h, so UTC timestamp; xác nhận target h phiên, dữ liệu input chỉ đến `base_date`, `publication_as_of` và target endpoint/cutoff riêng asset. **Timestamp không tự chứng minh không leakage.**
4. **Record hậu cutover PR #48 (xác minh theo bản ghi và sự kiện deploy):** Forecasts production phải được ghi bằng conditional `PutItem` và mang `input_snapshot_dt=YYYY-MM-DD` lấy từ `snap.dt` của clean snapshot đã thực sự dùng; trường này phải được validate với snapshot/input-as-of, không chỉ kiểm chuỗi. Khải phụ trách code champion và Forecasts contract trong PR #48; **cutover phải được ghi theo sự kiện CloudFormation, kết quả predict production và smoke test (dự kiến lượt 31/10/2026 12:15 UTC; dry_run không ghi bảng), không chỉ thời điểm build/approve**, không lấy ngày dự kiến 31/10 thay thế. Việc PR được approve/merge không tự chứng minh Lambda đã deploy.
5. **Record thiếu `input_snapshot_dt`/trước cutover — đã chốt chính sách `LEGACY_ACCEPT_WITH_EVIDENCE` nhưng phải xác minh từng record:** chỉ chấp nhận từng `(asset, base_date, model_version, created_at)` được Khải/Tiến kiểm chứng là lượt chạy lịch **12:15–13:30 UTC**, không chạy tay, không ghi đè/reissue, có cơ sở xác nhận input-as-of; được nhóm duyệt rõ ràng. **Miễn `input_snapshot_dt` chỉ cho những legacy được duyệt**; không bịa trường snapshot hoặc gắn nhãn `immutable_verified` như record sau PR #48. Danh sách/chứng cứ record được chấp nhận phải có tham chiếu có thể kiểm toán và fingerprint trong `META`/run provenance (không xây bảng manifest riêng). Khi bằng chứng không đủ, đánh dấu `legacy_unverified` và không chấm.
6. **Fail-closed trên từng record:** chính sách legacy đã chốt, nhưng record nào không vượt checklist/không có trong danh sách đã duyệt thì **loại khỏi `n_obs`**, tương đương `POST_CUTOVER_ONLY` đối với record đó; chỉ các record hậu cutover đạt điểm 4 được chấm bình thường. Không thay đổi dữ liệu phát hành cũ hoặc backfill. `first_eligible_base_date` là ngày gốc **có ít nhất một cặp thực sự được chấm**, không hardcode ngày 27/10.
7. Theo ADR/release, khi champion của một asset đổi thì job chỉ chấm forecast của **model mới từ `CHAMPION_EFFECTIVE_BASE_DATES[asset]`** (map authoritative tại `infra/app.py`, gắn với ADR/release), 56 ngày window vẫn giữ nguyên; asset khác không bị reset. Challenger S1a được xét riêng mục 3.5.

**Checklist audit legacy trước khi tính `n_obs` (evidence xuất trước 02/11):** phạm vi các asset/base_date, `created_at` và lịch, bằng chứng không có manual/rewrite đã kiểm, nguồn kiểm `publication_as_of`/input-as-of, người xác nhận, thời điểm phê duyệt và fingerprint/run reference. Đây là *ngoại lệ nghiên cứu/vận hành có kiểm soát*, không được suy ngầm từ việc nhìn thấy timestamp đúng lịch. Không cần tái dựng CloudWatch 56 ngày để complete một run MVP.

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

**Quyết định 30/10:** Khải chốt `LEGACY_ACCEPT_WITH_EVIDENCE` **chỉ đối với từng record có bằng chứng được duyệt**; không có bằng chứng thì loại khỏi scoring. Không suy ra rằng mọi record 27/10+ đã được duyệt. Fallback `POST_CUTOVER_ONLY` áp dụng cho record không xác minh được. Trong comment cuối Khải gọi đề xuất nhận legacy là “phương án B”, còn RFC v4.4 từng gọi cùng nội dung là “phương án A”; từ v4.5 **bỏ ký hiệu A/B** để tránh chốt nhầm. `first_eligible_base_date` xuất phát từ record/horizon đủ điều kiện, có thể `null`. Theo Khải, **20/11** là mốc đạt 20 base_date *theo lịch* nếu chấp nhận legacy, **27/11** là dự kiến nếu chỉ sau cutover 31/10; **không phải ngày Dashboard chắc chắn `ready`** vì còn target maturity, cutoff, lần chạy job và dữ liệu thực tế. Không tự nâng evidence của legacy thành bằng chứng bất biến tuyệt đối.

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
| Tần suất | Chạy sau predict mỗi TUE–SAT lúc **13:45 UTC** (`cron(45 13 ? * TUE-SAT *)`), mỗi asset một evaluation run khi input READY; missing snapshot/actual → log và thoát, không promote |

**Quy ước cuối:** `evaluation_start=window_start=job_utc_date−55 ngày`, `evaluation_end=window_end=job_utc_date` (hai biên inclusive), **không** co hẹp theo ngày đầu/cuối thật sự có forecast. Metadata riêng `first_eligible_base_date`, `last_eligible_base_date` nếu có; `target_cutoff_date` riêng từng asset và có thể sớm hơn `evaluation_end`.

Ví dụ job **05/11/2026**: cửa sổ lý thuyết là **11/09–05/11/2026**; `first_eligible_base_date` được suy từ forecast **thật sự được chấm**, có thể là `26/10` nếu legacy được xác minh/duyệt, hoặc muộn hơn sau PR #48. Web hiển thị **“Kể từ <first_eligible_base_date>”**, tuyệt đối không hardcode 27/10; khi chưa có eligible row, trả `null` và không tạo mốc giả.

### 3.2. Luồng job `rolling_8w`

1. Đọc/khóa clean price snapshot/quality và actual đã công bố; nếu snapshot hoặc nguồn truth chưa sẵn sàng, log rồi **thoát không promote** (lần chạy sau thử lại), không ghi `COMPLETED` dựa trên snapshot dở dang. Xác định `target_cutoff_date` theo asset. Nhận cấu hình **`MODEL_VERSIONS[asset]` và `CHAMPION_EFFECTIVE_BASE_DATES[asset]`** từ `infra/app.py` CDK (Predict, Rolling và Accuracy API nhận **cùng hai mapping** qua biến môi trường); dùng effective base date gắn ADR/release để không trộn lịch sử khi đổi riêng một tài sản.
2. Dựng expected schedule từ trading calendar + TUE–SAT để **đếm** expected/missing, không gọi CloudWatch cho luồng MVP. Với chính sách `LEGACY_ACCEPT_WITH_EVIDENCE` đã chốt, chỉ nhận **từng record có audit/approval** theo §2.3 trước khi nhận vào `n_obs`; không gọi tất cả legacy là verified chỉ vì `created_at` hợp lịch. Chỉ chọn bản ghi `Forecasts` production thực có, hợp lệ theo mục 2.3–2.5; không tạo forecast thay thế.
3. Ghép forecast với actual, tính đúng log return và 7 horizons; kiểm `created_at`, `is_sample`, model per-asset đang deploy, ngày hiệu lực theo asset, cutoff, `input_snapshot_dt` bắt buộc sau cutover, và bằng chứng conditional-write (hoặc legacy review được duyệt). **Đọc S1a từ S3 độc lập**, không dùng sự có mặt của S1a để quyết định champion eligibility.
4. Lưu counts expected/published/missing và lý do loại forecast/horizon quan sát được. Missing row không có log thì reason chỉ là `missing_record_unclassified`; không gán skip/upstream đã xác minh.
5. Kiểm shape 7 q và `prob_up` (mismatch >`1e-6` chỉ audit), calendar/valid endpoints; không sửa nguồn. Common mask theo Accuracy Schema; tính 4 METRIC gốc và **derived `width_80_pct` trên từng cặp q10/q90** cùng mask của `width_80`, rồi gộp đúng trọng số `n_obs` cho horizon/overall; tính `n_obs`, `n_base_dates` từng h/overall; tính `first_eligible_base_date` từ **base_date eligible đầu tiên** của model đang hiệu lực.
6. Ghi **28 `METRIC` gốc** qua conditional PutItem; đóng băng `derived_metrics.width_80_pct` (overall/by-horizon, cùng input fingerprint) trong run `META` để API trả trực tiếp mà không thêm hàng `METRIC`/h=0; chốt `META` status/28 row hashes/`run_id`, snapshot/version, cutoff, `MODEL_VERSIONS[asset]` và effective date, eligible-pair evidence, counts và `undefined_reason` khi không có nhãn. Không yêu cầu log ref hay trạng thái full-schedule verified.
7. Chuyển `META` sang `COMPLETED` chỉ sau khi validation nội dung thành công. Sau đó conditional `UpdateItem` **`STATE`/`LATEST_COMPLETED`** theo `latest_run_order` tăng, tuyệt đối không công bố run dở.
8. **Nhánh ADR-0011:** chấm champion–S1a trên paired common mask và ghi **Parquet nội bộ `eval/shadow_eval/`** theo mục 4.6; shadow thiếu/lỗi không chặn champion `COMPLETED`, không cập nhật `STATE` và không xuất public API.

**Giới hạn rollout:** khi đổi champion qua ADR/CDK, cập nhật cấu hình API và rolling đồng bộ với predict; API chỉ trả run mà `META.model_version` trùng `MODEL_VERSIONS[asset]` hiện tại, nếu pointer cũ không phù hợp thì `not_ready`. Không phục hồi forecast lịch sử hoặc tính lại Validation 2019.

### 3.3. Metric và `n_obs`

| Metric | Định nghĩa | Ghi chú |
|---|---|---|
| `coverage_80` | `mean(q10 <= y <= q90)` trên cặp return hợp lệ | Đếm số hit/tổng số cặp; mục tiêu danh nghĩa 80% |
| `width_80` | `mean(q90 − q10)` | Một trong 4 metric gốc, lưu `log_return`, không dùng giá trị này để tính simple-return width từ trung bình |
| `width_80_pct` (derived) | `mean_i[100 × (exp(q90_i) − exp(q10_i))]` trên **cùng tập cặp của `width_80`** | `unit=percent` (`4.2` nghĩa 4,2%); tính **trước khi tổng hợp**; ghi dữ liệu dẫn xuất vào run `META`, không thêm hàng `METRIC` thứ 29 hoặc sửa Accuracy Schema; Web dùng trường này |
| `sign_accuracy` | Dấu của q50 đúng dấu y, loại trường hợp dấu bằng 0 theo schema | Chỉ hiển thị cùng `up_rate` |
| `up_rate` | `mean(y>0)` trên common mask | Có thể có `n_obs` khác sign accuracy |
| Các metric khác | Theo Accuracy Schema | Lưu khi có đủ dữ liệu; không bắt buộc hiển thị trên web MVP |

`overall.coverage_80` = tổng số hit ở tất cả h / tổng số cặp đủ điều kiện. Không lấy trung bình không trọng số của 7 tỷ lệ và không tạo hàng `h=0` trong Accuracy. Các horizons có thể cùng `base_date`, nên `n_obs` cặp không phải số ngày quan sát độc lập.

**Ngưỡng hiển thị cuối cùng đã được Khải chốt (D06/D07/D11):** tối thiểu **20 `base_date` khác nhau có ít nhất một cặp đã có nhãn và được tính cho `overall.coverage_80`**. Trước ngưỡng: **mọi metric ở `overall`** (`coverage_80`, `width_80`, `width_80_pct`, `sign_accuracy`, `up_rate`) vẫn có `value` nội bộ khi tính được, nhưng **`display_value=null`, `display_status=insufficient_data`**. Khi đủ ngưỡng, metric có `status=ok` nhận `display_value` và `display_status=ready`; metric không tính được vẫn `display_value=null` và `display_status=undefined`. `not_ready` áp dụng khi không có completed run đúng champion. **Web chỉ đọc `display_value` và `display_status`**, không dùng `value` để vượt ngưỡng; riêng độ rộng chỉ chọn `width_80_pct`. `n_base_dates` để quyết định ngưỡng là số distinct base_date chung đã có cặp chấm coverage hợp lệ, **không lấy riêng số ngày/mẫu của mỗi metric**. Từng h chỉ hiển thị X/Y, các `display_value` theo h để null với `display_status=counts_only`, không công bố tỷ lệ %. `n_obs=0` có `status=undefined`, `value=null`.

Ước tính cũ (05/11 có 7 base_date/28 cặp; 22/11 có 19 base_date) chỉ là phép đếm phụ thuộc chấp nhận legacy. Khải tính bằng lịch NYSE/CME: **20/11** có thể đạt 20 phiên/base_date trên lịch nếu nhận legacy, hoặc khoảng **27/11** nếu chỉ chấm sau deploy PR #48 dự kiến 31/10. **Không suy ra `ready` ngay ngày 20/11/27/11:** một `base_date` chỉ được đếm khi forecast đó đã được phát hành/duyệt, có ít nhất một horizon đã có target thực tế hợp lệ trước `target_cutoff_date` và **job hằng ngày đã đánh giá**. Số 20 không là 20 quan sát thống kê độc lập; API trả `n_obs` và `n_base_dates` để diễn giải.

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

Mốc hiệu lực **cũng khai báo tại `infra/app.py`** theo từng asset (giá trị cụ thể phụ thuộc ADR/deploy, ví dụ dưới đây không phải mốc production đã duyệt):

```python
CHAMPION_EFFECTIVE_BASE_DATES = {
    "gold": "<approved-effective-base-date>",
    "silver": "<approved-effective-base-date>",
    "brent": "<approved-effective-base-date>",
    "wti": "<approved-effective-base-date>",
}
```

CDK truyền cả hai dưới dạng JSON env vars cho Predict, Rolling job và `/accuracy` Lambda. Predict ưu tiên `MODEL_VERSIONS[asset]`, chỉ fallback sang `MODEL_VERSION` cũ nếu env mới chưa được cấu hình trong giai đoạn chuyển đổi; **không** dùng fallback để lén đổi champion. Khải thực hiện Predict mapping trong PR #53, Tiến phụ trách CDK env mapping và test đồng bộ 4 asset (bao gồm effective dates).

Predict, Rolling và Accuracy API phải nhận **cùng hai mapping `MODEL_VERSIONS` / `CHAMPION_EFFECTIVE_BASE_DATES` và release config**, có CDK test xác nhận từng asset và không thiếu asset. Với asset `a`, champion là `MODEL_VERSIONS[a]`; ADR/deploy có thể đổi **chỉ một asset** nếu K4 đạt ở asset đó, không kéo theo ba asset còn lại. Mốc `CHAMPION_EFFECTIVE_BASE_DATES[a]` được khai báo tại `infra/app.py`, đối chiếu ADR/release và áp dụng từ phiên base_date đầu tiên có hiệu lực; không suy diễn từ Accuracy `STATE`. Trong giai đoạn tất cả cùng baseline, mapping có cùng giá trị nhưng contract vẫn dùng hình thức per-asset.

**Predict không đọc Accuracy**, không có `champion_release_operator` hoặc `champion_generation` trong `STATE`. Item `STATE` **chỉ** trỏ `LATEST_COMPLETED` (`latest_run_pk`, `latest_run_id`, `latest_run_order`). API cho `/accuracy/{asset}` chỉ đọc run `META.model_version == MODEL_VERSIONS[asset]` và `base_date >= CHAMPION_EFFECTIVE_BASE_DATES[asset]` đối với các cặp đã chấm của run. Nếu pointer còn trỏ run model cũ, **trả `not_ready`**, không công bố kết quả sai asset/model; job mới bắt đầu thống kê từ effective date của **asset đó**, không backfill model mới từ các forecast cũ. `evaluation_start/end` vẫn là cửa sổ 56 ngày, không tự co theo effective date.

**Đổi model và concurrent rollout:** `latest_run_order` ngăn rollback theo thời gian nhưng không tự giải quyết writer đời cũ chạy sau cùng với order mới hơn. Release phải đồng bộ CDK mapping ở Predict/Rolling/API, drain writer cũ theo asset trước khi publish mới, và kiểm thử fail-closed nếu các Lambda chưa đồng bộ. Condition của pointer phải bảo vệ chính run/order đã `COMPLETED`; không tuyên bố chỉ IAM/condition đủ làm release đồng bộ. Khi chuyển một asset, API ba asset còn lại vẫn có thể trả Accuracy của champion riêng mà không bị reset.

**Ranh giới S1a khi K4 được chọn:** `s1a-l094` theo ADR-0011/PR #49 là biến thể co giãn **phân vị `baseline-q252`**; nếu champion một asset chuyển sang K4, **không tự dùng K4 làm đầu vào nhưng vẫn gắn tên S1a**. Với asset đó, tạm không chấm paired S1a (`shadow_not_applicable_model_change`) hoặc phải có ADR/phiên bản challenger mới; nhánh champion Accuracy tiếp tục chạy độc lập. Các asset còn baseline vẫn có thể chấm S1a như cũ.

### 3.5. Chấm champion–challenger trên cùng tập quan sát [ADR-0011]

**Hai luồng tách biệt, chung lịch Rolling TUE–SAT:** (A) **Accuracy production** chấm *mọi* forecast champion đủ điều kiện theo mục 2–3 và ghi DynamoDB cho `/accuracy/{asset}`; (B) **shadow paired comparison** chỉ chấm phần giao champion–S1a cho báo cáo nội bộ. S1a không tham gia `STATE`, không cập nhật champion pointer, không ảnh hưởng ngưỡng 20 ngày của Dashboard. Khi ADR đổi champion tương lai được duyệt, phát hành production vẫn phải tuân theo contract Predict/Forecasts; không tự nâng bản shadow S3 thành forecast production.

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
| `META` | `RUN#<asset>#<model_version>#<run_id>` | `META` | Run status, model version của **run** (không nguồn champion), fingerprints, window/cutoff, snapshot/evidence của các cặp được chấm, 28 expected metric keys, aggregate/counts và **derived `width_80_pct`** (không phải hàng METRIC) |
| `METRIC` | **Cùng PK với META** | `METRIC#<sample>#<evaluation_kind>#<evaluation_start>#<evaluation_end>#<target_cutoff_date>#H<h>#<metric>` | Một item theo h/metric và khóa logic; có `payload_hash` |

**Thuật ngữ thống nhất:** `latest_run_pk`, `latest_run_id`, `latest_run_order` trong `STATE` **chính là cơ chế `LATEST_COMPLETED` của MVP**. Không có item `SK=LATEST`, partition champion riêng, hay bảng champion khác. `STATE` là tên kỹ thuật của item; `LATEST_COMPLETED` là vai trò của ba trường pointer.

`run_id` định danh evaluation run, không phải forecast run: `run_id = <job_utc_date>-<sha256(canonical(asset, MODEL_VERSIONS[asset], CHAMPION_EFFECTIVE_BASE_DATES[asset], job_date, revision, config_hash, immutable_snapshot_identity, target_cutoff_date, eligible_record_fingerprint))[:20]>`. Fingerprint và derived-metric payload/hash lưu đầy đủ trong META để tránh phụ thuộc hash rút gọn. `run_order=<YYYYMMDD>#<revision_4_digits>`; correction sau run completed dùng revision tăng có audit và `run_id` mới; retry cùng run/input giữ nguyên revision. Cùng `run_order` khác run là **conflict**, không promote.

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
3. Đủ **28 item METRIC** = 7 horizons × (`coverage_80`, `width_80`, `sign_accuracy`, `up_rate`); mỗi item có count/hash và `status=ok` hoặc `undefined/not_applicable` có reason hợp lệ. Chỉ chấm quan sát đủ điều kiện, `n_obs`, `n_base_dates`, overall pooled hit/count, **`width_80_pct` derived theo cặp trên cùng mask và hash đã đóng băng**, expected/published/missing counters nhất quán. `overall` trong META, không có `h=0`.
4. Không còn lỗi đọc snapshot, tính toán, conflict hoặc ghi metric chưa xử lý; strong read xác nhận 28 keys/hashes đúng trước khi complete.

**`COMPLETED` không yêu cầu `n_obs>=1` hoặc `n_base_dates>=20`.** Run với `n_obs=0` được `COMPLETED` nếu đã ghi 28 metric rows `undefined` và đúng số đếm, không bịa nhãn. `display_status=insufficient_data` trên **toàn bộ overall** khi chưa đủ 20 `base_date` có cặp hợp lệ; `ready` là UX, không phải run status. `issuance_evidence_status=verified_eligible_rows` chỉ áp dụng khi có **các cặp đã chấm**; nếu `n_obs=0`, dùng `no_eligible_rows`, không gắn nhãn verified cho dữ liệu không tồn tại; `schedule_evidence_status=not_audited_mvp` không có nghĩa kỳ phát hành nào cũng được xác minh.

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

## 5. API `GET /accuracy/{asset}` [QUYẾT ĐỊNH THIẾT KẾ, CHỜ CONTRACT]

### 5.1. Request

`GET /accuracy/wti`, với Cognito ID token như API hiện tại; asset thuộc `gold`, `silver`, `brent`, `wti`. MVP cố định `evaluation_kind=rolling_8w`, `sample=all` và **chỉ champion** theo `MODEL_VERSIONS[asset]` của CDK/API; `STATE` chỉ trỏ `LATEST_COMPLETED`. S1a shadow và paired reports không có route public và không nằm trong JSON Accuracy. Không hỗ trợ chọn model/run khác qua public query params trong MVP; request tham số không hỗ trợ bị từ chối hoặc bỏ qua theo hợp đồng API hiện có (ưu tiên từ chối để tránh hiểu nhầm).

### 5.2. JSON mẫu cho Tiến/Web (trước 02/11)

> **Fixtures minh họa giao diện, KHÔNG phải số liệu production.** Bản chính thức phải được duyệt trong PR contract. `by_horizon` đủ h=1..7 với **4 metric gốc + `width_80_pct` dẫn xuất**; mỗi metric có `n_obs`, `status`, các giá trị hiển thị phải qua `display_value`/`display_status`. Từng horizon chỉ dùng counts cho Web, không hiện tỷ lệ. Ba JSON dưới đây là **đề xuất cập nhật đồng bộ cho PR #62**; giá trị `width_80_pct` synthetic được dựng từ q10/q90 giả định theo cặp, không tính bằng `100×width_80` có sẵn.

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
      "status": "undefined",
      "display_status": "not_ready",
      "display_value": null
    },
    "width_80_pct": {
      "value": null,
      "n_obs": 0,
      "unit": "percent",
      "status": "undefined",
      "display_status": "not_ready",
      "display_value": null
    },
    "sign_accuracy": {
      "value": null,
      "n_obs": 0,
      "status": "undefined",
      "display_status": "not_ready",
      "display_value": null
    },
    "up_rate": {
      "value": null,
      "n_obs": 0,
      "status": "undefined",
      "display_status": "not_ready",
      "display_value": null
    }
  },
  "by_horizon": [
    {"h": 1,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}},
    {"h": 2,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}},
    {"h": 3,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}},
    {"h": 4,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}},
    {"h": 5,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}},
    {"h": 6,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}},
    {"h": 7,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}}
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
      "status": "ok",
      "display_status": "insufficient_data",
      "display_value": null
    },
    "width_80_pct": {
      "value": 2.49382275,
      "n_obs": 14,
      "unit": "percent",
      "status": "ok",
      "display_status": "insufficient_data",
      "display_value": null
    },
    "sign_accuracy": {
      "value": 0.375,
      "n_obs": 8,
      "status": "ok",
      "display_status": "insufficient_data",
      "display_value": null
    },
    "up_rate": {
      "value": 0.357143,
      "n_obs": 14,
      "status": "ok",
      "display_status": "insufficient_data",
      "display_value": null
    }
  },
  "by_horizon": [
    {"h": 1,"coverage_80": {"covered_count": 3,"n_obs": 4,"display_value": null,"display_status": "counts_only","n_base_dates": 4,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 4,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 4,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.333333,"n_obs": 3,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.5,"n_obs": 4,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 2,"coverage_80": {"covered_count": 2,"n_obs": 3,"display_value": null,"display_status": "counts_only","n_base_dates": 3,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 3,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 3,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.5,"n_obs": 2,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.333333,"n_obs": 3,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 3,"coverage_80": {"covered_count": 2,"n_obs": 3,"display_value": null,"display_status": "counts_only","n_base_dates": 3,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 3,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 3,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.5,"n_obs": 2,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.333333,"n_obs": 3,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 4,"coverage_80": {"covered_count": 1,"n_obs": 2,"display_value": null,"display_status": "counts_only","n_base_dates": 2,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 2,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 2,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.0,"n_obs": 1,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.5,"n_obs": 2,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 5,"coverage_80": {"covered_count": 1,"n_obs": 1,"display_value": null,"display_status": "counts_only","n_base_dates": 1,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 1,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 1,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.0,"n_obs": 1,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 6,"coverage_80": {"covered_count": 1,"n_obs": 1,"display_value": null,"display_status": "counts_only","n_base_dates": 1,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 1,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 1,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.0,"n_obs": 1,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 7,"coverage_80": {"covered_count": 0,"n_obs": 0,"display_value": null,"display_status": "counts_only","n_base_dates": 0,"status": "undefined"},"width_80": {"value": null,"n_obs": 0,"unit": "log_return","status": "undefined","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": null,"n_obs": 0,"unit": "percent","status": "undefined","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"},"up_rate": {"value": null,"n_obs": 0,"status": "undefined","display_value": null,"display_status": "counts_only"}}
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
      "display_value": 0.7755102,
      "status": "ok",
      "display_status": "ready"
    },
    "width_80": {
      "value": 0.025,
      "n_obs": 147,
      "unit": "log_return",
      "status": "ok",
      "display_status": "ready",
      "display_value": 0.025
    },
    "width_80_pct": {
      "value": 2.49382275,
      "n_obs": 147,
      "unit": "percent",
      "status": "ok",
      "display_status": "ready",
      "display_value": 2.49382275
    },
    "sign_accuracy": {
      "value": 0.485714,
      "n_obs": 140,
      "status": "ok",
      "display_status": "ready",
      "display_value": 0.485714
    },
    "up_rate": {
      "value": 0.489796,
      "n_obs": 147,
      "status": "ok",
      "display_status": "ready",
      "display_value": 0.489796
    }
  },
  "by_horizon": [
    {"h": 1,"coverage_80": {"covered_count": 19,"n_obs": 24,"display_value": null,"display_status": "counts_only","n_base_dates": 24,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 24,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 24,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.478261,"n_obs": 23,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.5,"n_obs": 24,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 2,"coverage_80": {"covered_count": 18,"n_obs": 23,"display_value": null,"display_status": "counts_only","n_base_dates": 23,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 23,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 23,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.5,"n_obs": 22,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.478261,"n_obs": 23,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 3,"coverage_80": {"covered_count": 17,"n_obs": 22,"display_value": null,"display_status": "counts_only","n_base_dates": 22,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 22,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 22,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.47619,"n_obs": 21,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.5,"n_obs": 22,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 4,"coverage_80": {"covered_count": 16,"n_obs": 21,"display_value": null,"display_status": "counts_only","n_base_dates": 21,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 21,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 21,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.5,"n_obs": 20,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.47619,"n_obs": 21,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 5,"coverage_80": {"covered_count": 16,"n_obs": 20,"display_value": null,"display_status": "counts_only","n_base_dates": 20,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 20,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 20,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.473684,"n_obs": 19,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.5,"n_obs": 20,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 6,"coverage_80": {"covered_count": 15,"n_obs": 19,"display_value": null,"display_status": "counts_only","n_base_dates": 19,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 19,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 19,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.5,"n_obs": 18,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.473684,"n_obs": 19,"status": "ok","display_value": null,"display_status": "counts_only"}},
    {"h": 7,"coverage_80": {"covered_count": 13,"n_obs": 18,"display_value": null,"display_status": "counts_only","n_base_dates": 18,"status": "ok"},"width_80": {"value": 0.025,"n_obs": 18,"unit": "log_return","status": "ok","display_value": null,"display_status": "counts_only"},"width_80_pct": {"value": 2.49382275,"n_obs": 18,"unit": "percent","status": "ok","display_value": null,"display_status": "counts_only"},"sign_accuracy": {"value": 0.470588,"n_obs": 17,"status": "ok","display_value": null,"display_status": "counts_only"},"up_rate": {"value": 0.5,"n_obs": 18,"status": "ok","display_value": null,"display_status": "counts_only"}}
  ],
    "data_status": "ready",
    "disclaimer": "Dự báo chỉ mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

### 5.3. Quy ước API

- `overall.coverage_80` gộp theo số cặp; `by_horizon` trả đủ h=1..7, mỗi metric có `n_obs` và trạng thái riêng; `n_base_dates` là số base date **khác nhau có cặp hợp lệ cho scope/metric tương ứng**, không phải số cặp; **`window.first_eligible_base_date` là trường bắt buộc** (ISO date hoặc `null`), tính từ base_date đầu tiên **có ít nhất một cặp được chấm**, của champion `MODEL_VERSIONS[asset]` hiện tại, không sớm hơn champion effective date. Web hiển thị “Kể từ <ngày>” động; không hardcode 27/10, không thay bằng timestamp phát hành.
- Dashboard MVP hiển thị `coverage_80`, **`width_80_pct`**, `sign_accuracy`, `up_rate` **cho champion production**. `width_80` gốc vẫn được lưu/trả như metric nghiên cứu (log return) nhưng Web chỉ hiển thị `width_80_pct` (percent). Với `gold/silver`, ADR-0005 (b) cấm hiển thị chuỗi giá Yahoo; các chỉ số Accuracy và dự báo return %/xác suất tăng không phải chuỗi giá và tiếp tục được phép hiển thị. Không hiển thị `pinball_skill=0` của champion `baseline-q252` so với chính baseline, không trả S1a/paired report trong Accuracy API. Derived width percent được đóng băng cùng fingerprint của run; metric khác vẫn được lưu nếu tính được; shadow `pinball_skill` chỉ trong artifact nội bộ.
- `width_80` gốc đo `mean(q90 − q10)` trên log return; **`width_80_pct` mới** đo `mean_i[100 × (exp(q90_i) − exp(q10_i))]` trên **từng cặp hợp lệ rồi mới tổng hợp** (không bằng `100×width_80`, cũng không bằng `100×(exp(mean_q90)−exp(mean_q10))` trong dữ liệu tổng quát). `unit="percent"`: `4.2` = 4,2%. Derived metric dùng **cùng common mask/n_obs** với `width_80`; lưu trong `META.derived_metrics` (overall và per-h) cùng fingerprint/run để API trả trực tiếp, **không tạo metric row thứ 29**. Web/chatbot/slide dùng **`width_80_pct.display_value` do API trả**, không tự dùng `exp` hay tự chuyển từ log-width. `sign_accuracy` và `up_rate` luôn đi cặp nhưng không mặc định có cùng mẫu số.
- **Tất cả metric `overall`** có `display_value` và `display_status` theo **cùng ngưỡng ≥20 distinct `base_date` có cặp chấm coverage hợp lệ**; dưới ngưỡng đồng loạt `display_value=null`, không sửa `value`/`status` nội bộ. Web chỉ đọc `display_value`, không hiển thị các `value` nội bộ của `collecting` qua field phụ. Các `by_horizon` chỉ hiển thị counts (`display_value=null`, `display_status=counts_only`), kể cả `width_80_pct` và khi `data_status=ready`.
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

| Tình huống | Quy tắc MVP v4.6 |
|---|---|
| `is_sample=true` hoặc `created_at` trước 27/10 12:00Z | Loại khỏi rolling production |
| Forecast trước cutover PR #48 / không có `input_snapshot_dt` | **Policy đã chốt có điều kiện**: chỉ nhận 27/10+ đúng lượt 12:15–13:30 UTC **và** từng record có evidence đã duyệt (không run tay/overwrite, model/is_sample, snapshot-as-of); không đủ → `legacy_unverified`/`issuance_unverified`, loại khỏi `n_obs` |
| Phát hành 27/10 cho `base_date=26/10` | Vẫn xét nếu đáp ứng nguồn phát hành bất biến và các kiểm tra khác |
| `h=1` phát hành ngày target | So timestamp cutoff 13:30 UTC, không so ngày; bảo vệ input-as-of tại predict |
| Đã có production cùng `(asset, base_date)` | Predict conditional write không ghi đè; `ConditionalCheckFailedException` → log `PREDICT_ALREADY_PUBLISHED`, không `GetItem`/so payload/alarm giả; khác với Accuracy METRIC conflict |
| Một ngày theo calendar TUE–SAT không có Forecasts row | Tăng missing counter, không chấm, reason `missing_record_unclassified`; **không chặn `COMPLETED`**, không gán đã xác minh upstream/skip |
| Log CloudWatch thiếu/hết 30 ngày | Không là gate completion Rolling MVP; **riêng bằng chứng legacy** Tiến xuất/đính kèm PR Contract trước 02/11 do log predict chỉ giữ 30 ngày; không bắt buộc tăng retention 90 ngày |
| `prob_up` lệch >`1e-6` | Chỉ ghi `prob_up_mismatch`, không loại, không ghi đè q/`prob_up` |
| `width_80_pct` ở API | `mean[100×(exp(q90)−exp(q10))]` **từng cặp**, lưu derived META cùng mask với `width_80`; Web chỉ dùng `display_value` khi đủ ngưỡng, không tự tính |
| Job 13:45 UTC TUE–SAT nhận snapshot/actual chưa sẵn sàng | Log và thoát, **không COMPLETED/promote**; retry 0; lượt sau tự tính lại khi input READY |
| Target chưa published/chưa đến cutoff | Pending; không tăng `n_obs` |
| Giá endpoint thiếu/rejected/không dương | Loại cặp theo ADR-0008, không nội suy endpoint |
| Thiếu phiên giữa endpoints | Không tự loại nếu hai endpoint hợp lệ; ghi số phiên thiếu |
| `input_snapshot_dt` sai/thiếu ở champion sau cutover | Record ineligible; trước cutover chỉ được miễn nếu **legacy verification** được họp thông qua và record đã chứng minh eligible |
| `n_obs=0`, đủ 28 item undefined và dữ liệu nhất quán | Vẫn có thể `COMPLETED`; API `collecting` hoặc chưa đủ dữ liệu tùy run/pointer, không hiện tỷ lệ |
| Chưa đủ 20 base_date có cặp coverage | **Mọi overall display_value đều null** (coverage, width, width_pct, sign, up); chỉ counts và số ngày, API vẫn trả `first_eligible_base_date` hoặc null; web không hardcode ngày |
| Đổi champion một asset theo ADR/CDK `MODEL_VERSIONS[asset]` | Không cập nhật champion/generation ở STATE; API đối chiếu META model **per-asset**, mismatch → `not_ready`; job chỉ chấm từ release effective base_date của asset đó; các asset khác giữ nguyên |
| Writer đời cũ sau deploy, run_order mới hơn | Không có quyền đổi champion; pointer có thể bị đẩy sai model nhưng API fail-closed; quy trình release phải dừng writer cũ và có test cutover |
| Snapshot correction/run hỏng | New revision/run nếu cần correction; không overwrite metric/run đã hoàn thành |
| S1a chưa phát hành/thiếu/lỗi | Shadow paired không chặn champion Accuracy; không backfill |
| S3 shadow object ghi muộn | Check LastModified/target cutoff; nếu unverified thì loại paired mask. `ListBucket` theo prefix cho phép kiểm tra bổ sung bằng ListObjectsV2 khi 403 từ GetObject còn mơ hồ |
| S1a báo cáo | **Parquet `eval/shadow_eval/run_id=<run_id>/`**; writer riêng với input JSON `eval/shadow/s1a-l094/`; không API/DynamoDB |
| Validation/test lịch sử | Không lẫn rolling production, không backfill |

---

## 8. Ma trận quyết định v4.6 — chốt theo phản hồi của Khải ngày 30/10

Khải đã xác nhận các điểm của Tiến, đặc biệt 7 nội dung cập nhật theo cuộc họp 30/10. **Thiết kế đã đủ điều kiện chuyển sang PR Contract** nhưng **không đồng nghĩa GitHub đã có tất cả approving reviews, không đồng nghĩa AWS đã triển khai hoặc dữ liệu legacy đã được kiểm toán xong**. Giữ nguyên các quyết định kiến trúc D01–D24 từ v4.5 trừ các thay đổi đã chỉ rõ.

| ID | Quy tắc / kiến trúc v4.6 | Owner / tình trạng |
|---|---|---|
| D01 | 56 ngày lịch UTC inclusive theo `base_date`, giữ evaluation_start/end | Khải/Long — giữ |
| D02 | `created_at>=27/10 12:00Z`; `LEGACY_ACCEPT_WITH_EVIDENCE` cho **từng record trước cutover** qua audit và danh sách đã duyệt; thiếu evidence loại khỏi `n_obs`. Tiến xuất chứng cứ trước 02/11 | Khải/Tiến/Long — **policy chốt; audit record chờ** |
| D03 | Job **hằng ngày TUE–SAT lúc 13:45 UTC** theo `cron(45 13 ? * TUE-SAT *)`, sau predict; readiness fail → log/thoát, không promote; timeout 300s, Scheduler retry=0, không reserved concurrency | Tiến CDK/Alarm; Long job — **chốt lịch, chưa deploy** |
| D04 | PR #48 Forecasts conditional PutItem, sample→production; already published log, không GetItem/so payload | Khải/Tiến — giữ |
| D05 | Bảng Accuracy `PK/SK` STATE pointer + RUN/META/28 METRIC; không GSI/Scan/TTL | Tuấn — giữ |
| D06 | Tất cả metric **`overall`** có `display_value`/`display_status`, cùng gate ≥20 distinct base_date đã có cặp coverage hợp lệ; `status`/`value` nội bộ giữ riêng | Khải/Tiến/Long — **chốt** |
| D07 | `/accuracy/{asset}` overall/h1..7: 4 metric gốc + `width_80_pct` derived; 3 JSON fixtures PR #62 (`not_ready/collecting/ready`); `first_eligible_base_date` ISO/null; HTTP 200 not_ready | Tuấn/Tiến/Long — **chốt schema, chờ Contract** |
| D08 | `/forecast-history/{asset}` riêng, phase 2 | Tuấn/Tiến — giữ |
| D09 | Historical pairs on-demand Forecasts + clean snapshot; không bảng history riêng | Tuấn/Long — giữ |
| D10 | **`MODEL_VERSIONS` + `CHAMPION_EFFECTIVE_BASE_DATES`** cùng trong `infra/app.py`, truyền JSON env cho Predict/Rolling/API; CDK test đủ 4 asset và cùng map; Khải sửa Predict trong PR #53 với fallback `MODEL_VERSION` cũ | Khải Predict, Tiến CDK, Tuấn API — **chốt** |
| D11 | Giữ `width_80=mean(q90−q10)` log; **`width_80_pct=mean_i[100×(exp(q90_i)−exp(q10_i))]`** trên cùng mask, `unit=percent`; Web chỉ dùng pct từ API; per-h chỉ counts. `width_80_pct` derived META, **28 metric items không đổi** | Khải/Tiến/Long — **chốt công thức; representation trong META là lựa chọn MVP đề xuất để contract hóa** |
| D12 | Snapshot correction → revision/run mới; record cũ bất biến | Tuấn/Long — giữ |
| D13 | Validation 2019 tách rolling, không sửa DM-HAC/gap policy trước 22/11 | Khải/Long — giữ/hoãn DM |
| D14 | Calendar + TUE–SAT chỉ expected/missing; Forecasts conditional write hoặc *verified legacy* mới là evidence cho cặp chấm; không dùng manifest/log gate | Khải/Tuấn — giữ |
| D15 | Missing record chỉ đếm, không chấm/không chặn COMPLETED; CloudWatch chỉ dùng audit legacy riêng trước 02/11, không thành dependency thường kỳ | Khải/Tuấn/Tiến — giữ |
| D16 | `prob_up` mismatch >1e-6 chỉ log, không loại/overwrite | Khải/Tuấn — giữ |
| D17 | External import ngoài rolling MVP | Khải/Tuấn — giữ |
| D18 | Record hậu cutover có `input_snapshot_dt` và conditional provenance; record thiếu field chỉ **ứng viên legacy** và phải có evidence/approval. Tiến ghi event deploy và lượt predict 31/10 nếu thực tế | Khải/Tiến/Long — **policy chốt; deploy/audit chờ** |
| D19 | META/28 METRIC immutable, RUNNING→VALIDATING→COMPLETED, STATE/LATEST_COMPLETED monotonic; derived `width_80_pct` trong run META, có fingerprint và không thêm hàng metric | Tuấn/Long — giữ + derived |
| D20 | IAM writer Accuracy/snapshot/shadow scoped, `ListBucket` theo prefix; API read-only; Predict không GetItem Accuracy | Tuấn/Tiến — giữ; IAM CDK review trước deploy |
| D21 | Champion Forecasts + S1a JSON `eval/shadow/s1a-l094/dt=<UTC>/<asset>.json`, không retrain | Khải/Long/Tiến — giữ |
| D22 | Paired common mask, pinball_skill/coverage/width của hai model, không backfill | Long/Khải — giữ |
| D23 | So sánh shadow Parquet nội bộ `eval/shadow_eval/run_id=<run_id>/`, immutable, không public API | Long/Tuấn — giữ |
| D24 | Shadow lỗi/thiếu không chặn champion; ADR riêng mới đổi champion | Khải/Long — giữ |

**Hiệu lực và đóng PR:** Đây là kết quả chốt nội dung theo comment Khải/Tiến ngày 30/10; **PR #45 review-only, không merge**, sau khi chuyển sang PR Contract và hoàn tất review/merge Contract thì đóng #45 `Closed — Not Merged`. Issue #23.2 hoàn tất ở mức tài liệu sau khi contract được merge, không mặc định implementation đã done.

---

## 9. Acceptance criteria và kế hoạch kiểm thử — điều kiện phê duyệt kiến trúc

### 9.1. Contract/invariants bắt buộc

- [ ] Evaluation `rolling_8w` có đúng khóa logic Accuracy Schema, 7 horizons, 28 METRIC items, overall trong META; validation/test vẫn S3 Parquet `eval/`.
- [ ] `STATE` **chỉ giữ** ba trường `latest_run_pk`, `latest_run_id`, `latest_run_order` = **`LATEST_COMPLETED`**; không `champion_model_version`, `champion_generation`, `effective_base_date` hay item LATEST riêng. `META.model_version` phải trùng `MODEL_VERSIONS[asset]` của API/CDK lúc trả; ngày gốc đã chấm không sớm hơn effective date của asset.
- [ ] `Forecasts` production bất biến tại `(asset,base_date)` theo PR #48; conditional fail → `PREDICT_ALREADY_PUBLISHED` **không GetItem/so payload**, khác với Accuracy METRIC; legacy chỉ được chấm theo `LEGACY_ACCEPT_WITH_EVIDENCE` sau khi nhóm duyệt và từng record có audit reference. Không backfill.
- [ ] `run_id`/fingerprint khóa asset, model config, snapshot, eligible records, cutoff và revision; retry cùng payload no-op; khác payload conflict; metric chỉ conditional PutItem, không overwrite, không BatchWriteItem.
- [ ] `COMPLETED` cần đủ 28 METRIC rows, correct counts, snapshot/cutoff và issuance evidence **của cặp được chấm**; **không yêu cầu** CloudWatch logs, publication manifest, 90-day retention hoặc mọi kỳ expected có row. `n_obs=0`/undefined hợp lệ nếu đầy đủ 28 rows.
- [ ] Expected count dùng calendar/TUE–SAT; thiếu Forecasts row chỉ tăng `missing_count` và không khẳng định skip/upstream, không chặn completion. `schedule_evidence_status=not_audited_mvp`, tách khỏi `issuance_evidence_status=verified_eligible_rows`.
- [ ] `MODEL_VERSIONS` và **`CHAMPION_EFFECTIVE_BASE_DATES`** là **hai mapping per-asset tại `infra/app.py`** truyền JSON env cho Predict/Rolling/API, có CDK test đồng bộ đủ 4 asset và effective date; Predict không gọi `STATE`/Accuracy, API fail-closed theo asset nếu META version khác. Một asset đổi K4 không làm reset ba asset khác; S1a không được đổi định nghĩa ngầm.
- [ ] API `/accuracy/{asset}` có **4 metric gốc + `width_80_pct` dẫn xuất** (không tăng 28 METRIC), overall/by_horizon, `n_obs`,`n_base_dates`, `first_eligible_base_date` ISO/null; mọi metric overall có `display_value/display_status` theo ngưỡng 20 base dates đã có cặp; Web chỉ dùng `width_80_pct` tính theo từng q10/q90 và chỉ dùng display field. Đồng bộ 3 fixtures PR #62 trước 02/11.
- [ ] IAM chỉ Rolling writer cập nhật STATE pointer (không field champion); API reader chỉ GetItem/Query. `s3:ListBucket` được scope bằng `s3:prefix` đúng clean/shadow, adapter phân biệt missing với IAM 403 qua scoped ListObjectsV2 nếu cần; ưu tiên PK/attributes IAM và deny tests. Không champion operator.
- [ ] Predict đọc/ghi source S1a tại `eval/shadow/s1a-l094/*` theo PR #49/#51; Rolling writer ghi **Parquet `eval/shadow_eval/*`**; quyền Predict `eval/shadow/*` không được ghi vào báo cáo so sánh, API không đọc report.
- [ ] Shadow trên paired mask, không tác động champion Accuracy/API và không auto-switch. Không SageMaker/Step Functions retrain. **Lịch/owner được Khải/Tiến xác nhận**: Tuấn bảng/API/IAM, Long job, Tiến CDK Scheduler/Lambda/image/alarm, Khải Predict mapping. Scheduler TUE–SAT 13:45 UTC, timeout 300s, retry=0, no reserved concurrency; deploy trước 05/11, xác minh bằng CDK/IAM/smoke tests.

### 9.2. Functional tests — 48 trường hợp (T01–T48) cập nhật theo họp 30/10

| ID test | Điều kiện thử | Expected v4.6 |
|---|---|---|
| T01 | Key metric khác `run_id`, asset, model, sample, kind, window, cutoff, h hoặc metric | Không va chạm PK/SK và đủ logical key |
| T02 | GET accuracy 4 asset; run có 28 METRIC và Query nhiều page | GetItem STATE + Query RUN, không Scan/GSI, chỉ current `MODEL_VERSIONS[asset]` |
| T03 | Crash sau 27/28 METRIC | Chưa completed, không promote pointer, API không đọc partial |
| T04 | Retry đúng run fingerprint/metric | No-op / resume, không overwrite |
| T05 | Cùng PK/SK khác payload hoặc cùng run_order khác run_id | Conflict, giữ record gốc, pointer không tự đổi |
| T06 | Hai writers complete trái thứ tự, run_order B>A | Pointer monotonic trỏ B; không rollback |
| T07 | ADR/CDK đổi champion **chỉ `gold`** từ baseline sang K4, ba asset khác giữ baseline, STATE gold còn pointer cũ | `/accuracy/gold` → `not_ready`, ba asset khác vẫn trả kết quả; gold không trộn model hoặc tự backfill trước effective date |
| T08 | Run đủ 28 rows nhưng không có cặp có nhãn hợp lệ, derived `width_80_pct` undefined | COMPLETED được phép với 28 undefined + reasons, derived value null và counts đúng; không giả tỷ lệ |
| T09 | Thiếu metric row hoặc hash/count không nhất quán | Không COMPLETED hoặc promote |
| T10 | Lịch có ngày expected nhưng Forecasts không có row | missing_count tăng, bỏ qua ngày; **không** block COMPLETED vì thiếu record |
| T11 | Record Forecasts hợp lệ nhưng không đọc được CloudWatch logs | Vẫn chấm theo record + conditional immutability, không đòi log |
| T12 | Lịch 56 ngày có logs thiếu/hết hạn 30 ngày | `schedule_evidence_status=not_audited_mvp`; 28 rows đủ và cặp có evidence → COMPLETED |
| T13 | Record trước 27/10 12Z, sample hoặc backfill; legacy đúng lịch nhưng không có approval | Loại khỏi scoring; legacy riêng được xét T37/T38, không tự cho phép bởi timestamp |
| T14 | h=1 phát hành cùng target date 12:15Z, >13:30Z, DST | So timestamp, kiểm input-as-of |
| T15 | `input_snapshot_dt` sai/missing **sau cutover** PR #48 | Ineligible; legacy chỉ miễn sau audit/duyệt `LEGACY_ACCEPT_WITH_EVIDENCE` tại T38 |
| T16 | `prob_up` sai lệch 0, 1e-6, >1e-6 | >ngưỡng chỉ log, không sửa/loại một mình |
| T17 | Endpoint invalid/missing; intermediate missing | Theo ADR-0008, không fill endpoint; thiếu giữa không tự invalid |
| T18 | Tất cả metric overall, 0/19/20 base dates và nhiều horizons cùng base_date | Pool hit/count; **5 trường overall** cùng gate (4 metric + derived width_pct), 0/19 đều `display_value=null`, 20 có `status=ok` mới hiện; Web không đọc `value` để bypass |
| T19 | Sign zero-mask khác up_rate; width log return và derived percent | Metric n_obs riêng; `width_80` ở log, `width_80_pct` ở %, cùng mask/n_obs; không h=0 hoặc hàng METRIC thứ 29 |
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
| T40 | CDK **hai JSON env mappings** `MODEL_VERSIONS` và `CHAMPION_EFFECTIVE_BASE_DATES` đủ bốn asset cho Predict/Rolling/API; Predict fallback `MODEL_VERSION` cũ lúc chuyển | Cả ba nhận **hai map giống nhau**, đổi riêng gold không reset asset khác; fallback không âm thầm đổi champion, mismatch fail-closed |
| T41 | API `first_eligible_base_date` null/26-10/31-10 và Web khi có/lúc chưa có nhãn | ISO/null từ ngày gốc đầu **đã chấm**, không hardcode ngày phát hành, không sớm hơn champion effective date |
| T42 | Nhiều cặp có q10/q90 bất đối xứng, khác độ rộng; tính theo từng cặp và gộp horizon/overall | `width_80_pct=mean_i[100×(exp(q90_i)−exp(q10_i))]`; không thay bằng `100×mean(q90−q10)` hoặc exp trên mean; unit percent, h/overall weighted đúng, derived META fingerprint ổn định |
| T43 | JSON fixtures PR #62: 7 horizons, **4 metric gốc + `width_80_pct` derived**, overall gating `not_ready/collecting/ready` | Parse/schema đúng; mọi `overall` metric có `display_value/display_status`, `collecting` không rò tỷ lệ từ `value`; `by_horizon` chỉ counts, all synthetic aggregates/units nhất quán |
| T44 | CDK accuracy job **`cpaws-dev-accuracy-job`**, ECR predict khác CMD, Scheduler `cron(45 13 ? * TUE-SAT *)` UTC (20:45 VN), alarm Errors→SNS; input chưa READY | Scheduler retry 0, timeout 300s, **không reserved concurrency**; snapshot/actual thiếu → log/exit không promote; wiring/permissions/alarm test, mỗi asset one run |

| T45 | Champion mapping đổi **chỉ Brent**, effective base_date ở giữa rolling window, `RUN` cũ còn trong STATE | Chỉ chấm Brent champion mới kể từ effective date; không trộn phiên trước, `not_ready` nếu chưa có run mới; gold/silver/wti không reset |
| T46 | Một asset đổi K4, S1a object cũ vẫn tồn tại; asset khác vẫn baseline | Không dùng K4 làm input cho `s1a-l094`; `shadow_not_applicable_model_change` theo asset đổi, paired S1a của asset khác vẫn tính; champion run không block |
| T47 | **Daily job** TUE–SAT: 20 base_date theo lịch nhưng chỉ 19 đã có cặp chấm; cặp thứ 20 trưởng thành sau cutoff, trước job ngày kế; thử cả snapshot not-ready và cuối tuần | Không promote khi snapshot/actual thiếu; trước completed daily run vẫn `insufficient_data` cho mọi overall metric; sau run mới với ≥20 eligible base_date mới có thể `ready`; không cam kết trước 22/11 |
| T48 | Legacy record thiếu approval, `input_snapshot_dt` thiếu/có, CloudWatch PREDICT_DONE/Invocations mâu thuẫn, cutover 31/10 thực tế khác dự kiến; trường hợp dry_run | Phân loại field chỉ là **candidate**; legacy chưa có audit duyệt bị loại; post-cutover phải verify deploy/conditional write; dry_run không làm chứng cứ; cutover/event & policy trong META |

### 9.3. Nghiệm thu MVP 05/11

- API `/accuracy/{asset}` chỉ đọc completed run `META.model_version==MODEL_VERSIONS[asset]` hiện deploy, có 28 METRIC, dữ liệu forecast thực hợp lệ; trạng thái `not_ready` hợp lệ nếu chưa có completed run hiện hành, không bịa forecast.
- `COMPLETED` không đòi `n_base_dates>=20`/`n_obs>0`, không phụ thuộc logs/manifest/90-day retention. Đủ 28 METRIC, snapshot/eligible pairs đúng, `n_obs`/counts nhất quán; `width_80_pct` derived đúng theo từng cặp, mọi overall display fields tuân ngưỡng 20 ngày; ngày expected thiếu row được đếm riêng, không chấm.
- `STATE` chỉ pointer ba trường `LATEST_COMPLETED`; IAM writer scoped pointer và `ListBucket` S3 theo prefix, API chỉ đọc; champion authoritative = mapping CDK `MODEL_VERSIONS[asset]`, đổi từng asset bằng ADR.
- S1a shadow xuất **S3 Parquet `eval/shadow_eval/run_id=<run_id>/`** trên paired mask và không chặn champion. Predict có thể ghi `eval/shadow/*` nhưng không ghi report.
- PR implementation chứng minh T01–T48 (T18/T42/T43/T44/T47 được cập nhật theo cuộc họp) (shadow T25–T34 sau khi có S1a, Predict T35–T36 theo PR #48, legacy T37–T38 theo quyết định họp); IAM deny tests, correct payload/hash và không có giả lập dữ liệu production.
- Không backfill 2020–2026, không retrain hoặc sửa Validation 2019/ADR-0008.

## 10. Quyết định đã chốt ngày 30/10, việc còn chờ evidence/deploy và chuyển Contract

**Trạng thái quyết định:** Khải đã chốt thiết kế theo phản hồi của Tiến và kết quả họp 30/10; đây không phải tuyên bố PR GitHub đã được formally approved bởi toàn bộ reviewers. Tài liệu PR #45 **không merge**; thực thi phụ thuộc review/merge PR Contract riêng và smoke test hệ thống thực tế. Những phần chưa có dữ liệu production/bằng chứng được ghi là *pending evidence* thay vì suy diễn approved.

### 10.1. Bảng chốt họp 30/10 và kế hoạch cutover

| Quyết định | Chính sách đã chốt | Việc cần chứng minh khi triển khai |
|---|---|---|
| **`width_80_pct` (điểm 18)** | Derived `mean_i[100×(exp(q90_i)−exp(q10_i))]` trên từng cặp hợp lệ, `unit=percent`, `4.2` nghĩa 4,2%; giữ `width_80` log trong 28 METRIC; API có trường ở overall/by_horizon; Web chỉ dùng pct | Long triển khai tính trên raw pairs + persist derived META, Tuấn API, Tiến Web, PR #62 cập nhật fixtures; test T42/T43 |
| **Gating mọi overall metric** | `display_value/display_status` cho `coverage_80`, `width_80`, `width_80_pct`, `sign_accuracy`, `up_rate` theo chung 20 distinct `base_date` có cặp chấm hợp lệ; Web không tự gating | Tuấn/Long API/tests, Tiến Web; test T18/T43/T47 |
| **Lịch accuracy job daily** | **`cron(45 13 ? * TUE-SAT *)` UTC** (20:45 VN), sau predict 12:15–13:30 UTC; retry Scheduler 0, timeout 300s, không reserved concurrency; thiếu snapshot/actual → log/exit, không promote | Tiến CDK Scheduler/alarm Errors→SNS, Long readiness/idempotency; test T44/T47 |
| **Legacy records** | `LEGACY_ACCEPT_WITH_EVIDENCE` chỉ từng record từ mốc 27/10 12:00Z theo lịch, `is_sample=false`, model đúng, không overwrite, snapshot-as-of; thiếu evidence không vào `n_obs` | Tiến xuất `created_at` 4 asset cho base 26–29/10 (+30/10 nếu trước cutover), CloudWatch `AWS/Lambda Invocations` và `PREDICT_DONE` (`snapshot_dt`, `dry_run`, `written`, `model_version`) thành artifact đính PR Contract **trước 02/11**, do predict logs giữ ~30 ngày; nhóm duyệt danh sách từng record |
| **Cutover PR #48** | Phân loại ứng viên theo field: có `input_snapshot_dt` → hậu cutover; không có → legacy cần audit. Không dùng field đơn độc chứng minh provenance. Dry-run **không ghi bảng**. Conditional write thực sự dự kiến lượt 19:15 VN **31/10** (12:15 UTC) | Tiến ghi thời điểm CloudFormation deploy và kết quả predict production lượt 31/10, Khải/Tiến smoke test conditional write; đưa timestamp và evidence ref vào Contract và META, không tự coi 31/10 đã deploy |
| **Champion map** | `MODEL_VERSIONS` và `CHAMPION_EFFECTIVE_BASE_DATES` trong `infra/app.py`, env JSON giống nhau cho Predict/job/API; per asset, đổi champion phải có ADR; Predict fallback `MODEL_VERSION` khi env map chưa có | Khải sửa Predict PR #53, Tiến CDK env/tests, Tuấn API map; test T40 |
| **Owner/infra** | **Tuấn:** Accuracy table, API, IAM. **Long:** rolling job/metrics/tests. **Tiến:** ECR predict image CMD handler mới, Lambda `cpaws-dev-accuracy-job`, CDK/Scheduler/alarm. **Khải:** Predict mapping/legacy code | Triển khai theo thứ tự bảng Tuấn → job Long merge → Tiến build/deploy image; nếu Long merge trước 03/11, Tiến có thể build image chung với S1a PR #53 |
| **`ready` và DM** | Không cam kết Dashboard `ready` trước 22/11; `collecting` phải đúng. DM calendar-gap policy **hoãn sau 22/11**, không sửa DM-HAC hay fingerprint K4 | Dùng `n_base_dates` từ cặp thực có nhãn, không tính theo lịch, no backfill 2019 |

**Lịch Scheduler/logic an toàn:** cron `cron(45 13 ? * TUE-SAT *)` UTC; timeout Lambda 300 giây, retry Scheduler = 0, không dùng reserved concurrency vì quota tài khoản. Bản job same `run_id`/fingerprint phải idempotent với conditional PutItem, không promote khi snapshot/actual chưa sẵn sàng. **Lưu ý:** không dùng được Scheduler retries=0 để thay thế xử lý lỗi input trong Lambda hoặc cảnh báo `Errors`→SNS. Một lượt chạy trùng giờ dựa vào run_id/condition để tránh double-publish; run thất bại có thể được xử lý ở lượt kế tiếp hoặc correction revision được audit.

**Legacy evidence:** Kiểm `created_at`, dữ liệu Forecasts thực, 4 asset, lịch phiên/khung giờ, model và `is_sample=false`, CloudWatch Invocations, dòng `PREDICT_DONE` (snapshot_dt, dry_run, written, model_version), dấu vết không overwrite/manual, kiểm input-as-of; **ghi rõ danh sách asset/base_date nào được duyệt** và audit reference/hash trong META. `PREDICT_DONE` là bằng chứng audit **một lần** cho legacy, **không** là dependency runtime của job thường kỳ. Đừng nhận `created_at` trong khung giờ làm bằng chứng đủ. Nếu không xác minh được, bỏ cặp khỏi `n_obs` và giữ `schedule_evidence_status=not_audited_mvp`.

**Cutover:** Mốc chuyển production phải dựa trên CloudFormation deploy event + hành vi ghi thật và `input_snapshot_dt`, không dựa vào `dry_run`, commit/approve PR #48 hay ngày 31/10 dự kiến. Có field snapshot → chỉ là candidate hậu cutover và phải so với timestamp/event, conditional provenance; không có field → candidate legacy **chỉ** theo whitelist audit được duyệt. Khi dữ liệu trái với sự kiện deploy, fail-closed và điều tra.

### 10.2. Milestones và ownership

| Mốc | Đầu ra | Owner / trạng thái |
|---|---|---|
| **30/10/2026** | Chốt thiết kế RFC trên comment Khải/Tiến; thông báo và bắt đầu chuyển Contract | Khải/Tiến đã xác nhận chính sách; reviewer khác vẫn có thể cần review Contract |
| **31/10/2026 (dự kiến lượt 12:15 UTC)** | PR #48 conditional write + `input_snapshot_dt` có hiệu lực production; lưu CloudFormation event + smoke test | Tiến/Khải — **chưa coi đã deploy cho đến khi có evidence** |
| **Trước 02/11/2026** | Export audit legacy đính PR Contract; cập nhật **PR #62** ba JSON theo `width_80_pct` và gating mọi overall | Tiến audit/log; Long fixtures/contract, Tuấn/Tiến review |
| **Trước 03/11/2026 (nếu kịp)** | Merge code rolling job để dùng chung image predict/S1a | Long; Tiến build image, không là điều kiện thay thế QA |
| **05/11/2026** | Accuracy table/API + rolling job/handler + Scheduler TUE–SAT 13:45 UTC + Alarm Errors→SNS, IAM tests/smoke | Tuấn table/API/IAM; Long job/tests; Tiến CDK/deploy; Khải Predict mapping |
| **02–06/11/2026** | S1a JSON source từ PR #53, shadow paired không chặn champion MVP | Khải/Tiến/Tuấn |
| **Sau khi shadow có nhãn** | Paired report Parquet nội bộ `eval/shadow_eval/run_id=<run_id>/` | Long + Khải/Tuấn review |
| **15/11/2026 (dự kiến)** | Dashboard hiển thị đúng `not_ready/collecting/ready` theo API | Tiến + Long |
| **22/11/2026** | Freeze: không cam kết `ready`, hoãn DM gap cho đến sau mốc | Nhóm |

### 10.3. Nội dung cần chuyển sang PR Contract (không merge PR #45)

1. **Forecast eligibility/legacy:** 56 ngày UTC, `created_at` min, timestamp trước target cutoff, champion theo `MODEL_VERSIONS[asset]`/`CHAMPION_EFFECTIVE_BASE_DATES[asset]`; field snapshot post-cutover, policy legacy có whitelist/evidence, cutover UTC thật và audit ref. Không nhận mọi record thiếu field là legacy hợp lệ.
2. **`docs/eval/walk-forward-contract.md` §7:** ngoại lệ `rolling_8w` MVP **không manifest/CloudWatch gate**; các log đính Contract chỉ xác minh legacy, calendar expected chỉ là expected count; không nới rules `validation/test/import`.
3. **API `/accuracy/{asset}`:** 4 metric gốc + derived `width_80_pct` (unit percent) ở overall/by_horizon, 3 JSON fixtures PR #62; mọi metric overall có `display_value/display_status` cùng ngưỡng ≥20 base_dates đã có cặp; Web chỉ dùng `width_80_pct.display_value` và không tự exp/chuyển đổi. Giữ `first_eligible_base_date` ISO/null.
4. **Storage:** 28 METRIC gốc không đổi và `META.derived_metrics.width_80_pct` cùng per-h/overall payload hash/provenance; STATE pointer LATEST_COMPLETED, META/METRIC immutability/idempotency; chỉ current champion API được hiển thị.
5. **Scheduler/CDK/ownership:** hai mappings từ `infra/app.py` qua JSON env cho Predict/Rolling/API; Predict fallback legacy env, không đọc Accuracy; Lambda accuracy job dùng predict ECR image với CMD handler riêng, Scheduler daily `cron(45 13 ? * TUE-SAT *)`, retry 0, timeout 300s, no reserved concurrency, Errors alarm SNS; Tuấn bảng/API/IAM, Long job, Tiến CDK/deploy, Khải Predict. Test T40/T44/T47 và IAM deny cases.
6. **Paired S1a/champion:** JSON shadow `eval/shadow/`, paired Parquet `eval/shadow_eval/`, không đụng state/champion. Nếu asset chuyển K4 thì dừng S1a của asset đó cho tới ADR khác.
7. **Data integrity/freeze:** mismatch `prob_up` >1e-6 chỉ log, không backfill, không sửa Validation 2019, hoãn DM calendar-gap sau 22/11; test T01–T48 theo update.

**Trình tự:** RFC #45 xác nhận chính sách (review-only) → **PR Contract** review/merge → implementation + smoke tests theo ownership → RFC #45 **Closed — Not Merged**. Không xem comment chốt thiết kế là approval IAM/CDK triển khai hoặc xác nhận Forecasts legacy đủ bằng chứng.

**Đường dẫn trên PR #45:** `docs/proposal/rolling-accuracy-design.md`.

## Phụ lục A — Đối chiếu source code

- Theo review Khải, tài liệu ở GitHub dẫn commit **`a5f770c`** thay vì tên ZIP source. Khi chuyển sang contract, đối chiếu commit thực tế với nhánh đang deploy.
- `docs/api/contract.md`: `/accuracy/{asset}` chưa có JSON chính thức trong snapshot được review.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, `target_cutoff_date`, common mask và status.
- `docs/eval/walk-forward-contract.md`: hiện yêu cầu publication manifest; **v4.6** dùng Forecasts+conditional immutable write hoặc legacy verified để xác minh **các cặp được chấm**, calendar/TUE–SAT chỉ đếm expected/missing; sửa mục 7 qua PR contract riêng, không bắt buộc CloudWatch hoặc 90-day retention MVP.
- `src/forecast/predict.py`/`to_forecast_record`: PR #48 đã được approve về conditional PutItem nhưng **bản được Tiến review chưa thêm `input_snapshot_dt` champion**; Khải mới **nhận bổ sung** và contract Forecasts trước khi deploy. PR #53 có `input_snapshot_dt` trên **S1a shadow**, không thay thế trường của champion. `MODEL_VERSIONS[asset]` từ CDK (đề xuất v4.5), Predict không truy cập STATE. Chỉ đánh giá tình trạng code/deploy sau khi xác minh commit.
- `src/eval/metrics.py`: có helper metrics; chưa có orchestration rolling hoàn chỉnh theo RFC.
- **PR #49/#53** `docs/experiments/s1a-shadow-plan.md` và code Predict: kế hoạch `src/forecast/vol_scale_core.py`, S1a input JSON `eval/shadow/s1a-l094/` và báo cáo paired shadow **Parquet `eval/shadow_eval/`**; PR #51 cấp quyền predict cho `eval/shadow/*` nên output phải nằm ngoài prefix đó. Tình trạng deploy cần xác minh riêng.
- **PR #46** ADR-0011: bỏ Step Functions/SageMaker retrain trước bảo vệ; bổ sung paired shadow theo lịch Rolling (cuộc họp 30/10 chốt TUE–SAT daily cho MVP). ADR-0005 cũng chọn hiển thị (b), chỉ return %/xác suất cho vàng/bạc; **RFC Accuracy vẫn đo trên log return; `width_80_pct` là dẫn xuất simple-return width cho Web** và không dùng giá vàng/bạc quy đổi để tính nhãn.
- `infra/lambda/forecast_api/handler.py`: chưa hỗ trợ `/accuracy/{asset}` trong snapshot được review.

Các trạng thái code là từ snapshot đã dùng để soạn RFC, không xác nhận deployment AWS đang chạy.

## Phụ lục B — Tài liệu tham khảo

1. *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (chèn liên kết nội bộ chính thức khi được cung cấp).
2. [Issue #23 — Walk-forward phase 2](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).
3. `docs/adr/0008-target-quantiles-evaluation.md`, `docs/adr/0009-ceemdan-dlinear-k3-result.md`, `docs/adr/0010-k3b-volatility-scaling-result.md`, **[PR #46 — ADR-0011, ADR-0005](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/46)**, **[PR #49 — S1a shadow plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/49)**, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`.
4. [S3 GetObject: 404 khi có ListBucket, 403 khi thiếu quyền](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html), [DynamoDB PutItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html), [BatchWriteItem không hỗ trợ conditional expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_ConditionalBatchUpdate.html), [DynamoDB strong reads](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html), [IAM DynamoDB LeadingKeys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/specifying-conditions.html).
5. Dawid (1984), *The Prequential Approach*, DOI: https://doi.org/10.2307/2981683.
6. Gneiting et al. (2007), *Probabilistic Forecasts, Calibration and Sharpness*, DOI: https://doi.org/10.1111/j.1467-9868.2007.00587.x.

> **Trạng thái cuối v4.6 (30/10):** Khải đã chốt quyết định thiết kế theo comment Tiến/họp: `width_80_pct` per-pair, gating **mọi** overall metric, Scheduler daily `13:45 UTC TUE–SAT`, policy legacy có audit, hai CDK mappings và owner. **Còn chờ dữ liệu vận hành**: danh sách legacy được kiểm toán trước 02/11, CloudFormation/predict cutover 31/10 và review/merge PR Contract. Không cam kết `ready` trước 22/11; DM gap hoãn sau 22/11. PR #45 **review-only, KHÔNG MERGE**; chỉ PR contract đã được duyệt/merge mới thành chuẩn triển khai.
