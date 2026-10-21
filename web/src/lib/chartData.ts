import type { AssetId, Currency, ForecastDetail, PricePoint } from "../api/types";
import { findHorizon, horizonView } from "./forecast";
import { convertPrice } from "./units";

/** Một điểm trên biểu đồ quạt giá. Trường thiếu = không vẽ ở điểm đó. */
export interface FanPoint {
  date: string;
  price?: number;
  median?: number;
  low?: number;
  high?: number;
  probUp?: number;
}

export const HISTORY_SESSIONS_SHOWN = 90;

/**
 * 90 phiên giá thực tế + 7 ngày dự báo (q10–q90 đã quy đổi về giá).
 * Điểm cuối của lịch sử cũng là điểm đầu của dải dự báo để các đường nối liền.
 */
export function buildFanData(
  asset: AssetId,
  detail: ForecastDetail,
  history: PricePoint[] | undefined,
  currency: Currency,
): FanPoint[] {
  const rate = detail.fx.usd_vnd;
  const toDisplay = (usd: number) => convertPrice(asset, usd, currency, rate);

  const recent = (history ?? []).slice(-(HISTORY_SESSIONS_SHOWN + 1));
  const points: FanPoint[] = recent.map((point) => ({
    date: point.date,
    price: toDisplay(point.price),
  }));

  // Điểm nối: ngày cuối (base_date) có cả giá thực và đầu dải dự báo.
  const lastDisplay = toDisplay(detail.last_price);
  const joint = points.find((point) => point.date === detail.base_date);
  if (joint) {
    joint.median = lastDisplay;
    joint.low = lastDisplay;
    joint.high = lastDisplay;
  } else {
    points.push({
      date: detail.base_date,
      price: lastDisplay,
      median: lastDisplay,
      low: lastDisplay,
      high: lastDisplay,
    });
  }

  for (const horizon of detail.horizons) {
    const view = horizonView(detail, horizon);
    points.push({
      date: view.targetDate,
      median: toDisplay(view.mid),
      low: toDisplay(view.low),
      high: toDisplay(view.high),
      probUp: view.probUp,
    });
  }
  return points;
}

/** Điểm trên biểu đồ quạt theo return (%), dùng ở chế độ nâng cao. */
export interface ReturnFanPoint {
  h: number;
  date: string;
  median: number;
  q10: number;
  q90: number;
  q05: number;
  q95: number;
}

export function buildReturnFanData(detail: ForecastDetail): ReturnFanPoint[] {
  const levels = detail.quantile_levels;
  const idx = (level: number) => levels.findIndex((value) => Math.abs(value - level) < 1e-9);
  const [i05, i10, i50, i90, i95] = [0.05, 0.1, 0.5, 0.9, 0.95].map(idx);
  const percent = (value: number) => value * 100;

  const start: ReturnFanPoint = {
    h: 0,
    date: detail.base_date,
    median: 0,
    q10: 0,
    q90: 0,
    q05: 0,
    q95: 0,
  };
  const rest = detail.horizons.map((horizon) => ({
    h: horizon.h,
    date: horizon.target_date,
    median: percent(horizon.returns[i50]),
    q10: percent(horizon.returns[i10]),
    q90: percent(horizon.returns[i90]),
    q05: percent(horizon.returns[i05]),
    q95: percent(horizon.returns[i95]),
  }));
  return [start, ...rest];
}

export { findHorizon };
