"""Hằng dùng chung giữa các stack, để tên tài nguyên và lịch không bị lệch nhau."""

# Phải KHỚP INGEST_SCHEDULE_EXPRESSION trong src/data/config.py (tests/test_infra_stacks.py kiểm tra).
# 12:15 UTC thứ Ba-thứ Bảy = 19:15 giờ VN, sau mốc công bố D+1 12:00 UTC của yfinance.
INGEST_SCHEDULE_EXPRESSION = "cron(15 12 ? * TUE-SAT *)"

# Schedule group chứa lịch ingest. Role Scheduler giới hạn aws:SourceArn theo ARN của group này
# (AWS yêu cầu ARN của schedule group, không phải của từng schedule); schedule phải đặt group_name
# bằng cùng giá trị, nếu lệch thì Scheduler không assume được role.
INGEST_SCHEDULE_GROUP = "default"


def ingest_function_name(env_name: str) -> str:
    """Tên Lambda ingest. CpawsData đặt function_name và log group theo tên này, CpawsOps dùng nó
    cho dimension của alarm; lệch tên thì alarm theo dõi metric không tồn tại và luôn OK."""
    return f"cpaws-{env_name}-ingest"


def predict_function_name(env_name: str) -> str:
    """Tên Lambda predict. CpawsData đặt function_name và log group theo tên này, CpawsOps dùng nó
    cho dimension của alarm (giống ingest_function_name)."""
    return f"cpaws-{env_name}-predict"


def forecasts_table_name(env_name: str) -> str:
    """Tên bảng DynamoDB Forecasts. Phải KHỚP table_name trong cpaws_serving_stack.py
    (tests/test_infra_stacks.py kiểm tra). CpawsData tham chiếu bảng theo tên thay vì export
    chéo stack, để không khóa CpawsServing khi sau này đổi bảng."""
    return f"cpaws-{env_name}-forecasts"
