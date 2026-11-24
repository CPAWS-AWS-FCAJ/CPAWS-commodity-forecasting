from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import calendars, storage
from src.data.config import ASSETS
from src.forecast import predict
from src.forecast.forecast_record import PRICE_UNIT

# Lý do bỏ ngày của last_price_display (display_factor_missing / display_factor_stale). Lớp này
# riêng của predict; import để bắt đúng lý do, không chép lại quy tắc factor.
from src.forecast.predict import _Skip as PredictSkip

EXPORT_ASSETS: tuple[str, ...] = predict.PREDICT_ASSETS
SERVING_PREFIX = "serving/price-history"  # Lambda: PRICE_HISTORY_PREFIX = serving/price-history/
DEFAULT_OUT_DIR = "data/serving/price-history"
DEFAULT_SESSIONS = 520  # bằng HISTORY_MAX của infra/lambda/forecast_api/handler.py
SOURCE_LABEL = "Yahoo Finance (yfinance)"
CONTENT_TYPE = "application/json"
# Số chữ số thập phân khi ghi (USD/oz cho vàng, bạc; USD/bbl cho dầu)
PRICE_DECIMALS = {"gold": 2, "silver": 2, "brent": 2, "wti": 2}

REASON_NONPOSITIVE = "nonpositive_price"
REASON_NOT_SESSION = "not_a_session"
REASON_REJECTED = "rejected"
REASON_DUPLICATE = "duplicate_date"

log = logging.getLogger("cpaws.export_price_history")


@dataclass
class AssetExport:
    asset: str
    points: list[dict] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    written_to: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.points)

    def summary(self) -> dict:
        return {
            "points": len(self.points),
            "first_base_date": self.points[0]["base_date"] if self.points else None,
            "last_base_date": self.points[-1]["base_date"] if self.points else None,
            "skipped": dict(sorted(self.skipped.items())),
            "written_to": self.written_to,
        }


def _asset_snapshot(snap: predict.Snapshot, asset: str) -> predict.Snapshot:
    """Snapshot chỉ còn dòng của asset (đọc nhanh hơn khi gọi last_price_display nhiều lần)."""
    p, f, r = snap.prices, snap.factors, snap.rejected
    return dataclasses.replace(
        snap,
        prices=p.loc[p["asset"] == asset].reset_index(drop=True),
        rejected=r.loc[r["asset"] == asset].reset_index(drop=True),
        factors=None if f is None else f.loc[f["asset"] == asset].reset_index(drop=True),
    )


def candidate_dates(snap: predict.Snapshot, asset: str, skipped: Counter) -> pd.DatetimeIndex:
    """Ngày có đúng một giá hợp lệ của asset, xếp cũ → mới: phiên của lịch tài sản, giá hữu hạn
    > 0, không nằm trong rejected.parquet. Ngày bị bỏ được đếm vào `skipped` theo lý do."""
    rows = snap.prices.loc[snap.prices["asset"] == asset]
    dates = pd.DatetimeIndex(pd.to_datetime(rows["date"])).normalize()
    price = pd.to_numeric(rows["price"], errors="coerce").to_numpy(dtype=float)
    keep = np.ones(len(dates), dtype=bool)

    rej = snap.rejected
    rejected = pd.DatetimeIndex(pd.to_datetime(rej.loc[rej["asset"] == asset, "date"])).normalize()
    checks = (
        (REASON_NOT_SESSION, dates.isin(calendars.sessions(ASSETS[asset].calendar))),
        (REASON_REJECTED, ~dates.isin(rejected)),
        (REASON_NONPOSITIVE, np.isfinite(price) & (price > 0)),
        (REASON_DUPLICATE, ~dates.duplicated(keep=False)),
    )
    for reason, ok in checks:
        ok = np.asarray(ok, dtype=bool)
        skipped[reason] += int((keep & ~ok).sum())
        keep &= ok
    return dates[keep].sort_values()


def price_points(snap: predict.Snapshot, asset: str, sessions: int) -> AssetExport:
    """Tối đa `sessions` điểm {base_date, last_price} gần nhất, xếp cũ → mới.

    Đi từ ngày mới nhất về trước, bỏ ngày last_price_display từ chối (thiếu factor / factor quá
    trễ), dừng khi đủ `sessions` điểm."""
    out = AssetExport(asset)
    sub = _asset_snapshot(snap, asset)
    digits = PRICE_DECIMALS[asset]
    for day in reversed(candidate_dates(sub, asset, out.skipped)):
        if len(out.points) == sessions:
            break
        try:
            value = predict.last_price_display(sub, asset, day)
        except PredictSkip as s:
            out.skipped[s.reason] += 1
            continue
        if not (math.isfinite(value) and value > 0):
            out.skipped[REASON_NONPOSITIVE] += 1
            continue
        out.points.append({"base_date": str(day.date()), "last_price": round(value, digits)})
    out.points.reverse()
    return out


def history_document(
    export: AssetExport, *, generated_at: datetime, snapshot_dt: str | None = None
) -> dict:
    """Nội dung file serving/price-history/<asset>.json (Lambda forecasts-api đọc)."""
    doc = {
        "asset": export.asset,
        "unit": PRICE_UNIT[export.asset],
        "source": SOURCE_LABEL,
        "generated_at": generated_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_base_date": export.points[-1]["base_date"],
        "points": export.points,
    }
    if snapshot_dt is not None:
        doc["input_snapshot_dt"] = snapshot_dt  # dt= của snapshot clean đã dùng (truy vết)
    return doc


def _encode(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def write_local(out_dir: str | Path, asset: str, doc: dict) -> str:
    path = Path(out_dir) / f"{asset}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_encode(doc))
    return str(path)


def write_s3(st: storage.S3Storage, asset: str, doc: dict) -> str:
    """Ghi đè s3://<bucket>/<root>serving/price-history/<asset>.json, ContentType JSON."""
    key = f"{st.root}{SERVING_PREFIX}/{asset}.json"
    st.s3.put_object(Bucket=st.bucket, Key=key, Body=_encode(doc), ContentType=CONTENT_TYPE)
    return f"s3://{st.bucket}/{key}"


def export(
    st,
    *,
    sessions: int = DEFAULT_SESSIONS,
    as_of: str | None = None,
    assets: tuple[str, ...] = EXPORT_ASSETS,
    dest: str = "local",
    out_dir: str | Path = DEFAULT_OUT_DIR,
    dest_st: storage.S3Storage | None = None,
    now: datetime | None = None,
) -> dict[str, AssetExport]:
    """Đọc snapshot mới nhất từ `st`, (cắt tại as_of), ghi file cho từng tài sản có điểm."""
    if sessions < 1:
        raise ValueError("sessions must be >= 1")
    if dest == "s3" and dest_st is None:
        raise ValueError("dest_st is required with dest='s3'")
    snap = predict.load_snapshot(st)
    if as_of is not None:
        snap = predict.cut_snapshot(snap, as_of)
    generated_at = now or datetime.now(UTC)
    results: dict[str, AssetExport] = {}
    for asset in assets:
        res = price_points(snap, asset, sessions)
        results[asset] = res
        if not res.ok:
            log.error("PRICE_HISTORY_EMPTY asset=%s skipped=%s", asset, dict(res.skipped))
            continue
        if len(res.points) < sessions:
            log.warning(
                "PRICE_HISTORY_SHORT asset=%s points=%d requested=%d",
                asset,
                len(res.points),
                sessions,
            )
        doc = history_document(res, generated_at=generated_at, snapshot_dt=snap.dt)
        if dest == "s3":
            res.written_to = write_s3(dest_st, asset, doc)
        else:
            res.written_to = write_local(out_dir, asset, doc)
        log.info(
            "PRICE_HISTORY_WRITTEN asset=%s points=%d to=%s", asset, len(res.points), res.written_to
        )
    return results


def _iso_date(s: str) -> str:
    try:
        return str(pd.Timestamp(s).date())
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid date {s!r}, expected YYYY-MM-DD") from e


def _positive_int(s: str) -> int:
    try:
        n = int(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid integer {s!r}") from e
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Xuất một lần chuỗi giá cuối phiên dài (mặc định 520 phiên, ~2 năm) cho biểu đồ lịch sử của web"
    )
    ap.add_argument("--source", choices=["local", "s3"], default="local")
    ap.add_argument("--lake-dir", default="data/lake", help="lake local khi --source local")
    ap.add_argument("--dest", choices=["local", "s3"], default="local")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="thư mục JSON khi --dest local")
    ap.add_argument("--sessions", type=_positive_int, default=DEFAULT_SESSIONS)
    ap.add_argument(
        "--as-of", type=_iso_date, default=None, help="ngày cuối (mặc định: dữ liệu mới nhất)"
    )
    ap.add_argument("--assets", nargs="+", choices=EXPORT_ASSETS, default=list(EXPORT_ASSETS))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    st = predict.make_storage(args.source, args.lake_dir)
    dest_st = None
    if args.dest == "s3":
        dest_st = st if isinstance(st, storage.S3Storage) else predict.make_storage("s3")
        if dest_st.root:
            # Lambda đọc PRICE_HISTORY_PREFIX ở gốc bucket; ghi dưới LAKE_PREFIX thì API không bao giờ
            # thấy file → dừng trước khi ghi bất cứ thứ gì.
            log.error(
                "EXPORT_PREFIX_MISMATCH LAKE_PREFIX=%r: Lambda reads %s at the bucket root; "
                "unset LAKE_PREFIX to export to S3",
                dest_st.root,
                SERVING_PREFIX,
            )
            return 2
    results = export(
        st,
        sessions=args.sessions,
        as_of=args.as_of,
        assets=tuple(args.assets),
        dest=args.dest,
        out_dir=args.out_dir,
        dest_st=dest_st,
    )
    print(json.dumps({a: r.summary() for a, r in results.items()}, indent=2, ensure_ascii=False))
    return 0 if all(r.ok for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
