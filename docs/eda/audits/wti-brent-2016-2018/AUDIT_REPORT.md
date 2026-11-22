# Audit WTI/Brent — hai phiên 2016 và đối chiếu 05/12/2018

Ngày audit: 28/10/2026. Trạng thái: **hoàn thành audit local với các giới hạn được nêu rõ**, chưa xác minh độc lập lịch settlement chính thức hoặc nguyên nhân thị trường/vendor.



> **Phạm vi bàn giao PR #47:** Các file `scripts/run_audit.py`, `scripts/build_reports.py`, `scripts/input_inventory.json`, `scripts/evidence.json` và log pytest là script/artifact của lần chạy audit local, **không nằm trong repository hoặc PR này**. PR chỉ bàn giao báo cáo, summary và các bảng evidence đã commit. Không thể tái chạy đầy đủ audit chỉ từ PR.

## Executive summary
Đã kiểm tra 3 ngày × 2 assets. Cả sáu trường hợp đều thiếu row trong raw futures lưu trong ZIP, thiếu trong clean và không có row rejected. Đây là **missing source row so với calendar hiện hành**, không phải lỗi rejection đã được chứng minh. EIA có giá spot tham chiếu, nhưng không thể dùng sự tồn tại của spot để chứng minh futures có settlement hay để điền nhãn futures.

Mỗi sự kiện/asset tạo 14 cặp target endpoint không hợp lệ (7 missing base + 7 missing target), còn 21 cặp chỉ đi qua ngày thiếu ở giữa vẫn có target hợp lệ. Hai sự kiện năm 2016 làm invalid 61 feature windows mỗi sự kiện, hợp lại 85 windows/asset vì 37 windows chồng lấn. Đây là tác động dựng lại bằng helper hiện tại; số mẫu thực tế bị loại trong training không có log để xác minh.

301 invalid forecast rows mỗi asset trong Validation 2019 được nối với **2018-12-05**, không phải hai ngày 2016. Không phát hiện bug trong cách xử lý target endpoint/interior hoặc feature window thuộc phạm vi kiểm tra; chưa đủ bằng chứng kết luận calendar sai. Chưa đề nghị sửa code/dataset tự động. Giữ dữ liệu, ghi nhận gap và yêu cầu đối chiếu lịch settlement theo instrument/nguồn vendor.

## 1. Input, phiên bản và bảo toàn
ZIP1–ZIP4 là bốn file được đính kèm bằng đường dẫn thực tế, không tìm một bản repository khác để thay thế:

| ZIP | filename | SHA-256 |
|---|---|---|
| 1 | CPAWS-commodity-forecasting-developer (2).zip | 5ef0987d4c23979e9831d5df9069f2279b6c914a06274485dcd422d133c68021 |
| 2 | data-20261018T113233Z-1-001.zip | b94b20beb7136c0db3598dfb9577b2c904572cbf3137cdc8da16d35d77b2d3a0 |
| 3 | CPAWS_Validation_2019_Drive_Review.zip | dd616f2aa2f4807b9b1099c60f596e0b85b77c393af5c03a922e6a32bb08d934 |
| 4 | cpaws-validation-2019-diagnostics-results.zip | 2a71860d6f7c43db71c43495910a28aa30da5cfde19da4a5a99ca3a2939126eb |

Tên trong prompt có thêm hậu tố `(2)(4)/(3)/(4)/(1)` nhưng đường dẫn đính kèm dùng tên trong bảng trên; báo cáo dùng chính các đường dẫn đính kèm. CRC và member hashes được ghi trong artifact local `scripts/input_inventory.json` và bản summary được commit tại `evidence/audit_summary.json`. Các bản source tham chiếu đã đọc ở lượt bị ngắt được đối chiếu byte với ZIP hiện tại trước khi import. Không suy phiên bản từ filename hoặc timestamp.

Cả 8 file chung giữa ZIP3 và ZIP4 có SHA-256 giống nhau: forecasts, detail, accuracy, model_comparison, manifest, log và hai CSV diagnostics/report. Chỉ phân tích **một run**. ZIP3 cũng khớp SHA-256 đã ghi trong audit 2018 trước đó; mọi kết luận lần này vẫn được tính lại từ input hiện tại. Không có hash lịch sử để chứng minh mọi ZIP khác đã thay đổi hay chưa so với tất cả bản cũ trên máy.

12/13 module trong manifest implementation khớp source developer hiện tại; khác: `src/forecast/baselines.py`. Các module calendar/config/returns/features/walk_forward/metrics liên quan trực tiếp audit đều khớp. Không gọi baseline hoặc đánh giá lại metrics bằng source mới. Tài liệu hiện tại được đọc theo ZIP1; không mở lại hoặc xử lý DM/HAC/Holm/K4.

Snapshot: `2026-10-09`. Run: `validation-2019-kaggle-diagnostics-v1`; forecast run `dlinear-2019-kaggle-diagnostics-forecasts`; model `dlinear-41e13dc5de3d`; config hash `87afd46a20e44a00032b383a9e0ab9410f2c1e8dadc0e8d555243d18af054767`; provenance `backtest_publication_rule`. Hash prices/rejected/quality trong ZIP2 khớp source-artifacts manifest của run.

## 2. Calendar: điều gì được chứng minh
`ZIP1::src/data/calendars.py:30` (`def _sessions(`) lấy valid days của `CMEGlobex_EnergyAndMetals`, rồi bỏ những phiên early-close mà NYSE nghỉ. Cả ba ngày thuộc CME của CPAWS và thuộc valid schedule của thư viện; **không ngày nào nằm trong early_closes của thư viện ở runtime audit**. Hai ngày 2016 là phiên NYSE; 05/12/2018 không là phiên NYSE. Riêng việc NYSE nghỉ không đủ để CPAWS loại ngày đó: rule còn yêu cầu CME early-close.

Phân biệt ba mức: (1) lịch thư viện có trading session; (2) thư viện có đánh dấu early close hay không; (3) có settlement chính thức của từng instrument hay không. Audit đã kiểm tra (1), (2) và rule CPAWS; **(3) chưa được xác minh**. Không có tài liệu settlement chính thức độc lập được dùng từ bốn ZIP. Không dùng tên ngày lễ hoặc EIA spot để suy ra sàn đóng/mở hay settlement. Cờ `official_settlement_verified=False` nghĩa là chưa xác minh, không phải khẳng định không có settlement.

Không có bằng chứng đủ để gọi calendar mismatch là root cause. Nếu sau này xác nhận mismatch, target_date theo h phiên có thể đổi; số lượng thay đổi đó hiện **unknown**, không ghi 0.

## 3. Raw → clean → rejected và EIA
| asset | audit_date | calendar_session | raw_present | clean_present | rejected_present | eia_values | nyse_session |
|---|---|---|---|---|---|---|---|
| wti | 2016-10-10 | True | False | False | False | ["49.76"] | True |
| wti | 2016-11-11 | True | False | False | False | ["43.39"] | True |
| wti | 2018-12-05 | True | False | False | False | ["52.64"] | False |
| brent | 2016-10-10 | True | False | False | False | ["51.54"] | True |
| brent | 2016-11-11 | True | False | False | False | ["41.61"] | True |
| brent | 2018-12-05 | True | False | False | False | ["61.4"] | False |

Raw futures: `ZIP2::data/lake/raw/yfinance/dt=2026-10-07/CL_F.csv`, `BZ_F.csv` và `.csv.gz`; đối chiếu thêm `.csv.gz` ngày 08/10 và 09/10. Bản 07/10 và 08/10 bao phủ lịch sử từ 2012, đều thiếu cả ba ngày. Bản 09/10 chỉ chứa 2026-10-01–2026-10-09: **ngoài phạm vi ngày audit**, không tính thành một bằng chứng độc lập về lịch sử thiếu. Bản CSV/gzip cùng snapshot cũng không phải hai nguồn độc lập. `scripts/evidence.json` lưu bounds, row presence và các row lân cận cho từng member.

Clean/rejected: `ZIP2::data/lake/clean/prices/dt=2026-10-09/`. Không có sáu khóa asset/date trong cả prices lẫn rejected. `ZIP1::src/data/clean.py:76` (`def bars_to_long(`) chỉ phân loại các thanh có sẵn; không thể gán một rejection reason cho row vốn không xuất hiện trong raw. `merge_snapshot()` giữ các khóa lịch sử không bị override; `src/data/storage.py` lưu snapshot theo dt. Audit không gọi ghi storage hay rebuild clean.

EIA: RWTC/RBRTE JSON ngày 07/10 và 08/10 có ba ngày audit. JSON 09/10 là incremental ngoài phạm vi lịch sử. Giá cùng ngày (USD/bbl): 10/10/2016 RWTC 49.76, RBRTE 51.54; 11/11/2016 RWTC 43.39, RBRTE 41.61; 05/12/2018 RWTC 52.64, RBRTE 61.40. Đây là **spot reference**, CL=F/BZ=F vẫn là target theo `src/data/config.py` và ADR-0005. Các row lân cận được lưu đầy đủ trong evidence, bảng ở phụ lục. Không trộn giá spot vào futures.

`ZIP1::src/data/quality.py:340` (`def asset_report(`) tính calendar.difference(price dates), không yêu cầu rejected row. Tái dựng khớp quality: WTI tổng 5 missing sessions, Brent 23; mỗi asset năm 2016 có 2, năm 2018 có 1. `missing_sessions_sample` chỉ lấy 20 ngày đầu: Brent không liệt kê ba ngày audit vì quota đã hết ở 2014, **không phải quality bỏ sót**. Dùng counts theo năm và reindex thực tế để kết luận.

## 4. Target: endpoint và nội bộ khác nhau
ADR-0008 mục 1 và `ZIP1::src/forecast/returns.py:91` (`def _horizon_log_returns_on_calendar(`): `y(t,h)=ln(P(t+h)/P(t))`, h=1..7 theo calendar, không dịch theo row quan sát. Audit gọi nguyên helper và kiểm tra giá trị với hai endpoint, không viết công thức thay thế cho production.

| Mỗi sự kiện, mỗi asset | Số cặp | Kết quả |
|---|---:|---|
| audit_date là base_date | 7 | NaN vì thiếu base price |
| audit_date là target_date | 7 | NaN vì thiếu target price |
| audit_date nằm giữa hai endpoint | 21 | Hai endpoint hợp lệ; return hữu hạn; missing_between_count=1 |

Các cặp cụ thể, h và target_date có trong `audit_impact.csv`. Với h=1 không có cặp interior; tổng h=2..7 là 1+2+3+4+5+6=21. Mỗi asset có 28 cặp endpoint invalid từ hai sự kiện 2016; cộng đối chiếu 2018 thành 42 cặp. Không cộng số target invalid với số feature invalid để suy số mẫu training, vì các loại có thể chồng lấn và training có thể yêu cầu đủ cả vector 7 targets.

## 5. Feature windows và mức độ lan truyền
`ZIP1::src/features/build.py:201` (`def make_windows(`), `build_feature_frame()`: 60 phiên feature `log_return_1_end`, bao gồm base_date, cần 61 giá liên tiếp. Thiếu giá tại d làm NaN feature kết thúc ở d và phiên tiếp theo. Window phải đủ lịch sử, có mọi feature valid và availability; không fill hoặc nén lịch. Cột flag/roll không tự làm feature invalid.

| asset/date | n_windows | first | last | train_windows | validation_windows |
|---|---|---|---|---|---|
| wti/2016-10-10 | 61 | 2016-10-10 | 2017-01-05 | 61 | 0 |
| wti/2016-11-11 | 61 | 2016-11-11 | 2017-02-09 | 61 | 0 |
| wti/2018-12-05 | 61 | 2018-12-05 | 2019-03-05 | 18 | 43 |
| brent/2016-10-10 | 61 | 2016-10-10 | 2017-01-05 | 61 | 0 |
| brent/2016-11-11 | 61 | 2016-11-11 | 2017-02-09 | 61 | 0 |
| brent/2018-12-05 | 61 | 2018-12-05 | 2019-03-05 | 18 | 43 |

Mỗi asset: union hai sự kiện 2016 = 85 windows, overlap = 37; toàn bộ nằm trong train period 2014–2018 (đuôi tới 2017). Sự kiện 2018 có 18 windows trong train và 43 trong validation. Union ba sự kiện có 103 windows ở train, 43 ở validation mỗi asset. Các số này là số cửa sổ có thể dựng từ snapshot và source, **không phải số mẫu đã được xác nhận loại khỏi một job train cụ thể**. Không có manifest/log sample-level training đủ để nối vào trọng số model; ảnh hưởng gián tiếp tới dự báo/metric vẫn chưa định lượng.

`audit_impact.csv` dùng khóa gồm asset, audit_date, impact_type, base_date, h. Khi một window chứa cả hai sự kiện 2016, file có hai dòng liên kết nguyên nhân; `all_audit_causes` chỉ rõ chồng lấn. Muốn đếm windows duy nhất phải distinct(asset,base_date), không cộng các dòng. Dòng target, feature và observed forecast là các đối tượng khác nhau.

Ba ngày nguồn không trùng expiry hoặc roll theo helper hiện tại. Không quy nguyên nhân trực tiếp cho roll. Thiếu feature availability do giá thiếu không tự chứng minh published_at bị trễ. Không thay cutoff hay common masks.

## 6. Diagnostics và Validation 2019
Schema thực tế ghi trong audit_summary.json. Detail dùng `target_valid`, `target_invalid_reason`, `missing_between_count`, `common_mask_all`, `common_mask_excl_roll`, `exclusion_reason`; không tự tạo cột target_invalid. Forecasts có `forecast_status` và `missing_reason`.

`ZIP1::src/eval/walk_forward.py:720` (`def _make_detail(`): common sample cần forecast hợp lệ, target hợp lệ, baseline hợp lệ và within cutoff. Primary exclusion theo thứ tự: outside_target_cutoff → no_forecast_row → invalid_input_window → generation_error → invalid_target → insufficient_baseline. Vì là ưu tiên loại mẫu, counter không thể thay thế mọi nguyên nhân đồng thời. `ZIP1::src/eval/walk_forward.py:942` (`def _summarize(`): excluded_missing_price đếm primary invalid_target; excluded_invalid_input_window đếm primary invalid_input_window; excluded_insufficient_baseline đếm primary insufficient_baseline. excl_roll thêm loại horizon có roll/expiry trong (base,target], khác với input invalid.

Các metric thông thường dùng common mask; sign_accuracy bỏ thêm y=0 hoặc q50=0; crossing_rate dùng raw crossing flags của forecast hợp lệ và là ngoại lệ. Accuracy/metrics không được tính lại trong audit. Bộ đếm được đọc từ log và đối chiếu với Detail/Forecasts, không gán chúng cho sự kiện 2016.

| Mỗi asset dầu trong kết quả gốc | Rows |
|---|---:|
| Tổng Forecasts/Detail | 1764 |
| invalid_input_window / input_nan | 301 |
| outside_target_cutoff | 28 |
| common_mask_all | 1435 |
| target invalid bên trong cutoff | 0 |

Trong 1736 targets bên trong cutoff, `missing_between_count` tổng bằng 0; 28 target ngoài cutoff ghi `not_loaded_cutoff`, không phải 28 lỗi missing price. Hai ngày 2016 không nằm ở endpoint hoặc feature input của validation. Tái dựng feature-only cho origins 2019 khớp đúng 43 ngày invalid của Forecasts mỗi asset, từ 2019-01-02 đến 2019-03-05, đều phụ thuộc gap 2018-12-05. 301 = 43×7 là số quan sát tính lại, không hardcode để tạo dữ liệu. Không chạy inference/evaluate, không tạo run validation mới.

## 7. Root cause và hành động theo ngày
| Ngày | Kết luận chắc chắn cho cả WTI/Brent | Chưa xác minh | Hành động tối thiểu |
|---|---|---|---|
| 2016-10-10 | Thiếu row futures trong raw lịch sử, clean; không rejected; calendar CPAWS có phiên | Vì sao vendor/raw thiếu, settlement chính thức | Ghi nhận gap, yêu cầu Data đối chiếu instrument/vendor; giữ nguyên |
| 2016-11-11 | Cùng hiện tượng được kiểm tra riêng; ảnh hưởng windows kéo tới 2017 | Nguyên nhân thị trường có giống 10/10 hay không | Ghi nhận riêng, không giả định cùng nguyên nhân |
| 2018-12-05 | Thiếu raw/clean; liên kết trực tiếp 301 invalid rows/asset của 2019 | Lý do thiếu và tính đúng calendar settlement | Giữ case đối chiếu; chờ bằng chứng trước khi sửa |

Mức chắc chắn cao cho **absence trong các file được cung cấp và hậu quả theo code hiện tại**; chưa đủ cho kết luận nguồn bên ngoài sai hoặc calendar sai. Không phát hiện bug thực sự trong logic endpoint/interior/window được kiểm tra. Khác hash baselines là khác phiên bản, không tự coi là bug. Chưa có căn cứ sửa dữ liệu hoặc production code; nếu lịch/nguồn sau này chứng minh có lỗi, đề xuất change và regression test riêng, không triển khai ở audit này. Không điền EIA, forward-fill hoặc nội suy; không chỉnh metric để cải thiện kết quả.

## 8. Kiểm thử, giới hạn và acceptance
- 1482 assertions audit đạt: integrity, snapshot lineage, raw absence, target validity/formula, feature linkage, counts và input preservation.
- Pytest thực chạy trên source ZIP1: **68 passed**, 0 failures, 0 errors, 0 skipped. Chỉ 3 file: data clean/quality, returns ADR0008 và feature builder. Log/JUnit nằm trong scripts. Không chạy toàn bộ suite hay test model/evaluation.
- Runtime local khác Kaggle; version được ghi trong reproduction. Không tuyên bố bitwise reproducibility của inference hoặc full evaluation. Snapshot dùng quy tắc publication, không phải historical vintage đã kiểm chứng.
- Không có lịch settlement chính thức độc lập; chưa định lượng calendar mismatch hoặc tác động trọng số/performance. Actual training exclusions ghi null, không 0.
- Audit local hoàn thành đủ 6 cặp và mọi deliverable; các phần không thể xác minh được giới hạn công khai, không tuyên bố đã xác minh market root cause.
- Không sửa source chính thức, dữ liệu input, model, manifest/log/Validation 2019; không dùng mạng, Git, GitHub, AWS hoặc model selection.

## Phụ lục — EIA cùng ngày và lân cận
Nguồn bảng: raw EIA JSON 07/10/2026 trong ZIP2; chỉ tham chiếu, không thay futures. Raw futures/clean lân cận và tên member cụ thể có trong `scripts/evidence.json`.

### wti/2016-10-10 — EIA ngày lân cận
| date | EIA spot USD/bbl |
|---|---|
| 2016-10-06 | 50.44 |
| 2016-10-07 | 49.76 |
| 2016-10-10 | 49.76 |
| 2016-10-11 | 50.72 |
| 2016-10-12 | 50.14 |
### wti/2016-11-11 — EIA ngày lân cận
| date | EIA spot USD/bbl |
|---|---|
| 2016-11-09 | 45.2 |
| 2016-11-10 | 44.62 |
| 2016-11-11 | 43.39 |
| 2016-11-14 | 43.29 |
| 2016-11-15 | 45.86 |
### wti/2018-12-05 — EIA ngày lân cận
| date | EIA spot USD/bbl |
|---|---|
| 2018-12-03 | 52.98 |
| 2018-12-04 | 53.21 |
| 2018-12-05 | 52.64 |
| 2018-12-06 | 51.54 |
| 2018-12-07 | 52.76 |
### brent/2016-10-10 — EIA ngày lân cận
| date | EIA spot USD/bbl |
|---|---|
| 2016-10-06 | 50.14 |
| 2016-10-07 | 50.49 |
| 2016-10-10 | 51.54 |
| 2016-10-11 | 50.48 |
| 2016-10-12 | 49.53 |
### brent/2016-11-11 — EIA ngày lân cận
| date | EIA spot USD/bbl |
|---|---|
| 2016-11-09 | 43.88 |
| 2016-11-10 | 43.67 |
| 2016-11-11 | 41.61 |
| 2016-11-14 | 41.83 |
| 2016-11-15 | 44.15 |
### brent/2018-12-05 — EIA ngày lân cận
| date | EIA spot USD/bbl |
|---|---|
| 2018-12-03 | 60.17 |
| 2018-12-04 | 61.22 |
| 2018-12-05 | 61.4 |
| 2018-12-06 | 57.83 |
| 2018-12-07 | 61.71 |
