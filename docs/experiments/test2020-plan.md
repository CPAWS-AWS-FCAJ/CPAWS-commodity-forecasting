# Tập test 2020 → nay: kế hoạch chạy một lần (chốt trước khi chạy)

- Ngày: 31/10/2026; sửa 2/11/2026 theo review của Long ở #75
- Người viết: Khải (bản nháp do Claude soạn); người duyệt: Long
- Trạng thái: **Bản nháp.** Long approve, merge, rồi mới viết hoặc chạy code. Sau khi chốt, không đổi mô hình, dữ liệu, chỉ số hay cách dùng kết quả; thay đổi (nếu có) ghi thành mục mới có ngày, kèm lý do, trước khi chạy.
- Căn cứ: ADR-0008 (chia dữ liệu, chỉ số), ADR-0010 (S1a), ADR-0011 (champion/challenger), ADR-0012 (dừng dò mô hình), họp 30/10 điểm 19 và 21.

## 0. Mục đích

ADR-0008 dành 2020 → nay làm tập test, chỉ chạy một lần sau khi khóa tham số. Validation 2019 đã dùng 4 lần với 13 cấu hình (ADR-0012), nên tập test là bằng chứng ngoài mẫu duy nhất chưa bị nhìn. Lần chạy này trả lời một câu: mô hình đang chạy trên sản phẩm và challenger của nó hoạt động thế nào trên dữ liệu chưa từng dùng để chọn.

## 1. Mô hình (chốt)

| Mô hình | Vai trò | Tham số |
|---|---|---|
| `baseline-q252` | Champion, mốc của mọi `pinball_skill` | Phân vị thực nghiệm 252 phiên nhân quả, không học |
| S1a (`s1a-l094`) | Challenger (ADR-0010, 0011) | λ = 0,94, kẹp k_t ∈ [0,5; 2,0], chọn trên 2019 rồi khóa |
| naive (return = 0) | Mẫu số của `mae_ratio_vs_naive` | Không có |

Không chạy K3, K3b khác S1a, K4, DLinear: đều đã thua mốc trên validation, chạy thêm không giúp quyết định nào và chỉ tăng số cấu hình xem trên test.

## 2. Dữ liệu và khoảng thời gian (chốt)

- Bản clean: `clean/prices/dt=<DT>/`, DT là snapshot mới nhất có trên S3 tại lúc merge kế hoạch này. DT, SHA-256 của bản clean và lineage (nguồn yfinance, mã chuỗi, commit `src/data/` tạo bản clean) ghi vào mục 8 và vào `claim.json` **trước khi chạy**; runner kiểm lại SHA-256 khi nạp và dừng nếu lệch.
- Ngày gốc: từ 2020-01-02 đến 2026-10-23 (phiên cuối trước base 26/10, ngày đầu của luồng chạy thật), theo lịch của từng tài sản (NYSE cho GLD/SLV, CME cho BZ=F/CL=F).
- Mốc cắt ngày đích: 2026-10-23. Ngày gốc có ngày đích sau mốc này bị loại và được đếm, không lấy giá sau mốc.
- **Chỉ dùng thông tin có tại ngày gốc.** Với mỗi h, `baseline-q252` chỉ dùng return h phiên đã hoàn tất (ngày đích ≤ ngày gốc); EWMA của S1a chỉ dùng return 1 phiên đến ngày gốc. Lịch sử khởi động dùng return trước 2020 theo cùng quy tắc.
- **Giới hạn PIT:** bản clean mới nhất là giá tải lại, không phải ảnh chụp tại từng ngày gốc, nên không chứng minh PIT lịch sử đầy đủ (Yahoo có thể sửa giá cũ). Báo cáo ghi rõ giới hạn này.
- Target và quy tắc dữ liệu giữ nguyên ADR-0008 và `src/data/`: log return h phiên, h = 1–7; giá ≤ 0 hoặc thiếu → NaN; không forward-fill.
- **WTI 20/4/2020:** nằm trong giai đoạn biến động COVID (mục 4) nhưng mọi cặp có giá ≤ 0 ở ngày gốc hoặc ngày đích không được chấm; báo cáo số cặp bị loại theo tài sản × h.
- Dầu báo cáo hai mẫu `all` và `excl_roll` (cửa sổ roll tính theo kỳ đánh giá, như K4 mục 8).

## 3. Chỉ số (ADR-0008 mục 5)

### 3.1 Chỉ số chính (chốt định nghĩa)

- **Mặt nạ chung:** một bộ (tài sản, ngày gốc, h) được chấm khi target hợp lệ và cả `baseline-q252` lẫn S1a đều có dự báo. Hai mô hình luôn chấm trên đúng cùng một tập dòng; runner kiểm số dòng của hai mô hình bằng nhau theo từng tài sản × h × mẫu, lệch thì dừng.
- **Skill theo h:** `pinball_skill(a, h) = 1 − L_S1a(a, h) / L_base(a, h)`, L là pinball loss trung bình 7 phân vị trên các dòng của mặt nạ chung (đúng hàm `src/eval/metrics.pinball_skill`).
- **Chỉ số chính theo tài sản:** trung bình cộng 7 skill theo h, `S(a) = (1/7) Σ_h pinball_skill(a, h)`, trên mẫu `all`. Lấy trung bình 7 skill (không gộp loss) để mỗi kỳ hạn có trọng số như nhau, vì loss h = 7 lớn hơn h = 1 nhiều lần; đơn vị đánh giá vẫn là nhóm tài sản × h như ADR-0011. Nếu một h không có dòng nào hoặc `L_base(a, h) = 0` thì `S(a)` là undefined (không bỏ bớt h để tính tiếp), báo lý do.
- **4 giả thuyết chính** (một cho mỗi tài sản, mẫu `all`): H0: S(a) ≤ 0, H1: S(a) > 0 (một phía).
- **Bootstrap:** circular moving-block bootstrap trên lịch hợp nhất NYSE/CME (như `walk_forward.py`), block 20, B = 2000, seed cố định ghi trong config. **Một kế hoạch rút mẫu ngày dùng chung** cho mọi tài sản và mọi h, nên giữ phụ thuộc giữa kỳ hạn và giữa tài sản. Mỗi lần rút tính lại `S*(a)` từ các dòng của ngày được rút. Lần rút nào cho giá trị không hữu hạn thì CI undefined (theo `block_bootstrap_ci`), không bỏ lần rút.
- **p-value (bootstrap căn giữa theo H0):** mỗi lần rút tính `T*(a) = S*(a) − Ŝ(a)`, với Ŝ(a) là giá trị trên mẫu gốc; phân phối của T* xấp xỉ phân phối của Ŝ(a) − S(a), nên dùng làm phân phối dưới H0 (S(a) = 0). p một phía `p(a) = (1 + #{T*(a) ≥ Ŝ(a)}) / (B + 1)`. Không dùng tỷ lệ lần rút có S* ≤ 0 làm p-value.
- **Holm** qua 4 tài sản trên 4 p-value trên, α = 0,05. Kết luận "S1a tốt hơn mốc ở tài sản a" chỉ khi p Holm của a < 0,05.
- **CI 95% percentile** của `S*(a)` báo kèm để mô tả độ bất định, không dùng thay kiểm định.
- Các con số trên chỉ để báo cáo (mục 5); không dùng đổi champion.

### 3.2 Bất biến của S1a (kiểm trước khi tính chỉ số, sai thì dừng)

- q50 của S1a trùng `baseline-q252` từng bit trên mặt nạ chung (ADR-0010: S1a co giãn quanh trung vị của mốc).
- Vì vậy `mae_ratio_vs_naive` và `sign_accuracy` của hai mô hình phải bằng nhau.
- `prob_up` của S1a tính lại từ 7 phân vị của S1a bằng cùng hàm `prob_up` như production, không chép từ mốc.

### 3.3 Chỉ số phụ (báo cáo, không dùng chọn kết quả)

- 28 skill theo tài sản × h, kèm CI cùng kế hoạch bootstrap.
- Hiệu chỉnh: `quantile_hit_rates`, `coverage_80`, `width_80`, `width_80_pct`, `interval_score_80`, cho cả hai mô hình.
- Xác suất tăng: `brier_skill`.
- Phụ: `mae_ratio_vs_naive`, `sign_accuracy` kèm `up_rate`.
- DM (HAC, HLN) theo chính sách khoảng trống hiện có trong `walk_forward.py` (họ Holm 28 nhóm cho `all`, 14 cho `excl_roll`); chính sách mới hoãn sau 22/11 (điểm 21), báo cáo rõ các nhóm DM bị chặn.
- Không dùng MAPE, RMSE hay sai số trên mức giá.

## 4. Báo cáo bổ sung (chỉ báo cáo, không dùng chọn kết quả tốt nhất)

- Mẫu `excl_roll` cho dầu.
- Theo năm 2020, 2021, …, 2026.
- Hai giai đoạn biến động: 2020-02-15 → 2020-05-31 (COVID, gồm WTI âm) và 2022-02-15 → 2022-04-30 (Nga – Ukraine).
- Độ nhạy CI theo block 10 và 40.
- Số ngày gốc hợp lệ, số cặp bị loại theo lý do, theo tài sản × h × mẫu.

Kết luận chính chỉ dựa trên mục 3.1 (block 20, mẫu `all`); các mục trên không thay thế kết luận chính dù cho kết quả khác.

## 5. Kết quả dùng để làm gì (chốt trước khi chạy)

- Chỉ dùng cho báo cáo cuối và buổi bảo vệ.
- **Không đổi champion trước 22/11**, kể cả khi S1a có cận dưới CI > 0 ở tài sản nào đó (ADR-0011, họp 30/10 điểm 19). Muốn đổi champion sau đó phải có ADR mới.
- Kết quả xấu cho `baseline-q252` cũng không đổi sản phẩm trước 22/11; ghi trung thực vào báo cáo.
- Không có lần chạy thứ hai, không thêm mô hình hay cấu hình, không sửa thiết kế sau khi xem kết quả.

## 6. Chạy một lần

- Code: runner theo mẫu stage val2019 của `run_k4.py` (phần chặn, `started.json`, `verified_result`, SHA-256 từng file), `run_id = test2020` cố định. Code và test merge vào `developer` trước khi chạy; không dùng dữ liệu 2020 → nay khi viết hay test code (test dùng dữ liệu tổng hợp hoặc ≤ 2019).
- `claim.json` ghi trước khi chạy: commit (sạch), DT và SHA-256 bản clean, lineage (mục 2), mốc cắt, block, B, seed, `config_hash`, người chạy, thời điểm. Ghi lên `s3://cpaws-dev-lake/eval/test2020/claim.json` bằng `--if-none-match "*"`; `pip freeze` vào `env.txt`.
- Chạy xong: tải cả thư mục kèm SHA-256 lên `eval/test2020/`, báo ở PR kế hoạch.
- **Chạy lỗi giữa chừng:** không tự chạy lại, không đổi cấu hình. Ghi lỗi vào `failure.json` cạnh `claim.json`; cả nhóm quyết và ghi lý do thành mục mới của file này trước khi chạy lại (nếu có).
- Người chạy: Long, trên một máy và một venv. Khải review kết quả.
- Claude không xem, không tóm tắt kết quả 2020 → nay (quy tắc project).

## 7. Lịch

- Kế hoạch: PR #75, merge trước 10/11.
- Code runner: trước 15/11.
- Chạy: tuần 16–22/11, trước đóng băng.

## 8. Ghi trước khi chạy (cách xác định đã chốt ở mục 2 và 6; giá trị điền lúc claim)

- DT của bản clean: …
- SHA-256 bản clean: …
- Commit chạy: …
- `config_hash`: …

## 9. Sửa đổi

- 3/11/2026 (review Long lần 2, #75): p-value đổi sang bootstrap căn giữa theo H0; Holm áp trên p-value này; CI percentile chỉ để mô tả.
- 2/11/2026 (review Long, #75): chốt định nghĩa chỉ số chính (trung bình 7 skill theo h, mặt nạ chung, xử lý undefined); bootstrap dùng chung kế hoạch rút mẫu, 4 giả thuyết một phía, p-value và Holm; bất biến S1a; khóa DT/SHA-256/lineage trong `claim.json`, giới hạn PIT; WTI 20/4/2020; quy trình khi chạy lỗi; B từ 1000 lên 2000; tách rõ chỉ số phụ và báo cáo bổ sung.
