# K3: kế hoạch thí nghiệm CEEMDAN + DLinear (chốt trước khi chạy)

- Ngày: 26/10/2026
- Người viết: Khải (bản nháp do Claude soạn)
- Trạng thái: **Chốt trước khi train.** File này được commit TRƯỚC khi có bất kỳ kết quả validation
  nào; không sửa lưới, quy tắc chọn hay tiêu chí sau khi đã thấy kết quả 2019. Thay đổi (nếu có)
  ghi thành mục mới có ngày, kèm lý do, và báo cáo cả kết quả trước lẫn sau thay đổi.
- Căn cứ: ADR-0001, ADR-0007, ADR-0008; probe 26/10 (`docs/experiments/k3-ceemdan-probe-2026-10-26.md`).

## 1. Dữ liệu và mẫu

- Train: ngày gốc 2014–2018 có mọi ngày đích ≤ 2018-12-31. Validation: ngày gốc 2019.
  **Không đọc dữ liệu sau 2019-12-31.**
- Cache CEEMDAN ADR-0007, `cfg_hash` 4c3229533ae3 (trials 100, epsilon 0,005, seed 42, `keep_last` 128).
- **Quy tắc A (ngày gốc hợp lệ):** có cửa sổ CEEMDAN; `make_windows(seq_len)` hợp lệ (đoạn `seq_len`
  đưa vào mô hình không có phiên thiếu); target hợp lệ cả 7 h; baseline-q252 hợp lệ; điều kiện thời
  điểm công bố như `dlinear_data`. Phần cũ hơn của cửa sổ decompose được phép có phiên thiếu (dầu:
  5/12/2018, 10/10/2016, 11/11/2016; Brent 2012–2013), ghi số phiên thiếu thành cột chẩn đoán.
- So sánh mọi cấu hình trên **tập ngày gốc chung** của từng tài sản (giao của 8 cấu hình), để khác
  biệt không đến từ tập mẫu.

## 2. Đặc trưng

- `fixed_imf_matrix(windows, max_imf=K, seq_len=L)` → `(n, L, K+1)`.
- Chuẩn hóa: chia mọi cột cho P_t (giá cuối cửa sổ, đã biết tại t); cột residue đổi thành
  `residue/P_t − 1`. Sau đó chuẩn hóa từng cột (mean/std), **fit chỉ trên train**.
- Cùng một hàm cho train, validation và (sau này) predict.

## 3. Mô hình

- Mỗi tài sản một mô hình (như DLinear MVP).
- **DLinear-CEEMDAN, tuyến tính, chia sẻ trọng số giữa các cột:** mỗi cột qua cùng một ánh xạ tuyến
  tính L → 49, nhân hệ số học được riêng của cột, rồi cộng lại.
- **Đầu ra neo vào mốc 252 phiên:** trung vị = q50 của baseline + Δm; mỗi khoảng cách giữa hai phân
  vị liền kề = khoảng cách tương ứng của baseline × exp(Δg). Δm, Δg là đầu ra của mô hình, khởi tạo
  bằng 0. Như vậy phân vị luôn tăng dần, và lúc khởi tạo mô hình trùng mốc 252 phiên (baseline tính
  từ return đã hoàn tất trước t, không rò rỉ).
- Loss pinball trung bình 7 h × 7 τ. Adam, lr 1e-3, weight decay 1e-4, batch 64, **20 epoch cố định**
  (không early stopping theo 2019).
- 3 seed (7, 8, 9); trung bình phân vị của 3 seed rồi gọi `normalize_quantiles()` đúng một lần.

## 4. Lưới (8 cấu hình, chốt)

| window | K | L |
|---|---|---|
| 252 | 3, 4 | 30, 60 |
| 504 | 4, 5 | 30, 60 |

Không thử thêm kiến trúc (LSTM, nhánh cao/thấp tần) trong K3; nếu cần thì là thí nghiệm mới, kế hoạch mới.

## 5. Quy tắc chọn (chốt)

- **Một cấu hình chung cho cả 4 tài sản:** cấu hình có trung bình `pinball_skill` cao nhất trên
  28 nhóm (4 tài sản × 7 h, `sample=all`), tính trên tập ngày gốc chung.
- Hòa (chênh < 0,1 điểm %): chọn cấu hình nhỏ hơn theo thứ tự window 252 trước 504, L 30 trước 60,
  K nhỏ trước K lớn.
- **Tiêu chí lên production không đổi (ADR-0008):** chỉ thay `baseline-q252` cho tài sản nào có cận
  dưới CI 95% của `pinball_skill` > 0 ở cấu hình đã chọn. Vì đã chọn 1 trong 8 cấu hình trên chính
  2019, kết quả này lạc quan; báo cáo kèm cả 8 cấu hình và nói rõ hạn chế.
- CI: block bootstrap như `walk_forward.py` (block 20, 1000 lần lấy mẫu, lịch hợp nhất NYSE/CME).

## 6. Báo cáo

- Cấu hình được chọn: mọi chỉ số ADR-0008 §5 theo tài sản × h, so với baseline-q252, naive và
  DLinear MVP (`dlinear-41e13dc5de3d`), trên cả `all` và `excl_roll` cho dầu.
- Cả 8 cấu hình: trung bình `pinball_skill` theo tài sản.
- DM test theo `DM_GAP_POLICY` hiện hành của `walk_forward.py` (nhóm bị chặn thì ghi bị chặn).
- Kết quả xong thì viết ADR-0009 (window, K, L, kiến trúc), không sửa ADR-0007.
