"""Probe K3: cache IMF CEEMDAN có dùng được cho mô hình chính không (chỉ đọc, chỉ in thống kê).

Chạy:
  python scripts/k3_ceemdan_probe.py [--lake-dir data/lake] [--processes 8]

Đọc bản clean (cắt tại 2019-12-31 ngay khi đọc, bằng filter của pyarrow) và cache
features/ceemdan (ADR-0007), in 6 mục dạng Markdown:
1. cfg_hash, phiên bản thư viện, độ phủ cache, price_hash so với bản clean (lệch thì dừng)
2. phiên lịch bị thiếu trong cửa sổ decompose (theo dòng) và trong đoạn seq_len cuối
3. phân phối n_imf, đề xuất K
4. thang giá trị sau chuẩn hóa chia cho giá tại t (chỉ train 2014–2018)
5. số ngày gốc hợp lệ train/validation theo tài sản × độ dài cửa sổ × seq_len, so với DLinear MVP
6. chống rò rỉ: decompose lại cửa sổ kết thúc tại t từ chuỗi cắt tại t, so với cache (atol 1e-10)

Không train, không ghi file, không dựng lại cache. Cấu hình: configs/k3_probe.py (tham số CEEMDAN
lấy từ configs/ceemdan_cache.py). Thoát mã 2 khi gặp điều kiện dừng ở mục 1.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configs import ceemdan_cache as CC
from configs import k3_probe as C
from src.data import calendars, storage
from src.data.config import ASSETS, PUBLISHED_AT_RULES
from src.features import ceemdan_cache as cc
from src.features.build import build_feature_frame, make_windows
from src.forecast import baselines as B
from src.forecast.decomposition import (
    PYEMD_VERSION,
    CeemdanConfig,
    WindowIMF,
    causal_imf_windows,
    fixed_imf_matrix,
)
from src.forecast.returns import horizon_log_returns

CUT = pd.Timestamp(C.CUTOFF)
TRAIN_END = pd.Timestamp(C.TRAIN[1])
YEARS = list(range(2014, CUT.year + 1))


@dataclass
class AssetData:
    """Chuỗi giá (dòng được giữ, ≤ CUTOFF) và vị trí của từng dòng trên lịch giao dịch."""

    asset: str
    calendar: str
    dates: pd.DatetimeIndex
    values: np.ndarray
    calpos: np.ndarray  # vị trí lịch của dòng i (trong cal)
    cal: pd.DatetimeIndex  # mọi phiên lịch từ ngày giá đầu tới CUTOFF
    missing: pd.DatetimeIndex  # phiên lịch không có dòng giá


@dataclass
class CacheData:
    df: pd.DataFrame  # các dòng cache, end_date ≤ CUTOFF, sắp tăng dần
    rows: np.ndarray  # vị trí dòng giá của end_date
    windows: list[WindowIMF]


def cfg_for(window: int) -> CeemdanConfig:
    return CeemdanConfig(
        window=window,
        trials=CC.TRIALS,
        epsilon=CC.EPSILON,
        seed=CC.SEED,
        keep_last=CC.KEEP_LAST,
    )


def md(rows: list[dict] | pd.DataFrame, floatfmt: str = ".4g") -> str:
    """Bảng Markdown đơn giản (không cần tabulate)."""
    df = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows
    if df.empty:
        return "_(trống)_"

    def fmt(v) -> str:
        if isinstance(v, float | np.floating):
            return "" if np.isnan(v) else format(float(v), floatfmt)
        return str(v)

    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(out)


def section(title: str) -> None:
    print(f"\n## {title}\n", flush=True)


# ---------- đọc dữ liệu (cắt tại CUTOFF ngay khi đọc) ----------


def read_clean(lake: Path, dt: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = lake / "clean" / "prices" / f"dt={dt}"
    flt = [("date", "<=", CUT)]
    prices = pd.read_parquet(d / "prices.parquet", filters=flt)
    rejected = pd.read_parquet(d / "rejected.parquet", filters=flt)
    for name, df in (("prices", prices), ("rejected", rejected)):
        if len(df) and pd.Timestamp(df["date"].max()) > CUT:
            raise SystemExit(f"{name}: đọc được dữ liệu sau {C.CUTOFF}, dừng")
    return prices[prices["asset"].isin(C.ASSETS)].copy(), rejected


def asset_data(prices: pd.DataFrame, asset: str) -> AssetData:
    dates, values = cc.asset_series(prices, asset)
    cal_name = ASSETS[asset].calendar
    cal = calendars.sessions(cal_name, dates.min(), CUT)
    calpos = cal.get_indexer(dates)
    if (calpos < 0).any():
        raise SystemExit(f"{asset}: có dòng giá không phải phiên {cal_name}")
    return AssetData(asset, cal_name, dates, values, calpos, cal, cal.difference(dates))


def read_cache(st, asset: str, cfg: CeemdanConfig) -> tuple[pd.DataFrame, list[str]]:
    months = list(pd.period_range("2014-01", C.CUTOFF, freq="M").strftime("%Y-%m"))
    frames, empty = [], []
    for m in months:
        f = cc.read_month(st, asset, cfg, m)
        (frames.append(f) if len(f) else empty.append(m))
    if not frames:
        return pd.DataFrame(columns=cc.COLUMNS), empty
    df = pd.concat(frames, ignore_index=True)
    df["end_date"] = pd.to_datetime(df["end_date"])
    df = df[df["end_date"] <= CUT].sort_values("end_date").reset_index(drop=True)
    return df, empty


def pinned_versions() -> dict[str, str]:
    text = (ROOT / C.REQUIREMENTS_FILE).read_text(encoding="utf-8")
    out = {}
    for pkg in ("numpy", "EMD-signal"):
        m = re.search(rf"^{re.escape(pkg)}==([^\s#]+)", text, flags=re.MULTILINE)
        out[pkg] = m.group(1) if m else "?"
    return out


# ---------- mục 1 ----------


def step1(st, clean_dt, assets, prices_ref) -> tuple[dict, bool]:
    section("1. Cache có dùng được không")
    pins = pinned_versions()
    stop = False
    print(
        md(
            [
                {"thư viện": "numpy", "venv": np.__version__, "requirements.txt": pins["numpy"]},
                {
                    "thư viện": "EMD-signal",
                    "venv": PYEMD_VERSION,
                    "requirements.txt": pins["EMD-signal"],
                },
            ]
        )
    )
    if np.__version__ != pins["numpy"] or PYEMD_VERSION != pins["EMD-signal"]:
        print("\n**Phiên bản trong venv khác requirements.txt.**")

    hash_rows, year_rows, gap_rows, ph_rows, caches = [], [], [], [], {}
    for asset, a in assets.items():
        for w in C.WINDOWS:
            cfg = cfg_for(w)
            h = cfg.hash()
            meta_key = f"{cc.prefix(asset, cfg)}/config.json"
            meta = json.loads(st.read_bytes(meta_key)) if st.exists(meta_key) else {}
            meta_hash = meta.get("cfg_hash")
            df, empty_months = read_cache(st, asset, cfg)
            col_hash = sorted(set(df["cfg_hash"])) if len(df) else []
            ok = h == C.EXPECTED_CFG_HASH and meta_hash == h and col_hash == [h]
            stop |= not ok
            hash_rows.append(
                {
                    "asset": asset,
                    "window": w,
                    "cfg.hash()": h,
                    "config.json": meta_hash,
                    "cột cfg_hash": ",".join(col_hash),
                    "keep_last": ",".join(map(str, sorted(set(df["keep_last"])))),
                    "platform": ",".join(sorted(set(df["platform"]))),
                    "tháng trống/hỏng": len(empty_months),
                    "khớp": "có" if ok else "**KHÔNG**",
                }
            )
            if not len(df):
                continue

            pos = pd.Series(np.arange(len(a.dates)), index=a.dates)
            ends = pd.DatetimeIndex(df["end_date"])
            stale = ends.difference(a.dates)  # cửa sổ không còn dòng giá tương ứng
            dup = int(ends.duplicated().sum())
            rows = pos.reindex(ends).to_numpy()
            seed_bad = int((df["seed_id"].to_numpy() != [cc.seed_id(asset, d) for d in ends]).sum())

            # Ngày gốc trên lịch 2014–2019 không có cửa sổ
            sess = calendars.sessions(a.calendar, "2014-01-01", CUT)
            miss = sess.difference(ends)
            no_row = miss.intersection(a.missing)
            in_rows = miss.difference(no_row)
            no_hist = [d for d in in_rows if pos[d] < w - 1]
            other = in_rows.difference(pd.DatetimeIndex(no_hist))
            gap_rows.append(
                {
                    "asset": asset,
                    "window": w,
                    "phiên lịch": len(sess),
                    "cửa sổ": len(df),
                    "thiếu": len(miss),
                    "không có dòng giá": ", ".join(no_row.strftime("%Y-%m-%d")) or "-",
                    "skipped_no_history": len(no_hist),
                    "khác (bất thường)": ", ".join(other.strftime("%Y-%m-%d")) or "0",
                    "end_date không có giá": len(stale),
                    "trùng": dup,
                    "seed_id sai": seed_bad,
                }
            )
            year_rows.append(
                {"asset": asset, "window": w} | {str(y): int((ends.year == y).sum()) for y in YEARS}
            )

            # price_hash so với bản clean hiện tại (và bản lúc dựng cache để đối chiếu)
            row = {"asset": asset, "window": w}
            for label, aa in (("clean " + clean_dt, a), ("clean " + C.REFERENCE_CLEAN_DT, None)):
                if aa is None:
                    if prices_ref is None:
                        continue
                    aa = asset_data(prices_ref, asset)
                p2 = pd.Series(np.arange(len(aa.dates)), index=aa.dates).reindex(ends)
                bad_months = []
                n_bad = 0
                for d, r, ph in zip(ends, p2.to_numpy(), df["price_hash"], strict=True):
                    if np.isnan(r) or r < w - 1:
                        n_bad += 1
                        bad_months.append(d.strftime("%Y-%m"))
                        continue
                    r = int(r)
                    if cc.price_hash(aa.values[r - w + 1 : r + 1]) != ph:
                        n_bad += 1
                        bad_months.append(d.strftime("%Y-%m"))
                row[f"lệch ({label})"] = n_bad
                if n_bad:
                    row[f"tháng lệch ({label})"] = ", ".join(
                        f"{m}:{k}"
                        for m, k in pd.Series(bad_months).value_counts().sort_index().items()
                    )
                if aa is a:
                    stop |= n_bad > 0
            ph_rows.append(row)
            if np.isnan(rows).any():
                rows = np.where(np.isnan(rows), -1, rows)
            caches[(asset, w)] = CacheData(df, rows.astype(int), cc.to_windows(df))

    print("\n**cfg_hash** (kỳ vọng " + C.EXPECTED_CFG_HASH + ")\n")
    print(md(hash_rows))
    print("\n**Số cửa sổ theo năm**\n")
    print(md(year_rows))
    print("\n**Ngày gốc trên lịch 2014–2019 không có cửa sổ**\n")
    print(md(gap_rows))
    print("\n**price_hash so với bản clean (đọc, không ghi)**\n")
    print(md(ph_rows))
    return caches, stop


# ---------- mục 2 ----------


def missing_in_span(a: AssetData, rows: np.ndarray, length: int) -> np.ndarray:
    """Số phiên lịch bị thiếu trong `length` dòng giá kết thúc tại từng dòng `rows`."""
    first = rows - length + 1
    out = np.full(len(rows), -1)
    ok = first >= 0
    out[ok] = a.calpos[rows[ok]] - a.calpos[first[ok]] + 1 - length
    return out


def step2(assets, caches) -> dict:
    section("2. Phiên lịch bị thiếu trong cửa sổ (theo dòng) và đoạn seq_len cuối")
    print(
        "Cửa sổ cache = `window` dòng giá được giữ kết thúc tại t. Một cửa sổ có k phiên lịch bị "
        "thiếu thì thực ra trải dài `window + k` phiên. (b) tính trên `seq_len` dòng cuối (đoạn "
        "IMF đưa vào mô hình); `make_windows(seq_len)` còn cần thêm 1 giá trước đoạn này.\n"
    )
    year_rows, sess_rows, full_clean = [], [], {}
    for (asset, w), c in caches.items():
        a = assets[asset]
        ends = pd.DatetimeIndex(c.df["end_date"])
        spans = {"full": missing_in_span(a, c.rows, w)}
        spans |= {f"seq{L}": missing_in_span(a, c.rows, L) for L in C.SEQ_LENS}
        full_clean[(asset, w)] = pd.Series(spans["full"] == 0, index=ends)
        for y in YEARS:
            m = ends.year == y
            year_rows.append(
                {"asset": asset, "window": w, "năm": y, "ngày gốc": int(m.sum())}
                | {f"ảnh hưởng {k}": int((v[m] > 0).sum()) for k, v in spans.items()}
                | {"max phiên thiếu (full)": int(spans["full"][m].max()) if m.any() else 0}
            )
        # Theo từng phiên thiếu: số ngày gốc 2014–2019 có cửa sổ phủ phiên đó
        firsts = {"full": a.dates[np.maximum(c.rows - w + 1, 0)]}
        firsts |= {f"seq{L}": a.dates[np.maximum(c.rows - L + 1, 0)] for L in C.SEQ_LENS}
        for m in a.missing:
            row = {"asset": asset, "window": w, "phiên thiếu": m.strftime("%Y-%m-%d")}
            for k, f in firsts.items():
                row[k] = int(((f < m) & (ends > m)).sum())
            if row["full"]:
                sess_rows.append(row)
    print(md(pd.DataFrame(year_rows).query("`ảnh hưởng full` > 0 or `ngày gốc` == 0")))
    print("\n_(chỉ in năm có ngày gốc bị ảnh hưởng; năm không in = 0)_\n")
    print("**Theo phiên thiếu** (số ngày gốc 2014–2019 có cửa sổ phủ phiên đó)\n")
    print(md(sess_rows))
    return full_clean


# ---------- mục 3 ----------


def step3(caches) -> dict:
    section("3. Số IMF")
    rows, ks = [], {}
    for (asset, w), c in caches.items():
        ends = pd.DatetimeIndex(c.df["end_date"])
        n = c.df["n_imf"].to_numpy(dtype=int)
        tr = ends <= TRAIN_END
        k = int(n[tr].min())
        ks[(asset, w)] = k
        for y in YEARS:
            m = ends.year == y
            vc = pd.Series(n[m]).value_counts().sort_index()
            rows.append(
                {"asset": asset, "window": w, "năm": y}
                | {"n_imf": " ".join(f"{i}:{v}" for i, v in vc.items())}
            )
        rows.append(
            {
                "asset": asset,
                "window": w,
                "năm": "**K đề xuất**",
                "n_imf": (
                    f"K={k} (min 2014–2018); > K: train {np.mean(n[tr] > k):.1%}, "
                    f"2019 {np.mean(n[~tr] > k):.1%}; < K trong 2019: {int((n[~tr] < k).sum())}; "
                    f"min/max 2019: {n[~tr].min()}/{n[~tr].max()}"
                ),
            }
        )
    print(md(rows))
    return ks


# ---------- mục 4 ----------


def step4(assets, caches, ks) -> None:
    section("4. Thang giá trị sau chuẩn hóa chia cho giá tại t (chỉ train 2014–2018)")
    print(
        f"`fixed_imf_matrix(K, seq_len={CC.KEEP_LAST})` (mọi điểm đã lưu) chia cho P_t = giá cuối "
        "cửa sổ. Cột `res` là residue + IMF sau K. `recon` = max |tổng cột − giá| / P_t.\n"
    )
    rows = []
    for (asset, w), c in caches.items():
        a = assets[asset]
        tr = np.flatnonzero(pd.DatetimeIndex(c.df["end_date"]) <= TRAIN_END)
        wins = [c.windows[i] for i in tr]
        rr = c.rows[tr]
        k = ks[(asset, w)]
        X = fixed_imf_matrix(wins, k, CC.KEEP_LAST)
        p_t = a.values[rr]
        Xn = X / p_t[:, None, None]
        idx = rr[:, None] + np.arange(-CC.KEEP_LAST + 1, 1)[None, :]
        recon = np.abs(X.sum(axis=2) - a.values[idx]).max() / p_t.min()
        for j in range(k + 1):
            col = Xn[:, :, j].ravel()
            rows.append(
                {
                    "asset": asset,
                    "window": w,
                    "cột": f"imf{j + 1}" if j < k else "res",
                    "min": col.min(),
                    "p01": np.quantile(col, 0.01),
                    "median": np.median(col),
                    "p99": np.quantile(col, 0.99),
                    "max": col.max(),
                    "std": col.std(),
                    "recon": recon if j == k else np.nan,
                }
            )
    print(md(rows, ".3g"))


# ---------- mục 5 ----------


def step5(prices, rejected, assets, caches, full_clean) -> None:
    section("5. Số mẫu (ngày gốc hợp lệ)")
    print(
        "Hợp lệ = có cửa sổ CEEMDAN + `make_windows(seq_len)` hợp lệ + published_at kịp (như "
        "`dlinear_data`) + target hợp lệ cả 7 h + ngày đích ≤ cuối giai đoạn (ADR-0008 mục 7) + "
        "baseline-q252 hợp lệ cả 7 h. Quy tắc A như trên; B = A + không có phiên thiếu nào trong "
        "toàn bộ cửa sổ decompose. MVP60 = quy tắc của `prepare_training_data` (cửa sổ 60, không "
        "cần CEEMDAN, không cần baseline); MVP60+bl thêm điều kiện baseline.\n"
    )
    rows_a, rows_b, rows_c, reason_rows = [], [], [], []
    for asset, a in assets.items():
        invalid = pd.to_datetime(rejected.loc[rejected["asset"] == asset, "date"]).tolist()
        frame = build_feature_frame(prices, asset, invalid_dates=invalid)
        full = calendars.sessions(a.calendar)
        series = pd.Series(a.values, index=a.dates)
        r_h = {
            h: horizon_log_returns(series, h, calendar=a.calendar, invalid_dates=invalid)
            for h in C.HORIZONS
        }
        bl = {h: B.baseline_valid(r_h[h], h) for h in C.HORIZONS}
        days, hour = PUBLISHED_AT_RULES[ASSETS[asset].primary.source]
        for period, (s, e) in (("train", C.TRAIN), ("val 2019", C.VALID)):
            base = calendars.sessions(a.calendar, s, e)
            end = np.datetime64(pd.Timestamp(e))
            y = np.column_stack([r_h[h].reindex(base).to_numpy() for h in C.HORIZONS])
            pos = full.get_indexer(base)
            targets = full.to_numpy()[pos[:, None] + np.arange(1, 8)]
            boundary_ok = (targets <= end).all(axis=1)
            target_ok = np.isfinite(y).all(axis=1)
            bl_ok = np.column_stack(
                [bl[h].reindex(base, fill_value=False).to_numpy(dtype=bool) for h in C.HORIZONS]
            ).all(axis=1)
            as_of = (base + pd.Timedelta(days=days, hours=hour)).to_numpy(dtype="datetime64[ns]")
            target_pub = targets[:, 0] + np.timedelta64(days, "D") + np.timedelta64(hour, "h")

            def win_ok(
                L: int, frame=frame, base=base, as_of=as_of, target_pub=target_pub
            ) -> np.ndarray:
                b = make_windows(frame, base, window=L)
                pub = b.max_input_published_at
                return b.valid & ~np.isnat(pub) & (pub <= as_of) & (as_of < target_pub)

            tgt = target_ok & boundary_ok
            mvp = win_ok(C.DLINEAR_WINDOW) & tgt
            base_row = {"asset": asset, "giai đoạn": period, "phiên": len(base)}
            mvp_cols = {"MVP60": int(mvp.sum()), "MVP60+bl": int((mvp & bl_ok).sum())}
            if period == "train":
                mvp_cols["manifest MVP"] = C.DLINEAR_MVP_TRAIN_N_VALID[asset]
            ra, rb, rc = dict(base_row) | mvp_cols, dict(base_row), dict(base_row)
            wins = {L: win_ok(L) for L in C.SEQ_LENS}
            has = {}
            for w in C.WINDOWS:
                c = caches[(asset, w)]
                has[w] = base.isin(pd.DatetimeIndex(c.df["end_date"]))
                clean = full_clean[(asset, w)].reindex(base, fill_value=False).to_numpy()
                for L in C.SEQ_LENS:
                    ok = has[w] & wins[L] & tgt & bl_ok
                    ra[f"w{w} L{L}"] = int(ok.sum())
                    rb[f"w{w} L{L}"] = int((ok & clean).sum())
                reason_rows.append(
                    {
                        "asset": asset,
                        "giai đoạn": period,
                        "window": w,
                        "phiên": len(base),
                        "không có cửa sổ CEEMDAN": int((~has[w]).sum()),
                        "make_windows(60) lỗi": int((~wins[60]).sum()),
                        "target NaN": int((~target_ok).sum()),
                        "ngày đích qua ranh giới": int((~boundary_ok).sum()),
                        "baseline không hợp lệ": int((~bl_ok).sum()),
                        "có phiên thiếu trong cửa sổ decompose": int((has[w] & ~clean).sum()),
                    }
                )
            for L in C.SEQ_LENS:
                both = has[252] & has[504] & wins[L] & tgt & bl_ok
                rc[f"L{L}"] = int(both.sum())
            rows_a.append(ra)
            rows_b.append(rb)
            rows_c.append(rc)
    print("**Quy tắc A** (cửa sổ decompose được phép chứa phiên thiếu)\n")
    print(md(rows_a))
    print("\n**Quy tắc B** (A + cửa sổ decompose không có phiên thiếu)\n")
    print(md(rows_b))
    print("\n**Tập chung 252 ∩ 504** (quy tắc A, dùng khi so 252 với 504, ADR-0007)\n")
    print(md(rows_c))
    print("\n**Lý do loại** (không loại trừ nhau; đếm trên mọi phiên của giai đoạn)\n")
    print(md(reason_rows))


# ---------- mục 6 ----------


def _redecompose(args) -> tuple[WindowIMF, WindowIMF]:
    """Cửa sổ kết thúc tại dòng i: từ chuỗi cắt tại t và từ chuỗi ≤ CUTOFF (có dữ liệu sau t)."""
    values, i, sid, cfg = args
    cut = causal_imf_windows(values[: i + 1], np.array([i]), cfg, seed_ids=np.array([sid]))[0]
    ext = causal_imf_windows(values, np.array([i]), cfg, seed_ids=np.array([sid]))[0]
    return cut, ext


def step6(assets, caches, ks, processes: int) -> None:
    section("6. Chống rò rỉ")
    print(
        f"{C.LEAK_N_ORIGINS} ngày gốc ngẫu nhiên (seed {C.LEAK_SEED}) mỗi tài sản × độ dài cửa sổ, "
        "trong 2014–2019. Decompose lại cửa sổ kết thúc tại t từ chuỗi cắt tại t (`cut`) và từ "
        "chuỗi ≤ 2019-12-31 có dữ liệu sau t (`ext`). So `fixed_imf_matrix(K, 128)` của `cut` với "
        f"cache (atol {C.LEAK_ATOL:g}) và `cut` với `ext` (từng bit).\n"
    )
    jobs, meta = [], []
    for (asset, w), c in caches.items():
        rng = np.random.default_rng(C.LEAK_SEED)
        pick = np.sort(rng.choice(len(c.df), size=C.LEAK_N_ORIGINS, replace=False))
        a = assets[asset]
        for j in pick:
            i = int(c.rows[j])
            jobs.append((a.values, i, cc.seed_id(asset, a.dates[i]), cfg_for(w)))
            meta.append((asset, w, j))
    if processes > 1:
        with Pool(processes) as p:
            res = p.map(_redecompose, jobs)
    else:
        res = [_redecompose(j) for j in jobs]

    agg: dict = {}
    for (asset, w, j), (cut, ext) in zip(meta, res, strict=True):
        c = caches[(asset, w)]
        k = ks[(asset, w)]
        cached = c.windows[j]
        m_cut = fixed_imf_matrix([cut], k, CC.KEEP_LAST)
        m_ext = fixed_imf_matrix([ext], k, CC.KEEP_LAST)
        m_cache = fixed_imf_matrix([cached], k, CC.KEEP_LAST)
        d = float(np.abs(m_cut - m_cache).max())
        g = agg.setdefault((asset, w), {"n": 0, "n_imf khớp": 0, "max|Δ| cache": 0.0, "đạt": 0})
        g["n"] += 1
        g["n_imf khớp"] += int(cut.n_imf == cached.n_imf)
        g["max|Δ| cache"] = max(g["max|Δ| cache"], d)
        g["đạt"] += int(np.allclose(m_cut, m_cache, rtol=0, atol=C.LEAK_ATOL))
        g["cut == ext (bit)"] = g.get("cut == ext (bit)", 0) + int(
            cut.n_imf == ext.n_imf and np.array_equal(m_cut, m_ext)
        )
        g.setdefault("ngày", []).append(c.df["end_date"].iloc[j].strftime("%Y-%m-%d"))
    rows = []
    for (asset, w), g in agg.items():
        days = g.pop("ngày")
        rows.append({"asset": asset, "window": w} | g | {"ví dụ ngày": ", ".join(days[:3]) + "…"})
    print(md(rows, ".3g"))
    n_fail = sum(r["n"] - r["đạt"] for r in rows) + sum(
        r["n"] - r["cut == ext (bit)"] for r in rows
    )
    print(f"\n**Kết quả: {'ĐẠT' if n_fail == 0 else f'KHÔNG ĐẠT ({n_fail} lỗi)'}**")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"))
    ap.add_argument("--processes", type=int, default=C.PROCESSES)
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    lake = Path(args.lake_dir)
    st = storage.LocalStorage(str(lake))
    clean_dt = C.CLEAN_DT or storage.latest_dt(st, "clean/prices", must_have="prices.parquet")
    prices, rejected = read_clean(lake, clean_dt)
    ref_dir = lake / "clean" / "prices" / f"dt={C.REFERENCE_CLEAN_DT}"
    prices_ref = read_clean(lake, C.REFERENCE_CLEAN_DT)[0] if ref_dir.exists() else None
    print("# Probe K3: cache CEEMDAN và số mẫu\n")
    print(
        f"Python {platform.python_version()} ({platform.system()}), numpy {np.__version__}, "
        f"EMD-signal {PYEMD_VERSION}, pandas {pd.__version__}. Clean dt={clean_dt}, cắt tại "
        f"{C.CUTOFF} (ngày lớn nhất đọc được: {prices['date'].max().date()})."
    )
    assets = {asset: asset_data(prices, asset) for asset in C.ASSETS}

    timings = {}
    t = time.perf_counter()
    caches, stop = step1(st, clean_dt, assets, prices_ref)
    timings["1"] = time.perf_counter() - t
    if stop:
        print("\n**DỪNG**: cfg_hash khác hoặc price_hash lệch. Không chạy mục 2–6.")
        return 2
    for name, fn in (
        ("2", lambda: step2(assets, caches)),
        ("3", lambda: step3(caches)),
    ):
        t = time.perf_counter()
        out = fn()
        timings[name] = time.perf_counter() - t
        if name == "2":
            full_clean = out
        else:
            ks = out
    t = time.perf_counter()
    step4(assets, caches, ks)
    timings["4"] = time.perf_counter() - t
    t = time.perf_counter()
    step5(prices, rejected, assets, caches, full_clean)
    timings["5"] = time.perf_counter() - t
    t = time.perf_counter()
    step6(assets, caches, ks, args.processes)
    timings["6"] = time.perf_counter() - t

    section("Thời gian chạy")
    print(md([{"mục": k, "giây": round(v, 1)} for k, v in timings.items()]))
    print(f"\nTổng: {time.perf_counter() - t0:.1f} s ({args.processes} tiến trình cho mục 6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
