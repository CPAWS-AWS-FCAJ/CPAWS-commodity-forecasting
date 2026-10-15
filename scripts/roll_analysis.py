"""Phân tích roll của CL=F, BZ=F và đợt CL=F lệch RWTC 9–10/2026 (docs/experiments/roll-analysis-2026-10.md).

Chạy: python scripts/roll_analysis.py [--lake-dir data/lake] [--raw-dt 2026-10-08]
In JSON ra stdout. Chỉ đọc dữ liệu, không ghi gì.

Phần 1 (dữ liệu 2026): return ngày CL=F so với BZ=F, chênh lệch Brent–WTI so với trung vị 60 phiên
trước đó, và độ lệch CL=F/RWTC, BZ=F/RBRTE so với trung vị 60 phiên trước đó.
Phần 2 (chỉ 2014–2019, cắt dữ liệu tại 31/12/2019 ngay khi đọc): ngày roll theo quy tắc
(flag roll) so với ngày Yahoo chuyển hợp đồng nhận biết từ volume (raw yfinance) và từ phần dư
return so với hợp đồng kia; |return| ngày roll; roll trùng ngày; sai số của việc thay return
ngày roll bằng return của hợp đồng kia, ước lượng trên ngày không roll.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import storage
from src.data.clean import split_flags
from src.data.quality import EXCLUDE_REF

P1 = ("2026-09-15", "2026-10-09")
P2_END = "2019-12-31"
PERIODS = {"2014_2018": ("2014-01-01", "2018-12-31"), "2019": ("2019-01-01", "2019-12-31")}
WIN = 3  # tìm ngày chuyển thật trong ±3 phiên quanh ngày roll theo quy tắc
MED = 60


def load_clean(lake: Path):
    st = storage.LocalStorage(lake)
    dt = storage.latest_dt(st, "clean/prices", must_have="prices.parquet")
    p = storage.read_parquet(st, f"clean/prices/dt={dt}/prices.parquet")
    r = storage.read_parquet(st, f"clean/reference_prices/dt={dt}/reference.parquet")
    return dt, p, r


def series(df, asset, exclude=None) -> pd.Series:
    d = df[df["asset"] == asset]
    if exclude:
        d = d[~d["flag"].map(lambda f: bool(split_flags(f) & exclude))]
    return pd.Series(d["price"].to_numpy(), index=pd.DatetimeIndex(d["date"])).sort_index()


def flagged(df, asset, flag) -> pd.DatetimeIndex:
    d = df[(df["asset"] == asset) & df["flag"].map(lambda f: flag in split_flags(f))]
    return pd.DatetimeIndex(d["date"]).sort_values()


def raw_volume(lake: Path, raw_dt: str, symbol: str) -> pd.Series:
    path = lake / "raw" / "yfinance" / f"dt={raw_dt}" / f"{symbol.replace('=', '_')}.csv.gz"
    df = pd.read_csv(io.BytesIO(gzip.decompress(path.read_bytes())))
    idx = pd.DatetimeIndex(pd.to_datetime(df["Date"].str[:10]))
    return pd.Series(df["Volume"].to_numpy(dtype=float), index=idx)


def trailing_median_dev(x: pd.Series) -> pd.Series:
    return x - x.shift(1).rolling(MED, min_periods=20).median()


def part1(p, r) -> dict:
    cl, bz = series(p, "wti"), series(p, "brent")
    rw, rb = series(r, "rwtc", EXCLUDE_REF), series(r, "rbrte", EXCLUDE_REF)
    j = pd.concat({"cl": cl, "bz": bz}, axis=1, join="inner")
    j = j[(j > 0).all(axis=1)]
    ret = np.log(j).diff() * 100
    spread = np.log(j["bz"] / j["cl"]) * 100
    cl_rw = pd.concat({"f": cl, "s": rw}, axis=1, join="inner")
    cl_rw = np.log(cl_rw["f"] / cl_rw["s"]) * 100
    bz_rb = pd.concat({"f": bz, "s": rb}, axis=1, join="inner")
    bz_rb = np.log(bz_rb["f"] / bz_rb["s"]) * 100
    rw_ret = np.log(rw).diff() * 100
    cl_rw_ret = np.log(pd.concat({"f": cl, "s": rw}, axis=1, join="inner")).diff() * 100
    t = pd.DataFrame(
        {
            "r_cl": ret["cl"],
            "r_bz": ret["bz"],
            "r_cl_minus_r_bz": ret["cl"] - ret["bz"],
            "spread_bz_cl_dev_vs_med60": trailing_median_dev(spread),
            "cl_vs_rwtc_dev_vs_med60": trailing_median_dev(cl_rw).reindex(j.index),
            "bz_vs_rbrte_dev_vs_med60": trailing_median_dev(bz_rb).reindex(j.index),
            "r_rwtc": rw_ret.reindex(j.index),
            "r_cl_minus_r_rwtc": (cl_rw_ret["f"] - cl_rw_ret["s"]).reindex(j.index),
        }
    ).loc[P1[0] : P1[1]]
    rolls = {
        a: [str(d.date()) for d in flagged(p, a, "roll") if P1[0] <= str(d.date()) <= P1[1]]
        for a in ("wti", "brent")
    }
    rows = [
        {
            "date": str(d.date()),
            **{k: (None if pd.isna(v) else round(float(v), 2)) for k, v in row.items()},
        }
        for d, row in t.iterrows()
    ]
    return {
        "last_price_date": str(j.index.max().date()),
        "last_rwtc_date": str(rw.index.max().date()),
        "last_rbrte_date": str(rb.index.max().date()),
        "roll_days": rolls,
        "rows": rows,
    }


def detect_switch(rule_days, idx: pd.DatetimeIndex, score: pd.Series) -> list[dict]:
    """Với mỗi ngày roll theo quy tắc, ngày có score lớn nhất trong ±WIN phiên (theo dòng)."""
    out = []
    pos = pd.Series(np.arange(len(idx)), index=idx)
    for d in rule_days:
        if d not in pos.index:
            continue
        i = int(pos[d])
        lo, hi = max(i - WIN, 1), min(i + WIN, len(idx) - 1)
        w = score.iloc[lo : hi + 1]
        if w.isna().all():
            continue
        best = int(np.nanargmax(w.to_numpy()))
        srt = np.sort(w.dropna().to_numpy())[::-1]
        out.append(
            {
                "rule_day": d,
                "detected": w.index[best],
                "offset": lo + best - i,
                "score": float(srt[0]),
                "margin": float(srt[0] - srt[1]) if len(srt) > 1 else float("nan"),
            }
        )
    return out


def q(x) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if not len(x):
        return {"n": 0}
    return {
        "n": len(x),
        "median": round(float(np.median(x)), 3),
        "p90": round(float(np.quantile(x, 0.9)), 3),
        "mean": round(float(x.mean()), 3),
    }


def part2(p, lake: Path, raw_dt: str) -> dict:
    end = pd.Timestamp(P2_END)
    p = p[p["date"] <= end]  # không dùng dữ liệu sau 2019
    out: dict = {}
    s = {a: series(p, a) for a in ("wti", "brent")}
    s = {a: v[v > 0] for a, v in s.items()}
    r = {a: np.log(v).diff() for a, v in s.items()}  # return theo dòng của chính tài sản
    rolls = {a: flagged(p, a, "roll") for a in ("wti", "brent")}
    vol = {
        a: raw_volume(lake, raw_dt, sym).loc[:end]
        for a, sym in (("wti", "CL=F"), ("brent", "BZ=F"))
    }
    j = pd.concat({"wti": r["wti"], "brent": r["brent"]}, axis=1, join="inner").dropna()
    resid = (j["wti"] - j["brent"]).abs()

    det: dict = {}
    for a in ("wti", "brent"):
        idx = s[a].index
        v = vol[a].reindex(idx)
        dv = np.log(v.where(v > 0)).diff()  # tăng volume mạnh nhất = ngày chuyển sang hợp đồng mới
        rule = [d for d in rolls[a] if d >= pd.Timestamp("2014-01-01")]
        by_vol = detect_switch(rule, idx, dv)
        by_res = detect_switch(rule, idx, resid.reindex(idx))
        agree = {x["rule_day"]: x["detected"] for x in by_vol}
        n_agree = sum(1 for x in by_res if agree.get(x["rule_day"]) == x["detected"])
        det[a] = {"by_volume": by_vol, "by_resid": by_res}
        out[f"{a}_switch"] = {
            "n_rule_rolls": len(rule),
            "volume_offset_counts": pd.Series([x["offset"] for x in by_vol])
            .value_counts()
            .sort_index()
            .to_dict(),
            "resid_offset_counts": pd.Series([x["offset"] for x in by_res])
            .value_counts()
            .sort_index()
            .to_dict(),
            "volume_jump_x_median": round(float(np.exp(np.median([x["score"] for x in by_vol]))), 2)
            if by_vol
            else None,
            "volume_margin_median_log": round(float(np.nanmedian([x["margin"] for x in by_vol])), 2)
            if by_vol
            else None,
            "n_volume_and_resid_agree": n_agree,
            "n_volume_zero_or_missing": int((vol[a].reindex(idx).fillna(0) <= 0).sum()),
        }

    # |return| ngày roll (theo quy tắc và theo volume) so với ngày thường
    for a in ("wti", "brent"):
        rule = set(rolls[a]) | set(rolls["brent" if a == "wti" else "wti"])
        detected = {x["detected"] for k in ("wti", "brent") for x in det[k]["by_volume"]}
        ra = r[a].dropna()
        for per, (lo, hi) in PERIODS.items():
            x = ra.loc[lo:hi].abs() * 100
            normal = x[~x.index.isin(list(rule | detected))]
            out[f"{a}_absret_{per}"] = {
                "normal_days": q(normal),
                "rule_roll_days": q(x[x.index.isin(list(rolls[a]))]),
                "volume_switch_days": q(
                    x[x.index.isin([d["detected"] for d in det[a]["by_volume"]])]
                ),
            }

    # Roll trùng ngày
    cl_r, bz_r = set(rolls["wti"]), set(rolls["brent"])
    near = sum(1 for d in cl_r if any(abs((d - b).days) <= 1 for b in bz_r))
    cl_v = {x["detected"] for x in det["wti"]["by_volume"]}
    bz_v = {x["detected"] for x in det["brent"]["by_volume"]}
    out["same_day_rolls"] = {
        "rule_same_day": sorted(
            str(d.date()) for d in cl_r & bz_r if d >= pd.Timestamp("2014-01-01")
        ),
        "rule_within_1_day": near,
        "volume_switch_same_day": sorted(str(d.date()) for d in cl_v & bz_v),
    }

    # Thay return ngày roll bằng return hợp đồng kia: sai số ước lượng trên ngày không roll
    excl = cl_r | bz_r | cl_v | bz_v
    for per, (lo, hi) in PERIODS.items():
        jj = j.loc[lo:hi] * 100
        normal = jj[~jj.index.isin(list(excl))]
        err = normal["wti"] - normal["brent"]
        roll_cl = jj[jj.index.isin(list(cl_r | cl_v))]
        roll_bz = jj[jj.index.isin(list(bz_r | bz_v))]
        out[f"substitution_{per}"] = {
            "n_normal_days": len(normal),
            "corr_normal": round(float(normal["wti"].corr(normal["brent"])), 3),
            "abs_err_normal": q(err.abs()),
            "rmse_normal": round(float(np.sqrt((err**2).mean())), 3),
            "baseline_zero_mae_cl": round(float(normal["wti"].abs().mean()), 3),
            "baseline_zero_mae_bz": round(float(normal["brent"].abs().mean()), 3),
            "abs_diff_on_cl_roll_days": q((roll_cl["wti"] - roll_cl["brent"]).abs()),
            "abs_diff_on_bz_roll_days": q((roll_bz["brent"] - roll_bz["wti"]).abs()),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"))
    ap.add_argument("--raw-dt", default="2026-10-08", help="dt của file raw yfinance có đủ lịch sử")
    args = ap.parse_args()
    lake = Path(args.lake_dir)
    dt, p, r = load_clean(lake)
    res = {
        "input_dt": dt,
        "raw_dt": args.raw_dt,
        "part1": part1(p, r),
        "part2": part2(p, lake, args.raw_dt),
    }
    print(json.dumps(res, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
