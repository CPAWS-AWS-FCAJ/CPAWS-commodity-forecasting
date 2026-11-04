"""Hằng số đã chốt của minh họa CEEMDAN + LSTM (kế hoạch mục 2, 3.1–3.3).

Không đổi giá trị sau khi đã thấy kết quả đánh giá 2017–2018 (kế hoạch mục 3.2). Tham số CEEMDAN
(trials, epsilon, seed, keep_last) lấy từ configs/ceemdan_cache.py, giống w252 của K3.
"""

from __future__ import annotations

from configs import ceemdan_cache as CC
from configs import k3_grid as K3
from src.forecast.decomposition import CeemdanConfig

ASSETS = ("gold", "silver", "brent", "wti")

# Kế hoạch mục 2: không đọc gì sau CUTOFF (cắt ngay khi đọc parquet)
CUTOFF = "2018-12-31"
WARMUP_START = "2012-01-01"
TRAIN = ("2014-01-01", "2016-12-31")
EVAL = ("2017-01-01", "2018-12-31")
# Kế hoạch mục 3.2: fit / early stopping / hiệu chỉnh phân vị, chia theo thời gian trong TRAIN
SPLIT = (0.70, 0.15, 0.15)
SPLIT_NAMES = ("fit", "early_stop", "calib")

# Kế hoạch mục 3.1: IMF1..3 + phần còn lại (IMF4 trở đi + residue) = 4 thành phần
SEQ_LEN = 20
N_COMPONENTS = 4
MAX_IMF = N_COMPONENTS - 1
COMPONENTS = ("imf1", "imf2", "imf3", "rest")

# Kế hoạch mục 3.2: siêu tham số đóng băng (bước 1 chỉ khai báo, chưa dùng)
LSTM = {"layers": 1, "units": 32, "lr": 1e-3, "batch": 64, "max_epochs": 200, "patience": 20}
SEEDS = (0, 1, 2)

# Kế hoạch mục 3.3: CEEMDAN = w252 của K3; bản clean như K3/K4
WINDOW = 252
CLEAN_DT = K3.CLEAN_DT
EXPECTED_CFG_HASH = K3.EXPECTED_CFG_HASH
# R-causal: ngày cuối cửa sổ từ phiên đầu tiên ≥ CAUSAL_START tới CUTOFF
CAUSAL_START = "2014-01-01"

OUT_SUBDIR = "eval/repl-ceemdan-lstm"  # trong data/ (đã gitignore)


def ceemdan_config() -> CeemdanConfig:
    """Cấu hình w252 của K3 (cfg.hash() kỳ vọng = EXPECTED_CFG_HASH nếu đúng phiên bản thư viện)."""
    return CeemdanConfig(
        window=WINDOW,
        trials=CC.TRIALS,
        epsilon=CC.EPSILON,
        seed=CC.SEED,
        keep_last=CC.KEEP_LAST,
    )
