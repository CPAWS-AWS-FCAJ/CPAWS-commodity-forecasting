# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** DRAFT / PROPOSAL — **chưa được phê duyệt, chưa phải API contract chính thức**  
> **Ngày cập nhật:** 2026-10-28 (điều chỉnh sau review PR #45; chờ họp 30/10/2026)  
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

**Đề xuất MVP sau review Khải (chờ nhóm chốt):** cửa sổ 56 ngày UTC theo `base_date`; mốc `created_at >= 2026-10-27T12:00:00Z`; conditional write để không ghi đè forecast thật; lịch phát hành kỳ vọng suy từ trading calendar + lịch chạy TUE–SAT + predict logs, không xây bảng manifest riêng; kiểm tra sai lệch `prob_up` với dung sai `1e-6`; giới hạn Dashboard ở 4 metric; đề xuất ngưỡng hiển thị coverage gộp theo tối thiểu 20 ngày `base_date` khác nhau có nhãn hợp lệ.

**Cần chốt trước triển khai:** cách chứng thực lịch phát hành dự kiến và trạng thái `no_forecast_row`, quy tắc chống leakage theo thời gian, chống ghi đè, trường JSON API, ngưỡng hiển thị, thời điểm đổi champion và xử lý khi log/snapshot chưa đầy đủ. Các thay đổi chính sách so với `docs/eval/walk-forward-contract.md` chỉ có hiệu lực sau PR contract được duyệt.

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
| DynamoDB `Forecasts` | PK=`asset`, SK=`base_date`; `created_at`, `model_version`, `target_series`, `horizons[].{h,target_date,q,prob_up}`, `is_sample` |
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
4. Dự báo chỉ dùng thông tin có sẵn đến `base_date`/input-as-of và chưa dùng nhãn target tương lai. Mốc 13:30 UTC là **cutoff bảo thủ được đề xuất**, không được hiểu là giờ công bố settlement cố định của dầu hoặc giờ mở NYSE cố định quanh năm.
5. Chỉ chấm forecast của champion trong giai đoạn hiệu lực; không trộn model khi champion thay đổi.
6. Giá target phải thực sự được công bố và hợp lệ tại thời điểm evaluation; sample, backfill/test và forecast không thể xác minh điều kiện phát hành được loại hoặc ghi trạng thái theo policy được duyệt.

Cần Tuấn/Tiến xác nhận cách diễn giải `created_at` so với thời điểm ghi thành công và nguồn log để đối chiếu khi triển khai.

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

**Phân loại báo cáo vận hành đề xuất:** `published_ok`, `no_forecast_row`, `skipped/invalid_input_window`, `generation_error/upstream_failure`, `already_published`, `not_scheduled`, `publication_unverified`. Chỉ dùng `no_forecast_row` khi đủ căn cứ về kỳ dự kiến và thiếu bản ghi; thiếu log hoặc lịch không xác thực phải báo trạng thái chứng cứ chưa đầy đủ. Các tên này là mã audit, **không phải enum tự động thêm vào bảng Accuracy**.

Lưu/ghi nhận trong evaluation-run metadata các căn cứ lịch, thời điểm chạy, snapshot, số lượng expected/published/failed/missing/eligible/matured và trạng thái truy vết; không bắt buộc tạo bảng manifest mới. **`coverage_80` chỉ lấy mẫu số `n_obs` từ các cặp forecast–nhãn hợp lệ**, không dùng `expected_count`.

**Phụ thuộc contract:** `docs/eval/walk-forward-contract.md` hiện yêu cầu publication manifest cho `rolling_8w`. Nếu nhóm chọn phương án derived schedule trên, cần cập nhật rõ quy tắc/chứng cứ thay thế trong PR contract, trước khi áp dụng như tiêu chuẩn chính thức. Phạm vi khi log thiếu/chưa xác thực phải được chốt tại họp 30/10.

### 2.6. Issue #23.1 — So khớp `prob_up` nguồn đã làm tròn [ĐỀ XUẤT MVP]

Với dữ liệu lưu Decimal 6 chữ số, đề xuất kiểm tra nhanh `abs(prob_up_stored − prob_up_recomputed(q_stored)) <= 1e-6` sau khi xác minh đủ 7 phân vị/horizon, thứ tự, miền giá trị và clipping. Sai khác trong dung sai được chấp nhận là tương thích với làm tròn; **giữ nguyên q và `prob_up` đã lưu**, không ghi đè bằng giá trị nội suy lại.

Nếu vượt ngưỡng, ghi nhận sai khác và chuyển kiểm tra theo policy được duyệt, không tự sửa nguồn hoặc tự gán là lỗi thuật toán khi chưa có kiểm tra đầy đủ. Kiểm thử cần có trường hợp gần 0, tie, khoảng phân vị hẹp, clip và dữ liệu thật sự không nhất quán. Kiểm tra chuyên sâu hơn có thể triển khai sau MVP.

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
| Tần suất | Đề xuất chạy hàng tuần sau ingest/snapshot hoàn tất |

**Cần chốt ý nghĩa `evaluation_start/evaluation_end`:** hoặc là ranh giới 56 ngày của window, hoặc là ngày gốc đầu/cuối có cặp được xem xét; phải áp dụng nhất quán trong Accuracy storage, run metadata và API. Nếu lưu ranh giới window, dùng trường riêng cho ngày forecast thực tế đầu/cuối.

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
9. Ghi DynamoDB idempotent; chỉ đổi latest completed run khi hoàn tất và đạt chính sách evidence đã được chốt.
10. Ghi run metadata: snapshot, window, champion, counts expected–published, exclusions, rounding check, thời điểm job và lỗi vận hành; không ghi thông tin bí mật.

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

**Ngưỡng hiển thị — đề xuất mang ra họp 30/10 (D06/D11):** tối thiểu **20 `base_date` khác nhau có ít nhất một cặp đã có nhãn và được tính cho `overall.coverage_80`**. Trước ngưỡng: giữ metric nội bộ nếu tính được, API `display_value=null`, `display_status=insufficient_data`, web hiển thị X/Y và “từ N ngày dự báo” thay cho phần trăm. Từng h chỉ hiển thị X/Y, không hiện tỷ lệ %. Trường hợp `n_obs=0` có `status=undefined` và giá trị null.

Khải ước tính nếu đủ lần phát hành và nhãn: 05/11 có 7 `base_date` / 28 cặp; 15/11: 14 / 77; 22/11: 19 / 112; 30/11: 23 / 140. Đây là **số dự kiến**, không phải số rolling production đã đo. Ngưỡng 20 ngày chỉ là quy tắc hiển thị UX.

### 3.4. Champion [D10]

Chỉ đánh giá `model_version` champion đang vận hành. Khi đổi champion, bắt đầu thống kê mới từ thời điểm/ngày hiệu lực đã chốt và hiển thị “Kể từ <ngày đổi>”; không trộn forecast của các champion vào cùng tỷ lệ. Thời điểm hiệu lực và bản model cần được ghi trong metadata của evaluation run.

---

## 4. Accuracy Storage

- **Đã chốt trong Accuracy Schema:** `validation`/`test` → Parquet trên S3 `eval/`; `rolling_8w` → DynamoDB.
- Mỗi metric/h có khóa logic `(run_id, model_version, asset, sample, evaluation_kind, evaluation_start, evaluation_end, target_cutoff_date, h, metric)`; không đồng nhất khóa logic này với PK/SK vật lý.
- **Tuấn chốt:** PK/SK/GSI, truy vấn latest completed per asset/champion, IAM, TTL, batch/idempotency và quy tắc hoàn tất run.
- Để tính `overall`, đọc counts từ các cặp chi tiết hoặc aggregate riêng có provenance; không tự thêm `h=0` hay `metric=covered_count` vào schema hiện hành.
- Lịch sử forecast–actual có thể tính khi đọc hoặc lưu chi tiết ngoài bảng Accuracy theo phương án được duyệt; snapshot correction phải có dấu vết.
- Run metadata lưu/đối chiếu snapshot, lịch dự kiến, logs, trạng thái publication, cutoff, `n_base_dates`, `config_hash`; không tự thêm cột chính thức nếu chưa có PR schema.

---

## 5. API `GET /accuracy/{asset}` [ĐỀ XUẤT]

### 5.1. Request

`GET /accuracy/wti`, với Cognito ID token như API hiện tại; asset thuộc `gold`, `silver`, `brent`, `wti`. MVP mặc định `evaluation_kind=rolling_8w`, `sample=all` và champion đang vận hành. Query params khác chỉ thêm sau khi thống nhất.

### 5.2. Ví dụ JSON response

> **Chỉ minh họa định dạng, không phải số liệu CPAWS đã chạy.** `by_horizon` dưới đây rút gọn; API thực tế trả đủ 7 h. Các trường metadata mới cần Tuấn/Khải duyệt trước khi đưa vào contract.

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
      "n_base_dates_labeled": 7,
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
    {"h": 1, "coverage_80": {"covered_count": 5, "n_obs": 7, "display_status": "counts_only"}},
    {"h": 2, "coverage_80": {"covered_count": 4, "n_obs": 6, "display_status": "counts_only"}}
  ],
  "data_status": "collecting",
  "disclaimer": "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

### 5.3. Quy ước API

- `overall.coverage_80` gộp theo số cặp; `by_horizon` trả đủ h=1..7, mỗi metric có `n_obs` và trạng thái riêng.
- Dashboard MVP hiển thị `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`. Không hiển thị `pinball_skill=0` của champion `baseline-q252` so với chính baseline. Metric khác vẫn được lưu nếu tính được.
- `width_80` lưu log return; frontend đổi sang % và ghi rõ cách đổi. `sign_accuracy` và `up_rate` luôn đi cặp nhưng không mặc định có cùng mẫu số.
- `coverage_80.display_value=null` khi chưa đạt ngưỡng hiển thị đã chốt; không sửa `status` nội bộ chỉ vì ngưỡng UX. Tránh đưa tỷ lệ bị ẩn lên web thông qua field phụ.
- `data_status=not_ready|collecting|ready` là đề xuất; chưa có run → cân nhắc HTTP 200/`not_ready` với dữ liệu null. Lỗi asset/auth/hạ tầng theo error envelope contract hiện hành.
- Không công bố là đã đủ lịch phát hành chỉ vì có forecast được chấm; tách publication completeness khỏi coverage. Không đưa logs/credentials hoặc thông tin nội bộ nhạy cảm ra API.

---

## 6. API biểu đồ “dự báo cũ so với thực tế” [ĐỀ XUẤT]

### 6.1. Phương án

| Phương án | Ưu điểm | Hạn chế | Đề xuất |
|---|---|---|---|
| A — Nhúng vào `/accuracy/{asset}` | Một request | Payload lớn, khó phân trang và trộn dữ liệu tổng hợp/chi tiết | Không ưu tiên |
| B — `GET /forecast-history/{asset}` riêng | Hỗ trợ lọc h, cursor; phục vụ chart khi cần | Thêm route và triển khai | **Ưu tiên; chờ Tuấn/Tiến/Khải duyệt** |

### 6.2. JSON phác thảo

`GET /forecast-history/wti?h=3&limit=30` (Cognito ID token):

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

Giá trị chỉ minh họa, `target_date` phải xác nhận theo trading calendar. Với `pending`, `actual.log_return=null`, `inside_80=null`. Không tạo forecast mới khi GET. Chart mặc định biểu diễn return % để tránh nhầm GLD/SLV với giá spot; nếu biểu diễn giá, phải chuyển cả dự báo lẫn thực tế về cùng chuỗi và đơn vị. Chi tiết lưu trữ actual/correction và phân trang do Tuấn/Tiến chốt.

---

## 7. Edge cases và vận hành

| Tình huống | Quy tắc đề xuất |
|---|---|
| `is_sample=true` hoặc `created_at` trước 27/10 12:00Z | Loại khỏi rolling production |
| Phát hành 27/10 cho `base_date=26/10` | Vẫn xét nếu đạt các điều kiện hợp lệ |
| `h=1` có `target_date` cùng ngày phát hành | So timestamp theo cutoff, không so ngày; kiểm input-as-of |
| Đã có forecast production cùng `(asset, base_date)` | Conditional write chặn ghi đè; retry idempotent, có log |
| Run có lỗi nhưng một số asset phát hành thành công | Log/truy vết riêng từng asset, không coi toàn run thành công |
| Thiếu forecast trong kỳ dự kiến | Đối chiếu lịch + log, tách `no_forecast_row` khỏi skip/fail và thiếu chứng cứ |
| Ingest không xác định được `base_date` | Ghi lỗi ingest; không tạo kỳ `base_date` giả |
| `prob_up` lệch ≤ `1e-6` sau kiểm tra shape | Chấp nhận tương thích làm tròn, giữ giá trị nguồn |
| `prob_up` lệch > `1e-6` | Ghi lại để kiểm tra theo policy; không ghi đè |
| `target_date` chưa đến hoặc giá chưa published | `pending`, không tăng `n_obs` |
| Endpoint missing/rejected/giá không dương | Loại với reason; không nội suy endpoint |
| Thiếu giá giữa hai endpoint | Không tự loại target nếu endpoint hợp lệ; ghi số phiên thiếu |
| `n_obs=0` | `status=undefined`, không hiện tỷ lệ |
| Ít hơn 20 `base_date` có cặp đã chấm (đề xuất) | Web chỉ X/Y và số ngày dự báo, không hiển thị phần trăm overall |
| Nhiều horizon cùng một `base_date` | Đếm theo cặp, không gọi là số lần thử độc lập |
| Đổi champion | Bắt đầu lại thống kê từ ngày hiệu lực; không trộn đời model |
| Sửa snapshot hoặc job lỗi giữa chừng | Run/correction mới có dấu vết; không thay latest completed bằng run lỗi |
| Validation 2019, test 2020–2026 | Không đưa vào rolling live |

---

## 8. Quyết định chờ nhóm chốt (họp 30/10)

| ID | Vấn đề | Phương án trong RFC v3 | Người chốt |
|---|---|---|---|
| D01 | Neo rolling 8 tuần | Ngày chạy job UTC, 56 ngày lịch inclusive, lọc `base_date` | Khải + Tuấn |
| D02 | Bắt đầu forecast live | `created_at >= 2026-10-27T12:00:00Z` | Khải + Tiến |
| D03 | Tần suất job | Tuần 1 lần sau ingest/snapshot hoàn tất | Long + Tuấn |
| D04 | Forecast immutable | Conditional `PutItem`, không overwrite production; retry idempotent | Khải + Tuấn + Tiến |
| D05 | DynamoDB Accuracy | PK/SK/GSI, IAM, TTL, latest completed | Tuấn |
| D06 | Ngưỡng hiển thị coverage | Ít nhất 20 `base_date` khác nhau có cặp hợp lệ | Khải + Tiến |
| D07 | JSON `/accuracy/{asset}` | Overall và 7 h, 4 metric Dashboard MVP, trạng thái riêng | Long + Tuấn + Tiến |
| D08 | Endpoint history | Ưu tiên `GET /forecast-history/{asset}` riêng | Khải + Tuấn + Tiến |
| D09 | Lưu forecast–actual pairs | Tính khi đọc hoặc lưu detail ngoài bảng Accuracy | Tuấn + Long |
| D10 | Khi đổi champion | Chỉ champion; đếm lại từ ngày hiệu lực | Khải + Long |
| D11 | Hiển thị theo horizon | Chỉ X/Y từng h; overall có thể hiện % khi đạt ngưỡng | Khải + Tiến |
| D12 | Snapshot correction | Giữ tham chiếu nguồn và lịch sử chấm lại | Long + Tuấn |
| D13 | Validation 2019 trên Dashboard | Để trong mục “Phương pháp”, không đặt cạnh rolling | Khải |
| D14 (Issue #23.2) | Publication schedule | Calendar + lịch predict TUE–SAT + logs; không thêm kho manifest MVP | Khải + Tuấn + Tiến |
| D15 (Issue #23.2) | Khi thiếu logs/schedule evidence | Chốt trạng thái thiếu chứng cứ và điều kiện công bố chính thức | Khải + Tuấn |
| D16 (Issue #23.1) | `prob_up` 6 chữ số | Tolerance `1e-6`, giữ nguồn; chốt policy khi vượt ngưỡng | Khải + Tuấn |
| D17 (Issue #23.3) | Import provenance | Ngoài rolling MVP; giữ `external_unverified` cho import/historical khác | Khải + Tuấn + Tiến |
| D18 | Cutoff dự báo trước nhãn | `created_at < target_date 13:30 UTC` và input-as-of | Khải + Tuấn + Tiến |

**Không coi các lựa chọn ở bảng trên là contract chính thức khi chưa được chốt.** Issue #23 mục 2 chỉ hoàn tất về mặt contract sau khi PR cập nhật contract tương ứng merge; không mặc định toàn bộ Issue #23 đã được đóng hoặc code đã hỗ trợ.

---

## 9. Acceptance criteria và kế hoạch kiểm thử

### 9.1. Contract / Schema

- [ ] Nhóm duyệt mốc thời gian forecast production, cutoff, window và quy tắc chấm trước khi biết nhãn.
- [ ] Chốt derived schedule thay kho manifest cho MVP và cập nhật `docs/eval/walk-forward-contract.md` nếu quyết định thay đổi điều kiện nguồn chuẩn.
- [ ] Duyệt cơ chế conditional write + trạng thái retry trên đường predict.
- [ ] Duyệt JSON response, trạng thái không đủ dữ liệu, `n_base_dates`, ngưỡng 20 và metric phục vụ web.
- [ ] Giữ `evaluation_kind=rolling_8w`, `target_cutoff_date`, khóa logic, `n_obs` và `status` theo Accuracy Schema.
- [ ] Chốt rule `prob_up` rounding và xử lý khi dữ liệu không nhất quán.

### 9.2. Functional tests

- [ ] Dự báo trước mốc `2026-10-27T12:00Z`, `is_sample=true`, test/backfill không vào rolling.
- [ ] Forecast h=1 ghi 12:15 UTC đúng ngày đích có thể hợp lệ; forecast qua cutoff 13:30 UTC bị loại theo policy; kiểm hai chế độ DST.
- [ ] Input-as-of và target publication chặn dùng thông tin/nhãn tương lai.
- [ ] Trading calendar asset/horizon, missing endpoints và missing giữa endpoints tuân ADR-0008.
- [ ] Lịch dự kiến và log phân biệt forecast phát hành, skip, fail, missing và không xác minh được; không bịa `base_date` khi ingest lỗi.
- [ ] Conditional write: insert mới, thay sample, chặn production overwrite, retry idempotent; lỗi ghi thật vẫn báo lỗi.
- [ ] Rounding `prob_up` dưới/trên ngưỡng, q gần 0/tie/clip; giữ q/p nguồn.
- [ ] `overall.coverage_80` cộng hit/count đúng; `n_base_dates` chỉ đếm các ngày có cặp đánh giá hợp lệ; kiểm n=0/19/20.
- [ ] `sign_accuracy` luôn kèm `up_rate` và `n_obs` riêng; `width_80` ghi đơn vị log return.
- [ ] API đủ 4 asset × 7 horizons; champion đổi không trộn; run lỗi/partial không thay latest completed.
- [ ] Chưa có run, lỗi asset/auth, missing quality/roll dầu, API không tiết lộ AWS details.

### 9.3. Nghiệm thu MVP

- Job tính kết quả từ forecast thực đã phát hành và target hợp lệ; có metadata truy vết nguồn, mốc thời gian và tình trạng publication.
- `/accuracy/{asset}` trả bốn metric Dashboard với `n_obs` theo từng h/overall, cutoff, trạng thái tính toán và hiển thị theo policy được duyệt.
- Dashboard có thể ghi “Kể từ 27/10” và hiển thị X/Y từ N ngày dự báo; không tuyên bố đã có đủ 8 tuần hoặc dữ liệu thống kê độc lập.
- Không sửa kết quả Validation 2019 và không backfill forecast test.

---

## 10. Phân công, mốc thời gian và cách cập nhật contract

| Mốc | Đầu ra | Chủ trì / review |
|---|---|---|
| **28–29/10/2026** | RFC v3 đưa review PR #45 | Long; Khải/Tuấn/Tiến |
| **30/10/2026** | Họp chốt Rolling policy, hiển thị, API và Issue #23 liên quan | Khải + nhóm |
| **Sau họp/duyệt** | PR cập nhật `docs/api/contract.md`; cập nhật `docs/eval/walk-forward-contract.md`/schema/ADR nếu quyết định làm thay đổi nguồn chuẩn | Long + Tuấn, review Khải/Tiến |
| **05/11/2026 (dự kiến)** | Job `rolling_8w` + `/accuracy/{asset}` | Long; Tuấn (API/IAM), Tiến (Web), Khải (predict) |
| **15/11/2026 (dự kiến)** | Khối độ tin cậy và biểu đồ forecast–actual | Long + Tiến |
| **22/11/2026** | Đóng băng tính năng | Nhóm |

**Quy trình:** RFC → review/chốt → PR contract → PR implementation + tests → deploy và xác minh dữ liệu production. PR #45 là PR review, **không merge**; sau khi các quyết định được chuyển vào PR contract và được duyệt, đóng PR #45 không merge. Không cập nhật code hoặc contract chính thức trong PR RFC này.

**File RFC trong repository:** `docs/proposal/rolling-accuracy-design.md` (không phải `docs/proposals/`).

### Những nội dung chuyển vào contract sau khi được duyệt

1. Quy tắc cửa sổ rolling, cutoff `created_at`/`target_date`, champion và chọn target có nhãn hợp lệ.
2. Điều kiện lịch phát hành kỳ vọng và classification của trường hợp thiếu forecast; cập nhật Walk-forward contract khi cần.
3. `/accuracy/{asset}`: auth, JSON fields, errors, overall/by-horizon, `n_obs`, `n_base_dates`, ngưỡng UX, trạng thái.
4. API lịch sử nếu được chọn: route, filter, phân trang, pending/observed, nguồn return/price.
5. Bảo vệ bản forecast gốc và nguyên tắc không ghi đè `prob_up` nguồn.

---

## Phụ lục A — Đối chiếu source code

- Theo review Khải, tài liệu ở GitHub dẫn commit **`a5f770c`** thay vì tên ZIP source. Khi chuyển sang contract, đối chiếu commit thực tế với nhánh đang deploy.
- `docs/api/contract.md`: `/accuracy/{asset}` chưa có JSON chính thức trong snapshot được review.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, `target_cutoff_date`, common mask và status.
- `docs/eval/walk-forward-contract.md`: hiện yêu cầu publication manifest; nếu nhóm chọn phương án lịch dẫn xuất cho MVP, cần PR cập nhật policy tương ứng.
- `src/forecast/predict.py`: `put_item` hiện có thể ghi đè cùng khóa; conditional write do Khải triển khai ở PR predict riêng nếu được duyệt.
- `src/eval/metrics.py`: có helper metrics; chưa có orchestration rolling hoàn chỉnh theo RFC.
- `infra/lambda/forecast_api/handler.py`: chưa hỗ trợ `/accuracy/{asset}` trong snapshot được review.

Các trạng thái code là từ snapshot đã dùng để soạn RFC, không xác nhận deployment AWS đang chạy.

## Phụ lục B — Tài liệu tham khảo

1. *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (chèn liên kết nội bộ chính thức khi được cung cấp).
2. [Issue #23 — Walk-forward phase 2](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/issues/23).
3. `docs/adr/0008-target-quantiles-evaluation.md`, `docs/api/accuracy-schema.md`, `docs/eval/walk-forward-contract.md`.
4. [DynamoDB PutItem](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html).
5. Dawid (1984), *The Prequential Approach*, DOI: https://doi.org/10.2307/2981683.
6. Gneiting et al. (2007), *Probabilistic Forecasts, Calibration and Sharpness*, DOI: https://doi.org/10.1111/j.1467-9868.2007.00587.x.

> **Trạng thái cuối:** RFC v3 là đề xuất kỹ thuật phục vụ review và họp 30/10; chỉ contract được phê duyệt qua PR riêng mới là chuẩn implementation.
