# ADR-0012: Kết quả K4 — FHS + GJR-GARCH không thay mốc 252 phiên; kết thúc dò mô hình chỉ dùng giá

- Ngày: 2026-10-30
- Trạng thái: Đề xuất
- Người viết: Trịnh Tiến Khải (bản nháp do Claude soạn); người duyệt: Nguyễn Tiến Long

## Bối cảnh

ADR-0010 chốt dừng dò mô hình chỉ dùng giá sau K3b. K4 mở lại có chủ đích như một ngoại lệ nghiên cứu có giới hạn (`docs/experiments/k4-plan.md` mục 0 và mục 8, 29/10 tối): giả thuyết mới là biến động có điều kiện, phản ứng bất đối xứng và đuôi lấy từ phần dư, chưa thử ở K3/K3b. Ứng viên được chọn bằng kiểm định chéo 2016–2018, nên validation 2019 chỉ còn vai trò xác nhận. Kế hoạch đã chốt từ trước: không đạt mục 5 thì dừng dò mô hình chỉ dùng giá đến hết dự án, không có ngoại lệ thứ hai.

Thứ tự quyết định, tất cả đã ghi trong kế hoạch trước khi chạy 2019:

1. Kiểm định chéo chọn `fhs-gjr-t` thay vì `combo-eq3` theo mục 4.
2. Chẩn đoán cho thấy phần dư z dùng để bootstrap chưa trừ trung bình, nên FHS bị trôi âm.
3. Sửa đổi hậu nghiệm (mục 8, 29/10) đổi ứng viên 2019 thành `fhs-gjr-t-dm`: bootstrap từ z − mean(z), giữ nguyên các tham số khác. Quy tắc chốt trước khi xem số: trung bình `pinball_skill` 28 nhóm của bản dm trên kiểm định chéo phải > 0 thì mới chạy 2019.
4. Kiểm định chéo `fhs-gjr-t-dm` (`k4-cv-dm-clean3`) cho +2,57 điểm %, nên được chạy 2019 một lần.

Mô hình `fhs-gjr-t-dm`:

- Mô hình biến động là GJR-GARCH(1,1), nhiễu Student-t, fit bằng `arch` 8.0.0 offline trên 1000 return hợp lệ gần nhất, refit đầu mỗi tháng.
- FHS mô phỏng 5000 đường × 7 bước bằng NumPy, bootstrap phần dư chuẩn hóa đã trừ trung bình.

**Hai lần chạy val2019, ghi đầy đủ:**

- **Lần 1:** commit `666e6b4`.
  - Dừng trong `build_val` ở lần refit tháng 2019-01 của bạc, theo điều kiện dừng "lần refit đầu lỗi" (mục 8). Lúc đó vàng đã dựng xong dự báo, còn `evaluate_set` chưa chạy.
  - Không có file kết quả nào ngoài `started.json`; không chỉ số 2019 nào được tính hay xem.
  - Nguyên nhân: fit hội tụ nhưng ra γ = −α. `arch` coi ràng buộc α + γ ≥ 0 là thỏa trong sai số làm tròn, còn `GjrParams` kiểm ràng buộc này không có dung sai.
- **Sửa (commit `6654d20`):** các ràng buộc không âm nhận với dung sai `NONNEG_TOL = 1e-9`.
  - Chạy lại kiểm định chéo: `k4-cv-clean3`, `k4-cv-dm-clean3`. Mọi file chấm điểm trùng SHA-256 với bộ trước, Long đã đối chiếu 16/16 file.
  - Cơ chế lần 2 ghi ở mục 8 (30/10 chiều, PR #64): claim riêng `eval/k4/k4-val2019-attempt2/claim.json`, giữ nguyên dấu vết lần 1 trên S3.
- **Lần 2:** commit `6654d20`, chạy xong (128 giây).
  - Chỉ sửa lỗi dung sai: cùng ứng viên, tiêu chí, tập ngày gốc, mốc cắt và seed.
  - Vẫn tính là lần nhìn thứ 4 vào 2019 ở cấp dự án, vì lần 1 chưa có chỉ số.
  - Tổng số cấu hình đã xem trên 2019: 13 (DLinear MVP 1, K3 8, K3b 3, K4 1).

**Kết quả:** `s3://cpaws-dev-lake/eval/k4/k4-val2019-attempt2/` gồm `summary.md`, `summary.json`, các file parquet, `env.txt` (`pip freeze` của venv) và `k4-val2019-attempt2.sha256`.

## Các phương án

1. **Đưa `fhs-gjr-t-dm` lên làm challenger hoặc champion cho tài sản đạt.** Không áp dụng được: không tài sản nào đạt.
2. **Giữ `baseline-q252`, ghi kết quả âm, S1a vẫn là challenger, dừng dò mô hình chỉ dùng giá đến hết dự án.** Đúng mục 5 của kế hoạch K4.
3. **Thử tiếp biến thể** (cửa sổ khác, EGARCH, kết hợp với FHS-dm, chọn theo từng tài sản). Bị loại:
   - mỗi biến thể là thêm một lần nhìn vào 2019;
   - kế hoạch đã chốt không có ngoại lệ thứ hai;
   - mục 8 (30/10) chốt không có lần chạy thứ ba.
4. **Đổi challenger từ S1a sang `fhs-gjr-t-dm`** vì điểm ước lượng 2019 cao hơn (+1,25 so với −0,16 điểm %). Bị loại:
   - đây là quyết định hậu nghiệm dựa trên số 2019, trái mục 5 ("S1a vẫn là challenger");
   - CI của cả hai đều chứa 0;
   - S1a đã chạy song song trong luồng hằng ngày (PR #53), còn FHS cần thêm artifact tham số và phần dư, refit hằng tháng, chưa có bản production.

## Quyết định

Chọn **phương án 2**.

1. **Không tài sản nào đạt tiêu chí mục 5** (cận dưới CI 95% của `pinball_skill` trung bình 7 h > 0; block bootstrap, block 20, 1000 lần). Dầu quyết định theo sample `all`.

   Bảng dưới tính trên tập chung K3 (vàng 245, bạc 245, Brent 202, WTI 202), đơn vị điểm %:

| | vàng | bạc | Brent | WTI | 28 nhóm |
|---|---|---|---|---|---|
| `fhs-gjr-t-dm` | +2,06 | +1,95 | −0,13 | +1,13 | +1,25 |
| CI 95% | [−0,28; +4,55] | [−2,01; +4,94] | [−2,42; +2,76] | [−1,61; +4,31] | [−0,67; +3,40] |
| Đạt | không | không | không | không | |
| S1a (tham chiếu) | +0,34 | +0,75 | −0,79 | −0,94 | −0,16 |

   Dầu ở mẫu `excl_roll` (chỉ báo cáo) cũng không đạt: Brent +0,45 [−2,45; +3,42], WTI +0,47 [−1,81; +3,10].

2. **Báo cáo bổ sung không đổi kết luận:**
   - **Holm qua 4 tài sản** (một phía, ngưỡng 0,025): p_holm là vàng 0,208, bạc 0,471, Brent 0,540, WTI 0,471. Không tài sản nào qua.
   - **Độ nhạy theo block length 10/20/40:** không block nào cho cận dưới CI > 0. Vàng ở block 40 có cận dưới −0,19 và p một phía 0,038. Đây chỉ là độ nhạy; tiêu chí đã chốt block 20.
   - **Theo từng h:** 2/42 nhóm tài sản × h × sample có cận dưới CI > 0, là vàng h1 [+0,74; +4,32] và vàng h2 [+0,59; +4,89]. Kết quả này chưa hiệu chỉnh cho kiểm định nhiều lần. DM vàng h1 có p = 0,006, sau hiệu chỉnh Holm còn 0,176.
   - **Thu hẹp so với kiểm định chéo:** trung bình 28 nhóm giảm từ +2,57 (cv-dm 2016–2018) xuống +1,25 (2019).
   - **Độ bền mô phỏng:** đổi seed hai lần cho trung bình 28 nhóm là +1,18 và +1,18; chạy 10000 đường cho +1,19. Kết quả không phụ thuộc nhiễu mô phỏng.
3. **Production giữ `MODEL_VERSION=baseline-q252`** cho cả 4 tài sản. **S1a vẫn là challenger** (chạy song song theo PR #53), không đổi.
4. **Kết thúc dò mô hình chỉ dùng giá đến hết dự án.**
   - Đây là lần thứ ba (K3, K3b, K4) một họ mô hình chỉ dùng giá không vượt mốc phân vị 252 phiên trên 1–7 phiên.
   - Không có thí nghiệm mô hình nào khác trước khi đóng băng tính năng 22/11.
   - Nếu sau này có thí nghiệm dùng tín hiệu ngoài giá, thí nghiệm đó cần kế hoạch riêng, commit trước khi chạy, và phải ghi là lần dùng validation 2019 thứ 5.

## Hệ quả

- **Sản phẩm không đổi.** Web và chatbot vẫn ghi "Mốc thống kê 252 phiên"; `predict.py` không cần sửa.
- **Code K4 giữ trong repo để tái lập**, không dùng trong luồng hằng ngày. Gồm `configs/k4.py`, `src/forecast/fhs_fit.py`, `src/forecast/fhs_numpy.py`, `src/forecast/run_k4.py`.
- **Quan sát để báo cáo (không hành động):**
  - **Hiệu chỉnh khoảng 80%:** FHS gần 0,80 hơn mốc ở kim loại. `coverage_80` của vàng là 0,79–0,82 so với mốc 0,73–0,77; của bạc là 0,79–0,81 so với 0,74–0,78. Cái giá là khoảng rộng hơn khoảng 10–25%.
  - **Interval score:** `interval_score_80` của FHS thấp hơn mốc ở 25/28 nhóm. Ba nhóm còn lại là Brent h5–h7; ở đó FHS phủ quá mức (0,87–0,89).
  - **Pinball:** điểm ước lượng dương ở kim loại đến chủ yếu từ độ rộng khoảng, giống S1a ở ADR-0010, nhưng không đủ để CI loại 0.
  - **Hướng giá:** FHS không cải thiện xác suất tăng. Ở vàng 2019 (`up_rate` 0,54–0,60):
    - tỷ lệ return thực dưới q50 chỉ 0,38–0,47, tức trung vị FHS thấp hơn thực tế;
    - `sign_accuracy` là 0,42–0,52, thấp hơn `up_rate`;
    - `brier_skill` dao động quanh 0 (−0,015 đến +0,003).
  - **Độc lập của các lần vượt khoảng (Christoffersen 1998):** ở h = 1, p > 0,1 cho cả 4 tài sản. Ở h > 1, return chồng nhau nên các lần vượt phụ thuộc sẵn; mốc và S1a cũng vậy.
  - **DM ở mẫu `excl_roll`:** với h ≥ 2, kết quả là `undefined` do khoảng trống quanh ngày roll; chỉ báo cáo.
  - **Thời gian:** một lần dự báo FHS NumPy cho 4 tài sản mất 22 ms. Chi phí Lambda không phải lý do loại mô hình.
- **Fit FHS trên 2019:**
  - Vàng, Brent, WTI fit ok 12/12 tháng.
  - Bạc có 9 tháng ok và 3 tháng `fit_error` (2019-03, 2019-04, 2019-08). 2019-03 và 2019-04 dùng tham số 2019-02, 2019-08 dùng tham số 2019-07, tối đa 2 tháng liên tiếp, đúng quy tắc mục 3.
  - Nguyên nhân 3 tháng lỗi: `arch` hội tụ bình thường (`convergence_flag = 0`), nhưng `GjrParams` từ chối với lỗi "non-positive variance", tức có ràng buộc không âm bị vi phạm quá dung sai 1e-9. Tham số bị từ chối không được ghi log. Nhiều khả năng là α + γ âm nhỏ, vì các tháng liền kề đều ở biên α + γ. Không chẩn đoán thêm: muốn biết phải fit lại trên cửa sổ có return 2019, và dù thế nào kết luận cũng không đổi.
  - 8/9 lần fit ok của bạc có α + γ ở biên 0, tức cú sốc âm gần như không làm tăng phương sai. Tính cả 3 tháng dùng lại, chỉ các ngày gốc tháng 2019-06 dùng tham số không ở biên. `pinball_skill` trung bình 7 h: ở biên +1,84 điểm % (225 ngày gốc ở h7), còn lại +3,66 (20 ngày gốc). Nhóm "còn lại" quá nhỏ để so sánh.
  - Không lần fit nào trên 2019 nằm ở biên persistence.
  - Mọi ngày gốc của tập chung đều có dự báo FHS hợp lệ (0 `no_model`, 0 `invalid_variance`, 0 `nonfinite_quantiles`).
- **Các tháng ở biên persistence trên kiểm định chéo** (cam kết ở mục 8, 30/10): 15/142 lần fit ok, gồm bạc 2017-03 và 14 tháng của Brent:
  - Brent: 2016-03, 2016-09, 2016-10, 2016-12, 2017-01, 2017-02, 2017-03, 2017-04, 2017-06, 2017-07, 2017-08, 2017-09, 2017-12, 2018-01.
  - `pinball_skill` trung bình 7 h của `fhs-gjr-t-dm` (sample `all`), ngày gốc dùng tham số ở biên so với các ngày còn lại:
    - bạc: +0,95 điểm % (23 ngày gốc ở h7) so với +1,59 (724);
    - Brent: +3,96 (290) so với +2,74 (413).
  - Lo ngại "gần IGARCH nên khoảng quá rộng" không thấy ở Brent. Các tháng này không kéo kết quả kiểm định chéo xuống.
- **Hạn chế thống kê:**
  - K4 là lần nhìn thứ 4 vào 2019, với 13 cấu hình (White 2000), và ứng viên là bản sửa hậu nghiệm sau kiểm định chéo. Vì vậy điểm ước lượng 2019 nhiều khả năng lạc quan. Kết luận đã là âm nên điều này không đổi quyết định.
  - `combo-eq3` không kết hợp ba nguồn độc lập, vì q252 và S1a liên hệ trực tiếp.
  - FHS lấy đuôi từ phần dư lịch sử, nên có thể thiếu các cú sốc ngoài mẫu.
  - Tập test 2020 → nay chưa chạy cho K4 và sẽ không chạy.
- **Việc kỹ thuật còn lại (ưu tiên thấp, không ảnh hưởng kết quả):**
  - thêm scipy vào `environment_versions()`;
  - ghi tham số thô của `arch` vào `fhs_fits.parquet` cả khi `GjrParams` từ chối;
  - cột `n_excl_roll` trong `summary.md` đang in dạng số thực (`184.0000`).
- **Nội dung cho buổi bảo vệ:**
  - Ba thí nghiệm (K3, K3b, K4) đều có kế hoạch chốt trước, mốc so sánh mạnh, và kết quả âm có giải thích.
  - K4 còn cho thấy quy trình xử lý một lần chạy hỏng mà không nhìn lại 2019: dừng, chẩn đoán chỉ trên dữ liệu ≤ 2018, sửa có review, chạy lại kiểm định chéo và đối chiếu SHA-256, rồi chạy lại một lần.
  - Với dữ liệu chỉ có giá ở kỳ hạn 1–7 phiên, mốc phân vị 252 phiên rất khó vượt.
