"""Cấu hình thí nghiệm đo thời gian CEEMDAN theo cửa sổ cho vàng (scripts/ceemdan_timing.py).

Chỉ dùng dữ liệu tới hết 2019 (train + validation); không đọc hay tóm tắt IMF của 2020 → nay.
Thay đổi tham số ở đây, không sửa trong script.
"""

ASSET = "gold"  # GLD, bản clean mới nhất
DATA_END = "2019-12-31"  # cắt chuỗi ngay khi đọc
SAMPLE_START = "2014-01-01"  # ngày gốc lấy mẫu trong 2014–2019
SEED = 42  # = CeemdanConfig.seed mặc định

# (window, trials): lưới yêu cầu + cấu hình mặc định của decomposition.py để tham chiếu
GRID = [(252, 50), (252, 100), (504, 50), (504, 100), (512, 20)]

N_SEQ = 12  # số cửa sổ đo tuần tự cho mỗi cấu hình (inner parallel=False)
N_SEQ_INNER = 4  # số cửa sổ đo tuần tự khi để PyEMD tự chạy song song (parallel=True, mặc định)
N_PAR = 48  # số cửa sổ cho mỗi lần chạy song song ở tầng ngoài (Pool của causal_imf_windows)
PAR_PROCESSES = [4, 8, 15]  # số tiến trình; máy đo có 16 CPU logic
PAR_GRID = [(504, 100)]  # chạy với mọi PAR_PROCESSES; các cấu hình khác chỉ chạy với 8 tiến trình
PAR_DEFAULT_PROCESSES = 8

# Ngoại suy: số ngày gốc từ 2014 đến ngày chạy, 4 tài sản, theo lịch phiên của từng tài sản
EXTRAPOLATE_ASSETS = ["gold", "silver", "brent", "wti"]
EXTRAPOLATE_START = "2014-01-01"
LAMBDA_TIMEOUT_S = 900  # giới hạn 15 phút của Lambda
