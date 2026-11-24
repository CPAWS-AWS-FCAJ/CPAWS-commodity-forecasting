from __future__ import annotations

import logging
import os

from . import ingest_prices

log = logging.getLogger("cpaws.ingest")
log.setLevel(logging.INFO)


class IngestSourceFailed(RuntimeError):
    """Có tài sản chính mà nguồn lỗi; tài sản đó giữ dữ liệu cũ (stale_source)."""


def _lambda_setup() -> None:
    """Trong Lambda chỉ /tmp ghi được; yfinance mặc định ghi cache (múi giờ, cookie) vào thư mục
    người dùng nên phải chuyển sang /tmp trước lần tải đầu tiên."""
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        import yfinance

        # set_tz_cache_location đặt chung chỗ cho cache múi giờ, cookie và ISIN (yfinance 1.7)
        yfinance.set_tz_cache_location(os.getenv("YF_CACHE_DIR", "/tmp/yfinance-cache"))


def handler(event: dict | None, context=None) -> dict:
    event = event or {}
    _lambda_setup()
    if event.get("dry_run"):
        from .sources.yfinance_src import YFinanceSource

        result = ingest_prices.dry_run({"yfinance": YFinanceSource()})
        log.info("INGEST_DRY_RUN %s", result)
        return {"dry_run": True, "symbols": result}

    res = ingest_prices.run_ingest("s3", start=event.get("start"))
    summary = {
        "run_dt": res.run_dt,
        "status": res.report.get("status"),
        "stale_sources": res.report.get("stale_sources", {}),
        # tài sản thiếu phiên mới nhất (không phải lỗi nguồn): chỉ báo, không raise
        "stale_latest_session": sorted(res.report.get("stale_latest_session", {})),
        "written": len(res.written),
    }
    log.info("INGEST_DONE %s", summary)
    if not res.ok:
        raise IngestSourceFailed(f"stale sources: {sorted(summary['stale_sources'])}")
    return summary
