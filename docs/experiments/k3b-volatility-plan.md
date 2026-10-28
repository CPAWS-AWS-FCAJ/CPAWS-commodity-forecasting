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

## 6. Sửa đổi và làm rõ trước khi chạy (26/10/2026)

Ghi khi viết code, **trước khi có bất kỳ kết quả 2019 nào của K3b**. Không đổi ứng viên, λ, ngưỡng
kẹp hay siêu tham số.

1. **Sửa lỗi đếm cột S2 (Khải xác nhận).** Mục 3 ghi "6 cột", nhưng công thức cho 5:
   `fixed_imf_matrix` với K = 3 có 4 cột (IMF1–3 + residue), nên có 4 cột log năng lượng, cộng
   log(σ_short,t / σ_long,t) với λ = 0,94. S2 dùng **5 cột** theo đúng công thức; "6 cột" là viết
   nhầm.
2. **Tập chung để chọn và xét tiêu chí (Khải xác nhận).** "Tập chung" ở mục 4 là giao các ngày gốc
   hợp lệ của 3 ứng viên trên từng tài sản. Dự kiến bằng tập quy tắc A của S2 (window 252, L 30):
   vàng 245, bạc 245, Brent 232, WTI 232. Tập này rộng hơn tập K3 (Brent, WTI 202), vì tập K3 là
   giao 8 cấu hình, có cả cấu hình L = 60. Mọi chỉ số và CI cũng được báo cáo trên tập K3 (vàng 245,
   bạc 245, Brent 202, WTI 202) để so với ADR-0009. Nếu kết luận trên hai tập khác nhau thì ghi rõ.
   Code dừng nếu giao 3 ứng viên khác tập quy tắc A của S2, hoặc không chứa trọn tập K3.
3. **Chi tiết hiện thực mà kế hoạch chưa nói rõ** (chốt ở đây trước khi chạy):
   - Return ngày r_s đánh chỉ số tại phiên kết thúc s. r_s = NaN khi s hoặc phiên liền trước theo
     lịch không có giá hợp lệ (thiếu, bị loại, ≤ 0).
   - σ_long,t: độ lệch chuẩn mẫu (ddof = 1) của các r_s hợp lệ trong 252 phiên lịch gần nhất ≤ t.
     Cần ít nhất 200 return hợp lệ (cùng `MIN_OBS` của mốc 252 phiên), nếu không thì NaN và ngày gốc
     đó không hợp lệ.
   - σ_short: σ² bắt đầu tại phiên có return hợp lệ thứ 252 của chuỗi giá đã đọc (clean từ 2012),
     bằng phương sai mẫu (ddof = 1) của 252 return hợp lệ đầu tiên; đệ quy từ phiên sau đó. Trước
     phiên này σ_short là NaN.
   - S2 dùng tỷ số **chưa kẹp** σ_short/σ_long trong cột log; k_t (đã kẹp) chỉ dùng cho S1.
   - S2: Δg = W·x + b với W cỡ 42 × 5 (7 h × 6 khoảng cách), b cỡ 42, khởi tạo 0. Δm cố định bằng 0.
     Dùng cùng hàm neo của K3 (`anchor_quantiles`). Chuẩn hóa từng cột bằng `ColumnScaler`, fit chỉ
     trên mảng train. Weight decay là tham số `weight_decay` của `torch.optim.Adam`, như K3.
   - Mẫu S2 là quy tắc A (window 252, K 3, L 30) cộng thêm điều kiện tỷ số σ hợp lệ. Số mẫu phải bằng
     số mẫu K3 của `w252-k3-l30` (train/val: vàng 1251/245, bạc 1251/245, Brent 1110/232,
     WTI 1172/232), nếu khác thì dừng.
   - CI của `pinball_skill` trung bình 7 h: với mỗi lần lấy mẫu của kế hoạch bootstrap chung
     (`walk_forward.shared_bootstrap_plan`), tính `pinball_skill` từng h trên các ngày được rút rồi
     lấy trung bình 7 h. Giá trị điểm là trung bình 7 giá trị `pinball_skill` từng h.
   - Mốc so sánh K3 `w252-k3-l30` lấy từ lần chạy có provenance sạch `k3-val2019-clean` (commit
     `cc5dac3`), chỉ đọc, chấm lại bằng cùng hàm đánh giá.
   - Tài sản "đạt" xét trên mẫu `all` (mẫu mà sản phẩm dự báo). Với dầu, CI trung bình 7 h trên
     `excl_roll` được báo cáo cạnh đó; nếu hai mẫu cho kết luận khác nhau thì ghi rõ trong báo cáo.
