"""Cấu hình nguồn giá, tài sản, quy tắc thời điểm công bố và ngưỡng kiểm tra (ADR-0005)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

START_DATE = "2012-01-01"
NY_TZ = "America/New_York"
REFETCH_SESSIONS = 5  # mỗi lần chạy tải lại 5 phiên gần nhất, ghi đè theo khóa (date, asset)

# Hiển thị ở front-end; không có tính năng tải/xuất dữ liệu giá.
SOURCE_ATTRIBUTION = "Nguồn: Yahoo Finance, U.S. EIA"


@dataclass(frozen=True)
class SourceRef:
    source: str  # "yfinance" | "eia"
    symbol: str


@dataclass(frozen=True)
class AssetSpec:
    asset: str
    kind: str  # "etf" | "future" | "fx" | "spot"
    unit: str
    calendar: str  # "NYSE" | "CME" | "ICE" | "FX"
    primary: SourceRef
    valid_range: tuple[float, float] | None = None
    jump_threshold: float = 0.15  # |log return 1 ngày| vượt ngưỡng → flag "jump" (chỉ đánh dấu)
    roll_rule: str | None = None  # "CL" | "BZ" cho hợp đồng tương lai
    # Loại spike (vọt > ngưỡng jump rồi quay về gần mức cũ trong <= SPIKE_MAX_SESSIONS phiên),
    # cả đoạn gắn flag "bad_value|spike"
    reject_spikes: bool = False
    extra: dict = field(default_factory=dict)


# Tài sản dùng cho mô hình
ASSETS: dict[str, AssetSpec] = {
    "gold": AssetSpec(
        "gold",
        "etf",
        "USD/share",
        "NYSE",
        primary=SourceRef("yfinance", "GLD"),
        jump_threshold=0.08,
    ),
    "silver": AssetSpec(
        "silver",
        "etf",
        "USD/share",
        "NYSE",
        primary=SourceRef("yfinance", "SLV"),
        jump_threshold=0.10,  # bạc biến động mạnh hơn vàng
    ),
    "wti": AssetSpec(
        "wti", "future", "USD/bbl", "CME", primary=SourceRef("yfinance", "CL=F"), roll_rule="CL"
    ),
    "brent": AssetSpec(
        "brent", "future", "USD/bbl", "CME", primary=SourceRef("yfinance", "BZ=F"), roll_rule="BZ"
    ),
    "usd_vnd": AssetSpec(
        "usd_vnd",
        "fx",
        "VND/USD",
        "FX",
        primary=SourceRef("yfinance", "VND=X"),
        valid_range=(20_000.0, 30_000.0),
        jump_threshold=0.02,
        reject_spikes=True,
    ),
}

# Chuỗi tham chiếu: chỉ dùng trong quality.py và hệ số hiển thị, không đưa vào train
REFERENCES: dict[str, AssetSpec] = {
    "rwtc": AssetSpec("rwtc", "spot", "USD/bbl", "CME", primary=SourceRef("eia", "RWTC")),
    "rbrte": AssetSpec("rbrte", "spot", "USD/bbl", "ICE", primary=SourceRef("eia", "RBRTE")),
    "gc_fut": AssetSpec("gc_fut", "future", "USD/oz", "CME", primary=SourceRef("yfinance", "GC=F")),
    "si_fut": AssetSpec("si_fut", "future", "USD/oz", "CME", primary=SourceRef("yfinance", "SI=F")),
}

# published_at = 00:00 UTC của (date + days) + giờ. Bảo thủ, sẽ sửa sau khi đo độ trễ chốt thanh.
# yfinance: tạm 12:00 UTC ngày date+1. EIA: phát hành hằng tuần → date+7, 12:00 UTC.
PUBLISHED_AT_RULES: dict[str, tuple[int, int]] = {
    "yfinance": (1, 12),
    "eia": (7, 12),
}

# Ngưỡng đối chiếu chéo (chỉ đánh dấu, không loại)
XCHECK_WTI_LEVEL = 0.03  # |CL=F / RWTC - 1| > 3% → "xcheck_level" trên wti
XCHECK_BRENT_RESID = 0.08  # |r(BZ=F) - r(CL=F)| > 8% → "xcheck_resid" trên brent
STALE_RUN = 3  # giá y hệt ≥ 3 phiên liên tiếp → "stale" (chỉ đánh dấu)
# Spike: sau phiên vọt, giá phải quay về trong ±ngưỡng/2 quanh giá trước khi vọt trong tối đa
# SPIKE_MAX_SESSIONS phiên. Cũng là số phiên lớp hiển thị tỷ giá giữ "pending_confirm".
SPIKE_MAX_SESSIONS = 3
DISPLAY_FACTOR_WINDOW = 20  # giá vàng USD/oz = GLD × trung vị 20 phiên (GC=F / GLD), chỉ hiển thị
NBP_FIRST_DATE = "2013-01-02"
NBP_MONTHLY_TOL = 0.01

# Lỗi đã biết ở phía nguồn tham chiếu → flag "known_source_error", bỏ khỏi đối chiếu
KNOWN_SOURCE_ERRORS: set[tuple[str, str]] = {
    ("rwtc", "2026-09-25"),
    ("rwtc", "2026-09-28"),
}

# Ngày có biến động thật đã kiểm chứng (probe 07/10/2026) → không gắn "jump"
KNOWN_EVENTS: dict[str, set[str]] = {
    "gold": {"2013-04-15", "2026-01-30"},
    "silver": {"2013-04-15", "2020-03-16", "2026-01-30", "2026-02-05"},
    "wti": {
        "2014-11-28",
        "2019-09-16",
        "2020-03-09",
        "2020-03-18",
        "2020-03-19",
        "2020-04-02",
        "2020-04-21",
        "2020-04-22",
        "2020-04-23",
        "2020-04-27",
        "2020-04-29",
        "2020-04-30",
        "2020-05-05",
        "2026-04-08",
    },
    "brent": {
        "2019-09-16",
        "2020-03-09",
        "2020-03-18",
        "2020-04-02",
        "2020-04-21",
        "2026-04-01",
    },
    "usd_vnd": {"2015-08-12", "2015-08-19"},
}

# Ngày WTI âm hợp lệ: giữ giá, flag "negative_price"; returns trả NaN
ALLOWED_NEGATIVE: set[tuple[str, str]] = {("wti", "2020-04-20")}


def lake_bucket(env: str | None = None) -> str:
    """Tên bucket theo quy ước cpaws-<env>-lake (skill aws-serverless-platform)."""
    return f"cpaws-{env or os.getenv('CPAWS_ENV', 'dev')}-lake"
