"""Cấu hình benchmark gắn nhãn tin bằng Nova 2 Lite (scripts/benchmark/labeling_benchmark.py).

Thay đổi tham số ở đây, không sửa trong script. Cấu hình gọi model theo ADR-0004 và
docs/prompts/news-labeling-v2.md; ngưỡng đạt theo acceptance_criteria trong bộ case.
"""

CASES_PATH = "tests/labeling/synthetic_cases.json"
PROMPT_PATH = "docs/prompts/news-labeling-v2.md"
SCHEMA_PATH = "docs/prompts/news-labeling-schema.json"
PROMPT_VERSION = "labeling-v2"
RESULTS_DIR = "docs/experiments/results"  # kết quả ghi vào news-labeling-<YYYY-MM-DD>/

MODEL_ID = "global.amazon.nova-2-lite-v1:0"
REGION = "ap-southeast-1"
PROFILE = "cpaws-dev"
MAX_TOKENS = 1200
TEMPERATURE = 0
TOOL_NAME = "record_news_labels"

# Ngưỡng đạt (acceptance_criteria của synthetic_cases.json); confidence chỉ báo cáo, không có ngưỡng
THRESHOLDS = {
    "relevant_accuracy": 0.90,
    "event_type_accuracy": 0.90,
    "direction_accuracy": 0.80,
    "impact_abs_err_le1": 0.90,
}

MANUAL_SAMPLE_SIZE = 10  # số ô evidence duyệt thủ công
MANUAL_SAMPLE_SEED = 7

# Giá tham chiếu USD / 1 triệu token theo ADR-0004 (chỉ để ước tính chi phí in ra).
# Đối chiếu lại trang giá chính thức lúc chạy: https://aws.amazon.com/bedrock/pricing/
PRICE_INPUT_PER_M = 0.30
PRICE_OUTPUT_PER_M = 2.50
