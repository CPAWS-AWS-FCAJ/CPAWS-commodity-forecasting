# Tập test 2020 → nay: kế hoạch chạy một lần (chốt trước khi chạy)

- Ngày: 31/10/2026
- Người viết: Khải (bản nháp do Claude soạn); người duyệt: Long
- Trạng thái: **Bản nháp.** Commit và push file này, Long approve, rồi mới viết hoặc chạy code. Sau khi chốt, không đổi mô hình, dữ liệu, chỉ số hay cách dùng kết quả; thay đổi (nếu có) ghi thành mục mới có ngày, kèm lý do, trước khi chạy.
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

- Bản clean: `clean/prices/dt=<DT>/`, DT là snapshot mới nhất có trên S3 tại lúc commit kế hoạch này; ghi DT và SHA-256 của bản clean vào mục 8 trước khi chạy.
- Ngày gốc: từ 2020-01-02 đến 2026-10-23 (phiên cuối trước base 26/10, ngày đầu của luồng chạy thật), theo lịch của từng tài sản (NYSE cho GLD/SLV, CME cho BZ=F/CL=F).
- Mốc cắt ngày đích: 2026-10-23. Ngày gốc có ngày đích sau mốc này bị loại và được đếm, không lấy giá sau mốc.
- Lịch sử khởi động: mốc 252 phiên và EWMA của S1a dùng return trước 2020 theo đúng quy tắc nhân quả hiện có; không đọc dữ liệu sau ngày gốc.
- Target và quy tắc dữ liệu giữ nguyên ADR-0008 và `src/data/`: log return h phiên, h = 1–7; giá ≤ 0 hoặc thiếu → NaN (WTI 20/4/2020); không forward-fill.
- Dầu báo cáo hai mẫu `all` và `excl_roll` (cửa sổ roll tính theo kỳ đánh giá, như K4 mục 8).

## 3. Chỉ số (ADR-0008 mục 5)

- Chỉ số chính: `pinball_skill` của S1a so với `baseline-q252`, trung bình 7 h, theo từng tài sản; CI 95% bằng block bootstrap (block 20, 1000 lần, lịch hợp nhất NYSE/CME); Holm qua 4 tài sản.
- Hiệu chỉnh: `quantile_hit_rates`, `coverage_80`, `width_80`, `width_80_pct`, `interval_score_80`, cho cả hai mô hình.
- Xác suất tăng: `brier_skill`.
- Phụ: `mae_ratio_vs_naive`, `sign_accuracy` kèm `up_rate`.
- DM (HAC, HLN) theo chính sách khoảng trống hiện có trong `walk_forward.py`; chính sách mới hoãn sau 22/11 (điểm 21), báo cáo rõ các nhóm DM bị chặn.
- Không dùng MAPE, RMSE hay sai số trên mức giá.

## 4. Báo cáo bổ sung (chỉ báo cáo)

- Theo năm 2020, 2021, …, 2026.
- Hai giai đoạn biến động: 2020-02-15 → 2020-05-31 (COVID, gồm WTI âm) và 2022-02-15 → 2022-04-30 (Nga – Ukraine).
- Độ nhạy CI theo block 10, 20, 40.
- Số ngày gốc hợp lệ theo tài sản × h × mẫu.

## 5. Kết quả dùng để làm gì (chốt trước khi chạy)

- Chỉ dùng cho báo cáo cuối và buổi bảo vệ.
- **Không đổi champion trước 22/11**, kể cả khi S1a có cận dưới CI > 0 ở tài sản nào đó (ADR-0011, họp 30/10 điểm 19). Muốn đổi champion sau đó phải có ADR mới.
- Kết quả xấu cho `baseline-q252` cũng không đổi sản phẩm trước 22/11; ghi trung thực vào báo cáo.
- Không có lần chạy thứ hai, không thêm mô hình hay cấu hình sau khi xem kết quả.

## 6. Chạy một lần

- Code: runner theo mẫu stage val2019 của `run_k4.py` (phần chặn, `started.json`, `verified_result`, SHA-256 từng file), `run_id = test2020` cố định. Code và test merge vào `developer` trước khi chạy; không dùng dữ liệu 2020 → nay khi viết hay test code (test dùng dữ liệu tổng hợp hoặc ≤ 2019).
- Trước khi chạy: commit sạch; `claim.json` (commit, người chạy, thời điểm) ghi lên `s3://cpaws-dev-lake/eval/test2020/claim.json` bằng `--if-none-match "*"`; `pip freeze` vào `env.txt`.
- Chạy xong: tải cả thư mục kèm SHA-256 lên `eval/test2020/`, báo ở PR kế hoạch. Chạy hỏng giữa chừng: không tự chạy lại; cả nhóm quyết và ghi lý do.
- Người chạy: Long, trên một máy và một venv. Khải review kết quả.
- Claude không xem, không tóm tắt kết quả 2020 → nay (quy tắc project).

## 7. Lịch

- Kế hoạch: PR trước 10/11, Long approve.
- Code runner: trước 15/11.
- Chạy: tuần 16–22/11, trước đóng băng.

## 8. Ghi trước khi chạy

- DT của bản clean: …
- SHA-256 bản clean: …
- Commit chạy: …
