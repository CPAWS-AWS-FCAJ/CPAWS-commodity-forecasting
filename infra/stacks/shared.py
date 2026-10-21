"""Hằng dùng chung giữa các stack, để tên tài nguyên và lịch không bị lệch nhau."""

# Phải KHỚP INGEST_SCHEDULE_EXPRESSION trong src/data/config.py (tests/test_infra_stacks.py kiểm tra).
# 12:15 UTC thứ Ba-thứ Bảy = 19:15 giờ VN, sau mốc công bố D+1 12:00 UTC của yfinance.
INGEST_SCHEDULE_EXPRESSION = "cron(15 12 ? * TUE-SAT *)"


def ingest_function_name(env_name: str) -> str:
    """Tên Lambda ingest. CpawsData đặt function_name và log group theo tên này, CpawsOps dùng nó
    cho dimension của alarm; lệch tên thì alarm theo dõi metric không tồn tại và luôn OK."""
    return f"cpaws-{env_name}-ingest"
