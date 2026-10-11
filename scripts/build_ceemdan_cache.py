"""Tạo cache IMF CEEMDAN theo khoảng ngày, chạy n tiến trình, tiếp tục được khi bị ngắt.

Chạy:
  python scripts/build_ceemdan_cache.py --assets gold --windows 252 504 \
      --start 2014-01-01 --end 2014-03-31 --processes 8
  python scripts/build_ceemdan_cache.py --verify ...   # kiểm lại price_hash của mọi cửa sổ

Đọc bản clean mới nhất trong data/lake (chuỗi cắt tại --end), ghi vào
data/lake/features/ceemdan/... (layout trong src/features/ceemdan_cache.py). Cấu hình CEEMDAN:
configs/ceemdan_cache.py. Từ chối --end sau 2019-12-31 cho tới khi khóa tham số (K3), trừ khi có
--allow-after-2019.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configs import ceemdan_cache as C
from src.data import storage
from src.features import ceemdan_cache as cc
from src.forecast.decomposition import CeemdanConfig


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--assets", nargs="+", default=C.ASSETS)
    ap.add_argument("--windows", nargs="+", type=int, default=C.WINDOWS)
    ap.add_argument("--start", default=C.DEFAULT_START)
    ap.add_argument("--end", required=True)
    ap.add_argument("--processes", type=int, default=1)
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"))
    ap.add_argument("--verify", action="store_true", help="kiểm lại price_hash mọi cửa sổ")
    ap.add_argument("--allow-after-2019", action="store_true")
    args = ap.parse_args(argv)
    if pd.Timestamp(args.end) > pd.Timestamp(C.MAX_END_BEFORE_LOCK) and not args.allow_after_2019:
        raise SystemExit(f"--end sau {C.MAX_END_BEFORE_LOCK}: chưa khóa tham số (K3)")

    st = storage.LocalStorage(args.lake_dir)
    dt = storage.latest_dt(st, "clean/prices", must_have="prices.parquet")
    prices = storage.read_parquet(st, f"clean/prices/dt={dt}/prices.parquet")
    prices = prices[prices["date"] <= pd.Timestamp(args.end)]  # không đọc dữ liệu sau --end
    report = {"input_dt": dt, "start": args.start, "end": args.end, "runs": []}
    pool = Pool(args.processes) if args.processes > 1 else None
    try:
        for asset in args.assets:
            dates, _ = cc.asset_series(prices, asset)
            origins = dates[(dates >= pd.Timestamp(args.start)) & (dates <= pd.Timestamp(args.end))]
            for window in args.windows:
                cfg = CeemdanConfig(
                    window=window,
                    trials=C.TRIALS,
                    epsilon=C.EPSILON,
                    seed=C.SEED,
                    keep_last=C.KEEP_LAST,
                )
                t0 = time.perf_counter()
                stats = cc.ensure(
                    st,
                    prices,
                    asset,
                    cfg,
                    origins,
                    recheck=origins if args.verify else None,
                    pool=pool,
                    log=lambda m: print(m, flush=True),
                )
                wall = time.perf_counter() - t0
                run = {
                    "asset": asset,
                    "window": window,
                    "cfg_hash": cfg.hash(),
                    "origins": len(origins),
                    "computed": stats.computed,
                    "reused": stats.reused,
                    "skipped_no_history": stats.skipped_no_history,
                    "wall_s": round(wall, 2),
                    "s_per_computed_window": round(wall / stats.computed, 3)
                    if stats.computed
                    else None,
                }
                report["runs"].append(run)
                print(json.dumps(run), flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
