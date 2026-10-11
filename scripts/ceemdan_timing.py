"""Đo thời gian CEEMDAN theo cửa sổ (src/forecast/decomposition.causal_imf_windows) cho vàng và
ngoại suy thời gian cache. Cấu hình: configs/ceemdan_timing.py.

Chạy:
  python scripts/ceemdan_timing.py
Đầu ra (gitignore): data/lake/experiments/ceemdan_timing/dt=<ngày chạy>/results.json, summary.md

Chỉ đọc giá GLD tới DATA_END (2019); ngày gốc lấy mẫu trong 2014–2019. Số cửa sổ cần cache tới nay
được đếm từ lịch phiên (không đọc dữ liệu 2020 → nay).

Hai chế độ của PyEMD:
- inner=default: CEEMDAN(trials=...) như trong decompose_window; PyEMD 1.10 mặc định parallel=True,
  mỗi lần gọi tự mở Pool(os.cpu_count()).
- inner=off: thay CEEMDAN bằng CEEMDAN(parallel=False) (chỉ trong thí nghiệm này, qua biến môi
  trường để tiến trình con của Pool cũng nhận). Kết quả số phải giống hệt inner=default.
"""

from __future__ import annotations

import functools
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configs import ceemdan_timing as C
from src.data import calendars, storage
from src.data.config import ASSETS
from src.forecast import decomposition as D

_ORIG_CEEMDAN = D.CEEMDAN
_ENV = "CPAWS_CEEMDAN_INNER"


def _apply_inner_mode() -> None:
    """Chạy ở tiến trình chính và ở mỗi tiến trình con (spawn import lại module này)."""
    off = os.environ.get(_ENV, "default") == "off"
    D.CEEMDAN = functools.partial(_ORIG_CEEMDAN, parallel=False) if off else _ORIG_CEEMDAN


_apply_inner_mode()


def set_inner(mode: str) -> None:
    os.environ[_ENV] = mode
    _apply_inner_mode()


# ---------- dữ liệu ----------


def load_series(lake: Path) -> tuple[str, np.ndarray, pd.DatetimeIndex]:
    st = storage.LocalStorage(lake)
    dt = storage.latest_dt(st, "clean/prices", must_have="prices.parquet")
    p = storage.read_parquet(st, f"clean/prices/dt={dt}/prices.parquet")
    g = p[(p["asset"] == C.ASSET) & (p["date"] <= pd.Timestamp(C.DATA_END))]
    g = g.sort_values("date")
    dates = pd.DatetimeIndex(g["date"])
    cal = calendars.sessions(ASSETS[C.ASSET].calendar, dates.min(), dates.max())
    if not cal.equals(dates):
        raise SystemExit(f"{C.ASSET}: chuỗi tới {C.DATA_END} thiếu phiên so với lịch")
    return dt, g["price"].to_numpy(dtype=float), dates


def sample_origins(dates: pd.DatetimeIndex, window: int, n: int, salt: int = 0) -> np.ndarray:
    """n ngày gốc trải đều trong [SAMPLE_START, DATA_END], đủ lịch sử cho window."""
    lo = max(int(dates.searchsorted(pd.Timestamp(C.SAMPLE_START))), window - 1)
    hi = len(dates) - 1
    base = np.linspace(lo, hi, n + 2)[1:-1].round().astype(int)
    return np.clip(base + salt, lo, hi)


def cfg_of(window: int, trials: int) -> D.CeemdanConfig:
    return D.CeemdanConfig(
        window=window, trials=trials, seq_len=C.SEQ_LEN, n_imfs=C.N_IMFS, seed=C.SEED
    )


def n_components(out: np.ndarray) -> np.ndarray:
    """Số thành phần thật (IMF + residue) của mỗi cửa sổ = số cột không phải toàn 0 ở cuối
    (_fix_width đệm 0 bên phải)."""
    nonzero = np.any(out != 0, axis=1)  # (n_windows, n_imfs)
    return np.array([int(np.max(np.where(r)[0])) + 1 if r.any() else 0 for r in nonzero])


# ---------- đo ----------


def time_sequential(s, origins, cfg) -> tuple[list[float], np.ndarray]:
    times, outs = [], []
    for t in origins:
        t0 = time.perf_counter()
        outs.append(D.causal_imf_windows(s, np.array([t]), cfg)[0])
        times.append(time.perf_counter() - t0)
    return times, np.stack(outs)


def time_parallel(s, origins, cfg, processes) -> tuple[float, np.ndarray]:
    t0 = time.perf_counter()
    out = D.causal_imf_windows(s, origins, cfg, processes=processes)
    return time.perf_counter() - t0, out


def stats_s(x) -> dict:
    x = np.asarray(x, dtype=float)
    return {
        "n": len(x),
        "mean_s": round(float(x.mean()), 3),
        "median_s": round(float(np.median(x)), 3),
        "p90_s": round(float(np.quantile(x, 0.9)), 3),
        "max_s": round(float(x.max()), 3),
    }


def count_origins_to_now(run_dt: str) -> dict[str, int]:
    return {
        a: len(calendars.sessions(ASSETS[a].calendar, C.EXTRAPOLATE_START, run_dt))
        for a in C.EXTRAPOLATE_ASSETS
    }


def git_head() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT, check=False
        ).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except OSError:
        return "unknown"


# ---------- main ----------


def run(lake: Path, run_dt: str) -> dict:
    input_dt, s, dates = load_series(lake)
    res: dict = {
        "meta": {
            "run_dt": run_dt,
            "input_dt": input_dt,
            "commit": git_head(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "series_last_date": str(dates[-1].date()),
            "config": {k: getattr(C, k) for k in dir(C) if k.isupper()},
        },
        "sequential": [],
        "parallel": [],
        "checks": {},
    }
    seq_out: dict = {}
    comp_counts: dict = {}

    # 1) Tuần tự, inner=off
    set_inner("off")
    for w, tr in C.GRID:
        cfg = cfg_of(w, tr)
        o = sample_origins(dates, w, C.N_SEQ)
        times, out = time_sequential(s, o, cfg)
        seq_out[(w, tr)] = (o, out)
        comp_counts.setdefault((w, tr), []).extend(n_components(out).tolist())
        res["sequential"].append({"window": w, "trials": tr, "inner": "off", **stats_s(times)})
        print(f"seq inner=off w={w} trials={tr}: median {np.median(times):.2f}s", flush=True)

    # 2) Tuần tự, inner=default (PyEMD tự mở Pool mỗi lần gọi)
    set_inner("default")
    for w, tr in C.GRID:
        cfg = cfg_of(w, tr)
        o = seq_out[(w, tr)][0][: C.N_SEQ_INNER]
        times, out = time_sequential(s, o, cfg)
        same = bool(np.array_equal(out, seq_out[(w, tr)][1][: C.N_SEQ_INNER]))
        res["sequential"].append(
            {"window": w, "trials": tr, "inner": "default", **stats_s(times), "same_as_off": same}
        )
        print(f"seq inner=default w={w} trials={tr}: median {np.median(times):.2f}s", flush=True)

    # 3) Song song ở tầng ngoài (Pool của causal_imf_windows), inner=off
    set_inner("off")
    runs = [(w, tr, p) for (w, tr) in C.PAR_GRID for p in C.PAR_PROCESSES]
    runs += [(w, tr, C.PAR_DEFAULT_PROCESSES) for (w, tr) in C.GRID if (w, tr) not in C.PAR_GRID]
    for w, tr, procs in runs:
        cfg = cfg_of(w, tr)
        o = np.unique(np.concatenate([seq_out[(w, tr)][0], sample_origins(dates, w, C.N_PAR, 1)]))
        wall, out = time_parallel(s, o, cfg, procs)
        idx = np.searchsorted(o, seq_out[(w, tr)][0])
        same = bool(np.array_equal(out[idx], seq_out[(w, tr)][1]))
        comp_counts.setdefault((w, tr), []).extend(np.delete(n_components(out), idx).tolist())
        res["parallel"].append(
            {
                "window": w,
                "trials": tr,
                "inner": "off",
                "processes": procs,
                "n_windows": len(o),
                "wall_s": round(wall, 2),
                "s_per_window": round(wall / len(o), 3),
                "same_as_sequential": same,
            }
        )
        print(f"par p={procs} w={w} trials={tr}: {wall / len(o):.3f}s/window", flush=True)

    # 4) Song song tầng ngoài với inner=default: tiến trình daemon không được mở Pool con
    set_inner("default")
    try:
        time_parallel(s, sample_origins(dates, 252, 2), cfg_of(252, 50), 2)
        res["checks"]["outer_pool_with_inner_default"] = "ok"
    except Exception as e:  # noqa: BLE001 - ghi lại lỗi để báo cáo
        res["checks"]["outer_pool_with_inner_default"] = f"{type(e).__name__}: {e}"
    set_inner("off")

    # 5) Chạy lại cùng seed → cùng kết quả
    w, tr = 504, 100
    o, first = seq_out[(w, tr)]
    _, again = time_sequential(s, o[:4], cfg_of(w, tr))
    res["checks"]["same_seed_rerun_identical"] = bool(np.array_equal(again, first[:4]))

    # 6) Nhân quả: cắt chuỗi ngay sau t cho cùng IMF như chuỗi có thêm dữ liệu sau t (tới 2019)
    causal = []
    for w, tr in ((252, 50), (504, 100)):
        o, full = seq_out[(w, tr)]
        for k, t in enumerate(o[:6]):
            cut = D.causal_imf_windows(s[: t + 1], np.array([t]), cfg_of(w, tr))[0]
            causal.append(bool(np.array_equal(cut, full[k])))
    res["checks"]["future_append_does_not_change_imfs"] = {"n": len(causal), "all": all(causal)}

    # 7) Số thành phần (IMF + residue) theo cửa sổ
    res["n_components"] = {
        f"{w}x{tr}": {str(k): int(v) for k, v in pd.Series(c).value_counts().sort_index().items()}
        for (w, tr), c in comp_counts.items()
    }

    # 8) Ngoại suy
    n_orig = count_origins_to_now(run_dt)
    total = sum(n_orig.values())
    par8 = {
        (r["window"], r["trials"]): r["s_per_window"]
        for r in res["parallel"]
        if r["processes"] == C.PAR_DEFAULT_PROCESSES
    }
    seq_med = {
        (r["window"], r["trials"]): r["median_s"] for r in res["sequential"] if r["inner"] == "off"
    }
    res["extrapolation"] = {"origins_2014_to_now": n_orig, "total_windows": total, "by_config": []}
    for w, tr in C.GRID:
        sp = seq_med[(w, tr)]
        res["extrapolation"]["by_config"].append(
            {
                "window": w,
                "trials": tr,
                "full_cache_sequential_h": round(total * sp / 3600, 2),
                "full_cache_8proc_h": round(total * par8[(w, tr)] / 3600, 2),
                "daily_4_windows_sequential_s": round(4 * sp, 1),
                "daily_fits_lambda": 4 * sp * 2 < C.LAMBDA_TIMEOUT_S,  # lề an toàn x2
            }
        )
    return res


def markdown(res: dict) -> str:
    m = res["meta"]
    L = [
        (
            f"Đầu vào `clean/prices/dt={m['input_dt']}`, GLD tới {m['series_last_date']}; "
            f"commit `{m['commit']}`; {m['platform']}, {m['cpu_count']} CPU logic, "
            f"Python {m['python']}.\n"
        ),
        "### Tuần tự (giây mỗi cửa sổ)\n",
        "| window | trials | PyEMD inner | n | median | p90 | max | giống inner=off |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res["sequential"]:
        L.append(
            f"| {r['window']} | {r['trials']} | {r['inner']} | {r['n']} | {r['median_s']} | "
            f"{r['p90_s']} | {r['max_s']} | {r.get('same_as_off', '—')} |"
        )
    L += [
        "\n### Song song tầng ngoài (`causal_imf_windows(processes=k)`, inner=off)\n",
        "| window | trials | k | số cửa sổ | tổng (s) | s/cửa sổ | giống tuần tự |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in res["parallel"]:
        L.append(
            f"| {r['window']} | {r['trials']} | {r['processes']} | {r['n_windows']} | "
            f"{r['wall_s']} | {r['s_per_window']} | {r['same_as_sequential']} |"
        )
    e = res["extrapolation"]
    L += [
        f"\n### Ngoại suy: {e['total_windows']} cửa sổ ({e['origins_2014_to_now']})\n",
        (
            "| window | trials | cache toàn bộ, tuần tự (giờ) | cache toàn bộ, 8 tiến trình (giờ) | "
            "cập nhật hằng ngày 4 cửa sổ, tuần tự (s) |"
        ),
        "|---|---|---|---|---|",
    ]
    for r in e["by_config"]:
        L.append(
            f"| {r['window']} | {r['trials']} | {r['full_cache_sequential_h']} | "
            f"{r['full_cache_8proc_h']} | {r['daily_4_windows_sequential_s']} |"
        )
    L += ["\n### Kiểm tra\n", "```json", json.dumps(res["checks"], indent=2, ensure_ascii=False)]
    L += [json.dumps({"n_components": res["n_components"]}, indent=2), "```"]
    return "\n".join(L)


def main() -> None:
    run_dt = datetime.now(UTC).date().isoformat()
    out = ROOT / "data" / "lake" / "experiments" / "ceemdan_timing" / f"dt={run_dt}"
    out.mkdir(parents=True, exist_ok=True)
    res = run(ROOT / "data" / "lake", run_dt)
    (out / "results.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(res), encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
