from __future__ import annotations

import logging
import os

from . import predict

log = logging.getLogger("cpaws.predict")
log.setLevel(logging.INFO)


class PredictFailed(RuntimeError):
    """Có tài sản không được ghi dự báo mới (bỏ qua hoặc lỗi); bản ghi cũ của nó giữ nguyên."""


class PredictConfigError(RuntimeError):
    """Thiếu biến môi trường hoặc event sai."""


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PredictConfigError(f"{name} is not set")
    return value


def _model_versions() -> dict[str, str] | None:
    """MODEL_VERSIONS đã kiểm tra, hoặc None khi không đặt/rỗng (dùng MODEL_VERSION)."""
    value = os.getenv("MODEL_VERSIONS", "").strip()
    if not value:
        return None
    try:
        return predict.parse_model_versions(value)
    except (TypeError, ValueError) as e:
        raise PredictConfigError(str(e)) from e


def handler(event: dict | None, context=None) -> dict:
    event = event or {}
    model_versions = _model_versions()
    model_version = model_versions or _env("MODEL_VERSION")
    shadow_models = os.getenv("SHADOW_MODELS")  # run_predict kiểm; sai thì chỉ tắt shadow
    dry_run = bool(event.get("dry_run"))
    try:
        # Không có khóa "assets" → cả 4 tài sản; [] hoặc null là event sai, không ngầm chạy hết
        assets = predict.check_assets(event.get("assets", predict.PREDICT_ASSETS))
    except (TypeError, ValueError) as e:
        raise PredictConfigError(str(e)) from e
    st = predict.make_storage("s3")
    sink = None if dry_run else predict.DynamoSink(_env("FORECASTS_TABLE"))
    shadow_sink = None if dry_run else predict.ShadowSink(st)
    if model_versions is None:
        load_model = predict.make_model_loader(model_version, st=st)
    else:
        load_model = predict.make_asset_loader({a: model_versions[a] for a in assets}, st=st)
    run = predict.run_predict(
        st,
        sink,
        load_model=load_model,
        model_version=model_version,
        assets=assets,
        shadow_models=shadow_models,
        shadow_sink=shadow_sink,
    )
    summary = run.summary()
    log.info("PREDICT_DONE %s", summary)
    if not dry_run and not run.ok:
        failed = {r.asset: r.reason for r in run.results if r.status != predict.STATUS_OK}
        raise PredictFailed(f"assets not written: {failed}")
    return summary
