"""Thu thập giá → raw → clean (Parquet dạng dài) → quality.json. Cùng code cho local, S3 và Lambda.

Chạy:
  python -m src.data.ingest_prices --start 2012-01-01 --dest local   # tải toàn bộ lịch sử
  python -m src.data.ingest_prices --dest local                     # tăng dần: tải lại 5 phiên gần nhất
Key: EIA_API_KEY (.env khi chạy local; Lambda đọc từ nơi lưu secret). yfinance không cần key.

Xử lý lỗi nguồn (theo từng tài sản):
- Nguồn của một tài sản chính (ASSETS) lỗi hoặc trả rỗng: tài sản đó giữ dữ liệu clean của lần
  trước, dòng cuối của nó gắn flag "stale_source"; quality.json có stale_sources[asset] =
  {last_date, status, error}. Các tài sản khác vẫn cập nhật và bản clean mới vẫn được ghi. Log dòng
  ERROR có mã INGEST_SOURCE_FAILED (cho CloudWatch metric filter) và thoát mã 1.
  Lần chạy thành công sau tải lại từ phiên thứ REFETCH_SESSIONS tính từ cuối của tài sản cũ nhất,
  nên khoảng trống được bù và flag stale_source tự mất (dòng bị ghi đè theo khóa).
- Nguồn tham chiếu (EIA, GC=F, SI=F, NBP) lỗi: log WARNING INGEST_REFERENCE_FAILED, giữ bản tham
  chiếu cũ, thoát mã 0.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field

import pandas as pd
import requests

from . import clean, quality, storage
from .config import ASSETS, REFERENCES, REFETCH_SESSIONS, SOURCE_ATTRIBUTION, START_DATE, AssetSpec
from .sources import FetchResult, SourceError

PRICES = "clean/prices"
REFS = "clean/reference_prices"
FACTORS = "clean/display_factors"
DISPLAY_FX = "clean/display_fx"

log_ = logging.getLogger("cpaws.ingest")


@dataclass
class RunResult:
    run_dt: str
    prices: pd.DataFrame
    rejected: pd.DataFrame
    references: pd.DataFrame
    factors: pd.DataFrame
    report: dict
    written: list[str] = field(default_factory=list)
    ok: bool = True
    fx: pd.DataFrame | None = None


def _fail(log: list, spec: AssetSpec, status: str, error: str, primary: bool) -> None:
    ref = spec.primary
    entry = {"asset": spec.asset, "source": ref.source, "symbol": ref.symbol, "status": status}
    if error:
        entry["error"] = error
    log.append(entry)
    code, level = (
        ("INGEST_SOURCE_FAILED", logging.ERROR)
        if primary
        else ("INGEST_REFERENCE_FAILED", logging.WARNING)
    )
    log_.log(
        level,
        "%s asset=%s source=%s symbol=%s status=%s error=%s",
        code,
        spec.asset,
        ref.source,
        ref.symbol,
        status,
        error,
    )


def _fetch(
    sources: dict, spec: AssetSpec, start: str, log: list, primary: bool
) -> FetchResult | None:
    """Tải từ nguồn của tài sản; lỗi hoặc rỗng được ghi vào log và trả về None."""
    ref = spec.primary
    src = sources.get(ref.source)
    if src is None:
        _fail(log, spec, "source_unavailable", "", primary)
        return None
    try:
        res = src.fetch(ref.symbol, start)
    except Exception as e:  # noqa: BLE001 - mọi lỗi adapter phải vào log, không hỏng bản clean
        msg = str(e) if isinstance(e, SourceError) else f"{type(e).__name__}: {e}"
        _fail(log, spec, "error", msg, primary)
        return None
    if res.bars is None or res.bars.empty:
        _fail(log, spec, "empty", "no bars returned", primary)
        return None
    log.append(
        {
            "asset": spec.asset,
            "source": ref.source,
            "symbol": ref.symbol,
            "status": "ok",
            "rows": len(res.bars),
            "requests": res.n_requests,
        }
    )
    return res


def _load_prev(st, run_dt: str) -> dict[str, pd.DataFrame | None]:
    out: dict[str, pd.DataFrame | None] = {"prices": None, "rejected": None, "references": None}
    dt = storage.latest_dt(st, PRICES, run_dt, must_have="prices.parquet")
    if dt:
        out["prices"] = storage.read_parquet(st, f"{PRICES}/dt={dt}/prices.parquet")
        if st.exists(f"{PRICES}/dt={dt}/rejected.parquet"):
            out["rejected"] = storage.read_parquet(st, f"{PRICES}/dt={dt}/rejected.parquet")
    rdt = storage.latest_dt(st, REFS, run_dt, must_have="reference.parquet")
    if rdt:
        out["references"] = storage.read_parquet(st, f"{REFS}/dt={rdt}/reference.parquet")
    return out


def _incremental_start(prev: pd.DataFrame | None) -> str:
    """Ngày của phiên thứ REFETCH_SESSIONS tính từ cuối, lấy sớm nhất giữa các tài sản."""
    if prev is None or prev.empty:
        return START_DATE
    starts = [
        g["date"].sort_values().iloc[-min(REFETCH_SESSIONS, len(g))]
        for _, g in prev.groupby("asset")
    ]
    return str(pd.Timestamp(min(starts)).date())


def _collect(specs: dict[str, AssetSpec], sources, start, now, st, run_dt, log, written, primary):
    acc, rej, failed = [], [], []
    for spec in specs.values():
        res = _fetch(sources, spec, start, log, primary)
        if res is None:
            failed.append(spec.asset)
            continue
        written.append(st.write_bytes(f"raw/{res.source}/dt={run_dt}/{res.raw_name}", res.raw))
        a, r = clean.bars_to_long(res.bars, spec, res.source, now)
        acc.append(a)
        rej.append(r)
    return acc, rej, failed


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [f for f in frames if not f.empty]
    return (
        clean.normalize_types(pd.concat(frames, ignore_index=True))
        if frames
        else clean.empty_frame()
    )


def run(
    st,
    sources: dict,
    start: str | None = None,
    now: pd.Timestamp | None = None,
    nbp_source=None,
) -> RunResult:
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    now = now.tz_localize("UTC") if now.tz is None else now.tz_convert("UTC")
    run_dt = str(now.date())
    prev = _load_prev(st, run_dt)
    start = start or _incremental_start(prev["prices"])
    log: list[dict] = []
    written: list[str] = []

    acc, rej, failed = _collect(ASSETS, sources, start, now, st, run_dt, log, written, True)

    # Tài sản lỗi không có dòng mới nên merge_snapshot giữ nguyên dữ liệu cũ của nó
    new_acc, new_rej = _concat(acc), _concat(rej)
    keys = pd.concat([new_acc[clean.KEY], new_rej[clean.KEY]], ignore_index=True)
    prices = clean.merge_snapshot(prev["prices"], new_acc, keys)
    rejected = clean.merge_snapshot(prev["rejected"], new_rej, keys)
    # Spike (VND=X): đưa spike cũ về rồi tính lại trên toàn bộ lịch sử mỗi lần chạy
    prices, rejected = quality.restore_spikes(prices, rejected)
    prices, spikes = quality.reject_spikes(prices)
    rejected = clean.merge_snapshot(rejected, spikes, spikes[clean.KEY])

    racc, rrej, _ = _collect(REFERENCES, sources, start, now, st, run_dt, log, written, False)
    new_ref = _concat(racc)
    ref_keys = pd.concat([new_ref[clean.KEY], _concat(rrej)[clean.KEY]], ignore_index=True)
    refs = clean.merge_snapshot(prev["references"], new_ref, ref_keys)

    prices = quality.apply_series_flags(prices, refs)
    prices, stale = quality.mark_stale_sources(prices, failed, log)
    if failed:
        log_.error(
            "INGEST_PARTIAL kept previous data for %s",
            ", ".join(f"{a} (last {stale[a]['last_date']})" for a in failed),
        )
    factors = quality.display_factors(prices, refs)
    fx = quality.display_fx(prices)

    nbp = None
    if nbp_source is not None:
        try:
            res = nbp_source.fetch_gold_usd_oz(start, run_dt)
            written.append(st.write_bytes(f"raw/nbp/dt={run_dt}/{res.raw_name}", res.raw))
            nbp = res.bars["close"]
            log.append(
                {
                    "asset": "nbp_gold",
                    "source": "nbp",
                    "status": "ok",
                    "rows": len(nbp),
                    "requests": res.n_requests,
                }
            )
        except (SourceError, requests.RequestException, ValueError, KeyError) as e:
            # nguồn đối chiếu lỗi không dừng pipeline
            log.append({"asset": "nbp_gold", "source": "nbp", "status": "error", "error": str(e)})
            log_.warning("INGEST_REFERENCE_FAILED asset=nbp_gold source=nbp error=%s", e)

    report = quality.build_report(prices, rejected, refs, factors, nbp, fx)
    report["status"] = "partial" if failed else "ok"
    report["stale_sources"] = stale
    report["run"] = {
        "run_at_utc": now.isoformat(timespec="seconds"),
        "start": start,
        "source_attribution": SOURCE_ATTRIBUTION,
        "fetch_log": log,
    }
    base = f"dt={run_dt}"
    written += [
        storage.write_parquet(st, f"{PRICES}/{base}/prices.parquet", prices),
        storage.write_parquet(st, f"{PRICES}/{base}/rejected.parquet", rejected),
        storage.write_parquet(st, f"{REFS}/{base}/reference.parquet", refs),
        storage.write_parquet(st, f"{FACTORS}/{base}/display_factors.parquet", factors),
        storage.write_parquet(st, f"{DISPLAY_FX}/{base}/display_fx.parquet", fx),
        storage.write_json(st, f"{PRICES}/{base}/quality.json", report),
    ]
    return RunResult(run_dt, prices, rejected, refs, factors, report, written, ok=not failed, fx=fx)


def build_sources() -> tuple[dict, object]:
    """Tạo adapter từ biến môi trường; thiếu EIA_API_KEY thì bỏ đối chiếu EIA."""
    from .sources.eia import EIASource
    from .sources.nbp import NBPSource
    from .sources.yfinance_src import YFinanceSource

    sources: dict = {"yfinance": YFinanceSource()}
    if os.getenv("EIA_API_KEY", "").strip():
        sources["eia"] = EIASource(os.environ["EIA_API_KEY"].strip())
    return sources, NBPSource()


def summarize(report: dict) -> str:
    lines = ["asset     rows   first       last        flags / rejected"]
    for a, r in report["assets"].items():
        lines.append(
            f"{a:<9} {r.get('n_rows', 0):>5}  {r.get('first_date', '-'):<10}  "
            f"{r.get('last_date', '-'):<10}  {r.get('flags', {})} / {r.get('rejected', {})}"
        )
    errors = [x for x in report["run"]["fetch_log"] if x["status"] != "ok"]
    if errors:
        lines.append(f"fetch problems: {errors}")
    for a, s in (report.get("stale_sources") or {}).items():
        lines.append(f"STALE {a}: kept data up to {s['last_date']} ({s['status']})")
    fx = report.get("display_fx") or {}
    if fx:
        pending = "pending_confirm" in str(fx["flag"])
        lines.append(
            f"display_fx: {fx['rate']:.0f} ({fx['rate_date']}) flag={fx['flag'] or '-'}"
            + (f" pending {fx['pending_rate']:.0f} ({fx['pending_date']})" if pending else "")
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Mã thoát: 0 = mọi nguồn chính OK; 1 = có nguồn chính lỗi (clean vẫn ghi, tài sản lỗi giữ
    dữ liệu cũ với flag stale_source)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default=None, help="YYYY-MM-DD; bỏ trống = tải lại 5 phiên gần nhất")
    ap.add_argument("--dest", choices=["local", "s3"], default="local")
    ap.add_argument("--lake-dir", default="data/lake")
    ap.add_argument("--no-nbp", action="store_true", help="bỏ đối chiếu NBP")
    args = ap.parse_args(argv)

    from dotenv import load_dotenv

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    from .config import lake_bucket

    st = (
        storage.LocalStorage(args.lake_dir)
        if args.dest == "local"
        else storage.S3Storage(lake_bucket())
    )
    sources, nbp = build_sources()
    res = run(st, sources, start=args.start, nbp_source=None if args.no_nbp else nbp)
    print(summarize(res.report))
    print(f"\nwritten {len(res.written)} files; last: {res.written[-1] if res.written else '-'}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
