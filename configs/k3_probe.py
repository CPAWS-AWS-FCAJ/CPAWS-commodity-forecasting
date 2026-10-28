"""Cấu hình probe K3 (scripts/k3_ceemdan_probe.py): kiểm cache IMF CEEMDAN, số IMF, thang giá trị
và số mẫu trước khi train mô hình chính. Chỉ đọc dữ liệu tới CUTOFF (ADR-0008 mục 7).

Tham số CEEMDAN (trials, epsilon, seed, keep_last) lấy từ configs/ceemdan_cache.py, không lặp ở đây.
"""

ASSETS = ["gold", "silver", "brent", "wti"]
WINDOWS = [252, 504]
SEQ_LENS = [30, 60, 120]  # <= keep_last (128), ADR-0007
HORIZONS = list(range(1, 8))

EXPECTED_CFG_HASH = "4c3229533ae3"  # cache dựng 12/10/2026 (ADR-0007)
REQUIREMENTS_FILE = "requirements.txt"  # numpy và EMD-signal nằm trong cfg_hash

# Không đọc gì sau ngày này: cắt ngay khi đọc parquet (filter của pyarrow)
CUTOFF = "2019-12-31"
TRAIN = ("2014-01-01", "2018-12-31")
VALID = ("2019-01-01", "2019-12-31")

CLEAN_DT = None  # None = bản clean mới nhất trong data/lake/clean/prices
REFERENCE_CLEAN_DT = "2026-10-09"  # bản clean mới nhất lúc dựng cache (chỉ để đối chiếu thêm)

# Mục 5: DLinear MVP (ADR-0008 mục 8) dùng cửa sổ 60; n_valid train lấy từ manifest
# models/<asset>/dlinear-41e13dc5de3d/manifest.json (training_audit.n_valid)
DLINEAR_WINDOW = 60
DLINEAR_MVP_TRAIN_N_VALID = {"gold": 1251, "silver": 1251, "brent": 1050, "wti": 1142}

# Mục 6: kiểm chống rò rỉ
LEAK_N_ORIGINS = 20
LEAK_SEED = 7
LEAK_ATOL = 1e-10
PROCESSES = 8  # song song tầng ngoài khi decompose lại (ADR-0007)
