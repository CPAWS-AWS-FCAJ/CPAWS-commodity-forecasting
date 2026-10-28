"""Cấu hình K3b: co giãn theo biến động, chốt trước khi chạy (docs/experiments/k3b-volatility-plan.md).

Không thêm ứng viên, không đổi λ, ngưỡng kẹp hay siêu tham số sau khi đã thấy kết quả 2019
(kế hoạch, phần trạng thái). Dữ liệu, cache và cách đánh giá dùng lại của K3 (configs/k3_grid.py).
"""

from configs import k3_grid as K3

ASSETS = K3.ASSETS
HORIZONS = K3.HORIZONS

# Kế hoạch mục 0: lần nhìn thứ 2 vào validation 2019; K3 8 cấu hình + K3b 3 ứng viên
LOOK_NUMBER = 2
TOTAL_CONFIGS_SEEN = 11

# Kế hoạch mục 4: thứ tự ưu tiên khi hòa (đơn giản trước)
CANDIDATES = ("S1a", "S1b", "S2")
TIE_TOLERANCE = 0.001  # chênh < 0,1 điểm % là hòa

# Kế hoạch mục 3, S1a/S1b: không fit tham số nào trên dữ liệu
S1_LAMBDA = {"S1a": 0.94, "S1b": 0.97}
K_CLIP = (0.5, 2.0)
SIGMA_LONG_WINDOW = 252
SIGMA_MIN_OBS = 200  # mục 6.3: cùng MIN_OBS của mốc 252 phiên
EWMA_INIT_OBS = 252  # khởi tạo σ² bằng phương sai 252 return hợp lệ đầu tiên

# Kế hoạch mục 3, S2: đặc trưng từ cấu hình K3 đã chọn (w252-k3-l30), quy tắc A
S2_WINDOW = 252
S2_MAX_IMF = 3
S2_SEQ_LEN = 30
S2_LAMBDA = 0.94
S2_EXPECTED_N = {a: K3.EXPECTED_N[(a, S2_WINDOW, S2_SEQ_LEN)] for a in ASSETS}

# Kế hoạch mục 3, S2: huấn luyện như K3, 20 epoch cố định, không early stopping theo 2019
SEEDS = [7, 8, 9]
EPOCHS = 20
BATCH_SIZE = 64
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4

# Kế hoạch mục 2 và 6.2: tập chung để chọn (giao 3 ứng viên) và tập K3 để so với ADR-0009
EXPECTED_COMMON_N = {a: n_val for a, (_, n_val) in S2_EXPECTED_N.items()}
K3_COMMON_N = {"gold": 245, "silver": 245, "brent": 202, "wti": 202}

# Dữ liệu và đánh giá: như K3
EXPECTED_CFG_HASH = K3.EXPECTED_CFG_HASH
CLEAN_DT = K3.CLEAN_DT
CUTOFF = K3.CUTOFF
CACHE_START = K3.CACHE_START
TRAIN = K3.TRAIN
VALID = K3.VALID
BOOTSTRAP_SEED = K3.BOOTSTRAP_SEED
EVALUATION_AS_OF = K3.EVALUATION_AS_OF

# Mốc so sánh K3 (mục 6.3): lần chạy provenance sạch, chỉ đọc
K3_CONFIG_ID = "w252-k3-l30"
K3_RUN_ID = "k3-val2019-clean"
K3_COMMIT = "cc5dac30a181aa110b76c74e481f664d604907b6"
