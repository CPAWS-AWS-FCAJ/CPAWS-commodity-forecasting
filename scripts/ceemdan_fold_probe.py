"""Probe: CEEMDAN với max_imf=K có giống lần chạy đầy đủ rồi gộp phần đuôi vào residue không?

(a) CEEMDAN(max_imf=K)                    → IMF1..K + residue
(b) CEEMDAN đầy đủ (max_imf=-1)           → giữ IMF1..K, residue_b = residue + tổng IMF(K+1..)
K = số IMF nhỏ nhất quan sát được trên mẫu. Cùng seed (seed + origin như decompose_window),
parallel=False. Chỉ dùng GLD tới 2019; 10 ngày gốc trải đều trong 2014–2019.

Chạy: python scripts/ceemdan_fold_probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PyEMD import CEEMDAN

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import storage

SEED, TRIALS, N = 42, 50, 10


def gold_to_2019() -> tuple[np.ndarray, pd.DatetimeIndex]:
    st = storage.LocalStorage(ROOT / "data" / "lake")
    dt = storage.latest_dt(st, "clean/prices", must_have="prices.parquet")
    p = storage.read_parquet(st, f"clean/prices/dt={dt}/prices.parquet")
    g = p[(p["asset"] == "gold") & (p["date"] <= "2019-12-31")].sort_values("date")
    return g["price"].to_numpy(float), pd.DatetimeIndex(g["date"])


def run(x: np.ndarray, seed: int, max_imf: int) -> np.ndarray:
    c = CEEMDAN(trials=TRIALS, parallel=False)
    c.noise_seed(seed)
    return c(x, max_imf=max_imf)  # các dòng: IMF1..n, dòng cuối là residue


def main() -> None:
    s, dates = gold_to_2019()
    out = {}
    for window in (252, 504):
        lo = max(int(dates.searchsorted(pd.Timestamp("2014-01-01"))), window - 1)
        origins = np.linspace(lo, len(s) - 1, N + 2)[1:-1].round().astype(int)
        full = {t: run(s[t - window + 1 : t + 1], SEED + int(t), -1) for t in origins}
        n_imf = {t: f.shape[0] - 1 for t, f in full.items()}
        k = min(n_imf.values())
        rows = []
        for t in origins:
            a = run(s[t - window + 1 : t + 1], SEED + int(t), k)
            f = full[t]
            b = np.vstack([f[:k], f[k:].sum(axis=0)])  # IMF1..K, residue + đuôi
            assert a.shape == b.shape, (a.shape, b.shape)
            scale = np.abs(s[t - window + 1 : t + 1]).max()
            rows.append(
                {
                    "origin": str(dates[t].date()),
                    "n_imf_full": n_imf[t],
                    "max_abs_imfs": float(np.abs(a[:k] - b[:k]).max()),
                    "max_abs_residue": float(np.abs(a[k] - b[k]).max()),
                    "max_rel_to_price": float(np.abs(a - b).max() / scale),
                    "imfs_bit_identical": bool(np.array_equal(a[:k], b[:k])),
                }
            )
        out[f"window_{window}"] = {
            "K": k,
            "n_imf_counts": pd.Series(n_imf).value_counts().sort_index().to_dict(),
            "max_abs": max(max(r["max_abs_imfs"], r["max_abs_residue"]) for r in rows),
            "max_rel_to_price": max(r["max_rel_to_price"] for r in rows),
            "rows": rows,
        }
    print(json.dumps(out, indent=2, default=int))


if __name__ == "__main__":
    main()
