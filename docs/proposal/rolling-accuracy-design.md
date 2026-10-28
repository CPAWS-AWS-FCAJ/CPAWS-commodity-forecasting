# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** DRAFT / PROPOSAL — **chưa được phê duyệt, chưa phải API contract chính thức**  
> **Ngày soạn:** 2026-10-28  
> **Người đề xuất:** Long — nhóm CPAWS  
> **Người review:** Khải (đánh giá/hiển thị), Tuấn (API, DynamoDB, IAM), Tiến (Predict, Web)  
> **Đích sau khi duyệt:** cập nhật `docs/api/contract.md` bằng PR riêng; nếu cần thay đổi logic lưu trữ thì cập nhật `docs/api/accuracy-schema.md`/ADR qua quy trình review.  
> **Tài liệu tham chiếu trong `developer`:** `docs/api/contract.md`, `docs/api/accuracy-schema.md`, `docs/adr/0008-target-quantiles-evaluation.md`, `src/eval/metrics.py`, `src/forecast/forecast_record.py`, `src/forecast/returns.py`, `src/data/storage.py`, `infra/stacks/cpaws_serving_stack.py`, `infra/lambda/forecast_api/handler.py`.  
> **Đặc tả sản phẩm:** *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (5 trang).

## Tóm tắt quyết định và phạm vi

Mục đích của RFC là thống nhất **cách đánh giá dự báo đã phát hành thật** rồi trả kết quả cho dashboard, **trước khi** sửa hợp đồng API hoặc viết job. Hai chức năng được đề xuất:

1. Job `rolling_8w` tính độ tin cậy trên các cặp dự báo–giá thực tế đủ điều kiện và lưu kết quả theo Accuracy Schema hiện hành.
2. `GET /accuracy/{asset}` cung cấp chỉ số tổng hợp; **đề xuất** endpoint riêng `GET /forecast-history/{asset}` phục vụ biểu đồ “dự báo cũ so với thực tế”.

**Đã có căn cứ/chốt:** bốn asset `gold/silver/brent/wti`; horizon 1–7 **phiên giao dịch**; đánh giá trên **log return**; chỉ dùng forecast được phát hành thật từ 27/10/2026, không tạo ngược forecast cho tập test; `evaluation_kind=rolling_8w` lưu trên DynamoDB, validation/test lưu Parquet S3 `eval/`; coverage danh nghĩa 80%; `sign_accuracy` luôn đi cùng `up_rate` khi hiển thị. Theo PDF, dưới 20 lần đo **không hiển thị tỷ lệ coverage** (ngưỡng 20 dự kiến chốt trong họp 30/10).

**Chưa chốt:** mốc neo 56 ngày, thời điểm chạy job, bảng/index DynamoDB Accuracy, cơ chế bất biến của forecast đã phát hành, JSON API cuối cùng, endpoint lịch sử, khả năng lưu chi tiết từng cặp, số quan sát tối thiểu, xử lý nhiều `model_version`.

**Ngoài phạm vi RFC/PR tài liệu:** thay model, train/retrain, thay logic DM-HAC, triển khai IAM/CDK/Lambda, tự chạy backfill 2020–2026, chỉnh sửa các bộ Validation 2019 hoặc Parquet đã upload S3.

---

## 1. Mục tiêu và tiêu chí thành công

### 1.1. Bài toán

`baseline-q252` trả về **phân phối dự báo** bằng 7 phân vị cho mỗi h=1..7. Dashboard hiện có thể trình bày khoảng q10–q90 và `prob_up`, nhưng người dùng cần thấy lịch sử thực tế để đánh giá: (a) giá có nằm trong khoảng không, (b) mức độ rộng của khoảng, (c) dự báo hướng có tốt hơn cách luôn dự đoán tăng không.

### 1.2. Mục tiêu MVP

- Ghi nhận và chấm **forecast được phát hành trước khi nhãn tương lai được biết**; mỗi phép chấm truy vết được nguồn dự báo và nguồn giá.
- Tính `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`, `n_obs` và các metric hiện hành khi đủ đầu vào; tính theo từng horizon, hỗ trợ số liệu tổng hợp để web hiển thị.
- Chỉ trình bày coverage dưới dạng tỷ lệ khi mẫu đạt ngưỡng được nhóm chốt (PDF đề xuất **20**); nếu chưa đạt, trả lý do và số lần đo, **không bịa độ chính xác**.
- Giữ nguyên phân biệt giữa **metric có thể tính** (`status=ok` trong bảng Accuracy) và **metric được phép hiển thị** (`display_status` ở API).
- Khi dữ liệu chưa hoàn tất, không âm thầm đổi ngày mục tiêu hay dùng giá tương lai; tiếp tục công bố số lần đo thực.
- Tách rõ trách nhiệm job đánh giá, bảng lưu kết quả, API và frontend.

### 1.3. Không phải mục tiêu

- Không đánh giá khả năng sinh lợi hoặc khuyến nghị đầu tư.
- Không đưa MAPE/RMSE trên mức giá vào Accuracy Schema.
- Không đánh giá lại 2020–2026 bằng dự báo phát hành giả định sau khi biết nhãn.
- Không tuyên bố tỷ lệ coverage 80% chứng minh dự báo đã được hiệu chỉnh tốt khi mẫu nhỏ/phụ thuộc.

## 2. Nguồn dữ liệu, khóa ghép và tính bất biến

### 2.1. Nguồn đã tồn tại trong code

| Nguồn | Cấu trúc hiện có | Vai trò |
|---|---|---|
| DynamoDB `Forecasts` | PK=`asset`, SK=`base_date`; `created_at`, `model_version`, `target_series`, `horizons[].{h,target_date,q,prob_up}`, `is_sample` | Dự báo đã ghi |
| S3 clean snapshot | `clean/prices/dt=YYYY-MM-DD/prices.parquet`, kèm `rejected.parquet`, `quality.json` | Giá/quality dùng để tạo nhãn |
| `src/data/calendars.py` và `src/forecast/returns.py` | Lịch NYSE/CME và định nghĩa h-session log return | Xác minh `target_date`, target hợp lệ |
| `src/eval/metrics.py` | Các hàm đo coverage, width, sign accuracy, up rate, v.v. | Tái sử dụng phép tính |
| `docs/api/accuracy-schema.md` | Mỗi metric một dòng; có `evaluation_kind`, cutoff, status, `n_obs` | Hợp đồng lưu kết quả |

**Đúng target:** `gold → GLD`, `silver → SLV`, `brent → BZ=F`, `wti → CL=F`. Các phân vị trong `horizons[].q` là **log return**, **không phải giá**. Với GLD/SLV, `last_price` trong Forecasts là giá *hiển thị quy đổi USD/oz*, nên **không** dùng `last_price` đó thay cho giá đóng cửa GLD/SLV để tính nhãn return thực.

### 2.2. Ghép cặp dự báo–nhãn

Mỗi quan sát ứng viên được nhận diện theo `(asset, base_date, h, model_version, forecast_issuance_id [đề xuất])`, với `target_date` lưu từ forecast và xác nhận theo lịch giao dịch tài sản. Nhãn thực:

`y(t,h) = ln(P_target(target_date) / P_target(base_date))`

Chỉ dùng các giá đầu/cuối hợp lệ theo ADR-0008. Giá thiếu giữa hai endpoint **không tự làm target vô hiệu**, nhưng phải ghi log số phiên thiếu; không nội suy để chế tạo endpoint. Trường hợp WTI giá không dương phải tuân theo quy tắc bất thường/flag của ADR, không tính log return không xác định.

### 2.3. Dự báo đủ điều kiện đánh giá

1. `is_sample=false`; asset, horizon, bảy phân vị, `base_date` và `target_date` hợp lệ.
2. Có **bằng chứng dự báo đã phát hành** tại/ sau mốc vận hành thực tế **2026-10-27**; kiểm tra `created_at`/thời điểm lưu thực tế và `source`/provenance nếu có. `base_date` có thể trước 27/10 vì là ngày giá cuối cùng, **không** dùng riêng `base_date >= 2026-10-27` để nhận diện forecast thật.
3. `created_at`/thời điểm ghi ban đầu phải **sớm hơn thời điểm giá ở `target_date` được công bố/biết**; không chỉ so ngày dạng YYYY-MM-DD.
4. `target_date` đã đến hạn và giá target hợp lệ thực sự có sẵn tại thời điểm job chạy (publication/as-of checks); không sử dụng ngày đích thuộc tương lai hoặc giá chưa xuất bản.
5. Giữ `model_version` và trạng thái `sample` đúng như đã phát hành. Không ghép/đổi model một cách ngầm định.
6. Khi tính các metric đòi hỏi baseline, tuân theo điều kiện baseline/common mask trong Accuracy Schema; không thay đổi mask từng metric để làm kết quả đẹp hơn.

### 2.4. **Vấn đề bắt buộc chốt: Forecasts có thể bị ghi đè**

Implementation hiện tại gọi `Table.put_item(Item=record)` với khóa `(asset, base_date)`; lệnh `PutItem` có thể **thay thế** forecast trước đó. Đây là rủi ro đối với đánh giá prequential: dự báo người dùng đã nhìn thấy có thể khác bản còn lại trong bảng khi job chạy.

**[ĐỀ XUẤT]** đảm bảo một *bản phát hành bất biến* bằng một trong hai phương án:

- **A — Lưu append-only (ưu tiên nếu cần kiểm toán/so sánh model):** tạo kho lịch sử phát hành riêng có `forecast_issuance_id`, thời điểm phát hành, model, payload/hash và trạng thái; bảng `Forecasts` hiện có tiếp tục phục vụ “bản mới nhất”. Rolling đọc bản phát hành chính thức đã cố định.
- **B — Conditional write + chính sách bản đầu tiên:** ngăn ghi đè cùng khóa và định nghĩa retry idempotent; cần giải quyết nhu cầu chạy lại và chuyển model trước khi áp dụng.

Tuấn/Tiến chọn giải pháp và phạm vi IAM. **Không coi `created_at` đơn thuần là bảo chứng bất biến nếu record vẫn bị overwrite.**

## 3. Rolling window và quy tắc evaluation

### 3.1. Phạm vi 8 tuần **[ĐỀ XUẤT — CẦN KHẢI/TUẤN CHỐT]**

| Trường | Đề xuất | Vì sao |
|---|---|---|
| `evaluation_kind` | `rolling_8w` | Đúng Accuracy Schema |
| `window_days` | 56 **ngày lịch**, không phải 56 phiên | Phù hợp “8 tuần” |
| `window_anchor` | Ngày job chạy theo UTC | Dễ vận hành và tái lập |
| `window_basis` | `base_date` (ngày gốc t) | Phù hợp đề xuất hiện tại trong Accuracy Schema |
| `evaluation_start/end` | Khoảng base_date thuộc cửa sổ; với giới hạn 56 ngày inclusive, `[run_date-55d, run_date]` | Loại sai lệch biên một ngày |
| `issued_at_min` | 2026-10-27T00:00:00 theo múi giờ **nhóm chốt**; dùng timestamp phát hành thực tế | Tránh backfill; mốc ngày địa phương cần chốt |
| `target_cutoff_date` | Ngày giá target hợp lệ/công bố cuối thực có sẵn, riêng từng asset | Không mặc định bằng ngày job |
| Tần suất | **Đề xuất** 1 lần/tuần sau ingest và sau khi dữ liệu có trạng thái hợp lệ | Đảm bảo đủ dữ liệu và tránh chấm nhãn chưa có |

Ví dụ job ngày 05/11/2026: cửa sổ 56 ngày lý thuyết là **11/09–05/11/2026** (tính cả hai đầu), nhưng kho forecast thật chỉ bắt đầu phát hành từ 27/10, nên thống kê có thể còn nhỏ. Trong response, nếu `evaluation_start/end` mô tả khoảng ngày gốc *thực sự có forecast được xét* thì phải thêm `window_start/window_end` riêng để không nhầm với ranh giới 56 ngày; cách thể hiện cuối cùng cần nhóm chốt. Response phải công khai `evaluation_start`, `evaluation_end`, cutoff riêng asset, `evaluated_at`, `n_obs` và thông điệp “kể từ 27/10”, không tự giới thiệu “đã đo đủ 8 tuần”.

**Vấn đề cần chốt:** anchor theo ngày job hay giá mới nhất, timezone mốc 27/10, cutoff theo publication data, ý nghĩa của cửa sổ khi dự báo được phát hành trễ so với `base_date`.

### 3.2. Luồng job

1. Chọn snapshot giá/quality đã hoàn tất tại thời điểm job, khóa tham chiếu snapshot/etag/hash; lấy target cutoff riêng asset.
2. Truy vấn các forecast phát hành thật, bất biến, trong rolling window; kiểm tra tính hợp lệ và thời điểm công bố.
3. Tách 7 horizons/record; ghép giá đầu-cuối từ **đúng chuỗi target**, xác nhận `target_date` là phiên giao dịch thứ h sau `base_date`.
4. Xây `common_mask` và các bộ đếm loại mẫu theo Accuracy Schema, chỉ chấm horizon có target hoàn tất.
5. Tính metrics **theo từng `(asset, model_version, sample, h)`**; đếm `n_obs` theo đúng từng metric.
6. Tạo các dòng Accuracy với `evaluation_kind=rolling_8w`, `run_id`, `config_hash`, `evaluation_start/end`, `target_cutoff_date`, `status`, `undefined_reason`.
7. Ghi DynamoDB Accuracy một cách idempotent, không làm hỏng kết quả gần nhất nếu run lỗi giữa chừng. Chỉ đổi *latest completed run* khi ghi đủ toàn bộ kết quả.
8. Log run metadata: số forecast đủ điều kiện, số horizons chín muồi, số mẫu bị loại theo lý do, snapshot, UTC execution/issuance, các lỗi publication/giá. Bảo vệ không ghi/log thông tin bí mật.

**Không bao gồm:** gọi predict để tạo thêm forecasts lịch sử, tự điều chỉnh K3/K3b/K4, sửa Validation 2019, ghi `validation/test` vào DynamoDB Accuracy.

### 3.3. Metric và `n_obs`

| Metric | Định nghĩa / quy tắc | Ghi chú hiển thị |
|---|---|---|
| `coverage_80` | `mean(q10 <= y <= q90)` trên return thực | Số lần “trong khoảng”/số lần đo; mục tiêu 80% |
| `width_80` | `mean(q90-q10)` | Đánh giá độ rộng, tránh tối ưu coverage bằng cách làm khoảng quá rộng |
| `sign_accuracy` | Tỷ lệ dấu q50 đúng dấu y; bỏ `y=0` hoặc `q50=0` | **Chỉ trình bày cùng `up_rate`** |
| `up_rate` | `mean(y>0)` trên common mask | Có thể có `n_obs` khác `sign_accuracy` |
| Các metric khác | `quantile_hit_*`, `interval_score_80`, `brier_skill`, `pinball_skill`, `mae_ratio_vs_naive` theo Accuracy Schema | Không thay công thức gốc; trả khi thật sự có thể tính |

**Mẫu tổng hợp qua horizons:** nếu cần `overall.coverage_80`, lấy tổng số hit chia tổng số cặp `(base_date,h)` đủ điều kiện, **không** lấy trung bình đều của các tỷ lệ từng h khi `n_obs` khác nhau. Các cặp ở nhiều horizons có thể chung ngày và phụ thuộc; không giải thích `n_obs` như số lần thử độc lập.

**Ngưỡng hiển thị (PDF đề xuất):** với `n_obs < 20` cho chính phạm vi đang hiển thị, `coverage_80` *vẫn có thể được tính và lưu `status=ok`*, nhưng API trả `display_value=null`, `display_status=insufficient_data` và số cặp đã đo. Ngưỡng 20 là quy tắc UX **không phải** chứng minh độ hiệu chỉnh có ý nghĩa thống kê.

## 4. Accuracy Storage (lưu và truy xuất)

- **Đã chốt trong Accuracy Schema:** `validation` và `test` → Parquet trên S3 `eval/`; **chỉ** `rolling_8w` → DynamoDB phục vụ `/accuracy/{asset}`.
- Mỗi metric trong Accuracy Schema là **một dòng** có khóa logic `(run_id, model_version, asset, sample, evaluation_kind, evaluation_start, evaluation_end, target_cutoff_date, h, metric)`; **không được** nhầm khóa logic thành PK/SK vật lý DynamoDB.
- **[CẦN TUẤN CHỐT]** thiết kế bảng, PK/SK/GSI, kiểu truy vấn latest per-asset/model, chính sách TTL, ghi theo batch, quyền đọc/ghi tối thiểu, quy tắc idempotency và run completion marker.
- **[ĐỀ XUẤT]** lưu thống kê hit_count hoặc số liệu đủ để dựng tỷ lệ tổng hợp `overall` một cách chính xác (có thể ở lớp kết quả aggregate/chi tiết). Nếu phải mở rộng schema chính thức, yêu cầu PR riêng và review trước.
- **[CẦN CHỐT]** kết quả ghép từng forecast với nhãn dùng cho biểu đồ lịch sử được (A) tính khi đọc S3 hay (B) lưu kết quả chi tiết có provenance. B được ưu tiên nếu cần hiệu năng/audit, nhưng phải định nghĩa nơi lưu/TTL/quyền; **không tự ghi dữ liệu forecast history vào bảng Accuracy hiện tại** khi schema chưa cho phép.
- Mọi run lưu hoặc tham chiếu `run_id`, `config_hash`, snapshot ID/etag/hash, thời điểm job, tính toàn vẹn, số cặp lỗi; API đọc bản run **hoàn thành mới nhất**, không đọc run đang dở.

## 5. API: `GET /accuracy/{asset}` **[ĐỀ XUẤT]**

### 5.1. Request

`GET /accuracy/wti` — Có `Authorization: <Cognito ID token>` như các endpoint (trừ `/health`) trong contract hiện tại. Asset phải là `gold`, `silver`, `brent` hoặc `wti`. Đề xuất MVP mặc định `sample=all`, `evaluation_kind=rolling_8w` và model đang chạy; query params khác chỉ thêm sau khi chốt.

### 5.2. JSON response đề xuất

> **Ví dụ minh họa định dạng, KHÔNG phải dữ liệu dự báo/chỉ số CPAWS đã chạy thật.** Dãy `by_horizon` rút gọn chỉ hiện 2 phần tử; API thật trả đủ h=1..7 với trạng thái phù hợp.

```json
{
  "asset": "wti",
  "model_version": "baseline-q252",
  "evaluation_kind": "rolling_8w",
  "sample": "all",
  "run_id": "example-rolling-2026-11-05-wti",
  "evaluated_at": "2026-11-05T13:00:00Z",
  "window": {
    "basis": "base_date",
    "days": 56,
    "window_start": "2026-09-11",
    "window_end": "2026-11-05",
    "evaluation_start": "2026-10-27",
    "evaluation_end": "2026-11-05",
    "target_cutoff_date": "2026-11-04",
    "first_real_issuance_date": "2026-10-27"
  },
  "overall": {
    "coverage_80": {
      "display_value": null,
      "covered_count": 14,
      "n_obs": 18,
      "nominal": 0.8,
      "min_display_n": 20,
      "status": "ok",
      "display_status": "insufficient_data"
    },
    "sign_accuracy": {
      "value": 0.5,
      "n_obs": 16,
      "status": "ok"
    },
    "up_rate": {
      "value": 0.555556,
      "n_obs": 18,
      "status": "ok"
    }
  },
  "by_horizon": [
    {
      "h": 1,
      "coverage_80": {
        "display_value": null,
        "covered_count": 5,
        "n_obs": 7,
        "display_status": "insufficient_data"
      },
      "width_80": {"value": 0.025, "n_obs": 7, "status": "ok"}
    },
    {
      "h": 2,
      "coverage_80": {
        "display_value": null,
        "covered_count": 4,
        "n_obs": 6,
        "display_status": "insufficient_data"
      }
    }
  ],
  "data_status": "collecting",
  "disclaimer": "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."
}
```

### 5.3. Quy ước API

- `overall` là tổng hợp theo cặp dự báo–horizon, **không** giả làm metric cùng h=0 trong schema (h chỉ 1..7). Tính từ counts/chi tiết hoặc tổng có trọng số nhất quán.
- `by_horizon` trả đủ 7 phần tử, có `n_obs` và `status` riêng; tránh bỏ horizon không đủ dữ liệu làm web hiểu sai là không tồn tại.
- `coverage_80.display_value=null` khi chưa đủ 20 lần đo. Số liệu thô vẫn tính/lưu nội bộ; không ép Accuracy Schema `status=undefined` chỉ do chưa vượt ngưỡng UX.
- `sign_accuracy` **không được trình bày độc lập** nếu thiếu `up_rate`; cả hai luôn trả kèm `n_obs`, thừa nhận mẫu so sánh có thể khác nhau.
- `data_status`: **đề xuất** `not_ready` (chưa có run đủ điều kiện), `collecting` (có nhưng ít dữ liệu), `ready` (đã đủ ngưỡng hiển thị). Chưa có giá thì **không tự sinh tỷ lệ bằng 0**.
- Khi chưa có run: **đề xuất** HTTP 200 với `data_status=not_ready`, `overall=null`, `by_horizon=[]` hoặc 7 horizon rỗng (cần chốt), không gọi là lỗi hệ thống.
- Lỗi `400 invalid_asset`, lỗi auth theo Cognito và lỗi hạ tầng (`500 internal_error`) sử dụng envelope lỗi `{"error":"...","message":"..."}` đang có trong contract. Không đưa raw AWS errors ra ngoài.
- API chỉ trả dữ liệu cần cho web, không có AWS credentials, S3 private keys hoặc thông tin nhạy cảm trong response.

## 6. API biểu đồ “dự báo cũ so với thực tế”

### 6.1. So sánh phương án

| Phương án | Ưu điểm | Hạn chế | Đề xuất |
|---|---|---|---|
| A. Nhúng lịch sử vào `/accuracy/{asset}` | Một request | Response phình to; khó phân trang, trộn metrics tổng hợp và chuỗi chi tiết | Không ưu tiên |
| B. Endpoint riêng `GET /forecast-history/{asset}` | Phân trang/filter h; rõ trách nhiệm; web chỉ gọi khi mở biểu đồ | Thêm route/IAM/implementation | **Ưu tiên; chờ Tuấn + Tiến duyệt** |

### 6.2. Request/response phác thảo

`GET /forecast-history/wti?h=3&limit=30` (Cognito ID token). Đề xuất `h` từ 1..7, giới hạn `limit`/`cursor`, sort giảm theo `base_date` và thời điểm phát hành cố định; có thể thêm `status=observed|pending` sau khi chốt.

> Ví dụ minh họa, không phải dữ liệu thật:

```json
{
  "asset": "wti",
  "h": 3,
  "items": [
    {
      "forecast_issuance_id": "example-immutable-id",
      "base_date": "2026-10-27",
      "target_date": "2026-10-30",
      "created_at": "2026-10-27T13:00:00Z",
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

- Với `actual.status=pending`, `actual.log_return=null` và `inside_80=null`; tuyệt đối không suy ra nhãn khi chưa có giá.
- Biểu đồ mặc định hiển thị **return %** sẽ tránh nhầm chuỗi GLD/SLV với giá giao ngay. Nếu hiển thị khoảng giá, phải chuyển đổi cả dự báo lẫn thực tế **trên cùng chuỗi/cơ sở hiển thị**, giữ nhãn nguồn và đơn vị.
- Endpoint chỉ trả các forecast phát hành thật và đã lưu; không tạo lại forecast lịch sử khi GET.
- Nếu dùng DynamoDB Query từ bảng hiện tại, cần xử lý `Limit`, cursor và thứ tự; nhưng bảng Forecasts **không giữ được các phiên bản bị ghi đè** — phụ thuộc quyết định ở mục 2.4.
- **[CẦN TUẤN CHỐT]** lấy actual trực tiếp theo snapshot mỗi request hay đọc bảng/đối tượng chi tiết đã chấm và có provenance; tránh điểm thực tế thay đổi âm thầm khi snapshot revision.

## 7. Edge cases, chống leakage và vận hành

| Tình huống | Quy tắc đề xuất |
|---|---|
| `is_sample=true` | Loại, không tăng `n_obs` |
| `created_at` trước 27/10 hoặc không có chứng cứ phát hành thật | Loại khỏi rolling live; ghi lý do |
| Dự báo ngày 27/10 cho `base_date` 26/10 | Vẫn có thể chấm khi phát hành thật và qua window filter; không loại chỉ vì `base_date<27/10` |
| `target_date` chưa đến/giá chưa published | `pending`; không tăng số lần đo |
| Giá endpoint missing/rejected/không tính log return | Loại với reason; không nội suy |
| Thiếu giá ở giữa endpoints | Không tự loại target nếu endpoints hợp lệ; ghi log |
| Dự báo bị viết đè / chạy lại cùng key | Không chấm bản mới thay bản đã công bố; yêu cầu lịch sử immutable/conditional write |
| `model_version` đổi trong window | Không trộn vào một tỷ lệ không ghi nhãn; chốt policy phân nhóm hoặc theo champion hiện tại |
| `n_obs=0` | `status=undefined` theo schema (`no_evaluable_obs`); API `not_ready`/null |
| `0<n_obs<20` | Metric hợp lệ có thể `ok` nội bộ; API ẩn % coverage và hiển thị n |
| Nhiều horizons cùng một `base_date` | Tính từng cặp (t,h), thừa nhận phụ thuộc; không tự nói là n phép thử độc lập |
| Roll dầu | `sample=all` mặc định; `excl_roll` chỉ sau khi có logic theo horizon đủ chính xác và được duyệt |
| Snapshot được cập nhật/chỉnh lỗi quá khứ | Ghi snapshot ID/hash; quy định version/correction, không ghi đè điểm cũ mà mất dấu |
| Job lỗi nửa chừng | Không đổi latest completed run; retry idempotent |
| Dữ liệu quá ít trong bốn tuần đầu | Ghi “Kể từ 27/10, đã có Y lần đo”, không nói “đã đo đủ 8 tuần” |

## 8. Câu hỏi/Quyết định chờ nhóm chốt

| ID | Vấn đề | Phương án đề xuất | Người chốt | Mức độ |
|---|---|---|---|---|
| D01 | Neo 8 tuần theo gì? | Ngày chạy job UTC; lọc `base_date`; 56 ngày lịch inclusive | Khải + Tuấn | Bắt buộc trước coding |
| D02 | Mốc bắt đầu forecast live tính theo timezone nào? | UTC timestamp phát hành; xác nhận nghĩa ngày 27/10 theo VN/UTC | Khải + Tiến | Bắt buộc |
| D03 | Tần suất & trigger job | Tuần 1 lần, chỉ sau ingest/snapshot đã chốt | Long + Tuấn | Bắt buộc |
| D04 | Lưu forecast bất biến bằng cách nào? | Append-only issuance archive hoặc conditional write | Tuấn + Tiến | **Blocker đánh giá tin cậy** |
| D05 | PK/SK, GSI, IAM của Accuracy | Tuấn đề xuất từ access patterns `/accuracy/{asset}` | Tuấn | Bắt buộc |
| D06 | Mức tối thiểu hiển thị coverage | `min_display_n=20` theo PDF | Khải | Chờ 30/10 |
| D07 | Trả `overall` và 7 horizons như thế nào? | JSON trong mục 5, counts và status tách riêng | Long + Tuấn + Tiến | Bắt buộc |
| D08 | Lịch sử dự báo qua endpoint nào? | `GET /forecast-history/{asset}` riêng | Tuấn + Tiến + Khải | Chờ 30/10 |
| D09 | Lưu historical pairs/actual ở đâu? | Lưu chi tiết có provenance nếu cần phản hồi nhanh | Tuấn + Long | Cần cho biểu đồ |
| D10 | Khi đổi champion trong window? | Tách `model_version`, tránh trộn không nhãn | Khải + Long | Bắt buộc |
| D11 | Ngưỡng 20 áp dụng theo overall hay từng h? | Mỗi phạm vi được hiển thị có `n_obs` và ngưỡng riêng | Khải + Tiến | Chờ 30/10 |
| D12 | Actual correction/snapshot version | Giữ log phiên bản, xử lý chấm lại có audit trail | Long + Tuấn | Cần cho reproducibility |
| D13 | Hiển thị 2019 như “kiểm định lịch sử” riêng? | Không trộn với rolling live | Khải | Chờ 30/10 |

**Các lựa chọn ở bảng trên chưa được duyệt; không dùng câu chữ “đã chốt” khi copy sang contract chính thức.**

## 9. Acceptance criteria và kế hoạch kiểm thử

Trước khi approve RFC, nhóm cần chốt các quyết định D01–D08/D10/D11 và phạm vi D09/D12. Khi triển khai, ít nhất phải có:

### 9.1. Contract/Schema

- [ ] Có response JSON và lỗi API cuối cùng được Khải/Tuấn/Tiến chấp nhận.
- [ ] `evaluation_kind=rolling_8w`, `target_cutoff_date`, `n_obs`, `status` thống nhất với `accuracy-schema.md`; không tự thay đổi khóa logic.
- [ ] Không tạo metric mới hoặc đổi công thức ngầm trong tầng API; `overall` là tổng hợp hợp lệ của các horizon.
- [ ] Forecast history có chính sách bất biến, quyền truy cập, lọc h và phân trang.

### 9.2. Functional tests

- [ ] Cặp forecast thật có giá target mới được chấm; forecast mẫu, future label, backfill bị loại.
- [ ] `base_date` và `target_date` qua đúng calendar theo h; không nhầm ngày lịch với phiên.
- [ ] Missing endpoint/rejected khác missing ngày giữa endpoints; giữ thống kê loại mẫu.
- [ ] `coverage_80` đếm đúng số hit và mẫu; `overall` weighted/pooled đúng.
- [ ] Với n=0, 19, 20: kiểm tra `undefined`, `insufficient_data`, `ready`; **không sửa `status` nội bộ chỉ do ngưỡng UX**.
- [ ] `sign_accuracy` và `up_rate` luôn đi cặp, n_obs có thể khác; q50=0/y=0 xử lý như schema.
- [ ] Một forecast chạy lại cùng `(asset, base_date)` không thể âm thầm đổi dữ liệu dùng chấm.
- [ ] Thay đổi `model_version` không làm trộn số liệu, trừ khi contract có công bố rõ policy.
- [ ] Job retry và rerun có `run_id/config_hash`, ghi hoàn chỉnh và có khả năng tái lập từ snapshot.
- [ ] API không trả dữ liệu giả/historical test 2020–2026, không lộ AWS error/credentials.
- [ ] 4 assets, 7 horizons, Cognito/invalid asset, chưa có run, lỗi đọc storage, stale quality, roll dầu đều có tests.

### 9.3. Tiêu chí nghiệm thu MVP

- `GET /accuracy/{asset}` đọc kết quả rolling đã ghi thành công cho từng asset và trả `n_obs`, cutoff, trạng thái đúng.
- Dashboard có thể viết đúng câu “Kể từ 27/10, giá thực tế nằm trong khoảng 80% ở X/Y lần (mục tiêu 80%)” hoặc “Chưa đủ dữ liệu để đánh giá (mới có Y lần)” khi dưới ngưỡng.
- Biểu đồ lịch sử (giai đoạn tiếp theo) truy được từng forecast trước nhãn, q10/q90, actual/`pending` và tình trạng trong/ngoài khoảng.
- Không sửa đổi Validation 2019 và không đưa kết quả test lịch sử vào rolling live.

## 10. Phân công, mốc thời gian và cách cập nhật contract

| Mốc dự kiến | Đầu ra | Chủ trì | Review |
|---|---|---|---|
| **28–29/10/2026** | RFC này, ghi rõ các lựa chọn còn mở và JSON phác thảo | Long | Khải/Tuấn/Tiến |
| **30/10/2026** | Họp chốt rolling policy, display threshold và endpoint history | Khải + nhóm | — |
| **Sau RFC approved** | PR cập nhật **`docs/api/contract.md`** (và schema/ADR nếu quyết định làm thay đổi nguồn chuẩn), chỉ gồm nội dung đã chốt | Long, phối hợp Tuấn | Khải/Tuấn/Tiến |
| **05/11/2026** | Mốc **đề xuất**: `rolling_8w` job + `GET /accuracy/{asset}` | Long | Tuấn (API/IAM), Tiến (tích hợp) |
| **15/11/2026** | Mốc đề xuất: khối độ tin cậy và biểu đồ forecast cũ–actual | Long + Tiến | Tuấn |
| **22/11/2026** | Đóng băng tính năng | Cả nhóm | Khải |

### Quy trình thay đổi

**RFC (file hiện tại) → review/chốt nội dung → PR contract chính thức → PR implementation và tests → deploy + kiểm tra dữ liệu phát hành thật.** Không sửa `contract.md` trong bước RFC. Không mặc định tài liệu đề xuất này đã được thông qua.

### Những nội dung sẽ chuyển vào `docs/api/contract.md` khi được duyệt

1. Điều kiện `rolling_8w` / timestamp bắt đầu live / cutoff / cách lọc cửa sổ ở mức API cần biết.
2. `GET /accuracy/{asset}`: auth, query parameters, response JSON, status/errors, ý nghĩa `overall`, `by_horizon`, `n_obs`, quy tắc dưới 20 lần đo, liên kết `[Accuracy Schema](accuracy-schema.md)`.
3. Endpoint history nếu được chọn: tên route, filter, phân trang, định dạng `forecast_return`, `actual`, `inside_80`, `pending`.
4. Bảo đảm forecast phát hành thật và tính nhất quán của `model_version` ở giao diện API.

**Không chuyển các chi tiết nội bộ** như câu lệnh CDK, IAM policy JSON, thuật toán SQL/Query cụ thể vào API contract khi chưa cần thiết; chúng thuộc implementation/design notes.

---

## Phụ lục A — Đối chiếu source code bản `developer` được cung cấp

- `docs/api/contract.md`: `/accuracy/{asset}` nằm trong mục “Thêm sau”, mới mô tả danh sách metric; chưa định nghĩa response JSON chính thức hoặc endpoint history.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, status/undefined, common mask; **mốc neo 8 tuần và DynamoDB PK/SK chưa chốt**.
- `src/eval/metrics.py`: có helper `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`, v.v.; chưa có rolling orchestration.
- `src/forecast/forecast_record.py`: `horizons[].q` là log returns, `target_date` theo calendar; `last_price` vàng/bạc là giá hiển thị.
- `src/forecast/predict.py`: `DynamoDbWriter.put` dùng `put_item(Item=record)`; forecast hiện có thể bị thay thế khi cùng key.
- `infra/stacks/cpaws_serving_stack.py`: bảng `Forecasts` dùng PK=`asset`, SK=`base_date`; chưa có bảng `Accuracy` trong stack này.
- `infra/lambda/forecast_api/handler.py`: hiện hỗ trợ `/health`, `/forecasts`, `/forecasts/{asset}`; chưa có handler `/accuracy`.

> Source và trạng thái là từ **ZIP `CPAWS-commodity-forecasting-developer (2)(3).zip` được cung cấp**, không phải xác nhận deployment AWS ở thời điểm hiện tại.

## Phụ lục B — Cơ sở phương pháp / tài liệu đọc thêm

1. Dawid, A. P. (1984). *Statistical Theory: The Prequential Approach*. JRSS A. Nguyên tắc đánh giá tuần tự dự báo theo những gì đã phát hành trước khi quan sát kết quả. https://doi.org/10.2307/2981683
2. Gneiting, T., Balabdaoui, F., & Raftery, A. E. (2007). *Probabilistic Forecasts, Calibration and Sharpness*. JRSS B 69(2), 243–268. Đánh giá độ phủ (calibration) song song với độ rộng/sharpness, không tối ưu độ phủ một cách tách biệt. https://doi.org/10.1111/j.1467-9868.2007.00587.x
3. Amazon DynamoDB, *PutItem API*: `PutItem` thay thế item cùng primary key nếu không có điều kiện chặn, nên cần chính sách immutable/idempotent cho forecast đã phát hành. https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html

> Tài liệu học thuật/AWS dùng để **giải thích cơ sở thiết kế**, không thay thế quyết định ADR-0008, Accuracy Schema hoặc quy trình approve của nhóm.
