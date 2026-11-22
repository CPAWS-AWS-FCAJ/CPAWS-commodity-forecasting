"""Tool `get_forecast` cho chatbot CPAWS (Bedrock Converse tool use), đầu ra v2.

Đặc tả đầu ra: `docs/prompts/chatbot-haiku-v2.md`, mục "Đặc tả đầu ra get_forecast v2". Mỗi quy tắc
gắn với một lỗi của benchmark 23/10 (`docs/experiments/bedrock-model-test-2026-10.md` mục 10):
- Chỉ trả q10, q50, q90 dưới dạng trường có tên, đã đổi sang % (`q10_pct`...), không trả q05, q25,
  q75, q95: Haiku từng gọi q05/q95 hoặc q25/q75 là "khoảng 80%".
- `prob_up_pct` tính sẵn để model không phải tự nhân 100.
- `width_80_pct` (và `width_80_price` cho dầu) = q90 − q10 tính sẵn: dev2 ngày 26/10 Haiku tự so
  độ rộng khoảng bằng lời và sai (HAIKU-012, 029), tự tính "±" (HAIKU-013).
- Vàng, bạc không có `last_price`, `price_unit`, `qXX_price`; kèm `proxy_note` nói rõ chuỗi đại
  diện GLD/SLV. Dầu có giá USD/bbl cho q10, q50, q90.
- `disclaimer` luôn là câu cố định của contract, không lấy từ bản ghi.

Đầu vào luôn là JSON dạng `GET /forecasts/{asset}` của contract. Khi đọc bảng DynamoDB `Forecasts`,
tool dùng đúng hàm đọc và định dạng của Lambda API (`infra/lambda/forecast_api/forecast_format.py`:
`latest_record`, `detail_item`) như Khải chốt ngày 26/10, không gọi vòng qua API Gateway. Fixture
benchmark đã ở dạng đó nên đi thẳng vào bước chuyển sang v2. Tool không tự sắp xếp lại phân vị:
phân vị giảm thì báo `InvalidForecastRecord`.

Module chỉ dùng thư viện chuẩn (boto3 nạp khi cần) để chạy được trong Lambda `api` đóng gói zip,
không cần numpy/pandas. Hằng số trùng với `src/forecast/` được test kiểm tra để không lệch nhau.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol


def _load_forecast_format():
    """Module đọc/định dạng dùng chung với Lambda API. Lambda `/chat` đóng gói kèm
    `forecast_format.py` ở gốc nên import thẳng; trong repo thì nạp theo đường dẫn (thư mục tên
    `lambda` là từ khóa Python nên không import kiểu package được)."""
    try:
        import forecast_format  # type: ignore[import-not-found]

        return forecast_format
    except ImportError:
        path = (
            Path(__file__).resolve().parents[2]
            / "infra"
            / "lambda"
            / "forecast_api"
            / "forecast_format.py"
        )
        spec = importlib.util.spec_from_file_location("forecast_format", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


FF = _load_forecast_format()

TOOL_NAME = "get_forecast"
ASSETS: tuple[str, ...] = tuple(FF.ASSETS)
METALS = frozenset({"gold", "silver"})
TARGET_SERIES = {"gold": "GLD", "silver": "SLV", "brent": "BZ=F", "wti": "CL=F"}
OIL_PRICE_UNIT = "USD/bbl"
QUANTILE_LEVELS: tuple[float, ...] = tuple(FF.QUANTILE_LEVELS)
HORIZONS: tuple[int, ...] = tuple(range(1, 8))
PROB_UP_RANGE = (Decimal("0.05"), Decimal("0.95"))
# Vị trí của q10, q50, q90 trong QUANTILE_LEVELS; chỉ ba mức này được trả cho model
INTERVAL_INDEX = {"q10": 1, "q50": 3, "q90": 5}
DISCLAIMER: str = FF.DISCLAIMER
PROXY_NOTE = {
    "gold": "Dự báo vàng dựa trên quỹ GLD, là chuỗi đại diện, không phải giá vàng giao ngay.",
    "silver": "Dự báo bạc dựa trên quỹ SLV, là chuỗi đại diện, không phải giá bạc giao ngay.",
}

_CENT = Decimal("0.01")
_ONE = Decimal(1)

log = logging.getLogger("cpaws.chatbot.tools")

GET_FORECAST_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": TOOL_NAME,
        "description": (
            "Dự báo mới nhất của một tài sản (gold, silver, brent, wti) cho kỳ hạn h = 1–7 phiên "
            "giao dịch. Mỗi kỳ hạn có target_date, q10_pct, q50_pct, q90_pct (mức thay đổi theo %, "
            "khoảng dự báo 80% là từ q10 đến q90, trung vị là q50), width_80_pct (độ rộng khoảng "
            "80% theo điểm %, tính sẵn) và prob_up_pct (xác suất tăng theo %). Brent và WTI có "
            "thêm last_price, price_unit, q10_price, q50_price, q90_price và width_80_price theo "
            "USD/bbl. Vàng và bạc không có giá: dự báo dựa trên quỹ GLD/SLV (chuỗi "
            "đại diện). Kèm base_date, model_version, is_sample, stale, stale_sources, "
            "roll_in_horizon, fx (usd_vnd, date) và disclaimer."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "asset": {
                        "type": "string",
                        "enum": list(ASSETS),
                        "description": "Mã tài sản: gold, silver, brent hoặc wti.",
                    },
                    "horizon": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 7,
                        "description": "Kỳ hạn h (số phiên giao dịch). Bỏ trống để lấy cả 7 kỳ hạn.",
                    },
                },
                "required": ["asset"],
            }
        },
    }
}


class InvalidForecastRecord(ValueError):
    """Bản ghi không đúng contract (thiếu trường, phân vị giảm, prob_up ngoài khoảng...)."""


# ---------- lớp đọc dữ liệu ----------


class ForecastRepository(Protocol):
    """Nguồn bản ghi dự báo; test và benchmark thay bằng bản đọc fixture."""

    def latest(self, asset: str) -> Mapping[str, Any] | None:
        """Bản ghi mới nhất của tài sản, None nếu chưa có."""
        ...


class DynamoForecastRepository:
    """Đọc bảng DynamoDB `Forecasts` bằng đúng hàm của Lambda API: `latest_record` (Query theo
    `asset`, `ScanIndexForward=False`, `Limit=1`) rồi `detail_item` (JSON `GET /forecasts/{asset}`).

    table: đối tượng có `.query(**kwargs)` như boto3 `Table` (test truyền bảng giả)."""

    def __init__(self, table: Any):
        self._table = table

    @classmethod
    def from_table_name(
        cls, table_name: str, region: str = "ap-southeast-1"
    ) -> DynamoForecastRepository:
        import boto3  # nạp khi cần để module không phụ thuộc boto3 lúc import

        return cls(boto3.resource("dynamodb", region_name=region).Table(table_name))

    def latest(self, asset: str) -> Mapping[str, Any] | None:
        record = FF.latest_record(self._table, asset)
        if record is None:
            return None
        try:
            return FF.detail_item(record)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidForecastRecord(f"{asset}: cannot format Forecasts record: {exc}") from exc


class JsonFileForecastRepository:
    """Đọc bản ghi dạng `GET /forecasts/{asset}` từ file JSON (fixture benchmark, test).

    files: {asset: đường dẫn}. Tài sản không có file, hoặc file lỗi `{"error": "not_found"}` → None."""

    def __init__(self, files: Mapping[str, str | Path]):
        self._files = {a: Path(p) for a, p in files.items()}

    @classmethod
    def from_dir(cls, directory: str | Path) -> JsonFileForecastRepository:
        """Mỗi tài sản đọc `<directory>/<asset>.json`."""
        d = Path(directory)
        return cls({a: d / f"{a}.json" for a in ASSETS})

    def latest(self, asset: str) -> Mapping[str, Any] | None:
        path = self._files.get(asset)
        if path is None or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if "error" in data:
            if data["error"] == "not_found":
                return None
            raise InvalidForecastRecord(f"{path.name}: unexpected error payload {data['error']!r}")
        return data


# ---------- chuyển bản ghi thành kết quả tool ----------


def _error(code: str, message: str) -> dict[str, str]:
    """Lỗi theo dạng contract {"error", "message"}."""
    return {"error": code, "message": message}


def _dec(value: Any, field: str) -> Decimal:
    """Số từ DynamoDB (Decimal) hoặc JSON (int, float) → Decimal hữu hạn."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float):
        raise InvalidForecastRecord(f"{field}: expected a number, got {value!r}")
    try:
        d = value if isinstance(value, Decimal) else Decimal(repr(value))
    except InvalidOperation as exc:
        raise InvalidForecastRecord(f"{field}: invalid number {value!r}") from exc
    if not d.is_finite():
        raise InvalidForecastRecord(f"{field}: non-finite number {value!r}")
    return d


def _round(d: Decimal, step: Decimal) -> float | int:
    """Làm tròn nửa về số chẵn (như round()), bỏ -0 để model không đọc thấy "-0.0"."""
    q = d.quantize(step, rounding=ROUND_HALF_EVEN)
    if q == 0:
        return 0 if step == _ONE else 0.0
    return int(q) if step == _ONE else float(q)


def _plain_number(d: Decimal) -> float | int:
    """Decimal → int nếu là số nguyên, ngược lại float (JSON-safe)."""
    return int(d) if d == d.to_integral_value() else float(d)


def _require(record: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in record:
        raise InvalidForecastRecord(f"missing field {key!r}")
    value = record[key]
    if not isinstance(value, kind):
        raise InvalidForecastRecord(f"{key}: unexpected type {type(value).__name__}")
    return value


def _quantiles(item: Mapping[str, Any], h: int) -> list[Decimal]:
    """7 log return của một kỳ hạn: `q` (bảng DynamoDB) hoặc `returns` (GET /forecasts/{asset})."""
    raw = item.get("q", item.get("returns"))
    if not isinstance(raw, list) or len(raw) != len(QUANTILE_LEVELS):
        raise InvalidForecastRecord(f"h={h}: expected {len(QUANTILE_LEVELS)} quantiles")
    q = [_dec(v, f"h={h} quantile") for v in raw]
    if any(b < a for a, b in pairwise(q)):
        # Không sửa ở đây: predict phải gọi normalize_quantiles() trước khi ghi (ADR-0008 mục 2)
        raise InvalidForecastRecord(
            f"h={h}: quantiles are decreasing; predict must call normalize_quantiles() first"
        )
    return q


def _fx(record: Mapping[str, Any]) -> tuple[float | int, str]:
    """Tỷ giá: `fx_usd_vnd`, `fx_date` (bảng) hoặc `fx: {usd_vnd, date}` (GET /forecasts/{asset})."""
    if "fx" in record:
        fx = _require(record, "fx", Mapping)
        rate, day = fx.get("usd_vnd"), fx.get("date")
    else:
        rate, day = record.get("fx_usd_vnd"), record.get("fx_date")
    rate_d = _dec(rate, "fx_usd_vnd")
    if rate_d <= 0 or not isinstance(day, str):
        raise InvalidForecastRecord("fx_usd_vnd must be positive and fx_date a string")
    return _plain_number(rate_d), day


def _width(entry: Mapping[str, Any], unit: str) -> float | int:
    """Độ rộng khoảng 80% = q90 − q10, tính từ chính hai số đã làm tròn trả cho model, để model
    đọc thấy độ rộng khớp đúng hai đầu khoảng (dev2 26/10: HAIKU-012, 013, 029 tự so độ rộng sai)."""
    hi, lo = Decimal(repr(entry[f"q90_{unit}"])), Decimal(repr(entry[f"q10_{unit}"]))
    return _round(hi - lo, _CENT)


def build_forecast_result(
    record: Mapping[str, Any], *, asset: str | None = None, horizon: int | None = None
) -> dict[str, Any]:
    """Bản ghi `Forecasts` (hoặc JSON `GET /forecasts/{asset}`) → kết quả tool get_forecast v2.

    asset: tài sản đã yêu cầu; khác `record["asset"]` thì báo lỗi.
    horizon: 1–7 để chỉ trả một kỳ hạn; None trả cả 7. Mọi kỳ hạn đều được kiểm tra dù chỉ trả một.
    Báo InvalidForecastRecord nếu bản ghi sai contract, kể cả khi phân vị giảm (không tự sắp xếp)."""
    rec_asset = _require(record, "asset", str)
    if rec_asset not in ASSETS:
        raise InvalidForecastRecord(f"unknown asset {rec_asset!r}")
    if asset is not None and asset != rec_asset:
        raise InvalidForecastRecord(f"record is for {rec_asset!r}, requested {asset!r}")
    if horizon is not None and horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {HORIZONS}, got {horizon!r}")

    levels = _require(record, "quantile_levels", list)
    if len(levels) != len(QUANTILE_LEVELS) or any(
        abs(float(_dec(a, "quantile_levels")) - b) > 1e-9
        for a, b in zip(levels, QUANTILE_LEVELS, strict=True)
    ):
        raise InvalidForecastRecord(f"quantile_levels must be {list(QUANTILE_LEVELS)}")

    is_metal = rec_asset in METALS
    last_price: Decimal | None = None
    if not is_metal:
        last_price = _dec(record.get("last_price"), "last_price")
        if last_price <= 0:
            raise InvalidForecastRecord("last_price must be positive")
        if record.get("price_unit") != OIL_PRICE_UNIT:
            raise InvalidForecastRecord(f"price_unit must be {OIL_PRICE_UNIT} for {rec_asset}")

    items = _require(record, "horizons", list)
    by_h: dict[int, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise InvalidForecastRecord("horizons must contain objects")
        h_dec = _dec(item.get("h"), "h")
        if h_dec != h_dec.to_integral_value() or int(h_dec) in by_h:
            raise InvalidForecastRecord(f"invalid or duplicate h {item.get('h')!r}")
        by_h[int(h_dec)] = item
    if sorted(by_h) != list(HORIZONS):
        raise InvalidForecastRecord(f"horizons must be h = 1–7, got {sorted(by_h)}")

    out_horizons = []
    for h in HORIZONS:
        item = by_h[h]
        q = _quantiles(item, h)
        p_up = _dec(item.get("prob_up"), f"h={h} prob_up")
        if not PROB_UP_RANGE[0] <= p_up <= PROB_UP_RANGE[1]:
            raise InvalidForecastRecord(f"h={h}: prob_up {p_up} outside [0.05, 0.95]")
        target_date = item.get("target_date")
        if not isinstance(target_date, str):
            raise InvalidForecastRecord(f"h={h}: missing target_date")
        if horizon is not None and h != horizon:
            continue
        entry: dict[str, Any] = {"h": h, "target_date": target_date}
        for name, i in INTERVAL_INDEX.items():
            entry[f"{name}_pct"] = _round(q[i] * 100, _CENT)
        entry["width_80_pct"] = _width(entry, "pct")
        entry["prob_up_pct"] = _round(p_up * 100, _ONE)
        if last_price is not None:
            for name, i in INTERVAL_INDEX.items():
                price = float(last_price) * math.exp(float(q[i]))
                entry[f"{name}_price"] = _round(Decimal(repr(price)), _CENT)
            entry["width_80_price"] = _width(entry, "price")
        out_horizons.append(entry)

    stale_sources = _require(record, "stale_sources", list)
    if not all(isinstance(s, str) for s in stale_sources):
        raise InvalidForecastRecord("stale_sources must be a list of strings")
    fx_rate, fx_date = _fx(record)

    result: dict[str, Any] = {
        "asset": rec_asset,
        "target_series": TARGET_SERIES[rec_asset],
        "base_date": _require(record, "base_date", str),
        "model_version": _require(record, "model_version", str),
        "is_sample": _require(record, "is_sample", bool),
        "stale": bool(stale_sources),  # như GET /forecasts: true khi stale_sources không rỗng
        "stale_sources": list(stale_sources),
        "roll_in_horizon": _require(record, "roll_in_horizon", bool),
        "fx": {"usd_vnd": fx_rate, "date": fx_date},  # giữ dạng contract (Khải review PR #35)
    }
    if is_metal:
        result["proxy_note"] = PROXY_NOTE[rec_asset]
    else:
        result["last_price"] = _round(last_price, _CENT)
        result["price_unit"] = OIL_PRICE_UNIT
    result["horizons"] = out_horizons
    result["disclaimer"] = DISCLAIMER
    return result


def get_forecast(tool_input: Mapping[str, Any], repository: ForecastRepository) -> dict[str, Any]:
    """Chạy tool get_forecast với input model gửi (`toolUse.input`); trả dict JSON-safe cho
    `toolResult.content[].json`.

    Lỗi trả dạng contract: `invalid_asset`, `invalid_horizon` (không đọc dữ liệu), `not_found`,
    `internal_error` (bản ghi sai contract, ví dụ phân vị giảm; chi tiết chỉ ghi log). Lỗi của
    repository (ví dụ lỗi AWS) không bắt ở đây, để Lambda xử lý."""
    asset = tool_input.get("asset")
    if not isinstance(asset, str) or asset not in ASSETS:
        return _error("invalid_asset", f"asset phải là một trong: {', '.join(ASSETS)}.")
    horizon = tool_input.get("horizon")
    if horizon is not None and (
        isinstance(horizon, bool) or not isinstance(horizon, int) or horizon not in HORIZONS
    ):
        return _error("invalid_horizon", "horizon phải là số nguyên từ 1 đến 7.")

    try:
        record = repository.latest(asset)
        if record is None:
            return _error("not_found", f"Chưa có bản ghi dự báo cho tài sản {asset}.")
        return build_forecast_result(record, asset=asset, horizon=horizon)
    except InvalidForecastRecord:
        log.exception("get_forecast: invalid Forecasts record for %s", asset)
        return _error("internal_error", f"Bản ghi dự báo của {asset} không hợp lệ.")


__all__ = [
    "ASSETS",
    "DISCLAIMER",
    "GET_FORECAST_TOOL_SPEC",
    "TOOL_NAME",
    "DynamoForecastRepository",
    "ForecastRepository",
    "InvalidForecastRecord",
    "JsonFileForecastRepository",
    "build_forecast_result",
    "get_forecast",
]
