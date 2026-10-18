# Hợp đồng dữ liệu Walk-forward Evaluation — CPAWS

- **Trạng thái: Draft để Khải/Tuấn review; chưa phải hợp đồng đã phê duyệt.**
- Ngày soạn: 2026-10-18. Làm việc trên source giải nén cục bộ, không xác minh trạng thái merge từ xa.
- Phạm vi: hợp đồng đầu vào/đầu ra của hai chức năng sinh dự báo và đánh giá; không triển khai Python, không chọn hệ lưu trữ.
- Chỉ file này được tạo/chỉnh sửa trong nhiệm vụ. Không thay ADR, API contract, Accuracy Schema, code hoặc gói metrics đã bàn giao.

## 1. Mục tiêu, trạng thái và quy ước

Đủ thông tin để triển khai riêng `generate_forecasts(model, prices, cfg)` và `evaluate(forecasts, prices, cfg)`, phát hiện dự báo thiếu và truy vết nhãn/dữ liệu đã dùng.

Nhãn nguồn trong tài liệu:

| Nhãn | Ý nghĩa |
|---|---|
| **[ADR]** | Quy tắc đọc từ ADR-0008; phiên bản cụ thể được phân biệt ở mục 2. Không suy ra ADR đã được duyệt. |
| **[API]** | Cấu trúc trong `docs/api/contract.md`, nguồn chuẩn của DynamoDB/JSON API. |
| **[AS10]** | Accuracy Schema đọc từ ZIP PR #10; snapshot này có các điểm đã được review mới cập nhật, xem [REVIEW]. Không suy ra toàn bộ schema đã được duyệt. |
| **[REVIEW]** | Quyết định/cập nhật được nêu trong bản review người dùng cung cấp sau bản Draft 381 dòng; áp dụng theo yêu cầu sửa hiện tại. Không đồng nghĩa đã đọc trực tiếp file schema mới hơn ZIP hoặc kiểm chứng trạng thái merge. |
| **[SRC]** | Hành vi kiểm chứng được từ source cục bộ hoặc source trong ZIP được nêu tên. |
| **[YÊU CẦU]** | Thiết kế/bối cảnh nhóm cung cấp trong yêu cầu nhiệm vụ này. |
| **[ĐỀ XUẤT]** | Quyết định cụ thể của bản Draft này, cần review trước khi triển khai. |

Toàn bộ tên trường, enum, khóa và quy tắc giao tiếp mới ở mục 5–9 là **[ĐỀ XUẤT]**, trừ dòng có nguồn khác. Chữ “phải” trong các mục đó là tiêu chí của Draft, không phải tuyên bố nhóm đã duyệt.

`date` là ngày phiên ISO `YYYY-MM-DD`, không múi giờ; `timestamp` là ISO 8601 có UTC (`Z`). `number` phải hữu hạn. `null` là chưa có/không xác minh được/không áp dụng theo trường, khác `0` và `false`. Không serialize NaN/Infinity thành số JSON; không thay missing bằng 0.

## 2. Tài liệu nguồn và phụ thuộc thực tế

| Nguồn đã đọc | Tình trạng tại thời điểm soạn | Điều kiểm chứng/phụ thuộc |
|---|---|---|
| [ADR-0008 cục bộ](../adr/0008-target-quantiles-evaluation.md), mục 1–7 | Có trong thư mục `docs-adr-0008-review-fixes` | Target theo lịch; 7 phân vị; mask chung; crossing chỉ `all`; ranh giới nhãn. Header vẫn ghi đề xuất. |
| ADR-0008 trong `CPAWS-commodity-forecasting-feat-returns-adr0008 (1).zip` (bản PR #8 do người dùng cung cấp) | Đã đọc trực tiếp trong ZIP; không giải nén đè | Bản này ngắn hơn bản cục bộ ở mask, crossing, ranh giới split và thí nghiệm PCHIP. |
| [API contract cục bộ](../api/contract.md) và `docs/api/contract.md` trong ZIP Returns | Cả hai đã đọc | Cùng cấu trúc DynamoDB `q`/JSON `returns`; khác diễn đạt sign accuracy và một số minh họa. |
| `docs/api/accuracy-schema.md` trong `CPAWS-commodity-forecasting-docs-accuracy-schema.zip` (PR #10) | Đã đọc đủ; **chưa có bản cục bộ tại đường dẫn đích** | Snapshot trước các cập nhật trong [REVIEW]. Dùng review để cập nhật khóa, naive-zero và crossing, không giữ lại lựa chọn cũ đã được giải quyết. [Liên kết dự kiến — phụ thuộc PR #10](../api/accuracy-schema.md). |
| Bản review người dùng cung cấp sau Draft 381 dòng | Đã đọc trực tiếp | Nêu evaluation_kind/cutoff bắt buộc, naive-zero chỉ làm mẫu số, crossing thiếu raw là not_applicable; hợp đồng baseline-252 và ranh giới roll còn mở. Chưa có file schema mới hơn để kiểm tra nguyên văn. |
| [ADR-0002](../adr/0002-return-quantile-target.md) | Có cục bộ | Quyết định ban đầu; chi tiết 3 phân vị/MASE/input được ADR-0008 thay thế một phần. |
| [calendars.py](../../src/data/calendars.py), [config.py](../../src/data/config.py) | Có cục bộ | NYSE cho GLD/SLV; CME cho BZ=F/CL=F; lịch hiện giới hạn 2010–2030; công bố yfinance tạm D+1 12:00 UTC. |
| [clean.py](../../src/data/clean.py), [storage.py](../../src/data/storage.py) | Có cục bộ | Khóa `(date, asset)`; `published_at`, `ingested_at`, flag; snapshot `prices.parquet`/`rejected.parquet`; dòng `incomplete_bar` không lưu vào rejected. |
| [returns.py cục bộ](../../src/forecast/returns.py) | Có, **bản cũ** | Target dịch theo vị trí mảng; `prob_up` còn tự sửa bằng maximum-accumulate; không đáp ứng giao tiếp mục tiêu ADR-0008. Không sử dụng như bản triển khai mới. |
| `src/forecast/returns.py`, `src/forecast/baselines.py` trong ZIP Returns | Đã đọc; baselines chưa có cục bộ | Returns nhận Series/lịch/invalid_dates; sort một lần và trả crossing; baseline lấy các origin hoàn tất, tối thiểu 200. Chỉ là phụ thuộc tham khảo, chưa tích hợp. |
| [src/eval/metrics.py — liên kết phụ thuộc PR Metrics](../../src/eval/metrics.py) | Có trong snapshot cục bộ đã kiểm thử; chưa xác minh trên branch đích | Hàm thuần, DM nhận loss và trả NaN khi phương sai bằng 0. Snapshot cục bộ còn shim cũ, nhưng [REVIEW] cho biết PR Metrics đã xóa shim; hợp đồng này không phụ thuộc import cũ hoặc yêu cầu khôi phục shim. |
| `task.md`, `tasks.md`, `src/features/build.py` | Không tìm thấy trong source cục bộ; không có trong hai ZIP kèm nhiệm vụ | Chưa kiểm chứng giao tiếp features hoặc kế hoạch từ task file. |
| `src/eval/generate_forecasts.py`, `src/eval/evaluate.py` | Chưa có cục bộ hoặc trong hai ZIP | Kiến trúc mục tiêu theo [YÊU CẦU], không phải module hiện hữu. |

**Nguồn tham khảo và liên kết:** Các file trong ZIP hoặc snapshot của branch khác chỉ là tài liệu tham khảo thiết kế, không chứng minh file đã tồn tại trong branch chứa PR này. Bảng trên xác nhận sự tồn tại cục bộ, không xác nhận `developer` hoặc trạng thái merge. Liên kết ADR-0008 phụ thuộc PR #8; Accuracy Schema phụ thuộc PR #10; module metrics phụ thuộc PR Metrics. Trước tích hợp phải kiểm tra lại các đường dẫn trên branch đích sau khi PR phụ thuộc được merge; không coi liên kết mở được cục bộ là bằng chứng trên GitHub.

**Khác biệt phiên bản:** ADR trong ZIP Returns mục 4 nói thiếu baseline thì bỏ chỉ số *dùng mốc*, còn mục 5 nói mask chung; snapshot AS10 ZIP vẫn ghi câu hỏi này. ADR cục bộ đã làm rõ mask chung, ngoại lệ crossing và ranh giới nhãn. Draft giữ mask chung/crossing `all` theo **[YÊU CẦU] + ADR cục bộ**. Riêng khóa Accuracy, naive-zero và phân loại crossing áp dụng **[REVIEW]** mới hơn; không tiếp tục trình bày các lựa chọn cũ đó là câu hỏi cần phê duyệt lại.

## 3. Kiến trúc hai lớp

**[YÊU CẦU]** Luồng logic: `features → generate_forecasts → Internal Forecasts → evaluate → Detail → Accuracy`.

| Thành phần mục tiêu | Đầu vào | Trách nhiệm | Đầu ra |
|---|---|---|---|
| `src/eval/generate_forecasts.py` | Model cố định, prices/metadata đầu vào, cfg; giao tiếp với `build.py` chưa có | Đi qua lịch gốc; kiểm tra input point-in-time; model xuất `(7,7)`; ghi crossing thô; normalize đúng một lần; tính prob_up; giữ lần bỏ qua/lỗi | Internal Forecasts + metadata lần sinh và fits |
| `src/eval/evaluate.py` | Forecasts đã có, prices/rejected, cfg và metadata được cfg tham chiếu | Không gọi model, không normalize lại; dựng lịch kỳ vọng; tạo target/baseline; cutoff/mask; metrics/CI; ánh xạ status | Detail + Accuracy; log bộ đếm; comparison riêng khi có yêu cầu |

`evaluate()` nhận dự báo từ model, baseline phân phối hoặc nguồn đã lưu. Không bắt buộc gọi `generate_forecasts()` trong cùng tiến trình. `cfg` phải tham chiếu được các manifest/fits, snapshot giá, phiên bản lịch, giới hạn công bố, cấu hình bootstrap và hash bất biến; đây là giao tiếp đề xuất, không phải chữ ký Python đã triển khai.

MVP **[YÊU CẦU]**: train 2014–2018, validation 2019; model cố định, `retrain_every=None`, không retrain trong 2019, không early stopping trên 2019. Tham số có thể chọn bằng kết quả validation theo ADR, nhưng không dùng validation làm nhãn train hoặc dữ liệu fit scaler. Input cần lịch sử 2012–2013 có thể dùng làm warm-up, không biến thành nhãn train ngoài cấu hình. Test từ 2020 chỉ chạy theo chiến lược đã khóa; không dùng test chọn block length, ngưỡng hay nội suy.

## 4. Bốn loại dữ liệu khác nhau

| Dữ liệu | Mức hạt và mục đích | Quan hệ |
|---|---|---|
| API/DynamoDB `Forecasts` [API] | Một bản ghi tài sản/ngày gốc, nhiều horizons; phục vụ sản phẩm | Nguồn chuẩn là API contract; adapter có thể nhập thành Internal Forecasts |
| Internal Forecasts | Một dòng `(asset, base_date, h)` cho một nguồn/fit trong một lần sinh/nhập | Chưa có target tương lai; không thay DynamoDB, không thiết kế PK/SK |
| Detail | Một dòng dự kiến được chấm, thêm target/baseline/loss/cờ loại | Sinh cả dòng tổng hợp `no_forecast_row`; không nhân đôi cho hai sample |
| Accuracy [AS10] | Một metric/model/asset/h/sample/khoảng đánh giá/lần đánh giá | Tổng hợp từ Detail, giữ schema PR #10; fit_id không thêm vào khóa |

## 5. Internal Forecasts Schema

### 5.1. Trường và bất biến

Mọi cột dưới đây phải hiện diện; cột “Bắt buộc” phân biệt bắt buộc có giá trị và metadata tùy nguồn. `q05…q95` là **bảy cột riêng** theo thứ tự `(0.05,0.10,0.25,0.50,0.75,0.90,0.95)`.

| Trường | Kiểu logic | Bắt buộc | Null? | Giá trị/ý nghĩa | Kiểm tra |
|---|---|---|---|---|---|
| `forecast_run_id` | string | Có | Không | ID lần sinh hoặc nhập dự báo | Không rỗng; tham chiếu manifest bất biến |
| `model_version` | string | Có | Không | Nhóm kết quả của một phiên bản model | Không rỗng; nhất quán với fits/manifest |
| `fit_id` | string | Với nguồn có fit | Có | Bản huấn luyện cụ thể | FK tồn tại; null cho nguồn không có fit hoặc external_unverified thiếu chứng cứ theo mục 6 |
| `asset` | enum string | Có | Không | `gold`, `silver`, `brent`, `wti` | Khớp target series/lịch trong config |
| `base_date` | date | Có | Không | Phiên gốc của dự báo | Là phiên tài sản; thuộc lịch chạy; không đổi thành ngày tác vụ chạy |
| `h` | integer | Có | Không | Số phiên, `1..7` | Không nhận bool, số thập phân, hoặc ngày lịch |
| `q05`, `q10`, `q25`, `q50`, `q75`, `q90`, `q95` | number | Nếu status=ok | Có | Log return, không phải giá | Khi ok: đủ 7 số hữu hạn, không giảm; khi thất bại: tất cả null, không partial |
| `prob_up` | number | Nếu status=ok | Có | Xấp xỉ P(return>0), tuyến tính, chưa hiệu chỉnh | Khi ok: hữu hạn trong `[0.05,0.95]`, khớp q theo quy tắc mục 5.4; thất bại: null |
| `crossed_raw` | boolean | Cột có; chứng cứ tùy nguồn | Có | Crossing trước sort | true/false chỉ khi đã kiểm tra đủ 7 phân vị thô hữu hạn; không suy false từ q đã sort |
| `forecast_status` | enum string | Có | Không | `ok`, `invalid_input_window`, `generation_error` | Không nhận `no_forecast_row` từ bộ sinh/importer |
| `missing_reason` | enum string | Khi không ok | Có | Lý do bỏ qua/lỗi, mục 5.3 | null đúng khi ok; không dùng chuỗi tự do thay enum |
| `as_of_time` | timestamp UTC | Với nguồn verified | Có | Thời điểm phát hành thật hoặc giả lập khi input đã sẵn sàng | Điều kiện công bố mục 5.5; external thiếu chứng cứ được null |
| `provenance_status` | enum string | Có | Không | `verified_backtest`, `verified_production`, `external_unverified` | Các tên này là đề xuất; verified phải có metadata đủ kiểm tra |
| `created_at` | timestamp UTC | Tùy nguồn | Có | Thời điểm tạo/ghi bản ghi, không phải chứng cứ PIT | Import production giữ giá trị nguồn, không ghi đè bằng giờ import; batch lưu giờ import trong manifest |

### 5.2. Khóa, chạy lại và nhiều fit

Khóa logic đề xuất: `(forecast_run_id, model_version, fit_id, asset, base_date, h)`. Khi so trùng, null fit_id là **một giá trị “không có fit” duy nhất**, không dùng phép so sánh null của SQL để lọt dòng trùng. Không tạo fit giả cho nguồn không huấn luyện.

- Cùng khóa + payload giống hoàn toàn: lần nạp lại được coi idempotent, giữ một dòng và log; không tăng n_obs. Khác payload: từ chối batch, không chọn dòng cuối.
- Seed huấn luyện khác → fit_id mới; lần sinh/seed suy luận khác → forecast_run_id mới. Đổi dữ liệu, cấu hình hoặc model artifact không được ghi đè một run đã chốt.
- Đề xuất manifest mỗi forecast_run_id có `model_version`, seed, config_hash nguồn, artifact/snapshot IDs và lịch dự báo. Một model_version được phép có nhiều fit_id qua thời gian.
- Trong **một run/model/asset/base_date/h chỉ chọn một fit** theo manifest. Hai fit cùng dự báo một điểm không được trộn thành nhiều quan sát độc lập: tách forecast_run_id hoặc chọn trước một fit. Lịch fit tương lai phải không chồng lấp và có quy tắc hiệu lực bất biến.
- Không ghi đè run đã phát hành. Chạy lại chính xác để kiểm chứng có thể so byte/hash; nếu cần lưu kết quả khác thì tạo run mới.

### 5.3. Status và lần thử không thành công

| `forecast_status` | `missing_reason` | q/prob_up | Ý nghĩa |
|---|---|---|---|
| `ok` | null | Đầy đủ, hợp lệ | Dự báo dùng được; provenance được xét riêng |
| `invalid_input_window` | `input_nan`, `insufficient_input_history`, `input_not_available` | Tất cả null | Bỏ qua có giải thích do cửa sổ input không hợp lệ/chưa công bố |
| `generation_error` | `model_exception`, `invalid_model_output`, `upstream_failure` | Tất cả null | Lỗi model, output không hữu hạn/sai shape, hoặc sự cố phụ thuộc; log chi tiết theo run, không nhét traceback vào reason |
| `no_forecast_row` | `no_forecast_row` | Tất cả null | **Chỉ ở Detail**, evaluate tạo sau left join; không biết lần sinh đã xảy ra hay chưa |

Bộ sinh ghi một dòng cho mọi `(asset, base_date,h)` dự kiến. Input lỗi chung cho bảy h vẫn giữ bảy dòng thất bại; một h lỗi không xóa sáu h còn lại. Không lưu output NaN/inf thành hàng `ok`. `crossed_raw=null` khi không có bộ thô hữu hạn để kiểm tra; nếu đã kiểm tra được bộ thô rồi bước sau lỗi, có thể giữ true/false cùng audit evidence. [YÊU CẦU + ĐỀ XUẤT]

Điều này không mâu thuẫn production **[ADR/API]** “input NaN thì không ghi Forecasts mới”: Internal Forecasts là log lần thử nội bộ; không ghi dòng thất bại đó vào DynamoDB Forecasts.

### 5.4. Normalize, xác suất và crossing

**[ADR + SRC ZIP Returns]** Generate kiểm tra shape `(7,7)` và hữu hạn; ghi crossing trên trục phân vị; gọi `normalize_quantiles()` đúng một lần trên output hợp lệ; tính `prob_up` tuyến tính từ q đã sort. Importer chỉ nhận q đã chuẩn hóa, không tự sửa q. Evaluate xác thực không giảm, không normalize và không kẹp lại xác suất sai.

**[SRC ZIP Returns]** 0 dưới q05 → prob_up=0.95; trên q95 → 0.05; 0 trùng nhiều q → lấy mức phân vị cao nhất trong nhóm bằng 0. Quy tắc tie này cần Khải xác nhận vì ADR không mô tả đầy đủ trường hợp trùng nhiều mức.

**[ĐỀ XUẤT]** Dự báo nội bộ chưa làm tròn phải khớp hàm prob_up với dung sai tuyệt đối `1e-12` (ghi cfg). Bản production đã làm tròn cần profile riêng ở mục 10; không dùng dung sai tùy tiện để che sai thuật toán. Phương pháp nội suy là metadata bất biến trong manifest; mặc định linear, không ngầm chuyển PCHIP.

Crossing mask: `evaluation_start <= base_date <= evaluation_end AND crossed_raw IS NOT null`, với bằng chứng raw hữu hạn và dòng qua kiểm tra cấu trúc/provenance. `crossing_rate = count(crossed_raw=true)/count(crossed_raw IS NOT null)` riêng asset/h, `sample=all`; n_obs là mẫu số đó. Không dùng target, cutoff nhãn, baseline hay common_mask; target chưa có vẫn tính crossing. Không có chứng cứ ở một dòng → dòng đó không vào mẫu số, không suy false. [YÊU CẦU + ADR cục bộ]

Phân loại kết quả cho `sample=all` theo **[REVIEW]** (với dầu/excl_roll, dùng dòng `unsupported_sample` ở mục 9.3 trước khi xét khả năng cung cấp raw):

| Khả năng của nguồn / số quan sát đã kiểm tra | `status` | `value`, CI | `n_obs` | Lý do |
|---|---|---|---|---|
| Nguồn không cung cấp raw hoặc thông tin crossing có chứng cứ, không hỗ trợ đo chỉ số | `not_applicable` | null | 0 | Dùng mã thiếu raw đã có trong Accuracy Schema nếu được định nghĩa; mã mới còn cần review theo đoạn dưới |
| Nguồn hỗ trợ đo crossing nhưng không có bộ raw hữu hạn đủ điều kiện trong khoảng đang xét | `undefined` | null | 0 | `no_evaluable_obs` |
| Có ít nhất một bộ raw hữu hạn được kiểm tra | `ok` | Tỷ lệ hữu hạn; CI có thể null nếu chưa tính | Số bộ thực kiểm tra | null |

**Mã lý do thiếu raw:** ưu tiên đúng mã đã có trong Accuracy Schema, không tự đổi hoặc mở rộng danh mục. Snapshot schema trong ZIP đã đọc chưa xác định rõ mã riêng cho trường hợp này. `missing_raw_quantiles` **chỉ là tên đề xuất cần Khải review nếu schema chưa có mã tương ứng**, chưa được dùng như enum đã chốt hoặc xuất trong kết quả chính thức trước khi thống nhất. Không tự dùng `missing_quantiles` thay thế nếu nguồn vẫn có đủ bảy phân vị đã chuẩn hóa nhưng thiếu chứng cứ raw. Điều cần review là tên mã, không phải trạng thái `not_applicable` đã được xác nhận.

Đề xuất manifest khai boolean `supports_raw_crossing` theo nguồn/model/run để phân biệt khả năng đo với dữ liệu vắng ở một khoảng. Không suy capability=false chỉ vì tất cả crossed_raw hiện là null. Import DynamoDB không có raw/chứng cứ crossing khai capability=false; một run có capability=true nhưng không phát sinh raw hợp lệ thuộc trường hợp undefined. Thiếu khai báo capability phải được adapter làm rõ trước khi xuất status; không tùy ý chọn một trong hai. Tên trường manifest là đề xuất triển khai, không phải cột Accuracy mới.

### 5.5. Thời điểm và nguồn gốc

`as_of_time` là lúc phát hành/giả lập phát hành, **không phải** lúc evaluate hoặc ingest lại bản ghi. Với nguồn verified, phải có khả năng tra snapshot và kiểm tra:

1. `published_at(base_date) <= as_of_time`; **mọi** đầu vào, scaler/feature artifact phụ thuộc dữ liệu cũng phải sẵn sàng không muộn hơn as_of_time.
2. `as_of_time < published_at(target_date)` cho từng h; bằng thời điểm nhãn sẵn sàng cũng là quá muộn.
3. Snapshot và nhãn baseline dùng ở t không được mang revision chưa có ở as_of_time; kiểm tra date đơn thuần chưa bảo đảm điều này.

`published_at` hiện là **quy tắc công bố bảo thủ do config đặt**, không phải timestamp sàn được kiểm chứng; `ingested_at` là thời điểm nạp, không tự thay thế publication history. [SRC] Clean snapshot bị refetch/ghi đè theo khóa; snapshot mới nhất có thể chứa sửa giá về sau. [ĐỀ XUẤT] Manifest giữ snapshot URI/version/hash, phiên bản lịch/publication rule và max input publication time theo lần phát hành; nếu không có lịch sử revision thì hạ mức chứng cứ, không tự gắn verified.

| Tình trạng đề xuất | Chính sách evaluate |
|---|---|
| `verified_backtest` | Cần snapshot/cấu hình/fits và mô phỏng input as-of tái lập; trained_at thực tế có thể sau ngày lịch sử vì đây là backtest. Không coi replay hiện tại là dự báo production lịch sử. |
| `verified_production` | Cần timestamp phát hành thực, dữ liệu/artifact đã tồn tại trước phát hành; created_at riêng lẻ không đủ chứng minh. |
| `external_unverified` | Thiếu raw/fit/publication history: được chấm thống kê **thăm dò** nếu cấu trúc/nhãn hợp lệ, cảnh báo rõ PIT chưa xác minh. Tách run khỏi verified, không dùng như bằng chứng chọn model/so sánh chính thức. |
| Có chứng cứ vi phạm công bố/nhãn train hoặc FK/sai schema | Từ chối batch trước tính metrics; không “hạ thành external” để bỏ qua vi phạm đã biết. |
| Tự khai verified nhưng thiếu metadata bắt buộc | Từ chối chế độ verified; chỉ nhập lại thành external_unverified bằng quyết định rõ ràng có audit, không tự đổi nhãn. |

Các chính sách nguồn, enum và cách từ chối/cảnh báo là **[ĐỀ XUẤT CẦN KHẢI/TUẤN REVIEW]**. Không trộn provenance khác nhau vào cùng run kết quả; config/report phải chỉ rõ mức chứng cứ dù Accuracy chưa có cột provenance.

## 6. Fits metadata

Đề xuất cấu trúc `fits` riêng, khóa duy nhất `fit_id`; không tạo thuộc tính DynamoDB mới.

| Trường | Kiểu; null? | Quy tắc |
|---|---|---|
| `fit_id` | string; không | ID bất biến của artifact huấn luyện, seed khác/artifact khác có ID khác |
| `model_name`, `model_version` | string; không | Tên thuật toán và nhóm phiên bản; model_version khớp Forecasts |
| `train_end` | date; không | Giới hạn ngày gốc train khai báo, không thay cho ngày đích nhãn |
| `max_training_target_date` | date; không | Ngày đích muộn nhất trong mọi nhãn train/tuning nội bộ/early-stopping đã dùng để fit artifact |
| `max_training_label_available_at` | timestamp UTC; verified không null | Thời điểm nhãn train muộn nhất thực sự sẵn sàng; khác ngày đích |
| `trained_at` | timestamp UTC; không với fit có chứng cứ | Giờ tạo artifact thật; không đổi thành năm 2018 để giả lập backtest |
| `config_hash` | string; không | Hash cấu hình fit: data snapshot, seed, preprocessing/scaler, train split, target/calendar versions; khác hash đánh giá |

MVP validation 2019: `train_end <= 2018-12-31`, `max_training_target_date <= 2018-12-31`; các ngày gốc train thuộc 2014–2018. Nhãn origin cuối 2018 có target sang 2019 phải bị bỏ. `max_training_label_available_at <= as_of_time` đầu tiên dùng fit; nhãn ngày cuối 2018 công bố năm 2019 chỉ có thể dùng khi đã sẵn sàng, không tự gán khả dụng cuối năm. Không có nhãn validation dùng để fit/early stopping/scaler. [ADR ranh giới cục bộ + YÊU CẦU + ĐỀ XUẤT kiểm tra metadata]

Nguồn baseline không có fit → fit_id=null và manifest khai `no_training`; nguồn model có fit nhưng không khai ID không được giả làm baseline. Với external model không có fit metadata, chỉ chế độ unverified được chấp nhận, ghi rõ lý do trong manifest; không suy ra đã kiểm chứng train.

Tương lai retrain: mỗi forecast tham chiếu fit có nhãn đã công bố không muộn hơn as_of_time tương ứng; production còn yêu cầu trained_at không muộn hơn phát hành. Một model_version nhiều fit_id hợp lệ nếu manifest chọn đúng fit mỗi origin. Không cấm máy móc mọi dữ liệu từ 2020 trong mọi chế độ tương lai; phải chốt trước giao thức retrain và ngăn dùng nhãn chưa sẵn sàng. MVP vẫn từ chối retrain_every khác None. Metadata chỉ là khai báo/audit, không chứng minh tuyệt đối quá trình fit không rò rỉ.

## 7. Lịch ngày dự báo kỳ vọng

Cfg có `evaluation_start`, `evaluation_end`, `target_cutoff_date`, `evaluation_kind`, `horizons`, `assets`, `forecast_run_id` được chọn theo model_version và thời điểm evaluate `evaluation_as_of_time`. Theo **[REVIEW]**, `evaluation_kind` (`validation`, `test`, `rolling_8w`) và `target_cutoff_date` là **cột bắt buộc trong Accuracy và thuộc khóa logic**; không chỉ lưu trong cfg. Evaluate phải ghi đúng hai giá trị này trên mọi dòng kết quả. Giao tiếp các metadata cfg còn lại là đề xuất của Draft.

| Chế độ | Tập kỳ vọng | Điều kiện |
|---|---|---|
| validation/test lịch sử | Mọi phiên tài sản trong khoảng ngày gốc đóng `[start,end]` × các h cấu hình (MVP 1..7) | Lấy từ lịch, **không lấy từ các ngày còn giá hoặc có Forecasts**; giữ origin cuối kỳ dù target vượt cutoff để đếm loại |
| `rolling_8w` | Manifest phát hành production trong cửa sổ 8 tuần, có asset/base_date/h và nguồn model/run kỳ vọng | Không giả định phát hành mọi phiên. Cách neo 8 tuần, lịch phát hành và chính sách ingest/predict chưa có: **[CẦN KHẢI/TUẤN XÁC NHẬN]** |

Left join expected grid với Forecasts theo run/model/asset/base_date/h, lấy fit_id từ lịch fit đã khai. Thiếu dòng → Detail tổng hợp status/reason=no_forecast_row; fit_id lấy từ manifest hoặc null nếu nguồn không có fit. Không suy fit từ dòng lân cận. Giữ counters riêng cho invalid_input_window, generation_error và no_forecast_row.

Forecasts ngoài khoảng đang chấm được bỏ qua có đếm; dòng sai lịch hoặc h không hợp lệ bị từ chối ở validation cấu trúc, không đổi base_date. Snapshot giá bắt đầu quá muộn để tái tạo warm-up/cửa sổ input là lỗi chuẩn bị dữ liệu cần báo rõ hoặc lần thử insufficient_input_history; không lặng lẽ cắt ngày bắt đầu đánh giá. Một số origin có baseline dưới 200 là loại từng điểm, không tự làm mất cả run.

Thiếu manifest rolling_8w → không thể xác định no_forecast_row hoặc tuyên bố đủ coverage. Đề xuất từ chối báo cáo chính thức, chỉ cho chấm các dòng có sẵn dưới run thăm dò riêng có cảnh báo; không giả lập lịch production từ ingest cron.

## 8. Detail Schema

Khóa đề xuất `(run_id, forecast_run_id, model_version, fit_id, asset, base_date,h)`, null fit_id so trùng như mục 5.2. `run_id` là **lần evaluate**, khác forecast_run_id; cùng Forecasts có thể được evaluate với cutoff/config khác trong run_id mới.

Detail kế thừa **tất cả** cột Forecasts mục 5, cho phép thêm status=no_forecast_row. Không nhân bản một quan sát thành hai dòng all/excl_roll.

| Trường bổ sung | Kiểu; null? | Định nghĩa/kiểm tra |
|---|---|---|
| `run_id`, `config_hash` | string; không | ID/hash cấu hình đánh giá, liên kết Accuracy và manifest nguồn |
| `target_date` | date; không | Phiên thứ h sau base_date trên lịch tài sản; tính cả khi chưa có giá, không shift dòng |
| `evaluation_kind` | enum string; không | `validation`, `test`, `rolling_8w`; khớp cfg và cột bắt buộc trong Accuracy [REVIEW] |
| `target_cutoff_date` | date; không | Giới hạn ngày đích; khớp cfg và cột bắt buộc trong Accuracy [REVIEW] |
| `y_true` | number; có | ln(P_target/P_base); null khi endpoint không hợp lệ hoặc không được đọc vì cutoff/availability |
| `target_valid` | boolean; có | true khi hai endpoint hợp lệ và nhãn đã khả dụng; false khi đã kiểm tra thấy không hợp lệ; null khi chủ động chưa đọc vì cutoff |
| `target_invalid_reason` | enum string; có | null khi true; còn lại theo mục 9.1, không dùng null/0 thay thông tin thiếu |
| `within_cutoff` | boolean; không | target_date <= target_cutoff_date, luôn kiểm tra, không có cfg tắt |
| `missing_between_count` | integer >=0; có | Số phiên giữa `(base_date,target_date)` thiếu giá hợp lệ, do evaluate/hàm phụ tính từng cửa sổ; không lấy tổng từ Series.attrs; null nếu chưa kiểm tra; >0 không tự loại target |
| `baseline_q05`…`baseline_q95` | 7 number; có | Phân vị mốc trên cùng tập return h đã hoàn tất; null cả bộ khi baseline không hợp lệ |
| `baseline_prob_up` | number; có | **Tần suất** return>0 trên cùng tập baseline; `[0,1]`, không nội suy từ baseline_q và không kẹp `[.05,.95]` |
| `baseline_n_obs` | integer >=0; không | Số return hữu hạn, hợp lệ trong cửa sổ theo lịch tại origin |
| `baseline_valid` | boolean; không | Đủ >=200 trong cửa sổ 252 và output baseline hữu hạn; bất nhất count/output là lỗi module, không âm thầm bỏ điểm |
| `baseline_invalid_reason` | enum string; có | null nếu valid; `insufficient_history` hoặc `insufficient_valid_returns`; lỗi output được từ chối riêng |
| `forecast_valid` | boolean; không | status=ok, đủ q/prob, qua validation cấu trúc/xác suất; nguồn unverified có thể true nhưng run vẫn chỉ thăm dò |
| `roll_in_horizon` | boolean; có | Dầu: kết hợp expiry/flag theo mục 9.3; kim loại false; null nếu không đủ bằng chứng roll |
| `common_mask_all` | boolean; không | Công thức mục 9.2; không coi null target_valid là true |
| `common_mask_excl_roll` | boolean; có | Với dầu: common_mask_all AND roll_in_horizon=false; kim loại null (không áp dụng) |
| `model_pinball_loss`, `baseline_pinball_loss` | number >=0; có | Tính đủ 7 q, cùng y trên common_mask_all; ngoài mask để null |
| `exclusion_reason` | enum string; có | Lý do chính loại khỏi all theo ưu tiên mục 9.2; null nếu thuộc all |

**Baseline [ADR + SRC ZIP Returns]:** dùng `quantile_baseline`, `up_rate_baseline`, `baseline_valid` của Khải, không triển khai bản cạnh tranh trong evaluate. Trên lưới phiên đầy đủ, tại chỉ số t, origin s thuộc `[t−251,t−h]`; điều kiện s+h<=t là **vị trí lịch**, không cộng ngày lịch. Các NaN vẫn chiếm vị trí cửa sổ, không gom 252 return hợp lệ. Source ZIP dùng quantile interpolation linear. Adapter lọc rejected riêng từng asset, bảo đảm Series căn lịch/hữu hạn trước khi đưa vào module; output giữ index tương ứng.

Đề xuất thêm ràng buộc publication: return lịch sử dùng trong baseline phải khả dụng ở as_of_time của origin, cả endpoint và revision; điều kiện s+h<=t một mình chưa đủ chứng minh PIT. Source baseline trong ZIP chưa nhận publication timestamp; trách nhiệm xác thực nguồn nằm ở adapter/khung evaluate. Với nguồn external không có as_of_time đáng tin, chỉ xác minh được tính nhân quả theo ngày trên snapshot khai báo, phải ghi giới hạn này.

**Loss [ADR + SRC metrics]:** với τ theo đủ 7 mức, `L_t = sum(max(τ*(y-qτ), (τ-1)*(y-qτ)))/7`. Giữ hai cột loss để ghép ngày cho DM và resample block. `pinball_skill = 1 − mean(model_loss)/mean(baseline_loss)` trên cùng mask; **không** lấy trung bình skill từng dòng. Loss null ngoài mask không được tự điền 0.

## 9. Common mask, cutoff, missing và roll

### 9.1. Target và thời điểm nhãn

**[ADR + SRC ZIP Returns]** Giá hai đầu phải hữu hạn, >0, có trong clean và không nằm trong rejected **của đúng asset**. Cờ đánh dấu roll/low_liquidity/jump/xcheck/stale_source không tự loại giá. WTI âm được clean giữ nhưng target vẫn không hợp lệ. Thiếu phiên giữa không làm sai h hoặc tự hủy target; ghi missing_between_count và bộ đếm tổng.

**Trách nhiệm tính số phiên thiếu [SRC ZIP Returns + REVIEW]:** `horizon_log_returns()` hiện chỉ trả `Series.attrs["n_missing_between"]` là **tổng số target hợp lệ có ít nhất một phiên trung gian thiếu**, không phải số phiên thiếu từng dòng và cũng không phải tổng số phiên thiếu. Evaluate hoặc hàm phụ trợ phải căn lịch riêng từng asset, đánh dấu giá không hợp lệ (thiếu/rejected/không hữu hạn/không dương), rồi đếm các phiên không hợp lệ trong khoảng mở `(base_date,target_date)` cho từng dòng Detail. h=1 có 0 phiên trung gian; chưa kiểm tra do cutoff thì giữ null. Không gán giá trị attrs tổng cho mọi dòng, không cộng missing_between_count để diễn giải thành attrs; hai đại lượng đo khác nhau. Không cần sửa công thức target hoặc API Returns của Khải.

**[ĐỀ XUẤT]** Không đọc y sau cutoff để tính metric; giữ target_date nhưng y=null, target_valid=null, target_invalid_reason=`not_loaded_cutoff`. Với điểm trong cutoff, nhãn phải đã công bố không muộn hơn evaluation_as_of_time; chưa sẵn sàng → target_valid=false, reason=`label_not_available`. Khi có nhiều lỗi endpoint, reason chính theo thứ tự: `rejected_base`, `rejected_target`, `missing_base_price`, `missing_target_price`, `nonpositive_base_price`, `nonpositive_target_price`, `nonfinite_base_price`, `nonfinite_target_price`; kiểm tra publication sau các lỗi giá. Giữ audit endpoint để truy nguyên, không dùng rejected của silver loại gold cùng ngày.

`target_cutoff_date` ràng buộc ngày đích, còn start/end ràng buộc ngày gốc; validation 2019 dùng cutoff=2019-12-31. Ngày cutoff có thể là ngày lịch không giao dịch: chỉ target_date phiên <= cutoff được chấm. Target cuối 2019 sang 2020 vẫn có dòng Detail bị loại, không đọc giá tương lai để hoàn thiện metric validation. [AS10 + YÊU CẦU; ADR cục bộ mục 7]

### 9.2. Mask và lý do loại

Trên expected grid đã chọn run và trong start/end:

`common_mask_all = forecast_valid AND (target_valid IS true) AND baseline_valid AND within_cutoff`.

Áp dụng cho **mọi metric thông thường**, kể cả hit rates, coverage, width, interval score, Brier, up_rate. Sign accuracy dùng thêm `y_true != 0 AND q50 != 0`; crossing dùng mask riêng mục 5.4. Không để từng metric tự chọn ngày. [YÊU CẦU + ADR cục bộ; khác điểm còn chờ review trong AS10/ADR ZIP]

Ưu tiên exclusion_reason đề xuất: `outside_target_cutoff` → `no_forecast_row` → `invalid_input_window` → `generation_error` → `invalid_target` → `insufficient_baseline`; null khi thuộc all. Detail giữ target_invalid_reason, baseline_invalid_reason, missing_reason và cờ độc lập để không mất nguyên nhân chồng lấp. Dòng input sai cấu trúc/FK/chứng cứ rò rỉ bị từ chối trước bước tạo tập kết quả, không biến thành “thiếu dự báo”.

Log theo run/model/asset/h/sample: n_expected, n_received, n_common và các số loại tương ứng, gồm `excluded_insufficient_baseline`; tổng bộ đếm **lý do chính** bằng số dòng ngoài mask. Bộ đếm từng cờ có thể chồng lấp, không cộng thành tổng loại. `excluded_insufficient_baseline` chỉ là bộ đếm log, không phải mã `Accuracy.undefined_reason`; mask rỗng dùng quy tắc mục 11. Không thêm cột đếm vào Accuracy ở tuần đầu [AS10]; config/report giữ audit của run.

### 9.3. Roll và excl_roll

**[ADR]** Brent/WTI có thêm mẫu bỏ cửa sổ chứa đáo hạn hoặc phiên flag roll; GLD/SLV chỉ all. **[SRC]** calendars.py cung cấp cl_expiries/bz_expiries và roll_days; roll flag trong clean gắn phiên đầu sau expiry, không đồng nghĩa chính ngày expiry. BZ expiry dùng xấp xỉ ngày làm việc London bằng CME, cần giữ giới hạn này trong config/report.

**[ĐỀ XUẤT CẦN KHẢI REVIEW]** Cửa sổ target chọn các phiên trong `(base_date,target_date]` và kiểm tra **cả** expiry lẫn flag roll theo asset; boundary có tính base_date hay không chưa được ADR diễn đạt đủ chi tiết. Chưa xác nhận boundary thì không công bố excl_roll như kết quả đã chốt. Không suy ra không roll từ việc thiếu dòng clean: nếu không tái dựng đủ flag/expiry, roll_in_horizon=null, chưa xuất excl_roll chính thức và báo thiếu metadata; không đổi thành false.

Với dầu và metadata đủ: common_mask_excl_roll = common_mask_all AND NOT roll_in_horizon. Lý do loại riêng cho excl_roll là exclusion_reason của all nếu đã bị loại, nếu không thì `roll_window`; không sửa exclusion_reason all. `excluded_roll` chỉ đếm điểm vốn thuộc all. Kim loại: mask excl_roll=null, không tạo bản sao sample. Không nhân đôi Detail cho all/excl_roll. [YÊU CẦU + ĐỀ XUẤT]

**Quy tắc đã chốt cho crossing:** chỉ tính giá trị `crossing_rate` trên `sample=all`. Với **Brent/WTI và sample=excl_roll**, vẫn phải xuất dòng Accuracy `metric=crossing_rate`, `status=not_applicable`, `value=null`, `n_obs=0`, `undefined_reason=unsupported_sample` (CI=null/null). Đây là dòng thông báo metric không áp dụng, không phải tính crossing trên mask excl_roll và không cần nhân đôi Detail. Xét unsupported_sample trước khả năng cung cấp raw: dù nguồn có raw hay không, dòng dầu/excl_roll vẫn mang reason này. Quy tắc này không phụ thuộc quyết định boundary roll còn mở; không thêm sample excl_roll cho kim loại.

## 10. Ánh xạ với API/DynamoDB contract

**[API]** Contract cục bộ là nguồn chuẩn; bảng dưới chỉ định adapter, không sửa PK/SK hoặc JSON.

| Trường API/DynamoDB | Trường nội bộ Walk-forward | Quy tắc |
|---|---|---|
| `asset`, `base_date`, `model_version` | Cùng tên | Giữ nguyên; kiểm tra asset/lịch; không suy model fit từ version |
| `created_at` | `created_at` | Giữ thời gian nguồn; **không** tự gán as_of_time/provenance verified |
| `quantile_levels` | Thứ tự cố định q05,q10,q25,q50,q75,q90,q95 | Đủ đúng bảy mức, không chỉ q10/q50/q90 |
| `horizons[].h` | `h` | Unnest một horizon → một dòng; h phải duy nhất trong bản ghi |
| `horizons[].target_date` | Tính/đối chiếu `Detail.target_date` | Recompute theo lịch; lệch ngày → từ chối, không dùng shift dòng |
| DynamoDB `horizons[].q` | q05…q95 | Mảng 7 log return; không normalize lại |
| JSON `horizons[].returns` | q05…q95 | Tương ứng q lưu DynamoDB; **không** nhầm với `horizons[].prices` |
| `horizons[].prob_up` | `prob_up` | Giữ giá trị đã lưu và kiểm tra profile độ chính xác |
| `roll_in_horizon` ở cấp bản ghi | Metadata cảnh báo nguồn trong manifest | Một bool cho nhiều h chưa xác định được roll từng h; Detail tự xác định theo lịch/flags, không chép bool chung vào mọi h |
| `last_price`, `target_series`, `price_unit`, `horizons[].prices` | Manifest/hiển thị; không thay y_true | y_true dùng chuỗi target GLD/SLV/BZ=F/CL=F; giá quy đổi USD/oz, VND không phải target |

Adapter thêm forecast_run_id, fit_id (khi biết), provenance theo manifest. `fit_id`, crossed_raw, missing_reason và as_of_time mới không tự thành thuộc tính bắt buộc của DynamoDB. DynamoDB không có raw → crossed_raw=null; không suy false từ q không giảm. Một bản ghi h thành công không chứng minh những h/phiên khác đã được phát hành.

**Làm tròn [API + ĐỀ XUẤT]:** DynamoDB lưu Decimal làm tròn 6 chữ số. Import giữ q/prob đã lưu, manifest ghi độ chính xác và nguồn; không tái tạo “q gốc” hoặc thay p bằng phép tính lại trên q làm tròn. Đề xuất profile `stored_rounded`: xác thực p nằm trong khoảng, chỉ cảnh báo khác biệt nội suy do rounding, gắn giới hạn đo lường trong run/report; mâu thuẫn thuật toán đã có chứng cứ vẫn bị từ chối. Ngưỡng nhận biết lỗi thuật toán so với rounding cần Tuấn/Khải chốt, chưa coi bản import tương đương backtest đầy đủ chính xác. Không trộn profile này với internal_full_precision trong một Accuracy run.

## 11. Liên kết Accuracy Schema PR #10

Đây là bảng đối chiếu với **AS10 trong ZIP, cập nhật theo quyết định mới được nêu trong [REVIEW]**. Không tạo lại schema, không tuyên bố đã đọc file schema mới hơn chưa được cung cấp, và không coi các phần khác của Draft là đã được nhóm phê duyệt.

| Trường/quy tắc AS10 | Nguồn từ hợp đồng này | Trạng thái |
|---|---|---|
| Khóa `(run_id, model_version, asset, sample, evaluation_kind, evaluation_start, evaluation_end, target_cutoff_date, h, metric)` | run_id evaluate, model_version Forecasts và cfg/Detail | Khóa Accuracy theo [REVIEW]; evaluation_kind và target_cutoff_date bắt buộc, không còn phương án chỉ lưu cfg |
| `run_id`, `config_hash` | Metadata evaluate bất biến: input runs/fits/snapshots, calendar/publication versions, masks, interpolation/rounding, bootstrap | Không dùng forecast_run_id thay run_id; một run/model chọn đúng một nguồn mỗi origin |
| `evaluation_start/end`, `target_cutoff_date` | cfg và Detail | start/end theo origin; cutoff luôn kiểm tra và luôn lưu ở cột Accuracy, không null [REVIEW] |
| `evaluation_kind` | cfg/Detail: validation/test/rolling_8w | Cột Accuracy bắt buộc, thuộc khóa; không null, không suy ngầm từ ngày [REVIEW] |
| `model_version`, `asset`, `h`, `sample` | Nhóm các Detail đã chọn | Không thêm fit_id vào khóa; nhiều fit qua thời gian được nhóm theo model_version |
| `metric`, `value` | Hàm metrics trên mask | `pinball_loss` trong Accuracy gọi mean_pinball_loss, không gọi hàm legacy một tau |
| `quantile_hit_0.05`…`quantile_hit_0.95` | Từng khóa quantile_hit_rates | Bảy dòng dài; API pivot thành đối tượng quantile_hit_rates |
| `n_obs` | Số điểm thực đi vào metric | Thường n_common; sign loại hai loại 0; crossing/all đếm raw; dòng crossing dầu/excl_roll là 0 với unsupported_sample |
| `status`, `undefined_reason` | Bộ chuyển dòng kết quả | Giữ enum ok/undefined/not_applicable của AS10; không ghi NaN/inf thành value |
| `ci_low`, `ci_high` | Block bootstrap trên đúng mask | Có thể null/null khi chưa triển khai hoặc CI không tính được; value hợp lệ vẫn status=ok; cấu hình/log phân biệt lý do |

Giữ status AS10 với các quy tắc đã chốt: tính được → ok/value hữu hạn; mẫu số=0 khi có quan sát → undefined/zero_denominator và **giữ n_obs**. Khi common_mask không còn quan sát, **bất kể vì baseline thiếu hay nguyên nhân khác**, metric áp dụng dùng `status=undefined`, `value=null`, `n_obs=0`, `undefined_reason=no_evaluable_obs` (CI=null/null). Không dùng `insufficient_baseline` hoặc `excluded_insufficient_baseline` làm Accuracy.undefined_reason; `excluded_insufficient_baseline` chỉ là bộ đếm trong log. Reason `insufficient_baseline` ở Detail vẫn chỉ giải thích điểm bị loại, không chuyển thành mã lý do của Accuracy.

Thiếu capability model → not_applicable/missing_quantiles hoặc missing_prob_up, không điền q/p giả. Crossing/all: nguồn không hỗ trợ raw là not_applicable, mã lý do theo mục 5.4; nguồn hỗ trợ nhưng không có điểm là undefined/no_evaluable_obs. Crossing với Brent/WTI, sample=excl_roll: **luôn xuất** not_applicable/unsupported_sample, value=null, n_obs=0 theo mục 9.3, không áp quy tắc mask rỗng cho metric không áp dụng này.

**Naive-zero trong MVP [REVIEW + ADR]:** chỉ làm **mẫu số** `mean(abs(y_true))` của `mae_ratio_vs_naive` cho mô hình đang được đánh giá, trên cùng common mask. Evaluate tính mốc return=0 bên trong; **không tạo nguồn dự báo/adapter model độc lập cho naive-zero, không xuất bất kỳ dòng Accuracy nào có model_version=naive-zero**, kể cả dòng not_applicable. Không tính sign_accuracy riêng cho Naive, không giả lập bảy phân vị hoặc prob_up. Nếu mẫu số=0, dòng ratio của model hiện tại là undefined/zero_denominator và giữ n_obs. Đây là phạm vi MVP đã được review xác nhận, không còn là câu hỏi mở.

Baseline-252 có thể làm nguồn model phân phối để evaluate khi cần, fit_id=null và nguồn no_training; q/p theo baseline, không suy p bằng nội suy q. Vì p baseline là tần suất có thể bằng 0/1, **giao tiếp Internal Forecasts mục 5 chỉ dành nguồn có prob_up nội suy/kẹp ADR**; đề xuất adapter baseline phân phối có capability/profile riêng trong evaluate, không ghi sai một hàng ok theo schema đó. Khải cần chốt có mở rộng profile Internal Forecasts hay giữ adapter riêng; chưa triển khai mở rộng ngầm.

**DM/Holm [ADR + AS10]:** bảng model_comparison riêng. Ghép cặp theo asset/base_date/h và cùng cutoff/snapshot, giao các mask của hai model rồi dùng hai loss cùng ngày; không ghép theo vị trí sau lọc độc lập. d=PL_A−PL_B, âm nghĩa A loss nhỏ hơn. HAC lag>=h−1, HLN, p hai phía t(T−1); phương sai không dương/constant diff → undefined, giữ số cặp đã xét. Holm dùng họ định trước, không bỏ các vị trí test không xác định khỏi kích thước họ. Không dùng naive-zero cho DM pinball 7 q.

**CI [ADR + AS10 + SRC metrics]:** moving-block bootstrap theo trục ngày, giữ pairing loss; seed/block length/confidence/n_resamples khóa trong cfg trước test. Với skill phải resample cùng model/baseline và tính lại tỷ số của hai mean, không bootstrap skill từng điểm. Khi tổng hợp nhiều asset/h, dùng cùng block ngày (căn lịch và missingness được quy định trong cfg), không resample độc lập từng cột. Hàm thuần chỉ resample hàng, không tự căn lịch; adapter chịu trách nhiệm. Replicate không hữu hạn làm CI undefined/null theo metrics hiện có, không lặng lẽ bỏ replicate. MVP chưa CI phải ghi giới hạn này, không tuyên bố đã đáp ứng đầy đủ CI theo ADR.

## 12. Ví dụ dữ liệu tổng hợp

Các ví dụ không là giá/dự báo tài chính thật; timestamps là giả định metadata có chứng cứ. Ví dụ chỉ hiển thị một horizon, không thay yêu cầu generator giữ cả bảy lần thử. fit-demo có metadata hợp lệ theo mục 6; source/config/snapshot IDs ở manifest.

**12.1. Một Internal Forecasts hợp lệ (profile internal_full_precision)**

```json
{"forecast_run_id":"forecast-demo-01","model_version":"demo-fixed","fit_id":"fit-demo","asset":"gold","base_date":"2019-01-02","h":1,"q05":-0.03,"q10":-0.02,"q25":-0.01,"q50":0.0,"q75":0.01,"q90":0.02,"q95":0.03,"prob_up":0.5,"crossed_raw":false,"forecast_status":"ok","missing_reason":null,"as_of_time":"2019-01-03T12:00:00Z","provenance_status":"verified_backtest","created_at":null}
```

**12.2. Lần thử input NaN**

```json
{"forecast_run_id":"forecast-skip-demo-01","model_version":"demo-fixed","fit_id":"fit-demo","asset":"gold","base_date":"2019-01-02","h":2,"q05":null,"q10":null,"q25":null,"q50":null,"q75":null,"q90":null,"q95":null,"prob_up":null,"crossed_raw":null,"forecast_status":"invalid_input_window","missing_reason":"input_nan","as_of_time":"2019-01-03T12:00:00Z","provenance_status":"verified_backtest","created_at":null}
```

Ví dụ 12.2 thuộc run minh họa khác 12.1; nếu cùng một cửa sổ input dùng cho mọi h bị NaN thì cả bảy h phải được ghi bỏ qua.

**12.3. Phần bổ sung Detail cho dòng 12.1** — ghép toàn bộ trường Forecasts với đối tượng sau; giá tổng hợp hai đầu được chọn bằng nhau nên y=0. Baseline đủ lịch sử trong giả định minh họa.

```json
{"run_id":"eval-demo-01","config_hash":"sha256:illustration","evaluation_kind":"validation","target_date":"2019-01-03","target_cutoff_date":"2019-12-31","y_true":0.0,"target_valid":true,"target_invalid_reason":null,"within_cutoff":true,"missing_between_count":0,"baseline_q05":-0.06,"baseline_q10":-0.04,"baseline_q25":-0.02,"baseline_q50":0.0,"baseline_q75":0.02,"baseline_q90":0.04,"baseline_q95":0.06,"baseline_prob_up":0.5,"baseline_n_obs":240,"baseline_valid":true,"baseline_invalid_reason":null,"forecast_valid":true,"roll_in_horizon":false,"common_mask_all":true,"common_mask_excl_roll":null,"model_pinball_loss":0.0017142857142857146,"baseline_pinball_loss":0.0034285714285714293,"exclusion_reason":null}
```

Kiểm chứng số học đủ 7 mức: model loss từng tau = `[0.0015,0.002,0.0025,0,0.0025,0.002,0.0015]`; tổng=0.012, chia 7. Baseline gấp đôi q → tổng loss=0.024, chia 7; skill trên ví dụ một điểm là 0.5. Vì y=q50=0, dòng vẫn thuộc common nhưng **không** vào sign_accuracy; n_obs(sign)=0. Không dùng các số này như kết quả model thật.

**12.4. Unnest DynamoDB (trích hai horizons trong bản ghi có đủ 7)**

```json
{"asset":"gold","base_date":"2019-01-02","model_version":"demo-fixed","created_at":"2019-01-03T12:15:00Z","quantile_levels":[0.05,0.10,0.25,0.50,0.75,0.90,0.95],"horizons":[{"h":1,"target_date":"2019-01-03","q":[-0.03,-0.02,-0.01,0,0.01,0.02,0.03],"prob_up":0.5},{"h":2,"target_date":"2019-01-04","q":[-0.03,-0.02,-0.01,0,0.01,0.02,0.03],"prob_up":0.5}],"roll_in_horizon":false}
```

Đây là trích đoạn minh họa, không phải bản ghi production đầy đủ mọi trường contract. Mỗi h thành một dòng nội bộ với q05…q95 tương ứng; cả hai có forecast_run_id=`import-demo-01`, fit_id=null nếu không có metadata, crossed_raw=null, provenance_status=external_unverified, as_of_time=null, created_at giữ nguyên. Không tự gán verified từ created_at. Target_date chỉ có ở Detail sau khi adapter đối chiếu lịch; JSON API dùng `returns` thay `q` nhưng cùng thứ tự. Muốn xác nhận verified_production phải bổ sung chứng cứ ngoài bản ghi này.

## 13. Test cases / acceptance criteria (chưa viết pytest)

| # | Tình huống / đầu vào | Kết quả mong muốn | Chịu trách nhiệm |
|---|---|---|---|
| 1 | Đủ 7 q hữu hạn, không giảm, p đúng | Hàng ok; không normalize thêm ở evaluate | generate/evaluate |
| 2 | Raw q10>q25, đủ 7 số | crossed_raw=true trước sort; normalize đúng 1 lần, p tính sau sort | generate |
| 3 | Nguồn ngoại nhập q đã sort, không cung cấp raw/chứng cứ crossing và capability=false, sample=all | crossed_raw=null; crossing not_applicable/value=null/n_obs=0; dùng mã schema đã có hoặc chờ review mã thiếu raw, không tự dùng mã đề xuất | adapter/evaluate |
| 4 | Cửa sổ input có NaN | Giữ hàng invalid_input_window/input_nan, q/p null, tính bộ đếm riêng | generate |
| 5 | Expected grid có điểm không có Forecasts | Tạo Detail no_forecast_row, không coi là input_nan | evaluate |
| 6 | Trùng khóa kể cả fit_id=null | Payload giống: dedup idempotent; khác: từ chối, không double count | adapter/evaluate |
| 7 | Có fit_id nhưng không có fits tương ứng | Từ chối FK; không tự bỏ fit_id hoặc tự gắn baseline | fits metadata/evaluate |
| 8 | Fit validation dùng nhãn target_date năm 2019 | Từ chối; train_end 2018 không che được nhãn vượt ranh giới | fits metadata |
| 9 | Một input published_at>as_of_time | Không sinh dự báo từ input đó; ghi input_not_available; verified import có vi phạm thì từ chối | generate/adapter |
| 10 | as_of_time trước base publication hoặc >= target publication | Từ chối xác nhận phát hành hợp lệ; created_at không cứu được | adapter/evaluate |
| 11 | h=7, origin cuối 2019, target sang 2020 | Giữ Detail, within_cutoff=false; không đọc y, không vào common, tăng boundary counter | evaluate |
| 12 | Không có giá đúng phiên target | y=null, target_valid=false/missing_target_price; không lùi/tiến sang dòng khác | evaluate |
| 13 | Hai cửa sổ có lần lượt 1 và 2 phiên giữa không hợp lệ, hai đầu đều hợp lệ | y vẫn đúng h lịch; evaluate tính missing_between_count lần lượt 1 và 2; attrs tổng đếm 2 target, không gán 2 cho cả hai dòng | evaluate/hàm phụ trợ |
| 14 | rejected chỉ có `(silver,D)`, gold có giá hợp lệ D | Chỉ target silver chịu loại; gold không bị loại theo date đơn thuần | evaluate |
| 15 | Baseline chỉ có 199 return hợp lệ | baseline_valid=false; loại khỏi mọi metric thường, kể cả coverage/width | evaluate/Baselines adapter |
| 16 | Sửa/nối giá sau base_date, giữ snapshot as-of trước origin | q/p/count baseline tại origin không đổi | evaluate/Baselines adapter |
| 17 | WTI/Brent có expiry hoặc roll trong cửa sổ đã chốt, có hoặc không có raw | Thuộc all nếu đủ điều kiện, không thuộc excl_roll; crossing/excl_roll vẫn xuất Accuracy not_applicable/value=null/n_obs=0/unsupported_sample, kể cả mask rỗng; không nhân đôi Detail | evaluate |
| 18 | y=0 hoặc q50=0 trong common | Không vào sign; các metric thường khác vẫn dùng; crossing độc lập | evaluate |
| 19 | Không còn điểm common vì baseline thiếu, thiếu target hoặc nhiều nguyên nhân | Metric áp dụng: undefined/value=null/n_obs=0/no_evaluable_obs; excluded_insufficient_baseline chỉ đếm trong log, không dùng làm undefined_reason | evaluate |
| 20 | Nhập DynamoDB 6 chữ số, không raw | crossed_raw=null; profile rounded, ghi giới hạn p/q; không normalize hoặc tái tính thay p đã lưu | adapter |
| 21 | Một model_version có hai fit_id sau retrain | MVP từ chối retrain; giao thức tương lai chọn fit theo origin, không double count | fits metadata/evaluate |
| 22 | q chứa NaN/Infinity, thiếu một mức hoặc crossing ở hàng ok | Generate ghi invalid_model_output; import ok sai cấu trúc bị từ chối, không thay 0 | generate/adapter |
| 23 | base_date không là phiên NYSE/CME tương ứng | Từ chối trước join, không dịch sang phiên gần nhất | adapter/evaluate |
| 24 | Return WTI hai đầu có giá <=0 dù clean chấp nhận giá âm | y=null/target_valid=false; không lấy log abs(price) | evaluate |
| 25 | Mean baseline loss=0 với n_common>0 | Skill undefined/zero_denominator, giữ n_obs; loss/coverage khác vẫn có thể tính | evaluate |
| 26 | crossing có raw nhưng target chưa có hoặc baseline thiếu | Vẫn tính crossing/all trong khoảng origin; unknown raw không biến false; dòng dầu/excl_roll là not_applicable/unsupported_sample | evaluate |
| 27 | Thiếu manifest rolling_8w | Không tuyên bố đủ lịch/đếm missing chính thức; từ chối run chính thức hoặc run thăm dò có cảnh báo | evaluate/adapter |
| 28 | Hai run model có ngày missing khác nhau | DM ghép giao theo khóa ngày/h; không ghép theo vị trí vector | evaluate |
| 29 | Skill từng dòng có baseline=0, nhưng baseline mean trên common>0 | Tính tỷ số hai mean; không lấy mean skill từng dòng hoặc bỏ dòng baseline=0 | evaluate |
| 30 | Timestamp công bố bằng as_of_time; target publication bằng as_of_time | Input được dùng với <=; target ở ngưỡng bằng bị từ chối vì cần < | generate/evaluate |
| 31 | Future revision nằm trong snapshot mới nhất | Không tự xác nhận PIT; phải có snapshot as-of hoặc external_unverified | adapter/fits metadata |
| 32 | Lookup lịch ra ngoài phạm vi 2010–2030 hiện có | Lỗi cấu hình/phụ thuộc rõ ràng; không coi rỗng lịch là không có expected forecast | evaluate |
| 33 | Nguồn hỗ trợ crossing nhưng không có raw hữu hạn đủ điều kiện trong khoảng đánh giá | crossing undefined/no_evaluable_obs, value/CI=null, n_obs=0; khác nguồn không hỗ trợ raw ở case 3 | evaluate |
| 34 | Xuất Accuracy thiếu/null evaluation_kind hoặc target_cutoff_date | Từ chối hàng sai schema; cả hai trường bắt buộc và có trong khóa logic | evaluate/bộ chuyển dòng |
| 35 | Tính mae_ratio_vs_naive cho model thông thường | Mẫu số là mean(abs(y)) trên common; không sinh hàng Accuracy model_version=naive-zero hoặc sign riêng cho Naive | evaluate |

Hoàn thành thiết kế khi các câu hỏi mục 14 đã có quyết định được ghi nhận; hoàn thành triển khai về sau cần test các bất biến trên. Tài liệu này không tuyên bố code walk-forward đã tồn tại hoặc đã vượt các acceptance tests.

## 14. Những điểm cần Khải/Tuấn review

| Người review | Quyết định còn mở | Đề xuất của Draft / tác động |
|---|---|---|
| Khải | Hợp đồng baseline-252 như nguồn dự báo để so sánh DM | Chọn profile Internal Forecasts mở rộng hay adapter riêng; p là tần suất `[0,1]`, không ép nội suy/kẹp như AI. Không bao gồm naive-zero, vốn chỉ là mẫu số. |
| Khải | Boundary roll, expiry và dữ liệu flag thiếu | Đề xuất `(base_date,target_date]`; unknown roll không giả false; chốt trước excl_roll |
| Khải/Tuấn | Lịch production/manifest và cửa sổ rolling_8w | Không suy lịch predict từ ingest cron; chốt neo cửa sổ, expected emissions, freshness và thời điểm nhãn |
| Khải/Tuấn | Làm tròn, import production, provenance enums/policy | Chốt tolerance/profile và metadata chứng minh phát hành; created_at không tự là as_of_time |
| Khải | CI, ghép ngày multi-asset và họ Holm | Khóa block/seed/confidence, quy tắc ngày không giao dịch/missingness và họ all/excl_roll trước test; không tự coi 7 h độc lập |

Hai quyết định nghiệp vụ còn mở được [REVIEW] nêu rõ là hợp đồng baseline-252 và boundary roll. Các dòng về production, làm tròn và CI là chi tiết triển khai còn thiếu bằng chứng/cấu hình, không phải yêu cầu phê duyệt lại khóa Accuracy, vai trò naive-zero hay cách phân biệt status crossing. Giao tiếp features và snapshot point-in-time vẫn là phụ thuộc triển khai đã ghi ở mục 2–3/5.5, không làm thay đổi những quyết định đã được xác nhận.

Riêng **tên mã lý do thiếu raw** ở mục 5.4: đối chiếu và ưu tiên mã Accuracy Schema đã có; nếu cần thêm `missing_raw_quantiles` thì Khải phải review tên mã mới trước khi dùng. Không mở lại các quy tắc đã chốt: crossing dầu/excl_roll xuất not_applicable/unsupported_sample và common_mask rỗng dùng undefined/no_evaluable_obs dù thiếu baseline.

Đề xuất commit message (chỉ văn bản): `docs(eval): draft walk-forward data contract`.

Đề xuất Draft PR title (chỉ văn bản): `docs: Walk-forward evaluation data contract`.
