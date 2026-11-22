import { Link } from "react-router-dom";
import type { ForecastSummary } from "../api/types";
import { ASSET_DOT_CLASS, ASSET_HOVER_BORDER_CLASS, ASSETS } from "../lib/assets";
import { formatDate, formatNumber, formatPrice, formatReturnPercent } from "../lib/format";
import { BASELINE_Q252 } from "../lib/forecast";
import { ProbabilityBadge } from "./ProbabilityBadge";
import { ChevronRightIcon } from "./shell/icons";
import { BaselineBadge, RollBadge, SampleBadge, StaleBadge } from "./StatusBadges";

interface Props {
  item: ForecastSummary;
  /** Ẩn giá (vàng/bạc khi VITE_SHOW_METAL_PRICES=false): chỉ hiện % thay đổi và xác suất tăng. */
  hidePrice?: boolean;
  /**
   * Nửa độ rộng thang của thanh khoảng (log return, ví dụ 0,04 = ±4%). Trang chủ truyền cùng một
   * thang cho cả 4 thẻ để so độ rộng khoảng; không truyền thì thẻ tự tính theo chính nó.
   */
  scale?: number;
}

/** Log return của q10/q50/q90 sau 7 phiên so với giá cuối (từ giá API trả, không tự dự báo lại). */
export function h7Returns(item: ForecastSummary) {
  return {
    low: Math.log(item.h7.p10 / item.last_price),
    mid: Math.log(item.h7.p50 / item.last_price),
    high: Math.log(item.h7.p90 / item.last_price),
  };
}

/**
 * Thang chung cho thanh khoảng: lớn nhất của |q10|, |q90| trong các thẻ, cộng 15% lề, làm tròn lên
 * 1% (dưới 2% thì làm tròn 0,5%) để nhãn hai đầu gọn.
 */
export function rangeScale(items: readonly ForecastSummary[]): number {
  let widest = 0;
  for (const item of items) {
    const { low, high } = h7Returns(item);
    if (Number.isFinite(low)) widest = Math.max(widest, Math.abs(low));
    if (Number.isFinite(high)) widest = Math.max(widest, Math.abs(high));
  }
  const percent = Math.max(widest * 100 * 1.15, 0.5);
  const step = percent < 2 ? 0.5 : 1;
  return (Math.ceil(percent / step) * step) / 100;
}

function axisLabel(value: number): string {
  const percent = Math.abs(value * 100);
  const text = formatNumber(percent, Number.isInteger(Math.round(percent * 10) / 10) ? 0 : 1);
  return `${value < 0 ? "−" : "+"}${text}%`;
}

/**
 * Thanh khoảng 80% sau 7 phiên: vạch giữa là giá cuối, dải màu là q10–q90, vạch xanh là trung vị.
 * Thông tin chính đã có ở dòng chữ phía trên; thanh chỉ giúp so độ rộng giữa các sản phẩm.
 */
function RangeStrip({ low, mid, high, scale }: { low: number; mid: number; high: number; scale: number }) {
  const pos = (r: number) => Math.min(100, Math.max(0, 50 + (r / scale) * 50));
  const left = pos(low);
  const right = pos(high);
  return (
    <div
      role="img"
      aria-label={`Khoảng 80% sau 7 phiên từ ${formatReturnPercent(low)} đến ${formatReturnPercent(high)} so với giá cuối, trung vị ${formatReturnPercent(mid)}`}
      className="mt-3"
    >
      <div className="relative h-5">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line" />
        <div
          className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-band"
          style={{ left: `${left}%`, width: `${Math.max(right - left, 0.5)}%` }}
        />
        <div
          className="absolute top-1/2 h-3.5 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-forecast"
          style={{ left: `${pos(mid)}%` }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-price" />
      </div>
      <div aria-hidden="true" className="tabular mt-1 grid grid-cols-3 text-xs text-muted">
        <span>{axisLabel(-scale)}</span>
        <span className="text-center">Giá cuối</span>
        <span className="text-right">{axisLabel(scale)}</span>
      </div>
    </div>
  );
}

/**
 * Thẻ sản phẩm ở trang chủ: giá cuối, nhãn hướng + xác suất tăng h = 7, khoảng giá 80% và thanh
 * khoảng. Màu nhận diện của sản phẩm chỉ ở chấm cạnh tên và viền khi rê chuột.
 */
export function AssetCard({ item, hidePrice = false, scale }: Props) {
  const meta = ASSETS[item.asset];
  const unit = item.price_unit;
  const returns = h7Returns(item);
  const stripScale = scale ?? rangeScale([item]);

  return (
    <Link
      to={`/asset/${item.asset}`}
      className={`group flex h-full flex-col rounded-lg border border-line bg-surface p-5 transition-colors duration-150 sm:p-6 ${ASSET_HOVER_BORDER_CLASS[item.asset]}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${ASSET_DOT_CLASS[item.asset]}`} />
          {meta.name}
          <span className="text-xs font-normal text-muted">{meta.series}</span>
        </h2>
        <div className="flex flex-wrap gap-1">
          {item.is_sample ? <SampleBadge /> : null}
          {item.model_version === BASELINE_Q252 ? <BaselineBadge /> : null}
          {item.stale ? <StaleBadge /> : null}
          {item.roll_in_horizon ? <RollBadge /> : null}
        </div>
      </div>

      <div className="mt-4 grid gap-5 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div>
          {hidePrice ? (
            <p className="text-sm text-muted">
              Dữ liệu đến ngày {formatDate(item.base_date)}, hiển thị theo % thay đổi
            </p>
          ) : (
            <>
              <p className="tabular text-3xl font-semibold tracking-tight">
                {formatPrice(item.asset, item.last_price, "USD")}{" "}
                <span className="text-sm font-normal tracking-normal text-muted">{unit}</span>
              </p>
              <p className="mt-1 text-xs text-muted">Giá cuối ngày {formatDate(item.base_date)}</p>
            </>
          )}
        </div>
        <ProbabilityBadge probUp={item.h7.prob_up} horizonDays={7} />
      </div>

      <div className="mt-5 border-t border-line pt-4">
        {hidePrice ? (
          <p className="tabular text-sm">
            Thay đổi 80% sau 7 phiên:{" "}
            <span className="font-medium">
              {formatReturnPercent(returns.low)} đến {formatReturnPercent(returns.high)}
            </span>
          </p>
        ) : (
          <p className="tabular text-sm">
            Khoảng giá 80% sau 7 phiên:{" "}
            <span className="whitespace-nowrap font-medium">
              {formatPrice(item.asset, item.h7.p10, "USD")}–{formatPrice(item.asset, item.h7.p90, "USD")} {unit}
            </span>
          </p>
        )}
        <RangeStrip low={returns.low} mid={returns.mid} high={returns.high} scale={stripScale} />
      </div>

      <p className="mt-auto inline-flex items-center gap-1 pt-4 text-sm font-medium text-forecast">
        Xem chi tiết
        <ChevronRightIcon className="transition-transform duration-150 group-hover:translate-x-0.5 motion-reduce:transition-none" />
      </p>
    </Link>
  );
}
