ASSETS = ["gold", "silver", "brent", "wti"]
WINDOWS = [252, 504]
TRIALS = 100  # đề xuất; lưới đo thời gian 10/2026 dùng 50 và 100
EPSILON = 0.005  # mặc định PyEMD
SEED = 42
KEEP_LAST = 128  # >= seq_len lớn nhất sẽ thử (30–120)

# Chỉ cache 2014–2019 cho tới khi khóa tham số trên validation (không chạy 2020 → nay)
DEFAULT_START = "2014-01-01"
MAX_END_BEFORE_LOCK = "2019-12-31"
