"""Luật định tuyến chatbot (src/chatbot/router.py), theo ADR-0004 mục 1.

Router không gọi LLM. Câu đơn giản (chào hỏi, khái niệm, từ chối ngoài phạm vi hoặc tư vấn đầu tư)
sang Nova 2 Lite; câu cần số liệu dự báo hoặc tin tức sang Claude Haiku 4.5; không chắc thì sang
Haiku. Cụm từ viết có dấu; với câu người dùng gõ không dấu, router so cả bản đã bỏ dấu.
Thêm hay sửa cụm ở đây, không sửa trong code, và chạy lại tests/test_router.py.
"""

SIMPLE = "simple"  # Nova 2 Lite, không có tool
COMPLEX = "complex"  # Claude Haiku 4.5, có tool get_forecast/get_news
DEFAULT_BRANCH = COMPLEX  # ADR-0004: không đủ tự tin thì chuyển sang Haiku

# Tài sản trong phạm vi
ASSET_TERMS = (
    "vàng", "bạc", "brent", "wti", "dầu", "dầu thô", "gld", "slv",
    "gold", "silver", "oil", "crude",
)  # fmt: skip

# Ngoài phạm vi theo sản phẩm. Cụm gắn với tên tài sản ("vàng nhẫn", "dầu diesel") được xóa khỏi
# câu trước khi tìm tài sản, để "vàng nhẫn" không bị hiểu là hỏi về vàng (GLD).
OUT_OF_SCOPE_PRODUCT_TERMS = (
    "giá vàng trong nước", "vàng trong nước", "vàng sjc", "vàng miếng", "vàng nhẫn", "sjc", "pnj",
    "doji", "9999", "dầu diesel", "diesel", "xăng", "ron95", "ron 95", "cây xăng",
    "bitcoin", "btc", "crypto", "tiền mã hóa", "tiền điện tử", "cổ phiếu", "chứng khoán",
    "bất động sản", "ngoại tệ",
)  # fmt: skip
# Dự đoán trong ngày: luôn ngoài phạm vi, kể cả khi có tên tài sản
OUT_OF_SCOPE_INTRADAY_TERMS = (
    "trong ngày", "chiều nay", "sáng nay", "tối nay", "trưa nay", "giờ tới", "theo giờ",
    "phút tới", "intraday",
)  # fmt: skip
# Việc không liên quan đến sản phẩm
OFF_TOPIC_TERMS = (
    "chuyện cười", "truyện cười", "thời tiết", "bóng đá", "phim", "bài hát", "nấu ăn",
    "ăn gì", "nên ăn", "ăn trưa", "phở", "cơm tấm", "code", "python", "lập trình",
    "dịch giúp", "dịch sang", "translate", "joke",
)  # fmt: skip

ADVICE_TERMS = (
    "nên mua", "nên bán", "nên giữ", "có nên", "mua hay bán", "bán hay giữ", "hay giữ",
    "giữ hay", "chốt lời", "cắt lỗ", "phân bổ", "chia vào", "nên đầu tư", "đầu tư vào",
    "lướt sóng", "vào lệnh", "đặt lệnh", "dồn hết", "bán hết", "all in", "chiến lược",
    "có hợp lý", "đáng mua", "should i buy", "should i sell",
)  # fmt: skip
# Có các cụm này cùng tư vấn thì câu cần phân tích dự báo trước khi từ chối phần tư vấn → Haiku
ANALYSIS_TERMS = (
    "phân tích", "dự báo", "so sánh", "xu hướng", "nghiêng", "xác suất", "khoảng",
    "tăng hay giảm",
)  # fmt: skip

NEWS_TERMS = (
    "tin tức", "tin gì", "tin mới", "tin nào", "tin lớn", "có tin", "bản tin", "vì sao",
    "tại sao", "lý do", "nguyên nhân", "ảnh hưởng", "tác động", "điều gì có thể khiến",
    "news", "why",
)  # fmt: skip

FORECAST_TERMS = (
    "dự báo", "tăng", "giảm", "xác suất", "khoảng", "trung vị", "q10", "q50", "q90",
    "bao nhiêu", "thế nào", "ra sao", "sao rồi", "nghiêng", "biến động", "giá", "tỷ giá",
    "mô hình", "đáng tin", "tin cậy", "forecast", "price", "outlook",
)  # fmt: skip
TIME_TERMS = (
    "ngày mai", "phiên tới", "phiên nữa", "tuần tới", "tuần sau", "tuần này", "tuần qua",
    "mấy ngày tới", "mấy hôm nay", "gần đây", "sắp tới", "tomorrow", "next week",
)  # fmt: skip
# Kỳ hạn của sản phẩm là 1–7 phiên; "252 phiên" (mốc thống kê) không phải kỳ hạn
TIME_PATTERNS = (r"(?<!\d)[1-7]\s*phiên", r"kỳ hạn\s*[1-7](?!\d)", r"h\s*=\s*[1-7](?!\d)")
NUMBER_REQUEST_TERMS = ("bao nhiêu", "mức nào", "mấy phần trăm", "con số", "how much")

DEFINITION_TERMS = (
    "là gì", "là sao", "nghĩa là", "nghĩa gì", "có nghĩa", "ý nghĩa", "giải thích",
    "khác nhau", "khác gì", "phân biệt", "có phải", "hiểu thế nào", "hiểu sao",
    "what is", "what does", "meaning",
)  # fmt: skip
CONCEPT_TERMS = (
    "log return", "phân vị", "trung vị", "khoảng dự báo", "xác suất tăng", "ngày cơ sở",
    "base date", "kỳ hạn", "stale", "dữ liệu mẫu", "mốc thống kê", "252", "hợp đồng tương lai",
    "chuỗi đại diện", "q10", "q50", "q90",
)  # fmt: skip
# Câu hỏi về chính chatbot/sản phẩm, không cần số liệu
META_TERMS = (
    "tài sản nào", "làm được gì", "hỗ trợ những", "dùng thế nào", "bắt đầu", "xa nhất",
    "bao lâu", "cập nhật", "tiếng anh", "tiếng việt", "english", "vietnamese",
)  # fmt: skip
GREETING_TERMS = (
    "chào", "xin chào", "hello", "hi", "hey", "alo", "cảm ơn", "thank", "thanks",
    "tạm biệt", "bye", "bạn là ai", "who are you", "có ai", "có đó không", "bot ơi",
    "hẹn gặp lại",
)  # fmt: skip
