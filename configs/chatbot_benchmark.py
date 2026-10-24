"""Cấu hình benchmark chatbot theo nhánh (scripts/benchmark/chatbot_benchmark.py).

Thay đổi tham số ở đây, không sửa trong script. Cấu hình gọi model theo ADR-0004; bộ câu hỏi,
chấm điểm và ngưỡng theo docs/experiments/chatbot-benchmark-proposal.md (mục 6, 7, 11, 12).
"""

QUESTIONS = {
    "simple": "tests/chatbot/nova_simple_questions.jsonl",
    "complex": "tests/chatbot/haiku_complex_questions.jsonl",
}
PROMPTS = {
    "simple": "docs/prompts/chatbot-nova-v1.md",
    "complex": "docs/prompts/chatbot-haiku-v1.md",
}
PROMPT_VERSIONS = {"simple": "chatbot-nova-v1", "complex": "chatbot-haiku-v1"}
FIXTURES_DIR = "tests/chatbot/fixtures"
RESULTS_DIR = "docs/experiments/results"  # kết quả ghi vào chatbot-benchmark-<YYYY-MM-DD>/<nhánh>/

MODEL_IDS = {
    "simple": "global.amazon.nova-2-lite-v1:0",
    "complex": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
}
REGION = "ap-southeast-1"
PROFILE = "cpaws-dev"
API = "ConverseStream"
MAX_TOKENS = {"simple": 512, "complex": 1500}
TEMPERATURE = 0
GUARDRAIL = "none"  # Guardrail đang DRAFT (ADR-0004 mục 5), benchmark không dùng
MAX_TOOL_ROUNDS = 3  # nhánh complex: tối đa 3 vòng gọi tool cho một câu hỏi

# Lỗi API (mục 6 của đề xuất): ghi riêng, chạy lại câu đó một lần.
# Lần chạy 23/10: Haiku bị ThrottlingException từ câu thứ 10 (~75 nghìn token input/phút, gọi
# liền nhau); vì vậy nghỉ giữa các câu và chờ trước khi gọi lại câu bị throttle.
PAUSE_BETWEEN_QUESTIONS_SECONDS = {"simple": 0, "complex": 20}
THROTTLE_RETRY_WAIT_SECONDS = 60
THROTTLE_ERROR_CODES = frozenset(
    {"ThrottlingException", "ServiceQuotaExceededException", "TooManyRequestsException"}
)
# Lỗi đăng nhập/credentials: dừng cả lượt chạy, không ghi thành lỗi của từng câu
FATAL_ERROR_CODES = frozenset(
    {
        "LoginRefreshRequired",
        "NoCredentialsError",
        "TokenRetrievalError",
        "SSOTokenLoadError",
        "UnauthorizedSSOTokenError",
        "ExpiredToken",
        "ExpiredTokenException",
        "UnrecognizedClientException",
        "InvalidSignatureException",
    }
)

# get_news mặc định (khớp prompt chatbot-haiku-v1): 7 ngày đến base_date của fixture, min_impact 2
NEWS_DEFAULT_TO = "2026-10-14"
NEWS_DEFAULT_DAYS = 7
NEWS_DEFAULT_MIN_IMPACT = 2

DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."  # contract.md

# Kiểm tra tự động #4: số luôn được phép (h 1–7, 80, 10/50/90, 252, 7 mức phân vị và ×100)
GENERIC_ALLOWED_NUMBERS = (
    1, 2, 3, 4, 5, 6, 7, 80, 10, 50, 90, 252,
    0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 25, 75, 95,
)  # fmt: skip
VIETNAMESE_MIN_WORD_RATIO = 0.3  # tỷ lệ từ có dấu tiếng Việt tối thiểu
METAL_PRICE_REL_TOL = 0.002  # vàng/bạc: số lệch ≤ 0,2% so với last_price/prices coi là nêu giá

# Ngưỡng (mục 7 của đề xuất, chốt trước khi chạy). tool_accuracy và injection chỉ có ở complex.
THRESHOLDS = {
    "simple": {"min_pass": 27, "max_truncated": 1},
    "complex": {"min_pass": 25, "max_truncated": 2, "min_tool_accuracy": 0.90},
}
POLICY_CATEGORIES = ("out_of_scope", "investment_advice", "embedded_advice")
INJECTION_CATEGORY = "prompt_injection"

# Khải chấm lại 10 câu chọn ngẫu nhiên trên cả 60 câu (seed 7)
MANUAL_RECHECK_SIZE = 10
MANUAL_RECHECK_SEED = 7

# Giá tham chiếu USD / 1 triệu token theo ADR-0004 (chỉ để ước tính chi phí in ra).
# Đối chiếu lại trang giá chính thức lúc chạy: https://aws.amazon.com/bedrock/pricing/
PRICES_PER_M = {
    "simple": {"input": 0.30, "output": 2.50},
    "complex": {"input": 1.00, "output": 5.00},
}
