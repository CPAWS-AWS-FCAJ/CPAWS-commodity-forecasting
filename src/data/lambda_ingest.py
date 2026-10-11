"""Lambda ingest giá (bàn giao: docs/handoff/ingest-lambda.md).

Entrypoint: src.data.lambda_ingest.handler. Lịch: config.INGEST_SCHEDULE_EXPRESSION (UTC).
Biến môi trường: LAKE_BUCKET (bắt buộc trên AWS), LAKE_PREFIX (tùy chọn), EIA_SECRET_ID (tùy chọn;
thiếu thì bỏ đối chiếu EIA), CPAWS_ENV.

event:
  {}                     chạy thường lệ: tải lại 5 phiên gần nhất, ghi raw/ và clean/ lên S3
  {"start": "YYYY-MM-DD"} tải lại từ ngày đó (ví dụ nạp lịch sử lần đầu)
  {"dry_run": true}      chỉ tải GLD, SLV, CL=F, BZ=F, VND=X cho 10 phiên gần nhất, không ghi gì;
                         trả về số dòng và lỗi từng mã (kiểm tra Yahoo có chặn IP AWS không)
Khi có nguồn chính lỗi: dữ liệu các tài sản khác vẫn được ghi, log INGEST_SOURCE_FAILED, rồi raise
IngestSourceFailed để Lambda tính là lỗi (metric Errors của CloudWatch). Không dùng sys.exit.
"""

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
        "written": len(res.written),
    }
    log.info("INGEST_DONE %s", summary)
    if not res.ok:
        raise IngestSourceFailed(f"stale sources: {sorted(summary['stale_sources'])}")
    return summary
