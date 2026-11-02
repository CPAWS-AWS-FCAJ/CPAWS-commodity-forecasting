# Tái lập CEEMDAN + LSTM cho buổi bảo vệ (bản nháp, làm sau demo 8/11)

- Ngày: 31/10/2026
- Người viết: Khải (bản nháp do Claude soạn); người duyệt: Long
- Trạng thái: **Bản nháp, chưa chạy.** Cần Long đồng ý trước khi viết code. Chốt file này (commit) trước khi chạy.
- Khải chốt 31/10: hiện sai số trên mức giá trên slide (chỉ để minh họa); chạy đủ 4 tài sản; chạy trên máy Khải; code ở `src/experiments/`; không chờ toàn văn bài báo (mục 0).
- Bài tái lập: Cao, Li, Li (2019), *Financial time series forecasting model based on CEEMDAN and LSTM*, Physica A 519, 127–139, doi 10.1016/j.physa.2018.11.061.

## 0. Phạm vi: không phải thí nghiệm chọn mô hình

- Mục đích duy nhất: giải thích ở buổi bảo vệ vì sao kết quả của dòng bài "CEEMDAN + mạng nơ-ron" không chuyển được sang sản phẩm.
- Không mở lại ADR-0012: không đổi champion, không thêm challenger, không đưa mô hình nào vào Lambda.
- **Chỉ dùng dữ liệu ≤ 2018-12-31.** Không đọc validation 2019, không đọc test 2020 → nay; vì vậy không tính là lần nhìn thứ 5 vào 2019.
- Bài báo chỉ có bản trả phí; nhóm chưa đọc toàn văn. **Không chờ toàn văn:** thiết kế theo phần tóm tắt (mức giá chỉ số chứng khoán, một bước tới, LSTM cho từng IMF rồi cộng lại), vì mục đích là minh họa hai cách tách, không phải tái tạo đúng từng con số của bài. Nếu trước khi viết code (9/11) có được toàn văn, chỉ kiểm hai điểm: bài tách CEEMDAN trên toàn chuỗi hay theo cửa sổ, và bài dùng chỉ số nào; khác với giả định thì ghi thành mục sửa đổi trước khi chạy. Slide ghi rõ: "theo cách làm phổ biến của dòng bài này", không khẳng định bài cụ thể có rò rỉ nếu chưa đọc toàn văn.

## 1. Câu hỏi

1. Khi đo như bài báo (sai số trên mức giá, một bước tới), CEEMDAN + LSTM có trông tốt hơn dự báo "giá mai bằng giá hôm nay" không?
2. Khi đo theo ADR-0008 trên log return, lợi thế đó còn không?
3. Lợi thế (nếu có) đến từ đâu: từ CEEMDAN tách trên toàn chuỗi (dùng dữ liệu tương lai) hay từ mô hình?

## 2. Dữ liệu

- Bản clean như K3/K4 (`configs/k3_grid.CLEAN_DT`), cắt tại 2018-12-31.
- 2012–2013 khởi động (như ADR-0008), train 2014–2016, đánh giá 2017-01-01 → 2018-12-31; 4 tài sản (GLD, SLV, BZ=F, CL=F), h = 1 (một bước tới như bài báo). R-full tách CEEMDAN trên 2012–2018 nhưng vẫn train và đánh giá trên cùng các khoảng này.
- Không forward-fill; cặp phiên vắt qua phiên thiếu thì bỏ, như K4.

## 3. Biến thể (chốt)

| Mã | Tách chuỗi | Mô hình | Vai trò |
|---|---|---|---|
| R-full | CEEMDAN trên toàn chuỗi 2012–2018 rồi mới chia train/đánh giá | LSTM cho từng IMF, cộng lại | Cách thường gặp trong các bài này (có dùng dữ liệu tương lai) |
| R-causal | CEEMDAN theo cửa sổ trượt nhân quả (ADR-0001, cache ADR-0007) | LSTM cho từng IMF, cộng lại | Cách sản phẩm buộc phải dùng |
| R-raw | Không tách | LSTM trên chuỗi gốc | Tách riêng tác dụng của CEEMDAN |
| naive | — | giá mai = giá hôm nay (return = 0) | Mốc của bài toán mức giá |
| baseline-q252 | — | Phân vị 252 phiên | Mốc của sản phẩm |

- LSTM nhỏ, chốt trước: 1 lớp, 32 đơn vị, cửa sổ 20, Adam, early stopping trên 20% cuối của train; seed cố định; không tinh chỉnh tham số theo kết quả đánh giá.
- Số thành phần giống K3 (`w252-k3`): 3 IMF đầu + phần còn lại gộp làm 1 thành phần, tức 4 LSTM mỗi tài sản mỗi biến thể. R-causal lấy giá trị cuối cửa sổ của `fixed_imf_matrix` (cửa sổ 252, K = 3); R-full tách toàn chuỗi rồi gộp theo đúng cách đó. R-full và R-causal chỉ khác cách tách.
- Đọc cache CEEMDAN (ADR-0007, có cả 2019): lọc theo ngày khi nạp và `assert` ngày lớn nhất ≤ 2018-12-31 trước khi dùng.

## 4. Đo

- **Kiểu bài báo (chỉ để minh họa trên slide, không phải chỉ số đánh giá của dự án):** sai số trên mức giá một bước tới, đặt cạnh cùng chỉ số của naive. Ghi rõ trên slide: ADR-0008 không dùng các chỉ số này để đánh giá.
- **Theo ADR-0008 trên log return h = 1:** `mae_ratio_vs_naive`, `sign_accuracy` kèm `up_rate`; DM (HAC, HLN) so với naive. Với phân vị, gắn phân vị phần dư thực nghiệm của train (nhân quả) vào dự báo điểm để có `pinball_skill` so với `baseline-q252` (chỉ báo cáo).
- **Kiểu bài báo trên slide:** Khải chốt 31/10 hiện cả RMSE, MAE và MAPE trên mức giá, luôn đặt cạnh naive và ghi chú "chỉ số của bài báo, ADR-0008 không dùng để đánh giá"; Long xác nhận khi duyệt kế hoạch.
- **Chẩn đoán rò rỉ:** so IMF tại cùng một ngày giữa R-full và R-causal (độ lệch ở điểm cuối cửa sổ), minh họa vì sao R-full "biết trước". Chỉ xuất số tổng hợp (tương quan, sai lệch trung bình theo IMF); Claude Code không in hay tóm tắt giá trị IMF thô.

## 5. Kết quả dùng để làm gì

- Một mục trong báo cáo cuối và 1–2 slide: "vì sao không dùng kết quả các bài CEEMDAN + mạng nơ-ron".
- Kết quả nào cũng không đổi sản phẩm, không mở thí nghiệm mới.

## 6. Thực thi

- Code trong `src/experiments/repl_ceemdan_lstm/`, không import vào Lambda hay `src/forecast/`; PyTorch chỉ cài offline (`requirements-experiments.txt` riêng, không thêm vào `requirements.txt` hay requirements của Lambda). CI chỉ chạy test không cần GPU.
- Chạy trên máy Khải (RTX 4060 8 GB, Ryzen 7 7840H), PyTorch bản CUDA. Tái lập: seed cố định cho Python, NumPy, PyTorch; `torch.use_deterministic_algorithms(True)`, `CUBLAS_WORKSPACE_CONFIG=:4096:8`; ghi phiên bản PyTorch, CUDA, driver vào `env.txt`. Nếu LSTM cuDNN không chạy được ở chế độ tất định thì chạy CPU (mô hình nhỏ, 36 LSTM: R-full và R-causal mỗi bản 4 tài sản × 4 thành phần, R-raw 4; ước tính dưới 1 giờ).
- Kết quả lưu `eval/repl-ceemdan-lstm/` trên S3 kèm SHA-256, không commit dữ liệu.
- Claude Code không đọc hay tóm tắt dữ liệu sau 2018 trong việc này.

## 7. Lịch

- Long đồng ý phạm vi: trước 8/11.
- Chốt kế hoạch (PR) và viết code: 9–11/11.
- Chạy và làm slide: 12–15/11.
- Trễ thì bỏ, không ảnh hưởng sản phẩm.
