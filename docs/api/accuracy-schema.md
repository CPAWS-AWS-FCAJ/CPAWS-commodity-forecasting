# Schema `Accuracy` — CPAWS

- **Trạng thái:** **Đề xuất đã duyệt cho MVP** theo quyết định review của Khải trên PR #10 và Walk-forward PR #12. Các chi tiết hạ tầng/production Phase 2 (đặc biệt DynamoDB PK/SK, IAM và lịch `rolling_8w`) tiếp tục chờ Tuấn; trạng thái tài liệu không đồng nghĩa PR đã merge.
- **Nguồn quyết định:** [ADR-0008](../adr/0008-target-quantiles-evaluation.md), [hợp đồng API `contract.md`](contract.md), phản hồi Khải và Tuấn trên PR #10. ADR-0008 đã được tích hợp vào `developer`.
- **Phạm vi:** Định dạng logic lưu kết quả đánh giá và so sánh mô hình; **không** tự thiết kế DynamoDB PK/SK, quyền IAM hoặc toàn bộ API.

## 1. Mục đích và khóa logic

`Accuracy` lưu **mỗi metric thành một dòng** cho một mô hình, tài sản, chân trời dự báo `h`, loại lần đánh giá và mẫu quan sát. Cùng một schema được dùng cho validation, test lịch sử và kết quả chạy thật trên cửa sổ 8 tuần.

**Khóa logic đề xuất của `Accuracy`:**

```text
(run_id, model_version, asset, sample, evaluation_kind,
 evaluation_start, evaluation_end, target_cutoff_date, h, metric)
```

- `run_id` nhận diện lần chạy; `config_hash` cho phép đối chiếu cấu hình bất biến (model, dữ liệu, mask, seed, bootstrap, thời điểm huấn luyện, v.v.).
- Đây là **khóa duy nhất về mặt logic**, **không phải** thiết kế PK/SK của DynamoDB. PK/SK sẽ do Tuấn thiết kế cho phần phục vụ API.
- Bảy `quantile_hit_rates` lưu thành **bảy dòng metric riêng**, không lưu chung một mảng.

## 2. Các trường của bảng `Accuracy`

| Cột | Kiểu logic | Bắt buộc | Định nghĩa |
|---|---|---|---|
| `run_id` | `string` | Có | Mã của lần chạy đánh giá. |
| `config_hash` | `string` | Có | Hash của cấu hình dùng để tái lập kết quả. |
| `model_version` | `string` | Có | Ví dụ `dlinear-mvp-v1`, `baseline-252`; trong MVP **không dùng `naive-zero` như một mô hình có dòng `Accuracy`**. |
| `asset` | `enum(string)` | Có | `gold`, `silver`, `brent`, `wti`. |
| `sample` | `enum(string)` | Có | `all`; `excl_roll` chỉ áp dụng cho `brent` hoặc `wti`. |
| `evaluation_kind` | `enum(string)` | Có | `validation`, `test`, `rolling_8w`; **thuộc khóa logic**. |
| `evaluation_start` | `date` | Có | Ngày gốc dự báo `t` đầu tiên được xem xét (ISO `YYYY-MM-DD`). |
| `evaluation_end` | `date` | Có | Ngày gốc dự báo `t` cuối cùng được xem xét. |
| `target_cutoff_date` | `date` | Có | Ngày đích muộn nhất được sử dụng làm nhãn đánh giá; **lưu trực tiếp trong mỗi dòng**. |
| `h` | `integer` | Có | Chân trời từ 1 đến 7 **phiên giao dịch** theo lịch từng tài sản. |
| `metric` | `string` | Có | Tên metric theo danh mục ở mục 4. |
| `value` | `number` hoặc `null` | Có | Giá trị hữu hạn hoặc `null` khi không xác định/không áp dụng. |
| `ci_low` | `number` hoặc `null` | Có | Cận dưới khoảng tin cậy block bootstrap nếu có. |
| `ci_high` | `number` hoặc `null` | Có | Cận trên; nếu hai cận có giá trị thì `ci_low <= ci_high`. |
| `n_obs` | `integer >= 0` | Có | Số quan sát thực sự tham gia phép tính; không đưa về 0 chỉ vì mẫu số bằng 0. |
| `status` | `enum(string)` | Có | `ok`, `undefined`, `not_applicable`. |
| `undefined_reason` | `string` hoặc `null` | Có | Lý do không tính được/không áp dụng, `null` nếu `status=ok`. |

**Ràng buộc thời gian (bắt buộc kiểm tra):**

```text
evaluation_start <= t <= evaluation_end
target_date(t, h) <= target_cutoff_date
```

`target_date(t,h)` là phiên giao dịch thứ `h` sau `t` theo lịch tài sản. Không có công tắc tắt kiểm tra chống rò rỉ; **chỉ giá trị cutoff được cấu hình** theo lần đánh giá. Ví dụ validation 2019 có `target_cutoff_date=2019-12-31`, không dùng nhãn kéo sang 2020. Việc dựng train cũng không lấy nhãn bắt đầu cuối 2018 nhưng có ngày đích sang 2019. Các mẫu bị loại do ranh giới phải được thống kê riêng.

`evaluation_kind` **không suy ra từ ngày**, vì `rolling_8w` có thể nằm trong khoảng lịch sử của test. Cột này luôn được lưu, kể cả khi hai lần đánh giá có khoảng ngày giống nhau.

**Quy ước cutoff theo loại đánh giá:**

| `evaluation_kind` | `target_cutoff_date` | Giới hạn `evaluation_start`/`evaluation_end` |
|---|---|---|
| `validation` | `2019-12-31` theo ADR-0008 | Ngày gốc `t` thuộc validation 2019; không lấy target hoàn tất trong test 2020. |
| `test` | Ngày giá hợp lệ cuối cùng của **snapshot dữ liệu đã chốt cho lần đánh giá**, không vượt giới hạn giai đoạn test | `t` trong giai đoạn test và nhãn phải hoàn tất trước cutoff; tuyệt đối không dùng test để chọn tham số. |
| `rolling_8w` | Ngày giá hợp lệ cuối cùng thực sự có sẵn khi job đánh giá chạy (theo từng tài sản) | **Đề xuất** cửa sổ tám tuần xét theo **ngày gốc dự báo `t`**, không theo ngày đích; chỉ chấm dự báo đã có nhãn hoàn tất. |

**[CẦN CHỐT — Khải/Tuấn]** Với `rolling_8w`, xác nhận mốc neo cửa sổ tám tuần (ngày chạy job hay ngày giá mới nhất), phạm vi tám tuần theo ngày lịch và cách tạo báo cáo nếu mỗi tài sản có cutoff khác nhau. Đây là chi tiết API/đánh giá chạy thật, chưa được ADR-0008 chốt tường minh. `target_cutoff_date` không mặc nhiên là ngày chạy job; giá phải thực sự sẵn có.

**Khoảng tin cậy:** `ci_low`/`ci_high = null` vì chưa tính CI **không làm metric chuyển thành `undefined`** nếu `value` hợp lệ. Cấu hình phải lưu phương pháp bootstrap, mức tin cậy, độ dài khối, số lần lặp, seed. Không serialize `NaN`/`inf` vào JSON hoặc database.

## 3. Tập mẫu chung, ngoại lệ và `n_obs`

**Đã được Khải xác nhận trong review PR #8 (đối chiếu nội dung ADR-0008 khi merge):** đối với mỗi `(asset, h, sample)`, chỉ đánh giá một thời điểm `t` khi:

1. Ngày gốc và ngày đích nằm đúng phạm vi giai đoạn, không vượt `target_cutoff_date`.
2. Log return mục tiêu `r_h(t)` hợp lệ.
3. Có đầu ra dự báo đủ 7 phân vị đã qua `normalize_quantiles()` và hợp lệ theo ADR; `prob_up` được tính từ bộ phân vị đó khi cần.
4. Baseline phân phối/tần suất 252 phiên hợp lệ (đủ số return đã hoàn tất theo ADR).
5. Với `sample=excl_roll`: bỏ thêm các cửa sổ dầu chứa ngày đáo hạn hoặc cờ `roll`.

Tập này là **`common_mask`** và dùng cho mọi metric đánh giá thông thường, **kể cả metric không trực tiếp dùng baseline**. Số điểm qua mask là `n_common` (ghi vào log/báo cáo chạy). `n_obs` trong từng dòng metric bằng `n_common`, **trừ** `sign_accuracy` loại thêm các điểm `y=0` hoặc `q50=0`.

**Phạm vi mô hình trong bảng:** Các dòng `Accuracy` của MVP chỉ dành cho mô hình/phân phối dự báo có **7 phân vị** phù hợp `common_mask` (ví dụ DLinear và `baseline-252`). `naive-zero` chỉ là **mốc dự báo điểm bằng 0** khi tính `mae_ratio_vs_naive` của các mô hình khác, **không** là `model_version` độc lập trong bảng. Vì vậy, không tạo dòng `sign_accuracy` hay `mae_ratio_vs_naive` cho riêng naive. Các dòng `not_applicable` vẫn phải lưu với các metric/mẫu thuộc những mô hình đã tham gia bảng, ví dụ `crossing_rate` trên `excl_roll`.

**Ngoại lệ đã được Khải xác nhận — `crossing_rate`:**

- Chỉ áp dụng cho `sample=all`. Với `sample=excl_roll`, **vẫn ghi một dòng `status=not_applicable`, `value=null`, `n_obs=0`**, `undefined_reason=unsupported_sample`.
- Đo trên các bộ **7 phân vị thô hữu hạn** được mô hình xuất ra, có ngày gốc `t` trong `[evaluation_start, evaluation_end]`, **trước** `normalize_quantiles()`; không cần nhãn mục tiêu hoặc baseline 252 phiên.
- `n_obs` là số bộ phân vị thô được kiểm tra. Phải giữ cờ crossing từ đầu ra mô hình; không suy lại từ `Forecasts` đã chuẩn hóa. Mô hình không cung cấp phân vị thô thì ghi `not_applicable` với lý do phù hợp.

**Ghi log số mẫu bị loại**, chưa thêm cột vào `Accuracy` cho phần này. Theo `(run_id, asset, h, sample, evaluation_kind)`, ghi `n_common` và các bộ đếm:

- `excluded_target_boundary` — ngày gốc/ngày đích vượt phạm vi;
- `excluded_missing_price` — target không hợp lệ vì giá;
- `excluded_invalid_input_window` — input dự báo không hợp lệ;
- `excluded_insufficient_baseline` — không đạt điều kiện baseline 252 phiên;
- `excluded_roll` — chỉ với `excl_roll`.

Khi tính tổng, quy định thứ tự loại hoặc ghi nhận mẫu có nhiều lý do để tránh đếm trùng. `excluded_insufficient_baseline` là **lý do loại mẫu trong log**, **không** phải một hàng trạng thái `undefined` của `Accuracy`.

## 4. Danh mục metric

| `metric` | Diễn giải | Đơn vị |
|---|---|---|
| `pinball_skill` | `1 - PL(model)/PL(baseline_252)`, trung bình đều trên 7 phân vị; **chỉ số chính** | Vô thứ nguyên |
| `pinball_loss` | Trung bình pinball của 7 phân vị trên tập chung; metric thành phần khi cần lưu | Log return |
| `quantile_hit_0.05` | `mean(y <= q05)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.10` | `mean(y <= q10)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.25` | `mean(y <= q25)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.50` | `mean(y <= q50)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.75` | `mean(y <= q75)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.90` | `mean(y <= q90)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.95` | `mean(y <= q95)` | Tỷ lệ `[0,1]` |
| `coverage_80` | `mean(q10 <= y <= q90)` | Tỷ lệ `[0,1]` |
| `width_80` | `mean(q90 - q10)` | Log return |
| `interval_score_80` | Interval score của khoảng q10–q90 với `alpha=0.2` | Log return |
| `brier_score` | `mean((prob_up - 1[y>0])^2)`; metric thành phần khi cần lưu | Điểm `[0,1]` |
| `brier_skill` | `1 - BS(model)/BS(up_rate_252)` | Vô thứ nguyên |
| `brier_skill_vs_half` | `1 - BS(model)/BS(0.5)` | Vô thứ nguyên |
| `mae_ratio_vs_naive` | `mean(abs(y-q50))/mean(abs(y))`, cùng mẫu | Vô thứ nguyên |
| `sign_accuracy` | Tỷ lệ dấu q50 khớp y; loại thêm y=0 hoặc q50=0 | Tỷ lệ `[0,1]` |
| `up_rate` | `mean(y>0)` trên tập chung | Tỷ lệ `[0,1]` |
| `crossing_rate` | Tỷ lệ đầu ra thô phải sắp xếp phân vị trước chuẩn hóa | Tỷ lệ `[0,1]` |

**Quy ước:**

- Các skill dạng `1 - loss(model)/loss(baseline)` có **giá trị tối đa 1** nếu mẫu số dương, có thể âm không giới hạn; không ép về `[0,1]`.
- `pinball_loss()` trong code có thể là hàm **một mức τ**; khi lưu metric tên `pinball_loss` phải dùng phép **trung bình đủ 7 τ** (ví dụ `mean_pinball_loss()` trong code).
- `quantile_hit_rates()` trong code có thể trả dictionary theo τ; tầng xuất bảng chuyển thành 7 dòng `quantile_hit_0.05` … `quantile_hit_0.95`.
- `naive-zero` **không nằm trong bảng `Accuracy` như một `model_version` ở MVP** vì không có 7 phân vị; nó chỉ làm mẫu số trong `mae_ratio_vs_naive` của DLinear hoặc mô hình phân vị khác. Không sinh dòng `naive-zero/sign_accuracy` hay `naive-zero/mae_ratio_vs_naive`. Nếu về sau muốn đánh giá các mô hình chỉ có q50, phải thiết kế hợp đồng đánh giá điểm riêng hoặc có quyết định mới; không tự giả lập 7 phân vị.
- `baseline-252` có đủ 7 phân vị, dùng làm mốc cho `pinball_skill` và làm **đối tượng so sánh chính với DLinear bằng DM**.
- `mase_returns()` vẫn có thể giữ trong code/EDA, **không thuộc danh mục metric lưu trong `Accuracy`**. ARIMA **ngoài phạm vi MVP**; không đặt ví dụ ARIMA hoặc yêu cầu tạo phân vị ARIMA trong schema này. Nếu bổ sung ARIMA sau demo, cần ADR riêng.
- RMSE, sai số trên mức giá và nhóm chỉ số spike không thuộc bộ metric chính thức theo ADR-0008.

## 5. `status`, `n_obs` và cách biểu diễn giá trị thiếu

| Tình huống | `status` | `value` | `n_obs` | `undefined_reason` |
|---|---|---|---|---|
| Tính thành công | `ok` | Số hữu hạn | Số điểm thực dùng | `null` |
| Mẫu số bằng 0 | `undefined` | `null` | Giữ số điểm đã tham gia trước phép chia | `zero_denominator` |
| Không có điểm sau `common_mask` hoặc bộ lọc hợp lệ của metric | `undefined` | `null` | `0` | `no_evaluable_obs` |
| Metric không áp dụng cho mô hình/mẫu | `not_applicable` | `null` | `0` | `missing_quantiles`, `missing_prob_up` hoặc `unsupported_sample` |

**Luôn ghi dòng `not_applicable`**, không âm thầm bỏ dòng. Nếu mẫu không đủ baseline, điểm đã được loại ở `common_mask` và đếm trong `excluded_insufficient_baseline`; khi `n_common=0`, dùng `undefined_reason=no_evaluable_obs`, **không** tạo một trường hợp `insufficient_baseline` riêng trong bảng trạng thái.

Đặt `ci_low/ci_high=null` nếu CI chưa được tính hoặc không thể tính; giá trị metric có thể vẫn `ok`. Nếu nhiều chỉ số được tính trên cùng tập, không được tự ý đổi mask riêng để cải thiện kết quả. Mọi biến thể của quy tắc lọc phải được ghi trong config/phiên bản ADR và test.

## 6. Ví dụ dữ liệu (minh họa, không phải kết quả chạy thật)

```json
[
  {
    "run_id": "validation-2019-r01",
    "config_hash": "sha256:example",
    "model_version": "dlinear-mvp-v1",
    "asset": "gold",
    "sample": "all",
    "evaluation_kind": "validation",
    "evaluation_start": "2019-01-02",
    "evaluation_end": "2019-12-31",
    "target_cutoff_date": "2019-12-31",
    "h": 1,
    "metric": "coverage_80",
    "value": 0.74,
    "ci_low": null,
    "ci_high": null,
    "n_obs": 240,
    "status": "ok",
    "undefined_reason": null
  },
  {
    "run_id": "validation-2019-r01",
    "config_hash": "sha256:example",
    "model_version": "dlinear-mvp-v1",
    "asset": "brent",
    "sample": "excl_roll",
    "evaluation_kind": "validation",
    "evaluation_start": "2019-01-02",
    "evaluation_end": "2019-12-31",
    "target_cutoff_date": "2019-12-31",
    "h": 7,
    "metric": "crossing_rate",
    "value": null,
    "ci_low": null,
    "ci_high": null,
    "n_obs": 0,
    "status": "not_applicable",
    "undefined_reason": "unsupported_sample"
  }
]
```

Không dùng số minh họa `n_obs=240` để suy ra lượng dữ liệu thật; `h=1` và `h=7` có thể có số điểm khác nhau vì biên thời gian, missing, input, baseline hoặc roll.

## 7. Bảng riêng `model_comparison` (Diebold–Mariano)

DM là phép **kiểm định hai phía** so sánh hai mô hình bằng **chuỗi pinball loss ghép cặp cùng thời điểm**, không phải một metric của một mô hình riêng lẻ.

| Cột | Kiểu logic | Ý nghĩa |
|---|---|---|
| `run_id` | `string` | Lần chạy so sánh |
| `config_hash` | `string` | Hash cấu hình, gồm quy tắc so sánh và họ kiểm định |
| `asset` | `enum(string)` | `gold`, `silver`, `brent`, `wti` |
| `sample` | `enum(string)` | `all` hoặc `excl_roll` cho dầu |
| `evaluation_kind` | `enum(string)` | `validation`, `test`, `rolling_8w` |
| `evaluation_start`, `evaluation_end` | `date` | Khoảng ngày gốc t |
| `target_cutoff_date` | `date` | Ngày đích cuối được phép chấm |
| `h` | `integer` | 1..7 |
| `model_a`, `model_b` | `string` | Hai phiên bản đem so sánh |
| `loss` | `string` | `pinball` (trung bình 7 phân vị) |
| `dm_stat` | `number` hoặc `null` | Thống kê DM sau hiệu chỉnh HLN |
| `p_value` | `number` hoặc `null` | p-value kiểm định **hai phía** theo phân phối t với `n_obs-1` bậc tự do (`n_obs` là số cặp loss quan sát thực) |
| `p_value_holm` | `number` hoặc `null` | p-value điều chỉnh Holm theo họ kiểm định định trước |
| `hac_lag` | `integer` | Độ trễ HAC sử dụng `h-1` theo chính sách đã chốt |
| `n_obs` | `integer >= 0` | Số cặp loss hợp lệ đã so sánh |
| `status` | `enum(string)` | `ok`, `undefined`, `not_applicable` |
| `undefined_reason` | `string` hoặc `null` | Ví dụ `insufficient_pairs`, `nonpositive_hac_variance`, `missing_paired_loss` |

**Khóa logic đề xuất của `model_comparison`:**

```text
(run_id, model_a, model_b, asset, sample, evaluation_kind,
 evaluation_start, evaluation_end, target_cutoff_date, h, loss)
```

- Cặp so sánh chính: **`model_a=dlinear-mvp-v1`, `model_b=baseline-252`**, vì cả hai có đủ 7 phân vị. `naive-zero` không có 7 phân vị nên không được đưa vào danh sách cặp DM pinball của MVP.
- Quy ước dấu: `d_t = PL_A(t) - PL_B(t)`. `dm_stat < 0` nghĩa là A có pinball loss thấp hơn B; **chưa đủ để kết luận có ý nghĩa thống kê** nếu p-value chưa đạt ngưỡng.
- DM dùng phương sai HAC với `lag=h-1`, **trọng số đều (uniform)** trên các độ trễ được đưa vào (không dùng Bartlett hay đổi sang Parzen kernel), hiệu chỉnh HLN và phân phối t theo ADR-0008.
- **Họ Holm đã chốt** cho từng `(model_a, model_b, sample)`: `sample=all` có **28 vị trí** (4 tài sản × 7 h); `sample=excl_roll` có **14 vị trí** (chỉ Brent/WTI × 7 h), đúng implementation Walk-forward hiện tại. Hai mẫu là **hai họ riêng**, không gộp thành một họ 42 vị trí. Các vị trí `undefined`/`NaN` vẫn thuộc họ đã định trước; không thu nhỏ họ theo số p-value hữu hạn.
- **Yêu cầu đồng bộ code:** `holm_adjust()` phải có cách nhận **họ kiểm định định trước** một cách tường minh (ví dụ `family_size` hoặc danh sách đầy đủ vị trí kiểm định) và có test cho trường hợp p-value thiếu. Việc truyền vào riêng các p-value hữu hạn không được làm thay đổi quy tắc đã chốt. Phải lưu lựa chọn họ kiểm định trong cấu hình gắn với `config_hash`.
- Nếu không đủ loss ghép cặp, phương sai HAC không dương hoặc test không tính được, trả `status=undefined`, giá trị thống kê và p-value là `null`, giữ `n_obs` bằng số cặp đã có. Không tự tính p-value từ dữ liệu không hợp lệ.

**Chính sách DM khi lịch có khoảng trống — đã chốt (Khải, thay `DM_GAP_POLICY: pending`):**

- **Phương pháp chính:** HAC *amplitude-modulated* (Parzen) trên **lưới phiên giao dịch gốc của từng tài sản**; không nén lịch và không xem các phiên thiếu là hai quan sát liền kề. “Parzen” ở đây chỉ cách xử lý dữ liệu thiếu theo amplitude modulation, **không** có nghĩa thay trọng số HAC uniform hiện tại bằng một *Parzen kernel*.
- **Biểu diễn ngày thiếu:** ở phiên không có cặp pinball loss hợp lệ, đặt `d_t=0` để biểu diễn trên lưới cố định **đồng thời** đặt `observed_mask_t=False`. Giá trị 0 này chỉ là placeholder, không được tính là chênh lệch loss quan sát được. Phiên có cặp loss hợp lệ đặt `observed_mask_t=True`, `d_t=PL_A(t)-PL_B(t)`.
- **Tự hiệp phương sai `γ_k`:** chỉ cộng những cặp `(t, t-k)` có **cả hai** `observed_mask=True` và cách nhau đúng `k` **phiên trên lịch gốc**; không ghép qua khoảng trống, không dùng cặp có placeholder. Tính trung bình chênh lệch loss và hiệu chỉnh tâm theo **các quan sát thực**, không lấy các số 0 giả làm quan sát.
- **Độ trễ và trọng số:** giữ `hac_lag=h-1` và **trọng số đều (uniform)** cho các lag được đưa vào như chính sách DM/HAC hiện tại; giữ hiệu chỉnh **Harvey–Leybourne–Newbold (HLN)** và kiểm định hai phía. Dùng `n=n_obs` = **số cặp loss thực sự quan sát được** trong HLN và bậc tự do `n-1` của phân phối t; không lấy tổng số phiên trong lưới lịch làm `n`.
- **Kiểm tra độ nhạy (sensitivity):** tính thêm kết quả DM trên **chuỗi chỉ gồm các quan sát thực sau khi bỏ ngày thiếu** (chuỗi nén) và báo cáo tách biệt với kết quả chính; ghi số khoảng trống, `n_obs`, DM statistic, p-value và chênh lệch kết luận. Chuỗi nén chỉ để đối chiếu, không thay thế kết quả chính.
- **Trường hợp không tính được:** vẫn dùng `status=undefined` và các mã `undefined_reason` **đang có trong Accuracy Schema** khi thiếu cặp, không đủ quan sát hoặc phương sai HAC không dương; không tự thêm enum reason mới khi chưa được nhóm duyệt. Ghi nguyên nhân dữ liệu và số phiên thiếu trong log/manifest.
- **Tình trạng triển khai:** đây là **quyết định về contract**, chưa phải xác nhận code đã triển khai. `src/eval/walk_forward.py` trong snapshot `developer` đang chặn các nhóm có internal session gaps (`DM_GAP_POLICY=...pending_Khai_review`); việc sửa Metrics/Walk-forward, kiểm thử, tính lại DM và tạo **run ID mới** thuộc PR implementation riêng. Không diễn giải lại hoặc ghi đè kết quả Validation 2019 đã tạo từ code cũ.

## 8. Lưu trữ và tích hợp API

- **Validation / test:** lưu kết quả dưới dạng **Parquet trên S3, prefix `eval/`** (**đã chốt cho MVP**). Cần **Tuấn cấp quyền phù hợp cho `cpaws-ml`** trước khi ghi dữ liệu thật; cấu trúc đường dẫn chi tiết và quy tắc đặt tên file triển khai theo quyền/hạ tầng được cấp.
- **`rolling_8w` phục vụ `GET /accuracy/{asset}`:** **chỉ** loại đánh giá này được lưu trên **DynamoDB** (Phase 2/tuần 3). **Tuấn thiết kế PK/SK** và quyền tương ứng; không tự lấy khóa logic ở mục 1 làm PK/SK khi chưa được duyệt. `validation`/`test` không ghi vào bảng DynamoDB này.
- **Đầu mục nhờ Tuấn review (Phase 2/hạ tầng):** (a) cấp quyền ghi/đọc S3 `eval/` cho `cpaws-ml` (prefix đã chốt); (b) quy tắc đặt tên/partition Parquet theo `run_id`, `evaluation_kind`, `asset`, `sample`, `h`, kiểm soát ghi đè; (c) thiết kế DynamoDB PK/SK và chỉ mục phục vụ `/accuracy/{asset}`; (d) TTL, lịch cập nhật theo tuần và IAM. **Nơi lưu và prefix S3 đã chốt; thiết kế bảng DynamoDB chưa chốt và thuộc Tuấn/Phase 2.**
- API đọc dữ liệu theo asset/h/model/time window rồi **pivot** dạng dài sang dạng chỉ số cần trả trong `contract.md`; bảy dòng `quantile_hit_...` được ghép lại thành đối tượng `quantile_hit_rates`.
- **Bổ sung trong `docs/api/contract.md`** đường dẫn tham khảo tương đối `[Schema kết quả Accuracy](accuracy-schema.md)` tại phần `GET /accuracy/{asset}`. `contract.md` vẫn là hợp đồng API; `accuracy-schema.md` là nguồn định nghĩa logic lưu kết quả — không sao chép hai phiên bản schema ở hai nơi.
- `config_hash` phải liên kết được cấu hình của từng `run_id`, bao gồm ranh giới cutoff, mẫu, phương pháp CI, seed và họ Holm.

## 9. Phân tách code và lưu ý chuyển file

Theo cấu trúc mục tiêu mà nhóm yêu cầu:

```text
src/
  forecast/
    returns.py                 # Target và chuẩn hóa phân vị (Khải)
    baselines.py               # Baseline 252 phiên (Khải, khi đã tích hợp)
  eval/                        # Tạo mới
    __init__.py
    metrics.py                 # Công thức thuần, test các metric, DM, bootstrap
    ...                        # Walk-forward, tạo dòng Accuracy (triển khai sau)
```

**Tích hợp metrics:** Sử dụng `src/eval/metrics.py` theo implementation đã được review ở PR #11. Không tạo bản sao công thức đánh giá ở module khác. Các import và khả năng tương thích với code cũ phải được xác nhận bằng tests và CI.

Các hàm của `src/eval/metrics.py` chỉ tính toán (mảng → số/NaN), không trực tiếp trả schema. Lớp tổng hợp thuộc `src/eval/` áp dụng `common_mask`, tính `n_obs`, tạo `status`, CI và xuất một dòng `Accuracy`. `crossing_rate` lấy dữ liệu đầu ra thô và là ngoại lệ được xử lý riêng.

`pinball_loss()` của một τ trong code **khác** metric `pinball_loss` trung bình 7 τ ở bảng; phải ánh xạ đúng. Không viết lại baseline 252 phiên ở lớp metric; dùng `baselines.py` của Khải khi đã tích hợp.

## 10. Những câu hỏi còn mở / việc còn lại

1. **[Khải — phạm vi baseline]** Sau khi ARIMA bị loại khỏi MVP, đầu việc "Baseline naive và ARIMA" trong `tasks.md` được thay bằng đầu ra nào, ai cập nhật task và cách nghiệm thu?
2. **[Khải + Tuấn — `rolling_8w`]** "8 tuần gần nhất" xác định theo ngày gốc `t` có đúng không? Neo khoảng này vào ngày chạy job hay ngày dữ liệu cuối cùng đã có? Chốt cách dùng cutoff riêng từng tài sản để API không chấm các dự báo chưa đủ `h` phiên.
3. **[Tuấn — hạ tầng/Phase 2]** Prefix S3 `eval/` đã chốt; ai cấp quyền IAM cho `cpaws-ml` và triển khai quyền ghi/đọc? DynamoDB dùng PK/SK/index nào để query `asset`/`h`/`model_version`/khoảng thời gian? Tần suất job, overwrite và TTL ra sao?

Những điểm đã được Khải xác nhận về `common_mask`, `crossing_rate`, lưu `not_applicable`, `evaluation_kind`, `target_cutoff_date`, DM hai phía và phạm vi MVP **không hỏi lại**.

## 11. Checklist review và triển khai

- [x] Chốt `common_mask`, ngoại lệ `crossing_rate` và cách xử lý `excl_roll` theo phản hồi Khải/ADR-0008.
- [x] Chốt ghi dòng `not_applicable`, `evaluation_kind` bắt buộc và lưu `target_cutoff_date` thành cột hai bảng.
- [x] Tách lưu trữ Parquet/S3 cho validation-test và DynamoDB cho `rolling_8w`.
- [x] Chốt DM hai phía, cặp DLinear–baseline 252; Holm `sample=all` = **28**, `sample=excl_roll` = **14** vị trí theo từng họ riêng, kể cả vị trí p-value thiếu.
- [x] Chốt chính sách DM calendar gaps: HAC amplitude-modulated (Parzen), lưới phiên và observed mask, lag `h-1`, trọng số đều, HLN dùng `n_obs` thực; có sensitivity trên chuỗi bỏ ngày thiếu.
- [ ] Triển khai DM calendar-gap policy và tests trong PR code riêng; phát hành kết quả evaluation dưới `run_id` mới, không sửa các Parquet Validation 2019 cũ.
- [x] Loại ARIMA khỏi **MVP theo phản hồi Khải** và không lưu `mase_returns` trong bảng metric.
- [ ] **[CẦN CHỐT — Khải]** Đồng bộ `tasks.md`: đầu việc cũ "Baseline naive và ARIMA" và các so sánh có ARIMA chưa được sửa. Xác nhận nghiệm thu/khối lượng thay thế (ví dụ tích hợp naive làm mốc MAE, so sánh DLinear với baseline-252 đã có, test walk-forward) và cập nhật phân công sau demo.
- [x] Hoàn tất review PR #10; commit `179db6f` đã được Tuấn approve. Chờ merge theo quy trình GitHub.
- [ ] Nhờ **@hngtuan2kar5-prog** review **mục 1–2 (khóa/kiểu dữ liệu ở góc độ lưu trữ) và mục 8 (S3/Parquet, IAM, DynamoDB và truy vấn API)**; xác nhận quyền S3 `cpaws-ml`, thiết kế DynamoDB PK/SK, cập nhật/TTL. **Không mở lại quyết định prefix S3 `eval/` đã chốt.**
- [ ] Thêm link schema vào `contract.md` trên PR phù hợp để hai tài liệu không phân kỳ.
- [ ] Khi triển khai code, chuyển/đặt metric ở `src/eval/metrics.py`, xử lý toàn bộ import và chạy unit test + CI.

**Tài liệu này chốt nội dung đề xuất theo quyết định review; trạng thái approve/merge vẫn do GitHub và nhóm xác nhận.**
