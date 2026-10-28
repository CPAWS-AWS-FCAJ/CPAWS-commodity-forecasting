"""Cấu hình benchmark labeling-v3: 49 thông cáo Fed/EIA thật và vài case đặc biệt.

Chạy: python scripts/benchmark/labeling_benchmark.py --config labeling_benchmark_v3
Dựng bộ case: python scripts/benchmark/build_labeling_cases_v3.py

Bản v2 (configs/labeling_benchmark.py) giữ nguyên để tái lập lần chạy 22/10/2026.
Kế hoạch, cách gắn nhãn và ngưỡng đề xuất: docs/experiments/labeling-v3/labeling-v3-plan.md.
"""

# Nguồn để dựng bộ case
CANDIDATES_PATH = "docs/experiments/labeling-v3/candidates-fed-eia.csv"
LABELS_PATH = "docs/experiments/labeling-v3/labels-v3.csv"  # Phước điền nhãn
N_REAL_CASES = 49  # số thông cáo thật được chọn (cột selected); Khải loại E22 ngày 28/10
SPECIAL_CASES = {"injection": 2, "empty_summary": 1}  # ngoài 49 dòng thật, id X01, X02…
# Khải 28/10/2026: statement cắt hoặc tăng lãi suất phải ở nhóm A (chốt chặn cho mục 6.2)
REQUIRED_GROUP_A = ("F06", "F07", "F14")

# Bộ case đã dựng; script từ chối chạy thật khi status khác "locked"
CASES_PATH = "tests/labeling/real_cases_v3.json"
CASES_VERSION = "real-1"
REQUIRE_LOCKED_CASES = True

PROMPT_PATH = "docs/prompts/news-labeling-v3.md"
SCHEMA_PATH = "docs/prompts/news-labeling-schema.json"
PROMPT_VERSION = "labeling-v3"
EVIDENCE_RULE = "v3"  # impact ≥ 1 thì evidence bắt buộc, impact 0 thì evidence rỗng
RESULTS_DIR = "docs/experiments/results"
RESULTS_PREFIX = "news-labeling-v3"  # kết quả ghi vào news-labeling-v3-<YYYY-MM-DD>/

MODEL_ID = "global.amazon.nova-2-lite-v1:0"
REGION = "ap-southeast-1"
PROFILE = "cpaws-dev"
MAX_TOKENS = 1200
TEMPERATURE = 0
TOOL_NAME = "record_news_labels"

# Khải chốt ngày 28/10/2026: giữ như v2. Ngưỡng và tiêu chí duyệt tay được chép vào bộ case
# lúc dựng; khi chạy thật, script kiểm tra bộ case khớp cấu hình.
# confidence chỉ báo cáo, không có ngưỡng.
THRESHOLDS = {
    "relevant_accuracy": 0.90,
    "event_type_accuracy": 0.90,
    "direction_accuracy": 0.80,
    "impact_abs_err_le1": 0.90,
}

# Duyệt tay evidence (Khải chốt 28/10/2026): 10 ô lấy ngẫu nhiên seed 7 trong các ô model gán
# impact ≥ 1; đạt khi ≥ 8/10; Khải chấm theo ba tiêu chí ghi sẵn trước khi chạy.
MANUAL_SAMPLE_SIZE = 10
MANUAL_SAMPLE_SEED = 7
MANUAL_REVIEW = {
    "sample_size": MANUAL_SAMPLE_SIZE,
    "seed": MANUAL_SAMPLE_SEED,
    "pool": "ô có impact_score do model gán ≥ 1",
    "pass_min": 8,
    "reviewer": "Khải",
    "criteria": [
        "Đúng nội dung: evidence chỉ nêu điều có trong tiêu đề hoặc tóm tắt",
        "Khớp hướng: evidence ủng hộ đúng direction đã gán",
        "Không thêm dữ kiện: không có con số, nguyên nhân hay cơ chế mà bài không nêu",
    ],
}

# Giá tham chiếu USD / 1 triệu token theo ADR-0004 (chỉ để ước tính chi phí in ra).
# Đối chiếu lại trang giá chính thức lúc chạy: https://aws.amazon.com/bedrock/pricing/
PRICE_INPUT_PER_M = 0.30
PRICE_OUTPUT_PER_M = 2.50
