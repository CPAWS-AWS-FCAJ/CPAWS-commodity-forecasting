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
CPAWS_ENV.

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
    dry_run = bool(event.get("dry_run"))
    try:
        # Không có khóa "assets" → cả 4 tài sản; [] hoặc null là event sai, không ngầm chạy hết
        assets = predict.check_assets(event.get("assets", predict.PREDICT_ASSETS))
    except (TypeError, ValueError) as e:
        raise PredictConfigError(str(e)) from e
    st = predict.make_storage("s3")
    sink = None if dry_run else predict.DynamoSink(_env("FORECASTS_TABLE"))
    run = predict.run_predict(
        st,
        sink,
        load_model=predict.make_model_loader(model_version, st=st),
        model_version=model_version,
        assets=assets,
    )
    summary = run.summary()
    log.info("PREDICT_DONE %s", summary)
    if not dry_run and not run.ok:
        failed = {r.asset: r.reason for r in run.results if r.status != predict.STATUS_OK}
        raise PredictFailed(f"assets not written: {failed}")
    return summary
