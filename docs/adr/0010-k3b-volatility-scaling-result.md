# ADR-0010: Kết quả K3b — co giãn theo biến động không thay mốc 252 phiên; dừng dò mô hình chỉ dùng giá

- Ngày: 2026-10-27
- Trạng thái: Đề xuất
- Người viết: Trịnh Tiến Khải (bản nháp do Claude soạn); người duyệt: Nguyễn Tiến Long

## Bối cảnh

ADR-0009 ghi kết quả âm của K3 (CEEMDAN + DLinear) và chỉ ra giới hạn: đầu ra tuyến tính theo IMF có dấu nên không phản ánh được độ lớn biến động gần đây. K3b kiểm giả thuyết "co giãn độ rộng khoảng theo biến động gần đây cải thiện `pinball_skill`", theo kế hoạch commit và push trước khi chạy (`docs/experiments/k3b-volatility-plan.md`, nhánh `exp/k3b-volatility`, gồm mục sửa ngày 26/10 commit trước khi chạy 2019). Kết quả: `docs/experiments/k3b-volatility-results-2026-10.md`, lần chạy `k3b-val2019`, commit `918ec4f`, `commit_dirty = false`.

Ba ứng viên, đều giữ trung vị bằng mốc 252 phiên:
- **S1a, S1b:** phân vị mốc co giãn quanh trung vị theo k_t = clip(σ_EWMA / σ_252, 0,5, 2,0), λ = 0,94 và 0,97, không train.
- **S2:** mô hình neo chỉ học độ rộng từ 5 đặc trưng (log năng lượng IMF1–3 và residue của `fixed_imf_matrix` window 252, K 3, L 30; log σ_short/σ_long).

## Các phương án

1. **Đưa ứng viên được chọn lên production cho tài sản đạt tiêu chí.** Không áp dụng được: không tài sản nào đạt.
2. **Giữ `baseline-q252`, ghi kết quả âm, dừng dò mô hình chỉ dùng giá** (đúng mục 4 của kế hoạch K3b).
3. **Thử tiếp biến thể giá** (k_t khác nhau theo h, λ khác, kẹp khác). Mỗi biến thể là thêm một lần nhìn vào 2019; kế hoạch K3b đã chốt dừng nếu kết quả âm.

## Quyết định

Chọn **phương án 2**.

1. **Ứng viên được chọn: S1a** (λ = 0,94). Trung bình `pinball_skill` 28 nhóm trên tập chung (vàng 245, bạc 245, Brent 232, WTI 232), đơn vị điểm %:

| | vàng | bạc | Brent | WTI | 28 nhóm |
|---|---|---|---|---|---|
| S1a (chọn) | +0,34 | +0,75 | −1,11 | −1,26 | −0,32 |
| S1b | +0,47 | +0,58 | −1,66 | −1,62 | −0,56 |
| S2 | +0,03 | −1,08 | −1,77 | −1,11 | −0,98 |
| K3 `w252-k3-l30` | −2,94 | −4,16 | −1,73 | −2,35 | −2,79 |

   S1a hơn S1b 0,24 điểm % (trên ngưỡng hòa 0,1). Trên tập K3 (245/245/202/202) thứ tự chọn không đổi; K3 chấm lại trên tập đó ra −2,53, khớp ADR-0009.
2. **Không tài sản nào đạt tiêu chí ADR-0009 mục 4.** CI 95% của `pinball_skill` trung bình 7 h ở S1a đều chứa 0: vàng [−1,33; +2,29], bạc [−2,85; +3,93], Brent [−3,72; +2,30], WTI [−3,42; +1,41]; dầu ở mẫu `excl_roll` cùng kết luận. 0/42 nhóm tài sản × h có cận dưới CI > 0. DM sau Holm: không nhóm nào có ý nghĩa. DM ở đây dùng chính sách khoảng trống phiên cũ (`DM_GAP_POLICY` chặn nhóm có khoảng trống, h > 1), nên là kết quả lịch sử; chính sách HAC amplitude-modulated chốt ở PR #40 sẽ được triển khai và đánh giá riêng, không chạy lại K3b.
3. **Production giữ `MODEL_VERSION=baseline-q252`** cho cả 4 tài sản. **Challenger đổi sang S1a**, thay CEEMDAN-DLinear `w252-k3-l30` (ADR-0009): S1a gần mốc hơn nhiều (−0,32 so với −2,79 điểm %), cao hơn K3 ở 34/42 nhóm, không cần train, và chỉ cần NumPy (không cần PyEMD hay cache CEEMDAN), nên chấm song song với mốc trong luồng hằng ngày dễ nhất. K3 giữ trong repo để tái lập và cho buổi bảo vệ.
4. **Dừng dò mô hình chỉ dùng giá trên validation 2019.** Riêng K3 và K3b đã nhìn vào 2019 hai lần với 11 cấu hình. Trước đó validation 2019 đã được dùng để đánh giá DLinear MVP (PR #26), nên tính trên toàn dự án đây là lần dùng lại thứ 2 và thứ 3. Thí nghiệm mô hình tiếp theo (nếu có) chỉ là tín hiệu ngoài giá (K4: OVX/GVZ, GPR, lịch sự kiện, chỉ số tin), với kế hoạch riêng commit trước khi chạy, và phải ghi đây là lần dùng validation 2019 thứ 4 của dự án (sau DLinear MVP, K3, K3b).

## Hệ quả

- Sản phẩm không đổi; web và chatbot tiếp tục ghi "Mốc thống kê 252 phiên". Không cần sửa `predict.py`.
- Code K3b (`src/forecast/vol_scaled.py`, `src/features/imf_energy.py`, `src/forecast/energy_width*.py`, `src/forecast/run_k3b.py`) giữ trong repo để tái lập, không dùng trong luồng hằng ngày.
- **Quan sát để báo cáo (không hành động):**
  - Trung vị S1a trùng mốc từng bit, nên `mae_ratio_vs_naive` và `sign_accuracy` giống hệt mốc; mọi khác biệt đến từ độ rộng khoảng.
  - Kim loại: S1a nới khoảng 80% khoảng 10% so với mốc; `coverage_80` vàng tăng từ 0,750 lên 0,778 (mốc thiếu độ phủ ở 2019). Điểm ước lượng dương nhưng CI chứa 0.
  - Dầu: S1a thu hẹp khoảng và kém mốc từ h2 trở đi. Một k_t chung cho mọi h giả định biến động gần đây kéo dài nguyên vẹn tới h = 7, có thể không đúng với dầu. Không kiểm thêm vì phương án 3 bị loại.
  - S2 kém mốc ở bạc với CI trung bình 7 h [−2,24; −0,01]. CI bootstrap này chưa hiệu chỉnh cho việc thử nhiều ứng viên, nên chỉ coi là dấu hiệu, không phải kết luận có ý nghĩa thống kê.
  - k_t: ngưỡng kẹp gần như không tác động (≤ 2,1% train, ≤ 0,4% 2019); trung vị k_t 0,88–0,94 trên train và 0,96–1,04 trên 2019.
- **Hạn chế thống kê:** S1a được chọn trong 3 ứng viên, sau 8 cấu hình K3 và sau DLinear MVP, trên cùng 2019, nên kết quả lạc quan; vì kết luận là âm nên không đổi quyết định. Tập test 2020 → nay vẫn chưa chạy.
- **Nội dung cho buổi bảo vệ:** hai thí nghiệm có kế hoạch chốt trước, mốc so sánh mạnh, kết quả âm có giải thích; mốc 252 phiên khó vượt với dữ liệu chỉ có giá ở kỳ hạn 1–7 phiên.