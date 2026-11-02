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

/** Ngưỡng nhãn hướng (skill forecast-display), so trên xác suất tăng đã làm tròn đến 1%. */
export const LEAN_UP_PERCENT = 60;
export const LEAN_DOWN_PERCENT = 40;

export const LEAN_LABEL: Record<Lean, string> = {
  up: "Nghiêng tăng",
  down: "Nghiêng giảm",
  flat: "Chưa rõ xu hướng",
};

export interface ProbabilityText {
  lean: Lean;
  /** Nhãn hướng: "Nghiêng tăng", "Nghiêng giảm" hoặc "Chưa rõ xu hướng". */
  label: string;
  /** Xác suất tăng đúng như quy tắc hiển thị, ví dụ "56%", "≥ 95%" hoặc "≤ 5%". */
  probUpLabel: string;
  /** Xác suất tăng đã làm tròn đến 1%: số người dùng thấy, cũng là số dùng để so ngưỡng. */
  percent: number;
  /** Phần trăm vẽ trên thanh 0–100% (xác suất tăng). */
  barPercent: number;
}

/** Làm tròn xác suất đến 1%; toFixed khử sai số dấu phẩy động (0,585 × 100 = 58,4999…). */
export function roundPercent(probability: number): number {
  return Math.round(Number((probability * 100).toFixed(9)));
}

/**
 * Luôn dùng `prob_up` của API, không tự suy từ q10/q90. Nhãn hướng so trên số đã làm tròn để nhãn
 * và con số hiển thị không mâu thuẫn (0,597 → 60% → "Nghiêng tăng"). Chỉ đúng biên kẹp 0,95 / 0,05
 * mới ghi "≥ 95%" / "≤ 5%"; 0,945 vẫn là "95%".
 */
export function describeProbability(probUp: number): ProbabilityText {
  const percent = roundPercent(probUp);
  const lean: Lean =
    percent >= LEAN_UP_PERCENT ? "up" : percent <= LEAN_DOWN_PERCENT ? "down" : "flat";
  const probUpLabel =
    probUp >= PROB_MAX ? "≥ 95%" : probUp <= PROB_MIN ? "≤ 5%" : `${percent}%`;
  return { lean, label: LEAN_LABEL[lean], probUpLabel, percent, barPercent: percent };
}

export function quantileIndex(levels: readonly number[], level: number): number {
  return levels.findIndex((value) => Math.abs(value - level) < 1e-9);
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
    probability: describeProbability(horizon.prob_up),
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

/** model_version của mốc thống kê 252 phiên (Khải chốt dùng cho demo, 22/10). */
export const BASELINE_Q252 = "baseline-q252";

/** Tên dễ hiểu của mô hình; null khi không có tên riêng (giao diện hiện mã model_version). */
export function modelDisplayName(version?: string): string | null {
  return version === BASELINE_Q252 ? "Mốc thống kê 252 phiên" : null;
}
