"""EDA giá vàng, bạc, Brent, WTI trên bản clean mới nhất (ADR-0005). Tái lập: cùng bản clean → cùng
kết quả (không có ngẫu nhiên; ghi dt đầu vào và sha256 của file).

Chạy:
  python scripts/eda_prices.py                      # bản clean mới nhất trong data/lake
  python scripts/eda_prices.py --input-dt 2026-10-09

Đầu ra (gitignore): data/lake/eda/dt=<ngày chạy>/
  eda.json        toàn bộ số liệu
  summary.md      các bảng tổng hợp (không có chuỗi giá) để chép vào docs/eda/
  *.csv           bảng chi tiết; wti_around_2020-04-20.csv có giá (chỉ để kiểm tra nội bộ)
  *.png           độ biến động trượt 20 phiên, ACF

Quy ước (đã chốt với Long):
- Return h phiên: src.forecast.returns.horizon_log_returns trên lịch phiên riêng của từng tài sản
  (gold/silver: NYSE, wti/brent: CME). Phiên lịch không có giá (dòng bị loại hoặc thiếu) → NaN,
  không forward-fill; mọi cửa sổ chạm phiên đó là NaN. WTI 20/4/2020 (giá âm) → NaN.
- Cửa sổ gán theo ngày gốc t; chỉ giữ cửa sổ có t và t+h cùng nằm trong giai đoạn (cửa sổ 2019
  không chạm dữ liệu 2020).
- Thống kê phân phối return CHỈ cho 2014–2018 (train) và 2019 (validation). 2020 → nay chỉ có
  chất lượng dữ liệu.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import acf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import calendars, storage
from src.data.clean import split_flags
from src.data.config import ASSETS
from src.forecast.returns import horizon_log_returns

MODEL_ASSETS = ["gold", "silver", "brent", "wti"]
HORIZONS = [1, 3, 7]
QUANTILES = [0.01, 0.10, 0.50, 0.90, 0.99]
PERIODS = {
    "train_2014_2018": ("2014-01-01", "2018-12-31"),
    "val_2019": ("2019-01-01", "2019-12-31"),
}
QUALITY_START, NEG_DAY = "2012-01-01", pd.Timestamp("2020-04-20")
ACF_LAGS = 20
VOL_WINDOW = 20
# Bảng màu categorical (skill dataviz, slot 1–4, đã chạy validate_palette.js)
COLORS = {"gold": "#2a78d6", "silver": "#eb6834", "brent": "#1baf7a", "wti": "#eda100"}
MUTED = "#6B7280"
LABEL = {"gold": "Vàng (GLD)", "silver": "Bạc (SLV)", "brent": "Brent (BZ=F)", "wti": "WTI (CL=F)"}


# ---------- dữ liệu ----------


def load(lake: Path, input_dt: str | None) -> tuple[str, pd.DataFrame, pd.DataFrame, dict]:
    st = storage.LocalStorage(lake)
    dt = input_dt or storage.latest_dt(st, "clean/prices", must_have="prices.parquet")
    if dt is None:
        raise SystemExit("không có bản clean trong data/lake/clean/prices")
    base = f"clean/prices/dt={dt}"
    meta = {"input_dt": dt}
    frames = []
    for name in ("prices", "rejected"):
        raw = st.read_bytes(f"{base}/{name}.parquet")
        meta[f"{name}_sha256"] = hashlib.sha256(raw).hexdigest()
        frames.append(storage.read_parquet(st, f"{base}/{name}.parquet"))
    return dt, frames[0], frames[1], meta


def calendar_for(asset: str, start, end) -> pd.DatetimeIndex:
    cal = ASSETS[asset].calendar
    return calendars.sessions(cal, start, end)


def on_calendar(prices: pd.DataFrame, rejected: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Bảng theo lịch phiên của tài sản: price (NaN nếu thiếu), status = ok|rejected|absent."""
    d = prices[prices["asset"] == asset].set_index("date").sort_index()
    rj = rejected[rejected["asset"] == asset]
    cal = calendar_for(asset, d.index.min(), d.index.max())
    out = pd.DataFrame(index=cal)
    out["price"] = d["price"].reindex(cal)
    out["flag"] = d["flag"].reindex(cal).fillna("")
    out["status"] = np.where(out["price"].notna(), "ok", "absent")
    out.loc[out.index.isin(pd.DatetimeIndex(rj["date"])) & out["price"].isna(), "status"] = (
        "rejected"
    )
    out.loc[out["price"] <= 0, "status"] = "negative"
    return out


def windows(tab: pd.DataFrame, h: int) -> pd.DataFrame:
    """Cửa sổ (t, t+h phiên) trên lịch: return và lý do NaN."""
    p = tab["price"].to_numpy(dtype=float)
    r = horizon_log_returns(np.where(np.isnan(p), np.nan, p), h)
    n = len(tab)
    end_idx = np.arange(n) + h
    valid_end = end_idx < n
    end_date = pd.Series(pd.NaT, index=tab.index, dtype="datetime64[ns]")
    end_date[valid_end] = tab.index[end_idx[valid_end]]
    status = tab["status"].to_numpy()
    reason = np.full(n, "", dtype=object)
    for i in range(n):
        if not valid_end[i]:
            reason[i] = "no_future"
            continue
        seg = {status[i], status[i + h]}  # chỉ hai đầu cửa sổ quyết định return
        if "negative" in seg:
            reason[i] = "negative_price"
        elif "rejected" in seg:
            reason[i] = "rejected_row"
        elif "absent" in seg:
            reason[i] = "missing_session"
    return pd.DataFrame({"end": end_date, "r": r, "nan_reason": reason}, index=tab.index)


def in_period(w: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return w[(w.index >= s) & (w.index <= e) & (w["end"] <= e)]


# ---------- thống kê ----------


def describe(r: pd.Series) -> dict:
    x = r.dropna().to_numpy()
    q = np.quantile(x, QUANTILES)
    return {
        "n": len(x),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)),
        "skew": float(stats.skew(x, bias=False)),
        "excess_kurtosis": float(stats.kurtosis(x, fisher=True, bias=False)),
        **{f"q{round(k * 100):02d}": float(v) for k, v in zip(QUANTILES, q, strict=True)},
        "share_up": float((x > 0).mean()),
        "share_zero": float((x == 0).mean()),
    }


def baselines(train: pd.Series, val: pd.Series) -> dict:
    tr, va = train.dropna().to_numpy(), val.dropna().to_numpy()
    p_up = float((tr > 0).mean())
    y_val = (va > 0).astype(float)
    q10, q90 = np.quantile(tr, [0.10, 0.90])
    majority_up = p_up >= 0.5
    return {
        "mase_scale_train": float(np.abs(tr).mean()),  # MAE của naive (return = 0) trên train
        "naive_mae_val": float(np.abs(va).mean()),
        "naive_mase_val": float(np.abs(va).mean() / np.abs(tr).mean()),
        "share_up_train": p_up,
        "share_up_val": float(y_val.mean()),
        "brier_val_const_p_train": float(np.mean((p_up - y_val) ** 2)),
        "brier_val_p05": 0.25,
        "sign_acc_val_majority_train": float(y_val.mean() if majority_up else 1 - y_val.mean()),
        "train_q10": float(q10),
        "train_q90": float(q90),
        "coverage_val_q10_q90_train": float(((va >= q10) & (va <= q90)).mean()),
        "n_train": len(tr),
        "n_val": len(va),
    }


def acf_table(r1: pd.Series) -> dict:
    """ACF lag 1–20 của r và |r| (2014–2018). NaN giữ vị trí (missing='conservative')."""
    out = {}
    for name, x in (("r", r1), ("abs_r", r1.abs())):
        vals = acf(x.to_numpy(), nlags=ACF_LAGS, missing="conservative", fft=False)[1:]
        n = int(x.notna().sum())
        band = 1.96 / np.sqrt(n)
        out[name] = {
            "acf": [float(v) for v in vals],
            "band_95": float(band),
            "n_lags_outside_band": int((np.abs(vals) > band).sum()),
            "n": n,
        }
    return out


# ---------- chất lượng dữ liệu (mọi giai đoạn) ----------


def quality_by_year(prices: pd.DataFrame, rejected: pd.DataFrame, asset: str) -> pd.DataFrame:
    d = prices[prices["asset"] == asset]
    rj = rejected[rejected["asset"] == asset]
    cal = calendar_for(asset, QUALITY_START, d["date"].max())
    have = pd.DatetimeIndex(d["date"])
    rows = []
    for y in sorted(set(cal.year)):
        cy = cal[cal.year == y]
        dy = d[d["date"].dt.year == y]
        ry = rj[rj["date"].dt.year == y]
        missing = cy.difference(have)
        row = {
            "asset": asset,
            "year": y,
            "sessions_calendar": len(cy),
            "rows_kept": len(dy),
            "missing_sessions": len(missing),
            "missing_of_which_rejected": int(missing.isin(pd.DatetimeIndex(ry["date"])).sum()),
            "kept_off_calendar": int((~pd.DatetimeIndex(dy["date"]).isin(cy)).sum()),
        }
        for prefix, df in (("kept", dy), ("rej", ry)):
            for f in df["flag"]:
                for x in split_flags(f):
                    row[f"{prefix}:{x}"] = row.get(f"{prefix}:{x}", 0) + 1
        rows.append(row)
    return pd.DataFrame(rows).fillna(0)


def around_neg_day(prices: pd.DataFrame, tabs: dict) -> tuple[pd.DataFrame, dict]:
    """Các phiên quanh 20/4/2020 cho WTI và Brent: flag, trạng thái; số cửa sổ NaN do giá âm."""
    rows = []
    for asset in ("wti", "brent"):
        t = tabs[asset].loc["2020-04-14":"2020-04-28"]
        for d, r in t.iterrows():
            rows.append(
                {
                    "date": str(d.date()),
                    "asset": asset,
                    "status": r["status"],
                    "flag": r["flag"],
                    "price": r["price"],
                }
            )
    nan_windows = {}
    for h in HORIZONS:
        w = windows(tabs["wti"], h)
        nan_windows[f"h{h}"] = int((w["nan_reason"] == "negative_price").sum())
    return pd.DataFrame(rows), nan_windows


# ---------- hình ----------


def plot_rolling_vol(tabs: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(4, 1, figsize=(10, 9), sharex=True, dpi=150)
    for ax, a in zip(axes, MODEL_ASSETS, strict=True):
        t = tabs[a].loc["2014-01-01":"2019-12-31"]
        r = np.log(t["price"].where(t["price"] > 0)).diff()
        vol = r.rolling(VOL_WINDOW, min_periods=15).std() * np.sqrt(252) * 100
        ax.plot(vol.index, vol.to_numpy(), color=COLORS[a], lw=1.6)
        ax.axvline(pd.Timestamp("2019-01-01"), color=MUTED, lw=1, ls="--")
        ax.set_title(LABEL[a], loc="left", fontsize=10, color="#1F2328")
        ax.set_ylabel("% / năm", fontsize=8, color=MUTED)
        ax.grid(axis="y", color="#E5E7EB", lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=8, colors=MUTED)
    axes[0].text(
        pd.Timestamp("2019-01-15"),
        axes[0].get_ylim()[1] * 0.9,
        "validation 2019",
        fontsize=8,
        color=MUTED,
    )
    fig.suptitle(
        "Độ biến động trượt 20 phiên (std log return ngày × √252), 2014–2019",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    fig.text(
        0.01,
        0.005,
        "Nguồn: Yahoo Finance (GLD, SLV, BZ=F, CL=F); bản clean ADR-0005",
        fontsize=7,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(out / "rolling_vol_20_2014_2019.png")
    plt.close(fig)


def plot_acf(acfs: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lags = np.arange(1, ACF_LAGS + 1)
    fig, axes = plt.subplots(2, 4, figsize=(12, 5.5), sharey="row", dpi=150)
    for j, a in enumerate(MODEL_ASSETS):
        for i, (key, title) in enumerate((("r", "return"), ("abs_r", "|return|"))):
            ax = axes[i, j]
            v = acfs[a][key]
            ax.bar(lags, v["acf"], width=0.6, color=COLORS[a])
            ax.axhspan(-v["band_95"], v["band_95"], color=MUTED, alpha=0.15, lw=0)
            ax.axhline(0, color=MUTED, lw=0.8)
            ax.set_title(f"{LABEL[a]} · {title}", loc="left", fontsize=9)
            ax.set_xticks([1, 5, 10, 15, 20])
            ax.tick_params(labelsize=7, colors=MUTED)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            if i == 1:
                ax.set_xlabel("lag (phiên)", fontsize=8, color=MUTED)
    fig.suptitle(
        "ACF log return ngày, 2014–2018: return gần như không tự tương quan, |return| thì có",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    fig.text(
        0.01,
        0.005,
        "Vùng xám: ±1,96/√n. Nguồn: Yahoo Finance; bản clean ADR-0005",
        fontsize=7,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(out / "acf_2014_2018.png")
    plt.close(fig)


# ---------- báo cáo markdown ----------


ABS_R = "\\|r\\|"


def _pct(x: float, nd: int = 2) -> str:
    return f"{x * 100:.{nd}f}%"


def markdown(res: dict) -> str:
    L = []
    m = res["meta"]
    L.append(
        f"Đầu vào: `clean/prices/dt={m['input_dt']}` (prices sha256 `{m['prices_sha256'][:12]}…`), "
        f"chạy dt={m['run_dt']}.\n"
    )
    L.append("### Phân phối log return h phiên (đơn vị: %; std, phân vị theo %)\n")
    L.append(
        "| Tài sản | Giai đoạn | h | n | mean | std | skew | kurt dư | q01 | q10 | q50 | q90 | q99 | tăng | =0 |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for a in MODEL_ASSETS:
        for p in PERIODS:
            for h in HORIZONS:
                s = res["dist"][a][p][f"h{h}"]
                L.append(
                    f"| {a} | {p} | {h} | {s['n']} | {s['mean'] * 100:.3f} | {s['std'] * 100:.2f} | "
                    f"{s['skew']:.2f} | {s['excess_kurtosis']:.1f} | "
                    + " | ".join(f"{s[k] * 100:.2f}" for k in ("q01", "q10", "q50", "q90", "q99"))
                    + f" | {_pct(s['share_up'], 1)} | {_pct(s['share_zero'], 1)} |"
                )
    L.append("\n### Cửa sổ NaN theo lý do (số cửa sổ có ngày gốc trong giai đoạn)\n")
    L.append(
        "| Tài sản | Giai đoạn | h | tổng cửa sổ | NaN | missing_session | rejected_row | negative_price | vượt khỏi giai đoạn |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|")
    for a in MODEL_ASSETS:
        for p in PERIODS:
            for h in HORIZONS:
                c = res["nan"][a][p][f"h{h}"]
                L.append(
                    f"| {a} | {p} | {h} | {c['windows']} | {c['nan']} | {c['missing_session']} | "
                    f"{c['rejected_row']} | {c['negative_price']} | {c['crosses_period_end']} |"
                )
    L.append("\n### Mốc cho đánh giá (train 2014–2018 → validation 2019)\n")
    L.append(
        "| Tài sản | h | thang MASE = mean\\|r\\| train | naive MAE 2019 | naive MASE 2019 | "
        "tăng train | tăng 2019 | Brier 2019, p = tỷ lệ tăng train | đúng chiều 2019, đoán theo đa số train | "
        "q10 / q90 train (%) | coverage 2019 của [q10, q90] train |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for a in MODEL_ASSETS:
        for h in HORIZONS:
            b = res["baselines"][a][f"h{h}"]
            L.append(
                f"| {a} | {h} | {_pct(b['mase_scale_train'], 3)} | {_pct(b['naive_mae_val'], 3)} | "
                f"{b['naive_mase_val']:.2f} | {_pct(b['share_up_train'], 1)} | {_pct(b['share_up_val'], 1)} | "
                f"{b['brier_val_const_p_train']:.4f} | {_pct(b['sign_acc_val_majority_train'], 1)} | "
                f"{b['train_q10'] * 100:.2f} / {b['train_q90'] * 100:.2f} | "
                f"{_pct(b['coverage_val_q10_q90_train'], 1)} |"
            )
    L.append("\n### ACF return ngày, 2014–2018 (lag 1–20)\n")
    L.append(
        "| Tài sản | chuỗi | lag1 | lag2 | lag5 | lag10 | lag20 | số lag ngoài ±1,96/√n | band |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|")
    for a in MODEL_ASSETS:
        for k in ("r", "abs_r"):
            v = res["acf"][a][k]
            ac = v["acf"]
            name = "r" if k == "r" else ABS_R
            L.append(
                f"| {a} | {name} | {ac[0]:.3f} | {ac[1]:.3f} | {ac[4]:.3f} | "
                f"{ac[9]:.3f} | {ac[19]:.3f} | {v['n_lags_outside_band']}/20 | {v['band_95']:.3f} |"
            )
    L.append("\n### Tương quan return 1 ngày giữa các tài sản (ngày chung)\n")
    for p in PERIODS:
        c = res["corr"][p]
        L.append(f"**{p}** (n ngày chung theo cặp: {res['corr_n'][p]})\n")
        L.append("| | " + " | ".join(MODEL_ASSETS) + " |")
        L.append("|---|" + "---|" * len(MODEL_ASSETS))
        for a in MODEL_ASSETS:
            L.append(f"| {a} | " + " | ".join(f"{c[a][b]:.2f}" for b in MODEL_ASSETS) + " |")
        L.append("")
    L.append("### Số ngày tài sản hàng có phiên mà tài sản cột không có\n")
    for p in PERIODS:
        c = res["only_in"][p]
        L.append(f"**{p}**\n")
        L.append("| có \\ không có | " + " | ".join(MODEL_ASSETS) + " |")
        L.append("|---|" + "---|" * len(MODEL_ASSETS))
        for a in MODEL_ASSETS:
            L.append(f"| {a} | " + " | ".join(str(c[a][b]) for b in MODEL_ASSETS) + " |")
        L.append("")
    L.append("### Chất lượng dữ liệu theo năm, 2012 → nay (mọi giai đoạn)\n")
    L.append(
        "Phiên thiếu = phiên trong lịch sàn mà prices.parquet không có (trong ngoặc: do dòng bị loại). "
        "Lịch: gold/silver NYSE, wti/brent CME, usd_vnd thứ Hai–thứ Sáu.\n"
    )
    for a, rows in res["quality"].items():
        flag_cols = sorted({k for r in rows for k in r if ":" in k})
        L.append(f"**{a}**\n")
        head = ["năm", "phiên lịch", "dòng giữ", "thiếu (loại)", "ngoài lịch", *flag_cols]
        L.append("| " + " | ".join(head) + " |")
        L.append("|" + "---|" * len(head))
        for r in rows:
            cells = [
                r["year"],
                r["sessions_calendar"],
                r["rows_kept"],
                f"{r['missing_sessions']} ({r['missing_of_which_rejected']})",
                r["kept_off_calendar"],
                *(int(r.get(k, 0)) for k in flag_cols),
            ]
            L.append("| " + " | ".join(str(c) for c in cells) + " |")
        L.append("")
    L.append("### Quanh 20/4/2020 (không ghi giá)\n")
    L.append("| ngày | wti: trạng thái / flag | brent: trạng thái / flag |")
    L.append("|---|---|---|")
    nd = res["neg_day"]
    for d in sorted({r["date"] for r in nd["rows"]}):
        cells = []
        for a in ("wti", "brent"):
            r = next((x for x in nd["rows"] if x["date"] == d and x["asset"] == a), None)
            cells.append(f"{r['status']} / {r['flag'] or '-'}" if r else "-")
        L.append(f"| {d} | " + " | ".join(cells) + " |")
    L.append(
        "\nCửa sổ WTI thành NaN vì giá âm 20/4/2020: "
        + ", ".join(f"{k} = {v}" for k, v in nd["nan_windows"].items())
        + " (ngày 20/4 là gốc hoặc đích của cửa sổ).\n"
    )
    return "\n".join(L)


# ---------- main ----------


def run(lake: Path, input_dt: str | None, run_dt: str) -> dict:
    _, prices, rejected, meta = load(lake, input_dt)
    meta["run_dt"] = run_dt  # không ghi giờ chạy để chạy lại ra file y hệt
    out = lake / "eda" / f"dt={run_dt}"
    out.mkdir(parents=True, exist_ok=True)

    tabs = {a: on_calendar(prices, rejected, a) for a in MODEL_ASSETS}
    res: dict = {"meta": meta, "dist": {}, "nan": {}, "baselines": {}, "acf": {}}
    for a in MODEL_ASSETS:
        res["dist"][a], res["nan"][a], res["baselines"][a] = {}, {}, {}
        for h in HORIZONS:
            w = windows(tabs[a], h)
            per = {}
            for p, (s, e) in PERIODS.items():
                origin = w[(w.index >= s) & (w.index <= e)]
                inside = in_period(w, s, e)
                per[p] = inside["r"]
                reasons = inside.loc[inside["r"].isna(), "nan_reason"].value_counts()
                res["nan"][a].setdefault(p, {})[f"h{h}"] = {
                    "windows": len(origin),
                    "nan": int(inside["r"].isna().sum()),
                    "missing_session": int(reasons.get("missing_session", 0)),
                    "rejected_row": int(reasons.get("rejected_row", 0)),
                    "negative_price": int(reasons.get("negative_price", 0)),
                    "crosses_period_end": int(len(origin) - len(inside)),
                }
                res["dist"][a].setdefault(p, {})[f"h{h}"] = describe(inside["r"])
            res["baselines"][a][f"h{h}"] = baselines(per["train_2014_2018"], per["val_2019"])
        r1 = in_period(windows(tabs[a], 1), *PERIODS["train_2014_2018"])["r"]
        res["acf"][a] = acf_table(r1)

    # Tương quan và phiên lệch giữa các tài sản (r1 gán theo ngày gốc t)
    res["corr"], res["corr_n"], res["only_in"] = {}, {}, {}
    for p, (s, e) in PERIODS.items():
        r1 = pd.DataFrame({a: in_period(windows(tabs[a], 1), s, e)["r"] for a in MODEL_ASSETS})
        c = r1.corr(min_periods=50)
        res["corr"][p] = {a: {b: float(c.loc[a, b]) for b in MODEL_ASSETS} for a in MODEL_ASSETS}
        res["corr_n"][p] = int(r1.dropna().shape[0])
        have = {
            a: set(prices.loc[(prices["asset"] == a) & prices["date"].between(s, e), "date"])
            for a in MODEL_ASSETS
        }
        res["only_in"][p] = {
            a: {b: len(have[a] - have[b]) for b in MODEL_ASSETS} for a in MODEL_ASSETS
        }

    # Chất lượng dữ liệu mọi giai đoạn (kể cả usd_vnd vì dùng cho hiển thị)
    q = pd.concat(
        [quality_by_year(prices, rejected, a) for a in [*MODEL_ASSETS, "usd_vnd"]],
        ignore_index=True,
    ).fillna(0)
    q.to_csv(out / "quality_by_year.csv", index=False)
    res["quality"] = {
        a: [
            {
                k: (int(v) if isinstance(v, (int, float, np.integer, np.floating)) else v)
                for k, v in r.items()
                if not (":" in k and v == 0)
            }
            for r in g.drop(columns="asset").to_dict("records")
        ]
        for a, g in q.groupby("asset", sort=False)
    }
    neg_rows, neg_nan = around_neg_day(prices, tabs)
    neg_rows.to_csv(out / "wti_around_2020-04-20.csv", index=False)
    res["neg_day"] = {
        "rows": neg_rows.drop(columns="price").to_dict("records"),
        "nan_windows": neg_nan,
    }

    # Bảng chi tiết, hình
    pd.DataFrame(
        [
            {"asset": a, "period": p, "h": h, **res["dist"][a][p][f"h{h}"]}
            for a in MODEL_ASSETS
            for p in PERIODS
            for h in HORIZONS
        ]
    ).to_csv(out / "return_distribution.csv", index=False)
    pd.DataFrame(
        [
            {"asset": a, "h": h, **res["baselines"][a][f"h{h}"]}
            for a in MODEL_ASSETS
            for h in HORIZONS
        ]
    ).to_csv(out / "baselines.csv", index=False)
    plot_rolling_vol(tabs, out)
    plot_acf(res["acf"], out)

    (out / "eda.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(markdown(res), encoding="utf-8")
    res["out_dir"] = str(out)
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"))
    ap.add_argument("--input-dt", default=None, help="dt của bản clean; bỏ trống = mới nhất")
    ap.add_argument("--run-dt", default=datetime.now(UTC).date().isoformat())
    args = ap.parse_args(argv)
    res = run(Path(args.lake_dir), args.input_dt, args.run_dt)
    print(f"input dt={res['meta']['input_dt']}  ->  {res['out_dir']}")


if __name__ == "__main__":
    main()
