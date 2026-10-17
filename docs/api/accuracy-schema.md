# Đề xuất schema `Accuracy` — CPAWS

- **Trạng thái:** Bản đề xuất hoàn chỉnh để nhóm review trong PR #10; **chưa phải schema được nhóm phê duyệt**.
- **Dựa trên:** `docs/adr/0008-target-quantiles-evaluation.md` (mục 2, 4, 5, 6, 7) và `docs/api/contract.md` (endpoint `GET /accuracy/{asset}`).
- **Phạm vi:** Hợp đồng dữ liệu logic và định dạng xuất kết quả đánh giá; **chưa quyết định hệ lưu trữ** (DynamoDB/SQL/Parquet/CSV) hay cách triển khai endpoint.

## 1. Mục tiêu và mức hạt dữ liệu

Mỗi dòng `Accuracy` chứa **một metric của một phiên bản mô hình**, tại một tài sản, chân trời, tập đánh giá và mẫu quan sát xác định.

Khóa logic đề xuất để phân biệt các dòng:

`(run_id, model_version, asset, sample, evaluation_start, evaluation_end, target_cutoff_date, h, metric)`

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
| `evaluation_start` | `date` | Có | Ngày bắt đầu khoảng đánh giá **theo ngày gốc dự báo `t`**, ISO `YYYY-MM-DD`. |
| `evaluation_end` | `date` | Có | Ngày gốc dự báo `t` cuối cùng của giai đoạn xét, ISO `YYYY-MM-DD`; không đồng nghĩa ngày đích cuối được phép dùng. |
| `target_cutoff_date` | `date` | **Đề xuất** | Ngày đích muộn nhất được phép có nhãn thực tế khi đánh giá; ví dụ validation 2019 là `2019-12-31`. Xem quy ước ngay dưới bảng. |
| `h` | `integer` | Có | Chân trời **phiên giao dịch**, `1..7`; theo lịch riêng từng tài sản. |
| `metric` | `string` thuộc tập tên quy định | Có | Đúng một metric trên mỗi dòng, xem mục 3. |
| `value` | `number hoặc null` | Có | Giá trị metric; `null` khi không xác định hoặc không áp dụng; **không ghi `NaN` vào JSON/database**. |
| `ci_low` | `number hoặc null` | Có | Cận dưới CI block bootstrap; `null` nếu chưa tính/không tính được. |
| `ci_high` | `number hoặc null` | Có | Cận trên CI block bootstrap; `null` nếu chưa tính/không tính được; `ci_low <= ci_high` nếu có. |
| `n_obs` | `integer >= 0` | Có | Số điểm thực tế dùng để hình thành phép tính metric, sau khi áp dụng mask tương ứng. Không đặt về 0 chỉ vì mẫu số bằng 0. |
| `status` | `enum(string)` | Có | `ok`, `undefined`, `not_applicable`; xem mục 4. |
| `undefined_reason` | `string hoặc null` | Có | Lý do không tính được; `null` nếu `status=ok`. |

**Quy ước ranh giới đánh giá (đề xuất để ngăn rò rỉ):** `evaluation_start`/`evaluation_end` chỉ giới hạn **ngày gốc dự báo** `t`. Mỗi điểm `(t,h)` chỉ được chấm khi:

- `evaluation_start <= t <= evaluation_end`;
- `target_date(t,h) <= target_cutoff_date`, trong đó `target_date` là phiên thứ h sau `t` trên lịch tài sản (ADR-0008);
- nhãn `r_h(t)` đã hoàn tất và đáp ứng quy tắc dữ liệu hợp lệ.

**Bắt buộc thực hiện kiểm tra cutoff, không có tùy chọn tắt.** Chỉ **giá trị cutoff** thay đổi theo cấu hình giai đoạn. Ví dụ validation 2019 dùng `target_cutoff_date = 2019-12-31` để không lấy nhãn sang 2020; test hoặc báo cáo 8 tuần chỉ được chấm khi nhãn đích đã có và không vượt cutoff tương ứng. Đề xuất **lưu cutoff thành cột** để mỗi dòng tự giải thích; phương án gọn hơn là lưu trong cấu hình bất biến có `config_hash` và truy xuất được từ `run_id`. Nhóm cần chọn **một** phương án trước khi triển khai lưu trữ. Nếu chọn chỉ lưu trong cấu hình, bỏ cột khỏi khóa logic trên và bảo đảm `run_id` phân biệt các lần đánh giá khác cutoff. **ADR-0008 chưa chốt cách lưu này.**

Quy tắc ranh giới cho **train 2014–2018 / validation 2019 / test từ 2020** phải được áp dụng khi tạo tập dữ liệu trong `src/eval/`, kể cả loại target bắt đầu cuối 2018 nhưng kết thúc sang 2019 khỏi train. Đây là yêu cầu triển khai khung đánh giá, không phải thêm cột vào `Accuracy`. Theo dõi riêng số mẫu bị loại vì vượt ranh giới để `n_obs` có thể giải thích được.

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

Quy tắc danh mục:

- `mase_returns()` vẫn được giữ trong **code/EDA** để đối chiếu với phân tích trước đây, nhưng **không thuộc danh mục metric lưu mặc định trong `Accuracy`** vì ADR-0008 mục 5 và endpoint `/accuracy/{asset}` không yêu cầu. Nếu nhóm muốn lưu về sau, cần bổ sung định nghĩa thang đo train, giai đoạn train và cấu hình tương ứng trong `config_hash`.
- Các metric đòi **7 phân vị** chỉ được ghi `ok` khi mô hình thực sự có đủ 7 phân vị hợp lệ.
- `naive-zero` theo ADR chỉ cung cấp dự báo điểm `q50=0`, không có 7 phân vị hoặc `prob_up`. Các metric phụ thuộc những đầu ra đó được **bỏ dòng** hoặc ghi `status=not_applicable`, tuyệt đối không tự tạo phân vị để tính. Riêng `sign_accuracy` của naive không xác định vì mọi q50=0; `n_obs=0`, `status=undefined` với `undefined_reason=no_evaluable_obs`. `mae_ratio_vs_naive` bằng 1 khi mẫu số MAE của naive > 0.
- `crossing_rate` là chỉ số **chẩn đoán đầu ra thô** trước `normalize_quantiles()`, không thể tính lại từ 7 phân vị đã chuẩn hóa. **Đề xuất** tính trên các bộ 7 phân vị thô hữu hạn của mô hình có ngày gốc `t` trong `[evaluation_start, evaluation_end]`; không bắt buộc có target thực tế hoặc baseline 252 phiên. `n_obs` là số bộ phân vị thô thực sự kiểm tra. Đây là **ngoại lệ đề xuất** đối với quy tắc mask chung ở ADR-0008 mục 5, cần Khải xác nhận cùng vấn đề ở mục 4 / mục 8 câu 1. Đối với `sample=excl_roll`, phải làm rõ cách xác định cửa sổ roll tương ứng; không tự áp mask nhãn của metric khác.
- Khi mẫu số của baseline **dương** và loss/score không âm, các metric dạng `1 − loss(model)/loss(baseline)` có **giá trị tối đa bằng 1**, có thể âm không giới hạn khi mô hình tệ hơn mốc; **không ép vào `[0,1]`**. Khi mẫu số bằng 0, trả `value=null`, `status=undefined` thay vì chia.

## 4. Quy ước `status`, `n_obs`, giá trị thiếu

| Tình huống | `status` | `value` | `n_obs` | `undefined_reason` |
|---|---|---|---|---|
| Tính thành công | `ok` | Số hữu hạn | Số điểm dùng | `null` |
| Mẫu số metric bằng 0 | `undefined` | `null` | Giữ số điểm đã tham gia phép tính trước bước chia | `zero_denominator` |
| Không còn điểm đánh giá hợp lệ | `undefined` | `null` | `0` | `no_evaluable_obs` |
| Không đủ lịch sử baseline cho metric cần baseline | `undefined` | `null` | `0` nếu không còn điểm nào sau lọc | `insufficient_baseline` |
| Mô hình không có đầu ra cần thiết (ví dụ naive không có 7 phân vị) | `not_applicable` | `null` | `0` | `missing_quantiles` hoặc `missing_prob_up` |

`n_obs` không nhất thiết giống nhau giữa các metric nếu quy tắc loại điểm khác nhau (ví dụ `sign_accuracy`). Không tùy ý loại thêm quan sát sau khi đã tính các metric; lớp tính dòng kết quả phải ghi rõ mask dùng để đếm `n_obs`.

**Điểm chưa chốt trong PR #8:** ADR mục 5 hiện yêu cầu mọi metric dùng chung tập điểm có baseline 252 phiên hợp lệ, trong khi mục 4 giới hạn điều kiện ấy cho những metric dùng baseline. Phải đợi xác nhận rồi mới cố định quy tắc mask trong code. Schema hỗ trợ cả hai cách mà không phải đổi cột. `crossing_rate` được **đề xuất ngoại lệ** vì tại thời điểm `predict` chưa có nhãn thực tế hay baseline đánh giá.

**Ghi log số mẫu bị loại, không thêm cột vào `Accuracy` trong tuần đầu:** theo `(run_id, asset, h, sample)` ghi các bộ đếm `excluded_target_boundary`, `excluded_missing_price`, `excluded_invalid_input_window`, `excluded_insufficient_baseline`, `excluded_roll` (chỉ đối với `excl_roll`). Định nghĩa rõ thứ tự phân loại hoặc cho phép một điểm có nhiều lý do, tránh cộng các bộ đếm trùng nhau thành tổng bị loại. Bản MVP có thể ghi log/console trước; chưa cần một bảng lưu trữ riêng. `n_obs` luôn phản ánh đúng mask thực tế dùng để tính từng metric.

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
    "target_cutoff_date": "2019-12-31",
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
    "model_version": "naive-zero",
    "asset": "gold",
    "sample": "all",
    "evaluation_start": "2019-01-02",
    "evaluation_end": "2019-12-31",
    "target_cutoff_date": "2019-12-31",
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
| `config_hash` | `string` | Hash cấu hình của lần so sánh; bao gồm tập mẫu, lựa chọn HAC, phương pháp xử lý và thông tin mô hình; phục vụ tái lập |
| `asset` | `enum(string)` | `gold`, `silver`, `brent`, `wti` |
| `sample` | `enum(string)` | `all` hoặc `excl_roll` |
| `evaluation_start`, `evaluation_end` | `date` | Khoảng ngày gốc `t` được so sánh |
| `target_cutoff_date` | `date` (đề xuất) | Ngày đích muộn nhất cho phép theo cấu hình đánh giá; cùng quy tắc với `Accuracy` |
| `h` | `integer` | 1..7 |
| `model_a`, `model_b` | `string` | Phiên bản mô hình đem so sánh |
| `loss` | `string` | `pinball` theo ADR |
| `dm_stat` | `number hoặc null` | Thống kê DM sau hiệu chỉnh HLN |
| `p_value` | `number hoặc null` | p-value theo phân phối t với `T−1` bậc tự do |
| `p_value_holm` | `number hoặc null` | p-value sau điều chỉnh Holm với họ kiểm định đã định trước |
| `hac_lag` | `integer` | Ít nhất `h−1` |
| `n_obs` | `integer >= 0` | Số cặp loss ngoài mẫu hợp lệ |
| `status` | `enum(string)` | `ok`, `undefined`, `not_applicable` |
| `undefined_reason` | `string hoặc null` | Ví dụ `insufficient_pairs`, `nonpositive_hac_variance`, `missing_quantiles`, `missing_paired_loss`; `null` nếu `status=ok` |

**Khóa logic đề xuất:** `(run_id, model_a, model_b, asset, sample, evaluation_start, evaluation_end, target_cutoff_date, h, loss)`. Thứ tự cặp `(A,B)` có ý nghĩa vì quyết định dấu thống kê, không tự ý tráo vị trí hoặc coi hai cặp đảo chiều là một kết quả. `config_hash` để kiểm chứng khả năng tái lập, có thể trùng giữa các dòng cùng `run_id`. Nếu phương sai HAC không dương, không đủ cặp hợp lệ hoặc không có loss ghép cặp, không tự sinh p-value: `dm_stat`/`p_value`/`p_value_holm = null`, `status=undefined`, ghi lý do và giữ `n_obs` là số cặp đã xét.

**Giới hạn so sánh:** `naive-zero` theo ADR chỉ có q50=0, không có 7 phân vị nên **không thể ghép cặp DM dùng pinball loss 7 phân vị**; không tự giả lập phân vị. Nếu vẫn cần thể hiện cặp này trong bảng, dùng `status=not_applicable`, `undefined_reason=missing_quantiles`.

Quy ước dấu: `d_t = PL_A(t) − PL_B(t)`; `dm_stat < 0` nghĩa là **A có pinball loss trung bình thấp hơn B**, không đồng nghĩa có ý nghĩa thống kê nếu p-value chưa đủ nhỏ.

## 7. Ràng buộc với API và lớp tính toán

- `GET /accuracy/{asset}` theo `contract.md` sử dụng **8 tuần gần nhất**, riêng từng h. Tầng API sẽ lọc đúng `asset`, `model_version` và khoảng đánh giá, rồi **pivot** các dòng thành tên chỉ số như trong contract. `quantile_hit_0.05` ... `quantile_hit_0.95` được gom thành đối tượng `quantile_hit_rates` theo yêu cầu API, không bắt API nhận 7 cột tách rời.
- Không ép mọi hàm trong `src/forecast/metrics.py` trả ra từ điển schema. Hàm metric vẫn thuần (mảng → số thực/`NaN`); lớp `compute_metric_row()` ở `src/eval/` sẽ áp mask, tính `n_obs`, xử lý `status`, gắn CI rồi xuất hàng dài.
- `crossing_rate` phải được ghi từ thông tin trước khi sắp xếp phân vị; lớp đánh giá không thể phục hồi nó từ `Forecasts` đã chuẩn hóa.
- Khi làm tròn / serialize để lưu, giữ đủ độ chính xác để không gây sai lệch CI, `NaN`/`inf` được đổi sang `null` kèm lý do; không diễn giải `null` thành `0`.
- Không dùng dữ liệu từ test để chọn cấu hình, độ dài block bootstrap, ARIMA hay cách nội suy. Ghi các tham số này cùng cấu hình của `run_id`. Kiểm tra `target_date <= target_cutoff_date` **luôn bật** và ghi số điểm bị loại theo lý do; giá trị cutoff là cấu hình của từng giai đoạn.
- **Điểm cần đồng bộ trong `contract.md`:** mô tả `sign_accuracy` hiện nói “bỏ điểm bằng 0”, dễ hiểu thiếu trường hợp q50=0. Khi nhóm cập nhật hợp đồng API, nên ghi tường minh **loại cả `y = 0` và `q50 = 0`** như ADR-0008; tài liệu schema này không tự sửa contract.

## 8. Các quyết định cần nhóm xác nhận trước khi triển khai bảng thật

1. **Mask chung hay riêng theo metric:** Khi baseline 252 phiên không hợp lệ, có bắt buộc loại điểm khỏi mọi chỉ số không? **Riêng `crossing_rate`**: nhóm có đồng ý ngoại lệ tính trên đầu ra thô trong cùng khoảng `t`, không cần target hoặc baseline không? (Liên quan comment PR #8.)
2. **Metric không áp dụng:** Có ghi dòng `status=not_applicable` hay bỏ dòng? Khuyến nghị ghi dòng để phân biệt "không áp dụng" với "chưa chạy" khi pivot/hiển thị.
3. **Lưu trữ:** Tuần đầu chỉ cần Parquet/CSV hay phải có DynamoDB/SQL? Schema logic độc lập lựa chọn hệ lưu trữ.
4. **Kiểu lần đánh giá:** Có thêm `evaluation_kind` (`validation`, `test`, `rolling_8w`) ngay từ đầu không? Mức CI, block length, seed và số lần bootstrap được ghi trong cấu hình ứng với `config_hash`.
5. **Cách lưu cutoff:** Kiểm tra `target_date <= target_cutoff_date` **luôn thực hiện**; chỉ cần nhóm chọn `target_cutoff_date` là **cột của hai bảng** (phương án đề xuất hiện tại) hay chỉ lưu trong cấu hình bất biến gắn với `config_hash`. `evaluation_start/end` vẫn là ngày gốc `t`. Các nhãn vượt ranh giới split không tham gia đánh giá/tối ưu mô hình.
6. **Phân vị ARIMA:** ADR-0008 chưa quy định ARIMA tạo **7 phân vị cho h=1..7** bằng cách nào (ví dụ phân phối dự báo có giả định hoặc mô phỏng/bootstrapping nhân quả). Nhóm cần chọn một cách, đưa vào cấu hình và đánh giá trên validation 2019. `arima-p100-v1` trong ví dụ **chỉ là tên minh họa**, không có nghĩa đã chốt phương pháp.

## 9. Tiêu chí hoàn thành bước thiết kế

Bản đề xuất này đủ để nhóm **review** và thảo luận trong PR #10. Chỉ coi schema là **đã chốt để tích hợp** khi nhóm thống nhất cột/kiểu dữ liệu, khóa logic, danh mục metric, quy tắc `null/status/n_obs`, trường hợp `crossing_rate`, bảng DM, cách lưu cutoff và cách ánh xạ tới `/accuracy/{asset}`.

Sau khi chốt, triển khai `metrics.py` bằng các hàm tính toán thuần kèm unit test; lớp ở `src/eval/` phụ trách lọc mẫu, tạo dòng schema, log lý do loại điểm và không dùng nhãn thuộc giai đoạn tương lai. Phần metric thuần có thể thực hiện song song khi PR còn ở trạng thái Draft.
