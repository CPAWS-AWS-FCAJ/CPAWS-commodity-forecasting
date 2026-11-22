import type { AssetId, Currency } from "../api/types";

/** 1 ounce troy = 31,1034768 g; 1 lượng = 37,5 g. */
export const TROY_OUNCE_GRAMS = 31.1034768;
export const LUONG_GRAMS = 37.5;

export function isMetal(asset: AssetId): boolean {
  return asset === "gold" || asset === "silver";
}

/** Đơn vị hiển thị theo tiền tệ đã chọn. */
export function displayUnit(asset: AssetId, currency: Currency): string {
  if (currency === "USD") return isMetal(asset) ? "USD/oz" : "USD/thùng";
  return isMetal(asset) ? "VND/lượng" : "VND/thùng";
}

/**
 * USD/oz → VND/lượng: USD × 37,5 / 31,1034768 × USD/VND (vàng, bạc).
 * Dầu: USD/thùng → VND/thùng = USD × USD/VND.
 * Giá vàng quy đổi KHÔNG phải giá vàng miếng trong nước (chưa gồm thuế, phí, chênh lệch).
 */
export function usdToVnd(asset: AssetId, usd: number, usdVnd: number): number {
  const perUnit = isMetal(asset) ? (usd * LUONG_GRAMS) / TROY_OUNCE_GRAMS : usd;
  return perUnit * usdVnd;
}

export function convertPrice(
  asset: AssetId,
  usd: number,
  currency: Currency,
  usdVnd: number,
): number {
  return currency === "VND" ? usdToVnd(asset, usd, usdVnd) : usd;
}
