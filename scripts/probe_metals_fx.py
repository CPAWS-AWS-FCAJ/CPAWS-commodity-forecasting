"""Bước 0b – probe nguồn vàng, bạc: GLD/SLV qua yfinance, NBP; snapshot thanh gần nhất.

Chạy:
  python scripts/probe_metals_fx.py               # toàn bộ probe 0b (không cần key)
  python scripts/probe_metals_fx.py --bars-only   # chỉ chụp 5 thanh gần nhất và so với các lần chụp trước
- Tiingo đã bị gỡ (điều khoản gói Starter, xem ADR-0005); script không gọi Tiingo.
- Phản hồi thô: data/lake/raw/<source>/dt=<ngày chạy UTC>/. Báo cáo: data/lake/probe/dt=<ngày>/.
- NBP và WGC chỉ là chuỗi đối chiếu, không đưa vào pipeline.
Đây là script khảo sát, không phải pipeline.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from probe_sources import LAKE, gaps_over

NBP = "https://api.nbp.pl/api"
NBP_MAX_DAYS = 93
OZ_G = 31.1034768
BAR_TICKERS = ["GC=F", "SI=F", "BZ=F", "CL=F", "GLD", "SLV"]
PERIODS = {"2012-2019": ("2012-01-01", "2019-12-31"), "2020-now": ("2020-01-01", "2100-01-01")}


def _raw_dir(source: str, run_dt: str) -> Path:
    d = LAKE / "raw" / source / f"dt={run_dt}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_json(path: Path, obj: object) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f)


# ---------- chất lượng một chuỗi ----------


def quality(df: pd.DataFrame) -> dict:
    """df: index ngày (naive), cột close, open, (volume)."""
    s = df["close"].dropna()
    rep = {
        "first_date": str(s.index.min().date()),
        "last_date": str(s.index.max().date()),
        "n_obs": len(s),
        "per_year": {int(k): int(v) for k, v in s.groupby(s.index.year).size().items()},
        "gaps_gt_4_bdays": gaps_over(s.index),
        "weekend_rows": int((s.index.dayofweek >= 5).sum()),
        "pct_close_same_as_prev": round(float((s.diff() == 0).mean() * 100), 2),
        "pct_close_eq_open": round(float((df["close"] == df["open"]).mean() * 100), 2),
    }
    if "volume" in df:
        v = df["volume"]
        rep["median_volume_by_year"] = {
            int(k): int(x) for k, x in v.groupby(v.index.year).median().items()
        }
    return rep


def compare_returns(a: pd.Series, b: pd.Series, na: str, nb: str, top: int = 10) -> dict:
    """Tương quan log return 1 ngày (lệch k: a[t] với b[t+k]) theo giai đoạn + phần dư lớn nhất."""
    df = pd.concat({na: a, nb: b}, axis=1, join="inner").dropna()
    df = df[(df > 0).all(axis=1)]
    r = np.log(df).diff().dropna()
    out: dict = {"n_common_days": len(df)}
    for name, (lo, hi) in PERIODS.items():
        rp = r.loc[lo:hi]
        if len(rp) < 30:
            continue
        out[name] = {
            "n": len(rp),
            "corr_by_lag": {
                str(k): round(float(rp[na].corr(rp[nb].shift(-k))), 4) for k in (-1, 0, 1)
            },
        }
        res = rp[na] - rp[nb]
        out[name]["top_residuals"] = [
            {
                "date": str(i.date()),
                "resid": round(float(res[i]), 4),
                f"{na}_ret": round(float(rp.loc[i, na]), 4),
                f"{nb}_ret": round(float(rp.loc[i, nb]), 4),
                na: round(float(df.loc[i, na]), 3),
                nb: round(float(df.loc[i, nb]), 3),
            }
            for i in res.abs().nlargest(top).index
        ]
    return out


# ---------- nguồn ----------


def nbp_chunks(path_fmt: str, start: str, run_dt: str, name: str) -> tuple[list, int]:
    """Gọi NBP theo khúc ≤ 93 ngày; 404 = không có dữ liệu trong khúc đó."""
    rows, n_req = [], 0
    d0 = pd.Timestamp(start)
    today = pd.Timestamp(datetime.now(UTC).date())
    chunks = []
    while d0 <= today:
        d1 = min(d0 + timedelta(days=NBP_MAX_DAYS - 1), today)
        url = f"{NBP}/{path_fmt.format(a=d0.date(), b=d1.date())}"
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=60)
        n_req += 1
        if r.status_code == 200:
            body = r.json()
            chunks.append(body)
            rows.extend(body["rates"] if isinstance(body, dict) else body)
        elif r.status_code != 404:
            print(f"[nbp] {name} {d0.date()}..{d1.date()} -> HTTP {r.status_code}")
        d0 = d1 + timedelta(days=1)
        time.sleep(0.1)
    _save_json(_raw_dir("nbp", run_dt) / f"{name}.json.gz", chunks)
    return rows, n_req


def nbp_gold_usd_oz(run_dt: str) -> tuple[pd.Series, dict]:
    gold, n1 = nbp_chunks("cenyzlota/{a}/{b}", "2013-01-02", run_dt, "cenyzlota")
    usd, n2 = nbp_chunks("exchangerates/rates/a/usd/{a}/{b}", "2013-01-02", run_dt, "usd_pln")
    g = pd.Series({pd.Timestamp(x["data"]): float(x["cena"]) for x in gold}).sort_index()
    u = pd.Series({pd.Timestamp(x["effectiveDate"]): float(x["mid"]) for x in usd}).sort_index()
    df = pd.concat({"pln_g": g, "usdpln": u}, axis=1, join="inner").dropna()
    s = df["pln_g"] * OZ_G / df["usdpln"]
    info = {
        "requests": n1 + n2,
        "gold_first": str(g.index.min().date()) if len(g) else None,
        "gold_last": str(g.index.max().date()) if len(g) else None,
        "usd_first": str(u.index.min().date()) if len(u) else None,
        "n_gold": len(g),
        "n_joined": len(s),
        "gold_per_year": {int(k): int(v) for k, v in g.groupby(g.index.year).size().items()},
    }
    return s, info


def yf_daily(ticker: str, start: str, run_dt: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=False, actions=False)
    df.to_csv(_raw_dir("yfinance", run_dt) / f"{ticker.replace('=', '_')}.csv")
    df = df.rename(columns=str.lower)
    df.index = df.index.tz_localize(None).normalize()
    return df


def load_yf_raw(ticker: str) -> pd.DataFrame | None:
    """Dùng lại CSV thô gần nhất từ probe Bước 0 nếu có."""
    files = sorted((LAKE / "raw" / "yfinance").glob(f"dt=*/{ticker.replace('=', '_')}.csv"))
    if not files:
        return None
    df = pd.read_csv(files[-1], index_col=0)
    df.index = pd.to_datetime(df.index.str[:10])
    return df.rename(columns=str.lower)


# ---------- e. snapshot thanh gần nhất ----------


def snapshot_bars() -> dict:
    snap_dir = LAKE / "probe" / "bars"
    snap_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    snap = {"fetched_at_utc": now.isoformat(timespec="seconds"), "bars": {}}
    for tk in BAR_TICKERS:
        df = yf.Ticker(tk).history(period="10d", interval="1d", auto_adjust=False, actions=False)
        snap["bars"][tk] = {
            str(i.date()): {"close": round(float(r.Close), 4), "volume": int(r.Volume)}
            for i, r in df.tail(5).iterrows()
        }
    prev = sorted(snap_dir.glob("snap_*.json"))
    (snap_dir / f"snap_{now.strftime('%Y%m%dT%H%M%SZ')}.json").write_text(
        json.dumps(snap, indent=2), encoding="utf-8"
    )
    history = [json.loads(p.read_text(encoding="utf-8")) for p in prev] + [snap]
    changes = []
    for tk in BAR_TICKERS:
        dates = sorted({d for h in history for d in h["bars"].get(tk, {})})
        for d in dates:
            seen = [
                (h["fetched_at_utc"], h["bars"][tk][d])
                for h in history
                if d in h["bars"].get(tk, {})
            ]
            vals = [json.dumps(v, sort_keys=True) for _, v in seen]
            if len(set(vals)) > 1:
                changes.append({"ticker": tk, "date": d, "versions": seen})
    return {"n_snapshots": len(history), "latest": snap, "changed_bars": changes}


# ---------- main ----------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2012-01-01")
    ap.add_argument("--bars-only", action="store_true")
    args = ap.parse_args()
    run_dt = datetime.now(UTC).date().isoformat()
    out = LAKE / "probe" / f"dt={run_dt}"
    out.mkdir(parents=True, exist_ok=True)

    bars = snapshot_bars()
    if args.bars_only:
        text = json.dumps(bars, indent=2, default=str)
        (out / "bars_report.json").write_text(text, encoding="utf-8")
        print(text)
        return

    rep: dict = {"run_at_utc": datetime.now(UTC).isoformat(timespec="seconds"), "bars": bars}

    # a. GLD, SLV qua yfinance (dùng lại CSV thô trong lake nếu có)
    tg = {}
    rep["etf_yfinance"] = {}
    for tk in ("GLD", "SLV"):
        df = load_yf_raw(tk)
        if df is None:
            df = yf_daily(tk, args.start, run_dt)
        tg[tk] = df
        q = quality(df[["open", "close", "volume"]])
        if "adj close" in df:
            diff = (df["adj close"] / df["close"] - 1).abs()
            q["adjclose_differs_days"] = int((diff > 1e-9).sum())
        rep["etf_yfinance"][tk] = q

    # b. So sánh vàng, bạc
    gc, si = load_yf_raw("GC=F"), load_yf_raw("SI=F")
    rep["compare"] = {}
    if "GLD" in tg and gc is not None:
        rep["compare"]["GLD~GC=F"] = compare_returns(tg["GLD"]["close"], gc["close"], "GLD", "GC=F")
    if "SLV" in tg and si is not None:
        rep["compare"]["SLV~SI=F"] = compare_returns(tg["SLV"]["close"], si["close"], "SLV", "SI=F")

    nbp, nbp_info = nbp_gold_usd_oz(run_dt)
    rep["nbp"] = nbp_info
    if len(nbp):
        if "GLD" in tg:
            rep["compare"]["NBP~GLD"] = compare_returns(nbp, tg["GLD"]["close"], "NBP", "GLD")
        if gc is not None:
            rep["compare"]["NBP~GC=F"] = compare_returns(nbp, gc["close"], "NBP", "GC=F")

    # Tỷ lệ quy đổi ETF → USD/oz theo năm (trung vị), chỉ để hiển thị sau này
    ratios = {}
    if "GLD" in tg:
        for ref_name, ref in (("NBP", nbp), ("GC=F", gc["close"] if gc is not None else None)):
            if ref is not None and len(ref):
                x = (tg["GLD"]["close"] / ref).dropna()
                ratios[f"GLD/{ref_name}"] = {
                    int(k): round(float(v), 5) for k, v in x.groupby(x.index.year).median().items()
                }
    if "SLV" in tg and si is not None:
        x = (tg["SLV"]["close"] / si["close"]).dropna()
        ratios["SLV/SI=F"] = {
            int(k): round(float(v), 5) for k, v in x.groupby(x.index.year).median().items()
        }
    rep["etf_oz_ratio_by_year"] = ratios

    wgc = LAKE / "raw" / "wgc" / "gold_monthly_avg.xlsx"
    rep["wgc"] = (
        "file present: comparison not implemented yet"
        if wgc.exists()
        else "file not found, skipped"
    )

    # d. BZ=F, CL=F: volume theo năm; vì sao BZ=F thiếu phiên 2012–2013
    bz, cl = load_yf_raw("BZ=F"), load_yf_raw("CL=F")
    if bz is not None and cl is not None:
        miss = cl.loc["2012":"2013"].index.difference(bz.index)
        rep["brent_wti"] = {
            "median_volume_by_year": {
                "BZ=F": {
                    int(k): int(v) for k, v in bz["volume"].groupby(bz.index.year).median().items()
                },
                "CL=F": {
                    int(k): int(v) for k, v in cl["volume"].groupby(cl.index.year).median().items()
                },
            },
            "bz_missing_vs_cl_2012_2013": [str(d.date()) for d in miss],
            "bz_missing_day_of_month": pd.Series(miss.day).value_counts().sort_index().to_dict(),
            "bz_missing_weekday": pd.Series(miss.day_name()).value_counts().to_dict(),
        }

    text = json.dumps(rep, indent=2, ensure_ascii=False, default=str)
    (out / "probe_0b_report.json").write_text(text, encoding="utf-8")
    print(f"Saved: {out / 'probe_0b_report.json'}")


if __name__ == "__main__":
    main()
