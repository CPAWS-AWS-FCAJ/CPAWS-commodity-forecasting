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

/**
 * GET /accuracy/{asset} (contract mục "Rolling Accuracy MVP"; fixtures tests/fixtures/accuracy/).
 * Web chỉ đọc display_value/display_status và các trường đếm; `value` là số nội bộ, không dùng để
 * hiển thị hay vượt ngưỡng.
 */
export const ACCURACY_DATA_STATUSES = ["not_ready", "collecting", "ready"] as const;
export type AccuracyDataStatus = (typeof ACCURACY_DATA_STATUSES)[number];

/** Enum đóng của display_status ở overall; by_horizon chỉ có "counts_only". */
export const OVERALL_DISPLAY_STATUSES = ["not_ready", "insufficient_data", "ready", "undefined"] as const;
export type OverallDisplayStatus = (typeof OVERALL_DISPLAY_STATUSES)[number];
export const HORIZON_DISPLAY_STATUS = "counts_only";

interface AccuracyMetricBase {
  n_obs: number;
  /** Trạng thái tính toán nội bộ (ok | undefined); không quyết định việc hiển thị. */
  status: string;
  display_value: number | null;
  display_status: string;
}

export interface CoverageMetric extends AccuracyMetricBase {
  covered_count: number;
  n_base_dates: number;
}

export interface OverallCoverageMetric extends CoverageMetric {
  /** Ngưỡng số base date để hiện số overall (hiện là 20). */
  min_display_base_dates: number;
}

export interface ValueMetric extends AccuracyMetricBase {
  value: number | null;
  unit?: "log_return" | "percent";
}

export interface AccuracyMetrics<C extends CoverageMetric = CoverageMetric> {
  coverage_80: C;
  width_80: ValueMetric;
  width_80_pct: ValueMetric;
  sign_accuracy: ValueMetric;
  up_rate: ValueMetric;
}

export interface AccuracyHorizon extends AccuracyMetrics {
  h: number;
}

export interface AccuracyResponse {
  asset: AssetId;
  model_version: string;
  evaluation_kind: "rolling_8w";
  sample: "all";
  run_id: string | null;
  evaluated_at: string | null;
  window: {
    basis: "base_date";
    days: number;
    window_start: string | null;
    window_end: string | null;
    target_cutoff_date: string | null;
    first_eligible_base_date: string | null;
  };
  evaluation_evidence: {
    schedule_basis: string;
    schedule_evidence_status: string;
    issuance_evidence_status: string;
    expected_count: number | null;
    published_count: number | null;
    missing_count: number | null;
  };
  overall: AccuracyMetrics<OverallCoverageMetric>;
  by_horizon: AccuracyHorizon[];
  data_status: string;
  disclaimer: string;
}

export interface ApiErrorBody {
  error: string;
  message: string;
}

export function isAssetId(value: string | undefined): value is AssetId {
  return value !== undefined && (ASSET_IDS as readonly string[]).includes(value);
}
