# Thời gian chạy CEEMDAN theo cửa sổ: vàng, 2014–2019 (10/2026)

- Người làm: Trịnh Tiến Khải (script và bản nháp do Claude Code soạn). Người đọc: Châu Trần Mạnh Tiến (lịch cache, hạ tầng), Nguyễn Tiến Long.
- Script `scripts/ceemdan_timing.py`, cấu hình `configs/ceemdan_timing.py` (seed 42). Kết quả đầy đủ trong `data/lake/experiments/ceemdan_timing/dt=2026-10-10/` (không commit).
- Dữ liệu: GLD từ bản clean `dt=2026-10-09`, **cắt tới 31/12/2019** ngay khi đọc. Ngày gốc lấy mẫu trong 2014–2019. Không đọc hay tóm tắt IMF của giai đoạn 2020 → nay. Số cửa sổ cần cache tới nay được đếm từ lịch phiên.
- Máy đo: Windows 11, 16 CPU logic, Python 3.11.9, EMD-signal 1.10.0. `seq_len = 60`, `n_imfs = 10` (mặc định).

## Hai chế độ song song

- **inner=default**: `decompose_window` gọi `CEEMDAN(trials=...)`. Ở PyEMD 1.10, mặc định là `parallel=True`, nên mỗi lần gọi PyEMD tự mở `Pool(os.cpu_count())` (một lần cho nhiễu, một lần cho mỗi tầng IMF).
- **inner=off**: `CEEMDAN(parallel=False)`. Thí nghiệm thay hàm này qua biến môi trường, không sửa `decomposition.py`.
- **Song song tầng ngoài**: `causal_imf_windows(processes=k)`, mỗi tiến trình xử lý một cửa sổ (inner=off).

## Kết quả

Giây mỗi cửa sổ, chạy tuần tự (n = 12 cửa sổ với inner=off, 4 cửa sổ với inner=default):

| window | trials | inner=off: trung vị | inner=off: p90 | inner=default: trung vị |
|---|---|---|---|---|
| 252 | 50 | 0,99 | 1,14 | 9,36 |
| 252 | 100 | 1,90 | 2,14 | 9,83 |
| 504 | 50 | 1,49 | 1,74 | 9,82 |
| 504 | 100 | 3,00 | 3,30 | 11,68 |
| 512 (mặc định) | 20 (mặc định) | 0,61 | 0,69 | 9,10 |

Song song tầng ngoài (60 cửa sổ mỗi lần, đã gồm thời gian khởi động Pool):

| window | trials | k = 4 | k = 8 | k = 15 |
|---|---|---|---|---|
| 504 | 100 | 0,94 s/cửa sổ | 0,55 | 0,42 |
| 252 | 50 | — | 0,22 | — |
| 252 | 100 | — | 0,37 | — |
| 504 | 50 | — | 0,29 | — |
| 512 | 20 | — | 0,14 | — |

Ngoại suy: từ 01/2014 đến 09/10/2026 có **12.852 cửa sổ** (vàng 3.212, bạc 3.212, Brent 3.214, WTI 3.214 phiên theo lịch sàn).

| window | trials | cache toàn bộ, tuần tự | cache toàn bộ, 8 tiến trình | cập nhật hằng ngày (4 cửa sổ, tuần tự) |
|---|---|---|---|---|
| 252 | 50 | 3,6 giờ | 0,8 giờ | 4 s |
| 252 | 100 | 6,8 giờ | 1,3 giờ | 8 s |
| 504 | 50 | 5,3 giờ | 1,1 giờ | 6 s |
| 504 | 100 | 10,7 giờ | 2,0 giờ | 12 s |
| 512 | 20 | 2,2 giờ | 0,5 giờ | 2 s |

## Kiểm tra

| Kiểm tra | Kết quả |
|---|---|
| Chạy lại cùng seed (inner=off) | Giống hệt từng bit |
| Song song tầng ngoài so với tuần tự (inner=off) | Giống hệt từng bit (7/7 lần chạy) |
| inner=default so với inner=off | Lệch tối đa khoảng 3e-16. Hai lần chạy inner=default cũng lệch nhau, vì PyEMD cộng các trial bằng `imap_unordered` nên thứ tự cộng thay đổi mỗi lần |
| Nối thêm dữ liệu sau t (tới hết 2019) | IMF tại t không đổi (12/12 cửa sổ) |
| Pool tầng ngoài + inner=default | **Lỗi**: `AssertionError: daemonic processes are not allowed to have children`. Hiện `causal_imf_windows(processes>1)` không chạy được với cấu hình mặc định |
| Số thành phần (IMF + residue) mỗi cửa sổ | window 252: 5 hoặc 6 (19/60 và 41/60); window 504: 6 hoặc 7 (khoảng nửa mỗi loại); 512 × 20: 6 hoặc 7 |

## Đề xuất (chưa sửa code, chưa tạo tài nguyên AWS)

1. **Đặt `parallel=False` trong `decompose_window`** và song song ở tầng ngoài. Lý do:
   - Nhanh hơn 4–15 lần trên máy đo.
   - Tái lập được từng bit.
   - Cho phép dùng `processes > 1`.
   - Lambda không hỗ trợ `multiprocessing.Pool` (không có `/dev/shm`), nên chế độ mặc định của PyEMD sẽ lỗi trong Lambda dự đoán.

   Thay đổi này không làm đổi giá trị IMF (chỉ lệch khoảng 1e-16). Cần thêm test.
2. **Số IMF thay đổi giữa các cửa sổ** ảnh hưởng tới cách ghép đầu vào. `_fix_width` đệm 0 bên phải, nên residue lúc nằm ở cột 5, lúc ở cột 6 (window 504). Một cột vì thế mang ý nghĩa khác nhau giữa các ngày. Có hai hướng:
   - (a) căn từ phía tần số thấp: residue luôn ở cột cuối, IMF cao tần đệm ở giữa;
   - (b) giới hạn `max_imf` theo số nhỏ nhất quan sát được, để mọi cửa sổ có cùng số cột.

   Chọn trên validation 2019 và ghi ADR trước khi cache, vì đổi cách ghép sau khi cache là phải tính lại toàn bộ.
3. **Nơi chạy cache toàn bộ**:
   - Với window 504 × 100 trials: khoảng 2 giờ trên máy 8–16 luồng. Chạy được ở máy local, hoặc một SageMaker AI Processing Job CPU (ví dụ 16 vCPU), khoảng 1–2 giờ mỗi lần tính lại.
   - Không dùng Lambda cho việc này: 12.852 × 3 s ≈ 10,7 giờ CPU, vượt xa giới hạn 15 phút của một lần gọi. Muốn dùng Lambda phải chia nhỏ qua Step Functions Map, phức tạp hơn mức cần.
   - Ước tính chi phí theo skill `aws-cost-guard` trước khi tạo job.
4. **Cập nhật hằng ngày**: 4 cửa sổ mới, chạy tuần tự trong Lambda dự đoán chỉ mất khoảng 12 s (504 × 100). Lambda cấp CPU theo bộ nhớ (1.769 MB tương đương 1 vCPU), nên con số này đo trên máy local chỉ là ước lượng; cần chạy thử trong Lambda (việc của Tiến).
5. **Lịch sử cho window 504**:
   - Ngày gốc t cần 504 dòng giá tính tới t.
   - Vàng, bạc, WTI có 502 dòng trong 2012–2013, nên mất 1 ngày gốc đầu 2014.
   - Brent chỉ có 486 dòng (thiếu phiên sau ngày đáo hạn theo lịch ICE cũ), nên mất 17 ngày gốc đầu 2014.
   - Window 252 không gặp vấn đề này.

Tham khảo: [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) (timeout 900 s, bộ nhớ tới 10.240 MB, 1.769 MB ≈ 1 vCPU); [Parallel processing in Python with AWS Lambda](https://aws.amazon.com/blogs/compute/parallel-processing-in-python-with-aws-lambda/) (không có `/dev/shm`, không dùng được `multiprocessing.Pool`/`Queue`; bài viết cũ, cần chạy thử lại trên runtime hiện tại).
