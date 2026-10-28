# RFC — Thiết kế Rolling Accuracy và API lịch sử dự báo (CPAWS)

> **Trạng thái:** DRAFT / PROPOSAL — **chưa được phê duyệt, chưa phải API contract chính thức**  
> **Ngày rà soát:** 2026-10-28 (bản v2 — kiểm tra lại tính nhất quán Issue #23, Accuracy Schema và JSON API)  
> **Người đề xuất:** Long — nhóm CPAWS  
> **Người review:** Khải (đánh giá/hiển thị), Tuấn (API, DynamoDB, IAM), Tiến (Predict, Web)  
> **Đích sau khi duyệt:** cập nhật `docs/api/contract.md` bằng PR riêng; nếu cần thay đổi logic lưu trữ thì cập nhật `docs/api/accuracy-schema.md`/ADR qua quy trình review.  
> **Tài liệu tham chiếu trong `developer`:** `docs/api/contract.md`, `docs/api/accuracy-schema.md`, `docs/adr/0008-target-quantiles-evaluation.md`, `src/eval/metrics.py`, `src/forecast/forecast_record.py`, `src/forecast/returns.py`, `src/data/storage.py`, `infra/stacks/cpaws_serving_stack.py`, `infra/lambda/forecast_api/handler.py`.  
> **Đặc tả sản phẩm:** *Spec dashboard dự báo và độ tin cậy*, Khải, 27/10/2026 (5 trang).  
> **Review bổ sung:** GitHub Issue #23 — *Walk-forward phase 2: chốt 3 điểm còn mở* (phân biệt sai số làm tròn `prob_up`; manifest phát hành `rolling_8w`; provenance của dữ liệu import).  
> **Trạng thái Issue #23:** Ba nội dung được đưa vào RFC để **xin duyệt**; việc có mặt trong RFC **không có nghĩa Issue #23 đã đóng hoặc code đã hỗ trợ**. **Review/approve RFC không đồng nghĩa merge PR RFC**; những điểm được chốt sẽ cập nhật vào `docs/api/contract.md` qua PR riêng.

## Tóm tắt quyết định và phạm vi

Mục đích của RFC là thống nhất **cách đánh giá dự báo đã phát hành thật** rồi trả kết quả cho dashboard, **trước khi** sửa hợp đồng API hoặc viết job. Hai chức năng được đề xuất:

1. Job `rolling_8w` tính độ tin cậy trên các cặp dự báo–giá thực tế đủ điều kiện và lưu kết quả theo Accuracy Schema hiện hành.
2. `GET /accuracy/{asset}` cung cấp chỉ số tổng hợp; **đề xuất** endpoint riêng `GET /forecast-history/{asset}` phục vụ biểu đồ “dự báo cũ so với thực tế”.

**Đã có căn cứ/chốt:** bốn asset `gold/silver/brent/wti`; horizon 1–7 **phiên giao dịch**; đánh giá trên **log return**; chỉ dùng forecast được phát hành thật từ 27/10/2026, không tạo ngược forecast cho tập test; `evaluation_kind=rolling_8w` lưu trên DynamoDB, validation/test lưu Parquet S3 `eval/`; coverage danh nghĩa 80%; `sign_accuracy` luôn đi cùng `up_rate` khi hiển thị. Theo PDF, dưới 20 lần đo **không hiển thị tỷ lệ coverage** (ngưỡng 20 dự kiến chốt trong họp 30/10).

**Chưa chốt:** mốc neo 56 ngày, thời điểm chạy job, bảng/index DynamoDB Accuracy, cơ chế bất biến của forecast đã phát hành, JSON API cuối cùng, endpoint lịch sử, khả năng lưu chi tiết từng cặp, số quan sát tối thiểu, xử lý nhiều `model_version`, **cơ chế tạo publication manifest trước khi predict**, **chứng cứ verified production/import** và **quy tắc phân biệt sai khác `prob_up` do rounding**. Những nội dung này là *lựa chọn thiết kế*, không phải khẳng định hạ tầng hiện tại đã có.

### Truy vết Issue #23 (cần quyết định, chưa phải code)

| Mục Issue #23 | Phạm vi thay đổi trong RFC | Kết quả cần chốt |
|---|---|---|
| **#23.1 — `prob_up` làm tròn 6 chữ số** | Mục **2.6**, 7, 8, 9 | Profile `stored_rounded` so với `internal_full_precision`, quy tắc chấp nhận/cảnh báo/từ chối; **không ghi đè q/prob_up nguồn** bằng kết quả nội suy lại |
| **#23.2 — manifest `rolling_8w`** | Mục **2.5**, 3, 5, 8, 9 | Tập expected `(asset,base_date,h,model/run)` theo kế hoạch phát hành, cách đối chiếu expected–actual và **neo 8 tuần** |
| **#23.3 — provenance import** | Mục **2.7**, 6–9 | Thiếu bằng chứng thời điểm phát hành/revision → giữ **`external_unverified`**, không suy `verified_production` từ `created_at` |

**Quy tắc phối hợp:** Không đánh dấu Issue #23 “resolved” chỉ vì đã viết RFC; sau khi Khải/Tuấn chốt, chuyển quyết định vào `contract.md` và (nếu thuộc Walk-forward) `walk-forward-contract.md` qua PR phù hợp, rồi mới kiểm chứng bằng tests/implementation riêng.

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
2. Có **bằng chứng độc lập dự báo đã phát hành** tại/sau mốc vận hành thực tế **2026-10-27** (ví dụ bản ghi phát hành bất biến kèm timestamp và log run); `created_at` chỉ là metadata cần đối chiếu, **không tự nó xác minh provenance**. `base_date` có thể trước 27/10 vì là ngày giá cuối cùng, **không** dùng riêng `base_date >= 2026-10-27` để nhận diện forecast thật.
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

### 2.5. Issue #23.2 — Manifest dự kiến phát hành cho `rolling_8w` **[ĐỀ XUẤT — CHỜ KHẢI/TUẤN CHỐT]**

**Vì sao cần:** Bảng `Forecasts` chỉ chứa bản ghi đã được ghi thành công. Nếu một kỳ dự báo được lên kế hoạch nhưng predict bỏ qua/thất bại, truy vấn `Forecasts` đơn thuần không thể phân biệt “không có lịch phát hành” với “đã có lịch nhưng thiếu dự báo”. Theo `docs/eval/walk-forward-contract.md` mục 7, **thiếu manifest thì không thể tính `no_forecast_row` hay tuyên bố thống kê đầy đủ**.

**Hai tầng lịch phát hành — đề xuất để tránh khai hồi tố:**

1. **Schedule intent (trước ingest):** ghi ý định chạy job theo thời điểm dự kiến và tập asset/model; bước này **chưa thể luôn biết `base_date`**, vì `base_date` là phiên giá hợp lệ cuối cùng sau ingest. Nếu ingest thất bại, giữ sự kiện kế hoạch/lỗi ingest, **không tự bịa `base_date`**.
2. **Expected forecast grid (sau khi chốt input snapshot nhưng **trước khi predict/ghi Forecasts**):** từ snapshot và calendar đã khóa, xác định các tổ hợp kỳ vọng `(forecast_run_id, model_version, asset, base_date, h)`, ghi `declared_at`, hash và trạng thái *immutable*. Nếu asset không thể xác định `base_date`, ghi `skipped_before_base_date_resolution`/lý do nguồn ở log schedule, **không xem như một `no_forecast_row` có base_date cụ thể**.

**Đơn vị kỳ vọng:** Một mục cho mỗi **`(forecast_run_id, model_version, asset, base_date, h)`** thật sự được tuyên bố sẽ phát hành; `h=1..7` chỉ khi manifest run dự kiến đủ bảy h. Có thể bổ sung `issuance_id`/`fit_id` hoặc khóa revision. Không mặc định **mọi ngày giao dịch đều phát hành** hay tự dựng danh sách expected từ Forecasts/cron sau khi thấy kết quả.

**Ràng buộc thời gian:** `declared_at` của expected grid phải sớm hơn `predict_started_at`/attempt tương ứng (được xác nhận từ evidence độc lập). Không được tạo/đổi expected grid sau khi biết predict thành công hay thất bại để làm đẹp tỷ lệ completeness.

**Manifest tối thiểu đề xuất** (tên trường/kiểu lưu chưa được phê duyệt):

| Trường | Ý nghĩa | Quy tắc |
|---|---|---|
| `manifest_id`, `manifest_version` | Định danh và version bất biến | Thay đổi lịch phải tạo version/revision có dấu vết |
| `forecast_run_id`, `model_version` | Run/model dự kiến | Không tự suy từ bản ghi mới nhất |
| `asset`, `base_date`, `h` | Một tổ hợp dự kiến | Lịch asset/horizon được xác nhận tại lúc lập kế hoạch |
| `scheduled_at`, `declared_at` (UTC) | Lịch dự kiến và thời điểm khai báo expected grid **trước predict** | `declared_at < predict_started_at` theo chứng cứ; gắn với schedule intent trước ingest |
| `target_date` (nếu xác định trước) | Phiên đích theo calendar | Khi so khớp phải đối chiếu lại lịch asset |
| `issuance_id` hoặc `expected_record_ref` | Liên kết với bản phát hành thực tế | Nối với chứng cứ phát hành bất biến, không chỉ dựa vào `created_at` |
| `planned_status`/`source_policy` | Khung lịch dự kiến và lý do thay đổi | Phân biệt không được lên kế hoạch với dự kiến nhưng vắng bản ghi |
| `config_hash`, `manifest_hash`, `snapshot_ref` | Truy vết kế hoạch và input đã khóa | Có thể ghi trong run metadata; `snapshot_ref` phải có trước lúc suy ra `base_date` kỳ vọng |

**Đối chiếu expected–actual:** `left join` các tổ hợp dự kiến với các lần phát hành thực tế theo run/model/asset/base_date/h và (nếu có) issuance ID; kiểm tra trùng, thiếu, thừa, mismatch revision. `published_ok` cần bằng chứng đã phát hành chứ không chỉ có một dòng `Forecasts`. Phân biệt tối thiểu `published_ok`, `invalid_input_window`, `generation_error`/`upstream_failure`, `no_forecast_row` (không thấy bản ghi lẫn chứng cứ attempt), `not_scheduled` (không nằm trong manifest), `publication_unverified` (có dữ liệu nhưng thiếu chứng cứ). Tên các trạng thái ở đây là **mã báo cáo vận hành đề xuất**, **không phải enum đã được thêm vào `Accuracy`**. Một lần attempt lỗi cần log lỗi thật, không thay bằng `no_forecast_row`.

- **Đếm mẫu:** `expected_count`, `published_count`, `failed_count`, `missing_count`, `eligible_count`, `matured_count` theo asset/h/model/run; nêu cả tỷ lệ hoàn thành phát hành và số observation thực sự được đánh giá. **Coverage 80% dùng `n_obs` của forecasts có nhãn hợp lệ và đủ provenance, không dùng `expected_count` hay `published_count` làm mẫu số coverage.** Báo riêng completeness của lịch phát hành (và schedule intents không giải được `base_date`) để người xem không hiểu tỷ lệ coverage là tỷ lệ job hoạt động thành công.
- **Thiếu manifest hoặc manifest không xác thực:** đặt `manifest_status=missing|invalid`; **không xuất báo cáo `rolling_8w` chính thức hoặc diễn giải là đủ lịch phát hành**. Nếu cần, chỉ chạy audit/exploratory riêng có cảnh báo và run ID riêng, không dùng cho dashboard production cho tới khi được Khải/Tuấn duyệt quy tắc fallback.
- **Version/late correction:** không tự xoá các mục dự kiến thất bại hoặc biến `no_forecast_row` thành không dự kiến bằng sửa lịch sau khi biết kết quả. Mọi sửa chữa/retry liên kết tới manifest cũ với audit trail.

**Ví dụ schema phác thảo, CHỈ để review (không phải JSON từ API hiện hành):**

```json
{
  "manifest_id": "example-2026-10-28-run-001",
  "forecast_run_id": "example-prod-run-001",
  "manifest_version": 1,
  "declared_at": "2026-10-28T11:00:00Z",
  "expected": [
    {"asset":"wti","base_date":"2026-10-27","h":1,"model_version":"baseline-q252","scheduled_at":"2026-10-28T12:30:00Z"},
    {"asset":"wti","base_date":"2026-10-27","h":2,"model_version":"baseline-q252","scheduled_at":"2026-10-28T12:30:00Z"}
  ]
}
```

Các ngày, giờ, ID trong JSON chỉ minh họa; không chứng minh lịch production đã tồn tại. `scheduled_at` có thể bằng nhau cho nhiều horizon của một run, **không phải thời điểm biết nhãn**.

**Không đồng nhất hai khái niệm:** `manifest_status=valid` nghĩa là bản kê kỳ vọng có đầy đủ chứng cứ và không bị sửa hồi tố; `publication_completeness=partial` nghĩa là có vị trí kỳ vọng chưa phát hành. Một manifest *valid* vẫn có thể đi kèm `missing_count>0`; trạng thái công bố không được đặt thành `complete` chỉ vì schema manifest hợp lệ.

### 2.6. Issue #23.1 — So khớp `prob_up` nguồn có làm tròn 6 chữ số **[ĐỀ XUẤT]**

**Phân biệt hai profile kiểm tra:**

- `internal_full_precision`: q và `prob_up` nội bộ chưa làm tròn, kiểm tra tính nhất quán thuật toán theo rule nội suy hiện hành và tolerance chặt đã được code/contract chốt.
- `stored_rounded`: dữ liệu DynamoDB dùng Decimal làm tròn **6 chữ số**; giữ nguyên **q và `prob_up` đã lưu**, xác minh shape, thứ tự q, miền p `[0.05,0.95]`, rồi phân loại sai khác giữa `prob_up_stored` và phép nội suy từ **q đã làm tròn**. Không khẳng định có thể dựng chính xác q/prob gốc từ bản làm tròn.

**[CẦN KHẢI/TUẤN CHỐT]** Quy tắc lượng hóa dung sai phải tính đến `ROUND_HALF_EVEN`, bước lượng tử `10^-6` (sai số mỗi giá trị tối đa khoảng `0.5×10^-6` nếu được làm tròn từ số hữu hạn), vị trí 0 so với các điểm phân vị và trường hợp tie/độ rộng interval cực nhỏ; không dùng một threshold tuỳ ý để che sai thuật toán. Đề xuất kiểm tra **miền giá trị khả dĩ** của các phân vị thật trong khoảng lượng tử hóa, tính miền `prob_up` khả dĩ theo phép nội suy và clip đã chốt, rồi so với miền làm tròn của `prob_up` lưu; không chỉ dùng một ngưỡng `abs(p_stored - p_recalc)` cố định. Các kết quả: `rounding_compatible` (có nghiệm phù hợp), `algorithmic_inconsistency` (không có nghiệm), `indeterminate` (điểm biên/tie không chứng minh được bằng kiểm tra hiện có). Ghi chênh lệch và metadata độ chính xác vào log/manifest, **không tự ghi đè `prob_up` nguồn bằng p tái tính**. Chứng cứ thuật toán mâu thuẫn vẫn phải bị từ chối; khác biệt chỉ do rounding không được gọi nhầm là lỗi model.

Không trộn hai profile trong một Accuracy run chính thức; đưa nguồn/precision profile vào `config_hash`. Bản import thiếu provenance được xử lý độc lập theo mục 2.7, **không tự được verified chỉ vì q/p khớp toán học**.

### 2.7. Issue #23.3 — Provenance của bản ghi import và revision **[ĐỀ XUẤT]**

`created_at` có thể là lúc tạo/ghi/import và **không tự xác minh** dữ liệu hoặc model đã sẵn sàng trước khi target xuất hiện. Để coi dữ liệu production đã verified, tối thiểu cần chứng cứ có thể đối chiếu về **thời điểm phát hành thực**, **run/model/artifact đã dùng**, **revision/overwrite** (nếu có) và **input-as-of**. Cơ chế chứng cứ cụ thể do Tuấn/Tiến chốt, ví dụ nhật ký phát hành/issuance record không ghi đè và audit log gắn hash.

| Trạng thái provenance | Điều kiện RFC đề xuất | Được đưa vào rolling dashboard chính thức? |
|---|---|---|
| `verified_production` | Có chứng cứ phát hành/truy vết và điều kiện prequential được kiểm tra | **Có**, nếu các điều kiện khác đạt |
| `external_unverified` | Import thiếu chứng cứ phát hành **hoặc** revision/nguồn lúc phát hành | **Không**; chỉ audit/thăm dò riêng có cảnh báo, không trộn thống kê chính thức |
| `backtest_publication_rule` / `verified_backtest` | Theo Walk-forward historical modes, không coi là phát hành production | **Không** cho rolling live, dù lịch sử có nhãn đầy đủ |

**Không nâng cấp `external_unverified` thành verified bằng cách suy từ `created_at`, `base_date`, `target_date`, thời điểm import hoặc dữ liệu đang tồn tại trong S3.** Với dữ liệu live từ 27/10 nếu hệ thống chưa lưu evidence gốc, **không tự công nhận lịch sử này là verified bằng log được tạo muộn**; cần trình bày giới hạn dữ liệu và chốt chính sách migration rõ ràng trước mốc 05/11. Không tự sửa timestamp gốc; ghi `imported_at` riêng trong manifest nếu cần. Nếu sau này có chứng cứ bổ sung, tạo revision/audit có thể truy vết và chấm lại theo run ID phù hợp; không sửa ngầm số liệu đã công bố.

**Phân biệt hai kiểu thiếu:** không có Forecasts record khi manifest có kỳ vọng → `no_forecast_row`/lỗi phát hành; có Forecasts record nhưng thiếu evidence → `external_unverified`. Không nhập hai loại này làm một.

## 3. Rolling window và quy tắc evaluation

### 3.1. Phạm vi 8 tuần **[ĐỀ XUẤT — CẦN KHẢI/TUẤN CHỐT]**

| Trường | Đề xuất | Vì sao |
|---|---|---|
| `evaluation_kind` | `rolling_8w` | Đúng Accuracy Schema |
| `window_days` | 56 **ngày lịch**, không phải 56 phiên | Phù hợp “8 tuần” |
| `window_anchor` | Ngày job chạy theo UTC | Dễ vận hành và tái lập |
| `window_basis` | `base_date` (ngày gốc t) | Phù hợp đề xuất hiện tại trong Accuracy Schema |
| `evaluation_start/end` | Khoảng base_date thuộc cửa sổ; với giới hạn 56 ngày inclusive, `[run_date-55d, run_date]` | Loại sai lệch biên một ngày |
| `issued_at_min` | Mốc 27/10/2026 theo **múi giờ nhóm chốt**; so timestamp phát hành **có chứng cứ** | Tránh backfill; không lấy `created_at` thay issuance evidence |
| `target_cutoff_date` | Ngày giá target hợp lệ/công bố cuối thực có sẵn, riêng từng asset | Không mặc định bằng ngày job |
| Tần suất | **Đề xuất** 1 lần/tuần sau ingest và sau khi dữ liệu có trạng thái hợp lệ | Đảm bảo đủ dữ liệu và tránh chấm nhãn chưa có |

Ví dụ job ngày 05/11/2026: cửa sổ 56 ngày lý thuyết là **11/09–05/11/2026** (tính cả hai đầu), nhưng kho forecast thật chỉ bắt đầu phát hành từ 27/10 (một số forecast có `base_date` **26/10**), nên thống kê có thể còn nhỏ. Trong response, nếu `evaluation_start/end` mô tả khoảng ngày gốc *thực sự có forecast được xét* thì phải thêm `window_start/window_end` riêng để không nhầm với ranh giới 56 ngày; cách thể hiện cuối cùng cần nhóm chốt. Response phải công khai `evaluation_start`, `evaluation_end`, cutoff riêng asset, `evaluated_at`, `n_obs` và thông điệp “kể từ 27/10”, không tự giới thiệu “đã đo đủ 8 tuần”.

**Vấn đề cần chốt:** anchor theo ngày job hay giá mới nhất, timezone mốc 27/10, cutoff theo publication data, ý nghĩa của cửa sổ khi dự báo được phát hành trễ so với `base_date`; **việc `evaluation_start/end` chỉ diễn tả base_date từ expected grid được xem xét, không đồng nghĩa số observation có nhãn**; **nguồn manifest** và `declared_at` phải cố định độc lập với ngày job. Cùng một anchor/window phải được áp dụng cho **expected grid từ manifest** lẫn Forecasts đã phát hành, tránh một tập ngày được dùng ở mẫu số completeness nhưng tập khác dùng để chấm accuracy. Ngày job có thể khác ngày cutoff cuối do ingest trễ.

### 3.2. Luồng job

1. Chọn snapshot giá/quality đã hoàn tất tại thời điểm job, khóa tham chiếu snapshot/etag/hash; lấy target cutoff riêng asset.
2. Đọc **schedule intent** và **expected grid đã khai sau ingest nhưng trước predict** cho các kỳ thuộc rolling window; xác nhận thời điểm khai báo, hash/version/run và snapshot đã khóa. Thiếu manifest thì **không xuất rolling chính thức**; ghi cảnh báo/exception rõ ràng.
3. Truy vấn các forecast phát hành thật (bản ghi bất biến hoặc chuỗi revision có chứng cứ), đối chiếu **expected–actual** theo `(forecast_run_id, model_version, asset, base_date, h)`/issuance ID; giữ các tổ hợp thiếu làm `no_forecast_row` hoặc status attempt tương ứng, **không bỏ khỏi báo cáo completeness**.
4. Kiểm tra provenance: chỉ các bản phát hành có chứng cứ verified, không `is_sample` hoặc `external_unverified`, mới được đưa vào các metric rolling chính thức. Dùng profile `stored_rounded` khi kiểm tra `prob_up` nguồn DynamoDB, giữ giá trị nguồn.
5. Tách 7 horizons/record; ghép giá đầu-cuối từ **đúng chuỗi target**, xác nhận `target_date` là phiên giao dịch thứ h sau `base_date`.
6. Xây `common_mask` và các bộ đếm loại mẫu theo Accuracy Schema, chỉ chấm horizon có target hoàn tất.
7. Tính metrics **theo từng `(asset, model_version, sample, h)`**; đếm `n_obs` theo đúng từng metric. **Không dùng số lần lên kế hoạch phát hành làm mẫu số Coverage.**
8. Tạo các dòng Accuracy với `evaluation_kind=rolling_8w`, `run_id`, `config_hash`, `evaluation_start/end`, `target_cutoff_date`, `status`, `undefined_reason`.
9. Ghi DynamoDB Accuracy một cách idempotent, không làm hỏng kết quả gần nhất nếu run lỗi giữa chừng. Chỉ đổi *latest completed run* khi ghi đủ toàn bộ kết quả **và có manifest hợp lệ**.
10. Log run metadata: `expected/published/failed/missing/eligible/matured_count` theo asset/h, số mẫu bị loại theo lý do, manifest hash/version, provenance breakdown, rounding profile/diff, snapshot, UTC execution/issuance, các lỗi publication/giá. Bảo vệ không ghi/log thông tin bí mật.

**Không bao gồm:** gọi predict để tạo thêm forecasts lịch sử, tự điều chỉnh K3/K3b/K4, sửa Validation 2019, ghi `validation/test` vào DynamoDB Accuracy.

### 3.3. Metric và `n_obs`

| Metric | Định nghĩa / quy tắc | Ghi chú hiển thị |
|---|---|---|
| `coverage_80` | `mean(q10 <= y <= q90)` trên return thực | Số lần “trong khoảng”/số lần đo; mục tiêu 80% |
| `width_80` | `mean(q90-q10)` | Đánh giá độ rộng, tránh tối ưu coverage bằng cách làm khoảng quá rộng |
| `sign_accuracy` | Tỷ lệ dấu q50 đúng dấu y; bỏ `y=0` hoặc `q50=0` | **Chỉ trình bày cùng `up_rate`** |
| `up_rate` | `mean(y>0)` trên common mask | Có thể có `n_obs` khác `sign_accuracy` |
| Các metric khác | `quantile_hit_*`, `interval_score_80`, `brier_skill`, `pinball_skill`, `mae_ratio_vs_naive` theo Accuracy Schema | Không thay công thức gốc; trả khi thật sự có thể tính |

**Mẫu tổng hợp qua horizons:** nếu cần `overall.coverage_80`, lấy tổng số hit chia tổng số cặp `(base_date,h)` đủ điều kiện, **không** lấy trung bình đều của các tỷ lệ từng h khi `n_obs` khác nhau. `overall` là **phép tổng hợp dành cho API**, không tạo hàng `h=0` ngoài schema hiện hành. Các cặp ở nhiều horizons có thể chung ngày và phụ thuộc; không giải thích `n_obs` như số lần thử độc lập.

**Vấn đề mẫu số của `sign_accuracy`/`up_rate`:** theo Accuracy Schema, `up_rate=mean(y>0)` trên common mask, trong khi `sign_accuracy` loại thêm `y=0` và `q50=0`; **hai metric không nhất thiết có cùng `n_obs`**. Vì vậy, câu “luôn đoán tăng thì đúng b%” là diễn giải trực quan của `up_rate`, **không được tuyên bố là cùng mẫu số với sign_accuracy**. Muốn so công bằng trên đúng sign-mask cần metric phụ riêng/đề xuất thay đổi schema, **không tự đổi công thức up_rate**.

**Ngưỡng hiển thị (PDF đề xuất):** với `n_obs < 20` cho chính phạm vi đang hiển thị, `coverage_80` *vẫn có thể được tính và lưu `status=ok`*, nhưng API trả `display_value=null`, `display_status=insufficient_data` và số cặp đã đo. Ngưỡng 20 là quy tắc UX **không phải** chứng minh độ hiệu chỉnh có ý nghĩa thống kê.

## 4. Accuracy Storage (lưu và truy xuất)

- **Đã chốt trong Accuracy Schema:** `validation` và `test` → Parquet trên S3 `eval/`; **chỉ** `rolling_8w` → DynamoDB phục vụ `/accuracy/{asset}`.
- Mỗi metric trong Accuracy Schema là **một dòng** có khóa logic `(run_id, model_version, asset, sample, evaluation_kind, evaluation_start, evaluation_end, target_cutoff_date, h, metric)`; **không được** nhầm khóa logic thành PK/SK vật lý DynamoDB.
- **[CẦN TUẤN CHỐT]** thiết kế bảng, PK/SK/GSI, kiểu truy vấn latest per-asset/model, chính sách TTL, ghi theo batch, quyền đọc/ghi tối thiểu, quy tắc idempotency và run completion marker.
- **[ĐỀ XUẤT]** để tính `overall.coverage_80` đúng, lấy count hit từ các cặp chi tiết hoặc lưu aggregate riêng với provenance; **không tự tạo `metric=covered_count`/`h=0` trong bảng Accuracy hiện hành**. Nếu phải mở rộng schema chính thức, yêu cầu PR riêng và review trước.
- **[CẦN CHỐT]** kết quả ghép từng forecast với nhãn dùng cho biểu đồ lịch sử được (A) tính khi đọc S3 hay (B) lưu kết quả chi tiết có provenance. B được ưu tiên nếu cần hiệu năng/audit, nhưng phải định nghĩa nơi lưu/TTL/quyền; **không tự ghi dữ liệu forecast history vào bảng Accuracy hiện tại** khi schema chưa cho phép.
- Mọi run lưu hoặc tham chiếu `run_id` **của evaluation** (khác `forecast_run_id` của dự báo), `config_hash`, **publication manifest ID/version/hash**, snapshot ID/etag/hash, **provenance status**, `rounding_profile`, thời điểm job, tính toàn vẹn, số cặp lỗi; API đọc bản run **hoàn thành mới nhất đủ điều kiện verified**, không đọc run đang dở, thiếu manifest hoặc chỉ thăm dò. Manifest/lỗi phát hành là dữ liệu audit của run, **không tự ý thêm cột vào Accuracy Schema**.

## 5. API: `GET /accuracy/{asset}` **[ĐỀ XUẤT]**

### 5.1. Request

`GET /accuracy/wti` — Có `Authorization: <Cognito ID token>` như các endpoint (trừ `/health`) trong contract hiện tại. Asset phải là `gold`, `silver`, `brent` hoặc `wti`. Đề xuất MVP mặc định `sample=all`, `evaluation_kind=rolling_8w` và model đang chạy; query params khác chỉ thêm sau khi chốt.

### 5.2. JSON response đề xuất

> **Ví dụ minh họa định dạng, KHÔNG phải dữ liệu dự báo/chỉ số CPAWS đã chạy thật.** Dãy `by_horizon` rút gọn chỉ hiện 2 phần tử; API thật trả đủ h=1..7 với trạng thái phù hợp. `evaluation_evidence` trong ví dụ là **cấu trúc bổ sung đề xuất**, không có sẵn trong API hay bảng Accuracy hiện tại. `expected_count` đếm **vị trí (asset,base_date,h,run/model) dự kiến**, không phải số ngày; `manifest_status=valid` vẫn có thể đi cùng `publication_completeness=partial`. `evaluation_start/end` trong ví dụ biểu diễn ranh giới base_date được xét trong expected grid, **không phải** ngày phát hành đầu tiên hay số target đã hoàn tất.

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
    "evaluation_start": "2026-10-26",
    "evaluation_end": "2026-11-04",
    "target_cutoff_date": "2026-11-04",
    "first_real_issuance_date": "2026-10-27"
  },
  "evaluation_evidence": {
    "manifest_id": "example-issuance-plan-001",
    "manifest_version": 1,
    "manifest_status": "valid",
    "publication_completeness": "partial",
    "provenance_scope": "verified_production",
    "rounding_profile": "stored_rounded",
    "expected_count": 28,
    "published_count": 24,
    "missing_count": 4,
    "eligible_labeled_count": 18
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
- `sign_accuracy` **không được trình bày độc lập** nếu thiếu `up_rate`; cả hai luôn trả kèm `n_obs`, **không diễn giải `up_rate` là tỷ lệ chính xác trên chính tập sign-mask** khi hai mẫu số khác nhau. Cách so công bằng trên cùng mẫu phải được Khải duyệt riêng.
- `data_status`: **đề xuất** `not_ready` (chưa có run đủ điều kiện, bao gồm manifest thiếu), `collecting` (có nhưng ít dữ liệu), `ready` (đã đủ ngưỡng hiển thị). Chưa có giá thì **không tự sinh tỷ lệ bằng 0**.
- **Issue #23:** `manifest_status=valid` chỉ xác nhận manifest không thiếu/chưa bị sửa hồi tố, **không** xác nhận đã phát hành đủ. API không tuyên bố “đã phát hành đủ lịch” khi `publication_completeness != complete`; không xuất báo cáo **chính thức** nếu `manifest_status` thiếu/invalid hoặc không đủ provenance theo policy đã duyệt. `expected/published/missing` chỉ là thống kê completeness, **khác** `n_obs`/coverage. Contract có thể trả `evaluation_evidence` rút gọn hoặc link tới metadata run (Tuấn chốt trường); không công khai run exploratory `external_unverified` như độ tin cậy production.
- `prob_up` phục vụ đánh giá Brier và forecast/history phải lấy từ bản phát hành nguồn; chênh lệch vì lưu Decimal 6 chữ số được phân loại theo profile đã chốt, **không tự nội suy rồi ghi đè giá trị đã lưu**.
- Khi chưa có run: **đề xuất** HTTP 200 với `data_status=not_ready`, `overall=null`, `by_horizon` **đủ 7 horizon với metrics `null`/trạng thái chờ** (thống nhất với phản hồi khi có run); hình thức cuối cần Tuấn duyệt, không gọi là lỗi hệ thống.
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
      "issued_at": "2026-10-27T13:00:00Z",
      "provenance_status": "verified_production",
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

- Với `actual.status=pending`, `actual.log_return=null` và `inside_80=null`; tuyệt đối không suy ra nhãn khi chưa có giá. **Biểu đồ của PDF đặt giá thực tế cạnh khoảng dự báo**, nên API/adapter cần định nghĩa rõ chế độ `return_pct` hoặc `price` và cùng chuỗi/đơn vị; dữ liệu chỉ là log return trong ví dụ, chưa phải cấu trúc hiển thị giá cuối cùng.
- Biểu đồ mặc định hiển thị **return %** sẽ tránh nhầm chuỗi GLD/SLV với giá giao ngay. Nếu hiển thị khoảng giá, phải chuyển đổi cả dự báo lẫn thực tế **trên cùng chuỗi/cơ sở hiển thị**, giữ nhãn nguồn và đơn vị.
- Endpoint chỉ trả các forecast phát hành thật và đã lưu; không tạo lại forecast lịch sử khi GET. `issued_at`/`provenance_status` trong ví dụ là **metadata đề xuất của kho phát hành bất biến**, không thể tự suy ra từ `created_at` trong Forecasts hiện tại. Chỉ hiển thị dấu “đã xác minh” khi đủ chứng cứ.
- Khi có bản ghi import `external_unverified`, **không ghép vào biểu đồ/rolling live chính thức** như một dự báo đã phát hành thật; có thể có chế độ audit nội bộ riêng, không lẫn với production.
- Nếu dùng DynamoDB Query từ bảng hiện tại, cần xử lý `Limit`, cursor và thứ tự; nhưng bảng Forecasts **không giữ được các phiên bản bị ghi đè** — phụ thuộc quyết định ở mục 2.4.
- **[CẦN TUẤN CHỐT]** lấy actual trực tiếp theo snapshot mỗi request hay đọc bảng/đối tượng chi tiết đã chấm và có provenance; tránh điểm thực tế thay đổi âm thầm khi snapshot revision.

## 7. Edge cases, chống leakage và vận hành

| Tình huống | Quy tắc đề xuất |
|---|---|
| `is_sample=true` | Loại, không tăng `n_obs` |
| `created_at` trước 27/10 hoặc không có chứng cứ phát hành thật | Không chỉ dựa trên `created_at`; nếu không có evidence thì `external_unverified`, không vào rolling chính thức |
| Dự báo ngày 27/10 cho `base_date` 26/10 | Vẫn có thể chấm khi phát hành thật và qua window filter; không loại chỉ vì `base_date<27/10` |
| `target_date` chưa đến/giá chưa published | `pending`; không tăng số lần đo |
| Giá endpoint missing/rejected/không tính log return | Loại với reason; không nội suy |
| Thiếu giá ở giữa endpoints | Không tự loại target nếu endpoints hợp lệ; ghi log |
| Dự báo bị viết đè / chạy lại cùng key | Không chấm bản mới thay bản đã công bố; yêu cầu lịch sử immutable/conditional write, giữ revision/audit |
| Manifest khai kỳ vọng nhưng không thấy Forecasts | Phân biệt `no_forecast_row` với attempt lỗi; lưu `expected_count/missing_count`, không làm mất mẫu số completeness; kiểm tra `declared_at` trước predict |
| Thiếu manifest sản xuất / schedule intent | Không thể xác định đầy đủ expected grid và `no_forecast_row`; run thăm dò riêng, **không công bố rolling chính thức**; nếu ingest thất bại trước khi xác định base_date, log lỗi schedule thay vì chế ra `no_forecast_row` |
| `prob_up` khác kết quả nội suy lại | Kiểm tra `stored_rounded` theo 6 chữ số với miền lượng tử hóa và cạnh 0/tie; phân loại rounding-compatible, lỗi thuật toán, chưa thể kết luận; **không ghi đè số nguồn** |
| Import thiếu evidence thời điểm phát hành/revision | `external_unverified`, không nâng lên `verified_production` từ `created_at` |
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
| D01 | Neo 8 tuần theo gì? | Ngày chạy job UTC; lọc `base_date`; 56 ngày lịch inclusive; `evaluation_start/end` diễn tả base_date trong expected grid | Khải + Tuấn | Bắt buộc trước coding |
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
| **D14 (Issue #23.2)** | Manifest lịch phát hành production lấy từ đâu/khai trước khi nào? | Tách schedule intent trước ingest và expected grid sau ingest nhưng trước predict; snapshot_ref + declared_at + hash; left join với actual; không suy lịch từ Forecasts/cron | **Khải + Tuấn + Tiến** | **Blocker rolling chính thức** |
| **D15 (Issue #23.2)** | Thiếu manifest / khoảng 8 tuần chưa chốt xử lý thế nào? | Không công bố rolling chính thức nếu thiếu/invalid manifest hoặc thiếu provenance; run thăm dò riêng; chốt window_anchor/window_basis áp dụng đồng nhất cho expected và actual | **Khải + Tuấn** | **Blocker** |
| **D16 (Issue #23.1)** | Chấp nhận sai lệch `prob_up` do lưu 6 chữ số bằng quy tắc nào? | Hai profile `internal_full_precision` và `stored_rounded`; kiểm tra miền lượng tử hóa ROUND_HALF_EVEN (không dùng threshold tùy ý); **không sửa q/prob_up gốc** | **Khải + Tuấn** | **Bắt buộc trước import/rolling** |
| **D17 (Issue #23.3)** | Chứng cứ nào đủ cho `verified_production` khi import/ghi revision? | Issuance evidence bất biến + timestamps/input-as-of + revision audit; thiếu → `external_unverified`; cần kế hoạch transition cho dữ liệu live 27/10 nếu thiếu evidence | **Tuấn + Tiến + Khải** | **Blocker thống kê production** |

**Các lựa chọn ở bảng trên chưa được duyệt; không dùng câu chữ “đã chốt” khi copy sang contract chính thức.**

## 9. Acceptance criteria và kế hoạch kiểm thử

Trước khi approve RFC, nhóm cần chốt các quyết định D01–D08/D10/D11 **và D14–D17 (Issue #23)**, cùng phạm vi D09/D12. **RFC được approve không có nghĩa Issue #23 đã được đóng về mặt implementation.** Khi triển khai, ít nhất phải có:

### 9.1. Contract/Schema

- [ ] Có response JSON và lỗi API cuối cùng được Khải/Tuấn/Tiến chấp nhận.
- [ ] `evaluation_kind=rolling_8w`, `target_cutoff_date`, `n_obs`, `status` thống nhất với `accuracy-schema.md`; không tự thay đổi khóa logic.
- [ ] Không tạo metric mới hoặc đổi công thức ngầm trong tầng API; `overall` là tổng hợp hợp lệ của các horizon.
- [ ] Forecast history có chính sách bất biến, quyền truy cập, lọc h và phân trang.
- [ ] Issue #23.2: schedule intent **trước ingest**, expected grid **sau ingest nhưng trước predict**, `declared_at`/snapshot hash, cách đối chiếu `no_forecast_row` và 8-week anchor được Khải/Tuấn/Tiến chốt.
- [ ] Issue #23.1: quy tắc kiểm tra `prob_up` Decimal 6 chữ số (miền rounding vs sai thuật toán, trường hợp không đủ xác định) được duyệt; giá trị nguồn bất biến.
- [ ] Issue #23.3: điều kiện chứng cứ `verified_production`, import `external_unverified` và revision được duyệt; không dùng `created_at` đơn lẻ làm provenance.

### 9.2. Functional tests

- [ ] Cặp forecast thật có giá target mới được chấm; forecast mẫu, future label, backfill bị loại.
- [ ] `base_date` và `target_date` qua đúng calendar theo h; không nhầm ngày lịch với phiên.
- [ ] Missing endpoint/rejected khác missing ngày giữa endpoints; giữ thống kê loại mẫu.
- [ ] `coverage_80` đếm đúng số hit và mẫu; `overall` weighted/pooled đúng.
- [ ] Với n=0, 19, 20: kiểm tra `undefined`, `insufficient_data`, `ready`; **không sửa `status` nội bộ chỉ do ngưỡng UX**.
- [ ] `sign_accuracy` và `up_rate` luôn đi cặp, n_obs có thể khác; q50=0/y=0 xử lý như schema.
- [ ] Một forecast chạy lại cùng `(asset, base_date)` không thể âm thầm đổi dữ liệu dùng chấm.
- [ ] Expected grid gồm kỳ **có kế hoạch nhưng không phát hành**: left join sinh `no_forecast_row`, khác attempt lỗi; đủ counters expected/published/failed/missing; ingest fail **trước khi xác định base_date** được ghi ở schedule layer, không bịa forecast row; kiểm tra không có trùng run/model/asset/base_date/h.
- [ ] Thiếu manifest, manifest sửa hồi tố hoặc manifest không khớp run → run chính thức bị chặn; chỉ audit riêng có cảnh báo.
- [ ] `stored_rounded`: p/q nguồn 6 chữ số được giữ nguyên; dùng envelope của phép làm tròn (`ROUND_HALF_EVEN`), test gần 0/tie/clip; chênh lệch nội suy phù hợp chỉ cảnh báo; trường hợp mâu thuẫn thuật toán có chứng cứ bị từ chối; trường hợp không xác định ghi rõ, không tự ép kết luận.
- [ ] Import không có issuance/revision evidence vẫn `external_unverified` kể cả `created_at` có vẻ hợp lệ; không trộn vào `verified_production`; kiểm thử dữ liệu live 27/10 không có chứng cứ nguyên thủy và chính sách migration.
- [ ] Thay đổi `model_version` không làm trộn số liệu, trừ khi contract có công bố rõ policy.
- [ ] Job retry và rerun có `run_id/config_hash`, ghi hoàn chỉnh và có khả năng tái lập từ snapshot.
- [ ] API không trả dữ liệu giả/historical test 2020–2026, không lộ AWS error/credentials.
- [ ] 4 assets, 7 horizons, Cognito/invalid asset, chưa có run, lỗi đọc storage, stale quality, roll dầu đều có tests.

### 9.3. Tiêu chí nghiệm thu MVP

- `GET /accuracy/{asset}` đọc kết quả rolling đã ghi thành công cho từng asset và trả `n_obs`, cutoff, trạng thái đúng; chỉ công bố run có manifest/provenance đủ điều kiện theo policy đã được duyệt.
- Dashboard có thể viết đúng câu “Kể từ 27/10, giá thực tế nằm trong khoảng 80% ở X/Y lần (mục tiêu 80%)” hoặc “Chưa đủ dữ liệu để đánh giá (mới có Y lần)” khi dưới ngưỡng.
- Biểu đồ lịch sử (giai đoạn tiếp theo) truy được từng forecast trước nhãn, q10/q90, actual/`pending` và tình trạng trong/ngoài khoảng.
- Không sửa đổi Validation 2019 và không đưa kết quả test lịch sử vào rolling live.

## 10. Phân công, mốc thời gian và cách cập nhật contract

| Mốc dự kiến | Đầu ra | Chủ trì | Review |
|---|---|---|---|
| **28–29/10/2026** | RFC này, ghi rõ các lựa chọn còn mở và JSON phác thảo | Long | Khải/Tuấn/Tiến |
| **30/10/2026** | Họp chốt rolling policy, display threshold, endpoint history **và 3 điểm Issue #23** | Khải + nhóm | — |
| **Sau RFC approved** | PR cập nhật **`docs/api/contract.md`** (và schema/ADR nếu quyết định làm thay đổi nguồn chuẩn), chỉ gồm nội dung đã chốt | Long, phối hợp Tuấn | Khải/Tuấn/Tiến |
| **05/11/2026** | Mốc **đề xuất**: `rolling_8w` job + `GET /accuracy/{asset}` | Long | Tuấn (API/IAM), Tiến (tích hợp) |
| **15/11/2026** | Mốc đề xuất: khối độ tin cậy và biểu đồ forecast cũ–actual | Long + Tiến | Tuấn |
| **22/11/2026** | Đóng băng tính năng | Cả nhóm | Khải |

### Quy trình thay đổi

**RFC (file hiện tại) → review/chốt nội dung → PR contract chính thức → PR implementation và tests → deploy + kiểm tra dữ liệu phát hành thật.** Không sửa `contract.md` trong bước RFC. Không mặc định tài liệu đề xuất này đã được thông qua.

### Những nội dung sẽ chuyển vào `docs/api/contract.md` khi được duyệt

1. Điều kiện `rolling_8w` / timestamp bắt đầu live / cutoff / cách lọc cửa sổ **và điều kiện publication manifest đủ** ở mức API cần biết.
2. `GET /accuracy/{asset}`: auth, query parameters, response JSON, status/errors, ý nghĩa `overall`, `by_horizon`, `n_obs`, quy tắc dưới 20 lần đo, liên kết `[Accuracy Schema](accuracy-schema.md)`.
3. Endpoint history nếu được chọn: tên route, filter, phân trang, định dạng `forecast_return`, `actual`, `inside_80`, `pending`.
4. Bảo đảm forecast phát hành thật và tính nhất quán của `model_version` ở giao diện API; quy tắc không coi imported `external_unverified` là production.
5. Issue #23.1: nguyên tắc **bảo toàn `prob_up` nguồn** (đặc biệt khi tính Brier) và profile rounding khi API/adapter phục vụ forecast đã lưu; phần thuật toán kiểm tra chi tiết nằm trong Walk-forward specification / tests, không nhồi vào JSON API khi không cần.
6. Issue #23.2/3: tách manifest validation khỏi publication completeness, schedule/expected grid, nguồn issuance proof, chính sách từ chối công bố khi thiếu bằng chứng và migration khi thiếu dữ liệu lịch sử. Chỉ sửa `accuracy-schema.md` nếu quyết định thật sự làm thay đổi hợp đồng lưu kết quả.

**Không chuyển các chi tiết nội bộ** như câu lệnh CDK, IAM policy JSON, thuật toán SQL/Query cụ thể vào API contract khi chưa cần thiết; chúng thuộc implementation/design notes.

---

## Phụ lục A — Đối chiếu source code bản `developer` được cung cấp

- `docs/api/contract.md`: `/accuracy/{asset}` nằm trong mục “Thêm sau”, mới mô tả danh sách metric; chưa định nghĩa response JSON chính thức hoặc endpoint history.
- `docs/api/accuracy-schema.md`: có `evaluation_kind=rolling_8w`, khóa logic, status/undefined, common mask; **mốc neo 8 tuần và DynamoDB PK/SK chưa chốt**.
- `docs/eval/walk-forward-contract.md`: mục **7** nêu `rolling_8w` phải dùng **manifest lịch phát hành**, thiếu manifest không được tuyên bố `no_forecast_row` hay đủ coverage; mục **5.5/10** phân biệt provenance `external_unverified` với `verified_production` và cảnh báo sai lệch do **Decimal 6 chữ số** (`prob_up`). RFC này đề xuất cách giải quyết các phần còn đánh dấu cần Tuấn/Khải xác nhận, **không sửa hồi tố contract gốc**.
- `src/eval/metrics.py`: có helper `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`, v.v.; chưa có rolling orchestration.
- `src/forecast/forecast_record.py`: `horizons[].q` là log returns, `target_date` theo calendar; `last_price` vàng/bạc là giá hiển thị.
- `src/forecast/predict.py`: `DynamoDbWriter.put` dùng `put_item(Item=record)`; forecast hiện có thể bị thay thế khi cùng key.
- `infra/stacks/cpaws_serving_stack.py`: bảng `Forecasts` dùng PK=`asset`, SK=`base_date`; chưa có bảng `Accuracy` trong stack này.
- `infra/lambda/forecast_api/handler.py`: hiện hỗ trợ `/health`, `/forecasts`, `/forecasts/{asset}`; chưa có handler `/accuracy`.

> Source và trạng thái là từ **ZIP `CPAWS-commodity-forecasting-developer (2)(3).zip` được cung cấp**, không phải xác nhận deployment AWS ở thời điểm hiện tại.

### Các điểm cần đặc biệt xác nhận tại review (không phải quyết định đã chốt)

1. **Mốc 05/11 khả thi đến đâu khi historical live 27/10 chưa có immutable evidence?** Chốt phương án ghi chứng cứ phát hành trước khi chạy job rolling production; không tạo chứng cứ hồi tố.
2. **Tính `n_obs` cho overall:** lấy từ các cặp chi tiết được xác thực; số cặp qua horizons khác với số ngày hay số lần publish. `overall` chỉ là projection/API, không tạo h=0 trong Accuracy.
3. **Giao diện so sánh hướng:** `sign_accuracy` và `up_rate` theo schema hiện có không nhất thiết cùng mẫu; nếu cần benchmark “luôn đoán tăng” trên sign-mask, phải xác định metric/hiển thị riêng và duyệt thay đổi contract/schema nếu có.
4. **Các trạng thái manifest:** manifest `valid` không đồng nghĩa tất cả forecast thành công. Trả `publication_completeness` và `expected/published/missing` riêng; không tự gọi completeness của forecast là độ phủ 80%.
5. **Lời hứa của RFC:** PR proposal có thể được **Approve nhưng không Merge**; sau khi chốt, chỉ các quyết định được duyệt mới đi vào `docs/api/contract.md` qua PR chính thức.

## Phụ lục B — Cơ sở phương pháp / tài liệu đọc thêm

1. Dawid, A. P. (1984). *Statistical Theory: The Prequential Approach*. JRSS A. Nguyên tắc đánh giá tuần tự dự báo theo những gì đã phát hành trước khi quan sát kết quả. https://doi.org/10.2307/2981683
2. Gneiting, T., Balabdaoui, F., & Raftery, A. E. (2007). *Probabilistic Forecasts, Calibration and Sharpness*. JRSS B 69(2), 243–268. Đánh giá độ phủ (calibration) song song với độ rộng/sharpness, không tối ưu độ phủ một cách tách biệt. https://doi.org/10.1111/j.1467-9868.2007.00587.x
3. Amazon DynamoDB, *PutItem API*: `PutItem` thay thế item cùng primary key nếu không có điều kiện chặn, nên cần chính sách immutable/idempotent cho forecast đã phát hành. https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutItem.html

> Tài liệu học thuật/AWS dùng để **giải thích cơ sở thiết kế**, không thay thế quyết định ADR-0008, Accuracy Schema hoặc quy trình approve của nhóm.
