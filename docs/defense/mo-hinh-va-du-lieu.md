# Chương 1. Mô hình và dữ liệu

> Bản nháp ngày 11/11/2026. Chủ trì: Khải; review: Long. Cơ sở: `origin/developer` @ `c17cca9` (11/11/2026).
>
> - Chương này thay mục 2–3 của [tư liệu kiến trúc và mô hình](lua-chon-kien-truc-va-mo-hinh.md). Tư liệu đó là bản kế hoạch tháng 10, trước khi có kết quả thí nghiệm.
> - Định nghĩa chỉ số, tập điểm chung, bootstrap, Holm và DM nằm ở [Chương 2: Phương pháp đánh giá](phuong-phap-danh-gia.md), không nhắc lại ở đây.
> - Chương này **không có số của tập test 2020 → nay**. Long chạy tập này một lần trong tuần 16–22/11 theo [kế hoạch test2020](../experiments/test2020-plan.md). Chỗ để điền ghi `[CHỜ SỐ LIỆU]`.

## Tóm tắt

- CPAWS dự báo **phân phối của log return** 1–7 phiên tới cho vàng, bạc, Brent và WTI, dưới dạng 7 phân vị. CPAWS không dự báo mức giá. Web quy đổi phân vị ra khoảng giá và xác suất tăng.
- Sản phẩm đang chạy **mốc thống kê 252 phiên** (`baseline-q252`) cho cả 4 tài sản. Mốc này lấy phân vị thực nghiệm của return đã hoàn tất trong 252 phiên gần nhất, không có tham số học.
- Nhóm đã thử 4 họ mô hình chỉ dùng giá, tổng 13 cấu hình, trên validation 2019: DLinear, CEEMDAN + DLinear (K3), co giãn theo biến động (K3b) và GJR-GARCH + FHS (K4). Không mô hình nào vượt mốc theo tiêu chí chốt trước. Mỗi thí nghiệm có kế hoạch commit trước khi chạy.
- Challenger S1a (co giãn khoảng theo biến động EWMA) chạy song song trong Lambda predict từ 04/11/2026. Người dùng không thấy S1a. Mọi lần đổi champion đều phải có ADR.
- So với proposal, nhóm bỏ CEEMDAN + DLinear/LSTM làm mô hình chính và bỏ retrain bằng SageMaker AI. Lý do nằm ở kết quả K3, K3b, K4 và [ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md), xem mục 1.6.

## 1.1. Bài toán và đầu ra

### Tài sản và chuỗi target

| Tài sản | Chuỗi target | Lịch giao dịch | Ghi chú |
|---|---|---|---|
| Vàng | GLD | NYSE | Quỹ ETF giữ vàng vật chất, là **chuỗi đại diện**, không phải giá giao ngay |
| Bạc | SLV | NYSE | Quỹ ETF giữ bạc vật chất, chuỗi đại diện |
| Brent | BZ=F | CME | Hợp đồng tương lai gần nhất, có bước nhảy ngày chuyển hợp đồng |
| WTI | CL=F | CME | Như Brent; ngày 20/4/2020 giá âm |

### Target

Với ngày gốc `t` và kỳ hạn `h = 1…7`, target là log return:

```text
r_h(t) = ln( P(t+h) / P(t) )
```

- `t + h` là **phiên thứ h** sau `t` theo lịch giao dịch của tài sản, không phải h ngày lịch hay h dòng dữ liệu ([ADR-0008](../adr/0008-target-quantiles-evaluation.md) mục 1).
- `r_h(t)` là NaN khi thiếu giá hợp lệ tại `t` hoặc `t + h`, hoặc khi giá ≤ 0. Ví dụ là WTI ngày 20/4/2020. Target không được forward-fill.

### Đầu ra

- 7 phân vị `q05, q10, q25, q50, q75, q90, q95` cho mỗi h, học hoặc đánh giá bằng pinball loss.
- `normalize_quantiles()` sắp xếp phân vị đúng một lần, ngay sau khi mô hình xuất kết quả trong Lambda predict. Các bước sau (xác suất tăng, quy đổi giá, bản ghi `Forecasts`) chỉ kiểm tra, không sắp xếp lại.
- **Khoảng 80% danh nghĩa** `[q10, q90]` và trung vị `q50`, quy đổi sang giá bằng `P(t) × exp(q)`. Mức bao phủ thật đo bằng `coverage_80` (Chương 2), có thể khác 80%.
- **Xác suất tăng** `1 − F(0)`, với `F` nội suy tuyến tính giữa hai phân vị kẹp mức 0, giới hạn trong [0,05; 0,95]. Đây là xác suất xấp xỉ, chưa hiệu chỉnh. Thí nghiệm so PCHIP với nội suy tuyến tính (ADR-0008 mục 3) không thực hiện, giữ nội suy tuyến tính (PR #106).

### Vì sao không dự báo mức giá

Giá phiên sau gần bằng giá phiên trước, nên sai số trên mức giá luôn nhỏ, kể cả khi mô hình không học được gì.

- **Ví dụ trên 2017–2018:** naive "giá ngày mai = giá hôm nay" có MAPE trên mức giá chỉ 0,48% (vàng) đến 1,32% (WTI) ([PR #83](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/83), mục 6). Tức là đạt "chính xác 99%" mà không cần mô hình.
- **Hệ quả:** dự báo phân vị của return buộc mô hình phải học sự thay đổi thật. Vì vậy nhóm cấm MAPE, RMSE và mọi sai số trên mức giá khi chọn mô hình ([ADR-0002](../adr/0002-return-quantile-target.md), [ADR-0008](../adr/0008-target-quantiles-evaluation.md)).

## 1.2. Dữ liệu

### Nguồn ([ADR-0005](../adr/0005-price-data-sources.md))

Mỗi chuỗi dùng **một nguồn cho cả lịch sử lẫn cập nhật hằng ngày**, đều qua thư viện yfinance:

| Chuỗi | Dùng để | Không dùng để |
|---|---|---|
| GLD, SLV, BZ=F, CL=F | Train, đánh giá, dự báo hằng ngày | |
| VND=X (USD/VND) | Quy đổi hiển thị sang VND | Đặc trưng mô hình |
| GC=F | Hệ số hiển thị USD/oz | Train |
| EIA API v2 (RBRTE, RWTC) | Đối chiếu mức giá dầu | Target |
| NBP | Đối chiếu mức giá vàng | Target |

- Các nguồn đã loại: MetalpriceAPI, World Gold Council/LBMA, Stooq, Tiingo (ADR-0005).
- Rủi ro điều khoản Yahoo và cách nhóm xử lý nằm ở ADR-0005 và [chương Bảo mật và chi phí](security-and-cost.md) (#116). Chương này chỉ ghi ảnh hưởng tới mô hình (mục 1.7).

### Thu thập và làm sạch

- **Lịch chạy:** Lambda `ingest` chạy theo EventBridge Scheduler `cron(15 12 ? * TUE-SAT *)` UTC.
- **Tránh thanh chưa chốt:** bỏ thanh của ngày hiện tại theo giờ New York; tải lại 5 phiên gần nhất và ghi đè theo khóa.
- **Bản clean:** bảng dạng dài, mỗi dòng có cờ `flag`; dòng bị loại nằm trong `rejected.parquet`.
- **Lưu trữ:** mỗi lần chạy ghi một snapshot `clean/prices/dt=<ngày>/` trên S3 `cpaws-dev-lake`.
- **Lịch giao dịch:** dùng `pandas_market_calendars` (NYSE cho GLD, SLV; CME cho dầu).
- **Phiên thiếu:** phiên có trong lịch mà không có giá thì để NaN, không nội suy.
- **Dự báo từng ngày gốc** ghi rõ `input_snapshot_dt` (PR #48). Nhờ vậy biết mỗi dự báo đã dùng snapshot nào.

### Chia tập theo thời gian

| Giai đoạn | Khoảng | Dùng để |
|---|---|---|
| Khởi động | 2012–2013 | Cửa sổ 252 phiên, cửa sổ CEEMDAN, đặc trưng |
| Train | 2014–2018 | Huấn luyện, kiểm định chéo (K4: 2016–2018) |
| Validation | 2019 | Chọn cấu hình; đã dùng 4 lần với 13 cấu hình (mục 1.4) |
| Test | 02/01/2020 → 23/10/2026 | Chạy **một lần** sau khi khóa tham số ([kế hoạch #75](../experiments/test2020-plan.md)) |

- Một cặp `(t, h)` chỉ thuộc một giai đoạn khi cả `t` và `t + h` đều nằm trong giai đoạn đó. Nhờ vậy nhãn không vượt ranh giới; ví dụ cửa sổ 2019 không chạm dữ liệu 2020.
- Không xáo trộn ngẫu nhiên. Scaler và tham số chỉ fit trên train.

### Đặc điểm dữ liệu ([EDA 10/2026](../eda/eda-prices-2026-10.md))

| Tài sản | Độ lệch chuẩn return 1 phiên, train 2014–2018 | Tỷ lệ phiên tăng h = 7, train | Tỷ lệ phiên tăng h = 7, 2019 |
|---|---|---|---|
| Vàng | 0,83% | 50,5% | 59,6% |
| Bạc | 1,31% | 46,8% | 47,8% |
| Brent | 2,17% | 49,0% | 64,5% |
| WTI | 2,29% | 49,4% | 61,6% |

- **Dầu biến động mạnh hơn kim loại:** độ lệch chuẩn return 1 phiên trên train 2014–2018 của dầu (2,17–2,29%) gấp khoảng 1,7 lần bạc (1,31%) và 2,6–2,8 lần vàng (0,83%) ([EDA](../eda/eda-prices-2026-10.md)), nên khoảng dự báo của dầu rộng hơn nhiều.
- **2019 khác giai đoạn train:** vàng và dầu tăng nhiều hơn hẳn, độ lệch chuẩn thấp hơn. Mọi kết quả trên 2019 phải đọc trong bối cảnh một năm "yên và đi lên".
- **Cửa sổ NaN do thiếu phiên trong train:** Brent 10, WTI 6, kim loại 0 (EDA, bảng cửa sổ NaN).

### Dầu: ngày chuyển hợp đồng

- **Cách xử lý:** BZ=F và CL=F là hợp đồng gần nhất, nên có bước nhảy ở ngày chuyển hợp đồng. Nhóm chọn phương án A: giữ nguyên giá khi train, và khi đánh giá thì báo cáo hai mẫu, toàn bộ (`all`) và bỏ cửa sổ chứa ngày chuyển (`excl_roll`) (ADR-0008).
- **Kiểm chứng:** cờ `roll` khớp với ngày Yahoo thực sự chuyển giá ([phân tích roll](../experiments/roll-analysis-2026-10.md)).
- **Lỗ hổng đã biết:** Yahoo thiếu phiên 05/12/2018 của BZ=F và CL=F. Hôm đó NYSE đóng cửa vì quốc tang, còn CME năng lượng vẫn giao dịch. Hậu quả là 301 dòng dầu mỗi tài sản trong validation 2019 bị loại vì cửa sổ đầu vào không hợp lệ (43 ngày gốc 02/01–05/03/2019). Nhóm không forward-fill để cứu số dòng này.

## 1.3. Mốc tham chiếu và champion

### Hai mốc

- **Naive (return = 0):** làm mẫu số cho `mae_ratio_vs_naive`.
- **`baseline-q252`:** với mỗi h, lấy 7 phân vị thực nghiệm của các log return h phiên **đã hoàn tất** trong 252 phiên gần nhất. Return đã hoàn tất nghĩa là ngày đích ≤ ngày gốc.
  - Cần ít nhất 200 return hợp lệ trong cửa sổ; thiếu thì điểm đó bị loại khỏi tập đánh giá chung của mọi mô hình.
  - Có test kiểm kết quả tại `t` không đổi khi sửa hoặc nối thêm giá sau `t`.
  - Không huấn luyện, không có tham số phải chọn.

### Vì sao `baseline-q252` là champion

- **Rất khó vượt** với dữ liệu chỉ có giá ở kỳ hạn 1–7 phiên. Chiều của return ngắn hạn gần như không dự đoán được, nên giá trị chính của một dự báo phân vị nằm ở **độ rộng** khoảng. Mốc 252 phiên nắm đúng độ rộng phân phối gần đây.
- **Hệ quả cần nói rõ khi trình bày:** trung vị của mốc là trung vị return 252 phiên qua. Chiều "nghiêng tăng/nghiêng giảm" trên web phản ánh xu hướng 252 phiên đã qua, không phải dự đoán từ thông tin mới. Vì vậy web và chatbot ghi "Mốc thống kê 252 phiên", không gọi là mô hình dự báo.

### Đang chạy trong sản phẩm

- `MODEL_VERSIONS[asset] = "baseline-q252"` cho gold, silver, brent, wti (ADR-0012 mục 3).
- Lambda `predict` là container ECR, chỉ cần NumPy (1024 MB, 120 giây, retry 0). Hàm này chạy sau `ingest` qua Lambda destination và ghi DynamoDB `Forecasts` có điều kiện (PR #48).
- `predict` không lùi ngày khi thiếu phiên mới nhất. Tài sản thiếu phiên bị bỏ qua và báo alarm.

## 1.4. Các hướng mô hình đã thử

### Quy trình chung

- **Kế hoạch trước khi chạy:** mỗi thí nghiệm có kế hoạch commit trước khi chạy, gồm ứng viên, lưới tham số, tiêu chí đạt và điều kiện dừng.
- **Tiêu chí đạt:** một tài sản đạt khi **cận dưới CI 95% của `pinball_skill` trung bình 7 h > 0**. CI tính bằng block bootstrap, block 20, 1000 lần ([ADR-0009](../adr/0009-ceemdan-dlinear-k3-result.md) mục 4).
- **Đếm số lần dùng validation:** mỗi lần nhìn vào 2019 đều được đếm. Đến K4 là 4 lần, 13 cấu hình.

### Kết quả trên validation 2019

`pinball_skill` tính theo điểm %, trung bình 28 nhóm (4 tài sản × 7 h, mẫu `all`). Dương là tốt hơn mốc 252 phiên.

| Thí nghiệm | Ý tưởng | Cấu hình xem trên 2019 | Kết quả | Kết luận |
|---|---|---|---|---|
| DLinear MVP (PR #26) | DLinear, cửa sổ 60, chỉ dùng giá | 1 | −10,17 (vàng −13,80; bạc −15,65; Brent −6,23; WTI −4,99); âm ở 28/28 nhóm | Không đạt |
| K3 ([ADR-0009](../adr/0009-ceemdan-dlinear-k3-result.md)) | CEEMDAN nhân quả theo cửa sổ + DLinear, đầu ra neo vào mốc 252 phiên | 8 | −2,53 (tốt nhất `w252-k3-l30`; cả 8 cấu hình âm) | Không đạt; 0/42 nhóm có cận dưới CI > 0 |
| K3b ([ADR-0010](../adr/0010-k3b-volatility-scaling-result.md)) | Co giãn khoảng của mốc theo biến động gần đây | 3 | −0,32 (S1a, λ = 0,94) | Không đạt; S1a thành challenger |
| K4 ([ADR-0012](../adr/0012-k4-fhs-gjr-result.md)) | GJR-GARCH(1,1) Student-t + mô phỏng lịch sử có lọc (FHS) | 1 | +1,25, CI [−0,67; +3,40] | Không đạt; CI của cả 4 tài sản chứa 0 |

- **Tập điểm chung:** DLinear MVP, K3 và K4 tính trên tập vàng 245, bạc 245, Brent 202, WTI 202 ngày gốc. Số của DLinear MVP lấy từ bảng so sánh ở [kết quả K3](../experiments/k3-ceemdan-results-2026-10.md) mục 4, trung bình 7 h của từng tài sản. K3b tính trên tập 245/245/232/232; trên tập K3, S1a ra −0,16.
- **K4 là mô hình gần đạt nhất,** nhưng không tài sản nào qua tiêu chí:

| Tài sản | K4 `fhs-gjr-t-dm` | CI 95% | S1a (cùng tập) |
|---|---|---|---|
| Vàng | +2,06 | [−0,28; +4,55] | +0,34 |
| Bạc | +1,95 | [−2,01; +4,94] | +0,75 |
| Brent | −0,13 | [−2,42; +2,76] | −0,79 |
| WTI | +1,13 | [−1,61; +4,31] | −0,94 |

- **Holm qua 4 tài sản** (một phía): p_holm vàng 0,208, bạc 0,471, Brent 0,540, WTI 0,471; không tài sản nào qua.
- **Thu hẹp khi ra ngoài mẫu chọn:** trung bình 28 nhóm của K4 giảm từ +2,57 trên kiểm định chéo 2016–2018 xuống +1,25 trên 2019.

### Rút ra từ ba thí nghiệm

- **K3 thất bại vì cấu trúc, không vì thiếu tinh chỉnh.** Đầu ra là hàm tuyến tính của các thành phần IMF có dấu, nên độ rộng khoảng không phản ánh được độ lớn biến động gần đây. Mà độ lớn biến động (biến động co cụm) là thứ duy nhất đã biết là dự báo được trong return ngày. Dò thêm kiến trúc trên cùng đặc trưng sẽ không giải quyết được điều này (ADR-0009).
- **K3b và K4 đi đúng hướng đó và tiến gần mốc hơn,** nhưng chưa đủ để CI loại 0.
  - Ở kim loại, phần cải thiện đến từ **độ rộng khoảng**: `coverage_80` của vàng tăng từ 0,73–0,77 (mốc) lên 0,79–0,82 (K4).
  - Ở dầu, S1a thu hẹp khoảng và kém mốc từ h2 trở đi. Một hệ số co giãn chung cho mọi h giả định biến động gần đây kéo dài nguyên vẹn tới h = 7, giả định này có thể sai với dầu (ADR-0010).
- **Không mô hình nào cải thiện được chiều giá.** Trung vị của S1a trùng mốc từng bit. Ở vàng 2019, `sign_accuracy` của K4 (0,42–0,52) còn thấp hơn `up_rate` (0,54–0,60).
- **Quy trình chịu được sự cố.** Lần chạy 2019 đầu tiên của K4 dừng vì lỗi kiểm tra ràng buộc tham số khi chưa có chỉ số nào được tính. Nhóm làm như sau:
  - chẩn đoán chỉ trên dữ liệu ≤ 2018;
  - sửa có review;
  - chạy lại kiểm định chéo, đối chiếu SHA-256 16/16 file;
  - chạy lại 2019 đúng một lần với claim riêng trên S3 (ADR-0012).

### Minh họa: CEEMDAN + LSTM và rò rỉ dữ liệu tương lai

Nhiều bài báo về CEEMDAN + LSTM (ví dụ ý tưởng của Cao, Li, Li 2019) báo độ chính xác rất cao. Nhóm dựng một minh họa để giải thích vì sao kết quả kiểu này không chuyển sang sản phẩm ([PR #83](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/83), [kết quả](../experiments/repl-ceemdan-lstm-results-2026-11.md)).

- **Phạm vi:** chỉ dữ liệu ≤ 2018, đánh giá 2017–2018, h = 1. Siêu tham số đóng băng trước khi chạy. Đây là minh họa phương pháp, không phải thí nghiệm chọn mô hình: không đổi champion, không thêm challenger, không mở lại ADR-0012.
- **Ba biến thể, mỗi biến thể 3 seed, tổng 108 LSTM nhỏ:**
  - **R-full:** tách CEEMDAN một lần trên toàn chuỗi 2012–2018 (cách thường gặp trong các bài báo);
  - **R-causal:** tách theo cửa sổ 252 phiên kết thúc tại ngày gốc, như sản phẩm bắt buộc;
  - **R-raw:** LSTM trên giá gốc, không tách.

| Tài sản | Biến thể | `pinball_skill` so với mốc 252 phiên | Đúng chiều (tỷ lệ tăng thực tế) |
|---|---|---|---|
| Vàng | R-full | +0,48 | 83,6% (53,3%) |
| Vàng | R-causal | −1,20 | 51,0% (53,3%) |
| Bạc | R-full | +0,52 | 85,5% (48,3%) |
| Bạc | R-causal | −0,76 | 50,8% (48,3%) |

`pinball_skill` ở bảng này tính theo tỷ lệ, không phải điểm % như bảng kết quả 2019: +0,48 nghĩa là pinball loss thấp hơn mốc 48%, −1,20 nghĩa là cao hơn mốc 120%.

- **R-full đẹp bất thường:** R-full của vàng và bạc đoán đúng chiều return một ngày 84–86%, cao bất thường so với mọi cấu hình nhân quả nhóm đã chạy. Vì R-full tách CEEMDAN trên cả đoạn chứa ngày cần dự báo, các IMF đã mang thông tin tương lai, nên con số này không thể coi là kết quả dự báo nhân quả. Bản nhân quả R-causal đúng chiều 47–51%, thua cả naive lẫn mốc 252 phiên ở cả 4 tài sản.
- **Cơ chế:** tại cùng ngày gốc, ba IMF tần số cao của hai cách tách gần như là hai đại lượng khác nhau (tương quan 0,07–0,47). Trong bản tách toàn chuỗi, giá trị tại `t` được nội suy bằng cả các điểm sau `t` ([ADR-0001](../adr/0001-causal-ceemdan.md)).
- **Giới hạn khi đọc:**
  - R-full của dầu cũng thua naive, nên kết luận đúng là "đẹp bất thường ở 2/4 tài sản", không phải "luôn thắng".
  - Hai cách tách khác cả việc dùng dữ liệu tương lai lẫn độ dài chuỗi đưa vào CEEMDAN, nên không quy toàn bộ chênh lệch cho rò rỉ.

## 1.5. Champion, challenger và cập nhật mô hình

### Cập nhật mô hình thay cho retrain ([ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md))

- **Cách hiểu lại mục Must "retrain":** proposal đặt mục Must là "retrain hằng tuần" bằng Step Functions, SageMaker AI Training Job và Model Registry. Champion và challenger đều không có tham số học. Vì vậy mục này được hiểu lại thành: mô hình **tự cập nhật mỗi ngày theo cửa sổ trượt nhân quả** trong Lambda predict, cộng chấm champion/challenger tự động.
- **Lợi ích:** không thêm dịch vụ AWS mới, chi phí gần 0, và không phải dựng hạ tầng huấn luyện cho một mô hình không tồn tại.

### Challenger S1a chạy song song

- **Công thức:** S1a giữ trung vị của mốc và co giãn khoảng cách các phân vị quanh trung vị theo `k_t = clip(σ_EWMA / σ_252, 0,5; 2,0)`, với λ = 0,94 (ADR-0010).
- **Cách chạy:** Lambda predict tính S1a cùng lúc với champion, ghi S3 `eval/shadow/s1a-l094/dt=<ngày>/`, không ghi bảng `Forecasts`, nên người dùng không thấy. Code ở PR #53, CDK ở PR #79.
- **Deploy:** ngày 04/11/2026 (image `c61abdd`). Lượt chạy theo lịch đầu tiên là 12:15 UTC cùng ngày. Ba lượt đầu chạy ổn, `Duration` lớn nhất 3,29 giây.

### Đo độ tin cậy trên dữ liệu chạy thật (`rolling_8w`)

- **Cách đo:** job chạy mỗi ngày giao dịch sau lượt predict, chấm các cặp dự báo–thực tế đã có nhãn trong 56 ngày gần nhất, cho cả champion và S1a. Chỉ chấm dự báo có bằng chứng phát hành (Chương 2, Phụ lục A).
- **Hiển thị trên web:** `coverage_80`, `width_80_pct`, `sign_accuracy` luôn kèm `up_rate`, theo từng h. Web chỉ hiện số khi đủ 20 ngày gốc; trước đó hiện "Đang thu thập (n/20)".
- **Trạng thái ngày 12/11:**
  - bảng Accuracy và `GET /accuracy/{asset}` đã deploy (PR #87);
  - job deploy ngày 11/11 với lịch tắt (PR #89), test bổ sung ở PR #115;
  - dry-run 4 tài sản ngày 11/11: không lỗi, không có giá cơ sở bị sửa lại (0/63 mỗi tài sản); cảnh báo `prob_up_mismatch` lệch tối đa 8,5 × 10⁻⁶, do làm tròn 6 chữ số khi ghi DynamoDB, không loại cặp nào (#89);
  - lịch bật bằng PR #118, deploy 12/11; lượt chạy thật đầu tiên 20:45 ngày 12/11: `[CHỜ XÁC NHẬN: Tiến báo ở #89]`.

### Quy tắc đổi champion

- **Điều kiện:** chỉ đổi khi cận dưới CI 95% của `pinball_skill` trung bình 7 h > 0 trên tập đánh giá đã chốt, và mọi lần đổi phải có ADR.
- **Không đổi tự động:** vài tuần dữ liệu chạy thật (khoảng 40 ngày gốc mỗi tài sản sau 8 tuần) đủ để thấy khoảng 80% có phủ gần 80% hay không, nhưng không đủ để đổi champion.
- **Tập test 2020 → nay:** so `baseline-q252` với S1a một lần, chỉ để báo cáo. Kết quả không đổi champion trước 22/11. Kết quả: `[CHỜ SỐ LIỆU: Long chạy 16–22/11, báo ở #88]`.
- **Dừng dò mô hình chỉ dùng giá đến hết dự án** (ADR-0010, ADR-0012). Thí nghiệm dùng tín hiệu ngoài giá nếu có sau này phải có kế hoạch riêng và ghi là lần dùng validation 2019 thứ 5.

## 1.6. So với proposal

| Proposal | Thực tế | Lý do | Bằng chứng |
|---|---|---|---|
| Mô hình chính CEEMDAN + DLinear/LSTM | `baseline-q252`; CEEMDAN + DLinear giữ trong repo để tái lập | K3 âm ở cả 8 cấu hình; minh họa CEEMDAN + LSTM cho thấy kết quả đẹp chỉ có khi tách toàn chuỗi | ADR-0009, PR #83 |
| Retrain hằng tuần bằng Step Functions + SageMaker AI | Cửa sổ trượt hằng ngày + champion/challenger tự động | Champion và challenger không có tham số học | ADR-0011 |
| Tín hiệu ngoài giá (OVX/GVZ, GPR, lịch sự kiện, nhãn tin) làm đặc trưng | Chưa thử | Ưu tiên sản phẩm chạy thật trước đóng băng 22/11; mọi thí nghiệm mới phải nhìn lại 2019 lần thứ 5 | ADR-0012 mục 4 |
| Chế độ nâng cao giải thích theo thành phần IMF | Bỏ | Không mô hình CEEMDAN nào vào sản phẩm, nên predict không tính IMF | ADR-0009 (Hệ quả), ADR-0012 |
| Transformer (PatchTST, Informer) | Không làm | Tư liệu kiến trúc đã xếp ở mức "chỉ khi dư thời gian" vì dễ học thuộc với vài nghìn điểm; các mô hình đơn giản hơn đã không vượt mốc | [Tư liệu kiến trúc](lua-chon-kien-truc-va-mo-hinh.md) mục 2 |
| Đánh giá bằng MASE | `mae_ratio_vs_naive` (không gọi là MASE), chỉ số phụ; chỉ số chính `pinball_skill` | Thống nhất theo phân vị và mốc mạnh | ADR-0008 |

Điểm nên nói rõ khi trình bày: các thay đổi trên là kết quả của thí nghiệm có kế hoạch chốt trước, không phải thiếu tính năng. Ba kết quả âm có kiểm soát (K3, K3b, K4) cho thấy với dữ liệu chỉ có giá ở kỳ hạn 1–7 phiên, mốc phân vị 252 phiên rất khó vượt.

## 1.7. Giới hạn

- **Một năm validation, nhìn nhiều lần:** 2019 yên hơn 2014–2018 và đã được dùng 4 lần với 13 cấu hình. Các điểm ước lượng tốt nhất lạc quan; vì mọi kết luận đều âm nên điều này không đổi quyết định. Tập test là bằng chứng ngoài mẫu duy nhất chưa bị nhìn.
- **Chỉ dùng giá:** mọi mô hình đã thử chỉ dùng chuỗi giá của chính tài sản.
- **Chuỗi đại diện:** vàng và bạc dự báo trên GLD, SLV, không phải giá giao ngay. Dầu dùng hợp đồng gần nhất nên có bước nhảy ngày chuyển hợp đồng.
- **Không phải dữ liệu tại đúng thời điểm (point-in-time):** bản clean là giá tải lại; backtest mô phỏng thời điểm công bố bằng quy tắc, không chứng minh được dữ liệu lịch sử đúng như lúc đó.
- **Nguồn dữ liệu:** yfinance là thư viện không chính thức; README của yfinance nêu API Yahoo Finance chỉ dành cho mục đích cá nhân và nhóm không có giấy phép của Yahoo. Nếu phải dừng nguồn này thì mọi mô hình đều mất dữ liệu cập nhật (ADR-0005 mục 6).
- **Xác suất tăng chưa hiệu chỉnh:** nội suy tuyến tính giữa hai phân vị, kẹp [0,05; 0,95].

## Nguồn

- ADR: [0001](../adr/0001-causal-ceemdan.md), [0002](../adr/0002-return-quantile-target.md), [0005](../adr/0005-price-data-sources.md), [0007](../adr/0007-ceemdan-config-and-cache.md), [0008](../adr/0008-target-quantiles-evaluation.md), [0009](../adr/0009-ceemdan-dlinear-k3-result.md), [0010](../adr/0010-k3b-volatility-scaling-result.md), [0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md), [0012](../adr/0012-k4-fhs-gjr-result.md).
- Thí nghiệm: [EDA giá](../eda/eda-prices-2026-10.md), [phân tích roll](../experiments/roll-analysis-2026-10.md), [K3](../experiments/k3-ceemdan-results-2026-10.md), [K3b](../experiments/k3b-volatility-results-2026-10.md), [kế hoạch K4](../experiments/k4-plan.md), [minh họa CEEMDAN + LSTM](../experiments/repl-ceemdan-lstm-results-2026-11.md), [kế hoạch S1a chạy song song](../experiments/s1a-shadow-plan.md), [kế hoạch test2020](../experiments/test2020-plan.md).
- PR: #26 (DLinear MVP), #48 (predict ghi có điều kiện), #53 và #79 (S1a chạy song song), #83 (minh họa CEEMDAN + LSTM), #87, #89, #115 (độ tin cậy chạy thật), #106 (PCHIP không thực hiện).
- Chương liên quan: [Phương pháp đánh giá](phuong-phap-danh-gia.md), [Triển khai và vận hành](trien-khai-van-hanh.md), [Bảo mật và chi phí](security-and-cost.md).
