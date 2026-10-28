# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** RFC v4 — **KIẾN TRÚC ĐỀ XUẤT CUỐI ĐỂ PHÊ DUYỆT** (chưa được cả nhóm approve, chưa phải API contract chính thức)  
> **Ngày cập nhật:** 2026-10-28 (v4, hợp nhất các quyết định đã đồng ý của Khải và kiến trúc PK/SK, IAM, retry, completion, tests để chốt tại họp 30/10/2026)  
> **Người đề xuất:** Long — nhóm CPAWS  
> **Người review:** Khải (đánh giá/hiển thị), Tuấn (API, DynamoDB, IAM), Tiến (Predict, Web)  
> **Mục tiêu:** Chốt thiết kế MVP trước khi cập nhật `docs/api/contract.md` bằng PR riêng; nếu thay đổi quy tắc Walk-forward/Accuracy Schema thì cập nhật tài liệu tương ứng theo review.  
> **Tham chiếu:** `docs/api/contract.md`, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`, ADR-0008, ADR-0009, ADR-0010; source tại commit `a5f770c` theo review của Khải; *Spec dashboard dự báo và độ tin cậy* (27/10/2026); [Issue #23](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).

> **Quy trình PR #45:** PR tài liệu này chỉ dùng để review và approve, **KHÔNG MERGE vào `developer`**. Sau khi chốt, chuyển các quyết định được duyệt sang `docs/api/contract.md` và các contract liên quan bằng PR riêng, rồi đóng PR RFC với trạng thái *Closed — Not Merged*.

## Tóm tắt quyết định và phạm vi

RFC đề xuất hai chức năng phục vụ Dashboard CPAWS:

1. Job `rolling_8w` chấm những dự báo đã phát hành thật, có nhãn giá hợp lệ, lưu kết quả theo Accuracy Schema.
2. `GET /accuracy/{asset}` trả chỉ số tổng hợp và theo 7 horizons; đề xuất `GET /forecast-history/{asset}` riêng để vẽ biểu đồ “dự báo cũ so với thực tế”.

**Các quy tắc giữ nguyên:** bốn asset `gold/silver/brent/wti`; horizons `h=1..7` theo **phiên giao dịch của tài sản**; nhãn và các phân vị dự báo là **log return**; không tạo ngược forecast cho dữ liệu test 2020–2026; `validation/test` lưu S3 Parquet `eval/`, `rolling_8w` lưu DynamoDB; `overall.coverage_80` gộp theo số cặp hợp lệ, không lấy trung bình ngang các tỷ lệ của 7 horizons; `sign_accuracy` luôn hiển thị cùng `up_rate`.

**Chính sách MVP đã được Khải đồng ý và Tuấn đồng ý về nguyên tắc (chờ phê duyệt toàn RFC):** cửa sổ 56 ngày UTC theo `base_date`; mốc `created_at >= 2026-10-27T12:00:00Z`; conditional write để không ghi đè forecast thật; lịch phát hành kỳ vọng suy từ trading calendar + lịch chạy TUE–SAT + predict logs, không xây bảng manifest riêng; kiểm tra sai lệch `prob_up` với dung sai `1e-6`; giới hạn Dashboard ở 4 metric; ngưỡng hiển thị coverage gộp là tối thiểu 20 ngày `base_date` khác nhau có nhãn hợp lệ; lưu `n_obs` và `n_base_dates`, không dùng ngưỡng làm bằng chứng thống kê. Thêm `input_snapshot_dt` vào forecast production, và `prob_up` lệch >`1e-6` chỉ log, không loại.

**Kiến trúc đề xuất cuối để duyệt:** một bảng `cpaws-<env>-accuracy`, item `STATE` theo asset làm nguồn champion kiêm latest pointer, partition riêng theo asset/model/run cho `META` và metric, **không GSI, không Scan**; ghi từng metric bằng conditional `PutItem` và kiểm hash (không overwrite cùng run); promote sau khi kiểm đủ 28 dòng metric MVP, snapshot và chứng cứ publication; IAM tách Predict/Writer/API/Champion admin. Phần 4 và 9 dưới đây là một phương án hoàn chỉnh để nhóm duyệt/chỉnh **một lần**. Các thay đổi so với contract hiện hành chỉ có hiệu lực sau PR contract được merge.

---

## 1. Mục tiêu và tiêu chí thành công

### 1.1. Bài toán

`baseline-q252` tạo phân phối dự báo bằng 7 phân vị cho từng `h=1..7`. Dashboard đã có thể hiển thị q10–q90 và `prob_up`, nhưng cần dữ liệu thực tế để người dùng xem: (a) nhãn có nằm trong khoảng dự báo không, (b) khoảng rộng bao nhiêu, (c) dự báo hướng có giá trị tham khảo thế nào so với tỷ lệ tăng thực tế.

### 1.2. Mục tiêu MVP

- Chấm forecast đã phát hành thật **trước khi nhãn tương lai được biết**; truy vết được forecast, chuỗi target và snapshot giá.
- Tính `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`, `n_obs` theo mỗi h và tổng hợp hợp lệ cho Dashboard.
- Phân biệt `status` tính toán trong Accuracy với `display_status` tại API; khi chưa đủ dữ liệu thì hiển thị số lần đo và trạng thái thay vì suy diễn tỷ lệ.
- Phân biệt các kỳ dự kiến phát hành, bản ghi phát hành, cặp có nhãn và cặp được chấm; báo riêng publication completeness và accuracy.
- API chỉ sử dụng run hoàn thành; không đưa kết quả đang chạy hoặc run lỗi vào “latest completed”.

### 1.3. Ngoài phạm vi

- Không đánh giá lợi nhuận, không đưa MAPE/RMSE trên mức giá vào Accuracy Schema.
- Không retrain hoặc thay K3/K3b/K4, không thay logic DM-HAC.
- Không backfill forecast lịch sử từ test 2020–2026, không sửa Validation 2019 hay ghi đè Parquet cũ.
- RFC này không triển khai Lambda, IAM, CDK, DynamoDB hoặc deploy AWS.

---

## 2. Nguồn dữ liệu, khóa ghép và tính toàn vẹn

### 2.1. Nguồn hiện có trong code

| Nguồn | Cấu trúc / vai trò |
|---|---|
| DynamoDB `Forecasts` | PK=`asset`, SK=`base_date`; `created_at`, `model_version`, `target_series`, `horizons[].{h,target_date,q,prob_up}`, `is_sample`; **bổ sung** `input_snapshot_dt` trong PR predict |
| S3 clean snapshot | `clean/prices/dt=YYYY-MM-DD/prices.parquet`, `rejected.parquet`, `quality.json` |
| `src/data/calendars.py`, `src/forecast/returns.py` | Lịch NYSE/CME và log return theo h phiên |
| `src/forecast/predict.py`, Lambda predict | Sinh và ghi forecast, trạng thái và log run |
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
4. Dự báo chỉ dùng thông tin có sẵn đến `base_date`/input-as-of và chưa dùng nhãn target tương lai. Forecast production mới phải có `input_snapshot_dt=YYYY-MM-DD` (ngày `dt=` của clean snapshot dùng khi predict); job đối chiếu snapshot, `publication_as_of`, log và thời điểm phát hành. Nếu snapshot bị sửa mà không có version/hash truy vết, không tự coi là verified. Mốc 13:30 UTC là **cutoff bảo thủ**, không phải chứng minh không leakage một mình; không được hiểu là giờ công bố settlement dầu hoặc giờ mở NYSE cố định quanh năm.
5. Chỉ chấm forecast của champion trong giai đoạn hiệu lực; không trộn model khi champion thay đổi.
6. Giá target phải thực sự được công bố và hợp lệ tại thời điểm evaluation; sample, backfill/test và forecast không thể xác minh điều kiện phát hành được loại hoặc ghi trạng thái theo policy được duyệt.

Hợp đồng quy định `created_at` phải phản ánh timestamp phát hành thực được ghi cùng record; predict logs phải ghi dấu mốc ghi thành công hoặc `PREDICT_ALREADY_PUBLISHED`, đủ để đối chiếu nếu `created_at` chỉ là thời điểm dựng payload. Bản production cũ chưa có `input_snapshot_dt` chỉ được xác minh bằng log/snapshot có chứng cứ tương đương; nếu không thì `publication_unverified`, **không tự điền giá trị hồi tố**.

### 2.4. Bảo vệ bản forecast đã phát hành [ĐỀ XUẤT MVP — D04]

Bảng `Forecasts` hiện có thể bị thay bản ghi cùng PK/SK khi `PutItem` không có điều kiện. Đề xuất **phương án B — conditional write**, không tạo bảng issuance archive cho MVP:

```python
ConditionExpression = "attribute_not_exists(asset) OR is_sample = :true"
# ExpressionAttributeValues={":true": True}
```

- Chưa có item thì ghi mới; item cũ là sample thì có thể thay bằng bản production; item production đã tồn tại thì không cho ghi đè.
- `ConditionalCheckFailedException` với item production hợp lệ được xử lý idempotent và log `PREDICT_ALREADY_PUBLISHED`, không tính lỗi hệ thống. Những lỗi ghi thật vẫn phải báo lỗi.
- Logic `run_predict()`/kết quả Lambda cần thống nhất trạng thái retry để không phát sinh alarm giả.
- Đổi champion chỉ áp dụng từ `base_date` kế tiếp; giữ forecast đã phát hành của model trước.
- Cần kiểm tra dữ liệu/log production từ 27/10 vì điều kiện ghi mới không khôi phục được bản đã bị ghi đè trước khi áp dụng.

Khải phụ trách PR predict riêng sau khi Tuấn/Tiến đồng ý; phần này chưa được coi là đã triển khai.

### 2.5. Issue #23.2 — Lịch phát hành kỳ vọng cho `rolling_8w` [ĐỀ XUẤT MVP]

Đề xuất không xây **kho publication manifest riêng** trong MVP. Thay vào đó job tạo tập expected dựa trên:

1. **Trading calendar** riêng mỗi asset, từ các phiên `base_date` dự kiến bắt đầu 26/10/2026.
2. **Lịch predict TUE–SAT** và phiên bản cấu hình/lịch vận hành thực tế; có ghi nhận các ngoại lệ đã lên lịch.
3. **Forecasts + log predict/ingest** (`PREDICT_DONE`, lý do skip, fail và, khi hỗ trợ, `PREDICT_ALREADY_PUBLISHED`) để đối chiếu expected–actual theo `(asset, base_date, h, model_version)`.

Không dùng riêng các bản ghi Forecasts đã thành công để suy ra tất cả kỳ kỳ vọng. `scheduled_run_date` có thể khác `base_date`. Nếu ingest lỗi khiến chưa xác định được phiên gốc, ghi riêng lỗi ingest/schedule và không tạo `base_date` giả.

**Phân loại mỗi ngày/asset (đã được Khải làm rõ):** (i) có `PREDICT_DONE` và thiếu forecast asset → lấy **lý do cụ thể từ predict log** như `latest_session_missing`, `invalid_input_window` hoặc lỗi tạo; nếu log xác nhận kỳ vọng/attempt hoàn tất nhưng không có row hay skip reason thì `no_forecast_row`; (ii) ingest thất bại toàn lần chạy và có log tương ứng → `upstream_failure`; (iii) **không có log cho ngày phát hành dự kiến** hoặc log không đủ chứng minh → `publication_unverified`, tuyệt đối **không** suy thành `no_forecast_row`. Forecast hợp lệ là `published_ok`, retry hợp lệ `already_published`; ngày ngoài lịch là `not_scheduled`. Các tên trên là mã audit, không tự thêm enum vào Accuracy Schema.

Lưu/ghi nhận trong evaluation-run metadata các căn cứ lịch, thời điểm chạy, snapshot, số lượng expected/published/failed/missing/eligible/matured và trạng thái truy vết; không bắt buộc tạo bảng manifest mới. **`coverage_80` chỉ lấy mẫu số `n_obs` từ các cặp forecast–nhãn hợp lệ**, không dùng `expected_count`.

**Điều kiện xác minh publication evidence [KIẾN TRÚC MVP — D14/D15]:** chỉ dùng trạng thái `schedule_evidence_status=verified` nếu có (a) calendar và cấu hình lịch chạy/ngoại lệ áp dụng cho giai đoạn đó; (b) chứng cứ log/record của các kỳ chạy hoặc lý do thất bại/skip, đủ để phân biệt expected với actual; (c) dấu vết `created_at`, `is_sample`, `model_version` và snapshot/input-as-of để đối chiếu; (d) tham chiếu run metadata có thể truy xuất lại (nguồn, khoảng thời gian, hash/version nếu có). Nếu log bị xóa theo retention, không truy cập được, hoặc không thể phân biệt kỳ thiếu với kỳ không lên lịch, ghi `incomplete/unverified`, **không biến thành `no_forecast_row` đã xác minh hoặc công bố run như đủ publication evidence**. MVP không bắt buộc xây một kho manifest mới; bản kê kỳ vọng dẫn xuất và dấu vết dùng để xác minh phải được lưu/tham chiếu cùng evaluation run. **Biện pháp triển khai bắt buộc:** CloudWatch log group của ingest/predict hiện giữ 30 ngày trong snapshot repository, ngắn hơn cửa sổ 56 ngày; đổi retention **90 ngày** trước khi phụ thuộc vào lịch dẫn xuất, đủ cửa sổ và thời gian trễ job. Đây là thay đổi cấu hình triển khai có chi phí bổ sung, phải được review cùng PR hạ tầng. Không retro-khôi phục log đã hết hạn; nếu thiếu chứng cứ cũ, run không được promote `COMPLETED`. Run metadata phải lưu tóm tắt kỳ expected/actual, log event reference, cấu hình lịch, fingerprint snapshot và hash kiểm tra, không mở bảng manifest riêng.

**Phụ thuộc contract:** `docs/eval/walk-forward-contract.md` hiện yêu cầu publication manifest cho `rolling_8w`. Nếu nhóm chọn phương án derived schedule trên, cần cập nhật rõ quy tắc/chứng cứ thay thế trong PR contract, trước khi áp dụng như tiêu chuẩn chính thức. Chính sách v4: bất kỳ kỳ nằm trong tập expected có `publication_unverified` đều làm `schedule_evidence_status=unverified`, run không được promote; kỳ có `upstream_failure`/skip với log hợp lệ có thể làm `publication_completeness=partial` nhưng chứng cứ vẫn là `verified`.

### 2.6. Issue #23.1 — So khớp `prob_up` nguồn đã làm tròn [ĐỀ XUẤT MVP]

Với dữ liệu lưu Decimal 6 chữ số, đề xuất kiểm tra nhanh `abs(prob_up_stored − prob_up_recomputed(q_stored)) <= 1e-6` sau khi xác minh đủ 7 phân vị/horizon, thứ tự, miền giá trị và clipping. Sai khác trong dung sai được chấp nhận là tương thích với làm tròn; **giữ nguyên q và `prob_up` đã lưu**, không ghi đè bằng giá trị nội suy lại.

Nếu vượt ngưỡng, chỉ ghi event `prob_up_mismatch` với độ lệch và nguồn tham chiếu; **không loại forecast chỉ vì mismatch, không sửa q/`prob_up` nguồn**. Quy tắc kiểm tra shape, miền và tính hợp lệ của q là kiểm tra độc lập và vẫn bắt buộc. Kiểm thử cần có trường hợp gần 0, tie, khoảng phân vị hẹp, clip và dữ liệu thật sự không nhất quán. Kiểm tra chuyên sâu hơn có thể triển khai sau MVP.

### 2.7. Issue #23.3 — Provenance import [KHÔNG THUỘC LUỒNG ROLLING MVP]

Theo phạm vi Khải mô tả, forecast rolling production do Lambda CPAWS phát hành, không có import dữ liệu ngoài. Vì vậy MVP không xây pipeline nhập dữ liệu hoặc hệ phân loại migration riêng. Với workflow import/historical sau này, nguyên tắc `external_unverified` của Walk-forward vẫn được giữ; `created_at` một mình không chứng minh provenance của dữ liệu import. Cần Tuấn/Tiến xác nhận phạm vi dữ liệu bảng production và các đường ghi thủ công/test trước triển khai.

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

1. Khóa snapshot giá/quality hợp lệ và xác định `target_cutoff_date` riêng asset.
2. Xây tập expected từ trading calendar + lịch predict và đối chiếu log theo mục 2.5; ghi rõ tình trạng chứng cứ.
3. Đọc `Forecasts`, kiểm `created_at`, `is_sample`, champion, tính hợp lệ của phát hành và overwrite policy.
4. Ghép expected–actual; lưu publication counters, trạng thái skip/fail/missing riêng với observation dùng chấm.
5. Kiểm q/`prob_up` nguồn theo mục 2.6; không ghi đè giá trị nguồn.
6. Tách 7 horizons, xác nhận `target_date`, tính log return từ đúng target series và valid endpoints.
7. Áp dụng common mask; tính metrics, `n_obs` riêng từng metric/h và thống kê số `base_date` khác nhau có cặp đủ điều kiện.
8. Ghi các dòng Accuracy có `evaluation_kind`, `run_id`, `config_hash`, `evaluation_start/end`, `target_cutoff_date`, `status`, `undefined_reason` theo schema hiện hành.
9. Ghi Accuracy bằng conditional/idempotent writes theo mục 4.2; kiểm đầy đủ các metric, snapshot và publication evidence theo mục 4.3 trước khi đánh dấu `COMPLETED`; chỉ sau đó mới cập nhật latest pointer trong `STATE` bằng điều kiện generation/run_order chống run cũ ghi đè.
10. Chốt run metadata trước completion: snapshot, window, champion generation, counts expected–published, exclusions, rounding check, `config_hash`/payload hashes, evidence refs và thời điểm job; không ghi thông tin bí mật.

Không gọi predict để tạo forecast lịch sử hoặc viết validation/test vào bảng Accuracy.

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

### 3.4. Champion và đổi phiên bản [D10]

Mỗi asset có **một bản ghi `STATE` authoritative** trong bảng Accuracy (mục 4.1) gồm `champion_model_version`, `champion_generation` (số nguyên tăng đơn điệu), `effective_base_date` (phiên đầu được áp dụng). Quy trình release/đổi champion cập nhật item này có điều kiện, đồng bộ với cấu hình predict; Predict Lambda đọc `STATE` trước khi phát hành và không ghi forecast nếu model đang chạy không khớp champion cho `base_date`. Không dùng model của forecast gần nhất hoặc latest run làm nguồn suy đoán champion hiện hành.

Khi đổi champion: tăng generation, đặt hiệu lực từ `base_date` phiên kế tiếp, **xóa/reset latest pointer trong cùng cập nhật `STATE`**, không sửa forecast lịch sử. Rolling job bắt đầu cửa sổ tính từ `max(window_start, effective_base_date)` để không trộn đời model, giữ `evaluation_start/end` theo ranh giới 56 ngày và lưu `champion_effective_base_date` riêng. API trả `not_ready` cho tới khi có run completed của generation mới; Dashboard ghi “Kể từ <ngày hiệu lực>”. Mọi job đang chạy mang generation cũ bị điều kiện cập nhật STATE chặn promote.

---

## 4. Accuracy Storage — kiến trúc vật lý cuối đề xuất

**Ranh giới schema đã chốt:** `validation`/`test` → S3 Parquet `eval/`; chỉ `rolling_8w` → DynamoDB. Giữ nguyên khóa logic `(run_id, model_version, asset, sample, evaluation_kind, evaluation_start, evaluation_end, target_cutoff_date, h, metric)` của `docs/api/accuracy-schema.md`. `overall` là aggregate trong run `META`, không phải hàng metric `h=0`; mọi hàng metric h=1..7 giữ nguyên schema logic.

### 4.1. Bảng, PK/SK, nguồn champion và access patterns [D05/D10]

**Bảng:** `cpaws-<env>-accuracy` (production/dev theo môi trường), 1 table, partition key **`PK`** (String), sort key **`SK`** (String); **không GSI/LSI trong MVP, không TTL cho metric/META/STATE đã công bố**. Dùng `GetItem`/`Query` trên base table, không `Scan`. Khóa động phải canonical-encode hoặc length-prefix để không va chạm dấu `#`.

| Item | `PK` | `SK` | Nội dung chính |
|---|---|---|---|
| `STATE` | `ASSET#<asset>` | `STATE` | Nguồn champion: model, generation, effective_base_date; latest pointer `latest_run_pk`, `latest_run_id`, `latest_run_order` (null khi chưa sẵn sàng) |
| `META` | `RUN#<asset>#<model_version>#<run_id>` | `META` | run status, hashes, window/cutoff, champion generation, evidence, expected metric keys/count, aggregates/counters, completion timestamp |
| `METRIC` | **Cùng PK với META** | `METRIC#<sample>#<evaluation_kind>#<evaluation_start>#<evaluation_end>#<target_cutoff_date>#H<h>#<metric>` | Một hàng Accuracy theo h/metric, đủ các cột logic và `payload_hash` |

`run_id` định danh **evaluation run**, không phải `forecast_run_id`. `run_id = <job_utc_date>-<sha256(canonical(asset, champion_generation, job_date, revision, config_hash, immutable snapshot identity, target_cutoff_date, evidence_fingerprint))[:20]>`. Hai inputs giống nhau → cùng ID; snapshot/cfg/evidence khác → ID khác. `META` chứa full fingerprint để phát hiện hash collision (không chỉ tin 20 ký tự). `run_order=<YYYYMMDD>#<revision_4_digits>`; revision mặc định `0000`, bản sửa/correction trong cùng ngày phải được người vận hành cấp revision tăng đơn điệu, không tự đoán thứ tự từ hash. Cùng `run_order` nhưng fingerprint khác → conflict, không tự promote. Nếu job cũ `FAILED` và cần đánh giá lại dù inputs không đổi, phải tăng `revision` có kiểm toán; retry kỹ thuật vẫn dùng lại `revision`/`run_id` cũ khi fingerprint khớp và run chưa bị khóa.

**Ví dụ cấu trúc khóa** (dùng model minh họa `baseline-q252`):

```text
PK=ASSET#wti                                             SK=STATE
PK=RUN#wti#baseline-q252#20261105-a94e7b3d4d0c1fb8a5e0  SK=META
PK=RUN#wti#baseline-q252#20261105-a94e7b3d4d0c1fb8a5e0  SK=METRIC#all#rolling_8w#2026-09-11#2026-11-05#2026-11-04#H1#coverage_80
```

**Bốn access patterns được khóa:**

1. **`GET /accuracy/{asset}`**: `GetItem(PK=ASSET#asset, SK=STATE, ConsistentRead=true)` → lấy champion + `latest_run_pk`; `Query(PK=latest_run_pk, ConsistentRead=true)` → lấy `META` và mọi `METRIC` (phân trang tới hết). Đây là **1 GetItem + 1 Query logic** trong trường hợp thông thường, **0 Scan, 0 GSI**.
2. **Audit một run cụ thể:** `Query(PK=RUN#asset#model#run_id)` nếu biết run identity; kiểm `META` rồi metrics. Không cấp route audit công khai trong MVP.
3. **Ghi/retry run:** `GetItem(META)` và conditional `PutItem` từng metric theo run partition; không tác động run khác.
4. **Đổi champion:** release operator cập nhật có điều kiện item `STATE` của asset, tăng generation và clear latest; không cần index theo model. Predict và Rolling đều đối chiếu cùng `STATE`.

**Lý do chọn key này thay cho `PK=asset#model_version` của gợi ý review:** `/accuracy/{asset}` chỉ có asset; cần đọc champion đang hiệu lực **mà không đoán từ Forecasts cũ**. `STATE` theo asset giải quyết vấn đề đó, còn `RUN#...` cô lập run và bao phủ đầy đủ khóa logic qua `META` + SK. Không cần bảng champion riêng. `META`/metric và `STATE` có thể ở hai partition cùng table.

### 4.2. Immutable metric writes, fingerprint và retry [D19]

- Job lấy snapshot dữ liệu và champion generation trước, tạo `run_id` theo fingerprint đã khóa. Ghi `META` `status=RUNNING` bằng `PutItem(ConditionExpression=attribute_not_exists(PK))`. Nếu `META` đã tồn tại, kiểm **toàn bộ fingerprint**: giống và chưa completed → resume; giống và completed → chỉ xác minh pointer/return idempotently; khác → `RUN_ID_CONFLICT`, dừng.
- **Metric ghi bằng `PutItem` có điều kiện `attribute_not_exists(PK)`** trên khóa `(PK,SK)`; khi conditional fail, `GetItem` và so `payload_hash` + dữ liệu chuẩn hóa: giống → retry no-op; khác → `IMMUTABLE_METRIC_CONFLICT`. Không dùng `BatchWriteItem` vì API này không hỗ trợ conditional expressions.
- Mỗi metric thuộc một khóa logic đầy đủ, không được sửa sau ghi, kể cả trước completion nếu cùng khóa đã có payload khác. Snapshot correction/config change/evidence change → **run mới**; không bao giờ update metric đã công bố.
- `META` được phép chuyển trạng thái theo điều kiện (`RUNNING → VALIDATING → COMPLETED`; `FAILED` khi có lỗi), không sửa fingerprint/input/metric manifest. Nếu job ngắt khi đang ghi, retry đúng fingerprint hoàn tất những item còn thiếu. Run `FAILED` là terminal: muốn chạy lại phải dùng `revision` tăng để tạo run mới, không sửa run cũ.
- `config_hash` là hash của **nội dung canonical toàn bộ cấu hình đánh giá**, không phải chỉ tên phiên bản. `input_fingerprint` gồm S3 object key + VersionId hoặc content digest/ETag đã kiểm tra, cutoff, calendar version, schedule config và mã model/champion. Nếu không xác thực được snapshot bất biến, không promote.

### 4.3. Run completion, latest promotion và concurrent writers [D19]

**Một run `COMPLETED` nghĩa là evaluation job đã hoàn thành và có chứng cứ hợp lệ; không có nghĩa accuracy đạt ngưỡng hiển thị.** Các điều kiện bắt buộc:

1. `META` fingerprint, `evaluation_start/end`, cutoff theo asset, `sample=all`, `evaluation_kind=rolling_8w`, `champion_generation`, clean snapshot và provenance **khớp với dữ liệu đã ghi**; `input_snapshot_dt` được kiểm đối chiếu cho forecast mới. Bản cũ không có trường này phải có log/snapshot truy vết tương đương, nếu không là unverified.
2. Derived expected schedule bao phủ **toàn bộ** các ngày/asset kỳ vọng thuộc đoạn chấm, mỗi ngày có kết luận dựa trên calendar, lịch predict, log ingest/predict, forecast record và snapshot. Không có bất kỳ kỳ `publication_unverified`: `schedule_evidence_status=verified`. Verified **không đồng nghĩa** với hoàn thành đủ mọi lần phát hành: `publication_completeness=partial` vẫn hợp lệ nếu nguyên nhân upstream/skip/no row được xác minh.
3. Có đủ **28 item metric bắt buộc** = 7 horizons × 4 metric (`coverage_80`,`width_80`,`sign_accuracy`,`up_rate`) cho `sample=all`; các metric mở rộng theo schema không phải điều kiện chặn MVP. `status=undefined` hoặc `not_applicable` hợp lệ với `undefined_reason` tương ứng **được tính là item đầy đủ**, không tạo số giả. Kiểm `n_obs`, phép cộng hit/count, `n_base_dates`, các counters, không trùng khóa và all payload hashes. `overall` lưu aggregate/counters trong META, không hàng `h=0`.
4. Job đã hoàn thành kiểm tra giá/horizon/calendar, input-as-of, giá tại endpoints, common mask và publication evidence; không còn lỗi ghi/đọc hoặc conflict chưa giải quyết.

**Điều kiện ghi áp dụng trực tiếp** (cú pháp minh họa):

```python
metric_put_condition = "attribute_not_exists(PK)"  # kiểm tra item (PK, SK) chưa tồn tại
meta_complete_condition = "#s = :validating AND config_hash = :config_hash"
state_promote_condition = (
    "champion_generation = :generation AND champion_model_version = :model "
    "AND (attribute_not_exists(latest_run_order) "
    "OR latest_run_order < :new_order OR latest_run_pk = :same_run_pk)"
)
```

Một lần `PutItem` thất bại vì item đã có phải đọc/so payload trước khi coi là retry thành công; **không** nuốt mọi `ConditionalCheckFailedException` thành thành công.

**Publish protocol:**

- Bước A: ghi tất cả item metric bất biến → `META` `VALIDATING` → kiểm mạnh (strong read) đúng 28 keys/hash và evidence.
- Bước B: conditional `UpdateItem` META sang `COMPLETED` với `status=VALIDATING` và expected fingerprint/version; lưu `completed_at`, `manifest_hash`, counts/aggregate đã kiểm.
- Bước C: conditional `UpdateItem` `STATE` đặt `latest_run_pk`, `latest_run_id`, `latest_run_order`, với **`champion_generation` và `champion_model_version` vẫn bằng giá trị lúc chấm** và `(latest_run_order < :run_order OR latest_run_pk=:same_run_pk OR attribute_not_exists(latest_run_order))`. Nếu cùng thứ tự nhưng khác run → conflict, phải xử lý chủ động. Writer cũ hay generation cũ không thể rollback pointer.
- Nếu crash giữa B/C: run vẫn completed nhưng chưa visible; retry C an toàn. Nếu crash trước B: pointer không thay đổi. **Không mặc định dùng transaction** vì publish B→C đã an toàn theo quy tắc API chỉ đọc completed; có thể nâng cấp transaction nếu xuất hiện invariant mới cần cập nhật nguyên tử.
- Đổi champion bằng conditional update `STATE` (role quản trị/release): tăng generation, gán model/effective_base_date, **REMOVE latest_run_pk/latest_run_id/latest_run_order** trong cùng update. Old writer đang chạy không promote được; API sẽ trả `not_ready` đến khi có run completed của generation mới.
- API dùng `ConsistentRead=true`, kiểm `META.status=COMPLETED`, `meta.model==state.champion`, `meta.generation==state.generation`, `meta.run_order==state.latest_run_order`, `meta.evidence=verified`, và đủ 28 metric khi dựng response. **Đọc lại `STATE` trước khi trả response** nếu có nguy cơ champion đổi giữa hai lần đọc; nếu generation khác, trả `not_ready` hoặc retry ngắn có giới hạn. Không trả dữ liệu partial/corrupt.

### 4.4. IAM — quyền tối thiểu chốt trong kiến trúc [D20]

| Role / thành phần | Action được phép | Giới hạn tài nguyên, điều kiện |
|---|---|---|
| **Rolling writer** | Accuracy: `dynamodb:GetItem`, `Query`, `PutItem`, `UpdateItem`; Forecasts: `dynamodb:GetItem`, `Query`; S3: `s3:GetObject`; Logs: `logs:FilterLogEvents`, `logs:DescribeLogStreams` (thêm `GetLogEvents` chỉ nếu dùng API đó) | Chỉ bảng Accuracy, Forecasts; S3 `clean/*`, `eval/shadow/*` cần dùng; chính xác log group ingest/predict. Không `Scan`, `DeleteItem`, `BatchWriteItem`, `PutObject`, wildcard bảng. `UpdateItem` được ứng dụng ràng buộc đúng `META`/`STATE`; IAM không thể thay thế conditional expression. |
| **Accuracy API Lambda reader** | Accuracy: `dynamodb:GetItem`, `Query` | Chỉ ARN table Accuracy; **không** `Scan`, Put/Update/Delete, không đọc Forecasts/S3/log. Có Cognito authorizer như `/forecasts/{asset}`. |
| **Predict Lambda** | Forecasts: `dynamodb:PutItem` (conditional); Accuracy: `dynamodb:GetItem` chỉ để đọc champion `STATE`; S3: quyền đọc clean/models theo pipeline hiện hữu | Không ghi Accuracy; đọc STATE chỉ `ASSET#<asset>` qua điều kiện `dynamodb:LeadingKeys` hoặc tách policy đọc đúng partition, xác minh model trước predict. Quyền Forecasts giữ phạm vi bảng. |
| **Champion release operator** | Accuracy: `dynamodb:GetItem`, `UpdateItem` | Chỉ PK `ASSET#...` của bảng Accuracy, thay champion/generation và reset latest thông qua release workflow có kiểm toán; không quyền ghi metric hoặc Forecasts. |
| **Ingest Lambda** | Giữ quyền ingest theo hạ tầng hiện hành | Không cấp quyền ghi Accuracy. |

Bảo đảm execution roles chỉ có các tài nguyên cần dùng, thêm `kms:Decrypt` **chỉ nếu** data bucket/log dùng customer-managed KMS. CloudWatch ingestion/predict log groups phải giữ **tối thiểu 90 ngày** thay vì 30 ngày hiện tại; kiểm cost impact trong PR CDK. Nếu job không đọc được bất kỳ nguồn evidence bắt buộc thì `publication_unverified`, không promote. Dùng `logs:DescribeLogGroups` chỉ khi thực sự cần discovery; cấu hình tên log group cố định ưu tiên hơn. CDK/test rà lại IAM định dạng ARN/region/account theo môi trường.

### 4.5. Data integrity, TTL và rollback

- Không TTL cho item `STATE`, `META` completed hoặc `METRIC` trong MVP. Cleanup chỉ theo retention policy/PR riêng, không xóa dữ liệu đang được pointer tham chiếu.
- Dữ liệu Forecasts production dùng conditional write mục 2.4; retry `PREDICT_ALREADY_PUBLISHED` chỉ thành công nếu đọc lại bản cũ và kiểm là production hợp lệ cho cùng `(asset,base_date)` (không âm thầm nuốt conflict).
- `input_snapshot_dt` là **trường mới trên Forecasts**, không tự thay `created_at`, `base_date`, `target_date` hoặc chứng minh as-of nếu đứng một mình; lưu tham chiếu hash/version của snapshot trong run META nếu có.
- Run có chứng cứ thiếu, dữ liệu bị sửa ngoài ý muốn hoặc snapshot đổi → để `FAILED`/không promote; dữ liệu đã công bố giữ nguyên và correction là run mới có audit trail. Việc xóa hoặc sửa `STATE`/pointer cần được giám sát.

## 5. API `GET /accuracy/{asset}` [ĐỀ XUẤT]

### 5.1. Request

`GET /accuracy/wti`, với Cognito ID token như API hiện tại; asset thuộc `gold`, `silver`, `brent`, `wti`. MVP cố định `evaluation_kind=rolling_8w`, `sample=all` và champion từ Accuracy `STATE`. Không hỗ trợ chọn model/run khác qua public query params trong MVP; request tham số không hỗ trợ bị từ chối hoặc bỏ qua theo hợp đồng API hiện có (ưu tiên từ chối để tránh hiểu nhầm).

### 5.2. Ví dụ JSON response

> **Chỉ minh họa định dạng, không phải số liệu CPAWS đã chạy.** `by_horizon` dưới đây rút gọn; API thực tế trả đủ 7 h. Khuôn dữ liệu này là **đề xuất đã xác định của RFC v4**, có hiệu lực khi PR contract được duyệt.

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
    "schedule_evidence_status": "verified",
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
- Dashboard MVP hiển thị `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`. Không hiển thị `pinball_skill=0` của champion `baseline-q252` so với chính baseline. Metric khác vẫn được lưu nếu tính được.
- `width_80` lưu log return; frontend đổi sang % và ghi rõ cách đổi. `sign_accuracy` và `up_rate` luôn đi cặp nhưng không mặc định có cùng mẫu số.
- `coverage_80.display_value=null` khi chưa đạt ngưỡng hiển thị đã chốt; không sửa `status` nội bộ chỉ vì ngưỡng UX. Tránh đưa tỷ lệ bị ẩn lên web thông qua field phụ.
- `data_status=not_ready|collecting|ready`: **HTTP 200 + `not_ready`** (null metrics) nếu chưa có completed run của champion hiện tại; `collecting` nếu completed nhưng chưa đủ 20 `base_date` có nhãn; `ready` khi đạt ngưỡng hiển thị gộp. API đọc `STATE` bằng GetItem rồi Query run META+metrics bằng PK, không Scan/GSI; kiểm lại champion generation trước khi trả. Asset/auth/hạ tầng dùng error envelope contract hiện hành.
- Không công bố là đã đủ lịch phát hành chỉ vì có forecast được chấm; tách publication completeness khỏi coverage. Không đưa logs/credentials hoặc thông tin nội bộ nhạy cảm ra API.

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

| Tình huống | Quy tắc đề xuất |
|---|---|
| `is_sample=true` hoặc `created_at` trước 27/10 12:00Z | Loại khỏi rolling production |
| Phát hành 27/10 cho `base_date=26/10` | Vẫn xét nếu đạt các điều kiện hợp lệ |
| `h=1` có `target_date` cùng ngày phát hành | So timestamp theo cutoff, không so ngày; kiểm input-as-of |
| Đã có forecast production cùng `(asset, base_date)` | Conditional write chặn ghi đè; retry idempotent, có log |
| Run có lỗi nhưng một số asset phát hành thành công | Log/truy vết riêng từng asset, không coi toàn run thành công |
| Thiếu forecast trong kỳ dự kiến | PREDICT_DONE → lấy skip/error reason từ log; ingest lỗi → `upstream_failure`; không log → `publication_unverified`, chặn completed |
| Ingest không xác định được `base_date` | Ghi lỗi ingest; không tạo kỳ `base_date` giả |
| `prob_up` lệch ≤ `1e-6` sau kiểm tra shape | Chấp nhận tương thích làm tròn, giữ giá trị nguồn |
| `prob_up` lệch > `1e-6` | Chỉ log `prob_up_mismatch`, không loại dự báo chỉ vì lệch, không ghi đè |
| `target_date` chưa đến hoặc giá chưa published | `pending`, không tăng `n_obs` |
| Endpoint missing/rejected/giá không dương | Loại với reason; không nội suy endpoint |
| Thiếu giá giữa hai endpoint | Không tự loại target nếu endpoint hợp lệ; ghi số phiên thiếu |
| `n_obs=0` | `status=undefined`, không hiện tỷ lệ |
| Ít hơn 20 `base_date` có cặp đã chấm (đề xuất) | Web chỉ X/Y và số ngày dự báo, không hiển thị phần trăm overall |
| Nhiều horizon cùng một `base_date` | Đếm theo cặp, không gọi là số lần thử độc lập |
| Đổi champion | `STATE` tăng generation, reset latest; bắt đầu lại từ `effective_base_date`, API `not_ready` nếu chưa có run mới |
| Sửa snapshot hoặc job lỗi giữa chừng | Fingerprint khác → run mới, `run_order` revision tăng; không thay latest bằng run lỗi |
| Log ingest/predict chỉ còn 30 ngày | Nâng retention 90 ngày; không đủ evidence 56 ngày → không promote, không suy missing |
| `input_snapshot_dt` thiếu ở Forecasts cũ | Chỉ verified khi logs + immutable snapshot refs chứng minh; không tự backfill |
| Validation 2019, test 2020–2026 | Không đưa vào rolling live |

---

## 8. Ma trận kiến trúc cuối trình duyệt tại họp 30/10

Đây là **một bộ quyết định nhất quán**, không còn các ô “Tuấn tự chốt sau” trong nội dung thiết kế. Khải đã xác nhận bốn phản biện (derived schedule; input-as-of; prob_up; ngưỡng); Tuấn đã đồng ý hướng single-table/no-GSI, conditional concurrency, derived evidence, nhưng **chưa approve toàn bộ implementation**. Bảng này là quyết định **đề xuất cuối** để nhóm approve hoặc phản hồi thay đổi theo từng ID.

| ID | Kiến trúc / chính sách đề xuất cuối | Review chính |
|---|---|---|
| D01 | `rolling_8w`: 56 ngày UTC inclusive theo `base_date`; `evaluation_start/end` chính là ranh giới window | Khải/Long |
| D02 | Chỉ production `created_at >= 2026-10-27T12:00Z`, không backfill | Khải/Tiến |
| D03 | Chấm hàng tuần sau clean snapshot, mỗi asset một evaluation run | Long/Tuấn |
| D04 | Forecasts conditional Put: thay sample, không overwrite production; retry kiểm bản cũ | Khải/Tiến/Tuấn |
| D05 | `cpaws-<env>-accuracy`, `PK/SK` theo mục 4.1; item `ASSET#asset/STATE` + `RUN#asset#model#run_id`/`META` và `METRIC...`; **không GSI/Scan/TTL** | Tuấn |
| D06 | Gộp coverage chỉ hiện % khi `n_base_dates>=20`; `n_obs`, `n_base_dates` luôn trả | Khải/Tiến |
| D07 | `/accuracy/{asset}`: 4 metrics MVP, overall + h1–7, HTTP 200 `not_ready` cho chưa có valid run | Tuấn/Tiến/Long |
| D08 | `/forecast-history/{asset}` riêng, phase chart sau 05/11; không block MVP Accuracy | Tuấn/Tiến/Khải |
| D09 | History pairs **on-demand** từ Forecasts + clean snapshot đã xác minh, không bảng detail mới | Tuấn/Long |
| D10 | Champion authoritative = `STATE` (model, generation, effective_base_date); Predict đọc STATE; đổi champion reset pointer trong cùng update | Tuấn/Khải/Tiến |
| D11 | Mỗi horizon chỉ X/Y; overall tỷ lệ % sau ngưỡng | Khải/Tiến |
| D12 | Snapshot correction tạo run mới với `revision` tăng; giữ run cũ bất biến | Tuấn/Long |
| D13 | Validation 2019 chỉ ở trang “Phương pháp”, không trộn rolling | Khải |
| D14 | Derived calendar + TUE–SAT + ingest/predict logs thay publication manifest table cho MVP | Khải/Tuấn |
| D15 | Mọi expected day phải đủ evidence; ingest fail=`upstream_failure`; thiếu log=`publication_unverified` (chặn completed); log retention **90 ngày** | Tuấn/Khải |
| D16 | `prob_up` mismatch >`1e-6` chỉ log `prob_up_mismatch`, không loại/overwrite | Khải/Long |
| D17 | Import external ngoài rolling MVP, giữ `external_unverified` cho workflow khác | Khải/Tuấn |
| D18 | `created_at < 13:30 UTC` vào `target_date` + input-as-of; Forecasts mới có `input_snapshot_dt` | Khải/Tiến |
| D19 | Run fingerprint deterministic; immutable conditional metric writes; `RUNNING→VALIDATING→COMPLETED`; conditional STATE latest promotion theo generation+run_order | Tuấn/Long |
| D20 | IAM phân Predict/Writer/API/Champion operator; least privilege theo bảng/prefix/log ARN, không Scan | Tuấn |

**Hiệu lực:** chỉ sau khi nhóm approve và PR contract liên quan được merge. Nếu reviewer thay một quyết định, cập nhật đồng bộ các mục 2–9 trước khi duyệt, không để bảng quyết định và logic API mâu thuẫn. Issue #23 mục 2 đóng khi PR contract mục 7 đã merge, không tự coi toàn bộ Issue #23 hay implementation đã done.

## 9. Acceptance criteria và kế hoạch kiểm thử — điều kiện phê duyệt kiến trúc

### 9.1. Contract/invariants bắt buộc

- [ ] Mọi metric `rolling_8w` dùng đúng khóa logic và 7 h của Accuracy Schema; validation/test vẫn chỉ lưu S3, không đưa vào bảng Accuracy.
- [ ] Bảng `PK/SK` đúng mục 4.1; query chính chỉ `GetItem` và `Query`, không Scan/GSI; khi champion đổi không đọc run đời cũ.
- [ ] `run_id`/fingerprint xác định từ job UTC, asset, generation, config, snapshot và evidence; khác fingerprint không được reuse run cũ.
- [ ] `METRIC` bất biến; `META` chỉ đổi trạng thái có điều kiện; latest pointer chỉ được cập nhật sau completion có evidence verified.
- [ ] `STATE` authoritative; Predict và Rolling đều đối chiếu generation/model; IAM chính xác từng role.
- [ ] Log ingest/predict có retention **90 ngày** và đủ sự kiện để phân biệt schedule intent, PREDICT_DONE, skip, upstream failure và no log.
- [ ] `input_snapshot_dt` trên Forecasts từ khi code predict triển khai; bản cũ thiếu chỉ verified nếu có chứng cứ tương đương; không backfill giả.
- [ ] Chốt JSON `/accuracy/{asset}` cho 4 metrics, `n_obs`, `n_base_dates`, `status`/`display_status`, `not_ready`, `collecting`, `ready`; threshold 20 ngày chỉ UX.
- [ ] Kết quả lịch sử `/forecast-history/{asset}` tách giai đoạn chart, không tạo bảng detail/manifest mới để chặn MVP.

### 9.2. Functional tests — bộ bắt buộc trước deploy

| ID test | Điều kiện thử | Expected |
|---|---|---|
| T01 | Khóa metric khác `run_id`, asset, model, sample, evaluation_kind, window, cutoff, h hoặc metric | Không va chạm `(PK,SK)`; không mất chiều khóa logic |
| T02 | GET Accuracy: 4 asset, mỗi run có 28 metric rows, Query paginated | 1 GetItem STATE + 1 Query logic (nhiều page nếu cần); không `Scan`, không GSI |
| T03 | Job ghi 1..27/28 item rồi crash | `META` chưa `COMPLETED`; latest pointer giữ nguyên; API không đọc run dở |
| T04 | Cùng run/fingerprint, retry ghi lại cùng item hash | No-op; số item không tăng; completed không bị ghi đè |
| T05 | Cùng `(PK,SK)` nhưng payload khác hoặc same `run_order` khác fingerprint | `IMMUTABLE_METRIC_CONFLICT`/`RUN_ID_CONFLICT`; không sửa dữ liệu cũ |
| T06 | Hai writer A (run cũ) và B (run mới) hoàn tất ngược thứ tự | Pointer luôn trỏ B nếu `run_order(B)>run_order(A)` |
| T07 | Đổi champion trong khi writer cũ đang chạy | STATE generation đổi + latest reset; writer cũ promote thất bại; API `not_ready` không trả model cũ |
| T08 | Job COMPLETE với đủ 28 rows, trong đó có hàng `undefined` hợp lệ | `COMPLETED` nếu evidence verified; `n_obs=0`/value null không bị giả số |
| T09 | Thiếu 1 metric row hoặc hash/count lệch | Không chuyển `COMPLETED`, không update latest |
| T10 | Ingest log xác nhận lỗi toàn kỳ | `upstream_failure`, publication partial; evidence có thể verified nếu đủ nguồn |
| T11 | `PREDICT_DONE` nhưng asset thiếu có skip reason xác nhận | Phân loại reason từ log, không gán `no_forecast_row` tùy tiện |
| T12 | Không có log cho kỳ expected hoặc retention không đủ 56 ngày | `publication_unverified`, `schedule_evidence_status=unverified`, không promote |
| T13 | Forecast trước 27/10 12:00Z, `is_sample=true`, hoặc backfill giả | Bị loại khỏi rolling production |
| T14 | Forecast h=1 phát hành 12:15 UTC cùng target_date; trường hợp >13:30 UTC; hai chế độ DST | Đúng quy tắc timestamp và input-as-of, không so ngày YYYY-MM-DD đơn thuần |
| T15 | `input_snapshot_dt` khớp log/snapshot, không khớp, hoặc thiếu ở bản cũ | Chỉ verified nếu có evidence hợp lệ; không tự sửa record |
| T16 | `prob_up` lệch 0, `1e-6`, lớn hơn `1e-6`, q gần 0/tie/clip | >ngưỡng chỉ log `prob_up_mismatch`; không sửa q/prob_up, không loại bởi mismatch một mình |
| T17 | Endpoint missing/rejected/nonpositive; thiếu phiên ở giữa endpoints | Theo ADR-0008, missing giữa không tự vô hiệu target nếu endpoints hợp lệ |
| T18 | `overall.coverage_80`, n=0/19/20 distinct base_date, 7 horizons chồng lắp | Pool hit/count, không trung bình tỷ lệ; n_base_dates đúng; display hide/unhide đúng |
| T19 | `sign_accuracy` có mask zero khác `up_rate`; width trên log return | `n_obs` tách riêng, đơn vị đúng; không thêm h=0 |
| T20 | IAM: API gọi Put/Update/Scan, Predict ghi Accuracy, writer truy cập sai ARN/prefix | `AccessDenied`; API read-only; log/S3 permission đúng phạm vi |
| T21 | GET giữa lúc champion đổi / pointer thay | Đọc lại STATE generation; không trả response của champion cũ như current |
| T22 | Lỗi snapshot correction cùng job UTC, revision tăng có chủ đích | New run_id/`run_order`, run cũ bất biến, chỉ promote revision được xét mới |
| T23 | Validation 2019/test lịch sử và imported `external_unverified` | Không lẫn vào rolling live, không rewrite dữ liệu test/validation |
| T24 | Log group retention hiện chỉ 30 ngày | Deployment guard/test cấu hình phải thất bại cho đến khi nâng >=90 ngày |

### 9.3. Nghiệm thu MVP 05/11

- API `/accuracy/{asset}` bảo đảm không cung cấp số liệu chưa được phát hành hoặc thiếu chứng cứ; trạng thái **`not_ready` là hợp lệ** khi chưa đủ evidence production, không được tạo số liệu mô phỏng để lấp Dashboard.
- Nếu có completed run: đủ 28 metric rows, 7 horizons, aggregate/counters chính xác, `n_obs`, `n_base_dates` và trạng thái hiển thị theo policy. `publication_completeness` không dùng làm mẫu số coverage.
- Chỉ có champion hiện hành; dữ liệu trước lần đổi champion không trộn. Không đánh đồng 20 ngày với 20 quan sát độc lập.
- PR implementation có kết quả automated tests T01–T24 hoặc giải trình test tích hợp AWS tương đương, log/metadata truy vết, IAM access-denied tests và kiểm tra log retention.
- Không backfill 2020–2026, không retrain hoặc sửa Validation 2019/ADR-0008.

## 10. Phân công, mốc thời gian và cách cập nhật contract

| Mốc | Đầu ra | Chủ trì / review |
|---|---|---|
| **28–29/10/2026** | RFC v4 kiến trúc cuối đưa review PR #45 | Long; Khải/Tuấn/Tiến |
| **30/10/2026** | Họp phê duyệt đồng bộ D01–D20, đặc biệt PK/SK, IAM, state, completion và evidence | Khải + nhóm |
| **Sau họp/duyệt** | PR cập nhật `docs/api/contract.md` **và** `docs/eval/walk-forward-contract.md` mục 7; bổ sung `input_snapshot_dt`; giữ schema logic, cập nhật schema/ADR chỉ khi thực sự đổi chuẩn | Long + Tuấn, review Khải/Tiến |
| **05/11/2026 (dự kiến)** | Job `rolling_8w` + Accuracy table/STATE + `/accuracy/{asset}` + evidence/log retention | Long; Tuấn (API/IAM), Tiến (Web), Khải (predict) |
| **15/11/2026 (dự kiến)** | Khối độ tin cậy và biểu đồ forecast–actual | Long + Tiến |
| **22/11/2026** | Đóng băng tính năng | Nhóm |

**Quy trình:** RFC → review/chốt → PR contract → PR implementation + tests → deploy và xác minh dữ liệu production. PR #45 là PR review, **không merge**; sau khi các quyết định được chuyển vào PR contract và được duyệt, đóng PR #45 không merge. Không cập nhật code hoặc contract chính thức trong PR RFC này.

**File RFC trong repository:** `docs/proposal/rolling-accuracy-design.md` (không phải `docs/proposals/`).

### Những nội dung bắt buộc chuyển vào contract sau khi được duyệt

1. Quy tắc cửa sổ rolling, cutoff `created_at`/`target_date`, champion và chọn target có nhãn hợp lệ.
2. Điều kiện lịch phát hành kỳ vọng và classification của trường hợp thiếu forecast; cập nhật Walk-forward contract khi cần.
3. `/accuracy/{asset}`: auth, JSON fields, errors, overall/by-horizon, `n_obs`, `n_base_dates`, ngưỡng UX, trạng thái.
4. API lịch sử nếu được chọn: route, filter, phân trang, pending/observed, nguồn return/price.
5. Bảo vệ bản forecast gốc và nguyên tắc không ghi đè `prob_up` nguồn.
6. DynamoDB `PK/SK`, STATE/META/METRIC, `run_id`/`run_order`, conditional immutable writes, completion/promotion, quyền IAM writer/API/Predict/operator; policy/CDK JSON triển khai trong PR implementation.
7. Chính sách log retention 90 ngày và bằng chứng liên kết lịch phát hành; việc thiếu log từ trước không được hợp thức hóa bằng backfill giả.

---

## Phụ lục A — Đối chiếu source code

- Theo review Khải, tài liệu ở GitHub dẫn commit **`a5f770c`** thay vì tên ZIP source. Khi chuyển sang contract, đối chiếu commit thực tế với nhánh đang deploy.
- `docs/api/contract.md`: `/accuracy/{asset}` chưa có JSON chính thức trong snapshot được review.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, `target_cutoff_date`, common mask và status.
- `docs/eval/walk-forward-contract.md`: hiện yêu cầu publication manifest; v4 chọn derived schedule + logs và yêu cầu **sửa mục 7 trong cùng PR contract**, phân biệt `upstream_failure`, skip reason, `publication_unverified`.
- `src/forecast/predict.py`: `put_item` hiện có thể ghi đè cùng khóa; Khải triển khai conditional write và trường `input_snapshot_dt` trong PR predict riêng, đồng thời tích hợp kiểm champion STATE.
- `src/eval/metrics.py`: có helper metrics; chưa có orchestration rolling hoàn chỉnh theo RFC.
- `infra/lambda/forecast_api/handler.py`: chưa hỗ trợ `/accuracy/{asset}` trong snapshot được review.

Các trạng thái code là từ snapshot đã dùng để soạn RFC, không xác nhận deployment AWS đang chạy.

## Phụ lục B — Tài liệu tham khảo

1. *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (chèn liên kết nội bộ chính thức khi được cung cấp).
2. [Issue #23 — Walk-forward phase 2](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).
3. `docs/adr/0008-target-quantiles-evaluation.md`, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`.
4. [DynamoDB PutItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html), [BatchWriteItem không hỗ trợ conditional expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_ConditionalBatchUpdate.html), [DynamoDB strong reads](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html), [IAM DynamoDB LeadingKeys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/specifying-conditions.html).
5. Dawid (1984), *The Prequential Approach*, DOI: https://doi.org/10.2307/2981683.
6. Gneiting et al. (2007), *Probabilistic Forecasts, Calibration and Sharpness*, DOI: https://doi.org/10.1111/j.1467-9868.2007.00587.x.

> **Trạng thái cuối:** RFC v4 chứa **kiến trúc đề xuất cuối hoàn chỉnh** để review/approve một lần tại PR #45; chưa phải quyết định đã được toàn nhóm approve. Chỉ nội dung được chuyển qua PR contract và merge mới là chuẩn implementation; PR #45 **không merge**.
