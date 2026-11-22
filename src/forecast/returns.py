"""Target log return theo lịch giao dịch, chuẩn hóa phân vị, xác suất tăng, quy đổi giá và VND.

Mô hình CPAWS dự báo phân vị log return h phiên (không dự báo mức giá) để tránh "độ chính xác ảo".
Quy tắc theo ADR-0008 mục 1–3:
- t + h là phiên thứ h sau t trên lịch giao dịch của tài sản (CME cho BZ=F, CL=F; NYSE cho GLD,
  SLV), không theo vị trí dòng.
- Phân vị chuẩn hóa đúng một lần bằng normalize_quantiles() (np.sort trên từng (t, h)); các hàm
  phía sau (prob_up, prob_up_pchip, quantiles_to_prices) không tự sửa mà báo ValueError.
- prob_up nội suy tuyến tính hàm phân phối qua các phân vị, kẹp trong [0.05, 0.95].

Hàm công khai dùng chung cho DLinear (Long), Lambda predict (Tiến), seed dữ liệu mẫu (Tuấn):
giữ tên và kiểu dữ liệu ổn định.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from numbers import Real

import numpy as np
import pandas as pd

TROY_OUNCE_G = 31.1034768
LUONG_G = 37.5

# 7 mức phân vị dùng chung cho toàn dự án (ADR-0008 mục 2, docs/api/contract.md)
QUANTILE_LEVELS: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
PROB_UP_CLIP: tuple[float, float] = (0.05, 0.95)

log = logging.getLogger("cpaws.forecast")


# ---------- target ----------


def horizon_log_returns(
    prices,
    h: int,
    calendar: str | None = None,
    invalid_dates: Iterable | None = None,
    assume_aligned: bool = False,
):
    """Target r_h(t) = ln(P[t+h] / P[t]), t + h là phiên thứ h sau t theo lịch giao dịch.

    Hai cách gọi:
    - (Mặc định, bắt buộc cho code mới: DLinear, Lambda predict, build.py) prices là pd.Series có
      DatetimeIndex (giá hợp lệ của một tài sản, từ prices.parquet) và calendar = "NYSE" | "CME"
      (theo ADR-0005; xem src.data.config.ASSETS[asset].calendar). Trả về pd.Series đánh chỉ số
      theo mọi phiên của lịch từ ngày giá đầu tới ngày giá cuối. Phiên không có giá, ngày trong
      invalid_dates (dòng bị loại) và giá <= 0 coi là không hợp lệ. Không dịch theo vị trí dòng.
    - (Chỉ cho mảng ĐÃ CĂN THEO LỊCH) prices là mảng 1 chiều, mỗi phần tử một phiên liên tiếp của
      lịch, NaN cho phiên thiếu hoặc bị loại; phải khai báo assume_aligned=True. Trả về
      np.ndarray cùng độ dài. Mảng mà không có assume_aligned=True thì báo TypeError, vì dịch
      theo vị trí trên dữ liệu chưa căn lịch sẽ sai h khi thiếu dòng.

    r_h(t) là NaN khi không có giá hợp lệ tại t hoặc t + h (kể cả h phiên cuối chưa có tương lai).
    Phiên thiếu nằm giữa t và t + h không làm mất r_h(t) (log return chỉ phụ thuộc hai đầu);
    số target như vậy được ghi log và lưu ở result.attrs["n_missing_between"] (đường Series)."""
    if h < 1:
        raise ValueError("h must be >= 1")
    if isinstance(prices, pd.Series):
        if assume_aligned:
            raise TypeError("assume_aligned is only for numpy arrays; pass calendar= for a Series")
        if calendar is None:
            raise TypeError("pass calendar= ('NYSE' or 'CME'): targets follow the trading calendar")
        return _horizon_log_returns_on_calendar(prices, h, calendar, invalid_dates)
    if calendar is not None or invalid_dates is not None:
        raise TypeError("calendar/invalid_dates need a pd.Series with a DatetimeIndex")
    if not assume_aligned:
        raise TypeError(
            "horizon_log_returns on a plain array shifts by position. Pass a pd.Series with a "
            "DatetimeIndex and calendar='NYSE'|'CME' (ADR-0008), or assume_aligned=True only if "
            "the array is already on the trading calendar (one element per session, NaN gaps)."
        )
    return _aligned_log_returns(prices, h)


def _aligned_log_returns(prices, h: int) -> np.ndarray:
    """r_h trên mảng đã căn theo lịch (phần tử i ↔ phiên i)."""
    p = np.asarray(prices, dtype=float)
    valid = np.isfinite(p) & (p > 0)
    out = np.full(len(p), np.nan)
    if len(p) > h:
        ok = valid[:-h] & valid[h:]
        with np.errstate(divide="ignore", invalid="ignore"):
            out[:-h] = np.where(ok, np.log(p[h:] / p[:-h]), np.nan)
    return out


def _horizon_log_returns_on_calendar(
    prices: pd.Series, h: int, calendar: str, invalid_dates: Iterable | None
) -> pd.Series:
    from src.data import calendars

    idx = pd.DatetimeIndex(prices.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    idx = idx.normalize()
    if idx.has_duplicates:
        raise ValueError("duplicate dates in prices")
    s = pd.Series(prices.to_numpy(dtype=float), index=idx).sort_index()
    if s.empty:
        return pd.Series(dtype=float, name=f"r_{h}")
    cal = calendars.sessions(calendar, s.index.min(), s.index.max())
    off = s.index.difference(cal)
    if len(off):
        raise ValueError(
            f"{len(off)} price dates are not {calendar} sessions, e.g. {off[0].date()}"
        )
    if invalid_dates is not None:
        s = s.drop(pd.DatetimeIndex(list(invalid_dates)).normalize(), errors="ignore")
    p = s.reindex(cal).to_numpy()
    out = _aligned_log_returns(p, h)
    # đếm target hợp lệ có phiên giữa (t, t+h) không có giá hợp lệ
    invalid = (~(np.isfinite(p) & (p > 0))).astype(int)
    csum = np.concatenate([[0], np.cumsum(invalid)])
    n = len(p)
    between = np.zeros(n, dtype=int)
    if h > 1 and n > h:
        t = np.arange(n - h)
        between[: n - h] = csum[t + h] - csum[t + 1]  # phiên t+1 .. t+h-1
    n_missing_between = int(((between > 0) & np.isfinite(out)).sum())
    if n_missing_between:
        log.info(
            "horizon_log_returns h=%d calendar=%s: %d targets span missing sessions",
            h,
            calendar,
            n_missing_between,
        )
    res = pd.Series(out, index=cal, name=f"r_{h}")
    res.attrs["n_missing_between"] = n_missing_between
    return res


# ---------- chuẩn hóa và kiểm tra phân vị ----------


def normalize_quantiles(q) -> tuple[np.ndarray, np.ndarray]:
    """Sắp xếp phân vị theo thứ tự không giảm trên trục cuối (rearrangement bằng np.sort trên
    từng (t, h)). Gọi đúng một lần ngay sau khi mô hình xuất kết quả.

    q: mảng (..., n_levels), ví dụ (7,), (7 h, 7 phân vị) hoặc (T, 7, 7).
    Trả về (q_sorted, crossed): crossed là mảng bool cùng shape q[..., 0], True ở (t, h) phải sắp
    xếp lại. Tỷ lệ crossed.mean() là chỉ số "tỷ lệ phân vị cắt nhau" (ghi log trước khi sửa).
    Không dùng np.maximum.accumulate (cách đó đổi giá trị phân vị, không chỉ đổi thứ tự)."""
    a = np.asarray(q, dtype=float)
    if a.ndim == 0 or a.shape[-1] < 2:
        raise ValueError("quantiles must have at least 2 levels on the last axis")
    if not np.all(np.isfinite(a)):
        raise ValueError("quantiles contain NaN or inf")
    crossed = np.any(np.diff(a, axis=-1) < 0, axis=-1)
    if np.any(crossed):
        log.info(
            "normalize_quantiles: %d/%d rows crossed (%.4f), rearranged with np.sort",
            int(crossed.sum()),
            crossed.size,
            float(crossed.mean()),
        )
    return np.sort(a, axis=-1), crossed


def _levels_values(quantiles, levels: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    """Mapping {mức: giá trị} hoặc dãy giá trị theo `levels` → (levels, values), đã kiểm tra."""
    if isinstance(quantiles, Mapping):
        lv = np.array(sorted(quantiles), dtype=float)
        vals = np.array([quantiles[k] for k in sorted(quantiles)], dtype=float)
    else:
        lv = np.asarray(levels, dtype=float)
        vals = np.asarray(quantiles, dtype=float)
        if vals.shape != lv.shape:
            raise ValueError(f"expected {len(lv)} quantile values, got shape {vals.shape}")
    if not np.all(np.isfinite(vals)):
        raise ValueError("quantiles contain NaN or inf")
    if np.any(np.diff(vals) < 0):
        raise ValueError("quantiles are decreasing; call normalize_quantiles() first")
    return lv, vals


def _clip_prob(p: float) -> float:
    return float(min(max(p, PROB_UP_CLIP[0]), PROB_UP_CLIP[1]))


def _cdf_at_zero_edges(lv: np.ndarray, vals: np.ndarray) -> float | None:
    """P(r <= 0) ở các trường hợp biên; None nếu 0 nằm hẳn bên trong (q_min, q_max)."""
    if 0.0 < vals[0]:
        return float(lv[0])  # 0 < q05 → prob_up = 1 - 0.05
    if 0.0 > vals[-1]:
        return float(lv[-1])  # 0 > q95 → prob_up = 1 - 0.95
    hit = np.flatnonzero(vals == 0.0)
    if len(hit):
        return float(lv[hit[-1]])  # 0 trùng phân vị: dùng mức đó (lấy mức cao nhất nếu trùng nhiều)
    return None


def prob_up(quantiles, levels: Sequence[float] = QUANTILE_LEVELS) -> float:
    """Xác suất r > 0 = 1 − P(r ≤ 0); P(r ≤ 0) nội suy tuyến tính giữa hai phân vị kẹp mức 0.
    Kẹp kết quả trong [0.05, 0.95]. Biên: 0 < q_min → 1 − mức nhỏ nhất (0.95 với 7 mức);
    0 > q_max → 1 − mức lớn nhất (0.05); 0 trùng một phân vị → 1 − mức đó.

    quantiles: Mapping {mức: return} hoặc dãy return theo `levels` (mặc định QUANTILE_LEVELS).
    Phải không giảm (đã qua normalize_quantiles), nếu không báo ValueError."""
    lv, vals = _levels_values(quantiles, levels)
    edge = _cdf_at_zero_edges(lv, vals)
    if edge is not None:
        return _clip_prob(1.0 - edge)
    i = int(np.searchsorted(vals, 0.0))  # vals[i-1] < 0 < vals[i]
    x0, x1, y0, y1 = vals[i - 1], vals[i], lv[i - 1], lv[i]
    cdf = y0 + (y1 - y0) * (0.0 - x0) / (x1 - x0)
    return _clip_prob(1.0 - cdf)


def prob_up_pchip(quantiles, levels: Sequence[float] = QUANTILE_LEVELS) -> float:
    """Như prob_up nhưng nội suy hàm phân phối bằng PCHIP (đơn điệu) qua mọi phân vị. Cùng quy tắc
    biên và kẹp [0.05, 0.95]. Phân vị trùng giá trị: giữ mức cao nhất tại giá trị đó.

    CHỈ DÙNG CHO THÍ NGHIỆM (so Brier ở ADR-0008 mục 3), không gọi trong Lambda predict: hàm cần
    scipy, mà scipy chỉ được khai báo trong requirements-dev.txt (requirements.txt không khai báo
    trực tiếp; image Lambda có thể không có)."""
    from scipy.interpolate import PchipInterpolator

    lv, vals = _levels_values(quantiles, levels)
    edge = _cdf_at_zero_edges(lv, vals)
    if edge is not None:
        return _clip_prob(1.0 - edge)
    x, first = np.unique(vals[::-1], return_index=True)  # bỏ trùng, giữ mức cao nhất
    y = lv[::-1][first]
    cdf = float(PchipInterpolator(x, y, extrapolate=False)(0.0))
    return _clip_prob(1.0 - cdf)


# ---------- quy đổi giá ----------


def quantiles_to_prices(price_now: float, quantiles, levels: Sequence[float] = QUANTILE_LEVELS):
    """Phân vị log return → phân vị giá: P = P_now × exp(r). exp đơn điệu nên giữ thứ tự.

    quantiles là Mapping {mức: return} → trả dict {mức: giá}; là dãy return theo `levels` → trả
    np.ndarray. Phân vị phải không giảm (đã qua normalize_quantiles), nếu không báo ValueError.
    price_now phải là số thực hữu hạn > 0 (không nhận bool, NaN, ±Inf, 0, số âm), như điều kiện
    last_price trong forecast_record.py; nếu không báo ValueError."""
    # bool là lớp con của int nên phải loại riêng
    ok = (
        isinstance(price_now, Real)
        and not isinstance(price_now, bool | np.bool_)
        and bool(np.isfinite(price_now))
        and price_now > 0
    )
    if not ok:
        raise ValueError(f"price_now must be a finite positive real number, got {price_now!r}")
    lv, vals = _levels_values(quantiles, levels)
    prices = price_now * np.exp(vals)
    if isinstance(quantiles, Mapping):
        return {float(k): float(v) for k, v in zip(lv, prices, strict=True)}
    return prices


def usd_to_vnd(usd: float, usd_vnd: float) -> float:
    return float(usd * usd_vnd)


def usd_oz_to_vnd_luong(usd_per_oz: float, usd_vnd: float) -> float:
    """Giá thế giới quy đổi VND/lượng (chưa gồm thuế, phí, chênh lệch thị trường trong nước)."""
    return float(usd_per_oz * (LUONG_G / TROY_OUNCE_G) * usd_vnd)


__all__ = [
    "PROB_UP_CLIP",
    "QUANTILE_LEVELS",
    "horizon_log_returns",
    "normalize_quantiles",
    "prob_up",
    "prob_up_pchip",
    "quantiles_to_prices",
    "usd_oz_to_vnd_luong",
    "usd_to_vnd",
]
