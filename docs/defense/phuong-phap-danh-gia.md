# Phương pháp đánh giá mô hình dự báo CPAWS

> Bản nháp chương phương pháp đánh giá cho báo cáo bảo vệ, cập nhật ngày 04/11/2026. Các kết quả ngoài mẫu của test2020 chỉ được bổ sung sau lần chạy chính thức theo giao thức đã khóa.

## 1. Mục tiêu và đối tượng đánh giá

CPAWS đánh giá dự báo vàng, bạc, WTI và Brent ở các kỳ hạn 1–7 **phiên giao dịch**. Thay vì chỉ dự báo một mức giá, hệ thống ước lượng phân phối của lợi suất tương lai bằng bảy phân vị \(\mathcal T=\{0{,}05;0{,}10;0{,}25;0{,}50;0{,}75;0{,}90;0{,}95\}\). Trung vị \(q_{0.50}\) biểu thị mức dự báo trung tâm; cặp \(q_{0.10},q_{0.90}\) tạo khoảng dự báo danh nghĩa 80%. [ADR-0008](../adr/0008-target-quantiles-evaluation.md).

### 1.1. Target và lịch giao dịch

Với ngày gốc \(t\) và kỳ hạn \(h\), nhãn dự báo là log return:

\[
r_h(t)=\ln\left(\frac{P(t+h)}{P(t)}\right),\qquad h\in\{1,\ldots,7\}.
\]

\(t+h\) là **phiên thứ \(h\)** sau \(t\) theo lịch giao dịch của tài sản, không phải \(h\) ngày lịch hoặc \(h\) dòng dữ liệu giá còn tồn tại. Vàng dùng GLD, bạc dùng SLV (NYSE); WTI dùng CL=F và Brent dùng BZ=F (CME). GLD/SLV là chuỗi đại diện, không phải giá vàng/bạc giao ngay.

Hai endpoint phải tồn tại, có giá hữu hạn và dương, đồng thời không thuộc tập rejected của đúng tài sản. Không nội suy hoặc lấy trị tuyệt đối để cứu nhãn không hợp lệ. Thiếu giá **giữa** hai endpoint không tự làm target mất hiệu lực nếu hai endpoint hợp lệ; số cặp và số phiên thiếu ở giữa phải được thống kê. Cảnh báo roll của dầu không mặc nhiên đồng nghĩa với endpoint bị loại. [ADR-0008 §1](../adr/0008-target-quantiles-evaluation.md); [Walk-forward Contract §9](../eval/walk-forward-contract.md).

### 1.2. Tại sao không lấy sai số mức giá làm chỉ số chính?

Do mức giá có tính liên tục cao, một dự báo gần giá hiện tại vẫn có thể cho MAE, RMSE hoặc MAPE trên **mức giá** thấp nhưng không chứng minh khả năng dự báo lợi suất. Vì vậy, CPAWS dùng **pinball skill trên log return** so với baseline nhân quả 252 phiên làm tiêu chí chính; các chỉ số về độ phủ, độ rộng, xác suất và chiều biến động là bổ sung. [ADR-0008 §§4–5](../adr/0008-target-quantiles-evaluation.md).

Minh họa trong [PR #83 — CEEMDAN + LSTM](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/83) (tập 2017–2018) cho thấy biến thể **R-full**, tách CEEMDAN trên toàn chuỗi, có sai số mức giá đẹp bất thường ở vàng và bạc; trong khi **R-causal**, chỉ dùng thông tin đến ngày gốc, có pinball skill âm so với baseline-q252 trên cả bốn tài sản. Hai biến thể còn khác độ dài chuỗi dùng để tách, nên không thể quy toàn bộ chênh lệch cho rò rỉ dữ liệu. Thí nghiệm này có vai trò minh họa phương pháp, không phải cơ sở thay champion.

`prob_up` là xác suất tăng **xấp xỉ**, suy ra từ nội suy tuyến tính CDF của bảy phân vị tại 0 rồi giới hạn trong [0,05; 0,95]; nó không mặc nhiên là xác suất đã được hiệu chỉnh. Phân vị được chuẩn hóa một lần khi tạo forecast, evaluator chỉ kiểm tra hợp lệ, không tự sửa nguồn. [ADR-0008 §§2–3](../adr/0008-target-quantiles-evaluation.md).

## 2. Walk-forward và phân chia dữ liệu

Walk-forward đánh giá tuần tự theo thời gian: tại mỗi ngày gốc, dự báo chỉ sử dụng thông tin có thể biết lúc đó; nhãn tương lai được ghép để chấm khi đủ điều kiện. Việc dịch ngày đánh giá về phía trước **không đồng nghĩa** với huấn luyện lại ở từng bước. Trong validation MVP, mô hình và phép chuẩn hóa fit trên train được giữ cố định trong năm 2019. [Walk-forward Contract §§3, 6](../eval/walk-forward-contract.md).

| Giai đoạn | Vai trò | Ràng buộc |
|---|---|---|
| 2012–2013 | Khởi động đặc trưng/cửa sổ | Không đưa nhãn ngoài phạm vi train vào huấn luyện |
| 2014–2018 | Train | Target train không vượt ranh giới 2018 |
| 2019 | Validation, lựa chọn cấu hình | Không dùng target năm 2020 |
| 2020–23/10/2026 | Test ngoài mẫu theo #75 | Origin từ 02/01/2020; target cutoff 23/10/2026 |

Random split không phù hợp vì có thể đưa quan sát tương lai hoặc các cửa sổ chồng lấp vào tập huấn luyện. Trường hợp ngày đích vượt giới hạn giai đoạn được loại và đếm riêng, không âm thầm bỏ khỏi báo cáo. [ADR-0008 §7](../adr/0008-target-quantiles-evaluation.md); [Test2020 Plan §2](../experiments/test2020-plan.md).

### 2.1. Kiểm soát thời điểm thông tin

Trong đánh giá lịch sử, `backtest_publication_rule` mô phỏng thời điểm có thể công bố của dữ liệu: với chuỗi yfinance, quy tắc là ngày lịch \(D+1\) lúc 12:00 UTC. Input phải đủ điều kiện phát hành trước hoặc tại thời điểm dự báo giả lập; target phải chỉ sẵn có sau đó. Snapshot clean tải lại không phải dữ liệu point-in-time (PIT) tuyệt đối vì có thể chứa các bản sửa lịch sử. [Walk-forward Contract §5.5](../eval/walk-forward-contract.md).

Đối với Rolling Accuracy, dự báo phải **thực sự được phát hành**, có bằng chứng `created_at` và `input_snapshot_dt` phù hợp; mô phỏng quy tắc công bố không thay thế được bằng chứng này. Bước sinh forecast và bước đánh giá được tách biệt: evaluator không tự tạo forecast để lấp các ngày thiếu. [Walk-forward Contract §§5, 7](../eval/walk-forward-contract.md).

### 2.2. Ranh giới sử dụng validation

Validation 2019 đã được sử dụng nhiều lần để lựa chọn cấu hình; theo [kế hoạch #75](../experiments/test2020-plan.md), các lần thử đã làm suy giảm tính độc lập của kết quả 2019. Vì vậy kết quả validation chỉ là bằng chứng lựa chọn thiết kế. Khả năng tổng quát hóa phải được kiểm tra trên test2020 theo giao thức đã khóa, không tiếp tục điều chỉnh mô hình dựa trên các kết quả test.

## 3. Baseline và challenger trong phép so sánh

**Baseline-q252** lấy bảy phân vị thực nghiệm của các return \(h\)-phiên **đã hoàn tất** trong cửa sổ 252 phiên tính đến ngày gốc. Cần tối thiểu 200 return hợp lệ; nếu thiếu, cặp đó không được đưa vào common mask. Baseline là mốc so sánh pinball skill và champion được lựa chọn theo các ADR hiện hành. [ADR-0008 §4](../adr/0008-target-quantiles-evaluation.md).

**S1a (`s1a-l094`)** là challenger co giãn độ rộng các phân vị quanh trung vị theo tỷ số biến động ngắn/dài hạn, dùng EWMA \(\lambda=0{,}94\) và hệ số \(k_t\in[0{,}5;2{,}0]\):

\[
q^{S1a}_{\tau,t,h}=q^{base}_{0.50,t,h}
+k_t\big(q^{base}_{\tau,t,h}-q^{base}_{0.50,t,h}\big).
\]

S1a giữ nguyên \(q_{0.50}\); trên cùng mẫu, MAE trung vị và sign accuracy phải bằng baseline, còn `prob_up` phải được tính lại từ phân vị mới. Chương này chỉ định nghĩa phép so sánh; kiến trúc mô hình và kết quả validation được trình bày ở mục riêng của báo cáo. [ADR-0010](../adr/0010-k3b-volatility-scaling-result.md); [ADR-0012](../adr/0012-k4-fhs-gjr-result.md).

## 4. Rolling Accuracy: đánh giá dự báo đã phát hành

`rolling_8w` theo dõi forecast champion đã phát hành thật trong **56 ngày lịch UTC theo `base_date`**, từ \(D-55\) đến \(D\). Chỉ cặp forecast–actual có eligibility, provenance và nhãn hợp lệ mới được chấm; không backfill forecast lịch sử để lấp cửa sổ. Rolling MVP lưu bốn metric nền (`coverage_80`, `width_80`, `sign_accuracy`, `up_rate`) trên bảy horizon, tổng cộng **28 METRIC rows**. Giá trị overall chỉ được phép hiển thị sau ít nhất **20 distinct base dates** hợp lệ theo quy tắc coverage. [Walk-forward Contract §7](../eval/walk-forward-contract.md).

Rolling là cơ chế **giám sát hoạt động**, khác validation lịch sử và test2020 dùng để so sánh mô hình. Quy tắc chi tiết về phát hành, `input_snapshot_dt`, cutover, trạng thái hiển thị và lưu trữ nằm tại [Phụ lục A](#phụ-lục-a--rolling-accuracy-rolling_8w). 

## 5. Chỉ số đánh giá theo ADR-0008

### 5.1. Pinball loss và pinball skill

Với nhãn \(y\), dự báo phân vị \(q_\tau\) và mức \(\tau\), pinball loss là:

\[
L_\tau(y,q)=\max\{\tau(y-q),(\tau-1)(y-q)\},\qquad
PL=\frac1n\sum_{i=1}^{n}\frac17\sum_{\tau\in\mathcal T}L_\tau(y_i,q_{i,\tau}).
\]

Chỉ số chính của CPAWS là:

\[
\operatorname{pinball\_skill}=1-\frac{PL_{model}}{PL_{baseline}}.
\]

Hai loss phải được tính trên **cùng common mask**. Skill dương nghĩa tốt hơn baseline, bằng 0 nghĩa tương đương, âm nghĩa kém hơn. Phải lấy **tỷ số của hai mean loss**, không lấy trung bình tỷ số theo từng điểm. Khi mean loss của baseline bằng 0, skill `undefined` thay vì gán bằng 0. Không gộp loss thô qua các tài sản có thang biến động khác nhau để chọn mô hình. [ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md); [Metrics](../../src/eval/metrics.py).

### 5.2. Độ phủ, độ rộng và calibration

Đặt \(l_i=q_{i,0.10}\), \(u_i=q_{i,0.90}\). Với khoảng danh nghĩa 80%:

\[
\operatorname{coverage}_{80}=\frac1n\sum_i\mathbf1\{l_i\le y_i\le u_i\},\qquad
\operatorname{width}_{80}=\frac1n\sum_i(u_i-l_i).
\]

Coverage gần 80% chỉ có ý nghĩa khi xét cùng width (độ sắc nét): khoảng quá rộng có thể đạt độ phủ cao nhưng ít hữu ích. `interval_score_80` kết hợp cả hai bằng cách phạt các nhãn nằm ngoài khoảng, với \(\alpha=0{,}2\):

\[
IS_i=(u_i-l_i)+\frac2\alpha(l_i-y_i)\mathbf1\{y_i<l_i\}
+\frac2\alpha(y_i-u_i)\mathbf1\{y_i>u_i\}.
\]

`quantile_hit_rates` là tỷ lệ thực tế \(y_i\le q_{i,\tau}\) cho từng \(\tau\), dùng để đánh giá calibration. Dẫn xuất `width_80_pct` được tính trên từng cặp trước khi lấy trung bình: \(n^{-1}\sum_i100(e^{u_i}-e^{l_i})\), không đổi trực tiếp từ mean width. [ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md).

### 5.3. Xác suất, hướng và sai số trung vị

Brier score đánh giá `prob_up` đối với biến cố \(y>0\):

\[
BS=\frac1n\sum_i\big(p_i-\mathbf1\{y_i>0\}\big)^2,\qquad
\operatorname{BrierSkill}=1-\frac{BS_{model}}{BS_{reference}}.
\]

Reference chính là tần suất tăng được tính nhân quả trên 252 phiên; mốc xác suất 0,5 được báo bổ sung. `sign_accuracy` tính trên các cặp mà cả return thực và trung vị dự báo khác 0; `up_rate` là tỷ lệ nhãn \(y>0\) trên mẫu áp dụng. Vì mẫu số có thể khác nhau, không đồng nhất hai tỷ lệ này. Sai số trung vị so với naive return bằng 0 được trình bày bằng:

\[
\operatorname{mae\_ratio\_vs\_naive}=
\frac{\operatorname{mean}|y-q_{0.50}|}{\operatorname{mean}|y|}.
\]

Chỉ số này **không phải MASE** vì mẫu số không lấy thang đo từ train. Các tỷ số có mẫu số 0 phải trả `undefined`. [ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md); [Walk-forward Contract §8](../eval/walk-forward-contract.md).

### 5.4. Common mask và tính minh bạch mẫu đánh giá

Common mask là giao của các cặp ngày gốc–asset–horizon hợp lệ đối với những mô hình đang so sánh: forecast, target, baseline và cutoff đều phải đạt. Với test2020, mask được xác định **riêng theo asset × h × sample**, không buộc một origin phải đủ cả bảy horizon mới được chấm ở từng h. Tuy nhiên, thống kê tổng hợp \(S(a)\) vẫn cần đủ cả bảy horizon. Các lý do loại (forecast thiếu, endpoint lỗi, nhãn chưa có, baseline thiếu, provenance không đạt…) phải được đếm riêng; `undefined` không được thay bằng 0 hoặc NaN trong JSON. [Walk-forward Contract §9](../eval/walk-forward-contract.md); [Test2020 Plan §3.1](../experiments/test2020-plan.md).

## 6. Kiểm định thống kê và giao thức test2020

### 6.1. Historical validation và walk-forward

Các dự báo nhiều horizon có thể dùng chung dữ liệu tương lai, khiến quan sát phụ thuộc theo thời gian. Historical validation sử dụng block bootstrap với **1.000 lần rút**, block 20 và khoảng tin cậy 95%; replicate phải giữ cặp loss model/baseline trên cùng lịch lấy mẫu. Diebold–Mariano (DM) kiểm định chênh lệch loss ghép cặp bằng phương sai HAC và hiệu chỉnh Harvey–Leybourne–Newbold (HLN). Gia đình Holm dành cho DM lịch sử gồm 28 vị trí (`all`: bốn tài sản × bảy h) và 14 vị trí (`excl_roll`: hai tài sản dầu × bảy h), không loại vị trí undefined chỉ để giảm kích thước họ. [Walk-forward Contract §11](../eval/walk-forward-contract.md); [Accuracy Schema](../api/accuracy-schema.md).

Chính sách DM calendar-gap amplitude-modulated đã được đặc tả nhưng chưa được tích hợp vào code historical tại mốc tài liệu này; xử lý hiện hành chặn DM cho \(h>1\) nếu có khoảng trống phiên bên trong. Không coi chính sách mới là kết quả đã triển khai. [Accuracy Schema](../api/accuracy-schema.md); [Walk-forward implementation](../../src/eval/walk_forward.py).

### 6.2. Test2020 theo giao thức đã khóa ở #75

Test2020 so sánh **baseline-q252** và **S1a** trên bốn tài sản, bảy horizon, origin từ **02/01/2020 đến 23/10/2026**, target cutoff **23/10/2026**. Runner đã được xây dựng trong [PR #85](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/85); việc review và hợp nhất code được theo dõi riêng. Giao thức chỉ cho phép sử dụng kết quả sau khi khóa snapshot, code và cấu hình, không dùng test để điều chỉnh tham số. [Test2020 Plan](../experiments/test2020-plan.md).

Chỉ số chính theo từng tài sản là **trung bình đều bảy horizon** trên mẫu `all`:

\[
\widehat S(a)=\frac17\sum_{h=1}^7\left(1-\frac{\overline L_{S1a,a,h}}{\overline L_{base,a,h}}\right).
\]

Nếu thiếu một horizon hoặc mean loss của baseline ở horizon đó bằng 0, \(\widehat S(a)\) không xác định. Mặt nạ từng horizon được tính riêng, giữ các cặp hợp lệ của horizon khác. Bất biến \(q_{0.50}\) giữa S1a và baseline phải khớp từng bit; trên cùng mask, MAE trung vị và sign accuracy phải bằng nhau. [Test2020 Plan §3](../experiments/test2020-plan.md).

Cơ chế suy luận chính là **circular moving-block bootstrap** trên lịch hợp NYSE ∪ CME, một kế hoạch rút ngày dùng chung cho các asset/horizon, **B=2.000, block length=20, CI percentile 95%**. Với mỗi asset × h × sample, cần **ít nhất 20 quan sát hợp lệ** để tính bootstrap theo block 20. Nếu ít hơn, **CI và p-value là `undefined`**, không tạo số thay thế; điểm ước lượng hữu hạn có thể vẫn được lưu khi công thức cho phép. CI/p cho \(S(a)\) cũng không xác định nếu bất kỳ horizon bắt buộc nào không đủ điều kiện hoặc replicate không hữu hạn. Các lần rút lặp được giữ nguyên, không bỏ replicate lỗi để làm đẹp khoảng tin cậy.

Bốn kiểm định chính một phía có \(H_0:S(a)\le0\), \(H_1:S(a)>0\). P-value bootstrap được **căn giữa theo H0**:

\[
T_b^*(a)=S_b^*(a)-\widehat S(a),\qquad
p(a)=\frac{1+\sum_{b=1}^{B}\mathbf1\{T_b^*(a)\ge\widehat S(a)\}}{B+1}.
\]

Chỉ kết luận cải thiện ở asset có p sau **Holm trên bốn tài sản** nhỏ hơn 0,05. CI percentile mô tả độ bất định, không thay kiểm định. Các báo cáo theo năm, giai đoạn stress, mẫu dầu `excl_roll`, DM theo horizon và sensitivity block 10/40 là phân tích bổ sung, không dùng để thay kết luận chính của block 20/mẫu `all`. [Test2020 Plan §§3–5, 9](../experiments/test2020-plan.md).

### 6.3. Kiểm soát lần chạy chính thức

Giao thức yêu cầu đóng băng **snapshot DT và SHA-256**, lineage, runner commit sạch, `config_hash`, seed và môi trường trước khi chạy. Runner phải kiểm tra provenance, tạo S3 conditional claim (`IfNoneMatch="*"`) **trước khi đọc dữ liệu test được bảo vệ**. Lần chạy lỗi ghi `failure.json` và dừng để nhóm quyết định; không tự chạy lại hoặc thay đổi seed/dữ liệu. Kết quả chỉ phục vụ báo cáo, không tự động đổi champion trước 22/11/2026; mọi quyết định sau đó cần ADR mới. [Test2020 Plan §§2, 5–8](../experiments/test2020-plan.md).

## 7. Giới hạn và tính hợp lệ

### 7.1. Giới hạn khoa học

Validation 2019 đã được dùng nhiều lần để lựa chọn cấu hình nên không còn là kiểm chứng độc lập. Snapshot clean và quy tắc công bố mô phỏng không khôi phục đầy đủ phiên bản dữ liệu PIT ở từng thời điểm. Các horizon chồng lấp và biến động chung giữa các tài sản khiến số cặp lớn hơn số quan sát độc lập thực chất; bootstrap/HAC chỉ xử lý một phần phụ thuộc đó. [Test2020 Plan §0](../experiments/test2020-plan.md); [Walk-forward Contract §§5.5, 11](../eval/walk-forward-contract.md).

Dầu có thể gặp giá endpoint không dương, roll và giai đoạn biến động cực đoan; việc loại target không hợp lệ làm thay đổi tập quan sát nên phải báo counts. Coverage cao không tự chứng minh mô hình tốt hơn khi khoảng dự báo quá rộng. Kết quả validation, thí nghiệm minh họa #83 hoặc metric Rolling không thay thế kết quả test2020 chính thức. [ADR-0008](../adr/0008-target-quantiles-evaluation.md); [Test2020 Plan](../experiments/test2020-plan.md).

### 7.2. Phạm vi kết luận

Kết luận về **lựa chọn mô hình** dựa trên validation và các ADR; kết luận về **khả năng tổng quát hóa** đòi hỏi test2020 theo giao thức đã khóa; kết luận về **chất lượng vận hành** dựa vào Rolling Accuracy với provenance hợp lệ. Không chuyển các chỉ số giữa ba phạm vi này thành bằng chứng tương đương.

### 7.3. Trạng thái triển khai có liên quan

Kế hoạch test2020 theo [PR #75](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/75) đã được nhóm review và merge. Runner được phát triển trong [PR #85](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/85) và đang xử lý review về bytes của claim, đối chiếu `origin/developer` và protocol hash. Các bước xác nhận CI/merge, khóa DT/SHA-256, IAM và claim cần hoàn thành trước lần chạy dự kiến trong tuần **16–22/11/2026**. Chưa có kết quả test2020 chính thức để đưa vào kết luận ngoài mẫu.

## 8. Tóm tắt phương pháp

CPAWS kết hợp **validation lịch sử** để chọn cấu hình, **test2020 ngoài mẫu** để kiểm chứng khả năng tổng quát hóa sau khi khóa lựa chọn, và **Rolling Accuracy** để theo dõi dự báo đã phát hành. Pinball skill trên common mask là thước đo chính cho so sánh mô hình; các chỉ số coverage, width, xác suất và hướng bổ sung các khía cạnh calibration và sai số. Kiểm soát thời điểm thông tin, audit counts, bootstrap/Holm và provenance giới hạn phạm vi kết luận vào những gì dữ liệu và giao thức thực sự hỗ trợ.

---

# Phụ lục A — Rolling Accuracy `rolling_8w`

Phụ lục này trình bày chi tiết nghiệp vụ Rolling API; phần chính chỉ nêu vai trò giám sát và bộ metric nền. [Walk-forward Contract §7 v4.6](../eval/walk-forward-contract.md).

## A.1. Cửa sổ và lịch chạy

Với ngày chạy UTC \(D\), cửa sổ theo `base_date` là **[D−55 ngày, D]**, gồm hai biên và có 56 ngày lịch, không phải 56 phiên. `evaluation_kind=rolling_8w`, `sample=all`; không rút ngắn cửa sổ theo bản ghi đầu tiên. Lịch đánh giá TUE–SAT lúc 13:45 UTC. Target cutoff được xác định riêng theo asset và thời điểm sẵn có của actual.

## A.2. Điều kiện phát hành và provenance

Forecast chỉ được chấm khi đúng asset/target series/champion và ngày hiệu lực, không phải sample/backfill, đủ bảy phân vị hữu hạn không giảm và xác suất trong miền quy định. `created_at` phải từ **27/10/2026 12:00 UTC** và trước 13:30 UTC của ngày target cho từng h; record còn phải thỏa input-as-of. Sai lệch `prob_up` nội suy quá 1e−6 chỉ được audit, không tự loại nếu các điều kiện cấu trúc khác đạt.

**Effective base date ban đầu 26/10/2026** khác với **eligibility bắt đầu 27/10 12:00 UTC** và **cutover Predict #48 ngày 30/10/2026 08:10:06 UTC**. Sau cutover, record cần bằng chứng conditional write và `input_snapshot_dt` trỏ đúng snapshot đã dùng. Record legacy chỉ được phép vào mẫu theo `LEGACY_ACCEPT_WITH_EVIDENCE` và approval riêng; record sau cutover thiếu snapshot không được chuyển thành legacy để bỏ qua gate. Việc có timestamp phù hợp không tự chứng minh dữ liệu thực sự có sẵn ở thời điểm dự báo.

Lịch expected chỉ đo các kỳ dự kiến; trong cùng phạm vi, `expected = published + missing`. Một kỳ có record chưa chắc eligible, một kỳ thiếu record chưa chắc là thất bại của mô hình. Rolling không tạo forecast backfill. [Walk-forward Contract §§7.2–7.3](../eval/walk-forward-contract.md).

## A.3. Metric, aggregation và display gate

Bốn metric nền `coverage_80`, `width_80`, `sign_accuracy`, `up_rate` nhân với bảy horizon tạo **28 METRIC rows**. `width_80_pct` là dẫn xuất tính từng cặp và lưu trong metadata, không phải metric row thứ 29; overall cũng thuộc META, không phải horizon 0.

Overall coverage = tổng số cặp được phủ / tổng số cặp coverage hợp lệ trên bảy h. Width, width_pct, sign và up gộp theo các counts tương ứng, không lấy trung bình ngang các tỷ lệ horizon. `n_obs` là số cặp thực vào công thức; `distinct_base_dates` là hợp các ngày gốc có coverage hợp lệ, không phải tổng n ngày của từng h.

Giá trị overall chỉ hiển thị sau **ít nhất 20 distinct base dates** có coverage hợp lệ, áp dụng chung cho mọi metric nền và dẫn xuất. Trước ngưỡng, giá trị nội bộ có thể được tính nhưng `display_value` overall là `null`; tại từng horizon chỉ công bố counts (`counts_only`).

| Tình huống | Trạng thái / cách hiển thị |
|---|---|
| Chưa có completed run đúng champion | `data_status=not_ready` |
| Completed nhưng dưới 20 distinct base dates | `data_status=collecting`, overall `display_status=insufficient_data` |
| Đạt ngưỡng, metric xác định | `data_status=ready`, metric `status=ok`, `display_status=ready` |
| Đạt ngưỡng, metric không tính được | `status=undefined`, `display_status=undefined`, giá trị `null` |
| Mỗi horizon | `display_status=counts_only` |

`COMPLETED` là trạng thái xử lý, khác trạng thái thống kê/hiển thị. Run đủ điều kiện cấu hình và evidence vẫn có thể COMPLETED với 28 hàng undefined nếu không có cặp eligible; thiếu provenance configuration hoặc snapshot/actual chưa READY phải chặn publication. [Walk-forward Contract §§7.4–7.5](../eval/walk-forward-contract.md); [Rolling Accuracy](../../src/eval/rolling_accuracy.py).

## A.4. Lưu trữ và đối chiếu shadow

Run lưu định danh snapshot, config, evidence và hash. Sau khi kiểm đủ 28 METRIC rows và META nhất quán mới cập nhật pointer `LATEST_COMPLETED`; retry không được ghi đè payload khác. Hash bảo vệ tính toàn vẹn artifact, không thay chứng cứ thời điểm phát hành. [Rolling Store](../../src/eval/rolling_store.py).

Shadow S1a đối chiếu champion theo cùng asset, base_date, h, target_date, target series và actual. Artifact shadow thiếu không làm champion không hợp lệ; báo cáo paired lưu riêng và không thay pointer/API của champion. Nếu nhiều object cùng base_date, không được tùy chọn một bản theo tên file rồi coi là duy nhất. [Walk-forward Contract §7.6](../eval/walk-forward-contract.md).

# Phụ lục B — Khác biệt giữa các thế hệ tài liệu

Bảng dưới đây lưu dấu vết quyết định để tránh diễn giải nhầm những phiên bản tài liệu trước đó như giao thức đang áp dụng.

| Nội dung từ tài liệu cũ | Quy tắc sử dụng trong chương này |
|---|---|
| Bản mô tả bảo vệ cũ lấy MASE/sai số mức giá làm trọng tâm | Dùng `pinball_skill` trên log return theo ADR-0008; MASE không phải chỉ số chính |
| Tài liệu kiến trúc cũ mô tả hạ tầng retrain | ADR-0011/0012 chốt so sánh champion/challenger trong phạm vi MVP; không suy ra SageMaker retraining đang chạy |
| Accuracy Schema có đoạn Rolling dạng đề xuất | Walk-forward Contract §7 v4.6 xác định cửa sổ, provenance, 28 rows và display gate |
| DM calendar gaps đã có chính sách mới trong schema | Chưa coi amplitude-modulated là implementation hiện hành; tiếp tục báo giới hạn DM gap |
| Bootstrap historical và test2020 khác tham số | Historical: B=1.000; test2020: B=2.000 và Holm bốn tài sản |

Nguồn: [tài liệu kiến trúc trước đây](lua-chon-kien-truc-va-mo-hinh.md), [ADR-0008](../adr/0008-target-quantiles-evaluation.md), [ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md), [ADR-0012](../adr/0012-k4-fhs-gjr-result.md), [Accuracy Schema](../api/accuracy-schema.md), [Walk-forward Contract](../eval/walk-forward-contract.md), [Test2020 Plan](../experiments/test2020-plan.md).
