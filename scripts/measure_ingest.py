"""Đo thời gian và bộ nhớ đỉnh của ingest (để đặt memory/timeout cho Lambda). Gọi mạng thật.

Chạy (mỗi chế độ một tiến trình riêng để số bộ nhớ không lẫn nhau):
  python scripts/measure_ingest.py --mode daily --lake-dir <thư mục tạm có sẵn bản clean cũ>
  python scripts/measure_ingest.py --mode full  --lake-dir <thư mục tạm rỗng>
In JSON: wall_s, rss_after_import_mb, peak_rss_mb (Windows: peak working set; Linux: ru_maxrss).
Không ghi vào data/lake thật nếu --lake-dir trỏ ra thư mục tạm.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _peak_mb() -> float:
    import psutil

    mi = psutil.Process().memory_info()
    peak = getattr(mi, "peak_wset", None)  # Windows
    if peak is None:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB
    return peak / 2**20


def _rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 2**20


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "full"], required=True)
    ap.add_argument("--lake-dir", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    from dotenv import load_dotenv

    from src.data import ingest_prices

    load_dotenv()
    rss_import = _rss_mb()
    t0 = time.perf_counter()
    res = ingest_prices.run_ingest(
        "local", args.lake_dir, start="2012-01-01" if args.mode == "full" else None
    )
    wall = time.perf_counter() - t0
    fetch = res.report["run"]["fetch_log"]
    print(
        json.dumps(
            {
                "mode": args.mode,
                "wall_s": round(wall, 1),
                "rss_after_import_mb": round(rss_import, 0),
                "peak_rss_mb": round(_peak_mb(), 0),
                "status": res.report.get("status"),
                "start": res.report["run"]["start"],
                "rows": len(res.prices),
                "requests": sum(x.get("requests", 0) for x in fetch),
                "fetch_errors": [x for x in fetch if x["status"] != "ok"],
            }
        )
    )


if __name__ == "__main__":
    main()
