"""Cờ theo chuỗi, đối chiếu chéo, hệ số hiển thị và báo cáo quality.json (ADR-0005).

Cờ theo chuỗi (chỉ đánh dấu, tính lại trên toàn bộ lịch sử mỗi lần chạy):
  stale        phiên thứ >= STALE_RUN liên tiếp có giá y hệt (nhân quả: chỉ nhìn lùi)
  jump         |log return 1 ngày| > ngưỡng của tài sản, trừ ngày trong KNOWN_EVENTS
  roll         phiên đầu tiên sau ngày đáo hạn hợp đồng (CL, BZ); không dùng chuỗi back-adjusted
  xcheck_level wti: CL=F / RWTC lệch > 3% so với trung vị trượt 60 phiên trước đó (nhân quả)
  xcheck_resid brent: |r(BZ=F) - r(CL=F)| > 8% (cùng giờ chốt 14:30 ET)
Loại spike (tài sản có reject_spikes, hiện chỉ USD/VND): vọt > ngưỡng rồi quay về gần mức cũ trong
tối đa SPIKE_MAX_SESSIONS phiên → cả đoạn sang rejected với "bad_value|spike". display_fx giữ tỷ giá
hiển thị ở phiên trước cú vọt chưa xét xong ("pending_confirm"), không sửa prices.
RBRTE chỉ đối chiếu mức giá (chênh lệch trung vị theo năm). NBP chỉ đối chiếu mức giá và trung bình
tháng của vàng (chốt giá trưa Warsaw nên không so return ngày).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import calendars
from .clean import ROW_FLAGS, join_flags, split_flags
from .config import (
    ASSETS,
    DISPLAY_FACTOR_WINDOW,
    KNOWN_EVENTS,
    NBP_MONTHLY_TOL,
    SPIKE_MAX_SESSIONS,
    STALE_RUN,
    XCHECK_BRENT_RESID,
    XCHECK_WTI_LEVEL,
    XCHECK_WTI_MIN_PERIODS,
    XCHECK_WTI_WINDOW,
)

SERIES_FLAGS = {"stale", "jump", "roll", "xcheck_level", "xcheck_resid"}
EXCLUDE_REF = {"known_source_error", "suspect_holiday_row"}


def _series(df: pd.DataFrame, asset: str, exclude: set[str] | None = None) -> pd.Series:
    d = df[df["asset"] == asset]
    if exclude and len(d):
        bad = d["flag"].map(lambda f: bool(split_flags(f) & exclude)).astype(bool)
        d = d.loc[~bad]
    return pd.Series(d["price"].to_numpy(), index=pd.DatetimeIndex(d["date"])).sort_index()


def _known(asset: str) -> frozenset:
    return frozenset(pd.Timestamp(x) for x in KNOWN_EVENTS.get(asset, set()))


def _logret(s: pd.Series) -> pd.Series:
    s = s[s > 0]
    return np.log(s).diff().dropna()


def stale_mask(s: pd.Series, run: int = STALE_RUN) -> pd.Series:
    """Nhân quả: phiên t bị đánh dấu nếu là phiên thứ >= run liên tiếp có giá y hệt (chỉ nhìn lùi)."""
    same = s.eq(s.shift(1))
    grp = (~same).cumsum()
    count = s.groupby(grp).cumcount() + 1
    return count >= run


def _jump_starts(s: pd.Series, threshold: float, exempt=frozenset()) -> np.ndarray:
    """Vị trí i (>= 1) có |ln(P[i]/P[i-1])| > ngưỡng, trừ ngày trong exempt."""
    lp = np.log(s.to_numpy(dtype=float))
    big = np.abs(np.diff(lp)) > threshold
    idx = np.where(big)[0] + 1
    return np.array([i for i in idx if pd.Timestamp(s.index[i]) not in exempt], dtype=int)


def spike_mask(
    s: pd.Series,
    threshold: float,
    max_sessions: int = SPIKE_MAX_SESSIONS,
    exempt=frozenset(),
) -> pd.Series:
    """Spike theo đoạn: phiên t vọt |ln(P[t]/P[t-1])| > ngưỡng, rồi trong tối đa max_sessions phiên
    sau đó có phiên t+k quay về gần giá cũ (|ln(P[t+k]/P[t-1])| < ngưỡng/2) → loại cả đoạn t..t+k-1.
    Cần tới max_sessions phiên sau t nên các phiên cuối chưa xét xong (lớp hiển thị giữ
    "pending_confirm", xem display_fx); mỗi lần chạy tính lại trên toàn bộ lịch sử. Đây là làm sạch
    lỗi nguồn (dùng phiên sau t), không phải đặc trưng; USD/VND không vào mô hình."""
    s = s[s > 0]
    lp = np.log(s.to_numpy(dtype=float))
    n = len(lp)
    mask = np.zeros(n, dtype=bool)
    last, i = 0, 1  # last: phiên được giữ gần nhất (mốc "mức cũ")
    while i < n:
        if abs(lp[i] - lp[last]) > threshold and pd.Timestamp(s.index[i]) not in exempt:
            back = next(
                (
                    j
                    for j in range(i + 1, min(i + max_sessions, n - 1) + 1)
                    if abs(lp[j] - lp[last]) < threshold / 2
                ),
                None,
            )
            if back is not None:
                mask[i:back] = True
                i = back  # phiên quay về được so lại với cùng mốc, không bị coi là cú vọt mới
                continue
        last, i = i, i + 1
    return pd.Series(mask, index=s.index)


def restore_spikes(
    prices: pd.DataFrame, rejected: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Đưa các dòng spike đã loại ở lần chạy trước về prices để tính lại spike trên toàn bộ lịch sử
    (kết quả chỉ phụ thuộc dữ liệu, không phụ thuộc thứ tự các lần chạy)."""
    if rejected.empty:
        return prices, rejected
    is_spike = rejected["flag"].map(lambda f: "spike" in split_flags(f)).astype(bool)
    back = rejected.loc[is_spike].copy()
    back["flag"] = [join_flags(split_flags(f) & ROW_FLAGS) for f in back["flag"]]
    prices = pd.concat([prices, back], ignore_index=True)
    prices = prices.sort_values(["date", "asset"], kind="stable").reset_index(drop=True)
    return prices, rejected.loc[~is_spike].reset_index(drop=True)


def reject_spikes(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tách các dòng spike của tài sản có reject_spikes=True, gắn flag "bad_value|spike"."""
    drop = pd.Series(False, index=prices.index)
    for asset, spec in ASSETS.items():
        if not spec.reject_spikes:
            continue
        d = prices[prices["asset"] == asset].sort_values("date")
        if len(d) < 3:
            continue
        s = pd.Series(d["price"].to_numpy(), index=pd.DatetimeIndex(d["date"]))
        m = spike_mask(s, spec.jump_threshold, exempt=_known(asset))
        m = pd.Series(m.reindex(s.index, fill_value=False).to_numpy(), index=d.index)
        drop.loc[m[m].index] = True
    spikes = prices.loc[drop].copy()
    spikes["flag"] = [
        join_flags((split_flags(f) & ROW_FLAGS) | {"bad_value", "spike"}) for f in spikes["flag"]
    ]
    return prices.loc[~drop].reset_index(drop=True), spikes.reset_index(drop=True)


def series_flags(prices: pd.DataFrame, refs: pd.DataFrame) -> dict[str, dict[pd.Timestamp, set]]:
    """{asset: {date: {flags}}} cho các cờ theo chuỗi."""
    out: dict[str, dict[pd.Timestamp, set]] = {a: {} for a in ASSETS}

    def add(asset: str, dates, flag: str) -> None:
        for d in dates:
            out[asset].setdefault(pd.Timestamp(d), set()).add(flag)

    for asset, spec in ASSETS.items():
        s = _series(prices, asset)
        if s.empty:
            continue
        st = stale_mask(s)
        add(asset, s.index[st.to_numpy()], "stale")
        r = _logret(s)
        known = {pd.Timestamp(x) for x in KNOWN_EVENTS.get(asset, set())}
        big = r[(r.abs() > spec.jump_threshold) & ~r.index.isin(list(known))]
        add(asset, big.index, "jump")
        if spec.roll_rule:
            add(asset, calendars.roll_days(spec.roll_rule, s.index), "roll")

    dev = wti_level_deviation(prices, refs)
    add("wti", dev.index[(dev.abs() > XCHECK_WTI_LEVEL).to_numpy()], "xcheck_level")

    res = _brent_resid(prices)
    add("brent", res.index[(res.abs() > XCHECK_BRENT_RESID).to_numpy()], "xcheck_resid")
    return out


def _wti_rwtc_ratio(prices: pd.DataFrame, refs: pd.DataFrame) -> pd.Series:
    wti, rwtc = _series(prices, "wti"), _series(refs, "rwtc", EXCLUDE_REF)
    j = pd.concat({"f": wti, "s": rwtc}, axis=1, join="inner").dropna()
    j = j[(j > 0).all(axis=1)]
    return j["f"] / j["s"]


def wti_level_deviation(prices: pd.DataFrame, refs: pd.DataFrame) -> pd.Series:
    """Độ lệch của CL=F/RWTC so với trung vị trượt XCHECK_WTI_WINDOW phiên chung trước đó (chỉ
    nhìn lùi, không gồm t); thiếu lịch sử thì so với 1,0."""
    ratio = _wti_rwtc_ratio(prices, refs)
    base = ratio.shift(1).rolling(XCHECK_WTI_WINDOW, min_periods=XCHECK_WTI_MIN_PERIODS).median()
    return ratio / base.fillna(1.0) - 1


def _brent_wti_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Log return 1 ngày của BZ=F và CL=F trên ngày chung; bỏ ngày giá <= 0 (WTI 20/4/2020)."""
    bz, cl = _series(prices, "brent"), _series(prices, "wti")
    j = pd.concat({"bz": bz, "cl": cl}, axis=1, join="inner").dropna()
    j = j[(j > 0).all(axis=1)]
    return np.log(j).diff().dropna()


def _brent_resid(prices: pd.DataFrame) -> pd.Series:
    r = _brent_wti_returns(prices)
    return r["bz"] - r["cl"]


def apply_series_flags(prices: pd.DataFrame, refs: pd.DataFrame) -> pd.DataFrame:
    """Xóa cờ theo chuỗi cũ, giữ cờ theo dòng (ROW_FLAGS), gắn cờ theo chuỗi mới."""
    sf = series_flags(prices, refs)
    out = prices.copy()
    new_flags = []
    for a, d, f in zip(out["asset"], out["date"], out["flag"], strict=True):
        keep = split_flags(f) & ROW_FLAGS
        new_flags.append(join_flags(keep | sf.get(a, {}).get(pd.Timestamp(d), set())))
    out["flag"] = new_flags
    return out


def mark_stale_sources(
    prices: pd.DataFrame, failed: list[str], fetch_log: list[dict]
) -> tuple[pd.DataFrame, dict]:
    """Gắn "stale_source" vào dòng cuối của từng tài sản có nguồn lỗi (giữ dữ liệu lần trước).
    Trả về (prices, {asset: {last_date, status, error}}); last_date = None nếu chưa có dữ liệu."""
    out = prices.copy()
    info: dict[str, dict] = {}
    for asset in failed:
        entry = next((x for x in fetch_log if x.get("asset") == asset), {})
        d = out[out["asset"] == asset]
        last = None
        if len(d):
            i = d["date"].idxmax()
            out.loc[i, "flag"] = join_flags(split_flags(out.loc[i, "flag"]) | {"stale_source"})
            last = str(pd.Timestamp(out.loc[i, "date"]).date())
        info[asset] = {
            "last_date": last,
            "status": entry.get("status", "error"),
            "error": entry.get("error", ""),
        }
    return out, info


def display_factors(prices: pd.DataFrame, refs: pd.DataFrame) -> pd.DataFrame:
    """Hệ số quy đổi ETF → USD/oz, chỉ để hiển thị (không đưa vào train):
    factor[t] = trung vị DISPLAY_FACTOR_WINDOW phiên gần nhất (chỉ lùi) của (future / ETF)."""
    rows = []
    for asset, ref, reliability in (("gold", "gc_fut", "normal"), ("silver", "si_fut", "low")):
        etf, fut = _series(prices, asset), _series(refs, ref)
        j = pd.concat({"etf": etf, "fut": fut}, axis=1, join="inner").dropna()
        j = j[(j > 0).all(axis=1)]
        if j.empty:
            continue
        f = (j["fut"] / j["etf"]).rolling(DISPLAY_FACTOR_WINDOW, min_periods=5).median().dropna()
        rows.append(
            pd.DataFrame(
                {
                    "date": f.index,
                    "asset": asset,
                    "factor": f.to_numpy(),
                    "reference": ref,
                    "reliability": reliability,
                    "unit": "USD/oz per share",
                }
            )
        )
    if not rows:
        return pd.DataFrame(columns=["date", "asset", "factor", "reference", "reliability", "unit"])
    return pd.concat(rows, ignore_index=True)


DISPLAY_FX_COLUMNS = [
    "asset",
    "as_of_date",
    "rate_date",
    "rate",
    "unit",
    "published_at",
    "flag",
    "pending_date",
    "pending_rate",
]


def display_fx(prices: pd.DataFrame, asset: str = "usd_vnd") -> pd.DataFrame:
    """Tỷ giá dùng cho hiển thị (một dòng); không sửa prices.parquet.

    Nếu trong SPIKE_MAX_SESSIONS phiên gần nhất có phiên vọt > ngưỡng jump mà quy tắc spike chưa
    xét xong (chưa đủ phiên sau đó để biết giá có quay về không) → hiển thị giá phiên trước cú vọt,
    flag "pending_confirm". Lần chạy sau: nếu là spike thì dòng đó bị loại khỏi prices; nếu đã qua
    SPIKE_MAX_SESSIONS phiên mà không quay về thì coi là thay đổi thật và hiển thị giá mới nhất."""
    spec = ASSETS[asset]
    d = prices[prices["asset"] == asset].sort_values("date")
    d = d[d["price"] > 0]
    if d.empty:
        return pd.DataFrame(columns=DISPLAY_FX_COLUMNS)
    s = pd.Series(d["price"].to_numpy(), index=pd.DatetimeIndex(d["date"]))
    n = len(s)
    starts = _jump_starts(s, spec.jump_threshold, _known(asset)) if n > 1 else np.array([], int)
    undecided = [i for i in starts if n - 1 - i < SPIKE_MAX_SESSIONS]
    use = undecided[0] - 1 if undecided else n - 1
    row = d.iloc[use]
    flags = {"pending_confirm"} if undecided else set()
    if "stale_source" in split_flags(d.iloc[-1]["flag"]):
        flags.add("stale_source")  # nguồn lỗi ở lần chạy này: tỷ giá là của lần trước
    return pd.DataFrame(
        [
            {
                "asset": asset,
                "as_of_date": s.index[-1],
                "rate_date": s.index[use],
                "rate": float(s.iloc[use]),
                "unit": spec.unit,
                "published_at": row["published_at"],
                "flag": join_flags(flags),
                "pending_date": s.index[undecided[0]] if undecided else pd.NaT,
                "pending_rate": float(s.iloc[undecided[0]]) if undecided else float("nan"),
            }
        ],
        columns=DISPLAY_FX_COLUMNS,
    )


# ---------- báo cáo ----------


def gaps_over(dates: pd.DatetimeIndex, max_bdays: int = 4) -> list[dict]:
    d = pd.DatetimeIndex(dates).sort_values().to_numpy().astype("datetime64[D]")
    if len(d) < 2:
        return []
    missing = np.busday_count(d[:-1] + 1, d[1:])
    return [
        {"from": str(d[i]), "to": str(d[i + 1]), "missing_bdays": int(missing[i])}
        for i in np.where(missing > max_bdays)[0]
    ]


def _flag_counts(df: pd.DataFrame) -> dict[str, int]:
    c: dict[str, int] = {}
    for f in df["flag"]:
        for x in split_flags(f):
            c[x] = c.get(x, 0) + 1
    return dict(sorted(c.items()))


def _by_year(s: pd.Series, fn) -> dict[int, float]:
    return {int(k): v for k, v in s.groupby(s.index.year).apply(fn).items()}


def asset_report(prices: pd.DataFrame, rejected: pd.DataFrame, asset: str) -> dict:
    spec = ASSETS[asset]
    d = prices[prices["asset"] == asset]
    s = pd.Series(d["price"].to_numpy(), index=pd.DatetimeIndex(d["date"])).sort_index()
    rep: dict = {
        "n_rows": len(d),
        "unit": spec.unit,
        "sources": d["source"].value_counts().to_dict(),
    }
    if s.empty:
        return rep
    rep.update(
        {
            "first_date": str(s.index.min().date()),
            "last_date": str(s.index.max().date()),
            "rows_per_year": _by_year(s, len),
            "gaps_gt_4_bdays": gaps_over(s.index),
            "duplicate_dates": int(s.index.duplicated().sum()),
            "monotonic": bool(s.index.is_monotonic_increasing),
            "flags": _flag_counts(d),
            "rejected": _flag_counts(rejected[rejected["asset"] == asset]),
        }
    )
    if spec.calendar != "FX":
        cal = calendars.sessions(spec.calendar, s.index.min(), s.index.max())
        missing = cal.difference(s.index)
        rep["calendar"] = spec.calendar
        rep["missing_sessions"] = len(missing)
        rep["missing_sessions_by_year"] = {
            int(k): int(v) for k, v in pd.Series(missing.year).value_counts().sort_index().items()
        }
        rep["missing_sessions_sample"] = [str(x.date()) for x in missing[:20]]
    if spec.kind == "future":
        low = d["flag"].map(lambda f: "low_liquidity" in split_flags(f))
        low.index = pd.DatetimeIndex(d["date"])
        rep["low_liquidity_pct_by_year"] = {
            k: round(float(v) * 100, 2) for k, v in _by_year(low, np.mean).items()
        }
    return rep


def xcheck_report(prices: pd.DataFrame, refs: pd.DataFrame) -> dict:
    out: dict = {}
    ratio = _wti_rwtc_ratio(prices, refs)
    if len(ratio):
        pct = (ratio - 1) * 100
        dev = wti_level_deviation(prices, refs).abs() > XCHECK_WTI_LEVEL
        out["wti_vs_rwtc_level"] = {
            "n_common": len(ratio),
            "median_pct": round(float(pct.median()), 3),
            "abs_median_pct": round(float(pct.abs().median()), 3),
            "days_gt_3pct_vs_1": int((pct.abs() > XCHECK_WTI_LEVEL * 100).sum()),
            "days_flagged_vs_rolling_median": int(dev.sum()),
            "median_pct_by_year": {
                k: round(float(v), 2) for k, v in _by_year(pct, np.median).items()
            },
        }
    res = _brent_resid(prices)
    if len(res):
        r = _brent_wti_returns(prices)
        out["brent_vs_wti_returns"] = {
            "n": len(res),
            "days_resid_gt_8pct": int((res.abs() > XCHECK_BRENT_RESID).sum()),
            "corr_by_year": {
                int(y): round(float(g["bz"].corr(g["cl"])), 3) for y, g in r.groupby(r.index.year)
            },
        }
    bz, rb = _series(prices, "brent"), _series(refs, "rbrte", EXCLUDE_REF)
    j = pd.concat({"f": bz, "s": rb}, axis=1, join="inner").dropna()
    j = j[(j > 0).all(axis=1)]
    if len(j):
        pct = (j["f"] / j["s"] - 1) * 100
        out["brent_vs_rbrte_level"] = {
            "n_common": len(j),
            "median_pct_by_year": {
                k: round(float(v), 2) for k, v in _by_year(pct, np.median).items()
            },
        }
    return out


def nbp_report(prices: pd.DataFrame, factors: pd.DataFrame, nbp: pd.Series | None) -> dict:
    if nbp is None or nbp.empty:
        return {"status": "skipped"}
    gld = _series(prices, "gold")
    j = pd.concat({"gld": gld, "nbp": nbp}, axis=1, join="inner").dropna()
    out: dict = {"n_common": len(j)}
    if j.empty:
        return out
    ratio = j["gld"] / j["nbp"]
    out["gld_oz_per_share_by_year"] = {
        k: round(float(v), 5) for k, v in _by_year(ratio, np.median).items()
    }
    f = factors[factors["asset"] == "gold"]
    if len(f):
        fs = pd.Series(f["factor"].to_numpy(), index=pd.DatetimeIndex(f["date"]))
        usd_oz = (gld * fs).dropna()
        m = pd.concat(
            {"gold_usd_oz": usd_oz.resample("ME").mean(), "nbp": nbp.resample("ME").mean()}, axis=1
        ).dropna()
        diff = m["gold_usd_oz"] / m["nbp"] - 1
        bad = diff[diff.abs() > NBP_MONTHLY_TOL]
        out["monthly_mean_diff"] = {
            "n_months": len(m),
            "median_pct": round(float(diff.median() * 100), 3),
            "months_gt_1pct": {
                str(k.strftime("%Y-%m")): round(float(v * 100), 2) for k, v in bad.items()
            },
        }
    return out


def top_flagged_dates(prices: pd.DataFrame, rejected: pd.DataFrame, n: int = 15) -> list[dict]:
    rows = []
    for df, kind in ((prices, "kept"), (rejected, "rejected")):
        for d, a, f in zip(df["date"], df["asset"], df["flag"], strict=True):
            for x in split_flags(f):
                rows.append((pd.Timestamp(d), a, x, kind))
    if not rows:
        return []
    t = pd.DataFrame(rows, columns=["date", "asset", "flag", "kind"])
    g = t.groupby("date")
    top = g.size().sort_values(ascending=False, kind="stable").head(n)
    return [
        {
            "date": str(d.date()),
            "n_flags": int(c),
            "detail": sorted(f"{r.asset}:{r.flag}" for r in g.get_group(d).itertuples()),
        }
        for d, c in top.items()
    ]


def build_report(
    prices: pd.DataFrame,
    rejected: pd.DataFrame,
    refs: pd.DataFrame,
    factors: pd.DataFrame,
    nbp: pd.Series | None,
    fx: pd.DataFrame | None = None,
) -> dict:
    ref_rep = {}
    for ref in sorted(refs["asset"].unique()):
        d = refs[refs["asset"] == ref]
        ref_rep[ref] = {
            "n_rows": len(d),
            "first_date": str(d["date"].min().date()),
            "last_date": str(d["date"].max().date()),
            "flags": _flag_counts(d),
        }
    latest_factor = {}
    for a, g in factors.groupby("asset"):
        last = g.sort_values("date").iloc[-1]
        latest_factor[a] = {
            "date": str(pd.Timestamp(last["date"]).date()),
            "factor": round(float(last["factor"]), 5),
            "reliability": last["reliability"],
        }
    return {
        "assets": {a: asset_report(prices, rejected, a) for a in ASSETS},
        "rejected_total": _flag_counts(rejected),
        "flags_total": _flag_counts(prices),
        "top_flagged_dates": top_flagged_dates(prices, rejected),
        "xcheck": xcheck_report(prices, refs),
        "nbp": nbp_report(prices, factors, nbp),
        "references": ref_rep,
        "display_factors_latest": latest_factor,
        "display_fx": (
            {
                k: (
                    None
                    if not isinstance(v, str) and pd.isna(v)
                    else str(pd.Timestamp(v).date())
                    if k.endswith("_date")
                    else v
                )
                for k, v in fx.iloc[0].items()
                if k != "published_at"
            }
            if fx is not None and len(fx)
            else {}
        ),
    }
