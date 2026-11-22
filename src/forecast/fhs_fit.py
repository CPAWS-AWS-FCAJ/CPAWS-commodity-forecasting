"""K4 FHS: fit GJR-GARCH(1,1) Student-t bằng arch và lịch refit hằng tháng (k4-plan mục 3, 8).

Chỉ dùng offline (arch nằm trong requirements-dev.txt, không có trong image predict).
- fit_window(): 1000 return hợp lệ gần nhất × 100, arch_model(mean Zero, GJR o = 1, dist t,
  rescale=False). Lấy ω, α, γ, β, ν và backcast; đệ quy NumPy (fhs_numpy.variance_path) phải khớp
  conditional_volatility của arch; phần dư chuẩn hóa z tính từ chính đệ quy đó.
- monthly_fits(): refit đầu mỗi tháng, chỉ dùng return có ngày < ngày đầu tháng. Chưa đủ 1000
  return: tháng đó không có mô hình (FHS không hợp lệ, mục 8). Fit lỗi hoặc không hội tụ: dùng lại
  mô hình tháng trước (tham số, backcast, cửa sổ, z) và ghi log; lần refit đầu lỗi thì dừng.
- fhs_forecasts(): tại ngày gốc t trong tháng m, σ² đi theo đệ quy với tham số của tháng m qua
  mọi return hợp lệ từ đầu cửa sổ fit tới t, rồi mô phỏng FHS với seed theo (asset, t).

Mọi thống kê tại t chỉ dùng return có ngày ≤ t, nên không đổi khi nối thêm dữ liệu sau t (có test).
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from arch import arch_model

from configs import k4 as C
from src.forecast.fhs_numpy import LEVELS, GjrParams, fhs_quantiles, seed_for, variance_path


class FitStop(RuntimeError):
    """Điều kiện dừng của FHS: lần refit đầu lỗi, đệ quy NumPy lệch arch."""


@dataclass(frozen=True)
class WindowFit:
    """Một lần fit: tham số, backcast, cửa sổ (ngày return đầu và cuối), phần dư chuẩn hóa."""

    month: pd.Timestamp
    params: GjrParams
    backcast: float
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    z: np.ndarray
    loglikelihood: float
    parity_rel_error: float


def fit_window(window: pd.Series, month) -> tuple[WindowFit | None, dict]:
    """Fit trên một cửa sổ return hợp lệ (đã bỏ NaN). Trả (None, log) khi lỗi hoặc không hội tụ;
    đệ quy NumPy lệch arch là lỗi code nên dừng hẳn (FitStop)."""
    x = C.FHS_SCALE * window.to_numpy(dtype=float)
    log = {"n_window": len(x), "warnings": []}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = arch_model(x, **C.ARCH_SPEC, rescale=False)
            res = model.fit(disp="off")
        log["warnings"] = sorted({f"{w.category.__name__}: {w.message}" for w in caught})
        log["convergence_flag"] = int(res.convergence_flag)
        log["optimizer_message"] = str(res.optimization_result.message)
        p = res.params
        params = GjrParams(
            omega=float(p["omega"]),
            alpha=float(p["alpha[1]"]),
            gamma=float(p["gamma[1]"]),
            beta=float(p["beta[1]"]),
            nu=float(p["nu"]),
        )
        backcast = float(model.volatility.backcast(x))
    except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
        log.update(status="fit_error", error=f"{type(exc).__name__}: {exc}")
        return None, log
    log.update(
        omega=params.omega,
        alpha=params.alpha,
        gamma=params.gamma,
        beta=params.beta,
        nu=params.nu,
        persistence=params.persistence,
        loglikelihood=float(res.loglikelihood),
    )
    if res.convergence_flag != 0:
        log["status"] = "not_converged"
        return None, log
    sigma2, _ = variance_path(x, params, backcast)
    reference = np.asarray(res.conditional_volatility, dtype=float) ** 2
    parity = float(np.max(np.abs(sigma2 - reference) / reference))
    log["parity_rel_error"] = parity
    if not parity <= C.FILTER_PARITY_RTOL:
        raise FitStop(
            f"{pd.Timestamp(month):%Y-%m}: NumPy GJR recursion differs from arch {parity}"
        )
    fit = WindowFit(
        month=pd.Timestamp(month),
        params=params,
        backcast=backcast,
        window_start=pd.Timestamp(window.index[0]),
        window_end=pd.Timestamp(window.index[-1]),
        z=x / np.sqrt(sigma2),
        loglikelihood=float(res.loglikelihood),
        parity_rel_error=parity,
    )
    log["status"] = "ok"
    return fit, log


def monthly_fits(r: pd.Series, months, asset: str = "") -> tuple[dict, list[dict]]:
    """r: return ngày theo lịch (NaN ở cặp không hợp lệ). {tháng: WindowFit | None} và log."""
    fits, logs = {}, []
    previous = None
    for month in pd.DatetimeIndex(months):
        if month != month.to_period("M").to_timestamp():
            raise ValueError("months must be month starts")
        history = r[r.index < month].dropna()
        row = {"asset": asset, "month": month, "n_valid_before": len(history)}
        if len(history) < C.FHS_WINDOW:
            if previous is not None:
                raise FitStop(f"{asset} {month:%Y-%m}: fewer valid returns than an earlier refit")
            fits[month] = None
            logs.append({**row, "status": "insufficient_history", "used_month": None})
            continue
        window = history.iloc[-C.FHS_WINDOW :]
        t0 = time.perf_counter()
        fit, log = fit_window(window, month)
        row.update(log, seconds=time.perf_counter() - t0)
        row["window_start"], row["window_end"] = window.index[0], window.index[-1]
        if fit is None:
            if previous is None:
                raise FitStop(
                    f"{asset} {month:%Y-%m}: first refit {log['status']} (plan section 8)"
                )
            fit = previous  # mục 3: dùng tham số tháng trước
        previous = fit
        fits[month] = fit
        logs.append({**row, "used_month": fit.month})
    return fits, logs


def fhs_forecasts(
    r: pd.Series,
    asset: str,
    base_dates,
    fits: dict,
    demean: bool = False,
    *,
    seed_offset: int = 0,
    n_paths: int = C.FHS_PATHS,
    diag: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Phân vị FHS [n, 7, 7] chưa normalize (NaN ở ngày gốc không hợp lệ), mask hợp lệ và số giây
    phần NumPy (đệ quy + mô phỏng). demean=True là fhs-gjr-t-dm (kế hoạch mục 8). Ngày gốc chỉ
    hợp lệ khi có mô hình của tháng, σ² bước kế tiếp hữu hạn và dương, và mọi phân vị hữu hạn
    (mục 8, 29/10 tối); diag (nếu truyền) nhận số ngày bị loại theo từng lý do. seed_offset và
    n_paths chỉ dùng cho kiểm tra độ bền (mặc định đúng mô hình đã chốt)."""
    base = pd.DatetimeIndex(pd.to_datetime(base_dates))
    q = np.full((len(base), C.FHS_STEPS, len(LEVELS)), np.nan)
    ok = np.zeros(len(base), dtype=bool)
    seconds = 0.0
    counts = {"no_model": 0, "invalid_variance": 0, "nonfinite_quantiles": 0}
    months = base.to_period("M").to_timestamp()
    for month in months.unique():
        fit = fits.get(month)
        rows = np.flatnonzero(months == month)
        if fit is None:
            counts["no_model"] += len(rows)
            continue
        seq = r[(r.index >= fit.window_start) & (r.index <= base[rows].max())].dropna()
        if len(seq) < C.FHS_WINDOW or seq.index[C.FHS_WINDOW - 1] != fit.window_end:
            raise FitStop(
                f"{asset} {month:%Y-%m}: return sequence does not start at the fit window"
            )
        t0 = time.perf_counter()
        _, s2_next = variance_path(C.FHS_SCALE * seq.to_numpy(float), fit.params, fit.backcast)
        last = seq.index.searchsorted(base[rows], side="right") - 1  # return hợp lệ cuối ≤ t
        for i, pos in zip(rows, last, strict=True):
            s2 = float(s2_next[pos])
            if not np.isfinite(s2) or s2 <= 0:
                counts["invalid_variance"] += 1
                continue
            qi = fhs_quantiles(
                s2,
                fit.z,
                fit.params,
                seed=seed_for(asset, base[i].to_datetime64()) + seed_offset,
                scale=C.FHS_SCALE,
                n_paths=n_paths,
                n_steps=C.FHS_STEPS,
                demean=demean,
            )
            if not np.isfinite(qi).all():
                counts["nonfinite_quantiles"] += 1
                continue
            q[i] = qi
            ok[i] = True
        seconds += time.perf_counter() - t0
    if diag is not None:
        diag.update(counts)
    return q, ok, seconds


__all__ = ["FitStop", "WindowFit", "fhs_forecasts", "fit_window", "monthly_fits"]
