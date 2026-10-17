# Đề xuất schema `Accuracy` — CPAWS

- **Trạng thái:** Dự thảo để Long và nhóm review; chưa phải quyết định đã được chốt trong ADR.
- **Dựa trên:** `docs/adr/0008-target-quantiles-evaluation.md` (mục 2, 4, 5, 6, 7) và `docs/api/contract.md` (endpoint `GET /accuracy/{asset}`).
- **Phạm vi:** Hợp đồng dữ liệu logic và định dạng xuất kết quả đánh giá; **chưa quyết định hệ lưu trữ** (DynamoDB/SQL/Parquet/CSV) hay cách triển khai endpoint.

## 1. Mục tiêu và mức hạt dữ liệu

Mỗi dòng `Accuracy` chứa **một metric của một phiên bản mô hình**, tại một tài sản, chân trời, tập đánh giá và mẫu quan sát xác định.

Khóa logic đề xuất để phân biệt các dòng:

`(run_id, model_version, asset, sample, evaluation_start, evaluation_end, h, metric)`

`run_id` định danh lần chạy đánh giá; `config_hash` lưu dấu cấu hình để tái lập. Khi viết vào hệ lưu trữ, có thể tạo khóa vật lý khác miễn vẫn bảo đảm tính duy nhất logic. Kết quả trên 2019, test lịch sử và cửa sổ 8 tuần gần nhất của API đều có thể dùng chung schema.

Không lưu `quantile_hit_rates` như một mảng trong một dòng: mỗi mức τ là **một dòng riêng**.

## 2. Cấu trúc bảng `Accuracy`

| Cột | Kiểu logic | Bắt buộc | Quy tắc / ý nghĩa |
|---|---|---|---|
| `run_id` | `string` | Có | ID duy nhất của lần chạy đánh giá. |
| `config_hash` | `string` | Có | Hash cấu hình xử lý, mô hình, tham số đánh giá; dùng để tái lập. |
| `model_version` | `string` | Có | Ví dụ `dlinear-2026-10-20`, `arima-p100-v1`, `naive-zero`. |
| `asset` | `enum(string)` | Có | `gold`, `silver`, `brent`, `wti` theo `contract.md`. |
| `sample` | `enum(string)` | Có | `all`; `excl_roll` chỉ với `brent`/`wti` (ADR mục 6). |
| `evaluation_start` | `date` | Có | Ngày bắt đầu khoảng đánh giá, ISO `YYYY-MM-DD`. |
| `evaluation_end` | `date` | Có | Ngày kết thúc khoảng đánh giá, ISO `YYYY-MM-DD` (>= ngày bắt đầu). |
| `h` | `integer` | Có | Chân trời **phiên giao dịch**, `1..7`; theo lịch riêng từng tài sản. |
| `metric` | `string` thuộc tập tên quy định | Có | Đúng một metric trên mỗi dòng, xem mục 3. |
| `value` | `number|null` | Có | Giá trị metric; `null` khi không xác định hoặc không áp dụng; **không ghi `NaN` vào JSON/database**. |
| `ci_low` | `number|null` | Có | Cận dưới CI block bootstrap; `null` nếu chưa tính/không tính được. |
| `ci_high` | `number|null` | Có | Cận trên CI block bootstrap; `null` nếu chưa tính/không tính được; `ci_low <= ci_high` nếu có. |
| `n_obs` | `integer >= 0` | Có | Số điểm thực tế dùng để hình thành phép tính metric, sau khi áp dụng mask tương ứng. Không đặt về 0 chỉ vì mẫu số bằng 0. |
| `status` | `enum(string)` | Có | `ok`, `undefined`, `not_applicable`; xem mục 4. |
| `undefined_reason` | `string|null` | Có | Lý do không tính được; `null` nếu `status=ok`. |

**Không đưa `split` thành cột bắt buộc ở phiên bản đầu:** có thể xác định validation/test từ cấu hình chạy và ngày đánh giá. Nếu nhóm cần phân biệt các kiểu đánh giá khác nhau nhưng trùng ngày, có thể thêm `evaluation_kind` (`validation`, `test`, `rolling_8w`) trước khi tạo bảng thật.

**Về CI:** `ci_low/ci_high = null` khi chưa triển khai bootstrap **không** có nghĩa metric thất bại; `status=ok` nếu `value` vẫn tính được. Phương pháp, độ tin cậy, số lần lặp, độ dài block và seed phải được ghi trong cấu hình gắn với `config_hash`. Nếu API cần phân biệt "chưa tính CI" và "không thể tính CI" trực tiếp, cân nhắc thêm `ci_status` ở vòng sau.

## 3. Danh mục giá trị `metric`

| `metric` | Nguồn / diễn giải | Đơn vị |
|---|---|---|
| `pinball_skill` | `1 − PL(model)/PL(baseline_252)`; **chỉ số chính** | Vô thứ nguyên |
| `pinball_loss` | Trung bình đều pinball trên 7 phân vị và các điểm hợp lệ; metric thành phần (tùy nhu cầu lưu) | Log return |
| `quantile_hit_0.05` | `mean(y <= q05)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.10` | `mean(y <= q10)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.25` | `mean(y <= q25)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.50` | `mean(y <= q50)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.75` | `mean(y <= q75)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.90` | `mean(y <= q90)` | Tỷ lệ `[0,1]` |
| `quantile_hit_0.95` | `mean(y <= q95)` | Tỷ lệ `[0,1]` |
| `coverage_80` | `mean(q10 <= y <= q90)` | Tỷ lệ `[0,1]` |
| `width_80` | `mean(q90 - q10)` | Log return |
| `interval_score_80` | Interval score, α = 0.2 | Log return |
| `brier_score` | `mean((prob_up − 1[y>0])²)`; metric thành phần (tùy nhu cầu lưu) | Điểm `[0,1]` |
| `brier_skill` | `1 − BS(model)/BS(up_rate_252)` | Vô thứ nguyên |
| `brier_skill_vs_half` | `1 − BS(model)/BS(0.5)` | Vô thứ nguyên |
| `mae_ratio_vs_naive` | `MAE(q50)/MAE(return=0)` trên cùng mẫu | Vô thứ nguyên |
| `sign_accuracy` | Tỷ lệ đúng chiều, **loại y=0 và q50=0** | Tỷ lệ `[0,1]` |
| `up_rate` | `mean(y>0)` | Tỷ lệ `[0,1]` |
| `crossing_rate` | Tỷ lệ dự báo (t,h) có phân vị cắt nhau **trước** `normalize_quantiles()` | Tỷ lệ `[0,1]` |
| `mase_returns` | MASE theo thang đo return của train, **chỉ dùng báo cáo phụ/EDA nếu cần**, không thay `mae_ratio_vs_naive` | Vô thứ nguyên |

Quy tắc danh mục:

- Các metric đòi **7 phân vị** chỉ được ghi `ok` khi mô hình thực sự có đủ 7 phân vị hợp lệ.
- `naive-zero` theo ADR chỉ cung cấp dự báo điểm `q50=0`, không có 7 phân vị hoặc `prob_up`. Các metric phụ thuộc những đầu ra đó được **bỏ dòng** hoặc ghi `status=not_applicable`, tuyệt đối không tự tạo phân vị để tính. Riêng `sign_accuracy` của naive không xác định vì mọi q50=0; `n_obs=0`, `status=undefined` với `undefined_reason=no_evaluable_obs`. `mae_ratio_vs_naive` bằng 1 khi mẫu số MAE của naive > 0.
- `crossing_rate` là chẩn đoán từ output **thô** của mô hình. Không thể tính lại nó từ 7 phân vị đã chuẩn hóa. `n_obs` ở metric này đếm dự báo thô được kiểm tra; cần chốt có ràng buộc cùng mask baseline hay không (mục 6).
- Một số metric mang tên `*_skill` có thể âm hoặc lớn hơn 1 về độ lớn âm; **không ép vào `[0,1]`**.

## 4. Quy ước `status`, `n_obs`, giá trị thiếu

| Tình huống | `status` | `value` | `n_obs` | `undefined_reason` |
|---|---|---|---|---|
| Tính thành công | `ok` | Số hữu hạn | Số điểm dùng | `null` |
| Mẫu số metric bằng 0 | `undefined` | `null` | Giữ số điểm đã tham gia phép tính trước bước chia | `zero_denominator` |
| Không còn điểm đánh giá hợp lệ | `undefined` | `null` | `0` | `no_evaluable_obs` |
| Không đủ lịch sử baseline cho metric cần baseline | `undefined` | `null` | `0` nếu không còn điểm nào sau lọc | `insufficient_baseline` |
| Mô hình không có đầu ra cần thiết (ví dụ naive không có 7 phân vị) | `not_applicable` | `null` | `0` | `missing_quantiles` hoặc `missing_prob_up` |

`n_obs` không nhất thiết giống nhau giữa các metric nếu quy tắc loại điểm khác nhau (ví dụ `sign_accuracy`). Không tùy ý loại thêm quan sát sau khi đã tính các metric; lớp tính dòng kết quả phải ghi rõ mask dùng để đếm `n_obs`.

**Điểm chưa chốt trong PR #8:** ADR mục 5 hiện yêu cầu mọi metric dùng chung tập điểm có baseline 252 phiên hợp lệ, trong khi mục 4 giới hạn điều kiện ấy cho những metric dùng baseline. Phải đợi xác nhận rồi mới cố định quy tắc mask trong code. Schema hỗ trợ cả hai cách mà không phải đổi cột.

## 5. Ví dụ 3 dòng theo schema (giá trị minh họa, không phải kết quả chạy thực tế)

```json
[
  {
    "run_id": "validation-2019-r01",
    "config_hash": "sha256:example",
    "model_version": "dlinear-demo",
    "asset": "gold",
    "sample": "all",
    "evaluation_start": "2019-01-02",
    "evaluation_end": "2019-12-31",
    "h": 1,
    "metric": "quantile_hit_0.05",
    "value": 0.06,
    "ci_low": null,
    "ci_high": null,
    "n_obs": 240,
    "status": "ok",
    "undefined_reason": null
  },
  {
    "run_id": "validation-2019-r01",
    "config_hash": "sha256:example",
    "model_version": "dlinear-demo",
    "asset": "gold",
    "sample": "all",
    "evaluation_start": "2019-01-02",
    "evaluation_end": "2019-12-31",
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
    "model_version": "naive-zero",
    "asset": "gold",
    "sample": "all",
    "evaluation_start": "2019-01-02",
    "evaluation_end": "2019-12-31",
    "h": 1,
    "metric": "pinball_skill",
    "value": null,
    "ci_low": null,
    "ci_high": null,
    "n_obs": 0,
    "status": "not_applicable",
    "undefined_reason": "missing_quantiles"
  }
]
```

*Lưu ý*: dòng thứ ba chỉ có nếu nhóm chọn **ghi các metric không áp dụng**; nếu chọn bỏ dòng thì không có dòng này. Ví dụ dùng cùng `run_id` cho một lần chạy có nhiều mô hình; có thể quy định `run_id` cho mỗi mô hình nếu toàn nhóm muốn, miễn nhất quán.

## 6. `model_comparison` — bảng riêng cho Diebold–Mariano

DM so sánh **hai mô hình**, không phải metric của một mô hình, nên không lưu trong `Accuracy`.

| Cột | Kiểu logic | Ý nghĩa |
|---|---|---|
| `run_id` | `string` | Lần đánh giá |
| `asset` | `enum(string)` | `gold`, `silver`, `brent`, `wti` |
| `sample` | `enum(string)` | `all` hoặc `excl_roll` |
| `evaluation_start`, `evaluation_end` | `date` | Khoảng so sánh |
| `h` | `integer` | 1..7 |
| `model_a`, `model_b` | `string` | Phiên bản mô hình đem so sánh |
| `loss` | `string` | `pinball` theo ADR |
| `dm_stat` | `number|null` | Thống kê DM sau hiệu chỉnh HLN |
| `p_value` | `number|null` | p-value theo phân phối t với `T−1` bậc tự do |
| `p_value_holm` | `number|null` | p-value sau điều chỉnh Holm với họ kiểm định đã định trước |
| `hac_lag` | `integer` | Ít nhất `h−1` |
| `n_obs` | `integer >= 0` | Số cặp loss ngoài mẫu hợp lệ |

Quy ước dấu: `d_t = PL_A(t) − PL_B(t)`; `dm_stat < 0` nghĩa là **A có pinball loss trung bình thấp hơn B**, không đồng nghĩa có ý nghĩa thống kê nếu p-value chưa đủ nhỏ.

## 7. Ràng buộc với API và lớp tính toán

- `GET /accuracy/{asset}` theo `contract.md` sử dụng **8 tuần gần nhất**, riêng từng h. Tầng API sẽ lọc đúng `asset`, `model_version` và khoảng đánh giá, rồi **pivot** các dòng thành tên chỉ số như trong contract. `quantile_hit_0.05` ... `quantile_hit_0.95` được gom thành đối tượng `quantile_hit_rates` theo yêu cầu API, không bắt API nhận 7 cột tách rời.
- Không ép mọi hàm trong `src/forecast/metrics.py` trả ra từ điển schema. Hàm metric vẫn thuần (mảng → số thực/`NaN`); lớp `compute_metric_row()` ở `src/eval/` sẽ áp mask, tính `n_obs`, xử lý `status`, gắn CI rồi xuất hàng dài.
- `crossing_rate` phải được ghi từ thông tin trước khi sắp xếp phân vị; lớp đánh giá không thể phục hồi nó từ `Forecasts` đã chuẩn hóa.
- Khi làm tròn / serialize để lưu, giữ đủ độ chính xác để không gây sai lệch CI, `NaN`/`inf` được đổi sang `null` kèm lý do; không diễn giải `null` thành `0`.
- Không dùng dữ liệu từ test để chọn cấu hình, độ dài block bootstrap, ARIMA hay cách nội suy. Ghi các tham số này cùng cấu hình của `run_id`.

## 8. Các quyết định cần nhóm xác nhận trước khi triển khai bảng thật

1. **Mask chung hay riêng theo metric** khi baseline 252 phiên không hợp lệ (đang chờ phản hồi trên PR #8).
2. Có ghi dòng `not_applicable` hay **bỏ dòng** cho metric mô hình không cung cấp được? Khuyến nghị ghi dòng khi có bảng so sánh cố định, để UI phân biệt "không áp dụng" với "quên chạy".
3. **Cơ chế lưu trữ**: chỉ xuất Parquet/CSV trong vòng đầu, hay sẽ cần DynamoDB ngay? Cấu trúc trên độc lập với quyết định này.
4. Có thêm `evaluation_kind` ngay từ đầu để phân biệt `validation`, `test`, `rolling_8w` và cố định CI confidence level (ví dụ 95%) trong cấu hình chạy không?

**Tiêu chí hoàn thành bước schema:** thống nhất danh mục cột, kiểu dữ liệu, danh mục metric, khóa logic, quy tắc `null/status/n_obs`, bảng DM riêng và quan hệ với `/accuracy/{asset}`. Sau đó mới viết các hàm metric kèm test và lớp xuất dòng dữ liệu.
