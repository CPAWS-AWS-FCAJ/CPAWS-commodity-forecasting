"""Cấu hình benchmark chatbot theo nhánh (scripts/benchmark/chatbot_benchmark.py).

Thay đổi tham số ở đây, không sửa trong script. Cấu hình gọi model theo ADR-0004; bộ câu hỏi,
chấm điểm và ngưỡng theo docs/experiments/chatbot-benchmark-proposal.md (v1, mục 6, 7, 11, 12) và
docs/experiments/chatbot-benchmark-v2-proposal.md (v2, mục 4 và 7).
"""

# Bộ câu hỏi. v1: chạy chính thức 23/10, nay chỉ dùng cho lần chạy phát triển (run_type dev).
# v2: chạy chính thức trước 8/11; phải khóa SHA-256 (locked_sha256) trước khi chạy official.
QUESTION_SETS = {
    "v1": {
        "questions": {
            "simple": "tests/chatbot/nova_simple_questions.jsonl",
            "complex": "tests/chatbot/haiku_complex_questions.jsonl",
        },
        "fixtures_dir": "tests/chatbot/fixtures",
        "prompt_set": "v1",  # bộ prompt mặc định; lần chạy dev đổi được bằng --prompts
        "news_default_to": "2026-10-14",  # base_date của fixture v1
        "require_lock": False,
        "holdout": False,  # được chạy dev thật
        "locked_sha256": None,
    },
    "v2": {
        "questions": {
            "simple": "tests/chatbot/v2/nova_simple_questions.jsonl",
            "complex": "tests/chatbot/v2/haiku_complex_questions.jsonl",
        },
        "fixtures_dir": "tests/chatbot/v2/fixtures",
        # Khải chốt 25/10: chạy chính thức bằng prompt + tool v2 (prompt v2 phải được duyệt trước
        # khi khóa SHA-256)
        "prompt_set": "v2",
        "news_default_to": "2026-10-21",  # base_date của fixture v2
        "require_lock": True,
        # Bộ giữ riêng: chỉ chạy official sau khi khóa; chạy dev thật bị chặn (Khải review PR #35)
        "holdout": True,
        # Dán kết quả của `--print-lock --set v2` vào đây (và vào đề xuất v2) khi khóa ngày 3/11.
        "locked_sha256": None,
    },
}
DEFAULT_QUESTION_SET = "v1"

# Bộ prompt và dạng đầu ra của tool get_forecast đi kèm.
# contract: trả nguyên JSON GET /forecasts/{asset} (như lần chạy 23/10).
# v2: qua src/chatbot/tools.py (q10/q50/q90 có tên, vàng/bạc không có giá), dùng chung hàm định
#     dạng với Lambda API (infra/lambda/forecast_api/forecast_format.py).
PROMPT_SETS = {
    "v1": {
        "prompts": {
            "simple": "docs/prompts/chatbot-nova-v1.md",
            "complex": "docs/prompts/chatbot-haiku-v1.md",
        },
        "prompt_versions": {"simple": "chatbot-nova-v1", "complex": "chatbot-haiku-v1"},
        "tool_format": "contract",
    },
    "v2": {
        "prompts": {
            "simple": "docs/prompts/chatbot-nova-v2.md",
            "complex": "docs/prompts/chatbot-haiku-v2.md",
        },
        "prompt_versions": {"simple": "chatbot-nova-v2", "complex": "chatbot-haiku-v2"},
        "tool_format": "v2",
    },
}
# Code được khóa cùng bộ câu hỏi (Khải 25/10: khóa cả code tool chatbot)
TOOL_CODE_PATHS = (
    "scripts/benchmark/chatbot_benchmark.py",
    "src/chatbot/tools.py",
    "infra/lambda/forecast_api/forecast_format.py",
)
RUN_TYPES = (
    "official",
    "dev",
)  # dev: không báo cáo như kết quả đạt, thư mục kết quả có hậu tố -dev
RESULTS_DIR = "docs/experiments/results"  # chatbot-benchmark-<ngày>[-<bộ>][-dev|-dryrun]/<nhánh>/

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

# get_news mặc định (khớp prompt chatbot-haiku-v1): 7 ngày đến base_date của fixture
# (news_default_to của từng bộ), min_impact 2
NEWS_DEFAULT_DAYS = 7
NEWS_DEFAULT_MIN_IMPACT = 2

DISCLAIMER = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư."  # contract.md

# Kiểm tra tự động #4: số luôn được phép (h 1–7, 80, 10/50/90, 252, 7 mức phân vị và ×100)
GENERIC_ALLOWED_NUMBERS = (
    1, 2, 3, 4, 5, 6, 7, 80, 10, 50, 90, 252,
    0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 25, 75, 95,
)  # fmt: skip
# Kiểm tra nhãn khoảng 80% (Khải 25/10: gắn sai nhãn thì trượt tự động): đoạn có các cụm này mà
# chứa số khớp q05/q25/q75/q95 (và không khớp q10/q90) là gắn sai nhãn.
INTERVAL_LABEL_TRIGGERS = ("80%", "khoảng dự báo", "khoảng tin cậy")
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
