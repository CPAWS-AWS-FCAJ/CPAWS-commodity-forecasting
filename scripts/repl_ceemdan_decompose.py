"""Minh họa CEEMDAN + LSTM, bước 1: tách lại CEEMDAN từ dữ liệu ≤ 2018 (R-causal và R-full).

Chạy:
  python scripts/repl_ceemdan_decompose.py [--lake-dir data/lake] [--processes 8] [--limit N]

Kế hoạch: docs/experiments/ceemdan-lstm-replication-plan.md mục 3.3. Đọc bản clean
configs/k3_grid.CLEAN_DT ở lake local (cắt tại 2018-12-31 ngay khi đọc), không gọi AWS, không đọc
cache ADR-0007. Ghi vào data/eval/repl-ceemdan-lstm/ (gitignore; --limit ghi vào probe/):
  r_causal_<asset>.parquet  end_date, seed_id, price_hash, n_imf, imf1, imf2, imf3, rest
                            (mỗi ô thành phần: SEQ_LEN giá trị cuối của cửa sổ kết thúc tại end_date)
  r_full_<asset>.parquet    date, imf1, imf2, imf3, rest (một lần tách toàn chuỗi 2012–2018)
  manifest.json             CLEAN_DT, SHA-256 bản clean, cfg + cfg.hash(), phiên bản, commit, thời gian

--limit N: chỉ N cửa sổ R-causal mỗi tài sản, rải đều trên 2014–2018 (probe thời gian); R-full vẫn
chạy đủ. Chỉ in số tổng hợp, không in giá hay giá trị IMF. Mã thoát: 2 khi đọc được dữ liệu sau
CUTOFF, 3 khi thiếu bản clean ở local.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.experiments.repl_ceemdan_lstm import config as C
from src.experiments.repl_ceemdan_lstm.data import CutoffError, asset_series, read_clean
from src.experiments.repl_ceemdan_lstm.decompose import causal_origins, r_causal, r_full
from src.forecast.decomposition import PYEMD_VERSION

# Phiên bản lúc dựng cache ADR-0007 (cfg 4c3229533ae3), để giải thích khi cfg_hash lệch
CACHE_VERSIONS = {"EMD-signal": "1.10.0", "numpy": "2.4.6"}


def git_info() -> dict:
    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    return {"commit": run("log", "-1", "--format=%H"), "dirty": bool(run("status", "--porcelain"))}


def md(rows: list[dict]) -> str:
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def _timed_full(s, cfg):
    t = time.perf_counter()
    df, n_imf = r_full(s, cfg)
    return df, n_imf, time.perf_counter() - t


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake-dir", default=str(ROOT / "data" / "lake"))
    ap.add_argument("--processes", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="chỉ N cửa sổ mỗi tài sản (probe)")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / C.OUT_SUBDIR))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252
    t0 = time.perf_counter()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    try:
        clean = read_clean(args.lake_dir, C.CLEAN_DT)
    except FileNotFoundError as e:
        print(f"DỪNG: {e}. Tải bản clean dt={C.CLEAN_DT} về lake local rồi chạy lại.")
        return 3
    except CutoffError as e:
        print(f"DỪNG: {e}")
        return 2

    cfg = C.ceemdan_config()
    h = cfg.hash()
    versions = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "EMD-signal": PYEMD_VERSION,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": version("pyarrow"),
    }
    hash_note = "khớp"
    if h != C.EXPECTED_CFG_HASH:
        diff = [
            f"{k} {versions[k]} (cache {v})" for k, v in CACHE_VERSIONS.items() if versions[k] != v
        ]
        hash_note = "lệch: " + (", ".join(diff) or "phiên bản như cache, kiểm lại tham số cfg")

    out = Path(args.out_dir) / ("probe" if args.limit else "")
    out.mkdir(parents=True, exist_ok=True)
    print("# Minh họa CEEMDAN + LSTM, bước 1: tách lại CEEMDAN (≤ 2018)\n")
    print(
        f"Python {versions['python']} ({versions['platform']}), EMD-signal {PYEMD_VERSION}, "
        f"numpy {np.__version__}, pandas {pd.__version__}. Clean dt={clean.clean_dt}, cắt tại "
        f"{C.CUTOFF}; ngày lớn nhất đọc được: prices {clean.prices['date'].max().date()}, "
        f"rejected {clean.rejected['date'].max().date() if len(clean.rejected) else '-'}."
    )
    print(f"\ncfg {asdict(cfg)}, cfg.hash() = {h}, kỳ vọng {C.EXPECTED_CFG_HASH}: {hash_note}.")
    print(
        f"Tiến trình: {args.processes}; limit: {args.limit or 'không (chạy đủ)'}; ghi vào {out}\n"
    )

    series = {a: asset_series(clean.prices, a) for a in C.ASSETS}
    rows, stats = [], {}
    with Pool(args.processes) as pool:
        for asset, s in series.items():
            origins = causal_origins(s, cfg)
            pick = origins
            if args.limit:  # rải đều trên 2014–2018 để ước tính thời gian và khoảng n_imf
                at = np.linspace(0, len(origins) - 1, args.limit).round().astype(int)
                pick = origins[np.unique(at)]
            t = time.perf_counter()
            df, _ = r_causal(s, cfg, pick, pool=pool)
            sec = time.perf_counter() - t
            df.to_parquet(out / f"r_causal_{asset}.parquet", index=False)
            stats[asset] = {
                "r_causal": {
                    "n_origins": len(origins),
                    "n_computed": len(pick),
                    "first_end": str(s.dates[origins[0]].date()),
                    "last_end": str(s.dates[origins[-1]].date()),
                    "n_imf_min": int(df["n_imf"].min()),
                    "n_imf_max": int(df["n_imf"].max()),
                    "seconds": round(sec, 2),
                }
            }
            print(f"- {asset}: R-causal {len(pick)}/{len(origins)} cửa sổ, {sec:.1f} s", flush=True)

        t = time.perf_counter()
        full = pool.starmap(_timed_full, [(s, cfg) for s in series.values()])
        full_wall = time.perf_counter() - t
    for (asset, s), (df, n_imf, sec) in zip(series.items(), full, strict=True):
        df.to_parquet(out / f"r_full_{asset}.parquet", index=False)
        stats[asset]["r_full"] = {
            "length": len(s.values),
            "start": str(s.dates[0].date()),
            "end": str(s.dates[-1].date()),
            "n_imf": n_imf,
            "seconds": round(sec, 2),
        }

    est_total = 0.0
    for asset in C.ASSETS:
        rc, rf = stats[asset]["r_causal"], stats[asset]["r_full"]
        per = rc["seconds"] / rc["n_computed"]  # thời gian thực / cửa sổ khi chạy song song
        est = per * rc["n_origins"]
        est_total += est
        rows.append(
            {
                "asset": asset,
                "cửa sổ R-causal (đủ)": rc["n_origins"],
                "ngày cuối": f"{rc['first_end']} → {rc['last_end']}",
                "đã tách": rc["n_computed"],
                "n_imf min–max": f"{rc['n_imf_min']}–{rc['n_imf_max']}",
                "s/cửa sổ (wall)": f"{per:.3f}",
                "ước tính đủ (phút)": f"{est / 60:.1f}",
                "R-full độ dài": rf["length"],
                "R-full n_imf": rf["n_imf"],
                "R-full s": rf["seconds"],
            }
        )
    est_total += full_wall
    print("\n" + md(rows))
    print(
        f"\nR-full (4 tài sản song song): {full_wall:.1f} s. Ước tính chạy đủ với "
        f"{args.processes} tiến trình: {est_total / 60:.1f} phút."
    )

    manifest = {
        "step": "repl-ceemdan-lstm/decompose",
        "clean_dt": clean.clean_dt,
        "cutoff": C.CUTOFF,
        "warmup_start": C.WARMUP_START,
        "causal_start": C.CAUSAL_START,
        "sha256": clean.sha256,
        "cfg": asdict(cfg),
        "cfg_hash": h,
        "expected_cfg_hash": C.EXPECTED_CFG_HASH,
        "cfg_hash_note": hash_note,
        "max_imf": C.MAX_IMF,
        "components": list(C.COMPONENTS),
        "seq_len": C.SEQ_LEN,
        "versions": versions,
        "git": git_info(),
        "processes": args.processes,
        "limit": args.limit,
        "started_at": started_at,
        "seconds_total": round(time.perf_counter() - t0, 1),
        "estimated_full_seconds": round(est_total, 1),
        "assets": stats,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nTổng: {manifest['seconds_total']} s. Manifest: {out / 'manifest.json'}")
    if args.limit:
        print("\nLệnh chạy đủ:\n  python scripts/repl_ceemdan_decompose.py --processes 8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
