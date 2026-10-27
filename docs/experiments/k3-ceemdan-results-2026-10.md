# K3: kết quả CEEMDAN + DLinear trên validation 2019

- Ngày: 26/10/2026
- Người viết: Khải (bản nháp do Claude soạn)
- Kế hoạch đã chốt trước khi train: `docs/experiments/k3-ceemdan-plan.md` (commit `59384e4`). Làm
  đúng kế hoạch: không thêm cấu hình, không đổi siêu tham số, không early stopping theo 2019.
- Căn cứ: ADR-0007, ADR-0008; probe `docs/experiments/k3-ceemdan-probe-2026-10-26.md`.
- Chạy: `python -m src.forecast.train_ceemdan` (run `k3-val2019`), venv Python 3.11.9, numpy 2.4.6,
  EMD-signal 1.10.0, torch 2.14.1+cpu, 1 luồng.

## Tóm tắt

- **Không tài sản nào đạt tiêu chí lên production.** Ở cấu hình được chọn, cận dưới CI 95% của
  `pinball_skill` ≤ 0 ở cả 42/42 nhóm (28 nhóm `all`, 14 nhóm dầu `excl_roll`). `baseline-q252` giữ
  nguyên cho cả 4 tài sản.
- Cả 8 cấu hình đều có trung bình `pinball_skill` âm trên 28 nhóm (từ −2,53 đến −5,78 điểm %).
- Cấu hình được chọn theo quy tắc mục 5: **window 252, K 3, L 30** (`w252-k3-l30`), trung bình
  −2,53 điểm %. Cấu hình kế tiếp là `w252-k4-l30` (−3,07), cách 0,54 điểm %, nên không có hòa.
- So với DLinear MVP trên cùng tập ngày gốc: cấu hình chọn cao hơn MVP ở 41/42 nhóm (trừ WTI
  `excl_roll` h = 6), nhưng vẫn thua mốc 252 phiên. Lý do chủ yếu là đầu ra neo vào mốc, nên mô
  hình không lệch xa mốc như MVP.
- Có 5/28 nhóm `all` có `pinball_skill` dương (Brent h = 1–4, WTI h = 3), nhưng đều nhỏ (≤ +1,2
  điểm %) và CI chứa 0. Kết quả này lại được chọn trên chính 2019 (1/8 cấu hình), nên còn lạc quan.

## 1. Thiết lập

| mục | giá trị |
|---|---|
| Dữ liệu | clean `dt=2026-10-22`, cắt tại 2019-12-31 ngay khi đọc (filter pyarrow); 8.026 dòng 4 tài sản, ngày lớn nhất 2019-12-31 |
| Cache CEEMDAN | `cfg_hash` 4c3229533ae3 (trials 100, epsilon 0,005, seed 42, `keep_last` 128); chỉ đọc qua `src/features/ceemdan_cache.py`; `price_hash` của mọi cửa sổ dùng đến được kiểm lại với bản clean (khớp) |
| Train / validation | ngày gốc 2014–2018, mọi ngày đích ≤ 2018-12-31 / ngày gốc 2019, ngày đích ≤ 2019-12-31 |
| Mẫu | quy tắc A (kế hoạch mục 1) |
| Đặc trưng | `fixed_imf_matrix(K, L)` chia cho P_t; cột residue thành residue/P_t − 1; chuẩn hóa từng cột (mean/std) fit chỉ trên mảng train |
| Mô hình | mỗi tài sản một mô hình; tuyến tính L → 49 chia sẻ giữa các cột, nhân hệ số riêng từng cột, cộng lại; trung vị = q50 mốc + Δm, khoảng cách phân vị = khoảng cách mốc × exp(Δg); Δm = Δg = 0 lúc khởi tạo |
| Huấn luyện | pinball trung bình 7 h × 7 τ; Adam lr 1e-3, weight decay 1e-4, batch 64, 20 epoch cố định; seed 7, 8, 9 |
| Tổng hợp | trung bình phân vị 3 seed → `normalize_quantiles()` một lần → `prob_up()` |
| Đánh giá | `walk_forward._make_detail` + `_summarize` (chỉ số của `metrics.py`; CI block bootstrap block 20, 1.000 lần, lịch hợp nhất NYSE/CME, seed 7; DM theo `DM_GAP_POLICY`; Holm 28/14) trên tập ngày gốc chung của 8 cấu hình |
| So sánh | `baseline-q252` (cùng hàm mốc dùng để neo), DLinear MVP `dlinear-41e13dc5de3d` (artifact chỉ đọc, chạy NumPy trên cùng ngày gốc), naive (return = 0) |

**Những chỗ kế hoạch chưa nói rõ và cách đã làm** (không đổi lưới, siêu tham số hay quy tắc chọn).
Khải đã xác nhận mục 1, 2 và chốt mục 4 ngày 26/10/2026, sau khi có kết quả K3; các quyết định này
được ghi vào ADR.

1. *Bias* (đã chấp nhận). Kế hoạch ghi "cùng một ánh xạ tuyến tính L → 49". Code dùng ánh xạ tuyến tính không bias
   chia sẻ giữa các cột, nhân hệ số cột, cộng lại, rồi cộng **một** bias 49 chung, như bias của
   DLinear. Khởi tạo: trọng số chia sẻ = 0, bias = 0, hệ số cột = 1, nên Δm = Δg = 0 và gradient vẫn
   chảy vào trọng số chia sẻ và bias (có test).
2. *Độ chính xác số* (đã chấp nhận). Mô hình chạy float64, vì yêu cầu "lúc khởi tạo trùng
   baseline-q252 với atol 1e-9" không đạt được bằng float32. Runtime NumPy cho Lambda
   (`CeemdanDLinearNumpy`) cũng chạy float64, nên hai bên khớp nhau: parity torch–NumPy thực tế
   ≤ 1,1e-16.
3. *Weight decay* là tham số `weight_decay` của `torch.optim.Adam` (L2), áp lên mọi tham số.
4. *Tiêu chí theo tài sản* (đã chốt, áp dụng cho mọi thí nghiệm mới). Một tài sản đạt khi cận dưới
   CI 95% của `pinball_skill` **trung bình 7 h** lớn hơn 0, dùng chung kế hoạch block bootstrap của
   `walk_forward.py` (block 20, 1.000 lần, lịch hợp nhất NYSE/CME). Quy tắc này được chốt sau khi có
   kết quả K3, nên K3 không được đánh giá trước theo quy tắc này. Kết luận của K3 (§5) dựa trên CI
   theo từng nhóm tài sản × h: không nhóm nào có cận dưới > 0.
5. *Naive* không có phân vị. Nó là mẫu số của `mae_ratio_vs_naive` (naive = 1), nên không có cột
   riêng trong bảng.
6. *DLinear MVP* được chạy lại bằng `DLinearNumpy` trên bản clean `dt=2026-10-22` (MVP train trên
   `dt=2026-10-09`). Probe xác nhận giá 2014–2019 của hai bản giống nhau (`price_hash` lệch 0).

## 2. Số mẫu

Số mẫu train/validation của cả 32 (cấu hình × tài sản) **khớp bảng quy tắc A mục 5 của probe**. Code
dừng nếu lệch. Tập ngày gốc chung của 8 cấu hình (validation 2019): vàng 245, bạc 245, Brent 202,
WTI 202. Với dầu, tập này trùng tập L = 60. DLinear MVP có dự báo ở mọi ngày gốc của tập chung.

Theo quy tắc A, các mẫu dầu có phiên thiếu ở phần cũ của cửa sổ decompose vẫn được giữ, và số phiên
thiếu được ghi vào diag. Ví dụ với `w252-k3-l30`, Brent giữ 442/1.110 mẫu train và 221/232 mẫu
validation có phiên thiếu như vậy. Cột "n_imf < K" là số mẫu có ít IMF hơn K; các cột IMF thiếu của
những mẫu này bằng 0.

| config | asset | train | val | train có phiên thiếu (decompose) | val có phiên thiếu (decompose) | train n_imf < K | parity |
|---|---|---|---|---|---|---|---|
| w252-k3-l30 | gold | 1251 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w252-k3-l30 | silver | 1251 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w252-k3-l30 | brent | 1110 | 232 | 442 | 221 | 0 | 5.6e-17 |
| w252-k3-l30 | wti | 1172 | 232 | 221 | 221 | 0 | 5.6e-17 |
| w252-k3-l60 | gold | 1251 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w252-k3-l60 | silver | 1251 | 245 | 0 | 0 | 0 | 4.2e-17 |
| w252-k3-l60 | brent | 1050 | 202 | 382 | 191 | 0 | 2.8e-17 |
| w252-k3-l60 | wti | 1142 | 202 | 191 | 191 | 0 | 5.6e-17 |
| w252-k4-l30 | gold | 1251 | 245 | 0 | 0 | 2 | 1.4e-17 |
| w252-k4-l30 | silver | 1251 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w252-k4-l30 | brent | 1110 | 232 | 442 | 221 | 21 | 6.2e-17 |
| w252-k4-l30 | wti | 1172 | 232 | 221 | 221 | 3 | 5.6e-17 |
| w252-k4-l60 | gold | 1251 | 245 | 0 | 0 | 2 | 2.8e-17 |
| w252-k4-l60 | silver | 1251 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w252-k4-l60 | brent | 1050 | 202 | 382 | 191 | 21 | 5.6e-17 |
| w252-k4-l60 | wti | 1142 | 202 | 191 | 191 | 3 | 5.6e-17 |
| w504-k4-l30 | gold | 1250 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w504-k4-l30 | silver | 1250 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w504-k4-l30 | brent | 1110 | 232 | 946 | 232 | 0 | 5.6e-17 |
| w504-k4-l30 | wti | 1171 | 232 | 681 | 232 | 0 | 8.3e-17 |
| w504-k4-l60 | gold | 1250 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w504-k4-l60 | silver | 1250 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w504-k4-l60 | brent | 1050 | 202 | 886 | 202 | 0 | 5.6e-17 |
| w504-k4-l60 | wti | 1141 | 202 | 651 | 202 | 0 | 8.3e-17 |
| w504-k5-l30 | gold | 1250 | 245 | 0 | 0 | 0 | 1.4e-17 |
| w504-k5-l30 | silver | 1250 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w504-k5-l30 | brent | 1110 | 232 | 946 | 232 | 14 | 5.6e-17 |
| w504-k5-l30 | wti | 1171 | 232 | 681 | 232 | 3 | 1.1e-16 |
| w504-k5-l60 | gold | 1250 | 245 | 0 | 0 | 0 | 2.8e-17 |
| w504-k5-l60 | silver | 1250 | 245 | 0 | 0 | 0 | 4.2e-17 |
| w504-k5-l60 | brent | 1050 | 202 | 886 | 202 | 14 | 5.6e-17 |
| w504-k5-l60 | wti | 1141 | 202 | 651 | 202 | 3 | 5.6e-17 |

## 3. Cả 8 cấu hình: trung bình `pinball_skill` (sample = `all`, trung bình 7 h, tập chung)

| config | gold | silver | brent | wti | trung bình 28 nhóm |
|---|---|---|---|---|---|
| w252-k3-l30 | -0.0294 | -0.0416 | -0.0098 | -0.0205 | -0.0253 |
| w252-k3-l60 | -0.0673 | -0.0735 | -0.0474 | -0.0313 | -0.0549 |
| w252-k4-l30 | -0.0180 | -0.0531 | -0.0213 | -0.0305 | -0.0307 |
| w252-k4-l60 | -0.0675 | -0.0917 | -0.0510 | -0.0209 | -0.0578 |
| w504-k4-l30 | -0.0320 | -0.0312 | -0.0338 | -0.0456 | -0.0357 |
| w504-k4-l60 | -0.0549 | -0.0808 | -0.0613 | -0.0142 | -0.0528 |
| w504-k5-l30 | -0.0238 | -0.0309 | -0.0463 | -0.0520 | -0.0382 |
| w504-k5-l60 | -0.0546 | -0.0852 | -0.0715 | -0.0201 | -0.0578 |

- Cao nhất là `w252-k3-l30` (−0,0253). Cấu hình nào chênh dưới 0,1 điểm % thì coi là hòa; ở đây
  không có cấu hình nào hòa.
- L = 30 tốt hơn L = 60 ở cả 4 cặp (window, K), chênh 1,7–3,0 điểm %.
- Không cấu hình nào có trung bình dương ở bất kỳ tài sản nào.
- Số nhóm `all` có `pinball_skill` > 0 ở từng cấu hình: 5, 1, 3, 2, 0, 1, 0, 0 (theo thứ tự bảng).
  Không cấu hình nào có nhóm nào đạt cận dưới CI > 0.

## 4. Cấu hình được chọn `w252-k3-l30` so với baseline-q252 và DLinear MVP

Mỗi ô `pinball_skill` gồm giá trị và [CI 95%] block bootstrap. `width_80` và `interval_score_80` tính
theo đơn vị log return; `n` là số ngày gốc. Theo định nghĩa, baseline-q252 có `pinball_skill` = 0 và
CI [0, 0]. Code kiểm tra mốc dùng để neo trùng mốc mà `walk_forward` dùng khi chấm: sai lệch tối đa
dưới 1e-12, nếu không thì dừng.

#### gold

| sample | h | model | pinball_skill [CI 95%] | coverage_80 | width_80 | interval_score_80 | brier_skill | mae_ratio_vs_naive | sign_accuracy | up_rate | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 1 | w252-k3-l30 | -0.0201 [-0.0565, +0.0086] | 0.7306 | 0.0153 | 0.0279 | -0.0496 | 1.0344 | 0.5165 | 0.5388 | 245 |
| all | 1 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7388 | 0.0149 | 0.0275 | -0.0002 | 1.0009 | 0.5121 | 0.5388 | 245 |
| all | 1 | dlinear-mvp | -0.1979 [-0.3411, -0.0756] | 0.8735 | 0.0260 | 0.0320 | -0.1469 | 1.2537 | 0.5083 | 0.5388 | 245 |
| all | 2 | w252-k3-l30 | -0.0388 [-0.1070, +0.0159] | 0.6816 | 0.0218 | 0.0397 | -0.0786 | 1.0721 | 0.5185 | 0.5469 | 245 |
| all | 2 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7306 | 0.0215 | 0.0385 | 0.0025 | 1.0030 | 0.5447 | 0.5469 | 245 |
| all | 2 | dlinear-mvp | -0.0740 [-0.2211, +0.0447] | 0.8694 | 0.0341 | 0.0406 | -0.0364 | 1.1013 | 0.5226 | 0.5469 | 245 |
| all | 3 | w252-k3-l30 | -0.0200 [-0.0747, +0.0223] | 0.7143 | 0.0259 | 0.0485 | -0.0689 | 1.0376 | 0.5000 | 0.5796 | 245 |
| all | 3 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7469 | 0.0259 | 0.0475 | -0.0012 | 0.9991 | 0.5378 | 0.5796 | 245 |
| all | 3 | dlinear-mvp | -0.1220 [-0.2895, +0.0070] | 0.8612 | 0.0405 | 0.0517 | -0.1731 | 1.1970 | 0.4672 | 0.5796 | 245 |
| all | 4 | w252-k3-l30 | -0.0253 [-0.0744, +0.0211] | 0.7510 | 0.0303 | 0.0569 | -0.0641 | 1.0303 | 0.5061 | 0.5755 | 245 |
| all | 4 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7592 | 0.0306 | 0.0557 | -0.0026 | 1.0019 | 0.5347 | 0.5755 | 245 |
| all | 4 | dlinear-mvp | -0.1272 [-0.2789, -0.0170] | 0.8204 | 0.0467 | 0.0608 | -0.1329 | 1.1898 | 0.4776 | 0.5755 | 245 |
| all | 5 | w252-k3-l30 | -0.0318 [-0.0851, +0.0146] | 0.7184 | 0.0337 | 0.0644 | -0.0623 | 1.0402 | 0.5164 | 0.6000 | 245 |
| all | 5 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7551 | 0.0342 | 0.0623 | 0.0065 | 0.9923 | 0.5533 | 0.6000 | 245 |
| all | 5 | dlinear-mvp | -0.1938 [-0.3267, -0.0719] | 0.8204 | 0.0521 | 0.0716 | -0.1592 | 1.2573 | 0.4590 | 0.6000 | 245 |
| all | 6 | w252-k3-l30 | -0.0287 [-0.0766, +0.0137] | 0.7347 | 0.0382 | 0.0689 | -0.0831 | 1.0459 | 0.4980 | 0.5959 | 245 |
| all | 6 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7673 | 0.0388 | 0.0681 | -0.0016 | 1.0003 | 0.5469 | 0.5959 | 245 |
| all | 6 | dlinear-mvp | -0.1265 [-0.2336, -0.0351] | 0.8245 | 0.0556 | 0.0743 | -0.0966 | 1.1754 | 0.4857 | 0.5959 | 245 |
| all | 7 | w252-k3-l30 | -0.0408 [-0.0821, -0.0062] | 0.7306 | 0.0413 | 0.0755 | -0.0739 | 1.0632 | 0.4672 | 0.5959 | 245 |
| all | 7 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7551 | 0.0415 | 0.0736 | -0.0015 | 1.0041 | 0.5187 | 0.5959 | 245 |
| all | 7 | dlinear-mvp | -0.1246 [-0.2619, -0.0098] | 0.8408 | 0.0598 | 0.0798 | -0.1085 | 1.2042 | 0.4672 | 0.5959 | 245 |

#### silver

| sample | h | model | pinball_skill [CI 95%] | coverage_80 | width_80 | interval_score_80 | brier_skill | mae_ratio_vs_naive | sign_accuracy | up_rate | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 1 | w252-k3-l30 | -0.0543 [-0.0944, -0.0208] | 0.7551 | 0.0246 | 0.0472 | -0.0634 | 1.0795 | 0.5043 | 0.5306 | 245 |
| all | 1 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7592 | 0.0240 | 0.0457 | 0.0028 | 0.9996 | 0.5267 | 0.5306 | 245 |
| all | 1 | dlinear-mvp | -0.2926 [-0.4288, -0.1726] | 0.7959 | 0.0357 | 0.0552 | -0.1936 | 1.4051 | 0.5085 | 0.5306 | 245 |
| all | 2 | w252-k3-l30 | -0.0471 [-0.1136, +0.0093] | 0.7224 | 0.0333 | 0.0685 | -0.0773 | 1.0628 | 0.5413 | 0.5265 | 245 |
| all | 2 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7510 | 0.0331 | 0.0649 | 0.0019 | 1.0030 | 0.4698 | 0.5265 | 245 |
| all | 2 | dlinear-mvp | -0.1046 [-0.2506, +0.0134] | 0.8571 | 0.0496 | 0.0711 | -0.0641 | 1.1528 | 0.4917 | 0.5265 | 245 |
| all | 3 | w252-k3-l30 | -0.0147 [-0.0724, +0.0348] | 0.7388 | 0.0405 | 0.0822 | -0.0294 | 1.0298 | 0.5083 | 0.5224 | 245 |
| all | 3 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7673 | 0.0408 | 0.0811 | 0.0014 | 1.0014 | 0.5096 | 0.5224 | 245 |
| all | 3 | dlinear-mvp | -0.1084 [-0.2131, -0.0225] | 0.8327 | 0.0605 | 0.0872 | -0.0858 | 1.1552 | 0.5042 | 0.5224 | 245 |
| all | 4 | w252-k3-l30 | -0.0321 [-0.1093, +0.0365] | 0.7510 | 0.0476 | 0.0932 | -0.0429 | 1.0493 | 0.5062 | 0.5143 | 245 |
| all | 4 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7755 | 0.0479 | 0.0909 | 0.0053 | 0.9989 | 0.5451 | 0.5143 | 245 |
| all | 4 | dlinear-mvp | -0.1630 [-0.2899, -0.0557] | 0.8286 | 0.0718 | 0.1026 | -0.1243 | 1.2287 | 0.5103 | 0.5143 | 245 |
| all | 5 | w252-k3-l30 | -0.0277 [-0.1024, +0.0427] | 0.7347 | 0.0519 | 0.1051 | -0.0585 | 1.0517 | 0.4897 | 0.5020 | 245 |
| all | 5 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7510 | 0.0518 | 0.1028 | 0.0031 | 1.0012 | 0.5502 | 0.5020 | 245 |
| all | 5 | dlinear-mvp | -0.1634 [-0.2831, -0.0598] | 0.8245 | 0.0812 | 0.1125 | -0.1282 | 1.2500 | 0.4774 | 0.5020 | 245 |
| all | 6 | w252-k3-l30 | -0.0489 [-0.1390, +0.0314] | 0.7224 | 0.0557 | 0.1195 | -0.1143 | 1.0702 | 0.4856 | 0.4816 | 245 |
| all | 6 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7429 | 0.0560 | 0.1142 | -0.0017 | 1.0102 | 0.4891 | 0.4816 | 245 |
| all | 6 | dlinear-mvp | -0.1147 [-0.2398, -0.0128] | 0.8367 | 0.0883 | 0.1211 | -0.0899 | 1.1757 | 0.5350 | 0.4816 | 245 |
| all | 7 | w252-k3-l30 | -0.0662 [-0.1611, +0.0189] | 0.7388 | 0.0602 | 0.1274 | -0.1019 | 1.0924 | 0.4876 | 0.4776 | 245 |
| all | 7 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7551 | 0.0612 | 0.1209 | -0.0022 | 1.0139 | 0.4636 | 0.4776 | 245 |
| all | 7 | dlinear-mvp | -0.1489 [-0.3003, -0.0153] | 0.8408 | 0.0966 | 0.1323 | -0.1035 | 1.2210 | 0.5248 | 0.4776 | 245 |

#### brent

| sample | h | model | pinball_skill [CI 95%] | coverage_80 | width_80 | interval_score_80 | brier_skill | mae_ratio_vs_naive | sign_accuracy | up_rate | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 1 | w252-k3-l30 | +0.0006 [-0.0652, +0.0460] | 0.8218 | 0.0476 | 0.0712 | -0.0356 | 1.0150 | 0.5200 | 0.5495 | 202 |
| all | 1 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8218 | 0.0455 | 0.0722 | -0.0007 | 0.9984 | 0.5550 | 0.5495 | 202 |
| all | 1 | dlinear-mvp | -0.0718 [-0.1424, -0.0105] | 0.8465 | 0.0538 | 0.0771 | -0.0617 | 1.0694 | 0.5400 | 0.5495 | 202 |
| all | 2 | w252-k3-l30 | +0.0062 [-0.0424, +0.0496] | 0.8366 | 0.0713 | 0.0979 | -0.0154 | 1.0099 | 0.5323 | 0.5446 | 202 |
| all | 2 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8069 | 0.0691 | 0.1011 | 0.0045 | 0.9915 | 0.5473 | 0.5446 | 202 |
| all | 2 | dlinear-mvp | -0.0279 [-0.0672, +0.0101] | 0.7723 | 0.0668 | 0.1021 | -0.0012 | 1.0346 | 0.5572 | 0.5446 | 202 |
| all | 3 | w252-k3-l30 | +0.0110 [-0.0333, +0.0541] | 0.8168 | 0.0826 | 0.1149 | -0.0311 | 1.0212 | 0.5198 | 0.5743 | 202 |
| all | 3 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8020 | 0.0805 | 0.1185 | -0.0070 | 0.9898 | 0.5743 | 0.5743 | 202 |
| all | 3 | dlinear-mvp | -0.0526 [-0.1081, -0.0059] | 0.8218 | 0.0844 | 0.1231 | -0.0799 | 1.0773 | 0.5396 | 0.5743 | 202 |
| all | 4 | w252-k3-l30 | +0.0120 [-0.0356, +0.0577] | 0.8267 | 0.0907 | 0.1260 | -0.0245 | 1.0135 | 0.5495 | 0.5990 | 202 |
| all | 4 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8218 | 0.0884 | 0.1302 | -0.0051 | 0.9834 | 0.6139 | 0.5990 | 202 |
| all | 4 | dlinear-mvp | -0.0558 [-0.1083, -0.0135] | 0.8069 | 0.0973 | 0.1346 | -0.0874 | 1.0660 | 0.5149 | 0.5990 | 202 |
| all | 5 | w252-k3-l30 | -0.0286 [-0.0895, +0.0295] | 0.8416 | 0.1030 | 0.1403 | -0.0452 | 1.0617 | 0.5347 | 0.5891 | 202 |
| all | 5 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8218 | 0.1003 | 0.1385 | 0.0022 | 0.9768 | 0.5792 | 0.5891 | 202 |
| all | 5 | dlinear-mvp | -0.0640 [-0.1095, -0.0225] | 0.8614 | 0.1096 | 0.1451 | -0.0845 | 1.0600 | 0.5000 | 0.5891 | 202 |
| all | 6 | w252-k3-l30 | -0.0301 [-0.1044, +0.0439] | 0.8416 | 0.1190 | 0.1513 | -0.0726 | 1.0678 | 0.5473 | 0.6139 | 202 |
| all | 6 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8614 | 0.1154 | 0.1523 | -0.0080 | 0.9722 | 0.5920 | 0.6139 | 202 |
| all | 6 | dlinear-mvp | -0.0766 [-0.1388, -0.0184] | 0.8515 | 0.1197 | 0.1600 | -0.0912 | 1.0688 | 0.5473 | 0.6139 | 202 |
| all | 7 | w252-k3-l30 | -0.0394 [-0.1211, +0.0405] | 0.8663 | 0.1317 | 0.1608 | -0.0634 | 1.0694 | 0.5545 | 0.6139 | 202 |
| all | 7 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8762 | 0.1282 | 0.1632 | -0.0124 | 0.9714 | 0.5842 | 0.6139 | 202 |
| all | 7 | dlinear-mvp | -0.0876 [-0.1530, -0.0302] | 0.8564 | 0.1318 | 0.1712 | -0.1188 | 1.0899 | 0.4752 | 0.6139 | 202 |
| excl_roll | 1 | w252-k3-l30 | -0.0066 [-0.0785, +0.0461] | 0.8478 | 0.0476 | 0.0684 | -0.0481 | 1.0173 | 0.5301 | 0.5761 | 184 |
| excl_roll | 1 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8424 | 0.0455 | 0.0690 | -0.0047 | 0.9939 | 0.5792 | 0.5761 | 184 |
| excl_roll | 1 | dlinear-mvp | -0.0797 [-0.1623, -0.0093] | 0.8587 | 0.0540 | 0.0737 | -0.0681 | 1.0741 | 0.5519 | 0.5761 | 184 |
| excl_roll | 2 | w252-k3-l30 | -0.0208 [-0.0782, +0.0350] | 0.8571 | 0.0712 | 0.0947 | -0.0428 | 1.0215 | 0.5057 | 0.5714 | 175 |
| excl_roll | 2 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8343 | 0.0691 | 0.0941 | 0.0022 | 0.9802 | 0.5747 | 0.5714 | 175 |
| excl_roll | 2 | dlinear-mvp | -0.0414 [-0.0822, +0.0007] | 0.8057 | 0.0672 | 0.0945 | -0.0201 | 1.0598 | 0.5517 | 0.5714 | 175 |
| excl_roll | 3 | w252-k3-l30 | -0.0309 [-0.0846, +0.0249] | 0.8373 | 0.0823 | 0.1087 | -0.0688 | 1.0490 | 0.5000 | 0.6205 | 166 |
| excl_roll | 3 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8434 | 0.0806 | 0.1063 | -0.0120 | 0.9795 | 0.6145 | 0.6205 | 166 |
| excl_roll | 3 | dlinear-mvp | -0.0786 [-0.1396, -0.0215] | 0.8675 | 0.0844 | 0.1124 | -0.1070 | 1.1043 | 0.5361 | 0.6205 | 166 |
| excl_roll | 4 | w252-k3-l30 | -0.0270 [-0.0825, +0.0299] | 0.8408 | 0.0902 | 0.1179 | -0.0510 | 1.0424 | 0.5414 | 0.6688 | 157 |
| excl_roll | 4 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8408 | 0.0884 | 0.1170 | -0.0073 | 0.9719 | 0.6497 | 0.6688 | 157 |
| excl_roll | 4 | dlinear-mvp | -0.0874 [-0.1413, -0.0371] | 0.8153 | 0.0965 | 0.1238 | -0.1206 | 1.0916 | 0.5159 | 0.6688 | 157 |
| excl_roll | 5 | w252-k3-l30 | -0.0776 [-0.1457, +0.0011] | 0.8649 | 0.1023 | 0.1298 | -0.0657 | 1.1194 | 0.5405 | 0.6757 | 148 |
| excl_roll | 5 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8378 | 0.1004 | 0.1227 | 0.0021 | 0.9599 | 0.5676 | 0.6757 | 148 |
| excl_roll | 5 | dlinear-mvp | -0.0830 [-0.1408, -0.0235] | 0.8851 | 0.1090 | 0.1263 | -0.1230 | 1.1095 | 0.4595 | 0.6757 | 148 |
| excl_roll | 6 | w252-k3-l30 | -0.0853 [-0.1703, +0.0025] | 0.8705 | 0.1184 | 0.1425 | -0.1190 | 1.1259 | 0.5290 | 0.7194 | 139 |
| excl_roll | 6 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8777 | 0.1155 | 0.1375 | -0.0144 | 0.9392 | 0.6812 | 0.7194 | 139 |
| excl_roll | 6 | dlinear-mvp | -0.1110 [-0.1787, -0.0454] | 0.8849 | 0.1192 | 0.1426 | -0.1564 | 1.1256 | 0.5290 | 0.7194 | 139 |
| excl_roll | 7 | w252-k3-l30 | -0.1032 [-0.2043, +0.0030] | 0.8837 | 0.1315 | 0.1526 | -0.1111 | 1.1213 | 0.5659 | 0.7209 | 129 |
| excl_roll | 7 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.9147 | 0.1282 | 0.1463 | -0.0306 | 0.9260 | 0.6667 | 0.7209 | 129 |
| excl_roll | 7 | dlinear-mvp | -0.1074 [-0.1629, -0.0528] | 0.9225 | 0.1317 | 0.1494 | -0.1813 | 1.1506 | 0.4419 | 0.7209 | 129 |

#### wti

| sample | h | model | pinball_skill [CI 95%] | coverage_80 | width_80 | interval_score_80 | brier_skill | mae_ratio_vs_naive | sign_accuracy | up_rate | n |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 1 | w252-k3-l30 | -0.0457 [-0.0940, -0.0133] | 0.7822 | 0.0522 | 0.0803 | -0.1066 | 1.1007 | 0.4478 | 0.5248 | 202 |
| all | 1 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8069 | 0.0498 | 0.0794 | 0.0031 | 0.9996 | 0.5274 | 0.5248 | 202 |
| all | 1 | dlinear-mvp | -0.0721 [-0.1544, -0.0124] | 0.7921 | 0.0526 | 0.0825 | -0.1329 | 1.1062 | 0.4876 | 0.5248 | 202 |
| all | 2 | w252-k3-l30 | -0.0043 [-0.0364, +0.0268] | 0.7673 | 0.0729 | 0.1090 | -0.0366 | 1.0185 | 0.5099 | 0.5446 | 202 |
| all | 2 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7475 | 0.0700 | 0.1088 | 0.0011 | 0.9952 | 0.5446 | 0.5446 | 202 |
| all | 2 | dlinear-mvp | -0.0332 [-0.0873, +0.0148] | 0.7574 | 0.0680 | 0.1117 | -0.0516 | 1.0560 | 0.5297 | 0.5446 | 202 |
| all | 3 | w252-k3-l30 | +0.0012 [-0.0384, +0.0425] | 0.7673 | 0.0845 | 0.1247 | -0.0064 | 1.0154 | 0.5347 | 0.5495 | 202 |
| all | 3 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7673 | 0.0817 | 0.1271 | 0.0029 | 0.9966 | 0.5594 | 0.5495 | 202 |
| all | 3 | dlinear-mvp | -0.0434 [-0.0998, +0.0068] | 0.7574 | 0.0841 | 0.1316 | -0.0172 | 1.0827 | 0.5347 | 0.5495 | 202 |
| all | 4 | w252-k3-l30 | -0.0070 [-0.0564, +0.0436] | 0.8317 | 0.1057 | 0.1358 | -0.0195 | 1.0508 | 0.5248 | 0.5495 | 202 |
| all | 4 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8119 | 0.1014 | 0.1392 | 0.0029 | 0.9971 | 0.5149 | 0.5495 | 202 |
| all | 4 | dlinear-mvp | -0.0456 [-0.1044, +0.0060] | 0.7871 | 0.0968 | 0.1435 | -0.0518 | 1.0780 | 0.4802 | 0.5495 | 202 |
| all | 5 | w252-k3-l30 | -0.0261 [-0.0742, +0.0284] | 0.7723 | 0.1147 | 0.1521 | -0.0327 | 1.0561 | 0.5594 | 0.5743 | 202 |
| all | 5 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7723 | 0.1111 | 0.1524 | 0.0002 | 0.9882 | 0.5743 | 0.5743 | 202 |
| all | 5 | dlinear-mvp | -0.0458 [-0.1054, +0.0029] | 0.7822 | 0.1093 | 0.1589 | -0.0581 | 1.0675 | 0.4604 | 0.5743 | 202 |
| all | 6 | w252-k3-l30 | -0.0297 [-0.0905, +0.0236] | 0.8465 | 0.1327 | 0.1664 | -0.0528 | 1.0636 | 0.5495 | 0.5842 | 202 |
| all | 6 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8564 | 0.1274 | 0.1683 | -0.0041 | 0.9797 | 0.5446 | 0.5842 | 202 |
| all | 6 | dlinear-mvp | -0.0597 [-0.1269, -0.0010] | 0.7624 | 0.1220 | 0.1777 | -0.0917 | 1.0832 | 0.4851 | 0.5842 | 202 |
| all | 7 | w252-k3-l30 | -0.0320 [-0.0958, +0.0347] | 0.8465 | 0.1482 | 0.1774 | -0.0546 | 1.0525 | 0.5423 | 0.5990 | 202 |
| all | 7 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8515 | 0.1422 | 0.1805 | 0.0012 | 0.9724 | 0.5584 | 0.5990 | 202 |
| all | 7 | dlinear-mvp | -0.0498 [-0.1148, +0.0077] | 0.7822 | 0.1317 | 0.1859 | -0.1088 | 1.0804 | 0.4726 | 0.5990 | 202 |
| excl_roll | 1 | w252-k3-l30 | -0.0368 [-0.0865, -0.0013] | 0.8077 | 0.0524 | 0.0797 | -0.0909 | 1.1017 | 0.4420 | 0.5000 | 182 |
| excl_roll | 1 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8132 | 0.0498 | 0.0796 | 0.0052 | 1.0057 | 0.5028 | 0.5000 | 182 |
| excl_roll | 1 | dlinear-mvp | -0.0645 [-0.1540, -0.0055] | 0.8022 | 0.0529 | 0.0824 | -0.1027 | 1.1010 | 0.5028 | 0.5000 | 182 |
| excl_roll | 2 | w252-k3-l30 | +0.0054 [-0.0335, +0.0405] | 0.7791 | 0.0732 | 0.1062 | -0.0229 | 1.0121 | 0.5233 | 0.5233 | 172 |
| excl_roll | 2 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7500 | 0.0699 | 0.1068 | 0.0015 | 0.9999 | 0.5233 | 0.5233 | 172 |
| excl_roll | 2 | dlinear-mvp | -0.0268 [-0.0825, +0.0259] | 0.7674 | 0.0680 | 0.1097 | -0.0551 | 1.0443 | 0.5174 | 0.5233 | 172 |
| excl_roll | 3 | w252-k3-l30 | +0.0102 [-0.0273, +0.0492] | 0.7716 | 0.0848 | 0.1220 | 0.0043 | 1.0041 | 0.5432 | 0.5370 | 162 |
| excl_roll | 3 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7654 | 0.0817 | 0.1248 | 0.0016 | 0.9970 | 0.5494 | 0.5370 | 162 |
| excl_roll | 3 | dlinear-mvp | -0.0296 [-0.0865, +0.0184] | 0.7593 | 0.0830 | 0.1281 | 0.0050 | 1.0591 | 0.5556 | 0.5370 | 162 |
| excl_roll | 4 | w252-k3-l30 | -0.0050 [-0.0577, +0.0477] | 0.8355 | 0.1060 | 0.1349 | -0.0054 | 1.0278 | 0.5329 | 0.5197 | 152 |
| excl_roll | 4 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8158 | 0.1014 | 0.1354 | 0.0023 | 0.9985 | 0.5000 | 0.5197 | 152 |
| excl_roll | 4 | dlinear-mvp | -0.0328 [-0.0849, +0.0208] | 0.7961 | 0.0955 | 0.1393 | -0.0292 | 1.0411 | 0.5000 | 0.5197 | 152 |
| excl_roll | 5 | w252-k3-l30 | -0.0288 [-0.0879, +0.0345] | 0.7746 | 0.1155 | 0.1538 | -0.0087 | 1.0386 | 0.5775 | 0.5493 | 142 |
| excl_roll | 5 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.7746 | 0.1114 | 0.1490 | 0.0012 | 0.9906 | 0.5704 | 0.5493 | 142 |
| excl_roll | 5 | dlinear-mvp | -0.0328 [-0.0957, +0.0263] | 0.7817 | 0.1072 | 0.1579 | 0.0108 | 1.0123 | 0.5352 | 0.5493 | 142 |
| excl_roll | 6 | w252-k3-l30 | -0.0425 [-0.1079, +0.0228] | 0.8485 | 0.1339 | 0.1717 | -0.0207 | 1.0451 | 0.5606 | 0.5530 | 132 |
| excl_roll | 6 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8561 | 0.1279 | 0.1631 | -0.0046 | 0.9876 | 0.5227 | 0.5530 | 132 |
| excl_roll | 6 | dlinear-mvp | -0.0410 [-0.1238, +0.0354] | 0.7879 | 0.1189 | 0.1734 | -0.0299 | 1.0300 | 0.5606 | 0.5530 | 132 |
| excl_roll | 7 | w252-k3-l30 | -0.0244 [-0.0910, +0.0451] | 0.8689 | 0.1486 | 0.1769 | 0.0167 | 0.9908 | 0.6198 | 0.5656 | 122 |
| excl_roll | 7 | baseline-q252 | +0.0000 [+0.0000, +0.0000] | 0.8525 | 0.1427 | 0.1720 | -0.0008 | 0.9767 | 0.5630 | 0.5656 | 122 |
| excl_roll | 7 | dlinear-mvp | -0.0344 [-0.1177, +0.0433] | 0.7951 | 0.1269 | 0.1787 | -0.0639 | 1.0232 | 0.5537 | 0.5656 | 122 |

**Tóm tắt các chỉ số khác (sample = `all`, 28 nhóm, min / trung bình / max):**

| chỉ số | w252-k3-l30 | baseline-q252 | DLinear MVP |
|---|---|---|---|
| `coverage_80` | 0,682 / 0,775 / 0,866 | 0,731 / 0,785 / 0,876 | 0,757 / 0,820 / 0,874 |
| `brier_skill` | −0,114 / −0,056 / −0,006 | −0,012 / −0,000 / +0,007 | −0,194 / −0,096 / −0,001 |
| `mae_ratio_vs_naive` | 1,010 / 1,049 / 1,101 | 0,971 / 0,994 / 1,014 | 1,035 / 1,142 / 1,405 |

- **Hiệu chỉnh.** Khoảng 80% của cấu hình chọn hơi hẹp ở vàng và bạc (độ phủ 0,68–0,76) và gần
  danh nghĩa ở dầu, gần giống mốc. Như vậy Δg chỉ đổi độ rộng một chút.
- **Xác suất tăng.** `brier_skill` âm ở cả 28 nhóm `all`.
- **Trung vị.** `mae_ratio_vs_naive` > 1 ở cả 28 nhóm `all`: q50 sau khi dịch Δm kém hơn naive.
- **`sign_accuracy`** dao động quanh `up_rate` và thường thấp hơn cách luôn đoán tăng. Ví dụ Brent
  `excl_roll` h = 7: 0,566 trong khi `up_rate` = 0,721.

## 5. Tiêu chí cận dưới CI 95% > 0

| asset | sample | số h có ci_low > 0 | h | max ci_low |
|---|---|---|---|---|
| gold | all | 0 | - | -0.0565 |
| silver | all | 0 | - | -0.0724 |
| brent | all | 0 | - | -0.0333 |
| brent | excl_roll | 0 | - | -0.0782 |
| wti | all | 0 | - | -0.0364 |
| wti | excl_roll | 0 | - | -0.0273 |

**Không tài sản nào đạt** xét theo từng nhóm (tài sản × h): không nhóm nào có cận dưới CI > 0. Chưa
tính CI của `pinball_skill` trung bình 7 h (tiêu chí theo tài sản, chốt sau K3, §1 mục 4). Ước lượng
điểm của trung bình 7 h ở cấu hình chọn đều âm ở cả 6 cặp tài sản × sample (−0,010 đến −0,050). Không
có cơ sở thay `baseline-q252` cho bất kỳ tài sản nào.

## 6. DM test (cấu hình chọn vs baseline-252, `DM_GAP_POLICY` hiện hành)

| asset | sample | h | dm_stat | p_value | p_value_holm | status | undefined_reason |
|---|---|---|---|---|---|---|---|
| gold | all | 1 | 1.1262 | 0.2612 | 1.0000 | ok |  |
| gold | all | 2 | 1.2851 | 0.2000 | 1.0000 | ok |  |
| gold | all | 3 | 0.8580 | 0.3917 | 1.0000 | ok |  |
| gold | all | 4 | 0.9377 | 0.3493 | 1.0000 | ok |  |
| gold | all | 5 | 1.1704 | 0.2430 | 1.0000 | ok |  |
| gold | all | 6 | 1.0800 | 0.2812 | 1.0000 | ok |  |
| gold | all | 7 | 1.8304 | 0.0684 | 1.0000 | ok |  |
| silver | all | 1 | 2.2715 | 0.0240 | 0.6717 | ok |  |
| silver | all | 2 | 1.3715 | 0.1715 | 1.0000 | ok |  |
| silver | all | 3 | 0.5159 | 0.6064 | 1.0000 | ok |  |
| silver | all | 4 | 0.7921 | 0.4291 | 1.0000 | ok |  |
| silver | all | 5 | 0.6577 | 0.5113 | 1.0000 | ok |  |
| silver | all | 6 | 0.9822 | 0.3270 | 1.0000 | ok |  |
| silver | all | 7 | 1.2381 | 0.2169 | 1.0000 | ok |  |
| brent | all | 1 | -0.0243 | 0.9806 | 1.0000 | ok |  |
| brent | excl_roll | 1 | 0.2608 | 0.7945 | 1.0000 | ok |  |
| brent | all | 2 | -0.2905 | 0.7717 | 1.0000 | ok |  |
| brent | excl_roll | 2 |  |  |  | undefined | missing_paired_loss |
| brent | all | 3 | -0.4180 | 0.6764 | 1.0000 | ok |  |
| brent | excl_roll | 3 |  |  |  | undefined | missing_paired_loss |
| brent | all | 4 | -0.3833 | 0.7019 | 1.0000 | ok |  |
| brent | excl_roll | 4 |  |  |  | undefined | missing_paired_loss |
| brent | all | 5 | 0.6902 | 0.4909 | 1.0000 | ok |  |
| brent | excl_roll | 5 |  |  |  | undefined | missing_paired_loss |
| brent | all | 6 | 0.7000 | 0.4847 | 1.0000 | ok |  |
| brent | excl_roll | 6 |  |  |  | undefined | missing_paired_loss |
| brent | all | 7 | 0.8992 | 0.3696 | 1.0000 | ok |  |
| brent | excl_roll | 7 |  |  |  | undefined | missing_paired_loss |
| wti | all | 1 | 1.8855 | 0.0608 | 1.0000 | ok |  |
| wti | excl_roll | 1 | 1.4436 | 0.1506 | 1.0000 | ok |  |
| wti | all | 2 | 0.2465 | 0.8055 | 1.0000 | ok |  |
| wti | excl_roll | 2 |  |  |  | undefined | missing_paired_loss |
| wti | all | 3 | -0.0616 | 0.9510 | 1.0000 | ok |  |
| wti | excl_roll | 3 |  |  |  | undefined | missing_paired_loss |
| wti | all | 4 | 0.2412 | 0.8097 | 1.0000 | ok |  |
| wti | excl_roll | 4 |  |  |  | undefined | missing_paired_loss |
| wti | all | 5 | 0.8685 | 0.3862 | 1.0000 | ok |  |
| wti | excl_roll | 5 |  |  |  | undefined | missing_paired_loss |
| wti | all | 6 | 0.9625 | 0.3370 | 1.0000 | ok |  |
| wti | excl_roll | 6 |  |  |  | undefined | missing_paired_loss |
| wti | all | 7 | 0.9337 | 0.3516 | 1.0000 | ok |  |
| wti | excl_roll | 7 |  |  |  | undefined | missing_paired_loss |

- Không nhóm nào có ý nghĩa sau hiệu chỉnh Holm (p Holm nhỏ nhất 0,67, ở bạc h = 1). DM dương nghĩa
  là mô hình có loss lớn hơn mốc.
- Dầu `excl_roll` với h > 1 bị chặn (`missing_paired_loss`), vì sau khi bỏ cửa sổ roll chuỗi có phiên
  trống ở giữa (12 nhóm).
- Dầu `all` không bị chặn: tập chung năm 2019 bắt đầu sau đoạn 43 ngày gốc bị mất vì thiếu phiên
  5/12/2018, nên không có phiên trống ở giữa.

## 7. Quan sát về huấn luyện (chỉ ghi nhận, không chỉnh)

- Train loss của ensemble cuối cùng, tính lại trên toàn bộ train từ artifact (`w252-k3-l30`):
  - vàng 0,003562 so với mốc 0,003595;
  - bạc 0,005689 so với 0,005827;
  - Brent 0,008502 so với 0,009129;
  - WTI 0,008931 so với 0,009380.
  
  Mô hình học được một chút trong mẫu, nhưng phần cải thiện này không giữ được sang 2019.
- Từng seed của vàng kết thúc *trên* mốc trong mẫu (0,00362–0,00363). |Δm| trung bình bằng khoảng
  30% |y|, nên với lr 1e-3 và 20 epoch, trung vị dao động khá mạnh quanh mốc. Ensemble 3 seed giảm
  bớt dao động này: trên validation, trung bình 28 nhóm của từng seed là −4,0 đến −4,9 điểm %, còn
  ensemble là −2,8. Các con số này tính trên tập riêng của cấu hình, không phải tập chung.
- Theo kế hoạch, mọi thay đổi (lr nhỏ hơn, phạt Δm, early stopping) phải là thí nghiệm mới với kế
  hoạch mới, không dùng lại 2019 như một tập độc lập.

## 8. Hạn chế

- Cấu hình được chọn 1 trong 8 trên chính 2019 nên kết quả lạc quan. Dù vậy vẫn âm.
- Validation chỉ có một năm. 7 mức h dùng chung ngày tương lai nên không phải 7 bằng chứng độc lập.
- Backtest dùng bản clean mới nhất kèm quy tắc thời điểm công bố, không phải dữ liệu point-in-time
  (cùng hạn chế như `walk_forward`).
- Artifact ghi commit `59384e4` với cờ `commit_dirty = true`, vì code K3 chưa được commit lúc chạy.
  Mỗi artifact có `code_sha256` của các file đã dùng. Sau khi commit, có thể chạy lại để có
  provenance sạch: train và chia batch đều tất định theo seed.
- Không chạy tập test 2020 → nay. Không đọc dữ liệu sau 2019-12-31.

## 9. Việc tiếp theo (đề xuất, cần Khải quyết)

- Giữ `MODEL_VERSION=baseline-q252` cho cả 4 tài sản.
- Kế hoạch mục 6 yêu cầu viết ADR-0009 khi có kết quả. Đề xuất ADR-0009 ghi lại: CEEMDAN + DLinear
  tuyến tính trên lưới đã chốt không thắng mốc; cấu hình tham chiếu là `w252-k3-l30`; chưa có cấu
  hình nào cho production.
- Nếu tiếp tục, viết kế hoạch mới và chốt trước khi chạy, dùng tiêu chí theo tài sản đã chốt ở §1
  mục 4; chỉ thay đổi những gì có lý do từ phân tích train (ví dụ thang của Δm), không dựa vào 2019.

## 10. Thời gian chạy và file kết quả

- Tổng 231 s; tính cả khởi động Python là 3 phút 58 giây.
- Đọc 8 cache: 2,6 s.
- Train mỗi cấu hình (4 tài sản × 3 seed, gồm dựng đặc trưng và xuất artifact): 13,1–15,3 s. Không
  cấu hình nào gần giới hạn 10 phút.
- Đánh giá mỗi mô hình (detail + CI + DM): 10,7–12,3 s.

Kết quả chỉ lưu local, trong thư mục gitignore:

- `data/eval/k3/k3-val2019/`: `forecasts_val2019.parquet` (từng seed và ensemble), `accuracy.parquet`,
  `comparison.parquet`, `detail.parquet`, `summary.json`, `summary.md`.
- `data/models/<asset>/k3-ceemdan-dlinear-<cấu hình>-<hash>/`: 32 artifact, mỗi artifact gồm 3 seed,
  `integration_eligible = false`.
