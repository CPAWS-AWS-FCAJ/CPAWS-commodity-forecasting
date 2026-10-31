# Hợp đồng dữ liệu Walk-forward Evaluation — CPAWS

- **Trạng thái: đã duyệt cho MVP validation 2019; cập nhật Rolling MVP 2026-10-30 theo RFC [#45](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/45) v4.6 (PR [#65](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/65)); external import/PIT nâng cao vẫn phase 2.**
- Ngày soạn: 2026-10-18; cập nhật review Khải PR #12: 2026-10-19. Làm việc trên source giải nén cục bộ, không xác minh trạng thái merge từ xa.
- Phạm vi: hợp đồng đầu vào/đầu ra sinh dự báo và đánh giá; bổ sung storage/lifecycle Rolling MVP tại §7 theo RFC #45 v4.6, không triển khai Python.
- Bản cập nhật 30/10 chỉ đồng bộ hai Contract API/Walk-forward; không sửa ADR, Accuracy Schema, code, fingerprint K4 hoặc kết quả đã bàn giao. Các ghi chú source ở §2 và §14.2 là đối chiếu lịch sử khi soạn 19/10, không xác nhận tình trạng deploy hiện tại.

## 1. Mục tiêu, trạng thái và quy ước

Đủ thông tin để triển khai **một module `src/eval/walk_forward.py`** với hai chức năng logic độc lập: sinh dự báo từ model đã fit và đánh giá Forecasts đã có. Các tên `generate_forecasts(...)`/`evaluate(...)` bên dưới chỉ chức năng trong cùng module, không yêu cầu file riêng hoặc xác lập API Python mới. Giữ schema Forecasts/Detail/Accuracy, phát hiện dự báo thiếu và truy vết dữ liệu đã dùng.

Nhãn nguồn trong tài liệu:

| Nhãn | Ý nghĩa |
|---|---|
| **[ADR]** | Quy tắc đọc từ ADR-0008; phiên bản cụ thể được phân biệt ở mục 2. Không suy ra ADR đã được duyệt. |
| **[API]** | Cấu trúc trong `docs/api/contract.md`, nguồn chuẩn của DynamoDB/JSON API. |
| **[AS10]** | Accuracy Schema đọc từ ZIP PR #10; snapshot này có các điểm đã được review mới cập nhật, xem [REVIEW]. Không suy ra toàn bộ schema đã được duyệt. |
| **[REVIEW]** | Quyết định/cập nhật được nêu trong bản review người dùng cung cấp sau bản Draft 381 dòng; áp dụng theo yêu cầu sửa hiện tại. Không đồng nghĩa đã đọc trực tiếp file schema mới hơn ZIP hoặc kiểm chứng trạng thái merge. |
| **[KHẢI12]** | Những quyết định Khải đã xác nhận trên PR #12, được người dùng cung cấp ngày 2026-10-19; thay các phương án cũ tương ứng. Phạm vi MVP validation 2019 đã được Khải duyệt; các phần production/phase 2 tại mục 5.5, 7 và 10 còn chờ Tuấn review. |
| **[SRC]** | Hành vi kiểm chứng được từ source cục bộ hoặc source trong ZIP được nêu tên. |
| **[YÊU CẦU]** | Thiết kế/bối cảnh nhóm cung cấp trong yêu cầu nhiệm vụ này. |
| **[ĐỀ XUẤT]** | Quyết định cụ thể của bản Draft này, cần review trước khi triển khai. |

Riêng Rolling MVP tại §7 được cập nhật 2026-10-30 theo quyết định thiết kế RFC [#45](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/45) v4.6 (PR [#65](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/65)). Các thiết kế khác chưa có xác nhận ở mục 5–9 vẫn là **[ĐỀ XUẤT]**; quy tắc gắn [KHẢI12] là quyết định đã được review cung cấp, không mở lại để lựa chọn. Việc cập nhật không đồng nghĩa reviewer đã phê duyệt toàn bộ phiên bản tài liệu này.

`date` là ngày phiên ISO `YYYY-MM-DD`, không múi giờ; `timestamp` là ISO 8601 có UTC (`Z`). `number` phải hữu hạn. `null` là chưa có/không xác minh được/không áp dụng theo trường, khác `0` và `false`. Không serialize NaN/Infinity thành số JSON; không thay missing bằng 0.

## 2. Tài liệu nguồn và phụ thuộc thực tế

| Nguồn đã đọc | Tình trạng tại thời điểm soạn | Điều kiểm chứng/phụ thuộc |
|---|---|---|
| [ADR-0008 cục bộ](../adr/0008-target-quantiles-evaluation.md), mục 1–7 | Có trong snapshot; [KHẢI12] thông báo ADR đã merge vào developer, không tự kiểm chứng từ xa | Giữ target/phân vị/mask/cutoff; header snapshot cũ vẫn ghi đề xuất. Không sửa ADR trong nhiệm vụ này. |
| ADR-0008 trong ZIP Returns đã cung cấp trước đây | Nguồn tham khảo lịch sử; không giải nén đè | Các khác biệt snapshot trước đây không mở lại mask/cutoff đã được xác nhận. Trạng thái merge ADR lấy từ thông báo Khải, không từ tên ZIP. |
| [API contract cục bộ](../api/contract.md) và `docs/api/contract.md` trong ZIP Returns | Cả hai đã đọc | Cùng cấu trúc DynamoDB `q`/JSON `returns`; khác diễn đạt sign accuracy và một số minh họa. |
| `docs/api/accuracy-schema.md` trong `CPAWS-commodity-forecasting-docs-accuracy-schema.zip` (PR #10) | Đã đọc đủ; **chưa có bản cục bộ tại đường dẫn đích** | Snapshot trước các cập nhật trong [REVIEW]. Dùng review để cập nhật khóa, naive-zero và crossing, không giữ lại lựa chọn cũ đã được giải quyết. [Liên kết dự kiến — phụ thuộc PR #10](../api/accuracy-schema.md). |
| Bản review người dùng cung cấp sau Draft 381 dòng | Đã đọc trực tiếp; review PR #12 dưới đây cập nhật tiếp | Giữ evaluation_kind/cutoff bắt buộc, naive-zero chỉ làm mẫu số và status crossing; các câu hỏi baseline/roll của bản này đã được [KHẢI12] giải quyết. |
| Review Khải PR #12 được cung cấp ngày 2026-10-19 | Đã đọc trực tiếp; cập nhật mới hơn review trên | Chốt baseline chỉ ở Detail, roll, bootstrap/CI, DM/Holm, publication-rule provenance, Fits tối giản và một module triển khai; xem mục 14. |
| [ADR-0002](../adr/0002-return-quantile-target.md) | Có cục bộ | Quyết định ban đầu; chi tiết 3 phân vị/MASE/input được ADR-0008 thay thế một phần. |
| [calendars.py](../../src/data/calendars.py), [config.py](../../src/data/config.py) | Có cục bộ | NYSE cho GLD/SLV; CME cho BZ=F/CL=F; lịch hiện giới hạn 2010–2030; công bố yfinance tạm D+1 12:00 UTC. |
| [clean.py](../../src/data/clean.py), [storage.py](../../src/data/storage.py) | Có cục bộ | Khóa `(date, asset)`; `published_at`, `ingested_at`, flag; snapshot `prices.parquet`/`rejected.parquet`; dòng `incomplete_bar` không lưu vào rejected. |
| [returns.py cục bộ](../../src/forecast/returns.py) | Có, **bản cũ** | Target dịch theo vị trí mảng; `prob_up` còn tự sửa bằng maximum-accumulate; không đáp ứng giao tiếp mục tiêu ADR-0008. Không sử dụng như bản triển khai mới. |
| PR #13: `CPAWS-commodity-forecasting-feat-returns-adr0008 (2).zip` | Đã đọc source trực tiếp trong ZIP mới; PR mở/được review theo [KHẢI12]; baselines/forecast_record chưa có trong source cục bộ | API target/normalize/prob_up và quantile_baseline/up_rate_baseline/constant_prob_baseline/baseline_valid được đối chiếu trong ZIP; không nhập code hoặc suy đã merge. |
| [src/eval/metrics.py — phụ thuộc PR #11](../../src/eval/metrics.py) | PR #11 đã cập nhật theo review Khải; chờ hoàn tất tích hợp trước merge | DM sử dụng uniform HAC (trọng số đều) và HLN; có pinball_loss_per_origin và crossing_rate. Bootstrap helper không tự căn lịch nhiều asset, việc này thuộc Walk-forward orchestration. |
| PR #14: `src/features/build.py` trong `CPAWS-commodity-forecasting-feat-features-build.zip` | Đã đọc source trực tiếp trong ZIP mới; chưa có file cục bộ; PR phụ thuộc PR #13 | Đối chiếu đủ build_feature_frame/make_windows/latest_base_date, FeatureBatch và reason/timestamp ở mục 3.1; không viết lại logic hoặc suy đã merge. |
| `task.md`, `tasks.md` | Không tìm thấy cục bộ | Không suy thêm kế hoạch từ task file không có. |
| `src/eval/walk_forward.py` | Chưa có cục bộ | Module MVP đã chốt theo [KHẢI12]; chỉ là kế hoạch triển khai, không tạo trong nhiệm vụ này. |

**Nguồn tham khảo và liên kết:** File trong ZIP/snapshot không chứng minh trạng thái branch đích. ADR-0008 đã merge theo thông báo của Khải; Accuracy là PR #10, Metrics PR #11, Returns/Baselines PR #13 và Feature Builder PR #14. Chưa tuyên bố các PR còn lại đã merge; chỉ triển khai khi API tương ứng được cung cấp/kiểm chứng. Liên kết mở được cục bộ không là bằng chứng GitHub. Không lấy commit bằng Git trong nhiệm vụ này.

**Khác biệt phiên bản:** Giữ mask/cutoff/status và số học đã được Khải xác nhận đúng ADR; các câu hỏi cũ trong snapshot ZIP không mở lại quyết định đó. Khóa Accuracy/naive/crossing giữ theo [REVIEW]; những thay đổi phạm vi MVP và orchestration áp dụng [KHẢI12]. ADR cục bộ nói CI cho mọi metric; review chốt MVP bắt buộc CI pinball_skill, CI khác triển khai giai đoạn 2 trừ yêu cầu bắt buộc khác của hợp đồng cấp trên. Báo cáo phải nêu phạm vi CI đã thực hiện, không tự sửa ADR hoặc tuyên bố MVP đã tính mọi CI.

## 3. Hai chức năng trong một module Walk-forward

**[KHẢI12]** Module duy nhất: `src/eval/walk_forward.py`. Luồng logic: `PR #14 build_feature_frame → make_windows → sinh dự báo → Internal Forecasts → ghép target/baseline → Detail → Accuracy`.

| Thành phần mục tiêu | Đầu vào | Trách nhiệm | Đầu ra |
|---|---|---|---|
| Sinh dự báo trong `walk_forward.py` | Model cố định, FeatureBatch từ make_windows, scaler của fit và cfg | Giữ expected origins; kiểm tra input/publication; scale và chuyển float32; model xuất `(7,7)`; crossing raw, normalize một lần, prob_up | Internal Forecasts + metadata lần sinh và fits |
| Đánh giá trong cùng `walk_forward.py` | Forecasts model đã có, prices/rejected, cfg và fits | Không gọi model hoặc normalize; target từ Returns, baseline từ Baselines; cutoff/mask; metrics/CI từ PR #11 | Detail + Accuracy; log bộ đếm; comparison riêng khi cần |

Chức năng đánh giá nhận Forecasts của mô hình thật, có thể đã lưu từ lần sinh trước; không bắt buộc chạy model cùng tiến trình. **Baseline-252 không là một nguồn Internal Forecasts hoặc model giả**; nó được tính bằng PR #13 và gắn vào Detail. `cfg` tham chiếu fits, snapshot giá, lịch/publication rule và seed/config đánh giá; các kiểm tra vintage đầy đủ thuộc chế độ PIT/giai đoạn 2, không là điều kiện bắt buộc cho publication-rule MVP.

MVP **[YÊU CẦU]**: train 2014–2018, validation 2019; model cố định, `retrain_every=None`, không retrain trong 2019, không early stopping trên 2019. Tham số có thể chọn bằng kết quả validation theo ADR, nhưng không dùng validation làm nhãn train hoặc dữ liệu fit scaler. Input cần lịch sử 2012–2013 có thể dùng làm warm-up, không biến thành nhãn train ngoài cấu hình. Test từ 2020 chỉ chạy theo chiến lược đã khóa; không dùng test chọn block length, ngưỡng hay nội suy.

### 3.1. Feature Builder PR #14 — API Khải công bố, đã đối chiếu ZIP

| API | Output / trách nhiệm đã công bố |
|---|---|
| `build_feature_frame(prices, asset, *, invalid_dates=None)` | asset, feature_session_date, log_return_1_end, feature_valid, feature_reason, feature_available_at; invalid_dates xét riêng asset |
| `make_windows(frame, base_dates, window=60) -> FeatureBatch` | X NumPy float64 `[N,L,1]`; valid, reason, base_dates, input_session_dates, max_input_published_at; asset, feature_names, window |
| `latest_base_date(frame)` | Ngày gốc có giá cuối cùng, phục vụ predict production giai đoạn 2; không thay expected grid validation và không tự chứng minh window hợp lệ |

**make_windows là nơi duy nhất cắt input windows.** Walk-forward không tự trượt L phiên, căn return lại, forward-fill, drop dòng thiếu trước khi cắt, hoặc viết fallback khi API chưa có. Luồng validation 2019 theo asset: lấy base_dates từ lịch phiên → gọi make_windows với `window=cfg.window` → giữ mọi base_dates trong audit. Với valid=False không gọi model; với valid=True kiểm tra max_input_published_at<=as_of_time, dùng scaler đã fit từ train và chuyển float32 cho model, xuất đủ 7 h × 7 q. Không fit scaler lại trên 2019.

**Integration note từ source ZIP:** FeatureBatch giữ thứ tự base_dates caller truyền, không bỏ hàng invalid; valid=False có thể để X chứa NaN và max_input_published_at=NaT. Mảng timestamp max_input_published_at là `datetime64[ns]` không mang timezone nhưng **giá trị là UTC**; tầng orchestration gắn UTC khi so với as_of_time, không diễn giải thành giờ máy hoặc normalize về ngày. valid=True vẫn cần kiểm tra NaT/publication; không sửa builder để bỏ qua thiếu metadata. feature_available_at ở frame là timestamp UTC có timezone. latest_base_date trả phiên cuối frame, không lùi về cửa sổ hợp lệ gần nhất; production behavior này ở phase 2.

| FeatureBatch.reason khi valid=False | forecast_status | missing_reason |
|---|---|---|
| `invalid_input_window` | `invalid_input_window` | `input_nan` |
| `insufficient_input_history` | `invalid_input_window` | `insufficient_input_history` |

Publication metadata thiếu/không xác định không được suy cửa sổ đủ điều kiện chỉ vì X hữu hạn; phải tra được quy tắc nguồn để kiểm tra hoặc ghi nhận không đủ bằng chứng/không phát hành. Một vi phạm publication đã biết giữ lý do input_not_available riêng theo mục 5.3/5.5, không đổi thành target/baseline failure hoặc no_forecast_row. Nếu PR #14 phát sinh reason ngoài hai mã đã công bố thì cần integration note đối chiếu API, không tự tạo mapping/logic window mới.

## 4. Bốn loại dữ liệu khác nhau

| Dữ liệu | Mức hạt và mục đích | Quan hệ |
|---|---|---|
| API/DynamoDB `Forecasts` [API] | Một bản ghi tài sản/ngày gốc, nhiều horizons; phục vụ sản phẩm | Nguồn chuẩn là API contract; adapter có thể nhập thành Internal Forecasts |
| Internal Forecasts | Một dòng `(asset, base_date, h)` cho một nguồn/fit trong một lần sinh/nhập | Chưa có target tương lai; không thay DynamoDB, không thiết kế PK/SK |
| Detail | Một dòng dự kiến được chấm, thêm target/baseline/loss/cờ loại | Sinh cả dòng tổng hợp `no_forecast_row`; không nhân đôi cho hai sample |
| Accuracy [AS10] | Một metric/model/asset/h/sample/khoảng đánh giá/lần đánh giá | Tổng hợp từ Detail, giữ schema PR #10; fit_id không thêm vào khóa |

## 5. Internal Forecasts Schema

Schema nội bộ dưới đây giữ cho historical evaluation và external import. Rolling MVP đọc Forecasts production theo API Contract và eligibility §7; không bắt buộc tạo Fits/manifest phát hành mới hoặc mở rộng Forecasts production bằng toàn bộ cột nội bộ.

### 5.1. Trường và bất biến

Mọi cột dưới đây phải hiện diện; cột “Bắt buộc” phân biệt bắt buộc có giá trị và metadata tùy nguồn. `q05…q95` là **bảy cột riêng** theo thứ tự `(0.05,0.10,0.25,0.50,0.75,0.90,0.95)`.

| Trường | Kiểu logic | Bắt buộc | Null? | Giá trị/ý nghĩa | Kiểm tra |
|---|---|---|---|---|---|
| `forecast_run_id` | string | Có | Không | ID lần sinh hoặc nhập dự báo | Không rỗng; tham chiếu manifest bất biến |
| `model_version` | string | Có | Không | Nhóm kết quả của một phiên bản model | Không rỗng; nhất quán với fits/manifest |
| `fit_id` | string | Có trong MVP | Chỉ phase 2 theo nguồn | Bản huấn luyện cụ thể | MVP: FK tồn tại, model_version/asset khớp Fits; external_unverified thiếu fit chỉ thuộc phase 2, không giả lập baseline |
| `asset` | enum string | Có | Không | `gold`, `silver`, `brent`, `wti` | Khớp target series/lịch trong config |
| `base_date` | date | Có | Không | Phiên gốc của dự báo | Là phiên tài sản; thuộc lịch chạy; không đổi thành ngày tác vụ chạy |
| `h` | integer | Có | Không | Số phiên, `1..7` | Không nhận bool, số thập phân, hoặc ngày lịch |
| `q05`, `q10`, `q25`, `q50`, `q75`, `q90`, `q95` | number | Nếu status=ok | Có | Log return, không phải giá | Khi ok: đủ 7 số hữu hạn, không giảm; khi thất bại: tất cả null, không partial |
| `prob_up` | number | Nếu status=ok | Có | Xấp xỉ P(return>0), tuyến tính, chưa hiệu chỉnh | Khi ok: hữu hạn trong `[0.05,0.95]`, khớp q theo quy tắc mục 5.4; thất bại: null |
| `crossed_raw` | boolean | Cột có; chứng cứ tùy nguồn | Có | Crossing trước sort | true/false chỉ khi đã kiểm tra đủ 7 phân vị thô hữu hạn; không suy false từ q đã sort |
| `forecast_status` | enum string | Có | Không | `ok`, `invalid_input_window`, `generation_error` | Không nhận `no_forecast_row` từ bộ sinh/importer |
| `missing_reason` | enum string | Khi không ok | Có | Lý do bỏ qua/lỗi, mục 5.3 | null đúng khi ok; không dùng chuỗi tự do thay enum |
| `as_of_time` | timestamp UTC | Có trong MVP và verified | Chỉ external phase 2 nếu thiếu chứng cứ | Thời điểm phát hành thật hoặc giả lập | MVP: published_at(base_date) theo rule nguồn, không dùng created_at; kiểm tra mục 5.5 |
| `provenance_status` | enum string | Có | Không | `backtest_publication_rule`, `verified_backtest`, `verified_production`, `external_unverified` | Mức publication-rule do [KHẢI12] chốt cho validation 2019; khác PIT verified; nguồn phase 2 giữ theo mục 5.5 |
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

**[SRC ZIP Returns + KHẢI12]** 0 dưới q05 → prob_up=0.95; trên q95 → 0.05; 0 trùng nhiều q → lấy mức τ cao nhất của nhóm trùng theo quy ước CDF liên tục bên phải. Khải đã xác nhận tie này; không mở lại thành quyết định chưa chốt.

**[ĐỀ XUẤT]** Dự báo nội bộ chưa làm tròn phải khớp hàm prob_up với dung sai tuyệt đối `1e-12` (ghi cfg). Production import/làm tròn ở mục 10 thuộc phase 2, không chặn validation 2019; không dùng dung sai tùy tiện để che sai thuật toán. Phương pháp nội suy là metadata bất biến trong manifest; mặc định linear, không ngầm chuyển PCHIP.

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

`as_of_time` là lúc phát hành/giả lập phát hành, **không phải** lúc evaluate, trained_at hoặc ingest lại bản ghi. Không tự thêm cột provenance/run-status vào Accuracy; giữ provenance ở Internal Forecasts và cấu hình/báo cáo của run.

**MVP validation 2019 — `backtest_publication_rule` [KHẢI12]:** dùng snapshot clean mới nhất sẵn có, mô phỏng publication theo ADR-0005. Với yfinance price-only, `published_at(D)=D+1 lúc 12:00 UTC` và **as_of_time=published_at(base_date)**. D+1 là ngày lịch của rule công bố, không phải bước h theo phiên. Kiểm tra `max_input_published_at <= as_of_time` và `as_of_time < published_at(target_date)`; kiểm tra nhãn fit/baseline đã hoàn tất và có thể công bố theo cùng rule. Không áp D+1 cho EIA hoặc nguồn có lag khác.

Mức này **được dùng để chọn cấu hình/model trong MVP validation 2019**, nếu các kiểm tra dữ liệu, fit, mask/cutoff và input theo rule đạt. Báo cáo phải ghi rõ: “Sử dụng snapshot sạch mới nhất, mô phỏng thời điểm công bố; chưa kiểm chứng historical vintage/revisions; không phải backtest đã xác minh point-in-time đầy đủ.” Giữ định danh snapshot và rule/seed/config để tái lập; không yêu cầu xây pipeline lưu vintage trong MVP. Thiếu vintage một mình không chuyển run hợp lệ của chế độ này thành external_unverified.

Publication metadata phải xác định được từ nguồn/ngày và rule tương ứng, không suy từ X hữu hạn. Nếu thiếu max_input_published_at hoặc không thể kiểm tra nguồn/rule thì chưa đủ điều kiện phát hành/chọn model; không tự gắn publication-rule hợp lệ hoặc verified. Vi phạm publication hoặc nhãn train đã biết vẫn bị từ chối/ghi lý do, không được “hạ provenance” để bỏ qua. Dòng input chưa sẵn sàng giữ lần thử input_not_available, không biến thành no_forecast_row.

| Provenance | Eligibility / trạng thái run | Phạm vi |
|---|---|---|
| `backtest_publication_rule` | Kiểm tra rule/fit/dữ liệu đạt → được xuất kết quả và chọn model validation 2019, **kèm giới hạn vintage bắt buộc**. Metric status vẫn theo mục 11, không đổi thành undefined chỉ vì thiếu vintage. | MVP [KHẢI12] |
| `external_unverified` | Nguồn ngoài chưa đáp ứng chính sách cho phép chọn model; chỉ chấm thăm dò nếu cấu trúc/nhãn hợp lệ; không dùng chọn model chính thức. Thiếu raw chỉ ảnh hưởng crossing, không tự quyết định provenance. | Phase 2 |
| `verified_backtest` | Phải có bằng chứng lịch sử snapshot/revisions và input as-of; không suy từ snapshot mới nhất hoặc publication rule. trained_at thực tế có thể sau ngày lịch sử, không sửa thành năm 2018. | Chế độ PIT nâng cao/phase 2 |
| `verified_production` | Cần timestamp phát hành và bằng chứng dữ liệu/artifact tồn tại trước phát hành; created_at riêng lẻ không đủ. | Phase 2 |

Với hai chế độ verified, giữ điều kiện mọi input/artifact cần thiết sẵn sàng tại thời điểm mô phỏng/phát hành và không mang revision tương lai; đó là tiêu chuẩn **mạnh hơn** publication-rule MVP. Tự khai verified nhưng thiếu bằng chứng thì từ chối xác nhận verified; không tự đổi nhãn. Không trộn provenance khác nhau vào cùng run tổng hợp. External import/PIT nâng cao ở mục này và mục 10 vẫn cần review phase 2. Rolling MVP dùng eligibility/provenance riêng tại §7; không đổi điều kiện validation publication-rule hoặc tự gắn verified_production cho legacy.

## 6. Fits metadata

Metadata logic `fits`, khóa duy nhất fit_id; không thiết kế bảng DynamoDB/API Fits. **MVP có đúng nhóm trường bắt buộc sau [KHẢI12]**; các thông tin audit không biến thành điều kiện phụ cản demo.

| Trường | Kiểu; null? | Quy tắc |
|---|---|---|
| `fit_id` | string; không | ID bất biến của artifact huấn luyện, seed khác/artifact khác có ID khác |
| `model_version` | string; không | Nhóm phiên bản; khớp Forecasts |
| `asset` | enum string; không | gold/silver/brent/wti; khớp asset của Forecasts tham chiếu fit |
| `train_end` | date; không | Giới hạn ngày gốc train khai báo, không thay cho ngày đích nhãn |
| `max_training_target_date` | date; không | Ngày đích muộn nhất trong mọi nhãn train/tuning nội bộ/early-stopping đã dùng để fit artifact |
| `trained_at` | timestamp UTC; không | Giờ tạo artifact thật; không đổi thành năm 2018 để giả lập backtest |
| `config_hash` | string; không | Hash cấu hình fit: data snapshot, seed, preprocessing/scaler, train split, target/calendar versions; khác hash đánh giá |
| `commit` | string; không | Metadata do workflow triển khai cung cấp; không dùng Git lấy ở nhiệm vụ này, không bịa hash hoặc thay bằng chuỗi giả |

**Tùy chọn/audit trong MVP:** model_name, snapshot/version/hash references, max_training_label_available_at. Trường thời điểm nhãn này có thể suy từ publication rule của asset và các nhãn đã khai (với price-only yfinance, từ ngày đích muộn nhất theo rule); không bắt buộc phải lưu cột để kiểm tra. Nếu cả metadata lẫn rule/nguồn đều không cho xác định thời điểm nhãn thì báo thiếu khả năng kiểm tra, không suy nhãn đã sẵn sàng.

**Giai đoạn 2:** chứng cứ vintage/revision đầy đủ, lineage retrain và metadata production nâng cao phục vụ verified modes. Giữ các khái niệm audit đó để truy vết, không yêu cầu pipeline vintage cho MVP. Một ID fit không có dữ liệu metadata bắt buộc do workflow cung cấp chưa đủ điều kiện tích hợp; ví dụ fit-demo ở mục 12 chỉ là minh họa, không là fit thật đã được xác nhận.

MVP validation 2019: `train_end <= 2018-12-31`, `max_training_target_date <= 2018-12-31`; origin train thuộc 2014–2018. Nhãn cuối 2018 sang 2019 phải bỏ. Thời điểm nhãn train sẵn sàng, lấy từ trường audit hoặc suy theo publication rule, phải <=as_of_time đầu tiên dùng fit; không gán nhãn đã khả dụng trước giờ công bố. Không dùng nhãn validation để fit/early stopping/scaler. Trained_at là thời gian chạy thật, không phải giới hạn ngày nhãn train. [ADR + KHẢI12]

Baseline không tạo Forecasts hoặc Fits; không tạo fit_id=null/no_training để đưa baseline thành model giả. Model thật trong MVP phải tham chiếu fit hợp lệ. External model thiếu fit metadata chỉ thuộc luồng nhập thăm dò phase 2, ghi giới hạn và không giả làm baseline.

Tương lai retrain: mỗi forecast tham chiếu fit có nhãn đã công bố không muộn hơn as_of_time tương ứng; production còn yêu cầu trained_at không muộn hơn phát hành. Một model_version nhiều fit_id hợp lệ nếu manifest chọn đúng fit mỗi origin. Không cấm máy móc mọi dữ liệu từ 2020 trong mọi chế độ tương lai; phải chốt trước giao thức retrain và ngăn dùng nhãn chưa sẵn sàng. MVP vẫn từ chối retrain_every khác None. Metadata chỉ là khai báo/audit, không chứng minh tuyệt đối quá trình fit không rò rỉ.

## 7. Lịch ngày dự báo kỳ vọng và ngoại lệ Rolling MVP

**Cập nhật 2026-10-30 theo RFC [#45](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/45) v4.6 (PR [#65](https://github.com/CPAWS-AWS-FCAJ/CPAWS-commodity-forecasting/pull/65)).** Đây là cập nhật Contract cho `rolling_8w` MVP; **không xác nhận AWS đã triển khai**. Ngoại lệ dưới đây chỉ dành cho `rolling_8w` MVP, không nới provenance, manifest, common mask, Fits hay giao thức validation/test/import bên ngoài.

### 7.1. Validation/test lịch sử — giữ quy tắc hiện hành

Cfg có `evaluation_start`, `evaluation_end`, `target_cutoff_date`, `evaluation_kind`, `horizons`, `assets`, `forecast_run_id` theo model_version và `evaluation_as_of_time`. `evaluation_kind` và `target_cutoff_date` là cột bắt buộc, thuộc khóa logic Accuracy, không chỉ metadata cfg.

Expected grid lịch sử là mọi phiên tài sản trong khoảng ngày gốc đóng `[start,end]` × h=1..7, lấy từ lịch, không từ các ngày còn giá/Forecasts. Giữ origin cuối kỳ dù target vượt cutoff để đếm loại. MVP validation 2019 dùng model/scaler cố định, make_windows trên mọi phiên; test 2020+ chỉ theo giao thức đã khóa.

Left join grid với Forecasts theo run/model/asset/base_date/h; fit_id từ fit cố định khai cho asset (lịch fit riêng khi retrain được hỗ trợ). Thiếu dòng → Detail tổng hợp no_forecast_row, không suy fit từ dòng lân cận. Giữ counters invalid_input_window, generation_error và no_forecast_row; valid=False của make_windows vẫn là lần thử có lý do. Không tạo forecast thay thế.

Forecasts ngoài khoảng chấm bỏ qua có đếm; sai lịch/h bị từ chối, không dịch ngày. Snapshot thiếu warm-up là lỗi chuẩn bị dữ liệu hoặc insufficient_input_history, không cắt ngày bắt đầu đánh giá ngầm. Baseline dưới 200 loại từng điểm theo common mask, không tự làm mất cả run. Giữ nguyên tất cả điều kiện lịch sử tại §§5–6, 8–12.

### 7.2. Rolling window, Scheduler và expected schedule

Rolling production chỉ `evaluation_kind=rolling_8w`, `sample=all`, 4 asset với h=1..7 theo lịch riêng (NYSE cho GLD/SLV; CME cho BZ=F/CL=F). Window dựa trên base_date, 56 ngày lịch UTC inclusive: `evaluation_start=window_start=job_utc_date-55 ngày`, `evaluation_end=window_end=job_utc_date`. Không co window theo effective date hoặc ngày thực có forecast; cutoff nhãn riêng asset.

Job sau Predict, **`cron(45 13 ? * TUE-SAT *)` UTC**, 13:45 UTC / 20:45 Việt Nam, một run mỗi asset khi input READY. Lambda timeout 300 giây, Scheduler retry=0, không reserved concurrency; idempotency bằng run fingerprint/conditional writes, không dựa vào việc tránh chạy đồng thời. Snapshot/quality hoặc nguồn actual chưa READY → log và thoát, không COMPLETED/promote; lượt sau thử lại. Retry=0 không thay xử lý lỗi/Errors alarm. Snapshot hợp lệ đã đọc nhưng không có eligible observations là trường hợp khác, có thể COMPLETED với undefined đúng quy tắc.

Expected schedule suy từ trading calendar của asset, lịch Predict TUE–SAT, ngoại lệ đã biết, từ kỳ base_date 26/10/2026 trong window/phạm vi champion có hiệu lực; deduplicate một kỳ asset/base_date, không đếm lại theo h hoặc invocation retry. Đây là lịch kỳ vọng, không phải bằng chứng Lambda đã ghi. **Không yêu cầu manifest phát hành riêng, không đọc CloudWatch logs thường kỳ và không có log-retention guard cho COMPLETED.**

| Đại lượng | Mức đếm / quy tắc |
|---|---|
| `expected_count` | Số kỳ asset/base_date dự kiến trong phạm vi đã chọn; ghi phạm vi và calendar/schedule version vào META |
| `published_count` | Số kỳ trong cùng tập expected có bản ghi Forecasts thực; sự hiện diện không tự chứng minh record đủ điều kiện chấm |
| `missing_count` | Số kỳ expected không có bản ghi; `expected_count = published_count + missing_count` |
| `n_obs` | Số cặp asset/base_date/h thực vào công thức metric; không phải số bản ghi hoặc số lần Lambda chạy |
| `n_base_dates` | Số base_date khác nhau có ít nhất một cặp hợp lệ trong scope; gate overall dùng hợp base dates coverage |
| `issuance_evidence_status` | `verified_eligible_rows` chỉ khi có cặp đã chấm với evidence; `no_eligible_rows` nếu completed không có cặp; API dùng `no_completed_run` khi chưa có completed run phù hợp |
| `schedule_evidence_status` | `not_audited_mvp`; không gọi lịch expected là verified issuance |

Counters publication tách khỏi eligibility: row hiện diện nhưng sample/sai model/chưa mature/unverified được audit riêng, không tự thành n_obs; row ngoài tập expected không nhập vào đẳng thức counters. **Trong META provenance/audit**, có thể lưu `excluded_count` = số bản ghi kỳ expected *đã phát hành nhưng bị loại khỏi eligibility ở cấp record* (ví dụ legacy không được duyệt), kèm breakdown reasons; không nhập vào `missing_count`, không đếm lặp theo 7 horizons, không bổ sung field vào JSON API v3.1 hoặc 28 METRIC. Record hợp lệ nhưng target chưa mature được audit riêng ở cấp horizon, không đánh đồng với không được phát hành. Thiếu row chỉ ghi `missing_record_unclassified`, không gán upstream failure hay skip đã xác minh, không tạo forecast/backfill, không mặc nhiên làm run thất bại. Logs/manifest lịch sử và external import vẫn theo phạm vi riêng, không hưởng ngoại lệ này.

### 7.3. Champion, eligibility và cutover

Nguồn authoritative: hai JSON env mappings `MODEL_VERSIONS` và `CHAMPION_EFFECTIVE_BASE_DATES` cùng khai tại `infra/app.py`, đủ bốn asset, truyền đồng nhất cho Predict/Rolling/API; CDK tests phải kiểm cả hai map. **Đối với champion ban đầu `baseline-q252`, `CHAMPION_EFFECTIVE_BASE_DATES` là `2026-10-26` cho gold/silver/brent/wti**, dựa trên CloudTrail `CreateFunction cpaws-dev-predict` lúc `2026-10-25T09:15:08Z` (PR #32), không có lần đổi `UpdateFunctionConfiguration` sau đó, và lượt phát hành theo lịch 27/10 12:15 UTC có `base_date=2026-10-26` (bằng chứng Tiến cung cấp tại review PR #65). Mapping này được Tiến đưa vào PR CDK S1a và cần kiểm khi deploy; mốc effective date khác với cutover PR #48 và không thay eligibility `created_at`/legacy. Khi đổi champion tiếp theo, model/effective date theo ADR/release, không lấy từ STATE. Predict ưu tiên MODEL_VERSIONS, chỉ fallback MODEL_VERSION khi map mới chưa cấu hình trong chuyển đổi; không đổi champion ngầm. Khi đổi riêng asset: chỉ chấm model mới từ effective base date, không trộn model cũ hoặc reset asset khác. Drain writer cũ khi rollout, API kiểm mapping để fail-closed.

Mỗi cặp được chấm phải đáp ứng:

1. Forecast production thực, `is_sample=false`, asset/target đúng (gold→GLD, silver→SLV, brent→BZ=F, wti→CL=F), model đúng hiệu lực; không sample/backfill. Base_date thuộc window và không sớm hơn CHAMPION_EFFECTIVE_BASE_DATES[asset].
2. `created_at >= 2026-10-27T12:00:00Z` và `created_at < target_date T13:30:00Z` theo UTC ở từng h; đồng thời evidence chứng minh phát hành trước khi biết nhãn, input chỉ đến base_date và có thể công bố tại as-of. Mốc 27/10 là eligibility, không phải cutover; base_date có thể 26/10 nếu record đủ điều kiện.
3. Đủ 7 q hữu hạn, không giảm, prob_up trong [0.05,0.95]; giữ q/prob_up nguồn, không normalize lại. `abs(prob_up_stored-prob_up_recomputed)>1e-6` chỉ log `prob_up_mismatch`, không loại chỉ vì mismatch. Kiểm shape/miền/q vẫn bắt buộc. Profile full-precision của validation 2019 không đổi.
4. Sau cutover PR #48: conditional-write provenance và `input_snapshot_dt=YYYY-MM-DD` đúng `snap.dt` đã dùng, validate với snapshot/input-as-of. Có field chỉ là candidate hậu cutover, không chứng minh bất biến hoặc thời điểm phát hành.
5. Trước cutover: chỉ từng record được duyệt theo `LEGACY_ACCEPT_WITH_EVIDENCE`; thiếu/sai field sau cutover không được tự hạ thành legacy.

**Mốc deploy cutover PR #48 đã được Tiến cung cấp qua PR #68:** code `ce77bcb`, CloudFormation `PredictFunction UPDATE_COMPLETE` lúc **`2026-10-30T08:10:06Z`**. Đây là ranh giới deploy đã ghi nhận, khác `issued_at_min` 27/10 và champion effective `base_date=26/10`. **Smoke production đầu tiên dự kiến là lượt 30/10 lúc 12:15 UTC**, cần Tiến xác nhận ở PR #68 `written=4`, `already_published=0` và có `input_snapshot_dt` cho cả bốn asset trước khi đánh dấu kiểm chứng hành vi conditional write; cho đến khi có bằng chứng, không tự coi smoke test đã PASS. Lượt này có `base_date=2026-10-29`, là **hậu cutover**, bắt buộc `input_snapshot_dt` đúng snapshot/input-as-of và provenance phát hành hợp lệ; không được chuyển ngược sang legacy nếu thiếu field. Build/approve/merge hoặc `dry_run` không chứng minh ghi production. Thời điểm deploy và bằng chứng smoke phải lưu dưới dạng provenance/metadata có thể kiểm toán của evaluation run, không tự đặt tên attribute DynamoDB mới chưa được review.

**Legacy policy đã chốt, từng record còn cần evidence:** kiểm asset/base_date/model_version/created_at, khung lịch 12:15–13:30 UTC, is_sample=false, không manual overwrite/reissue, input-as-of; ghi người xác nhận, thời điểm duyệt, audit reference/hash và danh sách accepted records trong provenance META. Chỉ record đã duyệt được miễn input_snapshot_dt; không bịa snapshot hoặc gắn immutable_verified hồi tố. Timestamp đúng lịch chưa đủ. Thiếu evidence → legacy_unverified/issuance_unverified và loại khỏi n_obs; fail-closed tương đương POST_CUTOVER_ONLY với record đó.

Audit legacy riêng dự kiến Tiến cung cấp trước 02/11: **chỉ base_date 26–28/10/2026** (bốn asset, nếu có record), gồm created_at, CloudWatch Invocations/PREDICT_DONE, snapshot_dt/dry_run/written/model_version, đối chiếu input-as-of và lịch sử ghi. **Base_date 29/10**, phát hành 30/10 12:15 UTC, thuộc hậu cutover PR #48 nên không phải legacy; việc chứng thực lượt smoke vẫn đang chờ Tiến xác nhận tại PR #68. Đây là audit ngoại lệ một lần, **không** yêu cầu tạo manifest phát hành mới hay gọi CloudWatch mỗi lượt Rolling. Chưa có danh sách legacy records được duyệt trong gói tài liệu này.

### 7.4. Actual, common mask, metric và display

`y(t,h)=ln(P_target(target_date)/P_target(base_date))`; target_date là phiên thứ h sau base_date theo calendar riêng, không shift theo dòng có giá. Hai endpoint hữu hạn, dương, hợp lệ theo ADR và rejected đúng asset. Thiếu phiên giữa không tự vô hiệu target, phải đếm/log. Dùng GLD/SLV làm target kim loại, không dùng giá hiển thị quy đổi. Nhãn phải đã công bố ở evaluation_as_of_time và target_date<=target_cutoff_date riêng asset; không đọc tương lai để hoàn thiện cặp pending.

Giữ common_mask §9.2 và baseline nhân quả hợp lệ (252 phiên, ít nhất 200) cho các metric nền; sign loại thêm y=0 hoặc q50=0. Không đổi mask để tăng coverage. `first_eligible_base_date` là base_date đầu có cặp thực sự chấm của champion trong scope, null nếu không có; không hardcode 27/10.

Bốn metric nền coverage_80, width_80, sign_accuracy, up_rate × 7 horizons = **28 METRIC**. Overall trong META, không h=0. Giữ `width_80=mean(q90-q10)`, unit log_return; bổ sung derived `width_80_pct=mean_i[100 * (exp(q90_i)-exp(q10_i))]`, unit percent, cùng mask/n_obs với width_80. Tính từng cặp trước khi gộp, không dùng `100 * width_80` hoặc exp của trung bình q thay thế. Derived overall và by-horizon đóng băng trong `META.derived_metrics.width_80_pct`, cùng fingerprint/payload hash; không tăng thành 35 METRIC, không sửa Accuracy Schema.

Overall coverage = tổng hits/tổng cặp; width/width_pct/sign/up dùng trọng số n_obs riêng từng metric. Distinct base dates overall là hợp ngày, không tổng các h. Dưới 20 distinct base_date có ít nhất một cặp coverage hợp lệ: **mọi metric overall** display_value=null/display_status=insufficient_data, giữ value/status tính toán. Khi đủ ngưỡng: metric ok được ready và display_value; metric không tính được vẫn null/display_status=undefined. Không có completed run đúng champion → not_ready. Tất cả per-h display_value=null/display_status=counts_only. Web chỉ dùng display fields, chỉ hiển thị width_80_pct cho độ rộng; không tự exp/chuyển log-width. Không cam kết ready trước 22/11 hoặc suy từ 20 phiên lịch. Cấu trúc JSON và disclaimer đầy đủ tại [API Contract](../api/contract.md), dùng fixtures v3.1 synthetic.

### 7.5. Storage, lifecycle và concurrent writers

Validation/test vẫn Parquet S3 `eval/`. Rolling champion dùng `cpaws-<env>-accuracy`, PK/SK String, không GSI/LSI/Scan hoặc TTL cho record công bố. Key động canonical-encode/length-prefix để tránh collision.

| Item | PK | SK | Nội dung |
|---|---|---|---|
| STATE | ASSET#asset | STATE | Chỉ latest_run_pk/latest_run_id/latest_run_order = LATEST_COMPLETED |
| META | RUN#asset#model_version#run_id | META | Status, fingerprints, snapshot/cutoff, model/effective date, eligibility/legacy evidence, 28 expected keys/hashes, aggregate/counts, derived_metrics |
| METRIC | Cùng PK META | METRIC#sample#evaluation_kind#evaluation_start#evaluation_end#target_cutoff_date#Hh#metric | Một metric nền/h, payload_hash, schema logic hiện hành |

`run_id = <job_utc_date>-<sha256(canonical(asset, MODEL_VERSIONS[asset], CHAMPION_EFFECTIVE_BASE_DATES[asset], job_date, revision, config_hash, immutable_snapshot_identity, target_cutoff_date, eligible_record_fingerprint))[:20]>`. Lưu fingerprint đầy đủ và derived payload/hash trong META. `run_order=<YYYYMMDD>#<revision_4_digits>` tăng đơn điệu; retry cùng input giữ revision/run_id. Correction snapshot/config/evaluation tạo revision/run mới, không ghi đè kết quả cũ. Không cần fingerprint của toàn bộ CloudWatch schedule logs.

1. Khóa mapping/snapshot/cutoff/eligible records; tạo META RUNNING bằng conditional PutItem `attribute_not_exists(PK)`. Trùng full fingerprint: resume nếu chưa completed, hoặc xác nhận pointer/no-op nếu đã completed; khác → RUN_ID_CONFLICT.
2. Ghi 28 METRIC bằng conditional PutItem trên từng PK/SK, không BatchWriteItem. Conditional failure: consistent GetItem so payload_hash/nội dung; giống no-op, khác IMMUTABLE_METRIC_CONFLICT. Không nhầm với Predict already-published không GetItem/so payload.
3. META RUNNING→VALIDATING→COMPLETED bằng conditional UpdateItem; fingerprint/config/snapshot/evidence/metric hashes/derived payload bất biến. Strong-read xác nhận đủ 28 rows, counts, derived hash, actual/eligibility nhất quán và không còn lỗi tính/đọc/ghi/conflict. FAILED terminal, chạy lại cần revision mới.
4. Chỉ sau COMPLETED mới conditional promote STATE: pointer chưa có, hoặc order mới lớn hơn, hoặc cùng order **và cùng run PK** cho idempotent retry. Cùng order khác run là conflict; không rollback. Crash trước completion không đổi pointer; crash sau completion trước promote được retry promote.
5. API đọc STATE rồi Query đầy đủ run bằng strong reads; kiểm META COMPLETED/current champion/effective date/run order/28 hashes/derived/provenance; đọc lại pointer trước khi trả. Pointer đổi hoặc model mismatch → retry ngắn/not_ready, không trả sai champion. Monotonic order không tự giải quyết writer đời cũ chạy muộn; release phải drain writer cũ, đồng bộ hai mappings và test fail-closed theo asset.

Không promote khi snapshot không nhất quán, lỗi tính/ghi chưa xử lý, thiếu rows, payload/fingerprint conflict hoặc provenance của cặp scoring không hợp lệ. **Không chặn COMPLETED** chỉ vì missing kỳ expected, thiếu CloudWatch/manifest audit, n_obs=0 hay chưa đủ 20 ngày. Với input đã đọc hợp lệ và common rỗng, ghi đủ 28 undefined/value=null/n_obs=0/no_evaluable_obs, derived null; không gắn verified_eligible_rows khi không có cặp.

IAM: Rolling writer scoped Get/Query/Put/Update Accuracy, read Forecasts/clean/shadow, write chỉ shadow_eval; API reader chỉ Get/Query Accuracy, không Forecasts/S3/ghi/Scan. Predict không đọc Accuracy, không có champion release operator. IAM scope không thay conditional expressions. S3 ListBucket trên bucket ARN giới hạn request prefix clean/shadow; GetObject 403 mơ hồ không tự gọi missing: scoped ListObjectsV2(Prefix=key) để xác minh, nếu không xác minh giữ unverified/lỗi quyền. Không mở quyền toàn lake. No reserved concurrency không miễn kiểm concurrent writes.

### 7.6. Shadow và phạm vi triển khai

Theo ADR-0011, champion Accuracy và paired S1a là hai nhánh độc lập cùng lịch Rolling TUE–SAT 13:45 UTC đã được quyết định 30/10 cập nhật. Không train/retrain hoặc tự chuyển champion. S1a nguồn JSON `eval/shadow/s1a-l094/dt=<UTC>/<asset>.json`; dt là ngày chạy, không suy base_date từ key. Kiểm created_at và S3 LastModified/version/identity trước nhãn; không backfill.

Paired mask là giao eligible champion/shadow/actual hợp lệ/cùng target definition, ghép `(asset,base_date,h,target_date,target_series)` và cùng snapshot/cutoff; **bắt buộc `shadow.input_snapshot_dt == champion.input_snapshot_dt`** khi ghép shadow hậu cutover. Predict PR #53 có thể ghi shadow mới ngay cả khi champion cùng `base_date` đã `already_published` (ví dụ lịch NYSE/CME lặp base 27/11, 26/12, 02/01), nên có thể tồn tại **nhiều shadow files với cùng base_date**. Chọn chính xác shadow object có snapshot khớp champion và issuance/provenance hợp lệ trước nhãn; **không có file khớp thì `shadow_missing`**, không ghép theo base_date hoặc S3 `dt` một cách tùy tiện và không đếm cặp hai lần. Counts riêng, không dùng overall champion thay paired sample. Tính pinball_skill/coverage_80/width_80 cho cả hai trên cùng cặp; baseline tự so bằng 0 khi denominator dương, không có cặp/denominator 0 giữ undefined/reason theo schema. Report Parquet nội bộ `eval/shadow_eval/run_id=<run_id>/`, phân biệt file theo asset/comparison_id; IfNoneMatch=* và checksum: retry cùng payload no-op, khác conflict. Không ghi report vào prefix input shadow. Shadow lỗi/thiếu không chặn champion COMPLETED, không cập nhật STATE, không public API hoặc tạo sample/evaluation_kind mới. Nếu champion asset đổi khỏi baseline-q252, S1a baseline không tự là challenger phù hợp: shadow_not_applicable_model_change/chờ ADR mới, asset khác độc lập.

Tuấn phụ trách bảng/API/IAM; Long job/metrics/tests; Tiến CDK/image Lambda cpaws-dev-accuracy-job (image Predict, CMD handler riêng)/Scheduler/alarm Errors→SNS; Khải Predict mapping. Đây là trách nhiệm triển khai, không xác nhận source/deploy đã hoàn tất.

**DM calendar-gap policy hoãn sau 22/11/2026 theo D13.** Accuracy Schema snapshot đã mô tả chính sách gap, nhưng bản cập nhật Rolling này không kích hoạt thay đổi DM-HAC, không sửa metrics.py/walk_forward.py, fingerprint K4 hoặc yêu cầu chạy lại CV/Validation. Giữ kết quả cũ; mọi triển khai gap thuộc công việc riêng sau mốc hoãn. §11 về DM/CI lịch sử giữ nguyên.

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

**Baseline [ADR + SRC PR #13 + KHẢI12]:** gọi `quantile_baseline()`, `up_rate_baseline()`, `baseline_valid()` và `constant_prob_baseline()` (mốc 0.5 khi cần) từ module của Khải; **không tạo Baseline Adapter riêng hoặc triển khai bản cạnh tranh**. Giữ cửa sổ 252 phiên, return đã hoàn tất, tối thiểu 200 quan sát hợp lệ; chỉ mô tả phạm vi theo source là s thuộc `[t−251,t−h]` trên lịch. NaN vẫn chiếm vị trí phiên, không gom 252 return hợp lệ bất kể xa tới đâu. Tầng Walk-forward chỉ chuẩn bị target Series theo API Returns/invalid_dates đúng asset và ghép output module vào Detail; không sao chép thuật toán baseline.

Với backtest_publication_rule, kiểm tra return lịch sử dùng trong baseline đã hoàn tất và có thể công bố tại as_of_time theo rule của asset; vintage/revisions chưa xác minh phải báo rõ nhưng không cấm chọn model validation 2019. Source Baselines không nhận publication timestamp: kiểm tra này thuộc orchestration, không thêm API hoặc adapter baseline. Chỉ các chế độ verified nâng cao mới đòi bằng chứng snapshot/revision as-of thực sự.

Baseline luôn nằm ở các cột baseline_q*, baseline_prob_up, baseline_pinball_loss và validity/audit của **cùng dòng Detail**, không tạo model_name/model_version giả, dòng Fits hoặc Internal Forecasts riêng cho Baseline-252. Baseline_prob_up là tần suất `[0,1]`, không chịu điều kiện p nội suy/kẹp của hàng dự báo model nên không cần mở rộng Forecasts Schema.

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

Áp dụng cho **mọi metric thông thường**, kể cả hit rates, coverage, width, interval score, Brier, up_rate. Sign accuracy dùng thêm `y_true != 0 AND q50 != 0`; crossing dùng mask riêng mục 5.4. Không để từng metric tự chọn ngày. [ADR + KHẢI12: giữ logic mask đã được xác nhận]

Ưu tiên exclusion_reason đề xuất: `outside_target_cutoff` → `no_forecast_row` → `invalid_input_window` → `generation_error` → `invalid_target` → `insufficient_baseline`; null khi thuộc all. Detail giữ target_invalid_reason, baseline_invalid_reason, missing_reason và cờ độc lập để không mất nguyên nhân chồng lấp. Dòng input sai cấu trúc/FK/chứng cứ rò rỉ bị từ chối trước bước tạo tập kết quả, không biến thành “thiếu dự báo”.

Log theo run/model/asset/h/sample: n_expected, n_received, n_common và các số loại tương ứng, gồm `excluded_insufficient_baseline`; tổng bộ đếm **lý do chính** bằng số dòng ngoài mask. Bộ đếm từng cờ có thể chồng lấp, không cộng thành tổng loại. `excluded_insufficient_baseline` chỉ là bộ đếm log, không phải mã `Accuracy.undefined_reason`; mask rỗng dùng quy tắc mục 11. Không thêm cột đếm vào Accuracy ở tuần đầu [AS10]; config/report giữ audit của run.

### 9.3. Roll và excl_roll

**[ADR]** Brent/WTI có thêm mẫu bỏ cửa sổ chứa đáo hạn hoặc phiên flag roll; GLD/SLV chỉ all. **[SRC]** calendars.py cung cấp cl_expiries/bz_expiries và roll_days; roll flag trong clean gắn phiên đầu sau expiry, không đồng nghĩa chính ngày expiry. BZ expiry dùng xấp xỉ ngày làm việc London bằng CME, cần giữ giới hạn này trong config/report.

**[KHẢI12 — đã chốt]** Kiểm tra các phiên tài sản trong **`(base_date,target_date]`**: **loại chính base_date, tính target_date**. Dùng ngày đáo hạn từ cl_expiries/bz_expiries theo chức năng thực tế của calendars.py và các cờ roll liên quan nếu dữ liệu cung cấp. Roll ở base_date một mình không loại cửa sổ; expiry hoặc roll ở target_date thuộc cửa sổ. Không tự suy ngày đáo hạn hoặc thay công thức lịch. Thiếu thông tin lịch đáo hạn cần thiết/không xác định đủ thông tin roll thì giữ roll_in_horizon=null và chính sách báo thiếu metadata, không tự đổi thành false hay phát minh ngoại lệ. Giữ giới hạn xấp xỉ lịch Brent theo source trong báo cáo.

Với dầu và metadata đủ: common_mask_excl_roll = common_mask_all AND NOT roll_in_horizon. Lý do loại riêng cho excl_roll là exclusion_reason của all nếu đã bị loại, nếu không thì `roll_window`; không sửa exclusion_reason all. `excluded_roll` chỉ đếm điểm vốn thuộc all. Kim loại: mask excl_roll=null, không tạo bản sao sample. Không nhân đôi Detail cho all/excl_roll. [YÊU CẦU + ĐỀ XUẤT]

**Quy tắc đã chốt cho crossing:** chỉ tính giá trị `crossing_rate` trên `sample=all`. Với **Brent/WTI và sample=excl_roll**, vẫn phải xuất dòng Accuracy `metric=crossing_rate`, `status=not_applicable`, `value=null`, `n_obs=0`, `undefined_reason=unsupported_sample` (CI=null/null). Đây là dòng thông báo metric không áp dụng, không phải tính crossing trên mask excl_roll và không cần nhân đôi Detail. Xét unsupported_sample trước khả năng cung cấp raw: dù nguồn có raw hay không, dòng dầu/excl_roll vẫn mang reason này. Không thêm sample excl_roll cho kim loại; việc chốt boundary roll không thay quy tắc status này.

## 10. Ánh xạ với API/DynamoDB contract

**[API]** Contract cục bộ là nguồn chuẩn; bảng dưới giữ để tham khảo tích hợp **production/import phase 2**, không sửa PK/SK hoặc JSON và không là điều kiện bắt buộc cho demo validation 2019. External import vẫn cần Tuấn review; Rolling MVP áp dụng ngoại lệ §7 và response tại API Contract, không áp manifest import làm gate Rolling.

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

**Làm tròn [API + ĐỀ XUẤT]:** DynamoDB lưu Decimal làm tròn 6 chữ số. Import giữ q/prob đã lưu, manifest ghi độ chính xác và nguồn; không tái tạo “q gốc” hoặc thay p bằng phép tính lại trên q làm tròn. Đề xuất profile `stored_rounded`: xác thực p nằm trong khoảng, chỉ cảnh báo khác biệt nội suy do rounding, gắn giới hạn đo lường trong run/report; mâu thuẫn thuật toán đã có chứng cứ vẫn bị từ chối. Ngưỡng nhận biết lỗi thuật toán so với rounding cần Tuấn/Khải chốt, chưa coi bản import tương đương backtest đầy đủ chính xác. Không trộn profile này với internal_full_precision trong một Accuracy run. Riêng Rolling MVP, ngưỡng mismatch >1e-6 chỉ log theo §7.3, không tự loại hoặc thay p; các quy tắc internal validation/import khác giữ nguyên.

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
| `ci_low`, `ci_high` | Block bootstrap trên đúng mask | MVP bắt buộc triển khai CI pinball_skill; các CI khác có thể deferred phase 2 theo phạm vi đã chốt. CI không tính được vẫn null/null, value hữu hạn giữ status=ok và phải log lý do; không coi chưa triển khai CI pinball_skill là đã đạt MVP. |

Giữ status AS10 với các quy tắc đã chốt: tính được → ok/value hữu hạn; mẫu số=0 khi có quan sát → undefined/zero_denominator và **giữ n_obs**. Khi common_mask không còn quan sát, **bất kể vì baseline thiếu hay nguyên nhân khác**, metric áp dụng dùng `status=undefined`, `value=null`, `n_obs=0`, `undefined_reason=no_evaluable_obs` (CI=null/null). Không dùng `insufficient_baseline` hoặc `excluded_insufficient_baseline` làm Accuracy.undefined_reason; `excluded_insufficient_baseline` chỉ là bộ đếm trong log. Reason `insufficient_baseline` ở Detail vẫn chỉ giải thích điểm bị loại, không chuyển thành mã lý do của Accuracy.

Thiếu capability model → not_applicable/missing_quantiles hoặc missing_prob_up, không điền q/p giả. Crossing/all: nguồn không hỗ trợ raw là not_applicable, mã lý do theo mục 5.4; nguồn hỗ trợ nhưng không có điểm là undefined/no_evaluable_obs. Crossing với Brent/WTI, sample=excl_roll: **luôn xuất** not_applicable/unsupported_sample, value=null, n_obs=0 theo mục 9.3, không áp quy tắc mask rỗng cho metric không áp dụng này.

**Naive-zero trong MVP [REVIEW + ADR]:** chỉ làm **mẫu số** `mean(abs(y_true))` của `mae_ratio_vs_naive` cho mô hình đang được đánh giá, trên cùng common mask. Evaluate tính mốc return=0 bên trong; **không tạo nguồn dự báo/adapter model độc lập cho naive-zero, không xuất bất kỳ dòng Accuracy nào có model_version=naive-zero**, kể cả dòng not_applicable. Không tính sign_accuracy riêng cho Naive, không giả lập bảy phân vị hoặc prob_up. Nếu mẫu số=0, dòng ratio của model hiện tại là undefined/zero_denominator và giữ n_obs. Đây là phạm vi MVP đã được review xác nhận, không còn là câu hỏi mở.

**Baseline-252 [KHẢI12]:** chỉ tính từ Baselines PR #13 và lưu trong Detail; không đưa vào Internal Forecasts, không tạo Baseline Adapter riêng, không mở Forecasts profile hoặc model giả để chứa p tần suất. Pinball Skill dùng hai cột loss cùng điểm như mục 8. Bảng comparison có thể so model với baseline bằng các loss đó, không cần baseline phát hành Forecasts.

### 11.1. DM và Holm — dùng Metrics PR #11 theo review

**DM [KHẢI12]:** dùng chuỗi loss từng quan sát, lag **h−1**, **trọng số đều** trên các lag 1…h−1, giữ HLN và p hai phía t(T−1) theo ADR; **không dùng Bartlett weights**. Không triển khai lại công thức trong Walk-forward. Snapshot metrics cục bộ còn Bartlett, vì vậy chỉ truyền hac_lag=h−1 vào bản đó vẫn chưa đáp ứng review; phải dùng implementation PR #11 sau khi được chỉnh/đối chiếu. Đây là phụ thuộc tích hợp, không phải yêu cầu sửa metrics trong nhiệm vụ tài liệu.

- Model với Baseline-252: lấy model_pinball_loss và baseline_pinball_loss từ **cùng Detail**, cùng asset/base_date/h và common mask của sample. Không tạo/ghép Forecasts baseline.
- Hai model thật: chọn đúng model_version/run/forecast_run/fit lineage, cùng cutoff/snapshot; join Detail theo `(asset,base_date,h)`, lấy giao mask và loss hợp lệ của cả hai. Không join nhầm các phiên bản hoặc zip vector sau dropna độc lập.
- Giữ bảng model_comparison riêng theo AS10; d=PL_A−PL_B, âm nghĩa A loss thấp hơn. Không đủ cặp hoặc phương sai không dương/constant difference → undefined, giữ số cặp đã xét, không bịa p-value. Naive-zero không tham gia DM pinball 7 q.

**Holm [KHẢI12]:** với từng cặp model–baseline hoặc cặp model thật và cấu hình so sánh đã định, sample=all có **28 vị trí (4 asset × 7 h)**; sample=excl_roll có **14 vị trí (2 asset dầu × 7 h)**. Không gộp/trộn cặp so sánh hoặc sample thành họ khác. Vị trí NaN vẫn chiếm chỗ trong họ; p thô/điều chỉnh của vị trí không xác định vẫn thiếu theo status AS10, không thay bằng 1 hay xóa để thu nhỏ họ.

### 11.2. CI pinball_skill — bắt buộc trong MVP

**[KHẢI12]** Block bootstrap theo ngày, `block_length=20` phiên, `n_bootstrap=1000`, `confidence_level=0.95`; seed nằm trong cfg. Với pinball_skill, resample model/baseline loss **ghép cặp**, tính lại tỷ số hai mean trên từng replicate, không lấy mean skill từng dòng. Không bootstrap độc lập quantile hoặc từng horizon làm mất quan hệ ngày chung. Cấu hình tên n_bootstrap phải được ánh xạ đúng API helper PR #11 (snapshot cục bộ dùng n_resamples), không tự thêm tham số vào Metrics.

**[KHẢI12 — đã xác nhận cho MVP]** Cách căn ngày orchestration khi bootstrap đồng thời nhiều asset/h đã được Khải xác nhận: dùng lưới ngày gốc theo **hợp các phiên NYSE/CME** trong khoảng đánh giá, sắp tăng; giữ mỗi chuỗi loss và mask riêng theo **cùng ngày thật** trên lưới. Một block 20 là 20 vị trí phiên trên lưới ngày chung, không ép mỗi asset có đủ 20 quan sát. Tạo **một kế hoạch rút các block ngày** cho các replicate và áp cùng chỉ số/ngày đó cho các asset/h có mặt. Ngày một asset không giao dịch hoặc không có quan sát trong mask vẫn vắng ở chuỗi đó; không ghép sang ngày khác, forward-fill, điền 0 hoặc drop ngày theo từng asset trước khi tạo kế hoạch chung. Ngày bị rút lặp phải giữ lặp trong replicate, không dedup theo base_date. Ghi quy tắc lưới ngày trong cfg để tái lập.

Sau khi áp kế hoạch chung, mỗi metric chỉ nhận cặp loss thực có mặt/hợp lệ của nó; cỡ mẫu từng asset/h có thể khác và số quan sát replicate có thể đổi vì lịch/mask khác. Không coi thiếu ở một asset là giá trị 0 hoặc bắt loại ngày khỏi mọi asset. Giữ cùng cặp model/baseline và các quan hệ ở ngày chung; không gọi helper riêng trên các vector đã nén lịch với hy vọng cùng seed là cùng ngày. Snapshot helper cục bộ chỉ nhận mảng hữu hạn và resample hàng, **chưa tự xử lý bảng lịch có missing**: orchestration/PR #11 integration phải giữ kế hoạch ngày và chuyển đúng loss, không đưa NaN vào API không hỗ trợ hay viết lại công thức metric.

CI không tính được (ví dụ không đủ lịch sử cho block, không còn cặp hoặc replicate làm mẫu số không xác định) → ci_low/ci_high=null và log lý do, không bỏ replicate lỗi để làm đẹp CI; giữ status/value/n_obs theo AS10. Đây khác với **chưa triển khai** CI pinball_skill: trường hợp chưa triển khai chưa đạt MVP. Các CI khác deferred phase 2 theo review trừ yêu cầu bắt buộc khác của hợp đồng cấp trên; report ghi phạm vi thực tế, không tuyên bố đã có CI cho mọi metric.

## 12. Ví dụ dữ liệu tổng hợp

Các ví dụ không là giá/dự báo tài chính thật; timestamps giả lập theo publication rule yfinance D+1 ngày lịch lúc 12:00 UTC. Validation dùng snapshot sạch mới nhất với backtest_publication_rule, được chọn model trong MVP nhưng chưa kiểm chứng historical vintage/revisions, không phải PIT verified. Ví dụ chỉ hiển thị một horizon, không thay yêu cầu generator giữ cả bảy lần thử. fit-demo giả định có đủ tám trường bắt buộc mục 6 và model/scaler cố định trong 2019; commit do workflow cung cấp, không tạo hash giả. Source/config/snapshot IDs ở manifest.

**12.1. Một Internal Forecasts hợp lệ (profile internal_full_precision)**

```json
{"forecast_run_id":"forecast-demo-01","model_version":"demo-fixed","fit_id":"fit-demo","asset":"gold","base_date":"2019-01-02","h":1,"q05":-0.03,"q10":-0.02,"q25":-0.01,"q50":0.0,"q75":0.01,"q90":0.02,"q95":0.03,"prob_up":0.5,"crossed_raw":false,"forecast_status":"ok","missing_reason":null,"as_of_time":"2019-01-03T12:00:00Z","provenance_status":"backtest_publication_rule","created_at":null}
```

**12.2. Lần thử input NaN**

```json
{"forecast_run_id":"forecast-skip-demo-01","model_version":"demo-fixed","fit_id":"fit-demo","asset":"gold","base_date":"2019-01-02","h":2,"q05":null,"q10":null,"q25":null,"q50":null,"q75":null,"q90":null,"q95":null,"prob_up":null,"crossed_raw":null,"forecast_status":"invalid_input_window","missing_reason":"input_nan","as_of_time":"2019-01-03T12:00:00Z","provenance_status":"backtest_publication_rule","created_at":null}
```

Ví dụ 12.2 thuộc run minh họa khác 12.1; nếu cùng một cửa sổ input dùng cho mọi h bị NaN thì cả bảy h phải được ghi bỏ qua.

**12.3. Phần bổ sung Detail cho dòng 12.1** — ghép toàn bộ trường Forecasts với đối tượng sau; giá tổng hợp hai đầu được chọn bằng nhau nên y=0. Baseline đủ lịch sử trong giả định minh họa.

```json
{"run_id":"eval-demo-01","config_hash":"sha256:illustration","evaluation_kind":"validation","target_date":"2019-01-03","target_cutoff_date":"2019-12-31","y_true":0.0,"target_valid":true,"target_invalid_reason":null,"within_cutoff":true,"missing_between_count":0,"baseline_q05":-0.06,"baseline_q10":-0.04,"baseline_q25":-0.02,"baseline_q50":0.0,"baseline_q75":0.02,"baseline_q90":0.04,"baseline_q95":0.06,"baseline_prob_up":0.5,"baseline_n_obs":240,"baseline_valid":true,"baseline_invalid_reason":null,"forecast_valid":true,"roll_in_horizon":false,"common_mask_all":true,"common_mask_excl_roll":null,"model_pinball_loss":0.0017142857142857146,"baseline_pinball_loss":0.0034285714285714293,"exclusion_reason":null}
```

Kiểm chứng số học đủ 7 mức: model loss từng tau = `[0.0015,0.002,0.0025,0,0.0025,0.002,0.0015]`; tổng=0.012, chia 7. Baseline gấp đôi q → tổng loss=0.024, chia 7; skill trên ví dụ một điểm là 0.5. Vì y=q50=0, dòng vẫn thuộc common nhưng **không** vào sign_accuracy; n_obs(sign)=0. Không dùng các số này như kết quả model thật.

**12.4. Phase 2 — Unnest DynamoDB (trích hai horizons trong bản ghi có đủ 7)**

```json
{"asset":"gold","base_date":"2019-01-02","model_version":"demo-fixed","created_at":"2019-01-03T12:15:00Z","quantile_levels":[0.05,0.10,0.25,0.50,0.75,0.90,0.95],"horizons":[{"h":1,"target_date":"2019-01-03","q":[-0.03,-0.02,-0.01,0,0.01,0.02,0.03],"prob_up":0.5},{"h":2,"target_date":"2019-01-04","q":[-0.03,-0.02,-0.01,0,0.01,0.02,0.03],"prob_up":0.5}],"roll_in_horizon":false}
```

Đây là trích đoạn minh họa, không phải bản ghi production đầy đủ mọi trường contract. Mỗi h thành một dòng nội bộ với q05…q95 tương ứng; cả hai có forecast_run_id=`import-demo-01`, fit_id=null nếu không có metadata, crossed_raw=null, provenance_status=external_unverified, as_of_time=null, created_at giữ nguyên. Không tự gán verified từ created_at. Target_date chỉ có ở Detail sau khi adapter đối chiếu lịch; JSON API dùng `returns` thay `q` nhưng cùng thứ tự. Muốn xác nhận verified_production phải bổ sung chứng cứ ngoài bản ghi này.

## 13. Test cases / acceptance criteria (chưa viết pytest)

| # | Tình huống / đầu vào | Kết quả mong muốn | Chịu trách nhiệm | Phạm vi |
|---|---|---|---|---|
| 1 | Đủ 7 q hữu hạn, không giảm, p đúng | Hàng ok; không normalize thêm ở evaluate | generate/evaluate | MVP 2019 |
| 2 | Raw q10>q25, đủ 7 số | crossed_raw=true trước sort; normalize đúng 1 lần, p tính sau sort | generate | MVP 2019 |
| 3 | Nguồn ngoại nhập q đã sort, không cung cấp raw/chứng cứ crossing và capability=false, sample=all | crossed_raw=null; crossing not_applicable/value=null/n_obs=0; dùng mã schema đã có hoặc chờ review mã thiếu raw, không tự dùng mã đề xuất | adapter/evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 4 | Cửa sổ input có NaN | Giữ hàng invalid_input_window/input_nan, q/p null, tính bộ đếm riêng | generate | MVP 2019 |
| 5 | Expected grid có điểm không có Forecasts | Tạo Detail no_forecast_row, không coi là input_nan | evaluate | MVP 2019 |
| 6 | Trùng khóa kể cả fit_id=null | Payload giống: dedup idempotent; khác: từ chối, không double count | adapter/evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 7 | Có fit_id nhưng không có fits tương ứng | Từ chối FK; không tự bỏ fit_id hoặc tự gắn baseline | fits metadata/evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 8 | Fit validation dùng nhãn target_date năm 2019 | Từ chối; train_end 2018 không che được nhãn vượt ranh giới | fits metadata | MVP 2019 |
| 9 | Một input published_at>as_of_time | Không sinh dự báo từ input đó; ghi input_not_available; verified import có vi phạm thì từ chối | generate/adapter | MVP 2019: generate/validation nội bộ; Phase 2: import production |
| 10 | as_of_time trước base publication hoặc >= target publication | Từ chối xác nhận phát hành hợp lệ; created_at không cứu được | adapter/evaluate | MVP 2019: generate/validation nội bộ; Phase 2: import production |
| 11 | h=7, origin cuối 2019, target sang 2020 | Giữ Detail, within_cutoff=false; không đọc y, không vào common, tăng boundary counter | evaluate | MVP 2019 |
| 12 | Không có giá đúng phiên target | y=null, target_valid=false/missing_target_price; không lùi/tiến sang dòng khác | evaluate | MVP 2019 |
| 13 | Hai cửa sổ có lần lượt 1 và 2 phiên giữa không hợp lệ, hai đầu đều hợp lệ | y vẫn đúng h lịch; evaluate tính missing_between_count lần lượt 1 và 2; attrs tổng đếm 2 target, không gán 2 cho cả hai dòng | evaluate/hàm phụ trợ | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 14 | rejected chỉ có `(silver,D)`, gold có giá hợp lệ D | Chỉ target silver chịu loại; gold không bị loại theo date đơn thuần | evaluate | MVP 2019 |
| 15 | Baseline chỉ có 199 return hợp lệ | baseline_valid=false; loại khỏi mọi metric thường, kể cả coverage/width | evaluate/Baselines PR #13 | MVP 2019 |
| 16 | Sửa/nối giá có ngày sau base_date, giữ nguyên dữ liệu lịch sử đến origin | q/p/count baseline tại origin không đổi | evaluate/Baselines PR #13 | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 17 | WTI/Brent có expiry/roll: chỉ ở base_date hoặc ở target_date, có hoặc không có raw | Chỉ roll ở base_date không loại; roll ở target_date loại khỏi excl_roll nhưng vẫn thuộc all nếu đủ điều kiện; crossing/excl_roll vẫn xuất Accuracy not_applicable/value=null/n_obs=0/unsupported_sample, kể cả mask rỗng; không nhân đôi Detail | evaluate | MVP 2019 |
| 18 | y=0 hoặc q50=0 trong common | Không vào sign; các metric thường khác vẫn dùng; crossing độc lập | evaluate | MVP 2019 |
| 19 | Không còn điểm common vì baseline thiếu, thiếu target hoặc nhiều nguyên nhân | Metric áp dụng: undefined/value=null/n_obs=0/no_evaluable_obs; excluded_insufficient_baseline chỉ đếm trong log, không dùng làm undefined_reason | evaluate | MVP 2019 |
| 20 | Nhập DynamoDB 6 chữ số, không raw | crossed_raw=null; profile rounded, ghi giới hạn p/q; không normalize hoặc tái tính thay p đã lưu | adapter | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 21 | Một model_version có hai fit_id sau retrain | MVP từ chối retrain; giao thức tương lai chọn fit theo origin, không double count | fits metadata/evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 22 | q chứa NaN/Infinity, thiếu một mức hoặc crossing ở hàng ok | Generate ghi invalid_model_output; import ok sai cấu trúc bị từ chối, không thay 0 | generate/adapter | MVP 2019: generate/validation nội bộ; Phase 2: import production |
| 23 | base_date không là phiên NYSE/CME tương ứng | Từ chối trước join, không dịch sang phiên gần nhất | adapter/evaluate | MVP 2019 |
| 24 | Return WTI hai đầu có giá <=0 dù clean chấp nhận giá âm | y=null/target_valid=false; không lấy log abs(price) | evaluate | MVP 2019 |
| 25 | Mean baseline loss=0 với n_common>0 | Skill undefined/zero_denominator, giữ n_obs; loss/coverage khác vẫn có thể tính | evaluate | MVP 2019 |
| 26 | crossing có raw nhưng target chưa có hoặc baseline thiếu | Vẫn tính crossing/all trong khoảng origin; unknown raw không biến false; dòng dầu/excl_roll là not_applicable/unsupported_sample | evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 27 | Rolling MVP không có manifest/CloudWatch audit lịch, Forecasts thực có evidence; thử missing row và input chưa READY | Không cần manifest/log gate; missing chỉ đếm, không bịa nguyên nhân/forecast; input chưa READY không promote; input hợp lệ với 0 cặp có thể COMPLETED đủ 28 undefined và derived null theo §7 | evaluate/adapter | Rolling MVP theo RFC #45 v4.6; không đổi validation/test/import |
| 28 | Hai run model có ngày missing khác nhau | DM ghép giao theo khóa ngày/h; không ghép theo vị trí vector | evaluate | MVP 2019 |
| 29 | Skill từng dòng có baseline=0, nhưng baseline mean trên common>0 | Tính tỷ số hai mean; không lấy mean skill từng dòng hoặc bỏ dòng baseline=0 | evaluate | MVP 2019 |
| 30 | Timestamp công bố bằng as_of_time; target publication bằng as_of_time | Input được dùng với <=; target ở ngưỡng bằng bị từ chối vì cần < | generate/evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 31 | Future revision nằm trong snapshot mới nhất | Không tự xác nhận PIT; backtest_publication_rule vẫn được chọn model MVP nếu qua kiểm tra công bố và ghi giới hạn vintage; verified_backtest cần chứng cứ thật | adapter/fits metadata | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 32 | Lookup lịch ra ngoài phạm vi 2010–2030 hiện có | Lỗi cấu hình/phụ thuộc rõ ràng; không coi rỗng lịch là không có expected forecast | evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 33 | Nguồn hỗ trợ crossing nhưng không có raw hữu hạn đủ điều kiện trong khoảng đánh giá | crossing undefined/no_evaluable_obs, value/CI=null, n_obs=0; khác nguồn không hỗ trợ raw ở case 3 | evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 34 | Xuất Accuracy thiếu/null evaluation_kind hoặc target_cutoff_date | Từ chối hàng sai schema; cả hai trường bắt buộc và có trong khóa logic | evaluate/bộ chuyển dòng | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 35 | Tính mae_ratio_vs_naive cho model thông thường | Mẫu số là mean(abs(y)) trên common; không sinh hàng Accuracy model_version=naive-zero hoặc sign riêng cho Naive | evaluate | Hồi quy hỗ trợ / phase 2 theo nguồn |
| 36 | Validation 2019 trên snapshot mới nhất, chưa có vintage | backtest_publication_rule; as_of_time=published_at(base_date); kiểm tra input<=as_of_time<target publication; được chọn model và bắt buộc ghi giới hạn vintage, không gán PIT verified | generate/evaluate | MVP 2019 |
| 37 | FeatureBatch có cả window invalid, thiếu lịch sử và timestamp UTC-naive/NaT | Giữ mọi origin và đủ lần thử h; mapping theo mục 3.1; chỉ make_windows cắt input; gắn UTC đúng, không coi NaT là hợp lệ; scaler của fit, không fit trên 2019 | generate/Feature Builder PR #14 | MVP 2019 |
| 38 | CI pinball_skill trên asset/h có ngày giao dịch/missing khác nhau | Block 20, 1000 replicate, 95%, seed cfg; cùng kế hoạch ngày thật; giữ cặp loss và ngày rút lặp, không fill/ghép lệch ngày; tính lại tỷ số hai mean; CI không tính được ghi null và log | evaluate/Metrics PR #11 | MVP 2019 |
| 39 | DM model–baseline hoặc hai model thật trong luồng demo, có p NaN | Loss baseline cùng Detail hoặc join hai model đúng lineage; lag h−1, uniform weights và HLN; Holm giữ 28/14 vị trí kể cả NaN, không bịa p | evaluate/Metrics PR #11 | MVP nếu demo dùng DM/Holm |
| 40 | Fits validation thiếu trường bắt buộc, hoặc đổi fit/scaler trong 2019 | Tám trường mục 6 bắt buộc; max_training_label_available_at tùy chọn nhưng vẫn kiểm tra availability; commit từ workflow; không retrain/refit scaler trong 2019 | fits metadata/generate | MVP 2019 |

Nhóm ID MVP Khải chỉ định được giữ nguyên: **1, 2, 4, 5, 8, 11, 12, 14, 15, 17, 18, 19, 23, 24, 25, 28, 29**. Theo review bổ sung, nhánh generate/validation nội bộ của **9, 10, 22** cũng thuộc MVP 2019; chỉ nhánh import production của các ID này thuộc phase 2. ID 36–40 chỉ bổ sung kiểm tra các quyết định mới về provenance, Feature Builder, CI/DM và Fits/model cố định; không đánh số lại 1–35. Nhãn hồi quy hỗ trợ/phase 2 không miễn các bất biến cấu trúc, publication hoặc leakage khi áp dụng trong MVP; external import production vẫn phase 2; Rolling MVP theo §7, có bộ nghiệm thu riêng bên dưới.

Các quyết định review đã chốt được ghi ở mục 14; bản cập nhật vẫn cần reviewer xác nhận. Hoàn thành triển khai về sau cần kiểm thử nhóm MVP và các bất biến áp dụng; tài liệu này không tuyên bố code walk-forward đã tồn tại hoặc đã vượt acceptance tests.

### 13.1. Nghiệm thu bổ sung Rolling MVP (tài liệu; chưa tuyên bố đã chạy integration)

- 0/19/20 distinct coverage base dates: cả 5 overall display fields cùng gate; undefined không ready; mọi h counts_only; fixtures v3.1 parse và disclaimer khớp forecast_format.DISCLAIMER.
- Width_pct tính từng cặp q10/q90 bất đối xứng, gộp theo n_obs, cùng mask/width; kiểm META derived fingerprint và vẫn đúng 28 METRIC, không h=0.
- Expected = published + missing trong cùng scope; row hiện diện nhưng unverified không vào n_obs; thiếu row/log không chặn completed; snapshot chưa READY khác common rỗng trên input đã READY.
- Post-cutover thiếu/sai snapshot hoặc conditional provenance loại; legacy chỉ nhận danh sách audit đã duyệt, không dùng timestamp/field/dry_run làm bằng chứng đủ; kiểm cutover thực khác ngày dự kiến.
- Retry same payload no-op, khác payload conflict; 27/28 rows không promote; crash trước/sau completion; pointer đổi trong lúc GET; cùng order khác run conflict; hai mappings mismatch fail-closed theo asset.
- CDK kiểm cron TUE–SAT 13:45 UTC, timeout 300s, retry=0, không reserved concurrency; IAM reader deny writes/Scan/S3; Errors→SNS và input readiness.
- Shadow missing/late/error không chặn champion; paired counts chỉ phần giao; report immutable đúng prefix; đổi riêng champion không dùng S1a baseline cho model mới. Không thực thi DM gap hoặc chạy lại K4 trong cập nhật này.

## 14. Quyết định đã chốt và phụ thuộc còn lại

### 14.1. Resolved — không yêu cầu chọn lại

| Quyết định [KHẢI12] | Quy tắc áp dụng |
|---|---|
| Baseline-252 | PR #13 tính và gắn baseline/loss/validity vào Detail; không Baseline Adapter, model giả, Fits hoặc Internal Forecasts baseline |
| Roll | Brent/WTI kiểm tra (base_date,target_date]; unknown giữ chính sách null; crossing/excl_roll vẫn not_applicable/unsupported_sample |
| Tie prob_up | Chọn τ cao nhất của nhóm trùng theo CDF liên tục bên phải; crossing raw trước normalize một lần |
| Bootstrap/CI | Block 20 phiên, 1000 replicate, CI 95%, seed cfg; kế hoạch ngày chung theo mục 11.2; CI pinball_skill bắt buộc MVP |
| DM | PR #11 theo review: loss từng điểm, lag h−1, uniform weights, HLN; không Bartlett |
| Holm | Mỗi họ so sánh có all=28, excl_roll=14 vị trí; NaN vẫn chiếm chỗ |
| Provenance MVP | backtest_publication_rule cho phép model selection validation 2019, bắt buộc ghi giới hạn vintage; không phải PIT verified |
| Fits MVP | Tám trường bắt buộc mục 6; max_training_label_available_at tùy chọn, không bỏ kiểm tra availability; commit từ workflow |
| Module và features | Một src/eval/walk_forward.py; chỉ PR #14 make_windows cắt input; không tạo module trong nhiệm vụ tài liệu |

### 14.2. Phụ thuộc tích hợp và phase 2

| Phụ thuộc / người review | Việc thực sự còn lại | Phạm vi / tác động |
|---|---|---|
| Metrics PR #11 | Đối chiếu bản đã sửa uniform DM/HLN/Holm; snapshot cục bộ vẫn Bartlett. Bootstrap helper hữu hạn theo hàng chưa tự giữ lịch có missing; orchestration phải áp kế hoạch ngày chung trước khi tính replicate | Điều kiện tích hợp MVP cho CI pinball_skill; DM/Holm khi thuộc demo. Không sửa metrics hoặc tự triển khai công thức trong nhiệm vụ này |
| Returns/Baselines PR #13; Feature Builder PR #14 | API đã đọc trực tiếp từ hai ZIP mới, nhưng local returns còn cũ, baselines/forecast_record/build chưa có; đưa đúng phiên bản vào luồng triển khai và xử lý UTC/NaT theo mục 3.1 | Phụ thuộc triển khai MVP, không còn câu hỏi về API hoặc yêu cầu cung cấp lại ZIP; PR #14 phụ thuộc PR #13 |
| Accuracy PR #10 | `docs/api/accuracy-schema.md` là tài liệu tham chiếu hiện có của repository về logical keys, metrics, status và `evaluation_kind`. Trạng thái merge của PR #10 không được xác nhận trong phạm vi cập nhật này. | Giữ nguyên schema đã chốt; không yêu cầu sửa hoặc định nghĩa lại Accuracy Schema trong cập nhật này |
| Tuấn/Khải — mục 5.5, 7, 10 | External import, tolerance ngoài Rolling và PIT nâng cao vẫn phase 2; Rolling theo §7 không còn yêu cầu manifest phát hành | Không chặn validation 2019; Rolling cần implementation/IAM/CDK/smoke tests riêng, không xác nhận đã deploy |
| Khải — tên reason thiếu raw ở mục 5.4 | Ưu tiên mã đã có của Accuracy Schema; chỉ nếu cần mã mới missing_raw_quantiles thì phải review tên trước khi dùng | Liên quan import thiếu raw phase 2; không tự thêm enum hoặc đổi status crossing đã chốt |

Giữ nguyên mask/cutoff/status đã được xác nhận: common rỗng dùng undefined/no_evaluable_obs dù vì baseline thiếu; excluded_insufficient_baseline chỉ là log. Không mở lại baseline, boundary roll, CI configuration, họ Holm hoặc provenance MVP thành quyết định OPEN.


