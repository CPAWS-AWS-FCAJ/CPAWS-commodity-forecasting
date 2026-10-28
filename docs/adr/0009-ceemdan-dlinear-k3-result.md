# ADR-0009: Kết quả K3 — CEEMDAN + DLinear không thay mốc 252 phiên

- Ngày: 2026-10-26
- Trạng thái: Đề xuất
- Người viết: Trịnh Tiến Khải (bản nháp do Claude soạn); người duyệt: Nguyễn Tiến Long

## Bối cảnh

ADR-0007 mục 6 để lại ba tham số chọn ở K3 trên validation 2019: độ dài cửa sổ CEEMDAN, cách ghép IMF (K) và `seq_len`. Sản phẩm đang dùng `baseline-q252` vì DLinear MVP thua mốc này ở 28/28 nhóm (ADR-0008, tiêu chí lên production: cận dưới CI 95% của `pinball_skill` > 0).

K3 chạy theo kế hoạch commit trước khi train (`docs/experiments/k3-ceemdan-plan.md`, nhánh `exp/k3-ceemdan-probe`, commit `59384e4`), trên probe `docs/experiments/k3-ceemdan-probe-2026-10-26.md`. Kết quả đầy đủ: `docs/experiments/k3-ceemdan-results-2026-10.md`.

- Mô hình: DLinear chia sẻ trọng số giữa các cột IMF (chia cho P_t, residue thành `residue/P_t − 1`, scaler theo cột fit trên train), một bias 49 chung, đầu ra neo vào mốc 252 phiên (trung vị = q50 baseline + Δm; khoảng cách phân vị = khoảng cách baseline × exp(Δg); Δm, Δg khởi tạo 0), float64, 3 seed lấy trung bình.
- Lưới 8 cấu hình: window {252, 504} × K {3, 4 | 4, 5} × L {30, 60}; chọn một cấu hình chung theo trung bình `pinball_skill` 28 nhóm trên tập ngày gốc chung (vàng 245, bạc 245, Brent 202, WTI 202).

## Các phương án

1. **Đưa CEEMDAN-DLinear lên production cho tài sản nào đạt tiêu chí.** Không áp dụng được: không tài sản nào đạt.
2. **Giữ `baseline-q252`, CEEMDAN-DLinear làm challenger thay DLinear MVP.** Không tốn thêm hạ tầng; giữ đường để so ở retrain hằng tuần.
3. **Tiếp tục dò kiến trúc chỉ dùng giá** (LSTM, nhánh cao/thấp tần, lưới lớn hơn) trên 2019. Tốn thời gian; mỗi lần nhìn thêm vào 2019 làm kết quả lạc quan hơn; mục 4 dưới đây cho thấy giới hạn nằm ở loại đặc trưng chứ không ở kiến trúc.

## Quyết định

Chọn **phương án 2**.

1. **Cấu hình được chọn:** window 252, K = 3, L = 30 (`w252-k3-l30`), trung bình `pinball_skill` −2,53 điểm %; cấu hình kế tiếp `w252-k4-l30` −3,07. Cả 8 cấu hình đều âm.
2. **Không tài sản nào đạt tiêu chí:** cận dưới CI 95% ≤ 0 ở 42/42 nhóm (28 `all`, 14 dầu `excl_roll`). `mae_ratio_vs_naive` > 1 và `brier_skill` < 0 ở cả 28 nhóm `all`. Chỉ 5/28 nhóm có skill dương (Brent h1–h4, WTI h3, tối đa +1,2 điểm %, CI đều chứa 0). DM: không nhóm nào có ý nghĩa sau Holm (12 nhóm dầu `excl_roll` h > 1 bị chặn theo `DM_GAP_POLICY`).
3. **Production giữ `MODEL_VERSION=baseline-q252`** cho cả 4 tài sản. CEEMDAN-DLinear `w252-k3-l30` thay DLinear MVP làm challenger (tốt hơn MVP ở 41/42 nhóm), `integration_eligible = false`.
4. **Chốt cho các lần đánh giá sau (bổ sung kế hoạch K3 mục 5, chốt trước khi có thí nghiệm mới):** một tài sản đạt tiêu chí khi cận dưới CI 95% của `pinball_skill` **trung bình 7 h** > 0, CI tính bằng cùng kế hoạch block bootstrap (block 20, 1000 lần, lịch hợp nhất NYSE/CME) áp chung cho cả 7 h; báo cáo kèm từng h.
5. **Chi tiết hiện thực đã dùng** (kế hoạch chưa ghi rõ): một bias 49 chung sau khi cộng các cột; float64 để đầu ra lúc khởi tạo trùng baseline với sai số ≤ 1e-9.

## Hệ quả

- Sản phẩm không đổi; web và chatbot tiếp tục ghi "Mốc thống kê 252 phiên".
- Không cần đưa PyEMD hay cache CEEMDAN vào luồng predict lúc này. Khi nào một mô hình CEEMDAN đạt tiêu chí mới cần ADR về cách predict lấy IMF (đọc cache trên S3 hay thêm PyEMD vào image).
- **Giới hạn đã thấy:** đầu ra là hàm tuyến tính của IMF có dấu, nên Δg (độ rộng khoảng) không thể phản ánh độ lớn biến động gần đây — thứ duy nhất được biết là dự báo được trong return ngày (volatility clustering). Huấn luyện chỉ giảm nhẹ loss trong mẫu (vàng 0,003562 so với mốc 0,003595) và không giữ được sang 2019. Hướng tiếp theo, nếu làm, là thí nghiệm mới có kế hoạch riêng với đặc trưng độ lớn (năng lượng từng IMF, biến động thực hiện, OVX/GVZ ở K4), không phải dò thêm kiến trúc trên cùng đặc trưng.
- **Hạn chế thống kê:** cấu hình được chọn là 1 trong 8 trên chính 2019, nên kết quả của nó lạc quan; vì kết luận là âm nên hạn chế này không đổi quyết định. Mỗi thí nghiệm mới trên 2019 phải ghi số lần đã nhìn vào validation. Tập test 2020 → nay vẫn chưa chạy.
- Provenance: lần chạy đầu ghi `commit_dirty = true`; chạy lại sau khi commit để có provenance sạch (kết quả tất định theo seed).
