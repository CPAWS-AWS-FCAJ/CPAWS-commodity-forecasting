"""Bước 0 – probe nguồn giá: yfinance (5 mã) và EIA (RBRTE, RWTC) từ 2012-01-01.

Chạy:  python scripts/probe_sources.py [--start 2012-01-01]
- Lưu phản hồi thô vào data/lake/raw/<source>/dt=<hôm nay>/ (cùng layout S3, đã gitignore).
- Ghi báo cáo vào data/lake/probe/dt=<hôm nay>/probe_report.json và in tóm tắt ra màn hình.
- EIA: dùng API v2 nếu có EIA_API_KEY (từ .env hoặc biến môi trường); nếu không có thì
  dùng file lịch sử XLS công khai của EIA (cùng series). Key không bao giờ được in ra log.
Đây là script khảo sát một lần, không phải pipeline.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
LAKE = ROOT / "data" / "lake"
YF_TICKERS = {"GC=F": "gold", "SI=F": "silver", "BZ=F": "brent", "CL=F": "wti", "VND=X": "usd_vnd"}
EIA_SERIES = {"RBRTE": "brent", "RWTC": "wti"}
EIA_API_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
EIA_XLS_URL = "https://www.eia.gov/dnav/pet/hist_xls/{series}d.xls"
EIA_PAGE = 5000  # giới hạn số dòng mỗi lần gọi của EIA API v2
PAIRS = [("BZ=F", "RBRTE"), ("CL=F", "RWTC")]
VALID_RANGE = {"VND=X": (20_000.0, 30_000.0)}


def _raw_dir(source: str, run_dt: str) -> Path:
    d = LAKE / "raw" / source / f"dt={run_dt}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- yfinance ----------


def fetch_yf(ticker: str, start: str, run_dt: str) -> tuple[pd.DataFrame, dict]:
    """Tải lịch sử ngày, không điều chỉnh; lưu CSV thô (giữ nguyên index có múi giờ) + metadata."""
    t = yf.Ticker(ticker)
    df = t.history(start=start, interval="1d", auto_adjust=False, actions=False)
    meta = t.get_history_metadata() or {}
    out = _raw_dir("yfinance", run_dt)
    safe = ticker.replace("=", "_")
    df.to_csv(out / f"{safe}.csv")
    keep = (
        "exchangeName",
        "fullExchangeName",
        "exchangeTimezoneName",
        "timezone",
        "gmtoffset",
        "instrumentType",
        "currency",
        "firstTradeDate",
        "regularMarketTime",
    )
    meta_small = {k: meta.get(k) for k in keep if k in meta}
    (out / f"{safe}.meta.json").write_text(json.dumps(meta_small, default=str, indent=2))
    return df, meta_small


# ---------- EIA ----------


def fetch_eia_api(series: str, start: str, api_key: str, run_dt: str) -> pd.Series:
    """EIA API v2, phân trang theo offset; lưu từng trang JSON gzip."""
    rows, offset, page = [], 0, 0
    while True:
        params = {
            "api_key": api_key,
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": series,
            "start": start,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset": offset,
            "length": EIA_PAGE,
        }
        r = requests.get(EIA_API_URL, params=params, timeout=60)
        r.raise_for_status()  # URL lỗi chứa key: không in r.url
        body = r.json()
        with gzip.open(_raw_dir("eia", run_dt) / f"{series}.p{page}.json.gz", "wt") as f:
            json.dump(body, f)
        data = body["response"]["data"]
        rows.extend(data)
        total = int(body["response"].get("total", len(rows)))
        offset += len(data)
        page += 1
        if not data or offset >= total:
            break
    s = pd.Series(
        {pd.Timestamp(d["period"]): float(d["value"]) for d in rows if d["value"] is not None}
    )
    return s.sort_index()


def fetch_eia_xls(series: str, start: str, run_dt: str) -> pd.Series:
    """File lịch sử công khai của EIA (không cần key), sheet 'Data 1', 2 dòng tiêu đề phụ."""
    r = requests.get(EIA_XLS_URL.format(series=series), timeout=60)
    r.raise_for_status()
    path = _raw_dir("eia", run_dt) / f"{series}d.xls"
    path.write_bytes(r.content)
    df = pd.read_excel(path, sheet_name="Data 1", skiprows=2)
    s = pd.Series(df.iloc[:, 1].values, index=pd.to_datetime(df.iloc[:, 0])).astype(float).dropna()
    return s[s.index >= pd.Timestamp(start)].sort_index()


# ---------- phân tích ----------


def _naive_dates(df_or_s) -> pd.DatetimeIndex:
    idx = df_or_s.index
    return pd.DatetimeIndex(idx.tz_localize(None) if idx.tz is not None else idx).normalize()


def gaps_over(dates: pd.DatetimeIndex, max_bdays: int = 4) -> list[dict]:
    """Khoảng trống giữa 2 phiên liên tiếp có > max_bdays ngày làm việc (T2–T6) bị thiếu."""
    d = dates.values.astype("datetime64[D]")
    missing = np.busday_count(d[:-1] + 1, d[1:])
    idx = np.where(missing > max_bdays)[0]
    return [{"from": str(d[i]), "to": str(d[i + 1]), "missing_bdays": int(missing[i])} for i in idx]


def jump_days(close: pd.Series, z: float = 6.0, top: int = 15) -> list[dict]:
    """Ngày có |log return| vượt z lần độ lệch chuẩn robust (MAD) của 250 phiên trước (chỉ lùi)."""
    p = close[close > 0]
    r = np.log(p).diff()
    mad = r.abs().rolling(250, min_periods=60).median().shift(1) * 1.4826
    score = (r.abs() / mad.replace(0, np.nan)).dropna()  # MAD = 0 (tỷ giá đứng) → bỏ qua
    hits = score[score > z].sort_values(ascending=False).head(top)
    return [
        {
            "date": str(i.date()),
            "log_ret": round(float(r[i]), 4),
            "z_mad": round(float(v), 1),
            "day": i.day,
            "weekday": i.day_name(),
        }
        for i, v in hits.sort_index().items()
    ]


def series_report(name: str, close: pd.Series, extra: dict | None = None) -> dict:
    dates = _naive_dates(close)
    s = pd.Series(close.values, index=dates).dropna()
    per_year = s.groupby(s.index.year).size().to_dict()
    weekend = int((s.index.dayofweek >= 5).sum())
    dup = int(s.index.duplicated().sum())
    stale = int((s.diff() == 0).sum())
    rep = {
        "name": name,
        "first_date": str(s.index.min().date()) if len(s) else None,
        "last_date": str(s.index.max().date()) if len(s) else None,
        "n_obs": len(s),
        "per_year": {int(k): int(v) for k, v in per_year.items()},
        "gaps_gt_4_bdays": gaps_over(s.index),
        "weekend_rows": weekend,
        "duplicate_dates": dup,
        "unchanged_vs_prev_day": stale,
        "non_positive": [{"date": str(i.date()), "price": float(v)} for i, v in s[s <= 0].items()],
        "jumps": jump_days(s),
    }
    if extra:
        rep.update(extra)
    return rep


def yf_extra_checks(df: pd.DataFrame, valid_range: tuple[float, float] | None = None) -> dict:
    """Dấu hiệu bất thường riêng của yfinance: thanh lặp volume (ngày lễ/thanh chưa chốt),
    hợp đồng ít thanh khoản (Close == Open), giá ngoài khoảng hợp lệ."""
    d = df.copy()
    d.index = _naive_dates(d)
    vol = d["Volume"]
    same_vol = d[(vol == vol.shift(1)) & (vol > 0)]
    rep = {
        "same_volume_as_prev": [str(i.date()) for i in same_vol.index],
        "close_eq_open_frac": round(float((d["Close"] == d["Open"]).mean()), 3),
        "median_volume_by_year": {
            int(k): int(v) for k, v in vol.groupby(d.index.year).median().items()
        },
    }
    if valid_range:
        lo, hi = valid_range
        bad = d[(d["Close"] < lo) | (d["Close"] > hi)]
        rep["out_of_range"] = {str(i.date()): float(v) for i, v in bad["Close"].items()}
    return rep


def window(s: pd.Series, center: str, days: int = 4) -> dict:
    c = pd.Timestamp(center)
    w = s[(s.index >= c - pd.Timedelta(days=days)) & (s.index <= c + pd.Timedelta(days=days))]
    return {str(i.date()): round(float(v), 2) for i, v in w.items()}


def compare(fut: pd.Series, spot: pd.Series) -> dict:
    """So mức giá và log return 1 ngày giữa hợp đồng gần (yfinance) và giá giao ngay EIA."""
    df = pd.concat({"fut": fut, "spot": spot}, axis=1, join="inner").dropna()
    pos = df[(df > 0).all(axis=1)]
    pct = (pos["fut"] / pos["spot"] - 1) * 100
    r = np.log(pos).diff().dropna()
    lag = {}
    for k in (-1, 0, 1):
        # k = +1: return future ngày t so với return spot ngày t+1
        lag[str(k)] = round(float(r["fut"].corr(r["spot"].shift(-k))), 4)
    big = pct[pct.abs() > 3]
    # Phần dư return (future − spot): ngày roll hợp đồng thường lộ ra ở đây
    res = r["fut"] - r["spot"]
    res_big = res[res.abs() > 0.03]
    return {
        "residual_logret_gt_3pct": len(res_big),
        "residual_gt_3pct_by_day_of_month": {
            int(k): int(v)
            for k, v in pd.Series(res_big.index.day).value_counts().sort_index().items()
        },
        "residual_top": {
            str(i.date()): round(float(res[i]), 3) for i in res.abs().nlargest(12).index
        },
        "level_diff_pct_median_by_year": {
            int(k): round(float(v), 2) for k, v in pct.groupby(pct.index.year).median().items()
        },
        "n_common_days": len(df),
        "level_diff_pct_median": round(float(pct.median()), 3),
        "level_diff_abs_pct_median": round(float(pct.abs().median()), 3),
        "level_diff_pct_max_abs": round(float(pct.abs().max()), 2),
        "level_diff_pct_max_date": str(pct.abs().idxmax().date()),
        "days_abs_diff_gt_3pct": len(big),
        "days_abs_diff_gt_3pct_by_year": {
            int(k): int(v) for k, v in big.groupby(big.index.year).size().items()
        },
        "corr_logret_1d_by_lag": lag,
        "days_only_in_fut": len(fut.index.difference(spot.index)),
        "days_only_in_spot": len(spot.index.difference(fut.index)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2012-01-01")
    args = ap.parse_args()
    run_dt = datetime.now(UTC).date().isoformat()
    load_dotenv(ROOT / ".env")
    report: dict = {
        "run_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "start": args.start,
        "yfinance_version": yf.__version__,
        "series": {},
    }

    closes: dict[str, pd.Series] = {}
    for tk in YF_TICKERS:
        df, meta = fetch_yf(tk, args.start, run_dt)
        idx = df.index
        tz_info = {
            "index_tz": str(idx.tz),
            "index_time_of_day": sorted({str(t.time()) for t in idx[-300:]}),
            "meta": meta,
            "last_5": {
                str(i): {
                    c: (None if pd.isna(df.loc[i, c]) else round(float(df.loc[i, c]), 4))
                    for c in ("Open", "High", "Low", "Close", "Volume")
                }
                for i in idx[-5:]
            },
        }
        tz_info.update(yf_extra_checks(df, VALID_RANGE.get(tk)))
        closes[tk] = pd.Series(df["Close"].values, index=_naive_dates(df))
        report["series"][tk] = series_report(tk, df["Close"], tz_info)

    key = os.getenv("EIA_API_KEY") or ""
    eia_mode = "api_v2" if key else "public_xls"
    report["eia_mode"] = eia_mode
    for sid in EIA_SERIES:
        s = (
            fetch_eia_api(sid, args.start, key, run_dt)
            if key
            else fetch_eia_xls(sid, args.start, run_dt)
        )
        closes[sid] = s
        report["series"][sid] = series_report(sid, s)

    report["wti_2020_04"] = {
        "CL=F": window(closes["CL=F"], "2020-04-20"),
        "RWTC": window(closes["RWTC"], "2020-04-20"),
    }
    report["fut_vs_spot"] = {f"{a}~{b}": compare(closes[a], closes[b]) for a, b in PAIRS}

    out = LAKE / "probe" / f"dt={run_dt}"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    (out / "probe_report.json").write_text(text, encoding="utf-8")
    print(text)
    print(f"\nĐã lưu: {out / 'probe_report.json'}")


if __name__ == "__main__":
    main()
