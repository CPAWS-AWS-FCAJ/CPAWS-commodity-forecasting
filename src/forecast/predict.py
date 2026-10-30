"""Dự báo hằng ngày cho vàng, bạc, Brent, WTI → bảng `Forecasts` (docs/api/contract.md, ADR-0008).

Chạy sau Lambda ingest (kích hoạt bởi Lambda destination OnSuccess và OnFailure của Lambda ingest,
xem src/forecast/lambda_predict.py; hạ tầng do Tiến cấu hình). Với mỗi tài sản:
  1. Đọc snapshot clean mới nhất: clean/prices/dt=D/ (có quality.json, file ingest ghi cuối) và
     clean/display_factors/dt=D/ cùng ngày.
  2. build_feature_frame(prices, asset, invalid_dates=<ngày bị loại>) → latest_base_date →
     make_windows(frame, [base], window): con đường DUY NHẤT tạo input (không tự cắt, không fill).
  3. Không ghi bản ghi cho tài sản đó (bản ghi cũ giữ nguyên, không lùi ngày), log PREDICT_SKIPPED:
     - latest_session_missing: base_date sớm hơn phiên mong đợi (thiếu hoặc bị loại giá phiên cuối);
     - invalid_input_window / insufficient_input_history: cửa sổ input không hợp lệ;
     - input_publication_unavailable: batch.max_input_published_at là NaT hoặc muộn hơn as_of
       (cùng quy tắc với training, src/forecast/dlinear_data.py);
     - display_factor_missing / display_factor_stale (vàng, bạc), fx_missing.
  4. model.predict → normalize_quantiles() đúng một lần ngay sau mô hình; log
     PREDICT_QUANTILE_CROSSING với số hàng h phải sắp xếp.
  5. last_price, tỷ giá, stale_sources, roll_in_horizon → to_forecast_record → ghi. DynamoDB không
     ghi đè dự báo đã phát hành cùng (asset, base_date), chỉ thay bản mẫu (is_sample = true);
     log PREDICT_ALREADY_PUBLISHED, tài sản vẫn tính là xong.

Phiên mong đợi: chạy thường = phiên cuối của lịch tài sản đứng trước ngày dt của snapshot (ingest
chạy 12:15 UTC nên phiên của ngày dt chưa chốt); với --base-date D = phiên cuối <= D.

as_of (thời điểm dự báo được dùng dữ liệu): chạy thường = thời điểm chạy (now, UTC); với
--base-date D = D + PUBLISHED_AT_RULES[nguồn chính của tài sản] (yfinance: D+1 12:00 UTC), tức thời
điểm sớm nhất dự báo cho D được phép chạy.

Chạy:
  python -m src.forecast.predict --source local --dest local --out-dir data/forecasts \\
      --model-version dlinear-2026-10-20
  python -m src.forecast.predict --source s3 --dest dynamodb --model-version ...  # FORECASTS_TABLE
--base-date chỉ để test/backfill: cắt snapshot tại ngày đó (bỏ mọi dòng sau D) trước khi tạo frame;
khi đó stale_sources = [] vì quality.json là của snapshot hiện tại, không mô tả ngày D.

Model: artifact models/<asset>/<model_version>/ (weights.npz, config.json, scaler.json,
manifest.json) trong lake, hoặc thư mục --model-dir/<asset>/<model_version>/. Artifact có
manifest.integration_eligible khác true bị từ chối, trừ khi CLI có --allow-experimental.
--model-version baseline-q252: mốc phân vị 252 phiên (baselines.Quantile252Model, ADR-0008 mục 4),
không có artifact; cửa sổ input 252 phiên qua cùng make_windows và các bước như DLinear.

Không import torch, yfinance, PyEMD, requests (image Lambda chỉ có requirements-predict.txt): boto3
và DLinearNumpy chỉ import trong hàm.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from src.data import calendars, clean, quality, storage
from src.data.config import ASSETS, PUBLISHED_AT_RULES
from src.features.build import build_feature_frame, latest_base_date, make_windows
from src.forecast.baselines import Quantile252Model
from src.forecast.forecast_record import HORIZONS, OIL_ASSETS, target_dates, to_forecast_record
from src.forecast.returns import QUANTILE_LEVELS, normalize_quantiles

# Key trong lake: chép từ src.data.ingest_prices (module đó import requests và các nguồn tải, image
# predict không có); tests/test_predict.py kiểm tra hai nơi khớp nhau.
PRICES = "clean/prices"
FACTORS = "clean/display_factors"
MODELS = "models"  # models/<asset>/<model_version>/ (skill aws-serverless-platform)
MODEL_FILES = ("weights.npz", "config.json", "scaler.json", "manifest.json")
BASELINE_MODEL_VERSION = "baseline-q252"  # mốc 252 phiên, không có artifact

PREDICT_ASSETS: tuple[str, ...] = ("gold", "silver", "brent", "wti")
FX_ASSET = "usd_vnd"
DISPLAY_FACTOR_ASSETS = frozenset({"gold", "silver"})  # GLD/SLV → USD/oz (ADR-0005)
FACTOR_MAX_LAG_SESSIONS = 5  # factor cũ hơn 5 phiên NYSE so với base_date → không ghi

# Lý do bỏ qua (cùng với batch.reason của make_windows)
REASON_NO_PRICES = "no_prices"
REASON_LATEST_SESSION_MISSING = "latest_session_missing"
REASON_DISPLAY_FACTOR_MISSING = "display_factor_missing"
REASON_DISPLAY_FACTOR_STALE = "display_factor_stale"
REASON_FX_MISSING = "fx_missing"
REASON_INPUT_PUBLICATION = "input_publication_unavailable"  # cùng tên với dlinear_data.py
REASON_MODEL_ARTIFACT = "model_artifact"
REASON_EXCEPTION = "exception"

STATUS_OK, STATUS_SKIPPED, STATUS_ERROR = "ok", "skipped", "error"

_MODEL_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

log = logging.getLogger("cpaws.predict")


class SnapshotMissing(RuntimeError):
    """Lake chưa có snapshot clean nào có quality.json."""


class ModelArtifactError(RuntimeError):
    """Thiếu artifact, artifact sai tài sản/phiên bản, hoặc chưa đủ điều kiện tích hợp."""


class _Skip(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class ForecastModel(Protocol):
    def predict(self, windows: np.ndarray) -> np.ndarray:
        """windows [B, window, 1] log return chưa scale (cũ → mới) → [B, 7 h, 7 phân vị]."""
        ...


@dataclass(frozen=True)
class LoadedModel:
    model: ForecastModel
    window: int
    manifest: dict


# ---------- snapshot ----------


@dataclass(frozen=True)
class Snapshot:
    dt: str
    prices: pd.DataFrame
    rejected: pd.DataFrame
    quality: dict
    factors: pd.DataFrame | None  # None nếu dt này thiếu display_factors.parquet
    base_date: pd.Timestamp | None = None  # đã cắt tại ngày này (--base-date)


def load_snapshot(st) -> Snapshot:
    """Snapshot clean mới nhất có quality.json (file ingest ghi cuối cùng)."""
    dt = storage.latest_dt(st, PRICES, must_have="quality.json")
    if dt is None:
        raise SnapshotMissing(f"no {PRICES}/dt=*/quality.json in the lake")
    base = f"{PRICES}/dt={dt}"
    prices = storage.read_parquet(st, f"{base}/prices.parquet")
    rkey = f"{base}/rejected.parquet"
    rejected = storage.read_parquet(st, rkey) if st.exists(rkey) else clean.empty_frame()
    report = json.loads(st.read_bytes(f"{base}/quality.json"))
    fkey = f"{FACTORS}/dt={dt}/display_factors.parquet"
    factors = storage.read_parquet(st, fkey) if st.exists(fkey) else None
    return Snapshot(dt, prices, rejected, report, factors)


def _upto(df: pd.DataFrame | None, day: pd.Timestamp) -> pd.DataFrame | None:
    if df is None:
        return None
    return df.loc[pd.to_datetime(df["date"]) <= day].reset_index(drop=True)


def cut_snapshot(snap: Snapshot, base_date) -> Snapshot:
    """Bỏ mọi dòng sau base_date (prices, rejected, display factors) trước khi tạo frame."""
    day = pd.Timestamp(base_date).normalize()
    return dataclasses.replace(
        snap,
        prices=_upto(snap.prices, day),
        rejected=_upto(snap.rejected, day),
        factors=_upto(snap.factors, day),
        base_date=day,
    )


def expected_base_date(asset: str, snap: Snapshot) -> pd.Timestamp:
    """Phiên cuối của lịch tài sản đứng trước ngày dt của snapshot; với snapshot đã cắt tại D thì
    phiên cuối <= D. Logic nằm ở src/data/calendars.py, dùng chung với kiểm tra INGEST_STALE."""
    cal = ASSETS[asset].calendar
    if snap.base_date is not None:
        return calendars.last_session_on_or_before(cal, snap.base_date)
    return calendars.expected_latest_session(cal, snap.dt)


# ---------- các trường của bản ghi ----------


def last_price_display(snap: Snapshot, asset: str, base: pd.Timestamp) -> float:
    """Giá tại base theo đơn vị hiển thị: dầu = CL=F/BZ=F; vàng, bạc = GLD/SLV × display factor
    gần nhất <= base (WARNING nếu khác ngày base; cũ hơn FACTOR_MAX_LAG_SESSIONS phiên NYSE → bỏ)."""
    p = snap.prices
    row = p.loc[(p["asset"] == asset) & (pd.to_datetime(p["date"]) == base), "price"]
    if len(row) != 1:
        raise RuntimeError(f"expected one {asset} price at {base.date()}, got {len(row)}")
    price = float(row.iloc[0])
    if asset not in DISPLAY_FACTOR_ASSETS:
        return price
    f = snap.factors
    if f is not None:
        f = f.loc[(f["asset"] == asset) & (pd.to_datetime(f["date"]) <= base)]
    if f is None or f.empty:
        raise _Skip(REASON_DISPLAY_FACTOR_MISSING)
    last = f.sort_values("date").iloc[-1]
    fdate = pd.Timestamp(last["date"]).normalize()
    lag = len(calendars.sessions("NYSE", fdate, base)) - 1
    if lag > FACTOR_MAX_LAG_SESSIONS:
        raise _Skip(REASON_DISPLAY_FACTOR_STALE, f"factor_date={fdate.date()} lag={lag}")
    if fdate != base:
        log.warning(
            "PREDICT_DISPLAY_FACTOR_LAG asset=%s base_date=%s factor_date=%s lag=%d",
            asset,
            base.date(),
            fdate.date(),
            lag,
        )
    return price * float(last["factor"])


def fx_at(prices: pd.DataFrame, base: pd.Timestamp) -> tuple[float, pd.Timestamp]:
    """Tỷ giá USD/VND hiển thị tính trên dữ liệu <= base, cùng quy tắc với ingest
    (quality.display_fx: giữ giá trước cú vọt chưa xét xong, flag pending_confirm)."""
    fx = quality.display_fx(prices.loc[pd.to_datetime(prices["date"]) <= base])
    if fx.empty:
        raise _Skip(REASON_FX_MISSING)
    r = fx.iloc[0]
    if r["flag"]:
        log.info(
            "PREDICT_FX_FLAG base_date=%s rate_date=%s flag=%s",
            base.date(),
            r["rate_date"],
            r["flag"],
        )
    return float(r["rate"]), pd.Timestamp(r["rate_date"])


def stale_sources_for(report: dict, asset: str) -> list[str]:
    """Mã tài sản bị lỗi nguồn ở lần ingest này: chính tài sản và tỷ giá (dùng để hiển thị)."""
    stale = report.get("stale_sources") or {}
    return [x for x in (asset, FX_ASSET) if x in stale]


def roll_in_horizon(asset: str, base_date) -> bool:
    """Chỉ dầu: có phiên roll (phiên đầu tiên sau một ngày đáo hạn) trong (base_date, t7], tức ít
    nhất một return của kỳ dự báo nối hai hợp đồng. Đáo hạn đúng base_date → True; đáo hạn đúng t7
    → False (phiên roll nằm sau t7). Vàng, bạc luôn False."""
    rule = ASSETS[asset].roll_rule
    if asset not in OIL_ASSETS or rule is None:
        return False
    base = pd.Timestamp(base_date).normalize()
    t7 = pd.Timestamp(target_dates(asset, base)[-1])
    rolls = calendars.roll_days(rule, calendars.sessions(ASSETS[asset].calendar, base, t7))
    return bool(((rolls > base) & (rolls <= t7)).any())


def publication_as_of(asset: str, snap: Snapshot, now: datetime) -> pd.Timestamp:
    """Thời điểm (UTC) mà mọi giá trong cửa sổ input phải đã công bố.

    Chạy thường: now. Backfill tại D: D + PUBLISHED_AT_RULES[nguồn chính của tài sản], giống as_of
    của training (src/forecast/dlinear_data.py)."""
    if snap.base_date is None:
        return pd.Timestamp(now).tz_convert("UTC")
    days, hours = PUBLISHED_AT_RULES[ASSETS[asset].primary.source]
    return (snap.base_date + pd.Timedelta(days=days, hours=hours)).tz_localize("UTC")


# ---------- một tài sản ----------


@dataclass
class AssetResult:
    asset: str
    status: str
    reason: str = ""
    base_date: str | None = None
    n_crossed: int | None = None
    record: dict | None = None
    written_to: str | None = None
    already_published: bool = False  # khóa đã có dự báo phát hành, bản cũ giữ nguyên
    detail: str = ""


def _day(ts: pd.Timestamp | None) -> str | None:
    return None if ts is None else str(ts.date())


def predict_asset(
    snap: Snapshot,
    asset: str,
    loaded: LoadedModel,
    *,
    model_version: str,
    created_at: datetime | None = None,
) -> AssetResult:
    """Một bản ghi Forecasts cho asset, hoặc kết quả skipped kèm lý do (không ghi gì).
    created_at: thời điểm chạy (mặc định now, UTC), cũng là as_of khi chạy thường."""
    base: pd.Timestamp | None = None
    created_at = created_at or datetime.now(UTC)
    try:
        if not (snap.prices["asset"] == asset).any():
            raise _Skip(REASON_NO_PRICES)
        rej = snap.rejected
        invalid = pd.to_datetime(rej.loc[rej["asset"] == asset, "date"])
        frame = build_feature_frame(snap.prices, asset, invalid_dates=invalid)
        base = latest_base_date(frame)
        expected = expected_base_date(asset, snap)
        if base < expected:
            raise _Skip(REASON_LATEST_SESSION_MISSING, f"expected={expected.date()}")
        batch = make_windows(frame, [base], window=loaded.window)
        if not batch.valid[0]:
            raise _Skip(str(batch.reason[0]))
        # Cùng quy tắc với training: mọi giá của cửa sổ phải công bố trước as_of
        # (max_input_published_at không múi giờ nhưng mang giá trị UTC)
        as_of = publication_as_of(asset, snap, created_at)
        max_pub = batch.max_input_published_at[0]
        if np.isnat(max_pub) or max_pub > as_of.tz_localize(None).to_datetime64():
            raise _Skip(
                REASON_INPUT_PUBLICATION,
                f"max_input_published_at={max_pub} as_of={as_of.isoformat()}",
            )

        raw = np.asarray(loaded.model.predict(batch.X), dtype=float)
        if raw.shape != (1, len(HORIZONS), len(QUANTILE_LEVELS)):
            raise ValueError(f"model output shape {raw.shape}, expected (1, 7, 7)")
        q, crossed = normalize_quantiles(raw)  # đúng một lần, ngay sau mô hình (ADR-0008 mục 2)
        n_crossed = int(crossed.sum())
        log.info(
            "PREDICT_QUANTILE_CROSSING asset=%s base_date=%s n_crossed=%d n_rows=%d",
            asset,
            base.date(),
            n_crossed,
            crossed.size,
        )

        last_price = last_price_display(snap, asset, base)
        fx_rate, fx_date = fx_at(snap.prices, base)
        stale = [] if snap.base_date is not None else stale_sources_for(snap.quality, asset)
        record = to_forecast_record(
            asset,
            base,
            last_price,
            q[0],
            fx_usd_vnd=fx_rate,
            fx_date=fx_date,
            stale_sources=stale,
            roll_in_horizon=roll_in_horizon(asset, base),
            model_version=model_version,
            is_sample=False,
            created_at=created_at,
        )
        # Ngày dt= của snapshot clean đã dùng; rolling_8w loại bản ghi thiếu trường này (RFC #45 mục 7)
        record["input_snapshot_dt"] = snap.dt
        return AssetResult(
            asset, STATUS_OK, base_date=_day(base), n_crossed=n_crossed, record=record
        )
    except _Skip as s:
        log.warning(
            "PREDICT_SKIPPED asset=%s base_date=%s reason=%s %s",
            asset,
            _day(base),
            s.reason,
            s.detail,
        )
        return AssetResult(asset, STATUS_SKIPPED, s.reason, _day(base), detail=s.detail)


# ---------- model ----------


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ModelArtifactError(f"{path}: {e}") from e
    if not isinstance(obj, dict):
        raise ModelArtifactError(f"{path}: expected a JSON object")
    return obj


def load_model_dir(
    directory,
    asset: str,
    model_version: str,
    *,
    allow_experimental: bool = False,
    factory: Callable[[Path], ForecastModel] | None = None,
) -> LoadedModel:
    """Kiểm tra manifest (asset, model_version, integration_eligible) rồi nạp model.

    integration_eligible khác True (kể cả thiếu khóa) → ModelArtifactError; allow_experimental
    (chỉ CLI) cho phép nạp kèm WARNING. factory mặc định là DLinearNumpy.load (PR #18)."""
    d = Path(directory)
    missing = [f for f in MODEL_FILES if not (d / f).is_file()]
    if missing:
        raise ModelArtifactError(f"{d}: missing {missing}")
    manifest = _read_json(d / "manifest.json")
    config = _read_json(d / "config.json")
    for key, want in (("asset", asset), ("model_version", model_version)):
        if manifest.get(key) != want:
            raise ModelArtifactError(
                f"{d}: manifest {key}={manifest.get(key)!r}, expected {want!r}"
            )
    if manifest.get("integration_eligible") is not True:
        msg = (
            f"{d}: integration_eligible={manifest.get('integration_eligible')!r} "
            f"missing_metadata={manifest.get('missing_metadata')!r}"
        )
        if not allow_experimental:
            raise ModelArtifactError(f"{msg}; artifact is not eligible for production")
        log.warning("PREDICT_EXPERIMENTAL_MODEL asset=%s %s", asset, msg)
    window = config.get("window")
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ModelArtifactError(f"{d}: invalid window {window!r} in config.json")
    if factory is None:
        try:
            from src.forecast.dlinear_numpy import DLinearNumpy  # chỉ cần numpy
        except ImportError as e:
            raise ModelArtifactError(f"DLinearNumpy is not available: {e}") from e
        factory = DLinearNumpy.load
    try:
        model = factory(d)
    except (ValueError, OSError) as e:
        raise ModelArtifactError(f"{d}: {e}") from e
    return LoadedModel(model, window, manifest)


def _check_model_version(model_version: str) -> str:
    if not model_version or not _MODEL_VERSION_RE.fullmatch(model_version):
        raise ValueError(f"invalid model_version {model_version!r}")
    return model_version


def _download_model(st, asset: str, model_version: str, cache_root: Path) -> Path:
    d = cache_root / asset / model_version
    d.mkdir(parents=True, exist_ok=True)
    for f in MODEL_FILES:
        key = f"{MODELS}/{asset}/{model_version}/{f}"
        if not st.exists(key):
            raise ModelArtifactError(f"missing {key}")
        (d / f).write_bytes(st.read_bytes(key))
    return d


def make_model_loader(
    model_version: str,
    *,
    st=None,
    model_dir=None,
    cache_dir=None,
    allow_experimental: bool = False,
    factory: Callable[[Path], ForecastModel] | None = None,
) -> Callable[[str], LoadedModel]:
    """loader(asset) → LoadedModel. Nguồn: lake (st, tải models/<asset>/<version>/ về cache_dir,
    mặc định <tempdir>/cpaws-models, tức /tmp trong Lambda) hoặc model_dir/<asset>/<version>/.
    BASELINE_MODEL_VERSION: trả Quantile252Model, không đọc file, không qua manifest."""
    _check_model_version(model_version)
    if model_version == BASELINE_MODEL_VERSION:
        baseline = Quantile252Model()
        manifest = {"model_version": model_version}
        return lambda asset: LoadedModel(baseline, baseline.window, {**manifest, "asset": asset})
    if (st is None) == (model_dir is None):
        raise ValueError("pass exactly one of st or model_dir")
    cache_root = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "cpaws-models"

    def load(asset: str) -> LoadedModel:
        if model_dir is not None:
            d = Path(model_dir) / asset / model_version
        else:
            d = _download_model(st, asset, model_version, cache_root)
        return load_model_dir(
            d, asset, model_version, allow_experimental=allow_experimental, factory=factory
        )

    return load


# ---------- nơi ghi ----------


class DynamoSink:
    """Ghi bản ghi vào bảng DynamoDB `Forecasts` theo khóa asset + base_date.

    Không ghi đè dự báo đã phát hành: put_item có điều kiện chỉ ghi khi khóa chưa có hoặc bản cũ
    là bản mẫu (is_sample = true). Điều kiện không đạt → WARNING PREDICT_ALREADY_PUBLISHED, trả
    None (bản cũ giữ nguyên, tài sản vẫn tính là xong). ClientError khác raise như cũ."""

    def __init__(self, table_name: str, resource=None):
        if not table_name:
            raise ValueError("table_name is required (FORECASTS_TABLE)")
        if resource is None:
            import boto3

            resource = boto3.resource("dynamodb")
        self.table_name = table_name
        self.table = resource.Table(table_name)

    def put(self, record: dict) -> str | None:
        try:
            self.table.put_item(
                Item=record,
                ConditionExpression="attribute_not_exists(#a) OR #s = :t",
                ExpressionAttributeNames={"#a": "asset", "#s": "is_sample"},
                ExpressionAttributeValues={":t": True},
            )
        except Exception as e:
            # Nhận ClientError qua mã lỗi thay vì import botocore.exceptions: requirements-predict.txt
            # chỉ khai báo boto3 (như src/data/secret_store.py); lỗi khác raise nguyên vẹn
            response = getattr(e, "response", None)
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code != "ConditionalCheckFailedException":
                raise
            log.warning(
                "PREDICT_ALREADY_PUBLISHED asset=%s base_date=%s",
                record["asset"],
                record["base_date"],
            )
            return None
        return f"dynamodb://{self.table_name}/{record['asset']}/{record['base_date']}"


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


class LocalJsonSink:
    """Ghi <out_dir>/<asset>.json (Decimal → float), để xem thử khi chạy local."""

    def __init__(self, out_dir):
        self.out_dir = Path(out_dir)

    def put(self, record: dict) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        p = self.out_dir / f"{record['asset']}.json"
        text = json.dumps(record, indent=2, ensure_ascii=False, default=_json_default)
        p.write_text(text, encoding="utf-8")
        return str(p)


# ---------- chạy ----------


@dataclass
class PredictRun:
    snapshot_dt: str
    model_version: str
    base_date: str | None
    dry_run: bool
    results: list[AssetResult]

    @property
    def ok(self) -> bool:
        return all(r.status == STATUS_OK for r in self.results)

    def summary(self) -> dict:
        """Tóm tắt JSON được (không Decimal) cho log, Lambda và CLI."""
        assets = {}
        for r in self.results:
            a = {
                "status": r.status,
                "reason": r.reason,
                "base_date": r.base_date,
                "n_crossed": r.n_crossed,
            }
            if r.record is not None:
                a["last_price"] = float(r.record["last_price"])
                a["prob_up"] = [float(h["prob_up"]) for h in r.record["horizons"]]
            if r.written_to:
                a["written_to"] = r.written_to
            if r.already_published:
                a["already_published"] = True
            if r.detail:
                a["detail"] = r.detail
            assets[r.asset] = a
        return {
            "snapshot_dt": self.snapshot_dt,
            "model_version": self.model_version,
            "base_date_override": self.base_date,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "written": sum(1 for r in self.results if r.written_to),
            "already_published": sum(1 for r in self.results if r.already_published),
            "assets": assets,
        }


def check_assets(assets: Iterable[str]) -> list[str]:
    if assets is None or isinstance(assets, str):
        raise TypeError(f"assets must be a list of asset codes, got {assets!r}")
    out = list(assets)
    bad = [a for a in out if a not in PREDICT_ASSETS]
    if bad or not out or len(set(out)) != len(out):
        raise ValueError(f"invalid assets {out!r}; expected a subset of {list(PREDICT_ASSETS)}")
    return out


def run_predict(
    st,
    sink,
    *,
    load_model: Callable[[str], LoadedModel],
    model_version: str,
    assets: Iterable[str] = PREDICT_ASSETS,
    base_date=None,
    now: datetime | None = None,
) -> PredictRun:
    """Dự báo từng tài sản; sink=None là dry run (tính nhưng không ghi). Một tài sản lỗi hoặc bị
    bỏ qua không chặn các tài sản khác; người gọi xem PredictRun.ok."""
    assets = check_assets(assets)
    _check_model_version(model_version)
    snap = load_snapshot(st)
    created_at = now or datetime.now(UTC)
    if base_date is not None:
        snap = cut_snapshot(snap, base_date)
        log.info(
            "PREDICT_BACKFILL base_date=%s snapshot_dt=%s: stale_sources=[] "
            "(quality.json describes the snapshot, not this date)",
            snap.base_date.date(),
            snap.dt,
        )
    else:
        today = str(created_at.astimezone(UTC).date())
        if snap.dt != today:
            # Ingest hôm nay chưa ghi snapshot (lỗi hoặc chưa chạy): vẫn chạy trên snapshot cũ
            log.warning("PREDICT_SNAPSHOT_STALE snapshot_dt=%s today=%s", snap.dt, today)
    results: list[AssetResult] = []
    for asset in assets:
        try:
            loaded = load_model(asset)
            res = predict_asset(
                snap, asset, loaded, model_version=model_version, created_at=created_at
            )
            if res.status == STATUS_OK and sink is not None:
                # None: dự báo đã phát hành cho khóa này (DynamoSink), vẫn tính là xong
                res.written_to = sink.put(res.record)
                res.already_published = res.written_to is None
        except ModelArtifactError as e:
            log.error(
                "PREDICT_MODEL_MISSING asset=%s model_version=%s error=%s", asset, model_version, e
            )
            res = AssetResult(asset, STATUS_ERROR, REASON_MODEL_ARTIFACT, detail=str(e))
        except Exception as e:  # một tài sản lỗi không chặn các tài sản khác
            log.exception("PREDICT_FAILED asset=%s", asset)
            res = AssetResult(
                asset, STATUS_ERROR, REASON_EXCEPTION, detail=f"{type(e).__name__}: {e}"
            )
        results.append(res)
    base = None if snap.base_date is None else str(snap.base_date.date())
    return PredictRun(snap.dt, model_version, base, sink is None, results)


def make_storage(source: str, lake_dir: str = "data/lake"):
    """local: thư mục lake_dir; s3: bucket config.lake_bucket(), tiền tố config.lake_prefix()
    (như ingest_prices.make_storage, chép để không kéo theo requests)."""
    if source == "local":
        return storage.LocalStorage(lake_dir)
    if source == "s3":
        from src.data.config import lake_bucket, lake_prefix

        return storage.S3Storage(lake_bucket(), root=lake_prefix())
    raise ValueError(f"unknown source {source}")


def _iso_date(s: str) -> str:
    try:
        return str(pd.Timestamp(s).date())
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid date {s!r}, expected YYYY-MM-DD") from e


def main(argv: list[str] | None = None) -> int:
    """Mã thoát: 0 = mọi tài sản đã dự báo; 1 = có tài sản bị bỏ qua hoặc lỗi (các tài sản khác
    vẫn được ghi)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["local", "s3"], default="local")
    ap.add_argument("--lake-dir", default="data/lake", help="lake local khi --source local")
    ap.add_argument("--dest", choices=["local", "dynamodb"], default="local")
    ap.add_argument("--out-dir", default="data/forecasts", help="thư mục JSON khi --dest local")
    ap.add_argument(
        "--table", default=os.getenv("FORECASTS_TABLE"), help="mặc định FORECASTS_TABLE"
    )
    ap.add_argument(
        "--model-dir",
        default=None,
        help="thư mục chứa <asset>/<model_version>/; bỏ trống = tải models/ từ nguồn",
    )
    ap.add_argument("--model-version", default=os.getenv("MODEL_VERSION"))
    ap.add_argument("--assets", nargs="+", choices=PREDICT_ASSETS, default=list(PREDICT_ASSETS))
    ap.add_argument("--base-date", type=_iso_date, default=None, help="chỉ để test/backfill")
    ap.add_argument(
        "--allow-experimental",
        action="store_true",
        help="cho phép artifact có integration_eligible khác true (chỉ để thử, ghi WARNING)",
    )
    args = ap.parse_args(argv)
    if not args.model_version:
        ap.error("--model-version (or MODEL_VERSION) is required")
    if args.dest == "dynamodb" and not args.table:
        ap.error("--table (or FORECASTS_TABLE) is required with --dest dynamodb")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    st = make_storage(args.source, args.lake_dir)
    loader = make_model_loader(
        args.model_version,
        st=None if args.model_dir else st,
        model_dir=args.model_dir,
        allow_experimental=args.allow_experimental,
    )
    sink = LocalJsonSink(args.out_dir) if args.dest == "local" else DynamoSink(args.table)
    run = run_predict(
        st,
        sink,
        load_model=loader,
        model_version=args.model_version,
        assets=args.assets,
        base_date=args.base_date,
    )
    print(json.dumps(run.summary(), indent=2, ensure_ascii=False))
    return 0 if run.ok else 1


__all__ = [
    "BASELINE_MODEL_VERSION",
    "FACTOR_MAX_LAG_SESSIONS",
    "PREDICT_ASSETS",
    "AssetResult",
    "DynamoSink",
    "ForecastModel",
    "LoadedModel",
    "LocalJsonSink",
    "ModelArtifactError",
    "PredictRun",
    "Snapshot",
    "SnapshotMissing",
    "check_assets",
    "cut_snapshot",
    "expected_base_date",
    "fx_at",
    "last_price_display",
    "load_model_dir",
    "load_snapshot",
    "make_model_loader",
    "make_storage",
    "predict_asset",
    "publication_as_of",
    "roll_in_horizon",
    "run_predict",
    "stale_sources_for",
]


if __name__ == "__main__":
    raise SystemExit(main())
