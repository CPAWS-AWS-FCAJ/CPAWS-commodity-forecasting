# K3b: kế hoạch thí nghiệm co giãn theo biến động (chốt trước khi chạy)

- Ngày: 26/10/2026
- Người viết: Khải (bản nháp do Claude soạn)
- Trạng thái: **Chốt trước khi chạy.** Commit và push file này TRƯỚC khi có bất kỳ kết quả 2019 nào
  của K3b. Không sửa ứng viên, tham số hay quy tắc chọn sau khi thấy kết quả; thay đổi (nếu có) ghi
  thành mục mới có ngày, kèm lý do, và báo cáo cả kết quả trước lẫn sau.
- Căn cứ: ADR-0008, ADR-0009 (K3 âm; giới hạn: đầu ra tuyến tính theo IMF có dấu nên không phản ánh
  được độ lớn biến động gần đây), `docs/experiments/k3-ceemdan-plan.md`.

## 0. Số lần nhìn vào validation 2019

K3 là lần 1 (8 cấu hình). **K3b là lần 2, 3 ứng viên.** Tổng cộng 11 cấu hình đã xem trên 2019;
báo cáo phải ghi con số này. Tập test 2020 → nay vẫn không chạy.

## 1. Giả thuyết

Return ngày gần như không dự báo được về hướng, nhưng độ lớn biến động có tính cụm. Mốc 252 phiên
dùng phân phối vô điều kiện của 252 phiên, nên khoảng dự báo quá rộng lúc thị trường yên và quá
hẹp lúc biến động. Co giãn khoảng theo biến động gần đây có thể cải thiện `pinball_skill`, chủ yếu
qua `width_80` và `interval_score_80`, trong khi trung vị giữ như mốc.

## 2. Dữ liệu và mẫu

- Như K3: train ngày gốc 2014–2018 có mọi ngày đích ≤ 2018-12-31; validation ngày gốc 2019; không
  đọc dữ liệu sau 2019-12-31. Cùng bản clean (`configs/k3_grid.CLEAN_DT`).
- Return ngày r_s = ln(P_s / P_{s−1}) chỉ tính cho cặp phiên liền kề theo lịch của tài sản; cặp vắt
  qua phiên thiếu thì bỏ (không nối hai phiên cách xa). Mọi thống kê tại t chỉ dùng r_s với s ≤ t.
- So mọi ứng viên trên **tập ngày gốc chung** của từng tài sản, và trên chính tập chung của K3
  (vàng 245, bạc 245, Brent 202, WTI 202) để so được với ADR-0009. Ứng viên S2 dùng quy tắc A với
  window 252, L 30 như cấu hình K3 đã chọn.

## 3. Ứng viên (3, chốt)

Ký hiệu: Q_τ,h = phân vị baseline-q252 tại t; m_h = Q_0.5,h.

**S1a, S1b — mốc 252 phiên co giãn theo biến động (không train):**
- σ_long,t = độ lệch chuẩn của các r_s hợp lệ trong 252 phiên gần nhất ≤ t.
- σ_short,t = EWMA: σ²_t = λ·σ²_{t−1} + (1 − λ)·r_t², khởi tạo bằng phương sai của 252 return hợp lệ
  đầu tiên của chuỗi; cặp phiên không hợp lệ thì giữ nguyên σ²_{t−1}.
- k_t = clip(σ_short,t / σ_long,t, 0,5, 2,0), dùng chung cho mọi h.
- Phân vị: q_τ,h = m_h + k_t · (Q_τ,h − m_h). Trung vị không đổi; thứ tự phân vị giữ nguyên vì k_t > 0.
- **S1a: λ = 0,94. S1b: λ = 0,97.** Không có tham số nào fit trên dữ liệu.

**S2 — mô hình neo, chỉ học độ rộng từ năng lượng IMF (train):**
- Đặc trưng (6 cột): log của năng lượng từng cột `fixed_imf_matrix` (window 252, K 3, L 30) sau
  khi chia cho P_t, năng lượng = trung bình bình phương trên L điểm (cột residue dùng
  `residue/P_t − 1`); cộng log(σ_short,t / σ_long,t) với λ = 0,94. Chuẩn hóa từng cột, fit trên train.
- Đầu ra: Δm = 0 (trung vị = m_h); khoảng cách giữa hai phân vị liền kề = khoảng cách baseline ×
  exp(Δg), Δg = W·x + b, W và b khởi tạo 0 (lúc khởi tạo trùng baseline-q252).
- Pinball loss trung bình 7 h × 7 τ; Adam, lr 1e-3, weight decay 1e-4, batch 64, 20 epoch cố định,
  float64; 3 seed (7, 8, 9) lấy trung bình phân vị rồi `normalize_quantiles()` đúng một lần.

## 4. Quy tắc chọn và tiêu chí (chốt)

- Chọn **một ứng viên chung** có trung bình `pinball_skill` cao nhất trên 28 nhóm (`all`, tập chung).
  Hòa (chênh < 0,1 điểm %): ưu tiên S1a, rồi S1b, rồi S2 (đơn giản hơn trước).
- **Tiêu chí lên production (ADR-0009 mục 4):** tài sản đạt khi cận dưới CI 95% của `pinball_skill`
  **trung bình 7 h** > 0, CI block bootstrap (block 20, 1000 lần, lịch hợp nhất NYSE/CME) áp chung
  cho 7 h; báo cáo kèm từng h, cả `all` và `excl_roll` cho dầu.
- Nếu ứng viên được chọn đạt ở ít nhất một tài sản: viết ADR-0010 chốt ứng viên và tham số, rồi mới
  bàn việc đưa vào predict và chạy tập test một lần. Nếu không: ghi kết quả âm vào ADR-0010, giữ
  `baseline-q252`, dừng dò mô hình chỉ dùng giá.

## 5. Báo cáo

- Cả 3 ứng viên: mọi chỉ số ADR-0008 §5 theo tài sản × h, so với baseline-q252 và CEEMDAN-DLinear
  `w252-k3-l30`; trung bình 7 h kèm CI theo mục 4.
- Phân bố k_t trên train và 2019 (min, trung vị, max, tỷ lệ bị kẹp ở 0,5 hoặc 2,0).
- Ghi rõ: lần nhìn thứ 2 vào 2019, tổng 11 cấu hình.
