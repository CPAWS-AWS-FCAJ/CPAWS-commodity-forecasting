// Kiểu dữ liệu khớp docs/api/contract.md (nguồn chuẩn). Đổi trường → sửa contract qua PR trước.
// Giữ nguyên snake_case của API, không đổi sang camelCase.

export const ASSET_IDS = ["gold", "silver", "brent", "wti"] as const;
export type AssetId = (typeof ASSET_IDS)[number];

export type PriceUnit = "USD/oz" | "USD/bbl";
export type Currency = "USD" | "VND";

/** Mức phân vị lưu và trả về, luôn theo thứ tự này. */
export const QUANTILE_LEVELS = [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95] as const;

/** Một mức h trong GET /forecasts: p10/p50/p90 là GIÁ đã quy đổi (không phải return). */
export interface HorizonSummary {
  target_date: string;
  p10: number;
  p50: number;
  p90: number;
  prob_up: number;
}

/** GET /forecasts → items[] */
export interface ForecastSummary {
  asset: AssetId;
  target_series: string;
  base_date: string;
  last_price: number;
  price_unit: PriceUnit;
  h1: HorizonSummary;
  h7: HorizonSummary;
  stale: boolean;
  roll_in_horizon: boolean;
  is_sample: boolean;
  /** API trả trường này ở danh sách (handler `_summary_item`); dữ liệu mẫu cục bộ không có. */
  model_version?: string;
}

export interface ForecastListResponse {
  items: ForecastSummary[];
  disclaimer: string;
}

/** Một mức h trong GET /forecasts/{asset}: returns và prices có 7 phần tử theo quantile_levels. */
export interface HorizonDetail {
  h: number;
  target_date: string;
  returns: number[];
  prices: number[];
  prob_up: number;
}

export interface ForecastDetail {
  asset: AssetId;
  target_series: string;
  base_date: string;
  /** Contract có hai trường này ở chi tiết, nhưng API (PR #22) tạm chưa trả: coi là tùy chọn. */
  created_at?: string;
  model_version?: string;
  last_price: number;
  price_unit: PriceUnit;
  quantile_levels: number[];
  horizons: HorizonDetail[];
  fx: { usd_vnd: number; date: string };
  stale_sources: string[];
  roll_in_horizon: boolean;
  is_sample: boolean;
  disclaimer: string;
}

/**
 * LỊCH SỬ GIÁ: contract CHƯA có endpoint này (câu hỏi mở cho Khải/Tuấn).
 * Tạm giả định GET /history/{asset}?days=90 trả về dạng dưới đây; khi chốt thì sửa contract trước.
 */
export interface PricePoint {
  date: string;
  price: number;
}

export interface HistoryResponse {
  asset: AssetId;
  price_unit: PriceUnit;
  points: PricePoint[];
}

export interface ApiErrorBody {
  error: string;
  message: string;
}

export function isAssetId(value: string | undefined): value is AssetId {
  return value !== undefined && (ASSET_IDS as readonly string[]).includes(value);
}
