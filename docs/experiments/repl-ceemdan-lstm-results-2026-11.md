# Minh họa CEEMDAN + LSTM theo ý tưởng của Cao et al. (2019): kết quả trên 2017–2018

- Ngày chạy: 3/11/2026; sửa tài liệu 4/11/2026 theo review của Long ở #83 (không chạy lại). Người viết: Khải (bản nháp do Claude Code soạn). Người duyệt: Long.
- Kế hoạch: `docs/experiments/ceemdan-lstm-replication-plan.md` (#75); quyết định của Khải ngày 3/11 cho bước 1 và bước 2.
- **Đây là minh họa, không phải thí nghiệm chọn mô hình.** Kết quả không đổi champion, không thêm challenger, không mở lại ADR-0012 (kế hoạch mục 0, 5).
- **Chỉ dùng dữ liệu ≤ 2018-12-31**; không đọc validation 2019 hay test 2020 → nay. Mọi siêu tham số đã đóng băng trước khi chạy. Chạy hai lần với cùng tham số: lần đầu trên code chưa commit, lần sau trên commit sạch để chứng minh nguồn gốc, kết quả trùng từng bit (mục 9). Không chỉnh gì sau khi xem số 2017–2018.
- Báo cáo chỉ có số tổng hợp, không có giá hay giá trị IMF thô.

## 1. Tóm tắt

| Câu hỏi (kế hoạch mục 1) | Kết quả |
|---|---|
| 1. Đo kiểu bài báo (sai số trên mức giá, một bước tới), CEEMDAN + LSTM có trông tốt hơn naive không? | **Có, nhưng chỉ với R-full trên vàng và bạc:** MAE trên mức giá khoảng một nửa naive (0,49 và 0,48 lần). Với dầu thì R-full thua naive. R-causal thua naive ở cả 4 tài sản (1,59–1,80 lần). |
| 2. Đo theo ADR-0008 trên log return, lợi thế đó còn không? | **Chỉ còn ở R-full vàng/bạc**, với `pinball_skill` +0,48/+0,52 và đúng chiều 84–86%. Mức "quá tốt" này là dấu hiệu rò rỉ mà skill `leakage-safe-forecasting` dặn phải kiểm tra trước (đúng chiều > 60%). Bản nhân quả R-causal thua naive và thua baseline-q252 ở cả 4 tài sản: `mae_ratio_vs_naive` 1,56–1,80, `pinball_skill` −0,58 đến −1,20, DM p < 1e-19. |
| 3. Hai giao thức tách chuỗi khác nhau thế nào? | Với kim loại, khác biệt rất lớn: R-full thắng naive khoảng 2 lần, R-causal thua naive khoảng 1,6–1,8 lần. Với dầu, cả hai đều thua naive. Thành phần tại cùng ngày gốc lệch nhiều giữa hai giao thức: tương quan IMF1 chỉ 0,33–0,40. **R-full và R-causal khác cả rò rỉ lẫn độ dài chuỗi đưa vào CEEMDAN, nên không quy toàn bộ chênh lệch cho rò rỉ** (mục 8). |

Thông điệp cho slide: cách đo trên mức giá cùng giao thức tách toàn chuỗi cho kết quả đẹp bất thường ở 2/4 tài sản (vàng, bạc). Khi chỉ dùng dữ liệu có thật tại t, như sản phẩm buộc phải làm, lợi thế đó mất hẳn. Slide giữ nguyên lưu ý: hai giao thức khác cả rò rỉ lẫn độ dài chuỗi đưa vào CEEMDAN, nên không quy toàn bộ chênh lệch cho rò rỉ.

## 2. Thiết lập

- **Dữ liệu:** bản clean `dt=2026-10-22`, cắt tại 2018-12-31 ngay khi đọc. Ngày lớn nhất đọc được: prices 2018-12-31, rejected 2018-11-19. Bốn tài sản: GLD, SLV, BZ=F, CL=F. Khởi động 2012–2013, train 2014–2016, đánh giá với ngày gốc 2017-01-03 → 2018-12-28, h = 1.
- **CEEMDAN:** đúng `w252` của K3: window 252, trials 100, epsilon 0,005, seed 42, keep_last 128, `cfg_hash` `4c3229533ae3` (khớp). Noise seed theo ngày cuối cửa sổ + tài sản. Gộp IMF1, IMF2, IMF3 và phần còn lại (IMF4 trở đi + residue).
  - R-causal: tách lại 5.026 cửa sổ từ dữ liệu ≤ 2018, mất 27 phút với 8 tiến trình.
  - R-full: tách một lần trên toàn chuỗi 2012–2018 của từng tài sản (1.740–1.760 dòng).
- **LSTM (đóng băng):** 1 lớp, 32 đơn vị, đầu ra Linear, cửa sổ 20, MSE trên giá trị chuẩn hóa. Adam lr 1e-3, batch 64, tối đa 200 epoch, patience 20, khôi phục trọng số tốt nhất. Seed 0, 1, 2.
  - 108 mô hình: R-full và R-causal mỗi bản 4 thành phần × 4 tài sản, R-raw 1 × 4 tài sản, nhân 3 seed.
- **Chia train theo thời gian:** fit / early stopping / hiệu chỉnh = 70/15/15 theo dòng giá. Ranh giới tính một lần mỗi tài sản, dùng chung cho 3 biến thể và 3 seed. Bỏ mẫu có t + 1 ở đoạn sau.
- **Chuẩn hóa:** z-score cho mỗi tài sản × biến thể × thành phần, fit trên mọi giá trị đầu vào của đoạn fit; target dùng cùng scaler.
- **Dự báo:** P̂(t+1) là tổng các thành phần dự báo, r̂ = log(P̂ / P(t)).
  - Phân vị: r̂ cộng phân vị thực nghiệm của phần dư return trên đoạn hiệu chỉnh.
  - Không có dự báo P̂ ≤ 0 nào (0/108 mô hình, mọi đoạn).
- **So sánh:** naive (return = 0, tức giá mai bằng giá hôm nay) và baseline-q252 (nhân quả, h = 1), tính trên cùng tập ngày gốc với mô hình.
- **Thiết bị:** máy chỉ có torch bản CPU (2.14.1+cpu, `torch.cuda.is_available() = False`). Mọi mô hình chạy `--device cpu`, 1 luồng, `torch.use_deterministic_algorithms(True)`; không cài torch CUDA, không trộn thiết bị. Chi tiết trong `env.txt`.

## 3. Số mẫu

| Tài sản | fit | early stopping | hiệu chỉnh | đánh giá |
|---|---|---|---|---|
| gold | 528 | 113 | 112 | 501 |
| silver | 528 | 113 | 112 | 501 |
| brent | 523 | 112 | 110 | 500 |
| wti | 527 | 112 | 110 | 500 |

Ngày gốc bị loại: mỗi ngày tính một lý do, theo thứ tự ưu tiên ranh giới → sau CUTOFF → thiếu target.

| Tài sản | Ranh giới đoạn | t + 1 sau CUTOFF (2018-12-31) | t + 1 không có giá hợp lệ |
|---|---|---|---|
| gold | 3 | 1 | 0 |
| silver | 3 | 1 | 0 |
| brent | 3 | 1 | 5 |
| wti | 3 | 1 | 3 |

- Không có ngày gốc nào bị loại vì thiếu cửa sổ R-causal hay vì baseline-q252 không hợp lệ.
- Ranh giới đoạn (gold/silver; dầu lệch 1–2 phiên):
  - fit 2014-01-02 → 2016-02-08;
  - early stopping 2016-02-09 → 2016-07-21;
  - hiệu chỉnh 2016-07-22 → 2016-12-30.

**Cửa sổ R-causal chỉ có 3 IMF** (khi đó thành phần "rest" chỉ còn residue): gold 2, silver 0, brent 21, wti 3 trên 1.254–1.258 cửa sổ. Tất cả đều nằm trong tập mẫu được dùng. Không có cửa sổ nào ít hơn 3 IMF.

## 4. Kiểm tra trước khi đọc kết quả

- **Kiểm chéo cache ADR-0007** (chỉ đọc các tháng ≤ 2018-12; không dùng cache cho mô hình):
  - 5.026/5.026 cửa sổ chung;
  - 0 cửa sổ lệch `price_hash`, 0 lệch `n_imf`;
  - 20 giá trị cuối của 4 thành phần **trùng từng bit** (sai lệch lớn nhất 0).
  - Như vậy bản tách lại khớp hoàn toàn cache cũ ở mọi cửa sổ ≤ 2018.
- **Smoke** (gold × R-causal × IMF1 × seed 0, chạy hai lần trên CPU): trọng số và dự báo trùng từng bit; mỗi lần 3,7 s và 1,2 s (lần đầu có chi phí khởi động); best epoch 12.
- **Chạy đủ:** 108 mô hình trong 6,1 phút.
- **Test** (`tests/test_repl_ceemdan_lstm.py`, dữ liệu tổng hợp, CPU):
  - target không vượt ranh giới đoạn;
  - scaler chỉ thấy đoạn fit;
  - phân vị chỉ phụ thuộc phần dư đoạn hiệu chỉnh;
  - cùng seed cho trọng số trùng từng bit;
  - P̂ ≤ 0 được đếm là lỗi, không bị thay;
  - bất biến theo tiền tố của R-causal;
  - manifest hoặc digest bản tách thiếu, sai, hay một parquet bị sửa một byte thì báo lỗi;
  - lệnh git lỗi thì `dirty` là `None`, không báo nhầm là sạch.

## 5. Chỉ số theo ADR-0008 (log return h = 1, ngày gốc 2017–2018)

Mỗi ô ghi trung bình [min; max] qua 3 seed. Quy ước:
- `mae_ratio_vs_naive` < 1 là tốt hơn naive.
- `pinball_skill` > 0 là tốt hơn baseline-q252.
- Ngoặc sau `sign_accuracy` là `up_rate`; ngoặc sau `coverage_80` là coverage của baseline-q252.
- DM so với naive trên sai số tuyệt đối return, HAC lag 0, HLN: stat âm là mô hình có sai số nhỏ hơn. Cột p là giá trị lớn nhất trong 3 seed.

| Tài sản | Biến thể | n | mae_ratio_vs_naive | sign_accuracy (up_rate) | pinball_skill | coverage_80 (baseline) | DM: stat; p lớn nhất |
|---|---|---|---|---|---|---|---|
| gold | R-raw | 501 | 0,99 [0,98; 1,00] | 55,2% [54,1; 56,1] (53,3%) | −0,01 [−0,01; −0,01] | 84,6% [83,8; 85,4] (82,6%) | −0,9 [−1,3; −0,2]; 0,84 |
| gold | R-full | 501 | 0,49 [0,48; 0,52] | 83,6% [82,7; 84,5] (53,3%) | +0,48 [0,47; 0,48] | 90,2% [88,8; 91,0] (82,6%) | −13,2 [−13,6; −12,4]; 8e-31 |
| gold | R-causal | 501 | 1,80 [1,76; 1,82] | 51,0% [49,9; 51,5] (53,3%) | −1,20 [−1,27; −1,11] | 77,4% [75,2; 80,0] (82,6%) | +10,1 [9,5; 10,6]; 8e-20 |
| silver | R-raw | 501 | 1,04 [1,04; 1,05] | 54,2% [52,7; 54,9] (48,3%) | −0,05 [−0,07; −0,04] | 90,2% [89,4; 91,2] (81,8%) | +2,1 [1,8; 2,4]; 0,079 |
| silver | R-full | 501 | 0,48 [0,47; 0,49] | 85,5% [84,8; 85,9] (48,3%) | +0,52 [0,51; 0,52] | 93,4% [92,2; 94,6] (81,8%) | −14,3 [−14,6; −13,8]; 1e-36 |
| silver | R-causal | 501 | 1,63 [1,43; 1,88] | 50,8% [49,8; 52,0] (48,3%) | −0,76 [−1,28; −0,41] | 81,1% [71,1; 86,6] (81,8%) | +12,3 [10,3; 14,9]; 2e-22 |
| brent | R-raw | 500 | 2,17 [1,98; 2,43] | 49,4% [47,4; 50,8] (54,6%) | −0,95 [−1,19; −0,80] | 90,1% [85,0; 94,0] (81,2%) | +16,7 [15,1; 19,3]; 1e-42 |
| brent | R-full | 500 | 1,75 [1,32; 2,03] | 57,2% [54,4; 62,3] (54,6%) | −0,35 [−0,51; −0,20] | 96,0% [95,2; 96,4] (81,2%) | +10,8 [5,4; 14,0]; 8e-08 |
| brent | R-causal | 500 | 1,56 [1,47; 1,60] | 48,6% [47,2; 49,6] (54,6%) | −0,58 [−0,62; −0,51] | 90,2% [85,4; 92,8] (81,2%) | +10,6 [10,0; 11,2]; 9e-22 |
| wti | R-raw | 500 | 1,32 [1,20; 1,56] | 53,1% [52,1; 53,5] (56,0%) | −0,36 [−0,62; −0,23] | 92,3% [91,0; 93,0] (82,2%) | +7,6 [6,0; 10,6]; 3e-09 |
| wti | R-full | 500 | 1,73 [1,42; 1,89] | 54,4% [52,5; 58,1] (56,0%) | −0,37 [−0,48; −0,24] | 94,9% [94,2; 95,4] (82,2%) | +11,4 [7,5; 13,5]; 3e-13 |
| wti | R-causal | 500 | 1,67 [1,64; 1,72] | 47,0% [45,7; 48,1] (56,0%) | −0,60 [−0,67; −0,53] | 89,3% [88,2; 90,4] (82,2%) | +11,9 [11,2; 12,9]; 6e-26 |

Đọc bảng:
- **R-causal** (giao thức sản phẩm buộc phải dùng) thua naive và thua baseline-q252 ở cả 4 tài sản, mọi seed.
  - Đúng chiều 47–51%, không hơn việc luôn đoán chiều chiếm đa số (max(`up_rate`, 1 − `up_rate`) = 52–56%).
- **R-raw** xấp xỉ naive với vàng và bạc (gold không khác naive có ý nghĩa, p = 0,84), thua rõ với dầu.
- **R-full** chỉ "thắng" với vàng và bạc, ở mức khó tin với return một ngày (đúng chiều 84–86%). Với dầu, R-full cũng thua naive.
- Khoảng 80% của mọi biến thể dựa trên phần dư nửa sau 2016. Phần lớn rộng hơn danh nghĩa (coverage 84–96%), trừ R-causal của vàng (77%) và bạc (81%). Các khoảng này chỉ dùng để tính `pinball_skill`, không tinh chỉnh thêm.

## 6. Chỉ số kiểu bài báo (chỉ để minh họa, ADR-0008 không dùng)

Sai số trên **mức giá** một bước tới, chia cho cùng chỉ số của naive (giá mai = giá hôm nay); < 1 là "tốt hơn naive". MAPE ghi theo %. Mỗi ô ghi trung bình [min; max] qua 3 seed. MAPE chỉ tính trên cặp có giá thực > 0: không cặp nào bị loại.

Bộ chỉ số này không khẳng định là đúng bộ của Cao et al. (kế hoạch mục 0, 4).

| Tài sản | Biến thể | MAE / naive | RMSE / naive | MAPE mô hình | MAPE naive |
|---|---|---|---|---|---|
| gold | R-raw | 0,99 [0,98; 1,00] | 1,00 [1,00; 1,01] | 0,47 [0,47; 0,48] | 0,48 |
| gold | R-full | 0,49 [0,47; 0,52] | 0,48 [0,47; 0,51] | 0,24 [0,23; 0,25] | 0,48 |
| gold | R-causal | 1,80 [1,76; 1,82] | 2,00 [1,93; 2,08] | 0,86 [0,84; 0,87] | 0,48 |
| silver | R-raw | 1,04 [1,03; 1,05] | 1,04 [1,03; 1,05] | 0,82 [0,82; 0,83] | 0,79 |
| silver | R-full | 0,48 [0,47; 0,49] | 0,47 [0,46; 0,48] | 0,38 [0,37; 0,39] | 0,79 |
| silver | R-causal | 1,62 [1,44; 1,87] | 1,56 [1,40; 1,78] | 1,28 [1,13; 1,48] | 0,79 |
| brent | R-raw | 2,21 [2,03; 2,47] | 1,95 [1,83; 2,12] | 2,66 [2,42; 2,94] | 1,23 |
| brent | R-full | 1,80 [1,39; 2,10] | 1,57 [1,27; 1,82] | 2,13 [1,61; 2,46] | 1,23 |
| brent | R-causal | 1,59 [1,50; 1,65] | 1,51 [1,41; 1,57] | 1,92 [1,81; 1,98] | 1,23 |
| wti | R-raw | 1,33 [1,20; 1,58] | 1,28 [1,16; 1,52] | 1,74 [1,58; 2,06] | 1,32 |
| wti | R-full | 1,79 [1,48; 1,94] | 1,60 [1,36; 1,74] | 2,25 [1,86; 2,46] | 1,32 |
| wti | R-causal | 1,70 [1,67; 1,75] | 1,65 [1,63; 1,67] | 2,19 [2,15; 2,26] | 1,32 |

MAPE của naive chỉ khoảng 0,5–1,3%, tức "độ chính xác 99%" mà không cần mô hình nào. Đây là lý do ADR-0008 cấm báo cáo sai số trên mức giá. Slide nên đặt cột naive ngay cạnh cột mô hình.

## 7. Chẩn đoán cơ chế: thành phần tại ngày gốc t, R-full so với R-causal

So giá trị của từng thành phần tại t giữa hai giao thức:
- R-full: giá trị tại t của bản tách toàn chuỗi.
- R-causal: điểm cuối của cửa sổ kết thúc tại t.

Sai lệch tuyệt đối trung bình được chia cho giá trung bình của tập để không lộ mức giá.

| Tài sản | Thành phần | Tương quan (eval) | Sai lệch / giá (eval) | Tương quan (fit) | Sai lệch / giá (fit) |
|---|---|---|---|---|---|
| gold | imf1 | 0,38 | 0,27% | 0,40 | 0,42% |
| gold | imf2 | 0,22 | 0,50% | 0,17 | 0,58% |
| gold | imf3 | 0,15 | 1,18% | 0,16 | 1,42% |
| gold | rest | 0,89 | 1,35% | 0,94 | 1,68% |
| silver | imf1 | 0,33 | 0,50% | 0,44 | 0,63% |
| silver | imf2 | 0,16 | 0,93% | 0,20 | 0,90% |
| silver | imf3 | 0,20 | 1,22% | 0,16 | 2,71% |
| silver | rest | 0,95 | 1,60% | 0,95 | 3,25% |
| brent | imf1 | 0,40 | 0,73% | 0,40 | 0,75% |
| brent | imf2 | 0,12 | 1,08% | 0,29 | 1,22% |
| brent | imf3 | 0,18 | 2,22% | 0,13 | 1,98% |
| brent | rest | 0,97 | 2,58% | 1,00 | 2,54% |
| wti | imf1 | 0,37 | 0,77% | 0,47 | 0,82% |
| wti | imf2 | 0,26 | 1,01% | 0,33 | 1,37% |
| wti | imf3 | 0,22 | 2,88% | 0,07 | 2,63% |
| wti | rest | 0,95 | 3,33% | 0,99 | 3,12% |

- Ba IMF cao tần tại cùng ngày gốc gần như là hai đại lượng khác nhau giữa hai giao thức (tương quan 0,07–0,47).
- Sai lệch của IMF1 (0,3–0,8% giá) cùng cỡ với biến động giá một ngày.
- Lý do: trong R-full, giá trị tại t được spline nội suy bằng cả các điểm sau t. Trong R-causal, t là mép phải của cửa sổ, nơi CEEMDAN không có điểm phía sau (ADR-0001).
- Đây chỉ là minh họa cơ chế; bảng không đo riêng phần đóng góp của rò rỉ.

## 8. Giới hạn

1. **R-full cố ý tách toàn chuỗi 2012–2018 trước khi chia tập**, nên mọi giá trị thành phần (cả đầu vào lẫn target) chứa thông tin sau ngày gốc. 2017–2018 không được dùng để fit, chuẩn hóa, early stopping hay hiệu chỉnh phân vị, nhưng thông tin của giai đoạn này vẫn đi vào đầu vào và target của R-full qua bước tách.
2. **Câu 3 chỉ so sánh hai giao thức, không quy toàn bộ chênh lệch cho rò rỉ.** R-full và R-causal khác cả việc dùng dữ liệu tương lai lẫn độ dài lịch sử đưa vào CEEMDAN (toàn chuỗi khoảng 1.750 dòng so với 252 dòng). Muốn tách riêng phần rò rỉ thì cần thêm đối chứng nhân quả với cửa sổ mở rộng; ngoài phạm vi (kế hoạch mục 1).
3. **Số mô hình không bằng nhau:** R-raw có 1 LSTM mỗi tài sản, R-full và R-causal có 4. Chênh lệch giữa R-raw và hai bản có tách gồm cả tác dụng của việc có nhiều mô hình hơn (kế hoạch mục 3.4).
4. **Cửa sổ chỉ có 3 IMF** (gold 2, wti 3, brent 21): ở các cửa sổ này thành phần "rest" chỉ còn residue, nên ý nghĩa của nó không đồng nhất giữa các cửa sổ (như K3).
5. **Ngân sách epoch đóng băng:**
   - 13/48 mô hình R-full và 8/12 mô hình R-raw chạy hết 200 epoch mà chưa dừng sớm (best epoch trung vị: R-raw 189, R-full 65,5, R-causal 31,5).
   - Theo kế hoạch mục 3.2, không thử thêm epoch hay giá trị khác.
6. **R-full của dầu thua naive dù có rò rỉ.** Vì vậy kết luận là R-full **"đẹp bất thường ở 2/4 tài sản"** (vàng, bạc), không phải "luôn thắng". Báo cáo không phân tích nguyên nhân và không chạy thêm thí nghiệm (kế hoạch mục 5).
7. Ba seed chỉ cho thấy độ dao động, không chứng minh tính ổn định. Kết quả chỉ trên 2017–2018 với h = 1.
8. Chạy trên CPU (máy không có torch CUDA). Kết quả tất định trên máy này. Chưa so với chạy trên GPU hay nền tảng khác.
9. **Cấu hình CEEMDAN không độc lập hoàn toàn với 2019.** Cấu hình `w252` K3 (window 252, K = 3) kế thừa từ K3, mà K3 đã chọn cấu hình bằng validation 2019 (ADR-0009). Lần minh họa này không đọc dòng nào của 2019, nhưng việc chọn cấu hình không độc lập hoàn toàn với 2019.
10. **Phạm vi của "chỉ dùng dữ liệu ≤ 2018":** SHA-256 băm cả file clean (gồm dòng sau 2018); pyarrow có thể giải mã cả row group trước khi lọc, nhưng code không nhận dòng nào sau 2018-12-31.

## 9. Dòng thời gian và đăng ký trước

Mọi mốc trong ngày 3/11/2026, giờ UTC.

| Mốc | Sự kiện | Nguồn |
|---|---|---|
| 09:59 | #75 merge (kế hoạch: biến thể, cấu hình LSTM, seed, cách chia, chỉ số), trước mọi commit code | `mergedAt` của #75, `42d9bb4` |
| 10:25 | `d7d7bb1`: `config.py` với `LSTM`, `SEEDS`, `SPLIT`, `SEQ_LEN`, trước khi train | `git log` |
| 10:25 | `507a6d8`: code tách CEEMDAN | `git log` |
| 10:29–10:56 | Tách CEEMDAN đầy đủ trên `507a6d8` (`dirty: false`) | `manifest.json`, thời gian sửa của 8 file |
| 11:12–11:18 | Lần chạy đầu: train và đo trên code chưa commit (`dirty: true`), lần đầu thấy số 2017–2018 | `results-dirty/summary.json`, `env.txt` (có trên S3, mục 10) |
| 11:25 | `1854f5b`–`fff4f32`: commit code đó nguyên trạng | `git log` |
| 11:27–11:31 | Chạy lại trên `fff4f32` sạch (`dirty: false`) | `results/summary.json`, `env.txt` |

- **Khóa cấu hình:** tham số đã khóa ở #75 và `d7d7bb1`, trước lần đọc kết quả đầu tiên. `git diff d7d7bb1 fff4f32 -- src/experiments/repl_ceemdan_lstm/config.py` rỗng, nghĩa là cấu hình không đổi sau khi xem kết quả.
- **Hai lần chạy:** `dataset.py`, `model.py`, `evaluate.py` được commit sau khi đã có số của lần đầu. Vì vậy bằng chứng rằng không có chỉnh sửa là kết quả từ code đã commit trùng từng bit với lần đầu:
  - diagnostics, metrics, predictions, price_metrics có cùng SHA-256;
  - `train_log` chỉ khác cột `seconds`;
  - `env.txt` chỉ khác `date_utc`.
- **Mục đích và phạm vi chạy lại:** chứng minh kết quả đến đúng từ code đã commit. Không đổi tham số nào, không tách lại CEEMDAN.
- **Lịch chạy:** chạy sớm hơn lịch §7 của kế hoạch (9–15/11); đây là lệch so với lịch đã ghi. Lý do: #75 đã merge ngày 3/11, việc này không phụ thuộc ai, và cần kết quả cho bản nháp báo cáo cuối. Không dùng dữ liệu sau 2018.
- **Sửa ngày 4/11 (review #83):** chỉ thêm kiểm tra nguồn gốc (`check_manifest`, `--record-digests`, `git_info`), test và tài liệu. Không đổi code xử lý dữ liệu, mô hình hay chỉ số; không chạy lại; số trong báo cáo vẫn là của `fff4f32`.
- **`dirty` đã ghi:** `manifest.json` và `summary.json` hiện có được tạo trước khi có trường `git_status`. Cả hai có `commit` khác rỗng, tức lệnh git chạy được lúc đó.

## 10. Tái lập

- Bước 1 (tách CEEMDAN): commit `507a6d8`. Manifest `data/eval/repl-ceemdan-lstm/manifest.json`: `cfg_hash` `4c3229533ae3`; SHA-256 bản clean khớp; R-causal gold 1.258, silver 1.258, brent 1.254, wti 1.256 cửa sổ; R-full đủ 4 tài sản.
- Bước 2 (train và đo): commit `fff4f328950ed5b66b31879de451228620b2a96c`.
  - Lần chạy đầu dùng `507a6d8` cộng các thay đổi chưa commit (`dirty: true`).
  - Chạy lại trên commit sạch ngày 3/11 (`dirty: false`): kết quả trùng từng bit với lần chạy đầu (diagnostics, metrics, predictions, price_metrics); `train_log` chỉ khác cột thời gian chạy.
- Lệnh:
  ```
  python scripts/repl_ceemdan_decompose.py --processes 8
  python scripts/repl_ceemdan_train.py --device cpu --smoke
  python scripts/repl_ceemdan_train.py --device cpu
  ```
- Kết quả trong `data/eval/repl-ceemdan-lstm/results/` (không commit; đây là bản của lần chạy sạch, kết quả lần chạy đầu nằm riêng ở `results-dirty/`). SHA-256 lấy từ `results/summary.json` của lần chạy sạch trên `fff4f32`:

| File | SHA-256 |
|---|---|
| predictions.parquet | `e0c9bac4b22aa16f8f6bbaa7df4f4191fa0020ece18a31dca835ecf002464f58` |
| metrics.parquet | `7d6b0efcf61878056e7db00727d783658ad5626b3601aea61cb69d875251a210` |
| price_metrics.parquet | `5db7409b62b87ba8c0edaca849b9d79106a6ed8145f55cac69fcecaabbb9aacf` |
| train_log.parquet | `45c3f399f6957175801e01beb9459eee3c23351d20418640fe17776a5a43cb5f` |
| diagnostics.parquet | `a5e613ee3601ac7eac2b1fb46de64a94f4e3f50e7aaae56102c4ebe8bf756297` |
| env.txt | `4367e7dd2eb5843f15f18500c716d011ed3ba4b91b69fc9a0218c07679d5e2a2` |

  So với lần chạy đầu: diagnostics, metrics, predictions, price_metrics trùng từng bit; train_log khác cột `seconds`, env.txt khác dòng `date_utc`.

- Bản tách CEEMDAN: SHA-256 của 8 file, lấy từ `artifacts_sha256.json`, **ghi sau khi chạy, 4/11** (`recorded_at` 2026-11-04T04:02:30Z, `recorded_after_run: true`, bằng `--record-digests`, không tách lại). Bản tách được tạo ngày 3/11, thời gian sửa của 8 file là 10:35–10:56 UTC, trước lần train đầu. Digest ghi sau chỉ khóa nội dung file từ 4/11 trở đi; đối chiếu độc lập là bản trên S3 (dưới đây).

| File | SHA-256 |
|---|---|
| r_causal_gold.parquet | `d5bef80d99f79b98bdbb00e7f7f919f4690eb4c0b01592a12b3e99dd42ac0ea2` |
| r_causal_silver.parquet | `4762a05a0d65d526809e8247daa76940c1273bb456f0003b2473e398e97d8832` |
| r_causal_brent.parquet | `1d3d6fa8050bdba7167fb5871cb432dc2cf1000584e4ac6c64e862e11f869c98` |
| r_causal_wti.parquet | `408bb86e1a91d674a25fc7bb821e73a266090ca2e830805a2aea283b480f564b` |
| r_full_gold.parquet | `2f329b0d4cb6486b35632da490c46cc75e13a019d9ceaa8906a1d9d21e6ab006` |
| r_full_silver.parquet | `faa3d35dc5772b017b1f936d68fe49097f006bfa68b06e38d0a82a07f88475f4` |
| r_full_brent.parquet | `1819eb4fd2e0c25e7996c31535c4690ec16c885cd8711baa241c06c1fdcc767d` |
| r_full_wti.parquet | `d391e7a9de473a3696031dac5e17eb426927b82d4dfd3a8c9cc9f94c99eff04f` |

- `check_manifest()` trên dữ liệu thật (4/11, chỉ băm file, không train): không lỗi.
- Trên S3: `s3://cpaws-dev-lake/eval/repl-ceemdan-lstm/`, gồm `manifest.json`, `artifacts_sha256.json`, 8 file bản tách, `results/` (lần chạy sạch), `results-dirty/` (lần chạy đầu) và `probe/`.
  - Đối chiếu SHA-256 với S3: 4/11/2026 (Khải): tải toàn bộ `s3://cpaws-dev-lake/eval/repl-ceemdan-lstm/` về và so SHA-256 với bản local: 34/34 file khớp (`manifest.json`, `artifacts_sha256.json`, 8 file bản tách, 7 file `results/`, 8 file `results-dirty/`, 9 file `probe/`). `probe/` là bản probe `--limit 20` của bước 1, không dùng cho mô hình.

- `env.txt`:
  - torch 2.14.1+cpu, `torch.version.cuda = None`, `cuda.is_available() = False`; thiết bị cpu, 1 luồng; deterministic bật.
  - Máy có GPU RTX 4060 Laptop, driver 566.24, nhưng không dùng vì torch là bản CPU.
- Mục 8 "Thông tin lần chạy" của kế hoạch đã được điền sau khi chạy, theo manifest (CLEAN_DT, SHA-256 bản clean, `cfg_hash`, thời gian tách lại, kiểm chéo cache, commit).
