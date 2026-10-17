# ADR-0008: Target, phân vị, xác suất tăng và cách đánh giá mô hình

- Ngày: 2026-10-16 (cập nhật theo review của Long trên PR #6)
- Trạng thái: Đề xuất (chờ Long xác nhận; thông qua ở buổi họp 16/10)
- Người viết: Trịnh Tiến Khải; người duyệt: Long
- Liên quan: ADR-0002 (thay thế một phần), ADR-0005 (nguồn giá, lịch giao dịch, cờ `roll`), ADR-0007 (cache CEEMDAN), `docs/api/contract.md`, `docs/experiments/roll-analysis-2026-10.md`
- Đầu vào: văn bản "Chốt target, phân vị, MASE và return ngày roll" (Khải, 12–13/10); "Chốt target, phân vị và đánh giá mô hình" và "Đánh giá các metric trong metrics.py" (Long, 15/10); review của Long trên PR #6 (16/10)

## Bối cảnh

Trước khi làm DLinear MVP (demo 25/10), nhóm cần thống nhất mô hình dự báo cái gì, xuất ra gì và được chấm bằng chỉ số nào. Các quyết định này ảnh hưởng tới mô hình, Lambda `predict`, bảng `Forecasts`, web và tool chatbot; đổi sau sẽ phải sửa nhiều nơi.

Ràng buộc: validation chỉ có năm 2019 (một năm, ít biến động hơn 2014–2018); target h > 1 chồng lấp; tập test 2020 → nay chỉ được dùng một lần sau khi khóa tham số.

ADR này giữ quyết định cốt lõi của ADR-0002 (dự báo phân vị log return, không dự báo mức giá) và thay các chi tiết: h theo phiên giao dịch, 7 phân vị, bộ chỉ số đánh giá.
## Quyết định

### 1. Target

- Target là log return h phiên giao dịch của chuỗi target, h = 1–7:

  `r_h(t) = ln(P_(t+h) / P_t)`

- Chuỗi target: vàng → GLD, bạc → SLV, Brent → BZ=F, WTI → CL=F. GLD và SLV là chuỗi đại diện cho kim loại, không đồng nhất với giá giao ngay; web và chatbot phải nói rõ điều này.
- Ngày gốc dự báo (`base_date`) là ngày có giá hợp lệ cuối cùng của tài sản, không phải ngày chạy.
- Web ghi "phiên giao dịch", không ghi "ngày".

**Quy tắc xác định t + h (theo lịch, không theo dòng dữ liệu).**

- t + h là phiên thứ h sau t trên lịch giao dịch của tài sản theo ADR-0005 (CME cho BZ=F, CL=F; NYSE cho GLD, SLV). Không dùng `shift(-h)` theo vị trí dòng: nếu thiếu một dòng giữa t và t + h, dịch theo dòng sẽ thành h + 1 phiên.
- "Giá hợp lệ" tại một phiên: có dòng trong bản clean, không nằm trong `rejected.parquet`, giá > 0. Các cờ chỉ đánh dấu (`roll`, `low_liquidity`, `jump`, `xcheck_*`, `stale_source`) không làm giá mất hiệu lực.
- `r_h(t)` là NaN khi không có giá hợp lệ tại t hoặc tại t + h (thiếu dòng, dòng bị loại, giá ≤ 0 như WTI ngày 20/4/2020).
- Thiếu giá ở các phiên nằm giữa t và t + h không làm `r_h(t)` mất hiệu lực, vì log return chỉ phụ thuộc hai đầu; nhưng code phải đếm và ghi log số target có phiên giữa bị thiếu.
- Hàm tạo target (`horizon_log_returns()`) phải tính theo lịch; có test cho các trường hợp: thiếu dòng ở giữa (target vẫn đúng h phiên), thiếu dòng ở t + h (NaN), dòng bị loại (NaN), giá ≤ 0 (NaN).

**Quy tắc cho cửa sổ input của mô hình.**

- Return ngày dùng làm input `r_1(s)` cũng theo quy tắc trên, nên là NaN nếu thiếu giá hợp lệ tại s hoặc s + 1.
- Khi train và đánh giá: bỏ mẫu có NaN trong cửa sổ input hoặc trong target; số mẫu bị bỏ được báo cáo theo tài sản.
- Khi chạy `predict`: nếu cửa sổ input mới nhất có NaN, không ghi dự báo mới cho tài sản đó; bản ghi cũ trong `Forecasts` giữ nguyên và web hiện như dữ liệu cũ. Ghi log để xử lý.

### 2. Phân vị và hàm mất mát

- Mỗi h có 7 phân vị: 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95. Web hiển thị 0.10, 0.50, 0.90 (khoảng danh nghĩa 80%).
- Huấn luyện bằng pinball loss trung bình trên 7 phân vị × 7 mức h.
- Mô hình xuất q50 cộng các khoảng dương (softplus) về hai phía để hạn chế phân vị cắt nhau.

**Chuẩn hóa phân vị: làm một lần, kiểm tra ở mọi nơi.**

- Có một hàm duy nhất `normalize_quantiles()`: sắp xếp 7 phân vị theo thứ tự không giảm (rearrangement bằng `np.sort` trên từng (t, h)), trả kèm cờ cho biết có phải sắp xếp hay không. Không dùng `np.maximum.accumulate` vì cách đó thay đổi giá trị phân vị thay vì chỉ đổi thứ tự.
- Hàm này chạy đúng một lần, ngay sau khi mô hình xuất kết quả (trong `predict` và trong backtest). Số lần phải sắp xếp được ghi log trước khi sửa (chỉ số "tỷ lệ phân vị cắt nhau").
- `prob_up`, quy đổi giá và bản ghi `Forecasts` đều dùng cùng bộ phân vị đã chuẩn hóa này. Các hàm phía sau (`prob_up()`, `quantiles_to_prices()`, `to_forecast_record()`) không tự sửa phân vị: chúng kiểm tra đầu vào không giảm và báo lỗi nếu sai.
- Quy đổi giá: `P_(t+h) = P_t × exp(q)`. Khoảng [q10, q90] là khoảng danh nghĩa 80%, không phải cam kết.

### 3. Xác suất tăng

- MVP dùng nội suy tuyến tính giữa hai phân vị kẹp mức 0 để ước lượng P(r_h ≤ 0); xác suất tăng = 1 − P(r_h ≤ 0), kẹp trong [0.05, 0.95]. Đây là phép xấp xỉ, chưa hiệu chỉnh.
- Trường hợp biên: 0 < q05 → 0.95; 0 > q95 → 0.05; 0 trùng một phân vị → dùng đúng mức của phân vị đó.
- Thứ tự đánh giá: kiểm tra tỷ lệ trúng từng phân vị trước, sau đó mới đánh giá `prob_up` bằng Brier score và độ hiệu chỉnh trên dự báo ngoài mẫu.
- Thí nghiệm khi có dự báo DLinear trên validation 2019: so Brier score của (a) nội suy tuyến tính và (b) PCHIP, trên cùng các điểm của tập đánh giá chung. Định nghĩa ΔBS = BS(PCHIP) − BS(tuyến tính), lấy trung bình đều trên 4 tài sản × 7 mức h. Khoảng tin cậy 95% tính bằng block bootstrap theo ngày: rút cùng một khối ngày cho mọi tài sản và h để giữ tương quan; độ dài khối định trước trong config. Chỉ chuyển sang PCHIP khi khoảng tin cậy nằm hoàn toàn dưới 0; nếu khoảng chứa 0 hoặc nằm trên 0 thì giữ nội suy tuyến tính. ΔBS theo từng tài sản × h chỉ để tham khảo, không dùng để chọn phương pháp riêng cho từng cặp.
- Chưa dùng Platt scaling trong MVP; không hiệu chỉnh trên tập test.

### 4. Mốc so sánh

| Mốc | Dùng cho | Cách tính |
|---|---|---|
| Naive return = 0 | Tỷ lệ MAE của q50 | Dự báo return bằng 0 |
| Phân phối 252 phiên | Pinball, độ phủ, interval score | 7 phân vị thực nghiệm của các `r_h(s)` hợp lệ, đã hoàn tất (s + h ≤ t), với s thuộc 252 phiên gần nhất trước hoặc bằng t |
| Tần suất tăng 252 phiên; hằng số 0,5 | Brier score | Tỷ lệ `r_h(s) > 0` trên cùng tập s như trên; 0,5 |
| Luôn đoán tăng; tỷ lệ tăng thực tế | Tỷ lệ đúng chiều | |

- Mốc 252 phiên chỉ hợp lệ khi có ít nhất 200 return hợp lệ trong cửa sổ. Điểm không có mốc hợp lệ bị loại khỏi tập đánh giá chung (mục 5), tức là bị loại cho mọi chỉ số, kể cả chỉ số không dùng mốc. Vì dữ liệu bắt đầu từ 01/2012, điều kiện này luôn thỏa từ 2014 trở đi, trừ khi có khoảng trống dữ liệu dài; số điểm bị loại vì lý do này được báo cáo riêng.
- Có test chống rò rỉ: kết quả mốc tại t không đổi khi sửa hoặc nối thêm giá sau t; return chưa hoàn tất (s + h > t) không được dùng.

### 5. Chỉ số đánh giá

**Tập đánh giá chung (áp dụng cho mọi chỉ số). Với mỗi (tài sản, h, mẫu), điểm t thuộc tập đánh giá chung khi: r_h(t) không phải NaN (mục 1), có dự báo đã chuẩn hóa (mục 2), và mốc 252 phiên hợp lệ (mục 4). Mọi chỉ số đều tính trên cùng tập này, kể cả các chỉ số không dùng mốc (quantile_hit_rates, coverage_80, width_80, interval_score_80, sign_accuracy, up_rate). Lý do:

các chỉ số đặt cạnh nhau phải mô tả cùng các điểm;
kiểm định DM cần chuỗi loss khớp ngày;
tránh việc mỗi chỉ số tự chọn tập điểm có lợi cho mình.

Quy ước n_obs và trạng thái:

n_obs của một chỉ số là số điểm thực sự đi vào công thức của chỉ số đó. Giá trị này bằng kích thước tập chung, trừ sign_accuracy (bỏ thêm các điểm có y = 0 hoặc q_0.50 = 0). Báo kèm n_common và số điểm bị loại theo từng lý do: target NaN, thiếu dự báo, mốc không hợp lệ.
Chỉ số không xác định vì mẫu số bằng 0 (ví dụ mean(|y|) = 0, hoặc BS hay PL của mốc bằng 0): giá trị là NaN với trạng thái undefined, lý do zero_denominator; n_obs vẫn ghi số điểm đã dùng; không thay bằng 0 và không bỏ dòng.
Với dầu, mẫu excl_roll là tập con của tập chung, bỏ thêm các cửa sổ chứa ngày đáo hạn hoặc phiên có cờ roll (mục 6).
Mọi chỉ số tính trên log return, riêng từng tài sản × h, trên giai đoạn đánh giá. Ký hiệu: y là `r_h(t)` thực tế; q_τ là phân vị dự báo mức τ; τ ∈ {0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95}.

| Chỉ số | Công thức | Vai trò |
|---|---|---|
| Pinball loss | `L_τ(y, q) = max(τ·(y − q), (τ − 1)·(y − q))`; PL = trung bình đều trên 7 mức τ, rồi trung bình trên các điểm hợp lệ | Thành phần |
| `pinball_skill` | `1 − PL(mô hình) / PL(mốc 252 phiên)`, cùng tập điểm hợp lệ | **Chỉ số chính, chọn mô hình** |
| `quantile_hit_rates` | Với từng τ: tỷ lệ log return thực tế nằm dưới phân vị dự báo, `mean(y ≤ q_τ)`; so với τ | Kiểm tra hiệu chỉnh |
| `coverage_80` | `mean(q_0.10 ≤ y ≤ q_0.90)` | Kiểm tra hiệu chỉnh, hiển thị trên web |
| `width_80` | `mean(q_0.90 − q_0.10)`, đơn vị log return | Đi kèm `coverage_80` |
| `interval_score_80` | Với α = 0,2, l = q_0.10, u = q_0.90: `(u − l) + (2/α)·(l − y)·1{y < l} + (2/α)·(y − u)·1{y > u}`; trung bình trên các điểm hợp lệ | Kiểm tra hiệu chỉnh |
| Brier score | `BS = mean((p − 1{y > 0})²)`, p là `prob_up` | Thành phần |
| `brier_skill` | `1 − BS(mô hình) / BS(tần suất tăng 252 phiên)`; báo kèm `1 − BS(mô hình) / BS(0,5)` | Xác suất tăng |
| `mae_ratio_vs_naive` | `mean(|y − q_0.50|) / mean(|y|)` trên cùng tập điểm | Báo cáo phụ |
| `sign_accuracy` | `mean(sign(q_0.50) = sign(y))` trên các điểm có y ≠ 0 và q_0.50 ≠ 0 | Báo cáo phụ |
| `up_rate` | `mean(y > 0)`, luôn đặt cạnh `sign_accuracy` | Báo cáo phụ |
| `n_obs` | Số điểm hợp lệ dùng cho từng chỉ số | |
| Tỷ lệ phân vị cắt nhau | Tỷ lệ (t, h) phải sắp xếp lại ở mục 2 | Chẩn đoán |

- So sánh hai mô hình: Diebold–Mariano trên chuỗi chênh lệch PL của hai mô hình (hàm nhận thẳng chuỗi loss, không nhận sai số), riêng từng h, phương sai HAC với độ trễ ≥ h − 1, hiệu chỉnh HLN và so với phân phối t (T − 1 bậc tự do).
- Tên gọi: `mae_ratio_vs_naive()` tính tỷ lệ MAE so với naive, không gọi là MASE. `mase_returns()` giữ nghĩa MASE chuẩn (thang đo từ train) để đối chiếu với EDA; không đổi ngầm ý nghĩa của hai hàm.
- Không dùng: RMSE; mọi sai số tính trên mức giá; nhóm chỉ số spike.
- Không gộp pinball thô giữa các tài sản. Nếu cần một con số tổng hợp, lấy trung bình `pinball_skill` với trọng số định trước.
- Kiểm tra mẫu số bằng 0 (Brent giai đoạn giá đứng) trước khi chia.
- Mọi chỉ số kèm khoảng tin cậy block bootstrap. Khi báo nhiều kiểm định (4 tài sản × 7 mức h), định trước chỉ số chính và điều chỉnh p-value (Holm).
- Bảy mức h dùng chung ngày tương lai nên không phải bảy bằng chứng độc lập.
- Ngoại lệ: tỷ lệ phân vị cắt nhau là chẩn đoán đầu ra thô của mô hình. Chỉ số này tính trên mọi dự báo có t trong giai đoạn, không cần target hay mốc, và chỉ tính cho mẫu all.
### 6. Ngày roll của dầu

- Giữ nguyên giá khi huấn luyện (phương án A). Không thay return ngày roll bằng return của loại dầu kia (phương án C bị loại).
- Khi đánh giá dầu, báo cáo hai mẫu: toàn bộ điểm hợp lệ, và bỏ các cửa sổ chứa ngày đáo hạn hoặc phiên có cờ `roll`; Brent và WTI báo riêng.
- Xem lại nếu trên 2019 sai số của Brent dồn vào các cửa sổ chứa roll.
- Web hiện dòng lưu ý khi kỳ dự báo chứa ngày đáo hạn (`roll_in_horizon` trong `contract.md`).

### 7. Chia dữ liệu

- 2012–2013: khởi động (tính đặc trưng, cửa sổ CEEMDAN, mốc 252 phiên).
- 2014–2018: train. 2019: validation, dùng để chọn tham số. 2020 → nay: test, chạy một lần sau khi khóa tham số.
- Nếu kết quả 2020 → nay đã được dùng để ra quyết định nào, báo cáo phải nói rõ.
- Nhãn không được vượt ranh giới giai đoạn. Một điểm (t, h) chỉ thuộc giai đoạn khi cả t và ngày đích t + h đều nằm trong giai đoạn đó. Ví dụ: validation 2019 không dùng target có ngày đích sang 2020; train không dùng target có ngày đích sang 2019. Số điểm bị loại vì ranh giới được báo cáo riêng.
### 8. DLinear MVP (demo 25/10)

| Mục | Quyết định |
|---|---|
| Input | Chỉ log return ngày của chính tài sản, từ bản clean, theo quy tắc mục 1; không chỉ báo, không sentiment, không tài sản khác |
| Số mô hình | Mỗi tài sản một mô hình (4 mô hình) |
| Cửa sổ input | 60 phiên (có thể chỉnh trên validation 2019, ghi lý do) |
| Output | 7 mức h × 7 phân vị, chuẩn hóa theo mục 2 |
| Chuẩn hóa input | Mean/std của tập train, lưu cùng mô hình |
| Tái lập | Seed cố định; cấu hình trong file config; ghi commit hash |
| Đầu ra cho hệ thống | Đúng định dạng `docs/api/contract.md` |

Mô hình chung cho 4 tài sản, chỉ báo (GPR, OVX/GVZ, lịch sự kiện) và chỉ số tin là thí nghiệm của K3–K4.

## Các phương án đã cân nhắc

| Hạng mục | Phương án bị loại | Lý do |
|---|---|---|
| Target | Dự báo mức giá | Mức giá hôm sau gần bằng hôm nay nên chỉ số đẹp giả tạo |
| Target | t + h theo vị trí dòng (`shift(-h)`) | Thiếu một dòng thì h không còn là h phiên |
| Phân vị | Chỉ 3 phân vị 10/50/90 | Xác suất tăng nội suy quá thô quanh mức 0 |
| Phân vị cắt nhau | `np.maximum.accumulate`; mỗi hàm tự sửa | Thay đổi giá trị phân vị; xác suất và giá có thể tính từ hai bộ phân vị khác nhau |
| Chỉ số chính | Tỷ lệ MAE so với naive | Chỉ đo q50, bỏ qua 6 phân vị còn lại; không so được giữa tài sản |
| MASE | Thang đo từ train làm chỉ số chính | 2019 yên tĩnh hơn train: naive đạt 0,80–0,93 mà không học gì |
| Roll | C (thay return bằng loại dầu kia) | Sai số khoảng 0,5 điểm % mỗi lần thay; chưa xác định chắc ngày chuyển hợp đồng; lịch roll hai loại dầu khác nhau |
| Roll | B (bỏ cửa sổ có roll khi train) | Mất khoảng 1/3 target với h = 7; giữ làm mẫu đối chứng khi đánh giá |
| DLinear MVP | Thêm chỉ báo và sentiment | Cần EDA, làm sạch, căn thời điểm công bố riêng; dễ trễ demo và dễ rò rỉ |

## Hệ quả

- Bảng `Forecasts`, API và tool chatbot dùng 7 phân vị đã chuẩn hóa, `prob_up` và `target_series` theo `contract.md`.
- `src/forecast/returns.py`: `horizon_log_returns()` theo lịch; `normalize_quantiles()`; `prob_up()` và `quantiles_to_prices()` kiểm tra đầu vào thay vì tự sửa. `src/forecast/baselines.py` (mới): mốc 252 phiên nhân quả, có test chống rò rỉ.
- `metrics.py` (Long): cài đặt các công thức ở mục 5; sửa Diebold–Mariano; đánh dấu RMSE, MASE trên giá và nhóm spike là không dùng.
- Chưa thể kết luận DLinear tốt hơn mốc cho tới khi có kết quả ngoài mẫu; validation 2019 chỉ đủ để chọn tham số MVP.

## Việc cần làm

- [ ] Long xác nhận ADR này
- [ ] Khải: `returns.py` theo mục 1–3 (target theo lịch, `normalize_quantiles()`, kiểm tra đầu vào); `baselines.py` (mốc 252 phiên); `prob_up_pchip()` cho thí nghiệm; test đủ 7 mức phân vị, phân vị cắt nhau, 0 nằm ngoài khoảng và giới hạn [0.05, 0.95]
- [ ] Long: `metrics.py` theo mục 5 (hạn 20/10)
- [ ] Long: DLinear MVP theo mục 8, báo cáo trên 2019 (hạn 22/10)
- [ ] Long: thí nghiệm nội suy xác suất tăng theo mục 3 khi có dự báo DLinear
- [ ] Đánh giá dầu theo hai mẫu (mục 6)

## Tài liệu tham khảo

- Hyndman, R. J. & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting*, 22(4), 679–688.
- Gneiting, T. (2011). Quantiles as optimal point forecasts. *International Journal of Forecasting*, 27(2), 197–207.
- Gneiting, T. & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *JASA*, 102(477), 359–378.
- Chernozhukov, V., Fernández-Val, I. & Galichon, A. (2010). Quantile and probability curves without crossing. *Econometrica*, 78(3), 1093–1125.
- Diebold, F. X. & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263.
- Harvey, D., Leybourne, S. & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281–291.
- Christoffersen, P. F. (1998). Evaluating interval forecasts. *International Economic Review*, 39(4), 841–862.
