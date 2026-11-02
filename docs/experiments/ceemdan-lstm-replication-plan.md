# Minh họa CEEMDAN + LSTM theo ý tưởng của Cao et al. (2019) cho buổi bảo vệ (bản nháp, làm sau demo 8/11)

- Ngày: 31/10/2026; sửa 2/11/2026 theo review của Long ở #75
- Người viết: Khải (bản nháp do Claude soạn); người duyệt: Long
- Trạng thái: **Bản nháp, chưa chạy.** Long approve, merge, rồi mới viết code. Sau khi chốt, thay đổi ghi thành mục mới có ngày ở mục 9, trước khi chạy.
- Khải chốt 31/10: hiện sai số trên mức giá trên slide (chỉ để minh họa); chạy đủ 4 tài sản; chạy trên máy Khải; code ở `src/experiments/`; không chờ toàn văn bài báo (mục 0).
- Bài tham khảo: Cao, Li, Li (2019), *Financial time series forecasting model based on CEEMDAN and LSTM*, Physica A 519, 127–139, doi 10.1016/j.physa.2018.11.061.

## 0. Phạm vi: không phải thí nghiệm chọn mô hình

- Mục đích duy nhất: giải thích ở buổi bảo vệ vì sao kết quả của dòng bài "CEEMDAN + mạng nơ-ron" không chuyển được sang sản phẩm.
- Không mở lại ADR-0012: không đổi champion, không thêm challenger, không đưa mô hình nào vào Lambda.
- **Chỉ dùng dữ liệu ≤ 2018-12-31.** Không đọc validation 2019, không đọc test 2020 → nay; vì vậy không tính là lần nhìn thứ 5 vào 2019.
- **Đây là minh họa ý tưởng CEEMDAN + LSTM theo Cao et al. (2019), không phải tái lập đúng giao thức hay bộ chỉ số của tác giả.** Nhóm chưa đọc toàn văn; thiết kế theo phần tóm tắt (một bước tới, LSTM cho từng thành phần rồi cộng lại). Báo cáo và slide không khẳng định bài cụ thể này có rò rỉ, chỉ nói "theo cách làm phổ biến của dòng bài này". Nếu có toàn văn trước 9/11 thì ghi khác biệt vào mục 9, không đổi tên gọi.

## 1. Câu hỏi

1. Khi đo kiểu bài báo (sai số trên mức giá, một bước tới), CEEMDAN + LSTM có trông tốt hơn "giá mai bằng giá hôm nay" không?
2. Khi đo theo ADR-0008 trên log return, lợi thế đó còn không?
3. Hai **giao thức** tách chuỗi cho kết quả khác nhau thế nào: tách một lần trên toàn chuỗi 2012–2018 (R-full) so với tách theo cửa sổ 252 phiên nhân quả (R-causal)?

Câu 3 so sánh hai giao thức, **không quy chênh lệch hoàn toàn cho rò rỉ**: hai bản khác cả việc dùng dữ liệu tương lai lẫn độ dài lịch sử đưa vào CEEMDAN (toàn chuỗi so với 252 phiên). Muốn tách riêng phần rò rỉ thì cần thêm đối chứng nhân quả cửa sổ mở rộng cùng độ dài lịch sử; không làm trong phạm vi này (chi phí CEEMDAN lớn, thời gian đến 15/11). Phần chẩn đoán ở mục 4 chỉ minh họa cơ chế R-full nhìn thấy dữ liệu sau ngày gốc.

## 2. Dữ liệu

- Bản clean như K3/K4 (`configs/k3_grid.CLEAN_DT`), cắt tại 2018-12-31 ngay khi nạp; `assert` ngày lớn nhất ≤ 2018-12-31.
- 2012–2013 khởi động (như ADR-0008), train 2014–2016, đánh giá 2017-01-01 → 2018-12-31; 4 tài sản (GLD, SLV, BZ=F, CL=F), h = 1 (một bước tới).
- Không forward-fill; cặp phiên vắt qua phiên thiếu thì bỏ, như K4.

## 3. Biến thể (chốt)

| Mã | Tách chuỗi | Mô hình | Vai trò |
|---|---|---|---|
| R-full | CEEMDAN một lần trên toàn chuỗi 2012–2018 rồi mới chia train/đánh giá | LSTM cho từng thành phần, cộng lại | Giao thức thường gặp trong các bài này |
| R-causal | CEEMDAN theo cửa sổ 252 phiên kết thúc tại ngày gốc (ADR-0001, ADR-0007) | LSTM cho từng thành phần, cộng lại | Giao thức sản phẩm buộc phải dùng |
| R-raw | Không tách | LSTM trên chuỗi giá gốc | Đối chứng không tách |
| naive | — | giá mai = giá hôm nay (return = 0) | Mốc của bài toán mức giá |
| baseline-q252 | — | Phân vị 252 phiên | Mốc của sản phẩm (chỉ cho `pinball_skill`) |

### 3.1 Thành phần, đầu vào và target (chốt)

- Số thành phần giống K3 (`w252-k3`): IMF1, IMF2, IMF3 và phần còn lại (IMF4 trở đi + residue) gộp làm 1, tức 4 thành phần; R-full gộp theo đúng cách đó.
- **R-causal**, tại ngày gốc t: tách cửa sổ giá [t − 251, t]. Đầu vào thành phần k là 20 giá trị cuối của thành phần k **trong cửa sổ kết thúc tại t**. Target của thành phần k là giá trị cuối của thành phần k trong cửa sổ kết thúc tại t + 1 (chỉ biết sau phiên t + 1, dùng làm nhãn train; khi đánh giá chỉ dùng đầu vào tại t).
- **R-full:** đầu vào thành phần k là giá trị tại t − 19 … t của bản tách toàn chuỗi; target là giá trị tại t + 1 của cùng bản tách.
- **R-raw:** đầu vào là giá tại t − 19 … t; target là giá tại t + 1.
- **Dự báo:** giá dự báo P̂(t+1) = tổng 4 thành phần dự báo (R-raw: dự báo trực tiếp). Return dự báo r̂ = log(P̂(t+1) / P(t)); nếu P̂(t+1) ≤ 0 thì dòng đó ghi là lỗi dự báo, đếm và báo cáo, không thay giá trị.

### 3.2 Huấn luyện (chốt, không tinh chỉnh theo kết quả đánh giá)

- LSTM: 1 lớp, 32 đơn vị, cửa sổ 20, Adam, MSE trên giá trị chuẩn hóa.
- **Chuẩn hóa:** mỗi tài sản × biến thể × thành phần một scaler (z-score), fit chỉ trên phần fit của train (2014-01-01 → hết 80% đầu theo thời gian của train).
- **Early stopping:** trên 20% cuối của train theo thời gian (đoạn hiệu chỉnh), patience cố định. Không dùng dữ liệu 2017–2018 trong early stopping, chuẩn hóa hay dựng đặc trưng.
- **Seed:** chạy 3 seed cố định (0, 1, 2) cho mọi LSTM; báo cáo trung bình và khoảng min–max qua 3 seed. Vẫn chỉ là minh họa, không chứng minh tính ổn định.
- **Phân vị cho `pinball_skill`:** gắn phân vị thực nghiệm của phần dư return trên đoạn hiệu chỉnh (ngoài mẫu đối với LSTM đã fit) vào r̂. Không dùng phần dư trong mẫu fit.

### 3.3 Nguồn cache CEEMDAN cho R-causal (chốt)

Cache ADR-0007 có cả 2019; lọc theo ngày là chưa đủ, phải chứng minh từng cửa sổ dùng ≤ 2018 không phụ thuộc dữ liệu sau nó:

1. Chỉ dùng cửa sổ có `end_date` ≤ 2018-12-31 và đúng `cfg_hash` của `w252` K3.
2. Với mỗi cửa sổ dùng tới, tính lại `price_hash` từ bản clean đã cắt ≤ 2018 và so với `price_hash` trong cache; lệch bất kỳ cửa sổ nào thì dừng.
3. **Kiểm tính bất biến theo tiền tố:** chọn ngẫu nhiên 50 cửa sổ mỗi tài sản (seed cố định), tách lại từ bản clean đã cắt ≤ 2018 bằng `decompose_window` (cùng `cfg_hash`, noise seed theo ngày cuối cửa sổ, ADR-0007 mục 3); IMF1..K phải trùng từng bit, residue lệch ≤ 1e-12 tương đối (ngưỡng theo probe ADR-0007). Có test tự động cho bước này.
4. Nếu bước 2 hoặc 3 không qua thì tách lại toàn bộ cửa sổ 2014–2018 từ dữ liệu ≤ 2018, không dùng cache.

### 3.4 Giới hạn so sánh (ghi vào báo cáo)

- R-raw có 1 LSTM mỗi tài sản, R-full và R-causal có 4. Chênh lệch giữa R-raw và hai bản có tách gồm cả tác dụng của việc có nhiều mô hình hơn, không chỉ của CEEMDAN.
- R-full và R-causal khác cả rò rỉ lẫn độ dài lịch sử tách (mục 1).

## 4. Đo

- **Kiểu bài báo (chỉ minh họa trên 1–2 slide, không phải chỉ số đánh giá của dự án):** MAE, RMSE, MAPE trên mức giá một bước tới, luôn đặt cạnh cùng chỉ số của naive; slide ghi "chỉ số kiểu bài báo, ADR-0008 không dùng để đánh giá" và không khẳng định đây đúng là bộ chỉ số của Cao et al. MAPE chỉ tính trên cặp có giá thực > 0 (dữ liệu ≤ 2018 không có giá ≤ 0, vẫn kiểm và báo số cặp bị loại).
- **Theo ADR-0008 trên log return h = 1:** `mae_ratio_vs_naive`, `sign_accuracy` kèm `up_rate`; DM (HAC, HLN) so với naive. `pinball_skill` so với `baseline-q252` dùng phân vị ở mục 3.2 (chỉ báo cáo).
- **Chẩn đoán cơ chế:** so thành phần tại cùng một ngày giữa R-full và R-causal (độ lệch ở điểm cuối cửa sổ) để minh họa R-full dùng thông tin sau ngày gốc. Chỉ xuất số tổng hợp (tương quan, sai lệch trung bình theo thành phần); Claude Code không in hay tóm tắt giá trị IMF thô.

## 5. Kết quả dùng để làm gì

- Một mục trong báo cáo cuối và 1–2 slide: "vì sao không dùng kết quả các bài CEEMDAN + mạng nơ-ron".
- Kết quả nào cũng không đổi sản phẩm, không mở thí nghiệm mới, không tinh chỉnh thêm.

## 6. Thực thi

- Code trong `src/experiments/repl_ceemdan_lstm/`, không import vào Lambda hay `src/forecast/`; PyTorch chỉ cài offline (`requirements-experiments.txt` riêng, không thêm vào `requirements.txt` hay requirements của Lambda). CI chỉ chạy test không cần GPU (gồm test mục 3.3 trên dữ liệu tổng hợp).
- Chạy trên máy Khải (RTX 4060 8 GB, Ryzen 7 7840H), PyTorch bản CUDA. Tái lập: seed cố định cho Python, NumPy, PyTorch; `torch.use_deterministic_algorithms(True)`, `CUBLAS_WORKSPACE_CONFIG=:4096:8`; ghi phiên bản PyTorch, CUDA, driver vào `env.txt`. Nếu LSTM cuDNN không chạy được ở chế độ tất định thì chạy CPU (108 LSTM: 36 mỗi seed × 3 seed; ước tính vài giờ).
- Kết quả lưu `eval/repl-ceemdan-lstm/` trên S3 kèm SHA-256, không commit dữ liệu giá.
- Claude Code không đọc hay tóm tắt dữ liệu sau 2018 trong việc này.

## 7. Lịch

- Kế hoạch: PR #75, Long approve trước 8/11.
- Viết code: 9–11/11.
- Chạy và làm slide: 12–15/11.
- Trễ thì bỏ, không ảnh hưởng sản phẩm.

## 8. Ghi trước khi chạy

- `CLEAN_DT` và SHA-256 bản clean: …
- `cfg_hash` cache CEEMDAN và kết quả kiểm mục 3.3: …
- Commit chạy: …

## 9. Sửa đổi

- 2/11/2026 (review Long, #75): đổi tên thành minh họa ý tưởng, không tuyên bố tái lập đúng giao thức hay chỉ số; câu 3 chỉ so sánh hai giao thức, ghi giới hạn nhân quả; chốt đầu vào/target từng thành phần, quy đổi về giá và log return, chuẩn hóa và early stopping chỉ trên train, phân vị từ đoạn hiệu chỉnh; kiểm nguồn cache bằng `price_hash` và bất biến theo tiền tố, không qua thì tách lại; 3 seed; ghi giới hạn số LSTM của R-raw; MAPE chỉ trên giá > 0.
