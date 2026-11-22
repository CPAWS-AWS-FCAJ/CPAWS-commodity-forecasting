"""Hàm đặc trưng dùng chung cho backtest, retrain, walk-forward, training adapter và Lambda predict.

Đúng 3 hàm công khai, cùng một cách tính cho mọi nơi gọi (không có tham số mode/is_training):
- build_feature_frame(prices, asset): bảng đặc trưng theo phiên của lịch tài sản.
- make_windows(frame, base_dates, window): cắt cửa sổ input; không nơi nào khác tự cắt cửa sổ.
- latest_base_date(frame): ngày gốc dự báo cho Lambda predict (phiên có giá cuối cùng).

Quy tắc (ADR-0008 mục 1, 8):
- MVP chỉ dùng giá của chính tài sản: log_return_1_end tại phiên u = log return một phiên KẾT THÚC
  ở u, tức r_1(phiên trước u) của returns.horizon_log_returns, đổi nhãn sang u theo lịch.
- Giá hợp lệ: có dòng trong bảng clean, không thuộc invalid_dates, giá > 0. Cột flag không được
  đọc (roll, jump, xcheck_*, stale_source... không làm mất hiệu lực). Không forward-fill, không điền 0.
- Cửa sổ tại base_date t gồm `window` phiên lịch liên tiếp [t-window+1, ..., t], cũ → mới; cần
  window + 1 giá hợp lệ liên tiếp. Không chứa return đi tới t+1.
- Không fit gì (không scaler) và không tạo target: chuẩn hóa thuộc mô hình, target do
  horizon_log_returns tạo ở walk-forward.
- Chỉ import numpy, pandas, src.data, src.forecast.returns (Lambda predict phải nhẹ: không torch,
  scipy, PyEMD).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data import calendars
from src.data.config import ASSETS
from src.forecast.returns import horizon_log_returns

# Kênh input theo thứ tự trục cuối của X. Thêm kênh: thêm tên ở đây và cột cùng tên trong
# build_feature_frame; chữ ký hàm không đổi.
FEATURE_NAMES: tuple[str, ...] = ("log_return_1_end",)
# Mặc định cho DLinear MVP (ADR-0008 mục 8). Walk-forward truyền window từ cfg; Lambda predict
# truyền window từ metadata của mô hình đã train, không dựa vào giá trị mặc định này.
DEFAULT_WINDOW = 60

# Lý do cấp frame (feature_reason)
FRAME_REASON_MISSING = "missing_price"  # không có giá hợp lệ tại u hoặc phiên trước u
FRAME_REASON_NONPOSITIVE = "nonpositive_price"  # giá <= 0 tại u hoặc phiên trước u
FRAME_REASON_HISTORY_START = "history_start"  # phiên đầu của frame, chưa có phiên trước
FRAME_REASON_MISSING_PUBLISHED = "missing_published_at"  # giá hợp lệ nhưng published_at là NaT

# Lý do cấp cửa sổ (FeatureBatch.reason); "" nghĩa là hợp lệ
REASON_INVALID_WINDOW = "invalid_input_window"
REASON_INSUFFICIENT_HISTORY = "insufficient_input_history"

FRAME_COLUMNS = [
    "asset",
    "feature_session_date",
    *FEATURE_NAMES,
    "feature_valid",
    "feature_reason",
    "feature_available_at",
]


@dataclass(frozen=True)
class FeatureBatch:
    """Các cửa sổ input của một tài sản, mỗi dòng ứng với một base_date theo thứ tự caller truyền.

    X: (n, window, len(feature_names)) float64, cũ → mới; phần tử không hợp lệ là NaN (không điền).
    valid: (n,) bool. reason: (n,) str, "" hoặc REASON_INVALID_WINDOW/REASON_INSUFFICIENT_HISTORY.
    base_dates: (n,) datetime64[ns]. input_session_dates: (n, window) datetime64[ns], các phiên lịch
    của cửa sổ (NaT nếu nằm ngoài phạm vi lịch).
    max_input_published_at: (n,) datetime64[ns] KHÔNG múi giờ nhưng mang giá trị UTC: published_at
    lớn nhất của mọi giá mà cửa sổ dùng; NaT khi valid=False (chẩn đoán dựa vào reason)."""

    asset: str
    feature_names: tuple[str, ...]
    window: int
    X: np.ndarray
    valid: np.ndarray
    reason: np.ndarray
    base_dates: np.ndarray
    input_session_dates: np.ndarray
    max_input_published_at: np.ndarray

    def __len__(self) -> int:
        return len(self.base_dates)


def _naive_dates(values) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(values))
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize().astype("datetime64[ns]")


def _calendar(asset: str) -> str:
    if asset not in ASSETS:
        raise ValueError(f"unknown asset {asset!r}")
    return ASSETS[asset].calendar


def build_feature_frame(
    prices: pd.DataFrame,
    asset: str,
    *,
    invalid_dates: Iterable | None = None,
) -> pd.DataFrame:
    """Bảng đặc trưng theo phiên của một tài sản từ bảng clean dạng dài (src.data.clean.COLUMNS).

    Mỗi phiên của lịch tài sản từ ngày giá đầu tới ngày giá cuối là một dòng (không bỏ dòng), khóa
    duy nhất (asset, feature_session_date), sắp tăng dần. Cột: asset, feature_session_date
    (datetime64[ns]), log_return_1_end (float64, NaN nếu không hợp lệ), feature_valid (bool),
    feature_reason ("" | missing_price | nonpositive_price | missing_published_at | history_start),
    feature_available_at (datetime64[ns, UTC]: published_at lớn nhất của 2 giá, NaT nếu không hợp
    lệ). Giá hợp lệ mà published_at là NaT thì feature không hợp lệ (fail-closed), nên
    feature_valid=True luôn kéo theo feature_available_at khác NaT.

    invalid_dates: ngày bị loại (ví dụ của rejected.parquet), chuyển thẳng cho horizon_log_returns.
    Bảng prices.parquet vốn không chứa dòng bị loại, nên thường để None."""
    cal_name = _calendar(asset)
    # Đọc invalid_dates đúng một lần: iterator/generator sẽ rỗng ở lần dùng thứ hai
    invalid_list = None if invalid_dates is None else list(invalid_dates)
    df = prices.loc[prices["asset"] == asset]
    if df.empty:
        raise ValueError(f"no price rows for asset {asset!r}")
    dates = _naive_dates(df["date"])
    price = pd.Series(df["price"].to_numpy(dtype=float), index=dates)
    published = pd.Series(pd.to_datetime(df["published_at"], utc=True).to_numpy(), index=dates)

    # Return một phiên theo lịch (nhãn = phiên bắt đầu); hàm này báo lỗi nếu trùng ngày hoặc có
    # ngày không phải phiên giao dịch. Index = mọi phiên từ ngày giá đầu tới ngày giá cuối.
    r1 = horizon_log_returns(price, 1, calendar=cal_name, invalid_dates=invalid_list)
    cal = pd.DatetimeIndex(r1.index)

    # Đổi nhãn phiên bắt đầu cal[i] → phiên kết thúc cal[i+1] (theo lịch, không theo dòng dữ liệu)
    ret_end = pd.Series(r1.to_numpy()[:-1], index=cal[1:]).reindex(cal)

    # Giá hợp lệ theo phiên, chỉ để ghi lý do và published_at (không tính lại return)
    if invalid_list is not None:
        drop = _naive_dates(invalid_list)
        price = price.drop(drop, errors="ignore")
        published = published.drop(drop, errors="ignore")
    p = price.reindex(cal).to_numpy()
    present = np.isfinite(p)
    positive = present & (p > 0)
    pub = pd.DatetimeIndex(published.reindex(cal)).tz_convert("UTC")

    n = len(cal)
    reason = np.full(n, "", dtype=object)
    prev_present = np.concatenate([[False], present[:-1]])
    prev_positive = np.concatenate([[False], positive[:-1]])
    nonpos = (present & ~positive) | (prev_present & ~prev_positive)
    reason[nonpos] = FRAME_REASON_NONPOSITIVE
    reason[~present | ~prev_present] = FRAME_REASON_MISSING  # thiếu giá ưu tiên hơn giá <= 0
    reason[0] = FRAME_REASON_HISTORY_START
    values = ret_end.to_numpy(dtype=float)
    if not np.array_equal(reason == "", np.isfinite(values)):
        raise RuntimeError("feature validity disagrees with horizon_log_returns")

    # Fail-closed: giá hợp lệ nhưng không biết thời điểm công bố thì không dùng được (không
    # chứng minh được dữ liệu đã có tại thời điểm dự báo)
    pub_ns = pub.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    prev_ns = np.concatenate([np.array(["NaT"], dtype="datetime64[ns]"), pub_ns[:-1]])
    no_pub = np.isnat(pub_ns) | np.isnat(prev_ns)
    reason[(reason == "") & no_pub] = FRAME_REASON_MISSING_PUBLISHED
    valid = reason == ""
    values = np.where(valid, values, np.nan)

    # published_at lớn nhất của 2 giá (phiên trước u và u); NaT khi đặc trưng không hợp lệ
    avail_ns = np.where(valid, np.maximum(pub_ns, prev_ns), np.datetime64("NaT"))
    available_at = pd.DatetimeIndex(avail_ns.astype("datetime64[ns]")).tz_localize("UTC")

    out = pd.DataFrame(
        {
            "asset": asset,
            "feature_session_date": cal.astype("datetime64[ns]"),
            "log_return_1_end": values,
            "feature_valid": valid,
            "feature_reason": reason.astype(str),
            "feature_available_at": available_at,
        }
    )
    return out[FRAME_COLUMNS]


def _check_frame(frame: pd.DataFrame) -> tuple[str, pd.DatetimeIndex]:
    missing = [c for c in FRAME_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"frame is missing columns {missing}; use build_feature_frame()")
    assets = frame["asset"].unique()
    if len(assets) != 1:
        raise ValueError("frame must contain exactly one asset")
    asset = str(assets[0])
    dates = _naive_dates(frame["feature_session_date"])
    # Cửa sổ cắt theo vị trí lịch, nên frame phải đủ mọi phiên (không lọc dòng trước khi cắt)
    expected = calendars.sessions(_calendar(asset), dates.min(), dates.max())
    if not dates.equals(pd.DatetimeIndex(expected)):
        raise ValueError(
            "frame must cover every calendar session in order; do not filter rows "
            "(pass the output of build_feature_frame() unchanged)"
        )
    return asset, dates


def make_windows(frame: pd.DataFrame, base_dates, window: int = DEFAULT_WINDOW) -> FeatureBatch:
    """Cửa sổ input tại từng base_date t: `window` phiên lịch [t-window+1, ..., t], cũ → mới.

    - insufficient_input_history: phiên t-window (giá đầu của cửa sổ) nằm trước phiên đầu frame.
    - invalid_input_window: đủ lịch sử nhưng có phần tử không hợp lệ (thiếu giá, giá <= 0, thiếu
      published_at, hoặc t nằm sau ngày giá cuối của frame).
    Dòng không hợp lệ vẫn giữ (X là NaN ở phần tử thiếu, không tự điền). base_date không phải phiên
    của lịch tài sản hoặc bị trùng → ValueError (lỗi của caller)."""
    if int(window) != window or window < 1:
        raise ValueError("window must be a positive integer")
    window = int(window)
    asset, dates = _check_frame(frame)
    full = calendars.sessions(_calendar(asset))
    bd = _naive_dates(list(base_dates) if not isinstance(base_dates, pd.Index) else base_dates)
    if bd.has_duplicates:
        raise ValueError("duplicate base_dates")
    pos_t = full.get_indexer(bd)
    if np.any(pos_t < 0):
        bad = bd[pos_t < 0][0]
        raise ValueError(f"base_date {bad.date()} is not a {_calendar(asset)} session")

    n, k = len(bd), len(FEATURE_NAMES)
    start = int(full.get_loc(dates[0]))
    offsets = np.arange(-window + 1, 1)
    idx = pos_t[:, None] + offsets[None, :]  # vị trí lịch của từng phần tử, (n, window)
    in_cal = (idx >= 0) & (idx < len(full))
    sess = np.full(idx.shape, np.datetime64("NaT"), dtype="datetime64[ns]")
    sess[in_cal] = full.to_numpy()[idx[in_cal]]

    j = idx - start  # vị trí dòng trong frame (frame đủ mọi phiên nên vị trí lịch ↔ dòng)
    in_frame = (j >= 0) & (j < len(frame))
    jc = np.clip(j, 0, max(len(frame) - 1, 0))
    feats = frame[list(FEATURE_NAMES)].to_numpy(dtype=float)
    X = np.full((n, window, k), np.nan)
    X[in_frame] = feats[jc[in_frame]]
    # published_at: chuyển về UTC rồi bỏ múi giờ để lưu dạng datetime64[ns]
    avail = pd.DatetimeIndex(frame["feature_available_at"]).tz_convert("UTC").tz_localize(None)
    avail_ns = avail.to_numpy(dtype="datetime64[ns]")[jc]
    # Fail-closed cả khi frame bị sửa tay: phần tử không có thời điểm công bố là không hợp lệ,
    # nên valid=True luôn kéo theo max_input_published_at khác NaT
    elem_valid = in_frame & frame["feature_valid"].to_numpy(dtype=bool)[jc] & ~np.isnat(avail_ns)

    has_history = (pos_t - window) >= start
    valid = has_history & elem_valid.all(axis=1)
    reason = np.where(
        valid, "", np.where(has_history, REASON_INVALID_WINDOW, REASON_INSUFFICIENT_HISTORY)
    ).astype(object)

    max_pub = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    if valid.any():
        max_pub[valid] = avail_ns[valid].max(axis=1)

    return FeatureBatch(
        asset=asset,
        feature_names=FEATURE_NAMES,
        window=window,
        X=X,
        valid=valid,
        reason=reason.astype(str),
        base_dates=bd.to_numpy(dtype="datetime64[ns]"),
        input_session_dates=sess,
        max_input_published_at=max_pub,
    )


def latest_base_date(frame: pd.DataFrame) -> pd.Timestamp:
    """Ngày gốc dự báo cho Lambda predict: phiên cuối của frame (ngày có giá cuối cùng), KHÔNG lùi
    về phiên hợp lệ gần nhất. Lambda gọi make_windows(frame, [latest_base_date(frame)], window);
    nếu batch.valid[0] là False thì không ghi dự báo mới (docs/api/contract.md)."""
    _, dates = _check_frame(frame)
    return pd.Timestamp(dates[-1])


__all__ = [
    "DEFAULT_WINDOW",
    "FEATURE_NAMES",
    "FRAME_REASON_HISTORY_START",
    "FRAME_REASON_MISSING",
    "FRAME_REASON_MISSING_PUBLISHED",
    "FRAME_REASON_NONPOSITIVE",
    "REASON_INSUFFICIENT_HISTORY",
    "REASON_INVALID_WINDOW",
    "FeatureBatch",
    "build_feature_frame",
    "latest_base_date",
    "make_windows",
]
