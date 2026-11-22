"""Cấu hình K3: lưới CEEMDAN + DLinear đã chốt trước khi train (docs/experiments/k3-ceemdan-plan.md).

Không thêm cấu hình, không đổi siêu tham số sau khi đã thấy kết quả 2019 (kế hoạch, phần trạng
thái). Tham số CEEMDAN (trials, epsilon, seed, keep_last) lấy từ configs/ceemdan_cache.py.
"""

ASSETS = ["gold", "silver", "brent", "wti"]
HORIZONS = list(range(1, 8))

# Kế hoạch mục 4: (window, K, L), 8 cấu hình
GRID = [
    (252, 3, 30),
    (252, 3, 60),
    (252, 4, 30),
    (252, 4, 60),
    (504, 4, 30),
    (504, 4, 60),
    (504, 5, 30),
    (504, 5, 60),
]

# Kế hoạch mục 3: 20 epoch cố định, không early stopping theo 2019
SEEDS = [7, 8, 9]
EPOCHS = 20
BATCH_SIZE = 64
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4

# Kế hoạch mục 1: dữ liệu
EXPECTED_CFG_HASH = "4c3229533ae3"  # cache ADR-0007 dựng 12/10/2026
CLEAN_DT = "2026-10-22"  # bản clean của probe 26/10 (price_hash khớp cache)
CUTOFF = "2019-12-31"  # không đọc gì sau ngày này: cắt ngay khi đọc parquet
CACHE_START = "2014-01-01"
TRAIN = ("2014-01-01", "2018-12-31")
VALID = ("2019-01-01", "2019-12-31")

# Số ngày gốc hợp lệ theo quy tắc A, (train, val 2019), từ báo cáo probe
# docs/experiments/k3-ceemdan-probe-2026-10-26.md mục 5. Khác bảng này thì dừng.
EXPECTED_N = {
    ("gold", 252, 30): (1251, 245),
    ("gold", 252, 60): (1251, 245),
    ("gold", 504, 30): (1250, 245),
    ("gold", 504, 60): (1250, 245),
    ("silver", 252, 30): (1251, 245),
    ("silver", 252, 60): (1251, 245),
    ("silver", 504, 30): (1250, 245),
    ("silver", 504, 60): (1250, 245),
    ("brent", 252, 30): (1110, 232),
    ("brent", 252, 60): (1050, 202),
    ("brent", 504, 30): (1110, 232),
    ("brent", 504, 60): (1050, 202),
    ("wti", 252, 30): (1172, 232),
    ("wti", 252, 60): (1142, 202),
    ("wti", 504, 30): (1171, 232),
    ("wti", 504, 60): (1141, 202),
}

# Kế hoạch mục 5: chọn một cấu hình chung theo trung bình pinball_skill trên 28 nhóm (sample=all);
# chênh < 0,1 điểm % là hòa → cấu hình nhỏ hơn theo window, rồi L, rồi K.
TIE_TOLERANCE = 0.001
MAX_CONFIG_SECONDS = 600  # điều kiện dừng: một cấu hình chạy quá 10 phút

# Đánh giá: cùng EvaluationConfig của src/eval/walk_forward.py (block 20, 1000 lần, 95%, lịch hợp
# nhất NYSE/CME, seed bootstrap mặc định 7). Thời điểm đánh giá cố định cho mọi lần chạy lại.
BOOTSTRAP_SEED = 7
EVALUATION_AS_OF = "2026-10-26T00:00:00+00:00"

# So sánh với DLinear MVP (ADR-0008 mục 8), chỉ đọc artifact trong lake
MVP_MODEL_VERSION = "dlinear-41e13dc5de3d"
MVP_MODEL_SUBDIR = "models_incoming/Dlineartrain/models"
