"""Cấu hình K4: FHS GJR-GARCH và kết hợp phân vị, chốt trước khi chạy (docs/experiments/k4-plan.md).

Không đổi ứng viên, tham số hay quy tắc chọn sau khi đã thấy kết quả (kế hoạch, phần trạng thái);
sửa đổi ghi thành mục có ngày ở mục 8 của kế hoạch. Bản clean và cách đánh giá dùng lại của K3/K3b.
"""

from configs import k3_grid as K3
from configs import k3b as K3B

ASSETS = K3.ASSETS
HORIZONS = K3.HORIZONS

# Kế hoạch mục 0: lần nhìn thứ 3 vào validation 2019 (1 cấu hình); K3 8 + K3b 3 + K4 1
LOOK_NUMBER = 3
TOTAL_CONFIGS_SEEN = 12

# Kế hoạch mục 4: thứ tự ưu tiên khi hòa (ít thành phần trước)
FHS = "fhs-gjr-t"
COMBO = "combo-eq3"
CANDIDATES = (FHS, COMBO)
TIE_TOLERANCE = 0.001  # chênh < 0,1 điểm % là hòa
EARLY_STOP_AT_OR_BELOW = 0.0  # cả hai ứng viên có trung bình ≤ 0 thì dừng, không chạy 2019
BASELINE = "baseline-q252"
S1A = "S1a"
S1A_LAMBDA = K3B.S1_LAMBDA[S1A]  # 0,94 như K3b

# Kế hoạch mục 8, sửa đổi 29/10 sau kiểm định chéo: bản bootstrap từ z − mean(z) của cửa sổ fit
# (không đổi độ lệch chuẩn); chạy kiểm định chéo một lần, > 0 thì chạy 2019 một lần cho bản này.
# Không chọn lại giữa FHS và combo.
FHS_DM = "fhs-gjr-t-dm"
FHS_DEMEAN = {FHS: False, FHS_DM: True}
VAL2019_CANDIDATE = FHS_DM
CV_DM_PROCEED_ABOVE = 0.0  # trung bình pinball_skill 28 nhóm của cv-dm phải > ngưỡng này
CV_CONFIGS_SEEN = 3  # fhs-gjr-t, combo-eq3, rồi fhs-gjr-t-dm
VAL_MODELS = (FHS_DM, BASELINE, S1A)  # mục 5: so với baseline-q252 và S1a

# Kế hoạch mục 3, FHS: GJR-GARCH(1,1), nhiễu Student-t, trung bình 0, fit bằng arch (offline)
ARCH_VERSION = "8.0.0"
ARCH_SPEC = {"mean": "Zero", "vol": "GARCH", "p": 1, "o": 1, "q": 1, "dist": "t"}
FHS_WINDOW = 1000  # return hợp lệ gần nhất có ngày < ngày đầu tháng refit
FHS_SCALE = 100.0  # fit trên return × 100
FHS_PATHS = 5000
FHS_STEPS = 7
FILTER_PARITY_RTOL = 1e-8  # đệ quy NumPy so với conditional_volatility của arch trên cửa sổ fit

# Kế hoạch mục 2 và 8: kiểm định chéo, ba fold gộp, một mốc cắt ngày đích
CV_FOLDS = (2016, 2017, 2018)
CV = ("2016-01-01", "2018-12-31")
CV_CUTOFF = "2018-12-31"  # stage cv không đọc gì sau ngày này: cắt ngay khi đọc parquet
CV_EVALUATION_KIND = "cross_validation"  # cấu hình CV cố định trong src/eval/walk_forward.py
# Mục 8: số ngày gốc chung (q252, S1a, FHS cùng hợp lệ); Brent mất 1/1–29/2/2016 (39 ngày)
CV_EXPECTED_N = {"gold": 754, "silver": 754, "brent": 716, "wti": 755}

# Kế hoạch mục 2 và 5: validation 2019 trên tập chung K3 (chỉ ứng viên đã chọn, một lần)
VALID = K3.VALID
VAL_CUTOFF = K3.CUTOFF
K3_COMMON_N = K3B.K3_COMMON_N

# Kế hoạch mục 4 và 8: Model Confidence Set, chỉ báo cáo, theo từng tài sản; loss mỗi ngày gốc là
# pinball trung bình 7 h × 7 τ, sample all. Bootstrap khối vòng (cùng kiểu với
# metrics.block_bootstrap_ci), thống kê T_R của Hansen, Lunde, Nason (2011).
MCS_MODELS = (BASELINE, FHS, COMBO)
MCS_SIZE = 0.10
MCS_REPS = 1000
MCS_BLOCK = 20
MCS_SEED = 7
MCS_METHOD = "R"
MCS_BOOTSTRAP = "cbb"

# Dữ liệu và đánh giá: như K3
CLEAN_DT = K3.CLEAN_DT
BOOTSTRAP_SEED = K3.BOOTSTRAP_SEED
EVALUATION_AS_OF = K3.EVALUATION_AS_OF
