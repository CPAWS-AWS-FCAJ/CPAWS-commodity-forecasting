import type { AssetId, ClosePoint, Currency, ForecastDetail } from "../api/types";
import { formatNumber } from "./format";
import { findHorizon, horizonView } from "./forecast";
import type { Direction } from "./priceOverview";
import { convertPrice } from "./units";

/** Một điểm trên biểu đồ "Giá thực tế và dự báo". Trường thiếu = không vẽ ở điểm đó. */
export interface FanPoint {
  date: string;
  /** Giá cuối phiên thực tế (đơn vị đang chọn). */
  price?: number;
  /** Trung vị dự báo q50; ở phiên gần nhất bằng giá cuối để đường nối liền. */
  median?: number;
  low?: number;
  high?: number;
  probUp?: number;
  /** Số phiên h (1…7) của điểm dự báo; không có ở điểm lịch sử và điểm nối. */
  h?: number;
  /** Log return q50 của h phiên (so với giá cuối gần nhất). */
  changeMid?: number;
}

/**
 * Giá cuối phiên thực tế (`price_history`, đã cắt theo mốc xem) + 7 phiên dự báo (q10–q90 đã quy đổi
 * về giá). Điểm cuối của lịch sử (base_date) cũng là điểm đầu của dải dự báo để các đường nối liền.
 * Giá lịch sử quy đổi VND bằng tỷ giá của bản ghi dự báo (cùng quy ước trang Tổng quan giá).
 */
export function buildFanData(
  asset: AssetId,
  detail: ForecastDetail,
  history: readonly ClosePoint[] | undefined,
  currency: Currency,
): FanPoint[] {
  const rate = detail.fx.usd_vnd;
  const toDisplay = (usd: number) => convertPrice(asset, usd, currency, rate);

  // Chỉ lấy phiên đến base_date: điểm sau ngày dự báo (nếu có) sẽ chồng lên phần dự báo.
  const points: FanPoint[] = (history ?? [])
    .filter((point) => point.base_date <= detail.base_date && point.last_price > 0)
    .map((point) => ({ date: point.base_date, price: toDisplay(point.last_price) }));

  // Điểm nối: ngày cuối (base_date) có cả giá thực và đầu dải dự báo.
  const lastDisplay = toDisplay(detail.last_price);
  const joint = points.find((point) => point.date === detail.base_date);
  if (joint) {
    joint.price = lastDisplay;
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

  for (const horizon of [...detail.horizons].sort((a, b) => a.h - b.h)) {
    const view = horizonView(detail, horizon);
    points.push({
      date: view.targetDate,
      median: toDisplay(view.mid),
      low: toDisplay(view.low),
      high: toDisplay(view.high),
      probUp: view.probUp,
      h: view.h,
      changeMid: view.returnMid,
    });
  }
  return points;
}

/** Vị trí điểm nối (phiên gần nhất) trong mảng của buildFanData. */
export function jointIndex(data: readonly FanPoint[]): number {
  return data.findIndex((point) => point.median !== undefined && point.price !== undefined);
}

/** Thay đổi của trung vị so với giá cuối, kèm hướng để hiện ▲/▼ và chữ "tăng"/"giảm". */
export interface MedianChange {
  direction: Direction;
  /** Độ lớn không dấu, 1 chữ số: "0,4%". */
  magnitude: string;
}

/**
 * Dùng log return q50 (cùng con số "% thay đổi" ở thẻ theo phiên) để hai nơi không lệch nhau. Làm tròn
 * 1 chữ số bằng 0 thì coi là không đổi, để mũi tên khớp con số.
 */
export function describeMedianChange(logReturn: number): MedianChange {
  const percent = Math.abs(logReturn) * 100;
  const rounded = Number(percent.toFixed(1));
  const direction: Direction = rounded === 0 ? "flat" : logReturn > 0 ? "up" : "down";
  return { direction, magnitude: `${formatNumber(percent, 1)}%` };
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
  const rest = [...detail.horizons]
    .sort((a, b) => a.h - b.h)
    .map((horizon) => ({
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
