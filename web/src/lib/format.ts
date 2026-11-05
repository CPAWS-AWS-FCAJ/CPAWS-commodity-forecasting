import type { AssetId, Currency } from "../api/types";

const VN = "vi-VN";

export function formatNumber(value: number, fractionDigits = 0): string {
  return new Intl.NumberFormat(VN, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Vàng làm tròn đến 1 USD; bạc và dầu 2 chữ số thập phân. VND làm tròn nghìn đồng. */
export function formatPrice(asset: AssetId, value: number, currency: Currency): string {
  if (currency === "VND") return formatNumber(Math.round(value / 1000) * 1000);
  return formatNumber(value, asset === "gold" ? 0 : 2);
}

/** Xác suất làm tròn đến 1%. Đầu vào trong [0, 1]. */
export function formatProbability(probability: number): string {
  return `${Math.round(probability * 100)}%`;
}

/**
 * Log return → phần trăm có dấu, mặc định 1 chữ số (skill forecast-display), ví dụ +0,3%.
 * Số làm tròn về 0 thì không ghi dấu ("0,0%") để khỏi có "+0,0%" / "−0,0%".
 */
export function formatReturnPercent(logReturn: number, fractionDigits = 1): string {
  const percent = logReturn * 100;
  const text = formatNumber(Math.abs(percent), fractionDigits);
  if (Number(Math.abs(percent).toFixed(fractionDigits)) === 0) return `${text}%`;
  return `${percent > 0 ? "+" : "−"}${text}%`;
}

/** "2026-10-20" → "20/10/2026" (cắt chuỗi, không qua Date để khỏi lệch múi giờ). */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

/** "2026-10-20" → "20/10" cho nhãn trục. */
export function formatDayMonth(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}`;
}

/** Ngày theo giờ Việt Nam của một thời điểm UTC: "2026-10-28T18:00:00Z" → "29/10/2026". */
export function formatDateVn(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return formatDate(iso);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("day")}/${part("month")}/${part("year")}`;
}

/** Thời điểm UTC (ISO 8601) hiển thị theo giờ Việt Nam. */
export function formatDateTimeVn(iso: string): string {
  return new Intl.DateTimeFormat(VN, {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}
