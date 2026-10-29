# K4: FHS + GJR-GARCH và kết hợp phân vị (chốt trước khi chạy)

- Ngày: 29/10/2026
- Người viết: Khải (bản nháp cần phải check)
- Trạng thái: **Chốt trước khi chạy.** Commit và push file này TRƯỚC khi chạy bất kỳ ứng viên nào. Không
  sửa ứng viên, tham số hay quy tắc chọn sau khi thấy kết quả; thay đổi (nếu có) ghi thành mục mới có
  ngày, kèm lý do, và báo cáo cả kết quả trước lẫn sau.
- Căn cứ: ADR-0008, ADR-0009, ADR-0011, `docs/experiments/k3b-volatility-plan.md`.
- Định nghĩa lại K4 (29/10): bỏ độ rộng theo OVX/GVZ. Lý do: bảng tín hiệu chưa có, và bằng chứng về OVX
  yếu (Gilder & Tsiaras 2020, Journal of Futures Markets: "forecasts based on the OVX perform poorly").
  Giữ FHS làm nền như K4 cũ.

## 0. Mở lại vòng dò mô hình chỉ dùng giá

K3b mục 4 đã chốt: không đạt thì dừng dò mô hình chỉ dùng giá. K4 mở lại có chủ đích, với hai thay đổi
để không dùng 2019 vào việc chọn:
1. Chọn ứng viên bằng kiểm định chéo theo thời gian trên 2016, 2017, 2018 (mục 4).
2. Chỉ ứng viên được chọn chạy trên 2019, một lần.

Số lần nhìn vào validation 2019: K3 lần 1 (8 cấu hình), K3b lần 2 (3 cấu hình), **K4 lần 3 (1 cấu hình)**.
Tổng 12 cấu hình; báo cáo phải ghi con số này. Tập test 2020 → nay vẫn không chạy.

Căn cứ chọn hai ứng viên:
- Kuester, Mittnik, Paolella (2006, Journal of Financial Econometrics): trong các phương pháp VaR,
  filtered historical simulation (FHS) đứng sát sau GARCH đuôi dày + EVT; CAViaR kém.
- Nowotarski & Weron (2015): kết hợp dự báo phân vị mạnh trong dự báo giá năng lượng. K4 dùng trọng số
  đều để không có tham số học.

## 1. Giả thuyết

Như K3b: hướng return gần như không dự báo được, độ lớn biến động có tính cụm. S1a co giãn theo EWMA
nhưng phản ứng đối xứng và chậm hồi sau cú sốc (dầu 2019). GJR-GARCH với nhiễu Student-t mô hình hóa
được phản ứng bất đối xứng và đuôi dày; FHS lấy đuôi từ phần dư thực nghiệm. Kết hợp ba nguồn giảm rủi ro
một mô hình sai hẳn trong một giai đoạn.

## 2. Dữ liệu và mẫu

- Cùng bản clean với K3, K3b (`configs/k3_grid.CLEAN_DT`). Không đọc dữ liệu sau 2019-12-31.
- Return ngày r_s = ln(P_s / P_{s−1}) chỉ cho cặp phiên liền kề theo lịch của tài sản; cặp vắt qua
  phiên thiếu thì bỏ. Mọi thống kê tại t chỉ dùng r_s với s ≤ t.
- Target như ADR-0008: log return h phiên, h = 1–7, 7 phân vị.
- Kiểm định chéo: ba fold, ngày gốc trong năm 2016, 2017, 2018. Với fold năm Y, mọi tham số fit chỉ dùng
  return có ngày ≤ thời điểm refit (mục 3) và không dùng ngày đích sau base_date.
- Validation: ngày gốc 2019, trên tập ngày gốc chung của K3 (vàng 245, bạc 245, Brent 202, WTI 202).

## 3. Ứng viên (2, chốt)

Ký hiệu: Q_τ,h = phân vị `baseline-q252` tại t; S_τ,h = phân vị S1a (λ = 0,94, như K3b).

**FHS — `fhs-gjr-t` (train):**
- Mô hình: r_t = ε_t, ε_t = σ_t·z_t (trung bình 0, vì không dự báo hướng);
  σ²_t = ω + (α + γ·1[ε_{t−1} < 0])·ε²_{t−1} + β·σ²_{t−1}; z_t ~ Student-t chuẩn hóa (ν ước lượng).
- Fit bằng thư viện `arch` (chỉ dùng offline), return nhân 100, cửa sổ 1000 return hợp lệ gần nhất.
- Refit đầu mỗi tháng, chỉ dùng return có ngày < ngày đầu tháng; trong tháng giữ nguyên tham số, σ²_t
  cập nhật theo đệ quy với return mới. Fit lỗi hoặc không hội tụ: dùng tham số tháng trước và ghi log.
- Mô phỏng: phần dư chuẩn hóa z của cửa sổ fit; 5000 đường × 7 bước; z* lấy mẫu có hoàn lại từ z;
  ε* = σ*·z*, σ* đi theo phương trình trên; return h phiên = tổng ε* của h bước đầu. Phân vị thực nghiệm
  tại 7 τ, rồi `normalize_quantiles()` đúng một lần. Seed cố định theo (asset, base_date).

**Kết hợp — `combo-eq3` (không train ngoài FHS):**
- q_τ,h = (Q_τ,h + S_τ,h + F_τ,h) / 3, với F là phân vị FHS trước normalize; rồi `normalize_quantiles()`
  đúng một lần.

## 4. Quy tắc chọn (chốt)

- Tính `pinball_skill` so với `baseline-q252` trên 28 nhóm (4 tài sản × 7 h), gộp ngày gốc của ba fold
  2016–2018.
- Chọn ứng viên có trung bình `pinball_skill` cao hơn. Hòa (chênh < 0,1 điểm %): chọn `fhs-gjr-t` (ít
  thành phần hơn).
- **Điều kiện dừng sớm:** nếu cả hai ứng viên có trung bình `pinball_skill` ≤ 0 trên kiểm định chéo thì
  dừng, không chạy 2019, ghi kết quả âm.
- Báo cáo thêm Model Confidence Set 90% (Hansen, Lunde, Nason 2011) trên kiểm định chéo cho ba mô hình
  (`baseline-q252`, `fhs-gjr-t`, `combo-eq3`); chỉ để báo cáo, không dùng để chọn.

## 5. Tiêu chí trên 2019 (chốt, theo ADR-0009 mục 4)

- Chỉ chạy ứng viên đã chọn ở mục 4.
- Tài sản đạt khi cận dưới CI 95% của `pinball_skill` trung bình 7 h > 0; block bootstrap (block 20,
  1000 lần, lịch hợp nhất NYSE/CME), áp chung cho 7 h. Báo cáo từng h, cả `all` và `excl_roll` cho dầu.
- Đạt ở ít nhất một tài sản: viết ADR-0012 chốt mô hình và tham số; viết bản suy luận NumPy (tham số và
  phần dư lưu thành artifact theo ADR-0007, refit hằng tháng offline); chạy song song như S1a; quyết
  champion bằng ADR trước 22/11; tập test chạy một lần sau khi khóa.
- Không đạt: ghi kết quả âm vào ADR-0012, giữ `baseline-q252`, S1a vẫn là challenger, dừng dò mô hình
  chỉ dùng giá đến hết dự án.

## 6. Báo cáo

- Mọi chỉ số ADR-0008 mục 5 theo tài sản × h, cho `baseline-q252`, S1a, `fhs-gjr-t`, `combo-eq3` trên
  kiểm định chéo; ứng viên được chọn thêm 2019.
- Độ ổn định tham số FHS theo từng lần refit (ω, α, γ, β, ν; số lần không hội tụ).
- Thời gian chạy một lần dự báo (4 tài sản) để ước tính cho Lambda.
- Ghi rõ: lần nhìn thứ 3 vào 2019, tổng 12 cấu hình; kiểm định chéo nằm trong giai đoạn train của K3.

## 7. Nguồn

- Kuester, K., Mittnik, S., Paolella, M. (2006). Value-at-Risk Prediction: A Comparison of Alternative
  Strategies. Journal of Financial Econometrics 4(1), 53–89.
- Barone-Adesi, G., Giannopoulos, K., Vosper, L. (1999). VaR without correlations for portfolios of
  derivative securities. Journal of Futures Markets 19(5).
- Glosten, L., Jagannathan, R., Runkle, D. (1993). On the relation between the expected value and the
  volatility of the nominal excess return on stocks. Journal of Finance 48(5).
- Nowotarski, J., Weron, R. (2015). Computing electricity spot price prediction intervals using quantile
  regression and forecast averaging. Computational Statistics 30(3), 791–803.
- Hansen, P., Lunde, A., Nason, J. (2011). The Model Confidence Set. Econometrica 79(2), 453–497.
- Gilder, D., Tsiaras, L. (2020). Volatility forecasts embedded in the prices of crude-oil options.
  Journal of Futures Markets.

## 8. Sửa đổi

### 29/10/2026, trước khi chạy (sau bước probe dữ liệu, chưa có chỉ số nào)

- Brent chỉ có 972 return hợp lệ trước 2016-01-01 (35 cặp phiên vắt qua phiên thiếu); return hợp lệ thứ 1000 là ngày 2016-02-11. Giữ cửa sổ 1000: FHS Brent không hợp lệ ở các ngày gốc từ 1/1 đến 29/2/2016 (39 ngày), nên Brent có 716 ngày gốc trong tập chung thay vì 755. Vàng, bạc, WTI không đổi.
- Lần refit đầu tiên của một tài sản bị lỗi hoặc không hội tụ thì dừng chạy, vì không có tham số tháng trước để dùng lại.
- Model Confidence Set (mục 4, chỉ báo cáo): chạy theo từng tài sản; loss của mỗi ngày gốc là pinball trung bình trên 7 h × 7 τ, sample `all`; size 0,10; 1000 lần bootstrap, block 20, seed 7.
- Ba fold dùng chung một mốc cắt ngày đích là 2018-12-31.
- Để tính `excl_roll` trên 2016–2018, cửa sổ ngày roll trong `src/eval/walk_forward.py` được tính từ kỳ đánh giá thay vì gắn cứng quanh 2019. Kết quả 2019 không đổi (có test hàm thuần, không đọc dữ liệu 2019).

### 29/10/2026, sau kiểm định chéo, trước khi chạy 2019

- Chẩn đoán trên k4-cv-clean: phần dư chuẩn hóa z dùng để bootstrap không được trừ trung bình (trung vị của mean(z) theo tài sản từ −0,017 đến −0,051), nên FHS mang một độ trôi âm; q50 âm ở khoảng 90% ngày gốc, trái với mục 3 ("trung bình 0, không dự báo hướng").
- Sửa: ứng viên chạy 2019 là `fhs-gjr-t-dm`, giống `fhs-gjr-t` nhưng bootstrap từ z − mean(z) của cửa sổ fit (không đổi độ lệch chuẩn). Tham số GJR, cửa sổ, lịch refit, số đường và seed giữ nguyên.
- Đây là sửa đổi sau khi đã xem kết quả kiểm định chéo của bản gốc. `fhs-gjr-t-dm` chạy kiểm định chéo một lần, chỉ để kiểm tra. Quy tắc chốt trước khi xem số: trung bình pinball_skill 28 nhóm của bản dm > 0 thì chạy 2019 cho bản dm một lần, theo tiêu chí mục 5; ≤ 0 thì dừng, không chạy 2019. Không chọn lại giữa FHS và combo.
- Báo cáo cả `fhs-gjr-t` (kiểm định chéo) và `fhs-gjr-t-dm` (kiểm định chéo và 2019), ghi rõ thứ tự quyết định. Số cấu hình xem trên 2019 vẫn là 1 (tổng 12); kiểm định chéo thêm 1 cấu hình.

### 29/10/2026 tối, theo review của Long (#59), trước khi chạy 2019

- Quan hệ với ADR-0010: K4 là ngoại lệ nghiên cứu có giới hạn đối với quyết định dừng dò mô hình chỉ dùng giá. Lý do: giả thuyết mới (biến động có điều kiện, phản ứng bất đối xứng, đuôi lấy từ phần dư) chưa được thử ở K3/K3b, và việc chọn dùng kiểm định chéo để 2019 chỉ còn vai trò xác nhận. Người duyệt: Khải (Research Lead), Long review. Không đạt mục 5 thì dừng dò mô hình chỉ dùng giá đến hết dự án, không có ngoại lệ thứ hai.
- Đếm lại: tính cả DLinear MVP (ADR-0010), K4 là lần dùng validation 2019 thứ 4 ở cấp dự án; tổng số cấu hình đã xem trên 2019 = số cấu hình của DLinear MVP + 11 (K3, K3b) + 1 (K4). Báo cáo ghi rõ rủi ro data snooping (White 2000).
- Phân loại: `fhs-gjr-t` và `combo-eq3` là ứng viên đăng ký trước; `fhs-gjr-t-dm` là sửa đổi hậu nghiệm. Báo cáo thêm chênh lệch pinball_skill của `fhs-gjr-t-dm` so với `fhs-gjr-t` trên cùng common mask. Lý do sửa là trung bình của z âm (độ trôi); q50 âm chỉ là hệ quả.
- Nguồn cho `combo-eq3`: Lichtendahl, Grushka-Cockayne, Winkler (2013), Is It Better to Average Probabilities or Quantiles?, Management Science 59(7). Nowotarski & Weron (2015) là QRA, chỉ dùng làm bối cảnh.
- Báo cáo bổ sung, không đổi quy tắc chọn hay tiêu chí mục 5: kết quả từng fold 2016/2017/2018 và số ngày hợp lệ theo tài sản × h; Holm qua 4 tài sản cho kiểm định mục 5; độ nhạy CI theo block length 10, 20, 40; độ nhạy FHS theo 2 seed khác và 10000 đường (chỉ để kiểm tra độ bền); coverage_80, width_80, interval score, hit rate và kiểm định độc lập các lần vượt khoảng (Christoffersen 1998).
- Kiểm tra mô hình: tham số nạp vào phải có ν > 2 và α + γ/2 + β < 1; báo số tháng dùng lại tham số liên tiếp; phương sai và phân vị phải hữu hạn trước khi coi là hợp lệ.
- Phạm vi `cross_validation`: loại đánh giá nội bộ của K4, chỉ ghi vào `eval/k4/`, không vào bảng Accuracy hay schema production.
- Hạn chế ghi trong báo cáo: q252 và S1a có liên hệ trực tiếp nên `combo-eq3` không kết hợp ba nguồn độc lập; FHS lấy đuôi từ phần dư lịch sử nên có thể thiếu các cú sốc ngoài mẫu.
- **Tiêu chí mục 5 cho dầu:** quyết định "đạt" theo sample `all`; `excl_roll` chỉ báo cáo. Nếu `all` đạt mà `excl_roll` không đạt thì ghi rõ trong ADR-0012.
- **Toàn vẹn kết quả kiểm định chéo:** phần chặn val2019 chỉ nhận kết quả cv và cv-dm chạy từ code đã commit (không dirty), khớp fingerprint config/code/data và checksum từng file.

- **Sửa lại (29/10 khuya):** điều kiện persistence là α + γ/2 + β ≤ 1 (đúng ràng buộc của arch khi fit), không phải < 1. 11/142 lần fit trên kiểm định chéo nằm ở biên 1 (gần IGARCH); với kỳ hạn tối đa 7 phiên phương sai mô phỏng vẫn hữu hạn nên vẫn hợp lệ. Chỉ từ chối tham số có persistence > 1 + 1e-9 hoặc ν ≤ 2. Báo cáo liệt kê các lần fit nằm ở biên.
