import { QUANTILE_LEVELS } from "../api/types";
import type { ForecastDetail, HorizonDetail } from "../api/types";

export const PROB_MIN = 0.05;
export const PROB_MAX = 0.95;

/**
 * Xác suất tăng bằng nội suy tuyến tính hàm phân phối giữa các phân vị, kẹp trong [0.05, 0.95].
 * Chỉ dùng cho dữ liệu mẫu và test; web hiển thị `prob_up` do API trả về.
 */
export function probUpFromQuantiles(levels: readonly number[], returns: readonly number[]): number {
  if (levels.length !== returns.length || levels.length < 2) {
    throw new Error("levels và returns phải cùng độ dài (>= 2)");
  }
  const last = returns.length - 1;
  let cdfAtZero: number;
  if (0 <= returns[0]) cdfAtZero = levels[0];
  else if (0 >= returns[last]) cdfAtZero = levels[last];
  else {
    let i = 0;
    while (returns[i + 1] < 0) i += 1;
    const span = returns[i + 1] - returns[i];
    cdfAtZero =
      span === 0
        ? levels[i]
        : levels[i] + ((0 - returns[i]) / span) * (levels[i + 1] - levels[i]);
  }
  // Làm tròn 9 chữ số để 1 − 0,95 không ra 0,050000000000000044
  const probUp = Math.round((1 - cdfAtZero) * 1e9) / 1e9;
  return Math.min(PROB_MAX, Math.max(PROB_MIN, probUp));
}

export type Lean = "up" | "down" | "flat";

export interface ProbabilityText {
  lean: Lean;
  /** Dòng chính, ví dụ "Khả năng tăng 56%". */
  headline: string;
  /** Xác suất tăng đúng như quy tắc hiển thị, ví dụ "56%" hoặc "trên 90%". */
  probUpLabel: string;
  /** Phần trăm vẽ trên thanh 0–100% (xác suất tăng). */
  barPercent: number;
}

/**
 * Quy tắc skill forecast-display: nếu 0 nằm ngoài [q10, q90] thì ghi "trên 90%" / "dưới 10%",
 * không bịa con số chính xác hơn.
 * - zeroBelowQ10: q10 > 0 (cả khoảng 80% đều dương) → xác suất tăng trên 90%.
 * - zeroAboveQ90: q90 < 0 (cả khoảng 80% đều âm) → xác suất tăng dưới 10%.
 */
export function describeProbability(
  probUp: number,
  edge: { zeroBelowQ10: boolean; zeroAboveQ90: boolean },
): ProbabilityText {
  if (edge.zeroBelowQ10) {
    return { lean: "up", headline: "Khả năng tăng trên 90%", probUpLabel: "trên 90%", barPercent: 95 };
  }
  if (edge.zeroAboveQ90) {
    return { lean: "down", headline: "Khả năng giảm trên 90%", probUpLabel: "dưới 10%", barPercent: 5 };
  }
  const percent = Math.round(probUp * 100);
  if (percent > 50) {
    return { lean: "up", headline: `Khả năng tăng ${percent}%`, probUpLabel: `${percent}%`, barPercent: percent };
  }
  if (percent < 50) {
    return {
      lean: "down",
      headline: `Khả năng giảm ${100 - percent}%`,
      probUpLabel: `${percent}%`,
      barPercent: percent,
    };
  }
  return { lean: "flat", headline: "Tăng hay giảm ngang nhau (50%)", probUpLabel: "50%", barPercent: 50 };
}

export function quantileIndex(levels: readonly number[], level: number): number {
  return levels.findIndex((value) => Math.abs(value - level) < 1e-9);
}

/** Điều kiện biên (0 ngoài [q10, q90]) tính từ log return của một mức h. */
export function edgeFromReturns(
  levels: readonly number[],
  returns: readonly number[],
): { zeroBelowQ10: boolean; zeroAboveQ90: boolean } {
  const i10 = quantileIndex(levels, 0.1);
  const i90 = quantileIndex(levels, 0.9);
  if (i10 < 0 || i90 < 0) return { zeroBelowQ10: false, zeroAboveQ90: false };
  return { zeroBelowQ10: returns[i10] > 0, zeroAboveQ90: returns[i90] < 0 };
}

export interface HorizonView {
  h: number;
  targetDate: string;
  /** Giá USD theo q10, q50, q90 (đơn vị gốc của tài sản). */
  low: number;
  mid: number;
  high: number;
  returnLow: number;
  returnMid: number;
  returnHigh: number;
  probUp: number;
  probability: ProbabilityText;
}

/** Rút q10/q50/q90 từ một mức h của GET /forecasts/{asset}. */
export function horizonView(detail: ForecastDetail, horizon: HorizonDetail): HorizonView {
  const levels = detail.quantile_levels.length ? detail.quantile_levels : QUANTILE_LEVELS;
  const i10 = quantileIndex(levels, 0.1);
  const i50 = quantileIndex(levels, 0.5);
  const i90 = quantileIndex(levels, 0.9);
  return {
    h: horizon.h,
    targetDate: horizon.target_date,
    low: horizon.prices[i10],
    mid: horizon.prices[i50],
    high: horizon.prices[i90],
    returnLow: horizon.returns[i10],
    returnMid: horizon.returns[i50],
    returnHigh: horizon.returns[i90],
    probUp: horizon.prob_up,
    probability: describeProbability(horizon.prob_up, edgeFromReturns(levels, horizon.returns)),
  };
}

export function findHorizon(detail: ForecastDetail, h: number): HorizonDetail | undefined {
  return detail.horizons.find((item) => item.h === h);
}

/** Số ngày thứ Hai–thứ Sáu từ sau `baseDate` đến hết `today` (cả hai dạng YYYY-MM-DD). */
export function weekdaysSince(baseDate: string, today: string): number {
  const start = new Date(`${baseDate}T00:00:00Z`);
  const end = new Date(`${today}T00:00:00Z`);
  let count = 0;
  for (let day = new Date(start); ; ) {
    day = new Date(day.getTime() + 86_400_000);
    if (day > end) break;
    const weekday = day.getUTCDay();
    if (weekday !== 0 && weekday !== 6) count += 1;
  }
  return count;
}

/**
 * Ingest chạy 19:15 giờ VN (thứ Ba–thứ Bảy) nên `base_date` thường chậm 1 phiên.
 * Coi là cũ khi chậm hơn 2 ngày làm việc. Dữ liệu mẫu không bao giờ bị coi là cũ.
 * Giả định này cần Khải xác nhận.
 */
export const STALE_AFTER_WEEKDAYS = 2;

export function isStaleByDate(baseDate: string, today: string, isSample: boolean): boolean {
  if (isSample) return false;
  return weekdaysSince(baseDate, today) > STALE_AFTER_WEEKDAYS;
}

/** Ngày hôm nay theo giờ Việt Nam, dạng YYYY-MM-DD. */
export function todayInVietnam(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Ho_Chi_Minh" }).format(now);
}
