# ADR-0005: Nguồn dữ liệu giá vàng, bạc, dầu và tỷ giá USD/VND

- Ngày: 2026-10-07 (cập nhật 2026-10-08: gỡ Tiingo sau phản hồi của Tiingo)
- Trạng thái: Đề xuất
- Người viết: Trịnh Tiến Khải (bản nháp do Claude Code soạn từ kết quả probe); người duyệt: Huỳnh Ngọc Tuấn (IA), Nguyễn Tiến Long

## Bối cảnh
Mô hình cần chuỗi giá ngày từ 01/2012 (khởi động CEEMDAN 2012–2013, train 2014–2018, validation 2019, test 2020 → nay) cho vàng, bạc, Brent, WTI và tỷ giá USD/VND, cập nhật hằng ngày bằng Lambda `ingest`. Ràng buộc:

- Nhóm không trả phí dịch vụ dữ liệu; credit AWS 200–400 USD.
- Mỗi chuỗi dùng **một** nguồn cho cả lịch sử lẫn cập nhật hằng ngày (không ghép nguồn).
- Không rò rỉ dữ liệu tương lai: biết thời điểm dữ liệu thực sự có sẵn (`published_at`).

Probe ngày 07–08/10/2026 (`scripts/probe_sources.py`, `scripts/probe_metals_fx.py`, báo cáo trong `data/lake/probe/`) cho thấy:

- **FRED đã gỡ toàn bộ chuỗi LBMA vàng/bạc từ 01/2022.**
- Hai hợp đồng kim loại trên yfinance là GC=F và SI=F. Yahoo theo hợp đồng gần đáo hạn nhất, không phải hợp đồng giao dịch nhiều nhất:
  - GC=F có volume trung vị < 200 trong 2012–2019, đúng giai đoạn train.
  - SI=F có volume trung vị 20–150 trong toàn bộ giai đoạn.

## Các phương án

| # | Phương án | Ưu | Nhược | Chi phí | Kết luận |
|---|---|---|---|---|---|
| 1 | MetalpriceAPI trả phí | Một API cho kim loại, dầu, VND | Gói Free 100 request/tháng, không rõ độ sâu lịch sử | ≥ 5 USD/tháng | Loại: nhóm không trả phí dữ liệu |
| 2 | WGC (World Gold Council) | Giá vàng chuẩn, trung bình tháng | Chỉ tải tay; điều khoản hạn chế; không có bạc, dầu | 0 | Loại làm nguồn; có thể dùng đối chiếu nội bộ |
| 3 | Stooq | CSV miễn phí cho XAU, XAG, USD/VND | Key qua CAPTCHA, quota thấp; không lấy được key qua giao diện (07/10/2026) | 0 | Tạm bỏ |
| 4 | yfinance, hợp đồng tương lai kim loại (GC=F, SI=F) | Không cần key, lịch sử đủ từ 2012 | Theo hợp đồng ít giao dịch trong giai đoạn train; có roll | 0 | Loại làm nguồn; chỉ dùng tính hệ số hiển thị |
| 5 | Tiingo EOD, quỹ ETF (GLD, SLV) | API chính thức, chất lượng tốt | Gói Starter chỉ cho dùng cá nhân/nội bộ, không cho hiển thị, không cho lưu bền (xem mục "Phản hồi của Tiingo") | 0, nhưng muốn hiển thị phải mua gói khoảng 250 USD/tháng | **Loại (08/10/2026)** |
| 6 | **yfinance, quỹ ETF (GLD, SLV)** | Không cần key; trùng Tiingo đến ≤ 0,06%/ngày | API không chính thức; điều khoản Yahoo chỉ cho dùng cá nhân | 0 | **Chọn** |
| 7 | **yfinance, CL=F, BZ=F, VND=X** | Không cần key, đủ từ 2012 | Như trên; BZ=F 2014–2018 ít giao dịch; VND=X có giá trị hỏng | 0 | **Chọn** |
| 8 | EIA API v2 (RWTC, RBRTE) | Chính thức, dữ liệu công; có WTI −36,98 ngày 20/4/2020 | Phát hành hằng tuần; API và file XLS lệch ngày; có dòng vào ngày lễ | 0 | Chỉ dùng đối chiếu |
| 9 | NBP (Ba Lan), giá vàng PLN/g | Chính thức, không key, từ 2013 | Chốt giá trưa giờ Warsaw → lệch một ngày so với giá Mỹ; không có bạc | 0 | Chỉ dùng đối chiếu |
| 10 | Tiingo FX USD/VND | — | Gói free chỉ có FX từ 2020; `usdvnd` trả về rỗng | — | Loại |

## Phản hồi của Tiingo (07/10/2026)
Nhóm đã hỏi Tiingo về việc dùng gói Starter (miễn phí) cho đồ án. Tóm tắt câu trả lời:

- Gói Starter chỉ dành cho mục đích cá nhân hoặc nội bộ.
- Hiển thị giá hay biểu đồ dựng từ dữ liệu Tiingo cho người khác, kể cả giảng viên, đã bị coi là phân phối lại. Muốn làm vậy phải dùng gói trả phí, khoảng 250 USD/tháng.
- Theo điều khoản cập nhật ngày 06/10/2026, gói Starter chỉ cho lưu **tạm thời** dữ liệu Tiingo và các sản phẩm phái sinh từ dữ liệu đó, không cho lưu lâu dài.

Hệ quả:
- Gỡ Tiingo khỏi pipeline, cả vai trò nguồn chính lẫn dự phòng. Xóa adapter, test và key mẫu.
- **Ngày 08/10/2026 đã xóa toàn bộ dữ liệu Tiingo đã lưu**: dữ liệu thô `raw/tiingo/`, các bản clean có dòng `source=tiingo`, và báo cáo probe có số liệu phái sinh từ Tiingo. Sau đó chạy lại ingest và xác nhận trong `data/lake` chỉ còn nguồn `yfinance` và `eia`.
- Số liệu GLD/SLV trong phần Bằng chứng đã được tính lại từ yfinance.

## Quyết định

| Chuỗi | Nguồn | Đối chiếu (chỉ trong `quality.py`) |
|---|---|---|
| Vàng | **GLD** qua yfinance | NBP: mức giá và trung bình tháng |
| Bạc | **SLV** qua yfinance | — |
| WTI | **CL=F** qua yfinance | RWTC (EIA API v2): tỷ số CL=F/RWTC, đánh dấu khi lệch > 3% so với trung vị trượt 60 phiên trước đó |
| Brent | **BZ=F** qua yfinance | Return ngày so với CL=F (cùng giờ chốt), đánh dấu phần dư > 8%; RBRTE chỉ so mức giá (chênh lệch trung vị theo năm) |
| USD/VND | **VND=X** qua yfinance | — |

Không có nguồn dự phòng. Lỗi nguồn xử lý **theo từng tài sản** (cập nhật 10/10/2026):
- Nguồn của một tài sản chính (vàng, bạc, WTI, Brent, USD/VND) lỗi hoặc trả rỗng: tài sản đó giữ dữ liệu clean của lần trước, dòng cuối gắn `flag=stale_source`; `quality.json` có `stale_sources[asset]` với ngày dữ liệu cuối và lỗi. Các tài sản khác vẫn cập nhật, bản clean mới vẫn được ghi. Pipeline log dòng `ERROR INGEST_SOURCE_FAILED` và thoát mã 1 để Lambda kích CloudWatch alarm.
- Lần chạy thành công sau đó tải lại từ phiên thứ 5 tính từ cuối của tài sản cũ nhất, nên khoảng trống được bù và `stale_source` tự mất.
- Nếu USD/VND lỗi, tỷ giá hiển thị cũng mang `stale_source`.
- Nguồn tham chiếu (EIA, GC=F, SI=F, NBP) lỗi chỉ log `WARNING INGEST_REFERENCE_FAILED`, giữ bản tham chiếu cũ, thoát mã 0.
- **`xcheck_skipped` trong `quality.json`** (bổ sung 12/10/2026): đối chiếu với EIA chỉ chạy trên ngày có cả giá lẫn tham chiếu, nên ngày thiếu tham chiếu không có cờ. Để không nhầm "chưa đối chiếu" với "đối chiếu không thấy lệch", mỗi phép đối chiếu (`xcheck_level` với RWTC, mức giá Brent với RBRTE) ghi tài sản, lý do, ngày cuối có tham chiếu và khoảng ngày chưa đối chiếu. Hai lý do:
  - `source_unavailable`: EIA lỗi hoặc thiếu key; log `WARNING XCHECK_SKIPPED`.
  - `reference_pending`: EIA chạy bình thường nhưng chưa công bố tới các ngày đó (trễ date+7); chỉ ghi nhận, log mức INFO.
  `xcheck` trong `quality.json` cũng ghi `last_checked_date`.

Lớp adapter (`src/data/sources/`) cho phép thay nguồn mà không phải sửa phần clean và quality.

Các quy tắc đi kèm:
- **GC=F và SI=F không dùng làm nguồn.** Chúng chỉ dùng để tính hệ số hiển thị: giá vàng USD/oz = GLD × trung vị 20 phiên gần nhất của (GC=F/GLD). Bạc tính tương tự với SI=F/SLV nhưng gắn nhãn `reliability=low`. Hệ số này **không đưa vào train**.
- **EIA chỉ dùng qua API v2**, bỏ đường XLS. Dòng rơi vào ngày nghỉ của thị trường gắn `flag=suspect_holiday_row`. Lỗi đã biết của EIA (RWTC 25/09 và 28/09/2026) gắn `known_source_error` và bị loại khỏi đối chiếu.
- **VND=X:**
  - Loại các dòng ngoài khoảng 20.000–30.000 với `flag=bad_value`, không sửa bằng giá Open.
  - Loại spike với `flag=bad_value|spike`: giá vọt quá 2% so với phiên được giữ gần nhất, rồi trong tối đa 3 phiên (`SPIKE_MAX_SESSIONS`) quay về trong ±1% quanh mức cũ → loại cả đoạn. Ngày trong `KNOWN_EVENTS` không bị xét. Spike tính lại trên toàn bộ lịch sử mỗi lần chạy. Lần chạy 08/10/2026 (quy tắc một phiên) loại 10 ngày; lần chạy 09/10/2026 (quy tắc theo đoạn) loại 12 ngày, thêm đoạn 03/04 và 06/04/2015.
  - USD/VND chỉ dùng hiển thị, không làm đặc trưng.
  - **Tỷ giá hiển thị** (`clean/display_fx/`): nếu trong 3 phiên gần nhất có cú vọt > 2% mà quy tắc spike chưa xét xong, hiển thị giá phiên trước cú vọt với `flag=pending_confirm`; các lần chạy sau hoặc loại đoạn đó (spike) hoặc, sau 3 phiên không quay về, hiển thị giá mới. `prices.parquet` không bị ảnh hưởng.
  - Giá đứng chỉ đánh dấu (`stale`), không loại.
- **Cờ `xcheck_*` (`xcheck_level`, `xcheck_resid`) chỉ để đánh dấu chất lượng** (bổ sung 11/10/2026): không dùng làm đặc trưng mô hình, và không dùng để lọc dòng trong backtest, train hay inference. Lý do:
  - `xcheck_level` dựa trên RWTC, mà RWTC có `published_at` = date+7. Tại thời điểm dự báo, cờ này chưa thể biết, nên dùng nó là rò rỉ dữ liệu tương lai.
  - `xcheck_resid` là cờ chẩn đoán chất lượng Brent.

  Hai cờ này chỉ xuất hiện trong `quality.json` và báo cáo chất lượng dữ liệu.
- **Ngưỡng `jump` theo tài sản (chỉ đánh dấu):** vàng 8%, bạc 10%, dầu 15%, USD/VND 2%. Các ngày có biến động thật đã kiểm chứng nằm trong `config.KNOWN_EVENTS` và không bị đánh dấu.
- **Lịch phiên** (`pandas_market_calendars`):
  - Hợp đồng tương lai dùng lịch CME. Ngày có settlement là ngày hợp lệ của CMEGlobex_EnergyAndMetals, trừ các ngày Globex chỉ mở rút ngắn mà NYSE nghỉ.
  - ETF dùng lịch NYSE.
  - Thanh rơi vào ngày sàn đóng cả ngày bị loại với `flag=exchange_holiday`.
- **Không forward-fill target.** Mỗi tài sản giữ lịch riêng; việc ghép về một lịch chung để làm đặc trưng để dành cho `build.py` (tuần 2).
- **Roll hợp đồng:** ngày roll gắn `flag=roll` (phiên đầu tiên sau ngày đáo hạn, tính theo quy tắc CL và quy tắc ICE Brent). Không dùng chuỗi back-adjusted.
- **`published_at`** là hằng số cấu hình theo nguồn (`config.PUBLISHED_AT_RULES`):
  - Tạm thời: 12:00 UTC ngày date+1 cho yfinance; 12:00 UTC ngày date+7 cho EIA.
  - Sẽ sửa sau khi đo xong độ trễ chốt thanh của yfinance (`probe_metals_fx.py --bars-only`).
  - **Giờ chạy khớp `published_at`** (chốt 10/10/2026): Lambda ingest chạy 12:15 UTC từ thứ Ba đến thứ Bảy (`config.INGEST_SCHEDULE_EXPRESSION` = `cron(15 12 ? * TUE-SAT *)`, múi giờ UTC); predict chạy nối tiếp sau ingest. Khi rút `published_at` thì rút giờ chạy cùng lúc (có test kiểm tra hai giá trị khớp nhau).
- **`xcheck_level` (WTI)** so tỷ số CL=F/RWTC với trung vị trượt 60 phiên chung trước đó (nhân quả, không gồm t), không so với 1,0. Lý do: từ 2024, CL=F thấp hơn RWTC có hệ thống (trung vị theo năm −1,1% năm 2024, −1,0% năm 2025, −1,5% năm 2026), khiến quy tắc cũ đánh dấu hàng loạt mỗi khi chênh lệch này nới thêm. Trên bản clean 09/10/2026, tổng số ngày bị đánh dấu giảm từ 94 xuống 50; 2014–2020 không đổi, 2022 từ 8 xuống 2, 2024 từ 1 xuống 0, 2026 từ 47 xuống 10.

## Bằng chứng (probe 07–08/10/2026)

**Vàng, bạc: ETF so với hợp đồng tương lai** (tất cả lấy qua yfinance)

| Chỉ số | GLD | SLV | GC=F | SI=F |
|---|---|---|---|---|
| Ngày đầu / phiên mỗi năm (năm đủ) | 03/01/2012 / 250–253 | 03/01/2012 / 250–253 | 03/01/2012 / 250–253 | 03/01/2012 / 250–253 |
| Volume trung vị theo năm | 5,5–10,5 triệu | 5,4–26 triệu | **< 200 (2012–2019)**, khoảng 150.000–200.000 (2020→) | **20–150** |
| % Close = Open | 0,43% | 3,1% | 3,5% | 19,6% |
| Tương quan log return với ETF, 2012–2019 / 2020→ | — | — | 0,885 / 0,914 | 0,904 / 0,911 |

- **GLD/SLV qua yfinance trùng với Tiingo** trên 3.711/3.711 ngày, chênh lệch lớn nhất 0,046% (GLD) và 0,062% (SLV). Kết quả này được đo ngày 07/10/2026, trước khi xóa dữ liệu Tiingo.
- **Adj Close = Close** ở mọi ngày: GLD và SLV không chia cổ tức, không tách cổ phiếu.
- **Hệ số quy đổi ETF → USD/oz giảm đều theo năm, đúng bằng phí quản lý quỹ, không có điểm gãy:**
  - GLD/GC=F: 0,0971 (2012) → 0,0914 (2026), khoảng −0,4%/năm.
  - SLV/SI=F: 0,971 → 0,905, khoảng −0,5%/năm.
- **NBP:** return ngày t của NBP khớp với GLD/GC=F ngày t−1 (tương quan khoảng 0,6), vì NBP chốt giá vào trưa giờ Warsaw. Vì vậy NBP chỉ hợp để đối chiếu mức giá và trung bình tháng. Lần chạy 08/10/2026: chênh lệch trung bình tháng ở mức trung vị 0,15%; 9/166 tháng lệch quá 1%.

**Dầu:**
- **CL=F so với RWTC:** chênh mức giá trung vị 0,12%, tương quan return 0,95. Ngày 20/4/2020: CL=F −37,63 (trùng settlement chính thức), RWTC −36,98.
- **Phần dư return > 3% giữa CL=F và RWTC dồn vào ngày 20–31 trong tháng**, khớp lịch đáo hạn. Quy tắc đáo hạn ICE Brent cũ khớp **16/16 phiên BZ=F bị thiếu trong 2012–2013**: tất cả đều là phiên thứ 1 hoặc thứ 2 ngay sau ngày đáo hạn.

**Brent: BZ=F theo năm** (tương quan return; RBRTE~RWTC là mốc cho thấy chính chuỗi giá giao ngay của EIA cũng nhiễu):

| Năm | % Close=Open | % giá trùng hôm trước | ~RBRTE | ~CL=F | RBRTE~RWTC | Volume trung vị |
|---|---|---|---|---|---|---|
| 2012 | 1,65 | 0,00 | 0,739 | 0,836 | 0,618 | 782 |
| 2013 | 6,58 | 2,47 | 0,693 | 0,703 | 0,589 | 4.940 |
| 2014 | 5,20 | 0,80 | 0,686 | 0,823 | 0,577 | 8.998 |
| 2015 | 4,76 | 0,79 | 0,569 | 0,865 | 0,525 | 24.588 |
| 2016 | 5,60 | 0,00 | 0,778 | 0,884 | 0,747 | 28.422 |
| 2017 | 3,59 | 0,00 | 0,631 | 0,926 | 0,577 | 27.804 |
| 2018 | 2,39 | 1,59 | 0,727 | 0,898 | 0,619 | 29.917 |
| 2019 | 0,79 | 0,79 | 0,778 | 0,920 | 0,692 | 35.871 |
| 2020 | 1,19 | 0,00 | 0,800 | 0,892 | 0,713 | 29.327 |
| 2021 | 0,79 | 0,40 | 0,972 | 0,973 | 0,941 | 32.182 |
| 2022 | 0,00 | 0,40 | 0,938 | 0,938 | 0,911 | 22.959 |
| 2023 | 0,40 | 0,00 | 0,933 | 0,969 | 0,920 | 26.913 |
| 2024 | 0,00 | 0,79 | 0,772 | 0,963 | 0,734 | 33.167 |
| 2025 | 0,00 | 0,00 | 0,915 | 0,972 | 0,895 | 38.915 |
| 2026 | 0,00 | 0,52 | 0,857 | 0,911 | 0,803 | 42.047 |

**USD/VND (VND=X):**
- Có đủ từ 02/01/2012, nhưng chất lượng thấp:
  - 6 giá trị Close nằm ngoài khoảng hợp lệ (2012–2014).
  - 10 spike một ngày (2012–2021).
  - Khoảng 17% số ngày giá đứng; 42% số ngày Close = Open.
- Tiingo FX không có cặp này. Ngoài VND=X không còn ứng viên miễn phí nào.

**EIA, API v2 so với file XLS:**
- RBRTE: 11 ngày chỉ có trong API (có cả 25/12 và 1/1), 9 ngày chỉ có trong XLS, 3 ngày khác giá.
- RWTC: 26 ngày chỉ có trong API, 8 ngày chỉ có trong XLS.

## Hệ quả

### Điều khoản và hiển thị: **chốt lựa chọn (b) ngày 28/10/2026**
- **Yahoo Finance có điều khoản tương tự Tiingo**: dữ liệu chỉ dành cho mục đích cá nhân. yfinance là thư viện không chính thức, có thể bị chặn hoặc đổi định dạng bất cứ lúc nào.
- Dùng yfinance để huấn luyện và đánh giá nội bộ có cùng mức rủi ro như mọi dự án học thuật dùng nguồn này. Phần rủi ro chính là **hiển thị giá** cho người khác.
- Hai lựa chọn hiển thị đã cân nhắc:
  - **(a)** Giảng viên chấp nhận dùng dữ liệu Yahoo cho buổi demo đồ án. Web hiển thị giá và biểu đồ vàng, bạc, dầu như thiết kế, chỉ mở sau đăng nhập Cognito, có ghi nguồn và không có tính năng tải dữ liệu.
  - **(b)** Chỉ hiển thị chuỗi giá từ nguồn công khai (dầu từ EIA: RWTC, RBRTE). Với vàng và bạc, chỉ hiển thị **kết quả dự báo dạng % return và xác suất tăng**, không hiển thị chuỗi giá hay khoảng giá USD/VND dựng từ dữ liệu Yahoo.
- **Quyết định ngày 28/10/2026: chọn (b).** Nhóm tự chốt, không chờ giảng viên, vì (b) không phụ thuộc điều khoản Yahoo và đã chạy trên web từ trước. Web giữ `VITE_SHOW_METAL_PRICES=false`; chatbot cùng quy tắc (tool v2 không trả giá vàng/bạc). Bỏ chế độ (a) khỏi phạm vi trước buổi bảo vệ.
- Áp dụng cho cả hai lựa chọn:
  - Dự án phi thương mại.
  - Luôn ghi nguồn (`config.SOURCE_ATTRIBUTION` = "Nguồn: Yahoo Finance, U.S. EIA").
  - Không có tính năng tải hay xuất dữ liệu giá.
  - Cache trên S3 để không gọi nguồn mỗi lần người dùng xem trang.
- **EIA, NBP:** dữ liệu công, ghi nguồn khi dùng.

### Lệch giờ chốt
| Chuỗi | Giờ chốt |
|---|---|
| GLD, SLV | 16:00 ET (NYSE đóng cửa) |
| CL=F, BZ=F | 14:30 ET (settlement NYMEX) |
| GC=F | 13:30 ET |
| NBP | khoảng trưa giờ Warsaw |
| VND=X | 00:00 giờ London (một lần chụp giá, không phải giá đóng cửa) |

- Vào **ngày họp FOMC** (thông báo lúc 14:00 ET), GLD phản ánh tin ngay trong ngày, còn GC=F (và cả CL=F, BZ=F) chỉ phản ánh vào phiên sau. Bằng chứng: các cặp phần dư lớn nhất giữa GLD và GC=F đều rơi vào ngày FOMC (18–19/9/2013, 16–17/3/2016, 15–16/6/2016, 14/12/2016, 15/3/2017, 31/7–1/8/2019).
- Khi ghép vàng, bạc với dầu về một lịch chung để làm đặc trưng, cần nhớ độ lệch khoảng 1,5 giờ này.

### Rủi ro dữ liệu cần theo dõi
- **BZ=F 2014–2018 ít giao dịch.** Đây là Brent trên NYMEX, còn thị trường Brent chính nằm ở ICE.
  - Trong 2014–2018, tương quan với CL=F chỉ 0,82–0,93 (từ 2021 là 0,94–0,97), và Close = Open ở mức 2,4–5,6% (từ 2021 gần 0%).
  - Phần lớn mức tương quan thấp với RBRTE là do chính RBRTE nhiễu: RBRTE~RWTC chỉ 0,52–0,75 trong cùng giai đoạn.
  - Ngày Close = Open gắn `flag=low_liquidity` (chỉ đánh dấu). `quality.json` báo tỷ lệ này theo năm.
  - Nếu ablation cho thấy Brent 2014–2018 làm mô hình kém đi, xem lại ADR này.
- **Toàn bộ 5 chuỗi chỉ phụ thuộc một nguồn không chính thức là yfinance**, không còn dự phòng.
  - Nếu yfinance ngừng hoạt động, ứng viên thay thế cho dầu là EIA (giao ngay, trễ một tuần). Với vàng, bạc và USD/VND hiện chưa có ứng viên miễn phí: Stooq tạm bỏ, còn MyLBMA thì Khải tự nộp đơn.
- **Thanh mới nhất của yfinance chưa ổn định:**
  - Thanh của ngày hiện tại đang chạy, nên bị bỏ theo giờ New York.
  - Đến khoảng 08:30 UTC hôm sau, volume của thanh hôm trước vẫn trùng hệt ngày trước đó.
  - Vì vậy pipeline tải lại 5 phiên gần nhất mỗi lần chạy và ghi đè theo khóa.
- **yfinance từ IP đám mây** (Lambda ap-southeast-1) có thể bị chặn. Cần chạy thử trước khi đưa lên production (giao cho Tiến).

### Chính sách sử dụng dữ liệu
1. Dữ liệu giá chỉ dùng nội bộ để huấn luyện và đánh giá mô hình. Việc hiển thị cho người khác theo quyết định (a) hoặc (b) ở trên.
2. **Không commit dữ liệu** vào git: `data/lake/` đã nằm trong `.gitignore`. Chỉ dữ liệu mẫu nhỏ `data/sample_*.csv` được phép commit.
3. **S3 (`s3://cpaws-<env>-lake/`) là bản chính.** Nhóm tự sao lưu sang Google Drive; code không đụng tới Drive.
4. Không làm tính năng tải hay xuất dữ liệu giá. Mọi màn hình có giá phải hiển thị `SOURCE_ATTRIBUTION`.
5. Chỉ lưu dữ liệu giá và phản hồi thô của API. Không lưu key; key nằm trong `.env` (local) hoặc nơi lưu secret trên AWS.
6. Nếu một nhà cung cấp yêu cầu ngừng sử dụng, dừng hiển thị chuỗi đó ngay, xóa dữ liệu đã lưu như đã làm với Tiingo ngày 08/10/2026, và xem lại ADR này.
7. Khi thêm nguồn mới, đọc điều khoản về hiển thị và lưu trữ **trước khi** tải dữ liệu.
