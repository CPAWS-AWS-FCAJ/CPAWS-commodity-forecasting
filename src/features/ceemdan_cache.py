"""Cache IMF CEEMDAN theo cửa sổ (ADR-0007). Cùng layout cho local (data/lake/) và S3.

  features/ceemdan/asset=<asset>/window=<window>/cfg=<cfg_hash>/config.json
  features/ceemdan/asset=<asset>/window=<window>/cfg=<cfg_hash>/month=YYYY-MM.parquet

Mỗi dòng Parquet là một cửa sổ, khóa (asset, window, cfg_hash, end_date) và price_hash:
  asset, window, end_date, seed_id, cfg_hash, price_hash, n_imf, keep_last,
  imfs (list float64, n_imf × keep_last theo hàng), residue (list float64, keep_last),
  pyemd_version, numpy_version, platform
cfg_hash = CeemdanConfig.hash() (trials, epsilon, seed, keep_last, phiên bản PyEMD và numpy).
price_hash = sha256 của `window` giá float64 trong cửa sổ: giá trong cửa sổ đổi thì tính lại.
seed_id = số ngày từ 1970-01-01 tới end_date + zlib.crc32(tên tài sản); noise seed của PyEMD là
  (cfg.seed + seed_id) % 2**32. Không phụ thuộc vị trí dòng trong chuỗi, không dùng hash() của
  Python; bốn tài sản cùng ngày dùng bộ nhiễu khác nhau.

Chuỗi giá là các dòng được giữ trong prices.parquet của tài sản (cửa sổ tính theo dòng, không theo
lịch). Cửa sổ chỉ dùng dữ liệu tới end_date (causal_imf_windows).

Tái lập: cùng nền tảng → giống hệt từng bit. Giữa Windows (máy local) và Linux (Lambda, SageMaker)
chỉ so theo dung sai (atol 1e-10), vì libm và thứ tự phép tính dấu phẩy động có thể khác.
"""

from __future__ import annotations

import hashlib
import platform
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from src.data import storage
from src.forecast.decomposition import (
    PYEMD_VERSION,
    CeemdanConfig,
    WindowIMF,
    causal_imf_windows,
)

PREFIX = "features/ceemdan"
RECHECK_SESSIONS = 5  # cập nhật hằng ngày: kiểm lại hash giá của các cửa sổ kết thúc trong 5 phiên
COLUMNS = [
    "asset",
    "window",
    "end_date",
    "seed_id",
    "cfg_hash",
    "price_hash",
    "n_imf",
    "keep_last",
    "imfs",
    "residue",
    "pyemd_version",
    "numpy_version",
    "platform",
]
_EPOCH = pd.Timestamp("1970-01-01")


@dataclass
class CacheStats:
    computed: int = 0
    reused: int = 0
    skipped_no_history: int = 0
    months_written: list[str] = field(default_factory=list)


def prefix(asset: str, cfg: CeemdanConfig) -> str:
    return f"{PREFIX}/asset={asset}/window={cfg.window}/cfg={cfg.hash()}"


def seed_id(asset: str, d: pd.Timestamp) -> int:
    """Số ngày từ 1970-01-01 tới d cộng crc32 của tên tài sản (cố định giữa các tiến trình)."""
    return int((pd.Timestamp(d) - _EPOCH).days) + zlib.crc32(asset.encode("utf-8"))


def price_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values, dtype=np.float64).tobytes()).hexdigest()[:16]


def asset_series(prices: pd.DataFrame, asset: str) -> tuple[pd.DatetimeIndex, np.ndarray]:
    d = prices[prices["asset"] == asset].sort_values("date")
    return pd.DatetimeIndex(d["date"]), d["price"].to_numpy(dtype=float)


def _month(d: pd.Timestamp) -> str:
    return pd.Timestamp(d).strftime("%Y-%m")


def _month_key(asset: str, cfg: CeemdanConfig, month: str) -> str:
    return f"{prefix(asset, cfg)}/month={month}.parquet"


def read_month(st, asset: str, cfg: CeemdanConfig, month: str) -> pd.DataFrame:
    """Đọc một tháng; file thiếu hoặc hỏng (bị ngắt khi đang ghi) → bảng rỗng (sẽ tính lại)."""
    key = _month_key(asset, cfg, month)
    if not st.exists(key):
        return pd.DataFrame(columns=COLUMNS)
    try:
        return storage.read_parquet(st, key)
    except Exception:  # noqa: BLE001 - file dở dang: coi như chưa có
        return pd.DataFrame(columns=COLUMNS)


def _write_month(st, asset: str, cfg: CeemdanConfig, month: str, df: pd.DataFrame) -> None:
    df = df.sort_values("end_date").reset_index(drop=True)[COLUMNS]
    storage.write_parquet(st, _month_key(asset, cfg, month), df)


def _write_config(st, asset: str, cfg: CeemdanConfig) -> None:
    key = f"{prefix(asset, cfg)}/config.json"
    if not st.exists(key):
        meta = {
            **asdict(cfg),
            "cfg_hash": cfg.hash(),
            "pyemd": PYEMD_VERSION,
            "numpy": np.__version__,
        }
        storage.write_json(st, key, meta)


def _rows(asset, cfg, dates, values, windows: list[WindowIMF]) -> pd.DataFrame:
    rows = []
    for w in windows:
        t = w.origin
        rows.append(
            {
                "asset": asset,
                "window": cfg.window,
                "end_date": dates[t],
                "seed_id": seed_id(asset, dates[t]),
                "cfg_hash": cfg.hash(),
                "price_hash": price_hash(values[t - cfg.window + 1 : t + 1]),
                "n_imf": w.n_imf,
                "keep_last": cfg.keep_last,
                "imfs": w.imfs.ravel(),
                "residue": w.residue,
                "pyemd_version": PYEMD_VERSION,
                "numpy_version": np.__version__,
                "platform": platform.system(),
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def to_windows(df: pd.DataFrame) -> list[WindowIMF]:
    """Dòng cache → WindowIMF (origin = -1; dùng end_date để căn ngày)."""
    out = []
    for r in df.itertuples(index=False):
        imfs = np.asarray(r.imfs, dtype=float).reshape(int(r.n_imf), int(r.keep_last))
        out.append(WindowIMF(-1, imfs, np.asarray(r.residue, dtype=float)))
    return out


def ensure(
    st,
    prices: pd.DataFrame,
    asset: str,
    cfg: CeemdanConfig,
    origins: pd.DatetimeIndex,
    recheck: pd.DatetimeIndex | None = None,
    processes: int | None = None,
    pool=None,
    log: Callable[[str], None] = lambda _m: None,
) -> CacheStats:
    """Bảo đảm cache có các cửa sổ kết thúc tại `origins` (ngày phải có trong chuỗi).

    Cửa sổ đã có trong cache được dùng lại; riêng các ngày trong `recheck` thì so price_hash và
    tính lại nếu giá trong cửa sổ đã đổi. Ghi theo tháng, xong tháng nào ghi tháng đó, nên bị ngắt
    giữa chừng thì chạy lại sẽ tiếp tục từ tháng chưa xong."""
    dates, values = asset_series(prices, asset)
    pos = pd.Series(np.arange(len(dates)), index=dates)
    recheck = pd.DatetimeIndex([]) if recheck is None else pd.DatetimeIndex(recheck)
    stats = CacheStats()
    _write_config(st, asset, cfg)
    wanted = pd.DatetimeIndex(origins).intersection(dates).sort_values()
    for month, ds in pd.Series(wanted, index=wanted).groupby(_month):
        idx = pos.loc[pd.DatetimeIndex(ds)].to_numpy()
        ok = idx >= cfg.window - 1
        stats.skipped_no_history += int((~ok).sum())
        idx = idx[ok]
        if not len(idx):
            continue
        cached = read_month(st, asset, cfg, month)
        have = dict(zip(pd.DatetimeIndex(cached["end_date"]), cached["price_hash"], strict=True))
        todo = []
        for t in idx:
            d = dates[t]
            if d in have and (
                d not in recheck or have[d] == price_hash(values[t - cfg.window + 1 : t + 1])
            ):
                stats.reused += 1
                continue
            todo.append(t)
        if not todo:
            continue
        todo = np.array(todo)
        wins = causal_imf_windows(
            values,
            todo,
            cfg,
            processes=processes,
            seed_ids=np.array([seed_id(asset, dates[t]) for t in todo], dtype=np.int64),
            pool=pool,
        )
        new = _rows(asset, cfg, dates, values, wins)
        keep = cached[~pd.DatetimeIndex(cached["end_date"]).isin(pd.DatetimeIndex(new["end_date"]))]
        frames = [f for f in (keep, new) if len(f)]
        _write_month(st, asset, cfg, month, pd.concat(frames, ignore_index=True))
        stats.computed += len(todo)
        stats.months_written.append(month)
        log(f"{asset} w={cfg.window} {month}: +{len(todo)} (reused {len(idx) - len(todo)})")
    return stats


def update_recent(
    st,
    prices: pd.DataFrame,
    asset: str,
    cfg: CeemdanConfig,
    since: str | pd.Timestamp,
    recheck_sessions: int = RECHECK_SESSIONS,
    processes: int | None = None,
) -> CacheStats:
    """Cập nhật hằng ngày: mọi cửa sổ kết thúc từ `since` tới phiên mới nhất; RECHECK_SESSIONS
    phiên cuối được kiểm lại hash giá (giá có thể bị sửa khi ingest tải lại 5 phiên gần nhất)."""
    dates, _ = asset_series(prices, asset)
    origins = dates[dates >= pd.Timestamp(since)]
    return ensure(
        st, prices, asset, cfg, origins, recheck=dates[-recheck_sessions:], processes=processes
    )


def load(
    st, asset: str, cfg: CeemdanConfig, start, end
) -> tuple[pd.DatetimeIndex, list[WindowIMF]]:
    """Đọc cache trong [start, end] theo thứ tự ngày (cho build.py)."""
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M").strftime("%Y-%m")
    frames = [read_month(st, asset, cfg, m) for m in months]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DatetimeIndex([]), []
    df = pd.concat(frames, ignore_index=True)
    df = df[(df["end_date"] >= pd.Timestamp(start)) & (df["end_date"] <= pd.Timestamp(end))]
    df = df.sort_values("end_date")
    return pd.DatetimeIndex(df["end_date"]), to_windows(df)
