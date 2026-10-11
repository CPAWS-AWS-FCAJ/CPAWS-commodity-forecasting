# ADR-0007: Cấu hình CEEMDAN và định dạng cache IMF

- Ngày: 2026-10-11
- Trạng thái: Đề xuất
- Người viết: Trịnh Tiến Khải (bản nháp do Claude Code soạn); người duyệt: Nguyễn Tiến Long, Châu Trần Mạnh Tiến

## Bối cảnh

ADR-0001 chọn CEEMDAN theo cửa sổ kết thúc tại mỗi ngày gốc. Thí nghiệm đo thời gian (`docs/experiments/ceemdan-timing-2026-10.md`) và probe ngày 11/10/2026 cho thấy bốn vấn đề:

1. **PyEMD 1.10 mặc định `parallel=True`**: mỗi lần gọi tự mở `Pool(os.cpu_count())`.
   - Chậm hơn 4–15 lần so với chạy không song song.
   - Cộng các trial bằng `imap_unordered`, nên hai lần chạy cùng seed lệch nhau khoảng 1e-16 (không tái lập từng bit).
   - Không chạy được trong Pool tầng ngoài (`daemonic processes are not allowed to have children`).
   - Theo tài liệu AWS, Lambda không có `/dev/shm` nên không dùng được `multiprocessing.Pool`.
2. **Số IMF thay đổi giữa các cửa sổ**: 4 hoặc 5 IMF với cửa sổ 252, 5 đến 7 IMF với cửa sổ 504 (vàng, 2014–2019). Định dạng cũ đệm số 0 bên phải để có 10 cột, nên residue lúc nằm ở cột này, lúc ở cột khác.
3. **Độ dài cửa sổ (252 hay 504), cách ghép IMF và `seq_len` chưa chọn.** Các tham số này chọn ở K3 trên validation 2019. Cache phải dùng được cho mọi lựa chọn mà không phải tách lại.
4. **Noise seed đang theo vị trí dòng (`seed + origin`)**. Khi lịch sử phía trước đổi số dòng (ví dụ quy tắc làm sạch loại thêm một dòng cũ), seed của mọi cửa sổ sau đó đổi theo, dù giá trong cửa sổ không đổi.

## Các phương án

**Song song**
- (a) Giữ mặc định của PyEMD. Nhược điểm như mục 1.
- (b) `parallel=False` trong `decompose_window`, chỉ song song ở tầng ngoài (`causal_imf_windows(processes=k)` hoặc truyền `pool`). Tái lập từng bit, giá trị lệch phương án (a) khoảng 1e-16.

**Định dạng cache**
- (a) Ma trận cố định 10 cột, đệm 0 (định dạng cũ). Ý nghĩa cột thay đổi; đổi cách ghép thì phải tách lại.
- (b) Mỗi cửa sổ lưu IMF thô (đúng số IMF, không đệm), residue riêng và `n_imf`; ghép bằng hàm riêng khi dựng đặc trưng.

**Ghép cố định K IMF**
- (a) Chạy CEEMDAN với `max_imf=K`.
- (b) Chạy đầy đủ rồi giữ IMF1..K, cộng các IMF còn lại vào residue.

  Probe ngày 11/10/2026 (`scripts/ceemdan_fold_probe.py`; 10 cửa sổ vàng mỗi độ dài; trials 50; K = số IMF nhỏ nhất quan sát được, K = 4 với 252 và K = 5 với 504): IMF1..K **giống hệt từng bit** ở 20/20 cửa sổ; residue lệch tối đa 4,3e-14 trên giá khoảng 100–180, tức sai số tương đối 3e-16. Như vậy (b) tương đương (a) và chỉ cần tách một lần.

## Quyết định

1. `decompose_window` dùng `CEEMDAN(trials, epsilon, parallel=False)`. Song song chỉ ở tầng ngoài.
2. **Định dạng (b)**: `causal_imf_windows` trả về danh sách `WindowIMF(origin, imfs[n_imf, keep_last], residue[keep_last])`.
   - Mỗi cửa sổ giữ `keep_last = 128` điểm cuối, đủ cho `seq_len` 30–120.
   - `fixed_imf_matrix(windows, max_imf=K, seq_len)` ghép thành `(n, seq_len, K+1)`: IMF1..K, cột cuối là residue cộng phần đuôi, nên residue luôn ở cột cuối. Cửa sổ có ít hơn K IMF thì các cột thiếu bằng 0.
3. **Noise seed = `seed` + số ngày từ 1970-01-01 tới ngày cuối cửa sổ** (`seed_ids` trong `causal_imf_windows`). Seed không phụ thuộc vị trí dòng.
4. **Cache** (`src/features/ceemdan_cache.py`, chạy bằng `scripts/build_ceemdan_cache.py`):
   - Đường dẫn: `features/ceemdan/asset=<asset>/window=<window>/cfg=<cfg_hash>/month=YYYY-MM.parquet`, kèm `config.json`. Bố cục giống hệt trên `s3://cpaws-<env>-lake/`.
   - Khóa mỗi dòng: asset, window, `cfg_hash`, `end_date`. Ngoài ra lưu `price_hash`, là sha256 của các giá float64 trong cửa sổ.
   - `cfg_hash` gồm trials, epsilon, seed, `keep_last`, phiên bản PyEMD và numpy. Đổi bất kỳ giá trị nào thì cache nằm ở partition mới.
   - Ghi theo tháng: bị ngắt thì chạy lại sẽ tiếp tục từ tháng chưa xong (file hỏng coi như chưa có).
   - Cập nhật hằng ngày (`update_recent`): tính các cửa sổ mới; với cửa sổ kết thúc trong 5 phiên gần nhất, so `price_hash` và tính lại nếu giá trong cửa sổ đã đổi. Muốn kiểm lại toàn bộ thì chạy `--verify`.
   - Cửa sổ tính theo **dòng giá được giữ** của tài sản (prices.parquet), không theo lịch sàn.
5. **Cấu hình cache đề xuất** (`configs/ceemdan_cache.py`): trials = 100, epsilon = 0,005, seed = 42, `keep_last` = 128. Cache cả hai độ dài 252 và 504 cho tới K3. Cache chỉ tính 2014–2019 cho tới khi khóa tham số; script từ chối `--end` sau 2019 nếu không có `--allow-after-2019`.
6. **Chọn ở K3 trên validation 2019** (chưa quyết định ở ADR này): độ dài cửa sổ (252 hoặc 504), cách ghép IMF (K cố định, hay chia nhánh cao tần và thấp tần bằng `split_high_low` trên ma trận đã ghép), và `seq_len`. Khi chọn xong thì ghi ADR mới, không sửa ADR này.

## Hệ quả

- **Brent với cửa sổ 504**: Brent chỉ có 486 dòng giá trong 2012–2013, vì thiếu các phiên ngay sau ngày đáo hạn theo lịch ICE cũ (ADR-0005). Vì vậy 17 ngày gốc đầu 2014 không có đủ 504 dòng lịch sử và bị bỏ (`skipped_no_history`). Vàng, bạc, WTI mỗi tài sản mất 1 ngày (02/01/2014). Nhóm **chấp nhận** việc mất các ngày này; khi so 252 với 504 trên cùng tập ngày gốc, phải loại các ngày này ở cả hai.
- **Tái lập**: trên cùng nền tảng, kết quả giống hệt từng bit (có test). Giữa Windows (máy local) và Linux (Lambda, SageMaker) chỉ so theo dung sai `atol = 1e-10`, vì libm và thứ tự phép tính dấu phẩy động có thể khác. Cache dựng ở máy local vẫn dùng được với cửa sổ mới tính trong Lambda.
- **Thời gian**, đo trên máy 16 luồng với 8 tiến trình và trials 100 (chạy thử vàng 01–03/2014): 0,45 s mỗi cửa sổ với độ dài 252, 0,63 s với 504. Cache 2014–2019 cho 4 tài sản × 2 độ dài (khoảng 12.000 cửa sổ) mất khoảng **1,8 giờ**, dung lượng khoảng 95 MB (khoảng 8 KB mỗi cửa sổ).
- **Cập nhật hằng ngày**: 4 tài sản × 2 độ dài = 8 cửa sổ, chạy tuần tự khoảng 20 s trên máy local. Cần đo lại trong Lambda.
- **Rủi ro**:
  - Giá cũ hơn 5 phiên bị sửa thì cache không tự phát hiện; cần chạy `--verify` định kỳ (ví dụ trong lần retrain hằng tuần).
  - Đổi phiên bản PyEMD hay numpy làm đổi `cfg_hash` và buộc tính lại toàn bộ, nên cần ghim phiên bản trong ảnh container.
- Cập nhật skill `leakage-safe-forecasting` (mục tham số mặc định) cho khớp API mới.
