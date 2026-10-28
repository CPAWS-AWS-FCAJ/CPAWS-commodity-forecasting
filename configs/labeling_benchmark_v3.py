"""Cấu hình benchmark labeling-v3: 50 thông cáo Fed/EIA thật và vài case đặc biệt.

Chạy: python scripts/benchmark/labeling_benchmark.py --config labeling_benchmark_v3
Dựng bộ case: python scripts/benchmark/build_labeling_cases_v3.py

Bản v2 (configs/labeling_benchmark.py) giữ nguyên để tái lập lần chạy 22/10/2026.
Kế hoạch, cách gắn nhãn và ngưỡng đề xuất: docs/experiments/labeling-v3/labeling-v3-plan.md.
"""

# Nguồn để dựng bộ case
CANDIDATES_PATH = "docs/experiments/labeling-v3/candidates-fed-eia.csv"
LABELS_PATH = "docs/experiments/labeling-v3/labels-v3.csv"  # Phước điền nhãn
N_REAL_CASES = 50  # số thông cáo thật được chọn (cột selected)
SPECIAL_CASES = {"injection": 2, "empty_summary": 1}  # ngoài 50 dòng thật, id X01, X02…

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

# ĐỀ XUẤT, chưa chốt. Phước và Khải chốt trước khi dựng bộ case với --lock;
# ngưỡng được chép vào bộ case lúc dựng và script kiểm tra hai bên phải khớp.
# confidence chỉ báo cáo, không có ngưỡng.
THRESHOLDS = {
    "relevant_accuracy": 0.90,
    "event_type_accuracy": 0.90,
    "direction_accuracy": 0.80,
    "impact_abs_err_le1": 0.90,
}

MANUAL_SAMPLE_SIZE = 10  # số ô evidence duyệt tay
MANUAL_SAMPLE_SEED = 7

# Giá tham chiếu USD / 1 triệu token theo ADR-0004 (chỉ để ước tính chi phí in ra).
# Đối chiếu lại trang giá chính thức lúc chạy: https://aws.amazon.com/bedrock/pricing/
PRICE_INPUT_PER_M = 0.30
PRICE_OUTPUT_PER_M = 2.50
