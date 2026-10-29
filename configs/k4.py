"""Cấu hình K4: FHS GJR-GARCH và kết hợp phân vị, chốt trước khi chạy (docs/experiments/k4-plan.md).

Không đổi ứng viên, tham số hay quy tắc chọn sau khi đã thấy kết quả (kế hoạch, phần trạng thái);
sửa đổi ghi thành mục có ngày ở mục 8 của kế hoạch. Bản clean và cách đánh giá dùng lại của K3/K3b.

Loại đánh giá "cross_validation" (CV_EVALUATION_KIND) chỉ là đánh giá nội bộ của K4: kết quả chỉ
ghi vào <output>/eval/k4/, không vào bảng Accuracy, schema docs/api/accuracy-schema.md hay
production.
"""

from configs import k3_grid as K3
from configs import k3b as K3B

ASSETS = K3.ASSETS
HORIZONS = K3.HORIZONS

# Kế hoạch mục 8 (29/10 tối): tính cả DLinear MVP (ADR-0010), K4 là lần dùng validation 2019 thứ 4
# của dự án; tổng cấu hình đã xem trên 2019 = DLinear MVP + 11 (K3 8, K3b 3) + 1 (K4).
# DLinear MVP là 1 cấu hình (PR #26, Long xác nhận ở review #60; kế hoạch mục 0).
LOOK_NUMBER = 4
DLINEAR_MVP_CONFIGS = 1
K3_K3B_K4_CONFIGS = 12
TOTAL_CONFIGS_SEEN = (
    None if DLINEAR_MVP_CONFIGS is None else DLINEAR_MVP_CONFIGS + K3_K3B_K4_CONFIGS
)

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
# Chạy 2019 một lần (review #60): run-id cố định; kết quả upload lên S3 eval/k4/k4-val2019/. Đây là
# chặn ở mức quy trình, không phải bảo đảm tuyệt đối (ai có dữ liệu vẫn chạy lại được ngoài code).
VAL2019_RUN_ID = "k4-val2019"
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
# Mục 8 (29/10 tối): tham số nạp vào phải có ν > 2 và α + γ/2 + β ≤ 1 (đúng ràng buộc của arch, kèm
# dung sai số của bộ tối ưu); chỉ từ chối khi vượt. Nghiệm nằm ở biên (gap = 1 − persistence ≤
# dung sai) vẫn hợp lệ: với 7 phiên, phương sai mô phỏng vẫn hữu hạn; báo cáo liệt kê các lần này.
NU_MIN_EXCLUSIVE = 2.0
PERSISTENCE_MAX = 1.0
PERSISTENCE_TOL = 1e-9

# Kế hoạch mục 2 và 8: kiểm định chéo, ba fold gộp, một mốc cắt ngày đích
CV_FOLDS = (2016, 2017, 2018)
CV = ("2016-01-01", "2018-12-31")
CV_CUTOFF = "2018-12-31"  # stage cv không đọc gì sau ngày này: cắt ngay khi đọc parquet
# Cấu hình CV cố định trong src/eval/walk_forward.py; chỉ dùng nội bộ, ghi vào eval/k4/
CV_EVALUATION_KIND = "cross_validation"
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

# Mục 8 (29/10 tối), báo cáo bổ sung, không đổi quy tắc chọn hay tiêu chí mục 5:
# - Holm qua 4 tài sản: p một phía = (1 + #lần bootstrap ≤ 0) / (B + 1); ngưỡng 0,025 tương ứng
#   cận dưới CI 95% hai phía > 0.
# - Độ nhạy CI theo block length; độ bền của bản dm với seed lệch xa mọi seed theo ngày (cộng một
#   số ngày lớn hơn mọi khoảng ngày của dữ liệu) và với số đường lớn hơn.
HOLM_ALPHA = 0.025
CI_BLOCKS = (10, 20, 40)
DM_ROBUST_SEED_OFFSETS = (1_000_000, 2_000_000)
DM_ROBUST_PATHS = 10_000

# Dữ liệu và đánh giá: như K3
CLEAN_DT = K3.CLEAN_DT
BOOTSTRAP_SEED = K3.BOOTSTRAP_SEED
EVALUATION_AS_OF = K3.EVALUATION_AS_OF
