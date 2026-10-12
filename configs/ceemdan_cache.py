"""Cấu hình cache IMF CEEMDAN (scripts/build_ceemdan_cache.py, ADR-0007).

Đổi TRIALS, EPSILON, SEED hay KEEP_LAST thì cfg_hash đổi → cache nằm ở partition mới, phải tính
lại. Độ dài cửa sổ và cách ghép IMF chưa chốt (chọn ở K3 trên validation 2019), nên cache cả hai
độ dài cửa sổ.
"""

ASSETS = ["gold", "silver", "brent", "wti"]
WINDOWS = [252, 504]
TRIALS = 100  # đề xuất; lưới đo thời gian 10/2026 dùng 50 và 100
EPSILON = 0.005  # mặc định PyEMD
SEED = 42
KEEP_LAST = 128  # >= seq_len lớn nhất sẽ thử (30–120)

# Chỉ cache 2014–2019 cho tới khi khóa tham số trên validation (không chạy 2020 → nay)
DEFAULT_START = "2014-01-01"
MAX_END_BEFORE_LOCK = "2019-12-31"
