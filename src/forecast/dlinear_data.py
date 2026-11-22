"""Training-only data preparation using the shared Feature Builder and Returns."""

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data import calendars
from src.data.config import ASSETS, PUBLISHED_AT_RULES
from src.features.build import build_feature_frame, make_windows
from src.forecast.returns import horizon_log_returns

ASSET_NAMES = ("gold", "silver", "wti", "brent")


@dataclass
class TrainingData:
    X: np.ndarray
    y: np.ndarray
    base_dates: np.ndarray
    target_dates: np.ndarray
    audit: dict


@dataclass
class InputScaler:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, x):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 3 or x.shape[1:] != (60, 1) or not len(x) or not np.isfinite(x).all():
            raise ValueError("scaler needs finite nonempty training [N,60,1]")
        std = x.std(axis=(0, 1), ddof=0)
        return cls(x.mean(axis=(0, 1)), np.where(std == 0, 1.0, std))

    def transform(self, x):
        return ((np.asarray(x, dtype=np.float64) - self.mean) / self.std).astype(np.float32)


def prepare_training_data(prices, rejected, asset):
    """Fixed 2014-2018 complete cases; never read 2019+ prices for training."""
    if asset not in ASSET_NAMES:
        raise ValueError("asset must be gold/silver/wti/brent")
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.normalize()
    prices = prices.loc[(prices["asset"] == asset) & (prices["date"] <= "2018-12-31")]
    if prices.empty:
        raise ValueError("no training/warm-up prices")
    source = ASSETS[asset].primary.source
    if "source" in prices and not prices["source"].eq(source).all():
        raise ValueError("training needs the configured primary target source")
    invalid = []
    if rejected is not None and len(rejected):
        invalid = pd.to_datetime(rejected.loc[rejected["asset"] == asset, "date"]).tolist()
    cal_name = ASSETS[asset].calendar
    full = calendars.sessions(cal_name)
    origins = calendars.sessions(cal_name, "2014-01-01", "2018-12-31")
    frame = build_feature_frame(prices, asset, invalid_dates=invalid)
    batch = make_windows(frame, origins, window=60)
    series = pd.Series(prices["price"].to_numpy(float), index=pd.DatetimeIndex(prices["date"]))
    y = np.column_stack(
        [
            horizon_log_returns(series, h, calendar=cal_name, invalid_dates=invalid).reindex(
                origins
            )
            for h in range(1, 8)
        ]
    )
    positions = full.get_indexer(origins)
    targets = full.to_numpy()[positions[:, None] + np.arange(1, 8)]
    cutoff_ok = (targets <= np.datetime64("2018-12-31")).all(axis=1)
    days, hour = PUBLISHED_AT_RULES[source]
    as_of = (origins + pd.Timedelta(days=days, hours=hour)).to_numpy(dtype="datetime64[ns]")
    pub = batch.max_input_published_at
    publication_ok = ~np.isnat(pub) & (pub <= as_of)
    target_pub = targets[:, 0] + np.timedelta64(days, "D") + np.timedelta64(hour, "h")
    publication_ok &= as_of < target_pub
    finite_targets = np.isfinite(y).all(axis=1)
    reasons = np.full(len(origins), "", dtype=object)
    # Exclusive primary counts; retain independent flag counts for diagnostics.
    for mask, reason in [
        (~finite_targets, "invalid_target"),
        (~publication_ok, "input_publication_unavailable"),
        (~batch.valid, "invalid_input_window"),
        (~cutoff_ok, "outside_training_target_cutoff"),
    ]:
        reasons[mask] = reason
    for i in np.flatnonzero(~batch.valid & cutoff_ok):
        reasons[i] = str(batch.reason[i])
    keep = reasons == ""
    audit = {
        "asset": asset,
        "n_expected": len(origins),
        "n_valid": int(keep.sum()),
        "n_excluded": int((~keep).sum()),
        "excluded_by_reason": dict(Counter(reasons[~keep])),
        "input_publication_failures": int((~publication_ok & batch.valid).sum()),
        "provenance_status": "backtest_publication_rule",
        "limitation": "Latest clean snapshot; historical vintage/revisions not verified.",
    }
    return TrainingData(batch.X[keep], y[keep], batch.base_dates[keep], targets[keep], audit)
