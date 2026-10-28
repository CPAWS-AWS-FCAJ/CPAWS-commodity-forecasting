"""Lambda predict: dự báo hằng ngày, ghi bảng DynamoDB `Forecasts` (docs/api/contract.md).

Entrypoint: src.forecast.lambda_predict.handler. Chạy sau Lambda ingest, kích hoạt bởi Lambda
destination OnSuccess VÀ OnFailure của Lambda ingest (infra/stacks/cpaws_data_stack.py, PR #32);
không đặt lịch riêng, xem config.INGEST_SCHEDULE_EXPRESSION.
- OnSuccess: ingest xong bình thường.
- OnFailure: ingest raise sau khi đã retry (ví dụ một nguồn lỗi). Snapshot của các tài sản tốt vẫn
  đã ghi, nên predict vẫn chạy cho cả 4 tài sản; tài sản thiếu phiên mới nhất bị bỏ qua
  (latest_session_missing), bản ghi cũ giữ nguyên, rồi raise PredictFailed như dưới.
Destination chỉ gọi khi ingest được gọi bất đồng bộ (Scheduler hoặc aws lambda invoke
--invocation-type Event). Gọi đồng bộ (RequestResponse) thì predict không chạy.
Biến môi trường: LAKE_BUCKET (bắt buộc trên AWS), LAKE_PREFIX (tùy chọn), FORECASTS_TABLE (bắt buộc
trừ dry_run), MODEL_VERSION (bắt buộc; artifact ở models/<asset>/<MODEL_VERSION>/ trong lake),
CPAWS_ENV, SHADOW_MODELS (tùy chọn: rỗng/không đặt = tắt; chỉ nhận "s1a-l094", cần
MODEL_VERSION=baseline-q252; sai → log ERROR PREDICT_SHADOW_CONFIG_INVALID, tắt shadow cho lần chạy,
champion vẫn chạy bình thường).

event:
  {}                         dự báo 4 tài sản từ snapshot clean mới nhất, ghi DynamoDB
  <bản ghi destination>      như {}: event từ destination (version, requestContext.condition =
                             Success / RetriesExhausted / EventAgeExceeded, requestPayload,
                             responsePayload) không có khóa "assets" hay "dry_run", nên luôn
                             chạy cả 4 tài sản và ghi thật; nội dung bản ghi không được đọc
  {"assets": ["gold", ...]}  chỉ các tài sản này ([] hoặc null → PredictConfigError)
  {"dry_run": true}          tính nhưng không ghi; trả bản tóm tắt (không raise khi có tài sản lỗi)
Tài sản bị bỏ qua (cửa sổ không hợp lệ, thiếu phiên cuối, ...) hoặc lỗi (thiếu artifact, artifact
có manifest.integration_eligible khác true, ...) không chặn các tài sản khác; sau khi ghi xong
các tài sản tốt, raise PredictFailed để Lambda tính là lỗi (metric Errors của CloudWatch), giống
Lambda ingest. Lambda không có cờ cho phép artifact thử nghiệm (chỉ CLI có --allow-experimental).
Chạy lại cho (asset, base_date) đã có dự báo phát hành (is_sample = false): không ghi đè, log
PREDICT_ALREADY_PUBLISHED, tài sản tính là xong (không raise); PREDICT_DONE đếm already_published.
Shadow S1a (docs/experiments/s1a-shadow-plan.md) ghi eval/shadow/s1a-l094/dt=<ngày chạy UTC>/ trên
lake, không ghi đè; dry_run chỉ tính. Lỗi shadow không bao giờ làm Lambda raise; PREDICT_DONE có
shadow = {model_version, written, already_published, skipped, failed}, None khi tắt, hoặc
{disabled_reason} khi SHADOW_MODELS sai.
"""

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


def handler(event: dict | None, context=None) -> dict:
    event = event or {}
    model_version = _env("MODEL_VERSION")
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
    run = predict.run_predict(
        st,
        sink,
        load_model=predict.make_model_loader(model_version, st=st),
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
