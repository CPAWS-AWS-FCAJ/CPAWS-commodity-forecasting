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
        # Khóa 29/10 bằng `--print-lock --set v2` (prompt v2 bản dev3, Khải duyệt ở review
        # approve PR #38 ngày 27/10); đề xuất v2 mục 11. Đổi bất kỳ file hay tham số nào trong
        # khóa thì lần chạy official dừng trước khi gọi Bedrock.
        "locked_sha256": {
            "questions_simple": "e6eb5ac6e32f1efac892326c6587ece48162e2b861300e18f47a2af9e5594e11",
            "prompt_simple": "1246a14cbe38dd1ca90df393d7390703e50263e5ad0f750bdd9bb5e606f1af4f",
            "questions_complex": "d7e0e14fa37d36cef5fe19dac4267ec22c1cb055bf3b54eb67cb56537cbb7540",
            "prompt_complex": "a59e5cf5aa8668fd79a8ad2b3911bffc3c0d2ba30eec0bc8b7be94d46f7ae25a",
            "fixtures": "554b2fbc62a14aef69395f28bdf8d1e775243fe26a44109f13928a1856783ab6",
            "tool_code": "1e68386efb6c4bb5c5d171a7fe57bf2c44ac0f18197d4a7ca8ca5489015c6b8b",
            "scoring_config": "0462aa7ec9aa55ed6c032c6059f848c60fea2e42c6f1cdd35e1357566309798b",
            "set_config": "d2e1f478b852468b2ae7a41031763e644f0a8cddbb0bee76c9dbf7dc37c6b141",
        },
    },
}
DEFAULT_QUESTION_SET = "v1"

# Phân tích độ nhạy (Khải review PR #38, Phước chốt 27/10; đề xuất v2 mục 10.1): người soạn prompt
# v2 cũng soạn bộ v2, và các câu này từng trùng cụm trong prompt v2 (đã viết chung lại). Báo cáo
# lần chạy chính thức kèm kết quả sau khi loại các câu này. Chỉ báo cáo, không đổi ngưỡng đạt.
# Nằm trong SHA-256 scoring_config: danh sách cố định trước khi xem kết quả chính thức.
SENSITIVITY_EXCLUDE = {
    "v2": (
        "NOVA2-007", "NOVA2-008", "NOVA2-020", "NOVA2-024",
        "HAIKU2-010", "HAIKU2-027", "HAIKU2-030",
    ),
}  # fmt: skip

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
# Số được phép thêm theo bài (Khải chốt 26/10, đề xuất v2 mục 10.4):
# - simple: 20, phần bù của khoảng 80% ("vẫn còn khoảng 20% khả năng nằm ngoài khoảng");
# - complex: 0, mốc "không đổi" của return (như 50 là mốc của xác suất tăng).
BRANCH_ALLOWED_NUMBERS = {"simple": (20,), "complex": (0,)}
# Kiểm tra nhãn khoảng 80% (Khải 25/10: gắn sai nhãn thì trượt tự động): đoạn có các cụm này mà
# chứa số khớp q05/q25/q75/q95 (và không khớp q10/q90) là gắn sai nhãn.
INTERVAL_LABEL_TRIGGERS = ("80%", "khoảng dự báo", "khoảng tin cậy")
# Số width_80_* của tool v2 chỉ được coi là hợp lệ trên đoạn có các từ này (Khải review PR #38):
# width có thể trùng |q05| hay |q95| của tài sản, kỳ hạn khác (WTI h4 width_80_price 7,92 = |q05|
# Brent h6), nên nhận width ở mọi đoạn thì có thể bỏ sót lỗi gắn nhãn.
INTERVAL_WIDTH_WORDS = ("rộng",)
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
