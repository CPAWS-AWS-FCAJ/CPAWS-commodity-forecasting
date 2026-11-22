# Phương pháp đánh giá mô hình dự báo CPAWS

> Bản cập nhật Chương 2 ngày **16/11/2026**, kế thừa bản đã được duyệt ở PR #130 (mốc 14/11). Giữ nguyên bằng chứng Rolling Accuracy và S1a shadow tại thời điểm kiểm tra; bổ sung kết quả **official test2020 thực hiện một lần ngày 16/11/2026**, đã kiểm toán artifact cục bộ và S3. Kết quả chỉ dùng cho báo cáo cuối kỳ, **không thay đổi champion**.

## 1. Mục tiêu và đối tượng đánh giá

CPAWS đánh giá dự báo vàng, bạc, WTI và Brent ở các kỳ hạn 1–7 **phiên giao dịch**. Thay vì chỉ dự báo một mức giá, hệ thống ước lượng phân phối của lợi suất tương lai bằng bảy phân vị $\mathcal T=\{0{,}05;0{,}10;0{,}25;0{,}50;0{,}75;0{,}90;0{,}95\}$. Trung vị $q_{0.50}$ biểu thị mức dự báo trung tâm; cặp $(q_{0.10},q_{0.90})$ tạo khoảng dự báo danh nghĩa 80%. [ADR-0008](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md).

### 1.1. Target và lịch giao dịch

Với ngày gốc $t$ và kỳ hạn $h$, nhãn dự báo là log return:

$$
r_h(t)=\ln\left(\frac{P(t+h)}{P(t)}\right),\qquad h\in\{1,\ldots,7\}.
$$

$t+h$ là **phiên thứ $h$** sau $t$ theo lịch giao dịch của tài sản, không phải $h$ ngày lịch hoặc $h$ dòng dữ liệu giá còn tồn tại. Vàng dùng GLD, bạc dùng SLV (NYSE); WTI dùng CL=F và Brent dùng BZ=F (CME). GLD/SLV là chuỗi đại diện, không phải giá vàng/bạc giao ngay.

Hai endpoint phải tồn tại, có giá hữu hạn và dương, đồng thời không thuộc tập rejected của đúng tài sản. Không nội suy hoặc lấy trị tuyệt đối để cứu nhãn không hợp lệ. Thiếu giá **giữa** hai endpoint không tự làm target mất hiệu lực nếu hai endpoint hợp lệ; số cặp và số phiên thiếu ở giữa phải được thống kê. Cảnh báo roll của dầu không mặc nhiên đồng nghĩa với endpoint bị loại. [ADR-0008 §1](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md); [Walk-forward Contract §9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

### 1.2. Tại sao không lấy sai số mức giá làm chỉ số chính?

Do mức giá có tính liên tục cao, một dự báo gần giá hiện tại vẫn có thể cho MAE, RMSE hoặc MAPE trên **mức giá** thấp nhưng không chứng minh khả năng dự báo lợi suất. Vì vậy, CPAWS dùng **pinball skill trên log return** so với baseline nhân quả 252 phiên làm tiêu chí chính; các chỉ số về độ phủ, độ rộng, xác suất và chiều biến động là bổ sung. [ADR-0008 §§4–5](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md).

Minh họa trong [PR #83 — CEEMDAN + LSTM](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/83) (tập 2017–2018) cho thấy biến thể **R-full**, tách CEEMDAN trên toàn chuỗi, có sai số mức giá đẹp bất thường ở vàng và bạc; trong khi **R-causal**, chỉ dùng thông tin đến ngày gốc, có pinball skill âm so với baseline-q252 trên cả bốn tài sản. Hai biến thể còn khác độ dài chuỗi dùng để tách, nên không thể quy toàn bộ chênh lệch cho rò rỉ dữ liệu. Thí nghiệm này có vai trò minh họa phương pháp, không phải cơ sở thay champion.

`prob_up` là xác suất tăng **xấp xỉ**, suy ra từ nội suy tuyến tính CDF của bảy phân vị tại 0 rồi giới hạn trong [0,05; 0,95]; nó không mặc nhiên là xác suất đã được hiệu chỉnh. Phân vị được chuẩn hóa một lần khi tạo forecast, evaluator chỉ kiểm tra hợp lệ, không tự sửa nguồn. [ADR-0008 §§2–3](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md).

## 2. Walk-forward và phân chia dữ liệu

Walk-forward đánh giá tuần tự theo thời gian: tại mỗi ngày gốc, dự báo chỉ sử dụng thông tin có thể biết lúc đó; nhãn tương lai được ghép để chấm khi đủ điều kiện. Việc dịch ngày đánh giá về phía trước **không đồng nghĩa** với huấn luyện lại ở từng bước. Trong validation MVP, mô hình và phép chuẩn hóa fit trên train được giữ cố định trong năm 2019. [Walk-forward Contract §§3, 6](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

| **Giai đoạn**   | **Vai trò**                   | **Ràng buộc**                                     |
| --------------- | ----------------------------- | ------------------------------------------------- |
| 2012–2013       | Khởi động đặc trưng/cửa sổ    | Không đưa nhãn ngoài phạm vi train vào huấn luyện |
| 2014–2018       | Train                         | Target train không vượt ranh giới 2018            |
| 2019            | Validation, lựa chọn cấu hình | Không dùng target năm 2020                        |
| 2020–23/10/2026 | Test ngoài mẫu theo #75       | Origin từ 02/01/2020; target cutoff 23/10/2026    |

Random split không phù hợp vì có thể đưa quan sát tương lai hoặc các cửa sổ chồng lấp vào tập huấn luyện. Trường hợp ngày đích vượt giới hạn giai đoạn được loại và đếm riêng, không âm thầm bỏ khỏi báo cáo. [ADR-0008 §7](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md); [Test2020 Plan §2](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

### 2.1. Kiểm soát thời điểm thông tin

Trong đánh giá lịch sử, `backtest_publication_rule` mô phỏng thời điểm có thể công bố của dữ liệu: với chuỗi yfinance, quy tắc là ngày lịch (D+1) lúc 12:00 UTC. Input phải đủ điều kiện phát hành trước hoặc tại thời điểm dự báo giả lập; target phải chỉ sẵn có sau đó. Snapshot clean tải lại không phải dữ liệu point-in-time (PIT) tuyệt đối vì có thể chứa các bản sửa lịch sử. [Walk-forward Contract §5.5](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

Đối với Rolling Accuracy, dự báo phải **thực sự được phát hành**, có bằng chứng `created_at` và `input_snapshot_dt` phù hợp; mô phỏng quy tắc công bố không thay thế được bằng chứng này. Bước sinh forecast và bước đánh giá được tách biệt: evaluator không tự tạo forecast để lấp các ngày thiếu. [Walk-forward Contract §§5, 7](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

### 2.2. Ranh giới sử dụng validation

Validation 2019 đã được sử dụng nhiều lần để lựa chọn cấu hình; theo [kế hoạch #75](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md), các lần thử đã làm suy giảm tính độc lập của kết quả 2019. Vì vậy kết quả validation chỉ là bằng chứng lựa chọn thiết kế. Khả năng tổng quát hóa phải được kiểm tra trên test2020 theo giao thức đã khóa, không tiếp tục điều chỉnh mô hình dựa trên các kết quả test.

## 3. Baseline và challenger trong phép so sánh

**Baseline-q252** lấy bảy phân vị thực nghiệm của các return $h$-phiên **đã hoàn tất** trong cửa sổ 252 phiên tính đến ngày gốc. Cần tối thiểu 200 return hợp lệ; nếu thiếu, cặp đó không được đưa vào common mask. Baseline là mốc so sánh pinball skill và champion được lựa chọn theo các ADR hiện hành. [ADR-0008 §4](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md).

**S1a (`s1a-l094`)** là challenger co giãn độ rộng các phân vị quanh trung vị theo tỷ số biến động ngắn/dài hạn, dùng EWMA $\lambda=0{,}94$ và hệ số $k_t\in[0{,}5;2{,}0]$:

$$
q^{S1a}_{\tau,t,h}=q^{base}_{0.50,t,h}+k_t\left(q^{base}_{\tau,t,h}-q^{base}_{0.50,t,h}\right).
$$

S1a giữ nguyên $q_{0.50}$; trên cùng mẫu, MAE trung vị và sign accuracy phải bằng baseline, còn `prob_up` phải được tính lại từ phân vị mới. Chương này chỉ định nghĩa phép so sánh; kiến trúc mô hình và kết quả validation được trình bày ở mục riêng của báo cáo. [ADR-0010](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0010-k3b-volatility-scaling-result.md); [ADR-0012](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0012-k4-fhs-gjr-result.md).

### 3.1. Trạng thái S1a shadow trong vận hành (cập nhật 14/11)

Từ **04/11/2026**, luồng Lambda predict đã phát hành đồng thời champion `baseline-q252` vào DynamoDB `cpaws-dev-forecasts` và forecast **S1a shadow** (`s1a-l094`) ra `s3://cpaws-dev-lake/eval/shadow/s1a-l094/dt=<ngày chạy UTC>/<asset>.json`. Shadow dùng cùng thông tin đến ngày gốc, giữ trung vị, chỉ co giãn các phân vị ngoài trung vị; nhánh lỗi/cấu hình sai được cô lập, không làm hỏng forecast champion. Đây là **triển khai theo dõi song song**, không phải thay champion hoặc công bố S1a trên API. [Kế hoạch S1a shadow §§3–6, 14–15](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/s1a-shadow-plan.md); [Triển khai và vận hành §3](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/trien-khai-van-hanh.md).

Theo log vận hành ghi trong báo cáo triển khai, ba lượt predict đầu sau khi bật shadow ngày **04–06/11** đều ghi **4/4** artifact shadow, alarm OK; thời lượng lần lượt **3,29 s; 3,25 s; 3,27 s**. Giá trị lớn nhất 3,29 s cao hơn mốc 2,9 s khoảng 0,39 s, dưới ngưỡng tăng 2 giây của kế hoạch; nhóm giữ shadow hoạt động. Đây là bằng chứng deploy/độ ổn định ban đầu, **không phải bằng chứng S1a dự báo tốt hơn**. [Triển khai và vận hành §3](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/trien-khai-van-hanh.md).

Rolling job đọc hai nguồn để tạo báo cáo **paired champion–S1a** trên cùng asset, ngày gốc, horizon, ngày đích và actual; báo cáo shadow lưu riêng dưới `eval/shadow_eval/`, không ghi đè kết quả champion ở DynamoDB và không đi qua `GET /accuracy/{asset}`. Số liệu paired shadow chưa được tổng hợp thành kết luận so sánh trong chương này; kết quả official test2020 được trình bày độc lập tại §9, không dùng số liệu shadow thay thế. [Kế hoạch S1a shadow §§11, 14](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/s1a-shadow-plan.md); [Triển khai và vận hành §9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/trien-khai-van-hanh.md).

## 4. Rolling Accuracy: đánh giá dự báo đã phát hành

`rolling_8w` theo dõi forecast champion đã phát hành thật trong **56 ngày lịch UTC theo `base_date`**, từ $D-55$ đến $D$. Chỉ cặp forecast–actual có eligibility, provenance và nhãn hợp lệ mới được chấm; không backfill forecast lịch sử để lấp cửa sổ. Rolling MVP lưu bốn metric nền (`coverage_80`, `width_80`, `sign_accuracy`, `up_rate`) trên bảy horizon, tổng cộng **28 METRIC rows**. Giá trị overall chỉ được phép hiển thị sau ít nhất **20 distinct base dates** hợp lệ theo quy tắc coverage. [Walk-forward Contract §7](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

Rolling là cơ chế **giám sát hoạt động**, khác validation lịch sử và test2020 dùng để so sánh mô hình. Quy tắc chi tiết về phát hành, `input_snapshot_dt`, cutover, trạng thái hiển thị và lưu trữ nằm tại [Phụ lục A](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/phuong-phap-danh-gia.md#ph%E1%BB%A5-l%E1%BB%A5c-a--rolling-accuracy-rolling_8w).

### 4.1. Bằng chứng chạy thật đầu tiên và đối chiếu API (12–13/11/2026)

Hạ tầng rolling được bật lịch ngày **12/11/2026** ([PR #118](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/118)); job `cpaws-dev-accuracy-daily` chạy theo lịch **13:45 UTC / 20:45 Việt Nam, thứ Ba–thứ Bảy**. Lượt đầu **12/11 lúc 20:45 Việt Nam** báo cáo bốn tài sản `COMPLETED` và đã promote pointer; thời lượng **30,3 s**, dùng tối đa **297/1.024 MB**, alarm OK. Đây là quan sát vận hành, không phải lần chạy test2020. [Triển khai và vận hành §9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/trien-khai-van-hanh.md).

Kiểm tra độc lập ngày **13/11** bằng DynamoDB strong-consistent `GetItem` trên `STATE`/`META`, sau đó đối chiếu API đã xác thực Cognito từ trang Amplify `/accuracy`, xác nhận:

| **Tài sản** | **`run_id` (lượt 12/11)**         | **META**    | **API / Web**           | **`n_base_dates`** | **Cặp coverage hợp lệ / được phủ** |
| ----------- | --------------------------------- | ----------- | ----------------------- | ------------------ | ---------------------------------- |
| Gold        | `2026-11-12-fdcaccb87e4fef07aff2` | `COMPLETED` | HTTP 200 / `collecting` | 9/20               | 42 / 29                            |
| Silver      | `2026-11-12-cdc59ba969e46dd7b776` | `COMPLETED` | HTTP 200 / `collecting` | 9/20               | 42 / 40                            |
| WTI         | `2026-11-12-7d0f56754d73171166e1` | `COMPLETED` | HTTP 200 / `collecting` | 9/20               | 42 / 21                            |
| Brent       | `2026-11-12-c2b627318e68e24737c5` | `COMPLETED` | HTTP 200 / `collecting` | 9/20               | 42 / 19                            |

Trong từng tài sản, `STATE.latest_run_id` khớp `META.run_id` và API `run_id`; `model_version=baseline-q252`, `evaluation_kind=rolling_8w`, `evaluated_at=2026-11-12T13:45:00Z`. Cả bốn response có `overall.coverage_80.n_base_dates=9`, `min_display_base_dates=20`, `display_status=insufficient_data`, `display_value=null`; UI hiển thị **“Đang thu thập (9/20)”** và chỉ công bố counts theo h. Tổng 42 cặp là số cặp qua bảy horizon (**9+8+7+6+5+4+3**), **không** phải 42 ngày cơ sở độc lập. Đây là đối chiếu chuỗi STATE → META → API → UI trên **lượt chạy 12/11**, không chứng minh các lượt tương lai hoặc độ chính xác dài hạn.

Response cũng ghi `issuance_evidence_status=verified_eligible_rows`, `published_count=13`, `missing_count=0` cho mỗi tài sản; đồng thời ghi `schedule_evidence_status=not_audited_mvp`, vì vậy **chưa được coi là audit độc lập đầy đủ lịch phát hành**. Job có cảnh báo `prob_up_mismatch` do sai khác làm tròn (báo cáo vận hành ghi mức tối đa <1e-5); cảnh báo không tự đồng nghĩa forecast bị loại. [Triển khai và vận hành §9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/trien-khai-van-hanh.md); [Walk-forward Contract §7](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

## 5. Chỉ số đánh giá theo ADR-0008

### 5.1. Pinball loss và pinball skill

Với nhãn $y$, dự báo phân vị $q_\tau$ và mức $\tau$, pinball loss là:

$$
L_\tau(y,q)=\max\{\tau(y-q),(\tau-1)(y-q)\},\qquad PL=\frac{1}{n}\sum_{i=1}^{n}\frac{1}{7}\sum_{\tau\in\mathcal T}L_\tau(y_i,q_{i,\tau}).
$$

Chỉ số chính của CPAWS là:

$$
\operatorname{pinball\_skill}=1-\frac{PL_{model}}{PL_{baseline}}.
$$

Hai loss phải được tính trên **cùng common mask**. Skill dương nghĩa tốt hơn baseline, bằng 0 nghĩa tương đương, âm nghĩa kém hơn. Phải lấy **tỷ số của hai mean loss**, không lấy trung bình tỷ số theo từng điểm. Khi mean loss của baseline bằng 0, skill `undefined` thay vì gán bằng 0. Không gộp loss thô qua các tài sản có thang biến động khác nhau để chọn mô hình. [ADR-0008 §5](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md); [Metrics](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/src/eval/metrics.py).

### 5.2. Độ phủ, độ rộng và calibration

Đặt $l_i=q_{i,0.10}$, $u_i=q_{i,0.90}$. Với khoảng danh nghĩa 80%:

$$
\operatorname{coverage}_{80}=\frac{1}{n}\sum_i\mathbf{1}\{l_i\le y_i\le u_i\},\qquad \operatorname{width}_{80}=\frac{1}{n}\sum_i(u_i-l_i).
$$

Coverage gần 80% chỉ có ý nghĩa khi xét cùng width (độ sắc nét): khoảng quá rộng có thể đạt độ phủ cao nhưng ít hữu ích. `interval_score_80` kết hợp cả hai bằng cách phạt các nhãn nằm ngoài khoảng, với $\alpha=0{,}2$:

$$
IS_i=(u_i-l_i)+\frac{2}{\alpha}(l_i-y_i)\mathbf{1}\{y_i<l_i\}+\frac{2}{\alpha}(y_i-u_i)\mathbf{1}\{y_i>u_i\}.
$$

`quantile_hit_rates` là tỷ lệ thực tế $y_i\le q_{i,\tau}$ cho từng $\tau$, dùng để đánh giá calibration. Dẫn xuất `width_80_pct` được tính trên từng cặp trước khi lấy trung bình: $n^{-1}\sum_i100(e^{u_i}-e^{l_i})$, không đổi trực tiếp từ mean width. [ADR-0008 §5](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md).

### 5.3. Xác suất, hướng và sai số trung vị

Brier score đánh giá `prob_up` đối với biến cố $y>0$:

$$
BS=\frac{1}{n}\sum_i\left(p_i-\mathbf{1}\{y_i>0\}\right)^2,\qquad \operatorname{BrierSkill}=1-\frac{BS_{model}}{BS_{reference}}.
$$

Reference chính là tần suất tăng được tính nhân quả trên 252 phiên; mốc xác suất 0,5 được báo bổ sung. `sign_accuracy` tính trên các cặp mà cả return thực và trung vị dự báo khác 0; `up_rate` là tỷ lệ nhãn $y>0$ trên mẫu áp dụng. Vì mẫu số có thể khác nhau, không đồng nhất hai tỷ lệ này. Sai số trung vị so với naive return bằng 0 được trình bày bằng:

$$
\operatorname{mae\_ratio\_vs\_naive}=\frac{\operatorname{mean}|y-q_{0.50}|}{\operatorname{mean}|y|}.
$$

Chỉ số này **không phải MASE** vì mẫu số không lấy thang đo từ train. Các tỷ số có mẫu số 0 phải trả `undefined`. [ADR-0008 §5](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md); [Walk-forward Contract §8](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

### 5.4. Common mask và tính minh bạch mẫu đánh giá

Common mask là giao của các cặp ngày gốc–asset–horizon hợp lệ đối với những mô hình đang so sánh: forecast, target, baseline và cutoff đều phải đạt. Với test2020, mask được xác định **riêng theo asset × h × sample**, không buộc một origin phải đủ cả bảy horizon mới được chấm ở từng h. Tuy nhiên, thống kê tổng hợp $S(a)$ vẫn cần đủ cả bảy horizon. Các lý do loại (forecast thiếu, endpoint lỗi, nhãn chưa có, baseline thiếu, provenance không đạt…) phải được đếm riêng; `undefined` không được thay bằng 0 hoặc NaN trong JSON. [Walk-forward Contract §9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md); [Test2020 Plan §3.1](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

## 6. Kiểm định thống kê và giao thức test2020

### 6.1. Historical validation và walk-forward

Các dự báo nhiều horizon có thể dùng chung dữ liệu tương lai, khiến quan sát phụ thuộc theo thời gian. Historical validation sử dụng block bootstrap với **1.000 lần rút**, block 20 và khoảng tin cậy 95%; replicate phải giữ cặp loss model/baseline trên cùng lịch lấy mẫu. Diebold–Mariano (DM) kiểm định chênh lệch loss ghép cặp bằng phương sai HAC và hiệu chỉnh Harvey–Leybourne–Newbold (HLN). Gia đình Holm dành cho DM lịch sử gồm 28 vị trí (`all`: bốn tài sản × bảy h) và 14 vị trí (`excl_roll`: hai tài sản dầu × bảy h), không loại vị trí undefined chỉ để giảm kích thước họ. [Walk-forward Contract §11](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md); [Accuracy Schema](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/api/accuracy-schema.md).

Chính sách DM calendar-gap amplitude-modulated đã được đặc tả nhưng chưa được tích hợp vào code historical tại mốc tài liệu này; xử lý hiện hành chặn DM cho $h>1$ nếu có khoảng trống phiên bên trong. Không coi chính sách mới là kết quả đã triển khai. [Accuracy Schema](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/api/accuracy-schema.md); [Walk-forward implementation](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/src/eval/walk_forward.py).

### 6.2. Test2020 theo giao thức đã khóa ở #75

Test2020 so sánh **baseline-q252** và **S1a** trên bốn tài sản, bảy horizon, origin từ **02/01/2020 đến 23/10/2026**, target cutoff **23/10/2026**. Runner được triển khai theo [PR #85](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/85) và đã được đóng băng tại commit `a71db84679e806f6ac6ce5d91204ead1ffa89459` trước lần chạy official ngày 16/11/2026. Giao thức chỉ cho phép sử dụng kết quả sau khi khóa snapshot, code và cấu hình, không dùng test để điều chỉnh tham số. [Test2020 Plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

Chỉ số chính theo từng tài sản là **trung bình đều bảy horizon** trên mẫu `all`:

$$
\widehat S(a)=\frac{1}{7}\sum_{h=1}^{7}\left(1-\frac{\overline L_{S1a,a,h}}{\overline L_{base,a,h}}\right).
$$

Nếu thiếu một horizon hoặc mean loss của baseline ở horizon đó bằng 0, $\widehat S(a)$ không xác định. Mặt nạ từng horizon được tính riêng, giữ các cặp hợp lệ của horizon khác. Bất biến $q_{0.50}$ giữa S1a và baseline phải khớp từng bit; trên cùng mask, MAE trung vị và sign accuracy phải bằng nhau. [Test2020 Plan §3](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

Cơ chế suy luận chính là **circular moving-block bootstrap** trên lịch hợp NYSE ∪ CME, một kế hoạch rút ngày dùng chung cho các asset/horizon, **B=2.000, block length=20, CI percentile 95%**. Với mỗi asset × h × sample, cần **ít nhất 20 quan sát hợp lệ** để tính bootstrap theo block 20. Nếu ít hơn, **CI và p-value là `undefined`**, không tạo số thay thế; điểm ước lượng hữu hạn có thể vẫn được lưu khi công thức cho phép. CI/p cho $S(a)$ cũng không xác định nếu bất kỳ horizon bắt buộc nào không đủ điều kiện hoặc replicate không hữu hạn. Các lần rút lặp được giữ nguyên, không bỏ replicate lỗi để làm đẹp khoảng tin cậy.

Bốn kiểm định chính một phía có $H_0:S(a)\le 0$, $H_1:S(a)>0$. P-value bootstrap được **căn giữa theo H0**:

$$
T_b^*(a)=S_b^*(a)-\widehat S(a),\qquad p(a)=\frac{1+\sum_{b=1}^{B}\mathbf{1}\{T_b^*(a)\ge\widehat S(a)\}}{B+1}.
$$

Chỉ kết luận cải thiện ở asset có p sau **Holm trên bốn tài sản** nhỏ hơn 0,05. CI percentile mô tả độ bất định, không thay kiểm định. Các báo cáo theo năm, giai đoạn stress, mẫu dầu `excl_roll`, DM theo horizon và sensitivity block 10/40 là phân tích bổ sung, không dùng để thay kết luận chính của block 20/mẫu `all`. [Test2020 Plan §§3–5, 9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

### 6.3. Kiểm soát lần chạy chính thức

Giao thức yêu cầu đóng băng **snapshot DT/VersionId/SHA-256**, lineage, runner commit sạch, `config_hash`, seed và môi trường; đồng thời kiểm tra provenance rồi tạo S3 conditional claim (`IfNoneMatch="*"`) **trước khi đọc dữ liệu test được bảo vệ**. Nếu lượt chạy lỗi sau khi claim được tạo, phải lưu bằng chứng lỗi và không tự chạy lại. [Test2020 Plan §§2, 5–8](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

Official test2020 đã được thực hiện **duy nhất một lần, ngày 16/11/2026**, theo approval vận hành tại [PR #88](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/88). Các thông tin đã được kiểm tra trước khi chạy:

| **Thành phần**              | **Bằng chứng/giá trị**                                                                  |
| --------------------------- | --------------------------------------------------------------------------------------- |
| Runner commit               | `a71db84679e806f6ac6ce5d91204ead1ffa89459`                                              |
| `config_hash`/protocol hash | `d8e3f59e65bdbb99b5cdec9b93bd0eb4c6be02104432ba1fc5604e6e653b3640`                      |
| Clean snapshot              | `clean/prices/dt=2026-10-31/`                                                           |
| Snapshot objects            | `prices.parquet`, `rejected.parquet`, `quality.json`; 3/3 SHA-256 đã khớp               |
| Official bootstrap          | Seed 7, 2.000 replicates, block length 20                                               |
| Claim S3                    | `s3://cpaws-dev-lake/eval/test2020/claim.json`, ghi lúc **02:01:51 UTC** (09:01:51 ICT) |
| Artifact cuối               | Upload khoảng **02:02:32 UTC** (09:02:32 ICT)                                           |
| Kết quả kiểm toán           | Local verifier **PASS**; SHA-256 local ↔ S3 **PASS** cho 7/7 artifact                   |

Ba tệp snapshot có SHA-256 tương ứng: `prices.parquet` = `49dfc745881a38a07bd40b5f722bb2d3f123a7ea0aa1d197fd12ea1ccc954473`, `rejected.parquet` = `630dbe9889e5d1d0d215c01f8c3a34e951f1a6d3f12bd5ba7fe261484e388f2e`, `quality.json` = `cca4fd293c81028af8948420769638ba5b4c93379be74db7f91d5d6067584f30`. VersionId của từng tệp được ghi theo lineage khóa trong [Test2020 Plan §8.1](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md) và metadata/claim artifact. Không thay thế VersionId bằng đường dẫn snapshot hiện tại.

Bảy artifact chính thức là `claim.json`, `started.json`, `env.txt`, `pairs.parquet`, `summary.json`, `summary.md`, `checksums.json`, được lưu tại `s3://cpaws-dev-lake/eval/test2020/`. Kiểm tra không phát hiện `failure.json`; các artifact hiện diện ở cả local và S3, với checksum trùng khớp. **Kiểm toán toàn vẹn artifact không đồng nghĩa với xác minh đầy đủ point-in-time vintage** của nguồn dữ liệu lịch sử. Chi tiết kết quả và giới hạn được trình bày ở §9.

Kết quả official **chỉ dùng cho báo cáo**; champion hiện hành vẫn là `baseline-q252`. Mọi quyết định promote challenger cần ADR mới, không tự động suy ra từ p-value test2020.

## 7. Giới hạn và tính hợp lệ

### 7.1. Giới hạn khoa học

Validation 2019 đã được dùng nhiều lần để lựa chọn cấu hình nên không còn là kiểm chứng độc lập. Snapshot clean và quy tắc công bố mô phỏng không khôi phục đầy đủ phiên bản dữ liệu PIT ở từng thời điểm. Các horizon chồng lấp và biến động chung giữa các tài sản khiến số cặp lớn hơn số quan sát độc lập thực chất; bootstrap/HAC chỉ xử lý một phần phụ thuộc đó. [Test2020 Plan §0](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md); [Walk-forward Contract §§5.5, 11](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

Dầu có thể gặp giá endpoint không dương, roll và giai đoạn biến động cực đoan; việc loại target không hợp lệ làm thay đổi tập quan sát nên phải báo counts. Ở official test2020, common mask riêng từng asset × h × sample, khiến counts theo horizon và các workflow khác có thể khác nhau; các `n_obs` gộp bảy horizon không đại diện cho số phiên độc lập. **18/42 DM bị `undefined` do `internal_session_gaps`** theo chính sách khóa, không được coi là 18 kết quả không có ý nghĩa thống kê. Coverage cao không tự chứng minh mô hình tốt hơn khi khoảng dự báo quá rộng. Kết quả validation, thí nghiệm minh họa #83 hoặc metric Rolling không thay thế kết quả test2020 chính thức. [ADR-0008](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md); [Test2020 Plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).

### 7.2. Phạm vi kết luận

Kết luận về **lựa chọn mô hình** dựa trên validation và các ADR; bằng chứng **kiểm tra ngoài mẫu có điều kiện** dựa trên official test2020 đã khóa và audit ngày 16/11/2026; còn kết luận về **chất lượng vận hành** dựa vào Rolling Accuracy với provenance hợp lệ. Không chuyển các chỉ số giữa ba phạm vi này thành bằng chứng tương đương. Theo primary test, S1a có cải thiện có ý nghĩa thống kê trên Silver, WTI và Brent, nhưng không đủ bằng chứng với Gold; kết quả không khẳng định ưu thế trên mọi năm, mọi horizon hoặc môi trường PIT được xác minh. Không thay champion nếu chưa có ADR mới.

### 7.3. Trạng thái triển khai có liên quan

Kế hoạch/giao thức đã được review tại [PR #75](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/75) và [PR #88](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/88); runner theo [PR #85](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/85). **Official test2020 hoàn tất ngày 16/11/2026** với một lần chạy, conditional claim, đầy đủ artifact và kiểm toán SHA-256 local/S3 **PASS**. Kết quả đã được báo cáo trên PR #88; số liệu ở §9 lấy từ artifact official đã kiểm toán, không lấy từ validation/shadow.

Bằng chứng Rolling Accuracy 4/4 tài sản và trạng thái `collecting` 9/20 tại **lượt 12/11** được giữ theo mốc kiểm tra ở §4.1, không phải số liệu rolling realtime ngày 16/11. S1a shadow vận hành tách khỏi champion; champion vẫn là `baseline-q252`.

## 8. Tóm tắt phương pháp

CPAWS kết hợp **validation lịch sử** để chọn cấu hình, **test2020 ngoài mẫu** để kiểm chứng khả năng tổng quát hóa sau khi khóa lựa chọn, và **Rolling Accuracy** để theo dõi dự báo đã phát hành. Pinball skill trên common mask là thước đo chính cho so sánh mô hình; các chỉ số coverage, width, xác suất và hướng bổ sung các khía cạnh calibration và sai số. Tại mốc báo cáo này, rolling đã có bằng chứng chạy thật **9/20** ngày cơ sở trên cả bốn tài sản; S1a shadow phát hành độc lập, chưa thay champion; **official test2020 đã hoàn tất và có kết quả/kiểm toán ở §9**, không dùng rolling hoặc shadow để thay cho phép kiểm định ngoài mẫu. Kiểm soát thời điểm thông tin, audit counts, bootstrap/Holm và provenance giới hạn phạm vi kết luận vào những gì dữ liệu và giao thức thực sự hỗ trợ.

## 9. Kết quả test2020 chính thức — official run 16/11/2026

> **Nguồn bằng chứng:** `s3://cpaws-dev-lake/eval/test2020/` (đã audit local/S3, 7/7 artifact khớp SHA-256); thông tin phê duyệt và báo cáo kết quả ở [PR #88](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/88). Đây là **một lượt chạy official duy nhất**. Kết quả chỉ dùng cho báo cáo cuối kỳ; không tự động thay đổi champion và **không phải verified point-in-time backtest** vì historical vintage/revisions chưa được xác minh đầy đủ.

### 9.1. Provenance và bằng chứng toàn vẹn

Các bằng chứng runner commit, protocol/config hash, snapshot và thời điểm claim đã được ghi ở §6.3. Official artifact bao gồm `claim.json`, `started.json`, `env.txt`, `pairs.parquet`, `summary.json`, `summary.md` và `checksums.json`. Hàm `verified_result()` kiểm tra checksum local **PASS**; đối chiếu SHA-256 từ S3 với checksum đã khóa **7/7 PASS**. Không có `failure.json` trong các artifact liệt kê. `run_id` và lineage đầy đủ lấy từ **`claim.json`/`summary.json`**, không suy ra từ tên thư mục hoặc tự đặt lại.

### 9.2. Primary test — trung bình đều bảy horizon

Thống kê S(a) được tính theo §6.2 trên mẫu `all` với bảy horizon đều có trạng thái hợp lệ. Bootstrap **B=2.000, block 20, seed 7**, percentile CI 95% mang tính mô tả; p-value kiểm định một phía được căn giữa theo H0 và điều chỉnh **Holm trên bốn tài sản**. Các giá trị skill/CI được trình bày theo phần trăm (không phải điểm phần trăm giá).

| **Asset** | **S(a)** | **95% percentile CI** | **Holm-adjusted p** | **Kết luận ở α = 0,05** | **Tổng `n_obs` qua 7 h** |
| --------- | ---------------------- | --------------------- | ------------------- | -------------------------------- | ------------------------ |
| Gold      | +0,110%                | [−1,286%; +1,488%]    | 0,420790            | Chưa đủ bằng chứng cải thiện     | 11.956                   |
| Silver    | +2,120%                | [+0,165%; +4,095%]    | 0,038981            | Cải thiện có ý nghĩa             | 11.956                   |
| WTI       | +4,491%                | [+2,023%; +6,726%]    | 0,001999            | Cải thiện có ý nghĩa             | 11.949                   |
| Brent     | +4,213%                | [+1,877%; +6,349%]    | 0,001999            | Cải thiện có ý nghĩa             | 11.963                   |

**Diễn giải:** Theo tiêu chí chính đã khóa, S1a có pinball skill dương và cải thiện có ý nghĩa thống kê trên **Silver, WTI, Brent**; không đủ bằng chứng tương tự với Gold. Các giá trị `n_obs` là **tổng số cặp asset–horizon hợp lệ**, không phải số phiên giao dịch độc lập. Phân tích theo horizon và audit counts chi tiết có trong `summary.json`/`pairs.parquet`; không lấy tổng counts này làm kích thước mẫu độc lập để suy luận.

### 9.3. Sensitivity — circular block 10/20/40

Các phép phân tích bổ sung dưới đây giữ nguyên điểm ước lượng nhưng thay đổi độ dài block bootstrap. **Chỉ block 20 là kiểm định primary đã khóa**; CI block 10/40 không tạo ra quyết định Holm hay chọn lại mô hình.

| **Asset** | **Block 10: CI 95%** | **Block 20: CI 95%** | **Block 40: CI 95%** |
| --------- | -------------------- | -------------------- | -------------------- |
| Gold      | [−1,202%; +1,441%]   | [−1,286%; +1,488%]   | [−1,168%; +1,566%]   |
| Silver    | [+0,412%; +3,708%]   | [+0,165%; +4,095%]   | [−0,144%; +4,542%]   |
| WTI       | [+2,468%; +6,283%]   | [+2,023%; +6,726%]   | [+1,606%; +6,937%]   |
| Brent     | [+2,335%; +6,035%]   | [+1,877%; +6,349%]   | [+1,476%; +6,571%]   |

WTI và Brent giữ cận dưới CI dương ở ba độ dài block, trong khi Silver có CI chứa 0 ở block 40; Gold có CI chứa 0 ở cả ba block. Điều này cho thấy **độ nhạy về bất định**, không thay đổi kết luận chính được báo cáo theo block 20.

### 9.4. DM theo horizon và chính sách calendar-gap

Official tạo **42 vị trí DM**: `all` gồm 4 asset × 7 horizon (28 vị trí) và `excl_roll` gồm WTI/Brent × 7 horizon (14 vị trí). Có **24 vị trí tính được statistic/p-value**, **18 vị trí `undefined_reason=internal_session_gaps`**. Trong 24 vị trí có statistic hợp lệ, **11 vị trí** có p-value Holm nhỏ hơn 0,05:

| **Mẫu**     | **Asset** | **Vị trí DM có p Holm < 0,05** | **Vị trí `undefined`** |
| ----------- | --------- | ------------------------------ | ---------------------- |
| `all`       | Gold      | h=1                            | 0                      |
| `all`       | Silver    | h=1–2                          | 0                      |
| `all`       | WTI       | h=1                            | h=2–7                  |
| `all`       | Brent     | h=1–5                          | 0                      |
| `excl_roll` | WTI       | h=1                            | h=2–7                  |
| `excl_roll` | Brent     | h=1                            | h=2–7                  |

Các DM thiếu giá trị ở h>1 phải để **`undefined`**, không tự nối các phiên bị thiếu, không thay bằng 0 và không giảm số vị trí của gia đình Holm chỉ vì gặp gap. P-value in `0,000000` do làm tròn **không** có nghĩa p bằng 0. DM là phân tích bổ sung; dấu statistic phải được diễn giải đúng theo định nghĩa loss differential trong code, và **không thay thế primary S(a)**.

### 9.5. Theo năm và các giai đoạn stress

Bảng sau là **trung bình số học của các skill tính riêng cho h=1…7 trong từng giai đoạn**, không phải tái tạo S(a) toàn kỳ, không kèm kiểm định Holm riêng theo năm. Chỉ trình bày các asset đủ bảy horizon hợp lệ trong mỗi giai đoạn.

| **Năm**              | **Gold** | **Silver** | **WTI**  | **Brent** |
| -------------------- | -------- | ---------- | -------- | --------- |
| 2020                 | +1,966%  | +2,338%    | +10,345% | +9,658%   |
| 2021                 | −1,034%  | +0,331%    | +4,245%  | +3,068%   |
| 2022                 | −0,367%  | −0,926%    | +1,801%  | +2,552%   |
| 2023                 | −1,136%  | −1,899%    | −0,272%  | −0,130%   |
| 2024                 | −1,103%  | −0,451%    | +0,732%  | −0,016%   |
| 2025                 | −0,121%  | +2,810%    | −0,242%  | −0,920%   |
| 2026 (chưa trọn năm) | +1,114%  | +7,419%    | +4,301%  | +5,458%   |

| **Stress period** | **Gold** | **Silver** | **WTI**  | **Brent** |
| ----------------- | -------- | ---------- | -------- | --------- |
| COVID             | +7,999%  | +5,140%    | +11,653% | +11,619%  |
| Russia–Ukraine    | +0,521%  | −2,159%    | +7,411%  | +9,193%   |

Năm 2020 có skill dương trên bốn tài sản, đặc biệt WTI/Brent; ngược lại năm 2023 skill âm trên cả bốn. Hai chuỗi dầu có skill dương trong cả hai stress period theo **định nghĩa cửa sổ đã khóa trong kế hoạch/runner**. Đây là các mô tả về tính không đồng nhất theo thời gian; không chứng minh quan hệ nhân quả hoặc ưu thế bền vững trong mọi khủng hoảng. Không lấy trung bình các năm để thay thế kết quả primary toàn kỳ.

### 9.6. Audit mẫu, giới hạn và quyết định champion

Common mask được xác định riêng theo **asset × horizon × sample**. Một origin thiếu một horizon có thể vẫn hợp lệ ở horizon khác, nhưng primary S(a) yêu cầu đủ bảy horizon ở cấp tổng hợp. Các số đếm theo từng loại loại trừ (`endpoint`, `cutoff`, dữ liệu thiếu, provenance, roll, gap…) và các chỉ số phụ (`coverage_80`, `width_80`, Brier, `sign_accuracy`, `mae_ratio_vs_naive`) phải tham chiếu **các record gốc trong `summary.json`/`pairs.parquet`**; phần tóm tắt này không bịa thêm bảng counts hoặc xác nhận invariants chưa được trích xuất riêng.

Kết quả không loại bỏ các giới hạn về **historical vintage/revisions chưa xác minh đầy đủ**, horizon phụ thuộc, lỗi endpoint/roll dầu và DM gaps; dữ liệu không đủ để gọi là verified PIT backtest hoặc để suy rộng thắng lợi trên tất cả thời kỳ. Kết quả này **chỉ phục vụ báo cáo cuối kỳ (reporting-only)**; champion tiếp tục là **`baseline-q252`**, S1a vẫn là challenger/shadow. Mọi thay đổi champion sau đó cần **ADR mới**; không chạy lại official để tối ưu theo test.

**Bằng chứng gốc để đối chiếu:** [Test2020 Plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md), [PR #88](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/88), `s3://cpaws-dev-lake/eval/test2020/` (`claim.json`, `summary.json`, `summary.md`, `pairs.parquet`, `checksums.json`).

---

# Phụ lục A — Rolling Accuracy `rolling_8w`

Phụ lục này trình bày chi tiết nghiệp vụ Rolling API; phần chính chỉ nêu vai trò giám sát và bộ metric nền. [Walk-forward Contract §7 v4.6](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

## A.1. Cửa sổ và lịch chạy

Với ngày chạy UTC $D$, cửa sổ theo `base_date` là **[D−55 ngày, D]**, gồm hai biên và có 56 ngày lịch, không phải 56 phiên. `evaluation_kind=rolling_8w`, `sample=all`; không rút ngắn cửa sổ theo bản ghi đầu tiên. Lịch `cpaws-dev-accuracy-daily` **đã bật từ 12/11**, đánh giá TUE–SAT lúc 13:45 UTC (20:45 Việt Nam), sau ingest/predict lúc 12:15 UTC. Target cutoff được xác định riêng theo asset và thời điểm sẵn có của actual. [Triển khai và vận hành §9](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/trien-khai-van-hanh.md).

## A.2. Điều kiện phát hành và provenance

Forecast chỉ được chấm khi đúng asset/target series/champion và ngày hiệu lực, không phải sample/backfill, đủ bảy phân vị hữu hạn không giảm và xác suất trong miền quy định. `created_at` phải từ **27/10/2026 12:00 UTC** và trước 13:30 UTC của ngày target cho từng h; record còn phải thỏa input-as-of. Sai lệch `prob_up` nội suy quá 1e−6 chỉ được audit, không tự loại nếu các điều kiện cấu trúc khác đạt.

**Effective base date ban đầu 26/10/2026** khác với **eligibility bắt đầu 27/10 12:00 UTC** và **cutover Predict #48 ngày 30/10/2026 08:10:06 UTC**. Sau cutover, record cần bằng chứng conditional write và `input_snapshot_dt` trỏ đúng snapshot đã dùng. Record legacy chỉ được phép vào mẫu theo `LEGACY_ACCEPT_WITH_EVIDENCE` và approval riêng; record sau cutover thiếu snapshot không được chuyển thành legacy để bỏ qua gate. Việc có timestamp phù hợp không tự chứng minh dữ liệu thực sự có sẵn ở thời điểm dự báo.

Lịch expected chỉ đo các kỳ dự kiến; trong cùng phạm vi, `expected = published + missing`. Một kỳ có record chưa chắc eligible, một kỳ thiếu record chưa chắc là thất bại của mô hình. Rolling không tạo forecast backfill. [Walk-forward Contract §§7.2–7.3](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

## A.3. Metric, aggregation và display gate

Bốn metric nền `coverage_80`, `width_80`, `sign_accuracy`, `up_rate` nhân với bảy horizon tạo **28 METRIC rows**. `width_80_pct` là dẫn xuất tính từng cặp và lưu trong metadata, không phải metric row thứ 29; overall cũng thuộc META, không phải horizon 0.

Overall coverage = tổng số cặp được phủ / tổng số cặp coverage hợp lệ trên bảy h. Width, width_pct, sign và up gộp theo các counts tương ứng, không lấy trung bình ngang các tỷ lệ horizon. `n_obs` là số cặp thực vào công thức; `distinct_base_dates` là hợp các ngày gốc có coverage hợp lệ, không phải tổng n ngày của từng h.

Giá trị overall chỉ hiển thị sau **ít nhất 20 distinct base dates** có coverage hợp lệ, áp dụng chung cho mọi metric nền và dẫn xuất. Trước ngưỡng, giá trị nội bộ có thể được tính nhưng `display_value` overall là `null`; tại từng horizon chỉ công bố counts (`counts_only`).

| **Tình huống**                              | **Trạng thái / cách hiển thị**                                       |
| ------------------------------------------- | -------------------------------------------------------------------- |
| Chưa có completed run đúng champion         | `data_status=not_ready`                                              |
| Completed nhưng dưới 20 distinct base dates | `data_status=collecting`, overall `display_status=insufficient_data` |
| Đạt ngưỡng, metric xác định                 | `data_status=ready`, metric `status=ok`, `display_status=ready`      |
| Đạt ngưỡng, metric không tính được          | `status=undefined`, `display_status=undefined`, giá trị `null`       |
| Mỗi horizon                                 | `display_status=counts_only`                                         |

`COMPLETED` là trạng thái xử lý, khác trạng thái thống kê/hiển thị. Run đủ điều kiện cấu hình và evidence vẫn có thể COMPLETED với 28 hàng undefined nếu không có cặp eligible; thiếu provenance configuration hoặc snapshot/actual chưa READY phải chặn publication. [Walk-forward Contract §§7.4–7.5](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md); [Rolling Accuracy](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/src/eval/rolling_accuracy.py).

## A.4. Lưu trữ và đối chiếu shadow

Run lưu định danh snapshot, config, evidence và hash. Sau khi kiểm đủ 28 METRIC rows và META nhất quán mới cập nhật pointer tới run đã hoàn tất qua `STATE.latest_run_pk`/`STATE.latest_run_id` (khái niệm latest completed run); retry không được ghi đè payload khác. Hash bảo vệ tính toàn vẹn artifact, không thay chứng cứ thời điểm phát hành. Bằng chứng ngày 13/11 đã đối chiếu các trường `STATE`/`META` này với `run_id` của API cho cả bốn tài sản (§4.1). [Rolling Store](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/src/eval/rolling_store.py).

Shadow S1a đối chiếu champion theo cùng asset, base_date, h, target_date, target series và actual. Artifact shadow thiếu không làm champion không hợp lệ; báo cáo paired lưu riêng và không thay pointer/API của champion. Nếu nhiều object cùng base_date, không được tùy chọn một bản theo tên file rồi coi là duy nhất. [Walk-forward Contract §7.6](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md).

## A.5. Phạm vi kiểm chứng thực tế tại mốc 12/11

Khi job đã `COMPLETED`, không đồng nghĩa với trạng thái hiển thị `ready`. Lượt 12/11 có 9 distinct base dates hợp lệ và 42 cặp đã chấm cho mỗi tài sản; API vì thế trả `collecting`, còn các thống kê overall để `display_value=null` dù có giá trị nội bộ. Các counts theo từng h (9, 8, 7, 6, 5, 4, 3) được hiển thị trên trang `/accuracy`, không dùng để công bố độ chính xác chính thức khi chưa đạt ngưỡng. Bằng chứng đối chiếu ghi ở §4.1; số liệu là ảnh chụp của **một lượt chạy**, không phải dữ liệu cố định của mọi ngày.

**Giới hạn:** kiểm tra đã đối chiếu STATE/META/API/Web và các count được công bố; chưa tự chứng nhận toàn bộ hash/replay của 28 METRIC rows hoặc audit riêng lịch expected (`schedule_evidence_status=not_audited_mvp`). Quyền IAM của người kiểm tra không cho phép trực tiếp `lambda:InvokeFunction`, nên API được kiểm qua luồng Cognito/API Gateway từ web. Không cấp thêm IAM, không ghi dữ liệu hoặc chạy job lại để phục vụ việc đối chiếu.

---

# Phụ lục B — Khác biệt giữa các thế hệ tài liệu

Bảng dưới đây lưu dấu vết quyết định để tránh diễn giải nhầm những phiên bản tài liệu trước đó như giao thức đang áp dụng.

| **Nội dung từ tài liệu cũ**                               | **Quy tắc sử dụng trong chương này**                                                                          |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Bản mô tả ban đầu (K8) lấy MASE/sai số mức giá làm trọng tâm | Dùng `pinball_skill` trên log return theo ADR-0008; MASE không phải chỉ số chính                              |
| Tài liệu kiến trúc cũ mô tả hạ tầng retrain               | ADR-0011/0012 chốt so sánh champion/challenger trong phạm vi MVP; không suy ra SageMaker retraining đang chạy |
| Accuracy Schema có đoạn Rolling dạng đề xuất              | Walk-forward Contract §7 v4.6 xác định cửa sổ, provenance, 28 rows và display gate                            |
| DM calendar gaps đã có chính sách mới trong schema        | Chưa coi amplitude-modulated là implementation hiện hành; tiếp tục báo giới hạn DM gap                        |
| Bootstrap historical và test2020 khác tham số             | Historical: B=1.000; test2020: B=2.000 và Holm bốn tài sản                                                    |

Nguồn: [tài liệu kiến trúc trước đây](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/defense/lua-chon-kien-truc-va-mo-hinh.md), [ADR-0008](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0008-target-quantiles-evaluation.md), [ADR-0011](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0011-weekly-champion-challenger-instead-of-retrain.md), [ADR-0012](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/adr/0012-k4-fhs-gjr-result.md), [Accuracy Schema](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/api/accuracy-schema.md), [Walk-forward Contract](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/eval/walk-forward-contract.md), [Test2020 Plan](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/blob/developer/docs/experiments/test2020-plan.md).
