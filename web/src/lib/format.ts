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

/** Log return → phần trăm có dấu, ví dụ +0,30%. */
export function formatReturnPercent(logReturn: number): string {
  const percent = logReturn * 100;
  const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
  return `${sign}${formatNumber(Math.abs(percent), 2)}%`;
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
