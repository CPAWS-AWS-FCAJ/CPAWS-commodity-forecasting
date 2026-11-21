import type { ClosePoint } from "../api/types";
import { formatNumber } from "./format";

/**
 * Mốc xem lịch sử giá trên biểu đồ (Tổng quan giá và "Giá thực tế và dự báo"). `sessions` = số phiên
 * thay đổi, nên cần `sessions + 1` giá cuối phiên. Một tháng ≈ 21 phiên, một năm ≈ 252 phiên giao dịch.
 */
export interface HistoryRange {
  id: "7" | "21" | "126" | "252" | "504";
  label: string;
  sessions: number;
}

const RANGE_7: HistoryRange = { id: "7", label: "7 phiên", sessions: 7 };
const RANGE_1M: HistoryRange = { id: "21", label: "1 tháng", sessions: 21 };
const RANGE_6M: HistoryRange = { id: "126", label: "6 tháng", sessions: 126 };
const RANGE_1Y: HistoryRange = { id: "252", label: "1 năm", sessions: 252 };
const RANGE_2Y: HistoryRange = { id: "504", label: "2 năm", sessions: 504 };

/** Trang Tổng quan giá. */
export const OVERVIEW_RANGES: readonly HistoryRange[] = [RANGE_7, RANGE_1M, RANGE_6M, RANGE_1Y, RANGE_2Y];

/** Biểu đồ "Giá thực tế và dự báo" ở trang sản phẩm. */
export const FORECAST_CHART_RANGES: readonly HistoryRange[] = [RANGE_1M, RANGE_6M, RANGE_1Y, RANGE_2Y];

/** Số giá cuối phiên cần để vẽ đủ một mốc. */
export function pointsNeeded(range: HistoryRange): number {
  return range.sessions + 1;
}

/** Mốc dùng được khi đã có đủ giá cuối phiên; mốc vượt dữ liệu thì tắt (không ẩn). */
export function isRangeAvailable(range: HistoryRange, pointCount: number): boolean {
  return pointCount >= pointsNeeded(range);
}

/** Lý do một mốc đang tắt, hiện cạnh nút và trong title. */
export function rangeUnavailableReason(range: HistoryRange, pointCount: number): string {
  return `Mốc ${range.label} cần ${pointsNeeded(range)} giá cuối phiên, hiện mới có ${pointCount}.`;
}

/**
 * Mốc mặc định: mốc lớn nhất còn đủ dữ liệu, nhưng không quá `maxSessions`. Không mốc nào đủ dữ liệu
 * → null (biểu đồ vẽ toàn bộ số phiên đang có).
 */
export function defaultRange(
  ranges: readonly HistoryRange[],
  pointCount: number,
  maxSessions: number,
): HistoryRange | null {
  const fits = ranges.filter((range) => range.sessions <= maxSessions && isRangeAvailable(range, pointCount));
  return fits.length ? fits[fits.length - 1] : null;
}

/**
 * Các điểm của một mốc: N phiên thay đổi cần N + 1 điểm. `null` (chưa mốc nào đủ dữ liệu) trả nguyên
 * chuỗi. Chuỗi vào đã xếp cũ → mới (theo contract).
 */
export function sliceRange(points: readonly ClosePoint[], range: HistoryRange | null): ClosePoint[] {
  if (range === null) return [...points];
  return points.slice(-pointsNeeded(range));
}

export type Direction = "up" | "down" | "flat";

export interface PriceChange {
  /** Chênh lệch tuyệt đối (cùng đơn vị với giá). */
  delta: number;
  /** Thay đổi đơn giản: cuối / đầu − 1. */
  ratio: number;
  direction: Direction;
  /** Ngày của điểm được so sánh (điểm đầu). */
  fromDate: string;
}

export interface RangeStats {
  high: number;
  low: number;
  change: PriceChange | null;
}

/** % thay đổi làm tròn 1 chữ số bằng 0 thì coi là không đổi, để mũi tên khớp con số. */
function directionOf(ratio: number): Direction {
  const rounded = Number((Math.abs(ratio) * 100).toFixed(1));
  if (rounded === 0) return "flat";
  return ratio > 0 ? "up" : "down";
}

/** Thay đổi từ `from` đến `to`; null nếu giá không dương. */
export function changeBetween(from: ClosePoint, to: ClosePoint): PriceChange | null {
  if (!(from.last_price > 0) || !(to.last_price > 0)) return null;
  const ratio = to.last_price / from.last_price - 1;
  return {
    delta: to.last_price - from.last_price,
    ratio,
    direction: directionOf(ratio),
    fromDate: from.base_date,
  };
}

/** Thay đổi của phiên cuối so với phiên liền trước; null khi chưa đủ 2 điểm. */
export function lastSessionChange(points: readonly ClosePoint[]): PriceChange | null {
  if (points.length < 2) return null;
  return changeBetween(points[points.length - 2], points[points.length - 1]);
}

/** Cao nhất, thấp nhất và thay đổi đầu → cuối của một khoảng; null khi rỗng. */
export function rangeStats(points: readonly ClosePoint[]): RangeStats | null {
  if (points.length === 0) return null;
  const prices = points.map((point) => point.last_price);
  return {
    high: Math.max(...prices),
    low: Math.min(...prices),
    change: points.length >= 2 ? changeBetween(points[0], points[points.length - 1]) : null,
  };
}

/** Tỉ lệ thay đổi → "+0,8%", "−1,2%", "0,0%" (1 chữ số, dấu trừ là ký tự U+2212). */
export function formatChangePercent(ratio: number): string {
  const percent = ratio * 100;
  const text = formatNumber(Math.abs(percent), 1);
  if (Number(Math.abs(percent).toFixed(1)) === 0) return `${text}%`;
  return `${percent > 0 ? "+" : "−"}${text}%`;
}

/** Độ lớn thay đổi, không dấu, để đi cùng mũi tên và chữ "tăng"/"giảm": 0,8%. */
export function formatChangeMagnitude(ratio: number): string {
  return `${formatNumber(Math.abs(ratio) * 100, 1)}%`;
}

export const DIRECTION_ARROW: Record<Direction, string> = { up: "▲", down: "▼", flat: "◆" };
export const DIRECTION_WORD: Record<Direction, string> = {
  up: "tăng",
  down: "giảm",
  flat: "không đổi",
};
export const DIRECTION_CLASS: Record<Direction, string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-muted",
};
