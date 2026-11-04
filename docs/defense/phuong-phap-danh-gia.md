# Phương pháp đánh giá mô hình dự báo CPAWS

> Bản nháp phục vụ báo cáo bảo vệ, ngày 04/11/2026. Nội dung được đối chiếu với source và tài liệu trong bản developer do nhóm cung cấp. Chương này trình bày phương pháp, phạm vi implementation và giới hạn suy luận; không phải báo cáo kết quả test2020 hoặc xác nhận triển khai production.

## 1. Mục tiêu đánh giá

CPAWS đánh giá dự báo vàng, bạc, Brent và WTI trên các kỳ hạn từ một đến bảy phiên giao dịch. Mục tiêu không chỉ là dự đoán chiều biến động hoặc một giá trị trung tâm, mà còn là mô tả mức độ bất định của return tương lai. Mỗi kỳ hạn có bảy phân vị (quantile), tức các ngưỡng của phân phối dự báo ứng với xác suất tích lũy 0,05; 0,10; 0,25; 0,50; 0,75; 0,90 và 0,95. Trung vị là q50; q10–q90 tạo khoảng dự báo danh nghĩa 80%. “Danh nghĩa” không có nghĩa mỗi khoảng chắc chắn chứa kết quả thực tế. [Nguồn: ADR-0008 §§1–3](../adr/0008-target-quantiles-evaluation.md).

### 1.1. Target và lịch giao dịch

Với ngày gốc t và kỳ hạn h, target là log return:

\[
r_h(t)=\ln\left(\frac{P(t+h)}{P(t)}\right),\qquad h\in\{1,\ldots,7\}.
\]

Ký hiệu t+h là phiên giao dịch thứ h sau t theo lịch của tài sản, không phải h ngày lịch và không phải dòng dữ liệu thứ h sau dòng hiện tại. Việc phân biệt này bảo đảm một ngày thiếu dữ liệu không làm thay đổi kỳ hạn đang được đánh giá.

| Tài sản | Chuỗi target | Lịch phiên |
|---|---|---|
| Vàng | GLD | NYSE |
| Bạc | SLV | NYSE |
| Brent | BZ=F | CME |
| WTI | CL=F | CME |

GLD và SLV là chuỗi đại diện, không đồng nhất với giá vàng hoặc bạc giao ngay. Giá đã quy đổi để hiển thị không thay thế giá chuỗi target trong công thức nhãn. Hai endpoint phải có giá hữu hạn, dương, có trong dữ liệu clean và không bị loại trong dữ liệu rejected của đúng tài sản. Thiếu endpoint hoặc giá không dương làm log return không hợp lệ; không nội suy, forward-fill hoặc lấy trị tuyệt đối của giá để cứu nhãn. Thiếu phiên giữa hai endpoint không tự làm nhãn mất hiệu lực nếu cả hai endpoint hợp lệ, nhưng phải được thống kê. Số target có phiên giữa bị thiếu và số phiên thiếu trong từng cửa sổ là hai đại lượng khác nhau. Các cờ cảnh báo như roll không tự làm endpoint mất hiệu lực. [Nguồn: ADR-0008 §1](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §9.1](../eval/walk-forward-contract.md), [implementation Returns](../../src/forecast/returns.py).

### 1.2. Đánh giá phân phối thay vì sai số mức giá

Sai số mức giá không được chọn làm tiêu chí chính: tính liên tục của mức giá có thể làm dự báo gần giá hiện tại trông tốt mà chưa chứng minh khả năng dự báo biến động. Đánh giá return và toàn bộ các phân vị giúp xét đồng thời vị trí trung tâm, độ phủ và độ rộng của phân phối. Chỉ số chính là pinball skill so với mốc nhân quả 252 phiên; MASE, RMSE mức giá và tỷ lệ đúng chiều không thay thế tiêu chí này. [Nguồn: ADR-0008 §§4–5 và các phương án bị loại](../adr/0008-target-quantiles-evaluation.md).

`prob_up` là xác suất tăng xấp xỉ, được suy từ bảy phân vị bằng nội suy tuyến tính hàm phân phối tại 0, sau đó lấy một trừ xác suất tích lũy và giới hạn trong [0,05; 0,95]. Đây chưa phải xác suất đã được hiệu chỉnh thực nghiệm. Các phân vị được chuẩn hóa một lần khi sinh dự báo; evaluator kiểm tra tính không giảm, không sửa lại nguồn để làm kết quả đánh giá tốt hơn. Khi 0 trùng nhiều phân vị, quy tắc đã chốt dùng mức phân vị cao nhất của nhóm trùng. [Nguồn: ADR-0008 §§2–3](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §5.4](../eval/walk-forward-contract.md).

## 2. Walk-forward và phân chia dữ liệu

Walk-forward evaluation là đánh giá tuần tự theo các ngày gốc: tại mỗi ngày, chỉ dùng thông tin được phép có tại thời điểm đó để tạo dự báo, rồi ghép dự báo với nhãn tương lai khi nhãn đủ điều kiện. Tính tuần tự này không đồng nghĩa phải huấn luyện lại mô hình ở mỗi bước. Trong giao thức validation MVP, mô hình và bộ chuẩn hóa đã fit từ train được giữ cố định trong năm 2019. [Nguồn: Walk-forward Contract §§3, 6](../eval/walk-forward-contract.md).

| Giai đoạn | Vai trò | Giới hạn sử dụng |
|---|---|---|
| 2012–2013 | Khởi động đặc trưng, cửa sổ và baseline | Không chuyển thành nhãn train ngoài cấu hình |
| 2014–2018 | Huấn luyện | Nhãn train không vượt sang 2019 |
| 2019 | Validation và lựa chọn cấu hình | Không dùng nhãn năm 2020 để hoàn thiện các origin cuối năm |
| 2020–2026 | Test ngoài mẫu theo #75 | Origin 02/01/2020–23/10/2026, target cutoff 23/10/2026 |

Phân chia theo thời gian giữ hướng thông tin từ quá khứ sang tương lai. Random split có thể đưa những quan sát tương lai, hoặc những cửa sổ chồng lấp với chúng, vào tập huấn luyện của một dự báo quá khứ; vì vậy không phù hợp với giao thức này. Một cặp ngày gốc–kỳ hạn chỉ được chấm trong giai đoạn khi cả ngày gốc và ngày đích thuộc phạm vi cho phép. Những cặp vượt biên vẫn cần được đếm để tránh che giấu thiếu hụt dữ liệu. [Nguồn: ADR-0008 §7](../adr/0008-target-quantiles-evaluation.md), [Test2020 Plan §2](../experiments/test2020-plan.md).

### 2.1. Thông tin tại ngày gốc và provenance

Provenance là bằng chứng về nguồn gốc, phiên bản và thời điểm sẵn có của dữ liệu hoặc dự báo. Trong validation lịch sử, chế độ `backtest_publication_rule` dùng snapshot clean mới nhất và mô phỏng thời điểm công bố theo quy tắc nguồn. Với dữ liệu giá yfinance, quy tắc là D+1 lúc 12:00 UTC, trong đó D+1 là ngày lịch. Input phải đã có thể công bố không muộn hơn thời điểm phát hành giả lập, còn nhãn target phải công bố sau thời điểm đó. Không được suy input hợp lệ chỉ vì các số đầu vào hữu hạn. [Nguồn: Walk-forward Contract §5.5](../eval/walk-forward-contract.md).

Chế độ trên kiểm soát tính nhân quả theo quy tắc công bố, nhưng không chứng minh dữ liệu lịch sử là point-in-time (PIT) đầy đủ: snapshot được tải lại có thể chứa revision chưa tồn tại tại ngày gốc. Báo cáo phải giữ giới hạn này. Ngược lại, Rolling đánh giá forecast thực đã phát hành, nên cần bằng chứng issuance và input-as-of của từng record, không chỉ giả lập lịch sử. Hai loại bằng chứng không được hoán đổi. [Nguồn: Walk-forward Contract §§5.5, 7.3](../eval/walk-forward-contract.md).

### 2.2. Sinh dự báo và đánh giá là hai bước khác nhau

Luồng historical giữ lưới ngày gốc theo lịch, kể cả những lần thiếu input hoặc không sinh được forecast. Bước đánh giá ghép forecast có sẵn với target và baseline; không tự sinh forecast thay thế những dòng vắng. Các lý do thiếu, target chưa có và baseline không đủ dữ liệu được theo dõi riêng. Điều này giúp phân biệt chất lượng mô hình với khả năng cung cấp dữ liệu. [Nguồn: Walk-forward Contract §§3, 5, 7.1](../eval/walk-forward-contract.md), [implementation Walk-forward](../../src/eval/walk_forward.py).

Validation 2019 đã được sử dụng nhiều lần trong quá trình lựa chọn: tài liệu #75 ghi nhận bốn lần với 13 cấu hình theo ADR-0012. Vì vậy, kết quả năm 2019 có vai trò chọn thiết kế, không còn là bằng chứng ngoài mẫu độc lập cho cấu hình được chọn. Cần test theo giao thức khóa trước khi xem kết quả. Quy tắc mô hình cố định của validation MVP cũng không được suy rộng thành mô tả mọi thí nghiệm nghiên cứu: ADR-0012 mô tả giao thức K4 riêng. Chương này không coi các thử nghiệm đó là cơ chế expanding retraining đã triển khai trong sản phẩm. [Nguồn: Test2020 Plan §0](../experiments/test2020-plan.md), [ADR-0012](../adr/0012-k4-fhs-gjr-result.md).

## 3. Baseline và mô hình so sánh

### 3.1. Baseline-q252

Baseline-q252 lấy bảy phân vị thực nghiệm từ các return h phiên đã hoàn tất trong cửa sổ 252 phiên tại ngày gốc. Chỉ return có ngày đích không muộn hơn ngày gốc mới được sử dụng. Cửa sổ tính theo lịch phiên, không gom đủ 252 return hợp lệ bằng cách lùi tùy ý qua các khoảng thiếu. Baseline cần ít nhất 200 return hợp lệ; nếu không đạt thì điểm bị loại khỏi tập đánh giá chung, kể cả đối với các metric không trực tiếp chia cho baseline. Quy tắc nhân quả yêu cầu sửa hoặc nối giá sau ngày gốc không làm thay đổi baseline tại ngày đó. [Nguồn: ADR-0008 §4](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §8](../eval/walk-forward-contract.md).

Baseline đồng thời là champion được tài liệu lựa chọn và mốc đo pinball skill. Trong historical evaluation, baseline được gắn vào Detail để so sánh với mô hình, không phải mô hình được huấn luyện hoặc một Fits giả. Khi chính baseline là forecast production, Rolling chấm chất lượng forecast này bằng các metric MVP; không cần hiển thị skill tự so với chính nó. Quyết định champion trong tài liệu không tự chứng minh cấu hình AWS đang chạy. [Nguồn: ADR-0012](../adr/0012-k4-fhs-gjr-result.md), [Walk-forward Contract §§7–8](../eval/walk-forward-contract.md).

### 3.2. S1a: co giãn độ bất định quanh trung vị

S1a, phiên bản `s1a-l094`, là challenger điều chỉnh phân vị baseline theo biến động. Ước lượng biến động ngắn hạn dùng EWMA, tức trọng số suy giảm theo hàm mũ, với λ=0,94. Tỷ số biến động ngắn hạn và dài hạn được giới hạn trong [0,5; 2,0], tạo hệ số k tại ngày gốc. Phân vị được biến đổi quanh trung vị:

\[
q^{S1a}_{\tau,t,h}=q^{base}_{0.50,t,h}
+k_t\big(q^{base}_{\tau,t,h}-q^{base}_{0.50,t,h}\big),
\qquad 0.5\leq k_t\leq2.0.
\]

Khi độ biến động gần đây tăng tương đối, khoảng có thể rộng hơn; khi giảm, khoảng có thể hẹp hơn. Đây là cơ chế cần được đánh giá bằng loss và calibration, không phải bảo đảm cải thiện. Trung vị q50 được giữ nguyên, nên trên cùng mặt nạ, MAE của trung vị và sign accuracy phải bằng baseline. `prob_up` vẫn phải tính lại từ phân vị S1a; không chép xác suất baseline. Các tham số đã chọn trên 2019 được khóa, không tinh chỉnh bằng test2020. [Nguồn: ADR-0010](../adr/0010-k3b-volatility-scaling-result.md), [implementation volatility scaling](../../src/forecast/vol_scaled.py), [Test2020 Plan §§1, 3.2](../experiments/test2020-plan.md).

### 3.3. Giới hạn lựa chọn mô hình

ADR-0011 chuyển trọng tâm MVP từ xây hạ tầng retrain tự động sang so sánh champion/challenger. ADR-0012 ghi quyết định giữ baseline và dừng tiếp tục dò mô hình price-only sau K4. Cách tổ chức này tách đánh giá challenger khỏi quyết định thay champion, đồng thời hạn chế việc tiếp tục tối ưu trên cùng validation. Không mô tả DLinear/LSTM là champion hoặc SageMaker retraining là chức năng production đang vận hành. Lịch so sánh ban đầu trong ADR-0011 được cập nhật cho Rolling MVP thành TUE–SAT tại Walk-forward Contract §7. [Nguồn: ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md), [ADR-0012](../adr/0012-k4-fhs-gjr-result.md), [Walk-forward Contract §7](../eval/walk-forward-contract.md).

## 4. Rolling Accuracy `rolling_8w`

### 4.1. Cửa sổ và đối tượng đánh giá

Rolling đánh giá các forecast champion production đã phát hành thật. Với ngày chạy UTC D, cửa sổ gồm cả hai biên:

\[
[\text{window_start},\text{window_end}]=[D-55\text{ ngày},D].
\]

Đây là 56 ngày lịch UTC theo `base_date`, không phải 56 phiên giao dịch. `evaluation_kind=rolling_8w`, `sample=all`; không co cửa sổ theo ngày đầu có dữ liệu. Lịch đánh giá đã chốt là TUE–SAT lúc 13:45 UTC. Ngày cutoff target được xác định riêng cho từng tài sản; nhãn chưa công bố hoặc chưa hợp lệ không được dùng để tăng số quan sát. Không tái tạo forecast lịch sử để làm đầy cửa sổ. [Nguồn: Walk-forward Contract §§7.2–7.4](../eval/walk-forward-contract.md).

### 4.2. Eligibility và bằng chứng phát hành

Forecast được xét phải đúng asset, target series, champion và ngày hiệu lực; không phải sample hoặc backfill; đủ bảy phân vị hữu hạn, không giảm và xác suất trong miền quy định. Timestamp phát hành phải từ 27/10/2026 12:00 UTC và trước 13:30 UTC của ngày target ở từng h, đồng thời qua kiểm tra input-as-of. Timestamp một mình không chứng minh không nhìn trước. Sai lệch nội suy `prob_up` vượt 1e-6 trong dữ liệu làm tròn chỉ được ghi audit, không tự loại record hoặc sửa nguồn nếu các kiểm tra cấu trúc khác vẫn đạt. [Nguồn: Walk-forward Contract §7.3](../eval/walk-forward-contract.md).

Ngày hiệu lực champion, mốc bắt đầu eligibility và cutover conditional write là ba khái niệm khác nhau. Contract ghi effective base date ban đầu là 26/10/2026, còn cutover Predict PR #48 là 30/10/2026 08:10:06 UTC theo bằng chứng nhóm cung cấp. Forecast hậu cutover cần conditional-write provenance và `input_snapshot_dt` đúng snapshot thực sự dùng. Record legacy chỉ được chấp nhận riêng lẻ theo `LEGACY_ACCEPT_WITH_EVIDENCE`, có danh sách duyệt và audit input-as-of/lịch sử phát hành. Không được dùng timestamp đúng giờ làm approval, hoặc hạ record hậu cutover thiếu snapshot thành legacy. Các mốc trong Contract không chứng minh Rolling writer/API đã triển khai. [Nguồn: Walk-forward Contract §7.3](../eval/walk-forward-contract.md).

Lịch kỳ vọng chỉ phục vụ đếm số kỳ dự kiến. Trong cùng phạm vi, expected = published + missing; một record hiện diện vẫn có thể không đủ eligibility. Kỳ không có record chỉ là thiếu bản ghi chưa phân loại nguyên nhân, không mặc định là lỗi mô hình. Ngoại lệ MVP không yêu cầu đọc CloudWatch hoặc manifest lịch phát hành cho mỗi run; điều này không miễn provenance của các cặp thực sự được chấm. [Nguồn: Walk-forward Contract §7.2](../eval/walk-forward-contract.md).

### 4.3. Metric, tổng hợp và trạng thái hiển thị

Rolling MVP lưu bốn metric nền: `coverage_80`, `width_80`, `sign_accuracy`, `up_rate`. Bốn metric nhân bảy horizon tạo **28 METRIC rows cho mỗi asset/run**. `width_80_pct` là dẫn xuất theo từng cặp, lưu trong metadata của run; không tạo hàng metric thứ 29 hoặc thêm bảy hàng nền. Overall cũng là tổng hợp trong META, không phải horizon h=0. Rolling MVP không công bố toàn bộ bộ metric nghiên cứu ADR-0008, DM hoặc kết quả test2020. [Nguồn: Walk-forward Contract §§7.4–7.5](../eval/walk-forward-contract.md), [Rolling Store](../../src/eval/rolling_store.py).

Overall coverage bằng tổng số cặp được phủ chia tổng số cặp hợp lệ của bảy h, không lấy trung bình ngang bảy tỷ lệ. Width, width_pct, sign và up được gộp theo số quan sát riêng tương ứng. `n_obs` là số cặp thực đi vào công thức; số distinct base dates là số ngày gốc khác nhau, lấy hợp ngày giữa các h chứ không cộng số ngày từng h. Các cặp cùng ngày gốc không phải quan sát độc lập. [Nguồn: Walk-forward Contract §7.4](../eval/walk-forward-contract.md), [Rolling Accuracy](../../src/eval/rolling_accuracy.py).

Ngưỡng hiển thị overall là ít nhất 20 distinct base dates có cặp coverage hợp lệ. Cùng một ngưỡng áp dụng cho cả bốn metric nền và width_pct dẫn xuất, không xét riêng số ngày của mỗi metric. Trước ngưỡng, giá trị tính toán nội bộ có thể tồn tại nhưng mọi `display_value` overall đều null. Từng horizon chỉ hiển thị counts, kể cả khi overall đủ dữ liệu. [Nguồn: Walk-forward Contract §7.4](../eval/walk-forward-contract.md).

| Tình huống | Trạng thái cần phân biệt | Ý nghĩa |
|---|---|---|
| Chưa có completed run phù hợp champion | `data_status=not_ready` | Chưa có kết quả được phép phục vụ |
| Completed nhưng dưới 20 ngày gốc coverage hợp lệ | `data_status=collecting`, overall `display_status=insufficient_data` | Không hiển thị giá trị metric overall |
| Đạt ngưỡng, metric tính được | `data_status=ready`, metric `status=ok`, `display_status=ready` | Có thể hiển thị giá trị metric đó |
| Đạt ngưỡng nhưng một metric không tính được | Metric `status=undefined`, `display_status=undefined` | Giá trị vẫn null, không chuyển thành 0 |
| Mỗi horizon | `display_status=counts_only` | Không công bố tỷ lệ từ giá trị nội bộ |

Trạng thái xử lý `COMPLETED` khác trạng thái thống kê và hiển thị. Nguồn đã READY, evidence configuration hợp lệ nhưng không có cặp eligible vẫn có thể hoàn thành với 28 hàng undefined. Ngược lại, thiếu cấu hình provenance bắt buộc hoặc snapshot/actual chưa READY phải chặn publication; không được coi đó là một run rỗng hợp lệ. Legacy approval phải gắn với record thực thuộc asset/model/window của run, không mở gate cho tài sản khác. [Nguồn: Rolling handoff](../handoff/rolling-accuracy-handoff.md), [Rolling Job](../../src/eval/rolling_job.py).

### 4.4. Tính toàn vẹn và shadow độc lập

Run chứa định danh snapshot, cấu hình, evidence và hashes để truy vết. Chỉ sau khi xác nhận đủ 28 metric và metadata nhất quán mới hoàn thành và cập nhật con trỏ `LATEST_COMPLETED`; retry cùng payload không ghi đè kết quả khác. Cơ chế này bảo vệ tính toàn vẹn, không biến hash đúng thành bằng chứng provenance đúng hoặc bằng chứng triển khai AWS. [Nguồn: Walk-forward Contract §7.5](../eval/walk-forward-contract.md), [Rolling Store](../../src/eval/rolling_store.py).

Nhánh shadow ghép champion và S1a trên cùng asset, base_date, h, target_date, target_series và nguồn nhãn. Snapshot của shadow hậu cutover phải khớp champion; object phải có bằng chứng phát hành trước nhãn. Khi nhiều file cùng base_date, không chọn tùy ý theo tên ngày S3 và không đếm trùng. Report paired lưu riêng, không thay mẫu champion, pointer hoặc API; thiếu shadow không chặn champion. Nếu champion của một asset không còn baseline-q252, không tự đổi định nghĩa S1a để tiếp tục so sánh. [Nguồn: Walk-forward Contract §7.6](../eval/walk-forward-contract.md), [Rolling handoff](../handoff/rolling-accuracy-handoff.md).

## 5. Chỉ số đánh giá theo ADR-0008

Trong các công thức dưới đây, i chỉ một cặp ngày gốc–kỳ hạn hợp lệ trong phạm vi đang xét; y là log return thực tế, q là phân vị dự báo và n là số quan sát thực dùng. Trung bình giữa các nhóm chỉ được thực hiện theo trọng số đã định trước. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md).

### 5.1. Pinball loss

Pinball loss là hàm mất mát bất đối xứng cho phân vị mức τ:

\[
L_\tau(y,q)=\max\{\tau(y-q),(\tau-1)(y-q)\},
\qquad
PL=\frac1n\sum_{i=1}^{n}\frac17\sum_{\tau\in\mathcal T}L_\tau(y_i,q_{i,\tau}),
\]

với tập bảy mức \(\mathcal T=\{0.05,0.10,0.25,0.50,0.75,0.90,0.95\}\). Phạt hai phía khác nhau theo τ phù hợp với mục tiêu ước lượng từng phân vị. Trung bình đủ bảy mức đánh giá nhiều vị trí của phân phối, thay vì chỉ sai số trung vị. Không gộp pinball thô giữa các tài sản để chọn mô hình vì thang biến động khác nhau. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md), [Metrics](../../src/eval/metrics.py).

### 5.2. Pinball skill

\[
\operatorname{Skill}=1-\frac{PL_{model}}{PL_{baseline}}.
\]

Hai loss phải tính trên cùng tập quan sát. Skill dương nghĩa loss thấp hơn baseline; bằng 0 nghĩa bằng loss; âm nghĩa kém baseline. Đây là chỉ số chính để lựa chọn và đánh giá mô hình. Tính tỷ số của hai mean loss, không lấy mean của tỷ số từng dòng. Nếu baseline mean loss bằng 0, skill undefined; không gán skill bằng 0 dù các metric khác vẫn có thể tính. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md), [Accuracy Schema](../api/accuracy-schema.md).

### 5.3. Calibration, coverage và độ rộng

Calibration là sự phù hợp giữa xác suất danh nghĩa và tần suất thực tế; sharpness là mức tập trung của phân phối dự báo. Với từng phân vị, `quantile_hit_rates` là mean của chỉ báo y≤qτ và được đối chiếu với τ. Với khoảng l=q10, u=q90:

\[
\operatorname{coverage}_{80}=\frac1n\sum_i\mathbf1\{l_i\le y_i\le u_i\},
\qquad
\operatorname{width}_{80}=\frac1n\sum_i(u_i-l_i).
\]

Coverage gần 80% cần được đọc cùng width: tăng độ rộng có thể tăng độ phủ mà không chứng minh dự báo tốt hơn. Ngược lại, khoảng hẹp nhưng bỏ sót nhiều nhãn không phải kết quả tốt. `interval_score_80` kết hợp độ rộng và phạt nhãn nằm ngoài khoảng, với α=0,2:

\[
IS_i=(u_i-l_i)+\frac2\alpha(l_i-y_i)\mathbf1\{y_i<l_i\}
+\frac2\alpha(y_i-u_i)\mathbf1\{y_i>u_i\},
\qquad \operatorname{interval\_score}_{80}=\frac1n\sum_i IS_i.
\]

Width gốc có đơn vị log return. Dẫn xuất dùng để hiển thị là:

\[
\operatorname{width}_{80,pct}=\frac1n\sum_i100\big(\exp(u_i)-\exp(l_i)\big).
\]

Phép chuyển đổi được thực hiện trên từng cặp trước khi lấy trung bình, cùng mặt nạ và n với width gốc. Không thay bằng 100×width hoặc exp của các mean phân vị. Đơn vị percent nghĩa giá trị 4,2 được đọc là 4,2%. Web sử dụng giá trị đã được API cho phép hiển thị, không tự chuyển log-width. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §7.4](../eval/walk-forward-contract.md).

### 5.4. Xác suất tăng và hướng

Với p là `prob_up`, Brier score đo sai số xác suất của sự kiện tăng:

\[
BS=\frac1n\sum_i\big(p_i-\mathbf1\{y_i>0\}\big)^2,
\qquad \operatorname{BrierSkill}=1-\frac{BS_{model}}{BS_{reference}}.
\]

Mốc chính là tần suất tăng nhân quả trong cửa sổ 252 phiên, báo kèm mốc xác suất hằng 0,5. Tần suất tăng baseline không phải xác suất nội suy từ phân vị baseline và không bị kẹp vào miền [0,05; 0,95] của `prob_up`. Mẫu số Brier bằng 0 dẫn tới undefined. [Nguồn: ADR-0008 §§3–5](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §8](../eval/walk-forward-contract.md).

Gọi \(I_s=\{i:y_i\ne0,\ q_{i,0.50}\ne0\}\) là phần còn lại của common mask sau khi loại dấu bằng 0:

\[
\operatorname{sign\_accuracy}=\frac1{|I_s|}\sum_{i\in I_s}
\mathbf1\{\operatorname{sign}(q_{i,0.50})=\operatorname{sign}(y_i)\},
\qquad
\operatorname{up\_rate}=\frac1n\sum_i\mathbf1\{y_i>0\}.
\]

Sign accuracy luôn phải đặt cạnh up rate để thấy bối cảnh thiên lệch tăng/giảm. Hai chỉ số có thể khác mẫu số do sign loại thêm các trường hợp bằng 0; không giả định chúng dùng cùng n. Tỷ lệ đúng chiều không đo độ lớn sai số hoặc chất lượng toàn bộ phân phối. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md).

### 5.5. Sai số trung vị và mốc naive

\[
\operatorname{mae\_ratio\_vs\_naive}
=\frac{\operatorname{mean}(|y-q_{0.50}|)}{\operatorname{mean}(|y|)}.
\]

Mốc naive dự báo return bằng 0, chỉ dùng làm mẫu số của tỷ lệ này. Tỷ lệ nhỏ hơn 1 biểu thị MAE trung vị thấp hơn naive trên cùng tập điểm. Đây không phải MASE: mẫu số ở đây là sai số naive trên tập đánh giá, không phải thang đo từ tập train. Naive không cần trở thành model hoặc một dòng forecast giả; cũng không có sign accuracy riêng có ý nghĩa theo quy tắc loại dấu 0. Mean |y| bằng 0 thì tỷ lệ undefined. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §11](../eval/walk-forward-contract.md).

### 5.6. Common mask và trạng thái kết quả

Common mask là tập quan sát hợp lệ dùng chung để các chỉ số và các mô hình được so sánh công bằng. Trong historical evaluation, một điểm cần forecast hợp lệ, target hợp lệ, baseline hợp lệ và target trong cutoff. Khi so hai model, lấy giao theo khóa ngày gốc–asset–h, không ghép hai vector đã bỏ missing độc lập. Test2020 bắt buộc baseline và S1a có cùng dòng theo từng asset×h×sample. Rolling bổ sung eligibility của forecast production trước khi áp các kiểm tra target/baseline. [Nguồn: Walk-forward Contract §9.2](../eval/walk-forward-contract.md), [Test2020 Plan §3.1](../experiments/test2020-plan.md).

Các lý do loại gồm thiếu forecast, input không hợp lệ, target thiếu hoặc không dương, nhãn chưa sẵn sàng, target vượt cutoff, baseline dưới mức tối thiểu và provenance chưa đạt. Phải giữ số đếm theo lý do, tránh trình bày n giảm như thể đó chỉ là số kỳ không phát hành. Khi common mask rỗng, metric áp dụng nhận `status=undefined`, `value=null`, `n_obs=0`, `undefined_reason=no_evaluable_obs`. Khi mẫu số bằng 0 nhưng còn quan sát, reason là `zero_denominator` và giữ n thực tế. JSON không xuất NaN/Infinity hoặc thay missing bằng 0. [Nguồn: Accuracy Schema](../api/accuracy-schema.md), [Walk-forward Contract §§9, 11](../eval/walk-forward-contract.md).

Tỷ lệ crossing là chẩn đoán riêng trên forecast có bằng chứng phân vị thô, không cần target hoặc baseline. Không suy crossing=false chỉ vì phân vị lưu đã được sort. Với dầu, các metric thông thường có thêm mẫu `excl_roll`, bỏ cửa sổ chứa expiry/roll trong khoảng (base_date, target_date]; không sửa dữ liệu giá hoặc loại phiên base_date chỉ vì chính phiên đó có roll. Crossing chỉ áp dụng cho `all`; dòng crossing dầu/excl_roll là `not_applicable` với reason `unsupported_sample`. [Nguồn: ADR-0008 §§5–6](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §§5.4, 9.3](../eval/walk-forward-contract.md).

## 6. Kiểm định thống kê và độ tin cậy

### 6.1. Historical validation và Walk-forward

Các target nhiều kỳ hạn có thể dùng chung những phiên tương lai; vì vậy không coi toàn bộ các cặp là độc lập. Block bootstrap là phép lấy mẫu lại theo khối ngày liên tiếp để giữ một phần phụ thuộc thời gian. Giao thức validation MVP chốt block length 20 phiên, 1.000 replicate, CI 95% và seed trong cấu hình. Một kế hoạch rút ngày dùng chung trên lưới hợp lịch NYSE/CME được áp cho mọi asset/h. Ngày không có quan sát của một nhóm vẫn vắng; không điền 0, không dịch sang ngày khác và không loại ngày rút lặp. [Nguồn: Walk-forward Contract §11.2](../eval/walk-forward-contract.md).

Với pinball skill, mỗi replicate lấy cặp loss model/baseline trên cùng ngày rồi tính lại tỷ số hai mean. Implementation historical kiểm tra lịch sử đủ cho block; không có cặp, mẫu số không xác định hoặc replicate không hợp lệ dẫn tới CI undefined, không bỏ replicate xấu để làm đẹp CI. Điểm ước lượng hữu hạn có thể vẫn `status=ok` khi CI không tính được; phải báo riêng nguyên nhân CI null. Phạm vi MVP bắt buộc CI pinball skill, các CI khác có thể được hoãn theo Contract; không tuyên bố toàn bộ metric đã có CI chỉ vì ADR nêu mục tiêu chung. [Nguồn: Walk-forward Contract §11.2](../eval/walk-forward-contract.md), [Walk-forward implementation](../../src/eval/walk_forward.py), [Metrics](../../src/eval/metrics.py).

Diebold–Mariano (DM) kiểm tra chênh lệch loss dự báo. Chuỗi đầu vào là \(d_t=PL_{A,t}-PL_{B,t}\) trên các ngày ghép đúng; d trung bình âm có lợi cho A. Implementation dùng phương sai HAC, tức ước lượng phương sai có xét tự tương quan và phương sai thay đổi, với trọng số đều và độ trễ h−1 trong orchestration. Hiệu chỉnh Harvey–Leybourne–Newbold (HLN) và phân phối t với T−1 bậc tự do được dùng cho kiểm định hai phía, T là số loss ghép. Không đủ cặp hoặc phương sai không dương thì kiểm định undefined, không sinh p-value giả. [Nguồn: Walk-forward Contract §11.1](../eval/walk-forward-contract.md), [Metrics](../../src/eval/metrics.py).

Khi báo nhiều kiểm định, Holm điều chỉnh p-value theo họ định trước: 28 vị trí cho 4 asset×7 h ở `all`, 14 vị trí cho hai loại dầu ở `excl_roll`. Các vị trí undefined vẫn thuộc kích thước họ; không xóa chúng để giảm mức điều chỉnh. Đây là họ kiểm định theo horizon, khác họ bốn tài sản của kiểm định chính test2020. [Nguồn: Accuracy Schema](../api/accuracy-schema.md), [Walk-forward Contract §11.1](../eval/walk-forward-contract.md).

Về khoảng trống lịch, code Walk-forward hiện chặn DM ở h>1 khi chuỗi ngày được chấm có khoảng trống phiên bên trong. Chính sách amplitude-modulated đã được ghi trong Accuracy Schema chưa được triển khai thành xử lý mới tương ứng; không được diễn giải nó như Parzen kernel hoặc tuyên bố code đã xử lý gap theo chính sách mới. Việc cập nhật DM gap được hoãn sau 22/11; test2020 phải báo nhóm bị chặn theo implementation hiện có. [Nguồn: Accuracy Schema, phần DM calendar gaps](../api/accuracy-schema.md), [Walk-forward implementation](../../src/eval/walk_forward.py), [Walk-forward Contract §7.6](../eval/walk-forward-contract.md), [Test2020 Plan §3.3](../experiments/test2020-plan.md).

### 6.2. Test2020 theo giao thức #75

Giao thức `run_id=test2020` chỉ so baseline-q252 và S1a trên bốn tài sản, h=1–7, origin 02/01/2020–23/10/2026 và target cutoff 23/10/2026. Các tham số và quy tắc sử dụng kết quả được khóa trước lần chạy. Không dùng code validation cũ để thay thế định nghĩa riêng của test2020. [Nguồn: Test2020 Plan §§1–3, 6](../experiments/test2020-plan.md).

Chỉ số chính theo tài sản a là trung bình đều bảy skill trên mẫu `all`:

\[
\widehat S(a)=\frac17\sum_{h=1}^{7}
\left(1-\frac{\overline L_{S1a,a,h}}{\overline L_{base,a,h}}\right).
\]

Không gộp loss các h rồi lấy một tỷ số, vì như vậy horizon có loss lớn có thể chi phối kết quả. Thiếu bất kỳ h nào hoặc baseline mean loss của một h bằng 0 làm S(a) undefined; không bỏ h đó rồi chia cho số h còn lại. Bất biến q50 của S1a và baseline phải khớp từng bit trên mặt nạ chung; MAE ratio và sign accuracy phải bằng nhau. Vi phạm bất biến là lỗi phải dừng, không phải kết quả mô hình. [Nguồn: Test2020 Plan §§3.1–3.2](../experiments/test2020-plan.md).

Circular moving-block bootstrap lấy các khối trên lịch hợp nhất, cho phép khối vòng qua cuối lưới ngày. Giao thức chính dùng block 20, B=2.000 và seed cố định ghi trong config; kế hoạch lấy mẫu chung giữ liên hệ giữa asset và horizon. CI là khoảng percentile 95% của các giá trị S*(a). Mỗi replicate phải tính lại loss và skill từ các dòng tương ứng; replicate không hữu hạn làm CI undefined, không được bỏ lần rút đó. Không có đủ quan sát để tạo thống kê hợp lệ cũng không được sinh CI hoặc p-value bằng giá trị thay thế. Chi tiết kiểm tra điều kiện mẫu của runner cần được đối chiếu khi implementation được cung cấp, không tự thêm ngưỡng mới vào kế hoạch. [Nguồn: Test2020 Plan §3.1](../experiments/test2020-plan.md).

Có bốn giả thuyết chính một phía, mỗi tài sản một giả thuyết:

\[
H_0:S(a)\leq0,\qquad H_1:S(a)>0.
\]

Theo sửa đổi 03/11/2026, phân phối bootstrap được căn giữa tại giả thuyết không bằng:

\[
T_b^*(a)=S_b^*(a)-\widehat S(a),\qquad
p(a)=\frac{1+\sum_{b=1}^{B}\mathbf1\{T_b^*(a)\geq\widehat S(a)\}}{B+1}.
\]

Không lấy tỷ lệ S*≤0 làm p-value. Holm được áp trên bốn p-value tài sản với α=0,05; chỉ kết luận S1a tốt hơn baseline ở tài sản khi p sau Holm nhỏ hơn 0,05. CI percentile mô tả độ bất định, không thay thế kiểm định này. Nếu không thể xây phân phối thống kê hợp lệ thì không diễn giải ý nghĩa thống kê từ CI thiếu hoặc p-value không xác định. [Nguồn: Test2020 Plan §§3.1, 9](../experiments/test2020-plan.md).

Các báo cáo theo năm 2020–2026, dầu `excl_roll`, giai đoạn COVID 15/02–31/05/2020, Nga–Ukraine 15/02–30/04/2022 và sensitivity block 10/40 là bổ sung. Không chọn nhóm hay block có kết quả đẹp nhất để thay kết luận chính block 20/mẫu `all`. DM theo horizon cũng là phân tích phụ, không thay kiểm định bootstrap bốn tài sản. [Nguồn: Test2020 Plan §§3.3–4](../experiments/test2020-plan.md).

### 6.3. Một lần chạy và ranh giới sử dụng kết quả

Kế hoạch quy định ghi claim trước khi chạy, khóa snapshot DT, SHA-256, lineage, commit sạch, config hash, seed và môi trường. Snapshot là bản clean mới nhất tại thời điểm merge kế hoạch theo cách chọn đã định, không tùy chọn sau khi xem kết quả. Runner phải kiểm hash khi nạp. Claim ghi một lần bằng điều kiện không tồn tại; lỗi giữa chừng phải ghi failure và chờ nhóm quyết định, không tự chạy lại hoặc đổi cấu hình. Đây là giao thức được mô tả, không phải thao tác được thực hiện khi soạn chương này. [Nguồn: Test2020 Plan §§2, 6, 8](../experiments/test2020-plan.md).

Kết quả chỉ phục vụ báo cáo và bảo vệ; không đổi champion trước 22/11, và thay champion sau đó cần ADR mới. Lịch dự kiến chạy là tuần 16–22/11. Chương này không đưa kết quả test2020, không xác nhận lần chạy đã diễn ra và không suy S1a tốt hơn baseline từ thiết kế co giãn độ biến động. [Nguồn: Test2020 Plan §§5–7](../experiments/test2020-plan.md).

## 7. Giới hạn và tính hợp lệ của kết luận

### 7.1. Giới hạn khoa học

Validation 2019 đã tham gia chọn nhiều cấu hình, nên kết quả tốt trên năm này chịu ảnh hưởng của lựa chọn mô hình. Chỉ test đã khóa trước mới có thể bổ sung bằng chứng tổng quát hóa; không được dùng test để mở một vòng chọn mô hình khác mà vẫn gọi là kiểm tra độc lập. [Nguồn: ADR-0012](../adr/0012-k4-fhs-gjr-result.md), [Test2020 Plan §§0, 5](../experiments/test2020-plan.md).

Snapshot clean lịch sử không tương đương dữ liệu PIT tuyệt đối. Publication-rule simulation kiểm tra thời điểm công bố theo quy tắc, nhưng không khôi phục đầy đủ mọi revision lịch sử. Tương tự, checksum bảo vệ tính nhất quán của artifact, không tự chứng minh artifact tồn tại trước ngày phát hành. Cần tách giới hạn historical vintage khỏi evidence production. [Nguồn: Walk-forward Contract §5.5](../eval/walk-forward-contract.md), [Test2020 Plan §2](../experiments/test2020-plan.md), [Rolling handoff](../handoff/rolling-accuracy-handoff.md).

Horizon chồng lấp và các asset chịu biến động chung làm số cặp lớn hơn lượng thông tin độc lập. Bootstrap theo khối và HAC xử lý phụ thuộc theo giao thức đã định nhưng không loại bỏ mọi rủi ro suy luận, nhất là khi mẫu ngắn hoặc có khoảng trống. Ngưỡng 20 distinct base dates của Dashboard là quy tắc hiển thị, không phải chứng nhận 20 quan sát độc lập hay ý nghĩa thống kê. [Nguồn: ADR-0008 §5](../adr/0008-target-quantiles-evaluation.md), [Walk-forward Contract §§7.4, 11](../eval/walk-forward-contract.md).

Dữ liệu dầu có thể có endpoint không dương, roll và những giai đoạn biến động bất thường. Loại endpoint không hợp lệ là cần thiết để log return có nghĩa, nhưng cũng làm thay đổi tập quan sát của các giai đoạn căng thẳng; vì vậy phải báo số bị loại. Coverage tốt riêng lẻ không chứng minh dự báo tốt trên mọi mặt, đặc biệt khi đạt bằng khoảng rất rộng. Kết luận phải đọc cùng pinball skill, width, interval score và counts, không gán lợi ích đầu tư từ các metric này. [Nguồn: ADR-0008 §§1, 5–6](../adr/0008-target-quantiles-evaluation.md), [Test2020 Plan §§2–4](../experiments/test2020-plan.md).

### 7.2. Khác biệt giữa các thế hệ tài liệu

| Khác biệt trong nguồn | Cách xử lý trong chương này |
|---|---|
| Tài liệu bảo vệ cũ còn dùng MASE và mô tả hạ tầng retrain | Ưu tiên ADR-0008 về metric; ADR-0011/0012 về lựa chọn champion/challenger. Không sửa tài liệu cũ. |
| Accuracy Schema còn có đoạn Rolling ở trạng thái đề xuất | Áp dụng Walk-forward Contract §7 v4.6 cho cửa sổ, eligibility, 28 rows, derived width và display gate. |
| Ghi chú historical về code DM cũ chưa phản ánh bản Metrics hiện có | Đối chiếu implementation: trọng số HAC đều, HLN; không coi Bartlett là phương pháp hiện hành. |
| Chính sách DM calendar gaps đã ghi trong schema nhưng chưa triển khai | Mô tả giới hạn gap hiện tại; giữ cập nhật sau 22/11 ngoài phạm vi. |
| Bootstrap validation dùng 1.000 replicate, test2020 dùng 2.000 | Giữ hai giao thức riêng; test2020 dùng định nghĩa và sửa đổi 03/11 của kế hoạch. |

Nguồn đối chiếu: [tài liệu bảo vệ cũ](lua-chon-kien-truc-va-mo-hinh.md), [ADR-0008](../adr/0008-target-quantiles-evaluation.md), [ADR-0011](../adr/0011-weekly-champion-challenger-instead-of-retrain.md), [ADR-0012](../adr/0012-k4-fhs-gjr-result.md), [Accuracy Schema](../api/accuracy-schema.md), [Walk-forward Contract](../eval/walk-forward-contract.md), [Metrics](../../src/eval/metrics.py), [Test2020 Plan](../experiments/test2020-plan.md).

### 7.3. Những điểm cần xác nhận trước khi chốt báo cáo

**Trạng thái phê duyệt tài liệu.** Kế hoạch test2020 tại PR #75 đã được review, approve và merge vào `developer` theo xác nhận của người dùng. Header “Bản nháp” còn tồn tại trong file kế hoạch không đồng nghĩa giao thức chưa được chốt hoặc phản ánh trạng thái PR mới nhất. Tuy nhiên, trạng thái phê duyệt của các ADR liên quan cần được đối chiếu riêng nếu header và phần quyết định chưa thống nhất. Chương này sử dụng giao thức #75 làm cơ sở phương pháp, không mặc định mọi tài liệu tham chiếu đã có cùng trạng thái phê duyệt. [Nguồn: ADR-0008](../adr/0008-target-quantiles-evaluation.md), [ADR-0010](../adr/0010-k3b-volatility-scaling-result.md), [ADR-0012](../adr/0012-k4-fhs-gjr-result.md), [Test2020 Plan](../experiments/test2020-plan.md).

**[CẦN XÁC NHẬN] Tích hợp và kiểm chứng runner test2020.** Theo xác nhận của người dùng, runner test2020 đã được phát triển riêng và đang chuẩn bị PR, nhưng chưa có xác nhận PR runner đã được approve hoặc merge vào `developer`. Tại thời điểm đối chiếu ngày 04/11/2026, bản ZIP developer chưa chứa `src/eval/run_test2020.py` và `configs/test2020.py`; sự vắng mặt trong snapshot này không có nghĩa runner chưa được phát triển. Chưa thực hiện lần chạy test2020 chính thức. Trước lần chạy chính thức và trước khi sử dụng kết quả, nhóm cần hoàn tất kiểm tra CI, review giao thức, provenance, seed, clean snapshot DT/SHA-256, lineage, commit sạch, config hash và các điều kiện run-once. Việc có code runner không đồng nghĩa đã sẵn sàng chạy chính thức, đã triển khai production hoặc đã hoàn thành lần đánh giá ngoài mẫu. [Nguồn: Test2020 Plan §§3, 6, 8](../experiments/test2020-plan.md), [Metrics](../../src/eval/metrics.py), [Walk-forward implementation](../../src/eval/walk_forward.py).

Sự hiện diện của code Rolling và handoff cho phép mô tả implementation cục bộ, nhưng không chứng minh IAM, concurrency hoặc deployment AWS thực tế đã được nghiệm thu. Trạng thái triển khai cần bằng chứng vận hành riêng; chương này không thay thế việc xác minh đó. [Nguồn: Rolling handoff](../handoff/rolling-accuracy-handoff.md).

## 8. Tóm tắt phương pháp

Phương pháp CPAWS kết hợp ba cơ chế với ba mục tiêu khác nhau. Validation lịch sử dùng để lựa chọn cấu hình theo thời gian và kiểm tra các giả định; test ngoài mẫu theo giao thức #75 dùng để đánh giá khả năng tổng quát hóa sau khi khóa lựa chọn; Rolling Accuracy theo dõi chất lượng forecast thực đã phát hành với evidence và nhãn hợp lệ. Pinball skill giữ vai trò tiêu chí chính của đánh giá mô hình, còn coverage, width, xác suất và hướng cung cấp các góc nhìn bổ sung. Common mask, giới hạn thời gian thông tin, báo cáo counts và quy tắc undefined giúp các so sánh có thể kiểm tra và không che giấu dữ liệu thiếu. Kết luận thực nghiệm chỉ được đưa ra khi có kết quả chính thức theo đúng giao thức tương ứng.
