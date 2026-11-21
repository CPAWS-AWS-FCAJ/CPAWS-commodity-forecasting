import { useQueries, useQuery } from "@tanstack/react-query";
import { AccuracyFormatError } from "../lib/accuracy";
import { ApiError } from "./client";
import { config } from "./config";
import {
  PRICE_HISTORY_SESSIONS,
  getAccuracy,
  getForecast,
  getForecastWithHistory,
  getForecasts,
} from "./forecasts";
import { ASSET_IDS } from "./types";
import type { AssetId } from "./types";

// Dữ liệu chỉ đổi mỗi ngày nên cache 10 phút (cấu hình ở QueryClient trong main.tsx).

export function useForecasts() {
  return useQuery({ queryKey: ["forecasts"], queryFn: ({ signal }) => getForecasts(signal) });
}

/** Chi tiết dự báo không kèm lịch sử. `enabled = false` để chỉ gọi khi cần (dự phòng). */
export function useForecast(asset: AssetId, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["forecast", asset],
    queryFn: ({ signal }) => getForecast(asset, signal),
    enabled: options.enabled ?? true,
  });
}

/** Độ tin cậy rolling_8w; lỗi định dạng (trạng thái lạ) không thử lại. */
export function useAccuracy(asset: AssetId) {
  return useQuery({
    queryKey: ["accuracy", asset],
    queryFn: ({ signal }) => getAccuracy(asset, signal),
    // Route chưa deploy: không gọi (xem config.accuracyApiEnabled)
    enabled: config.accuracyApiEnabled,
    retry: (failureCount, error) =>
      !(error instanceof AccuracyFormatError) &&
      !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
      failureCount < 2,
  });
}

/** Khóa cache chung của "chi tiết + price_history" để trang sản phẩm và Tổng quan giá dùng lại nhau. */
function withHistoryKey(asset: AssetId) {
  return ["forecast-with-history", asset, PRICE_HISTORY_SESSIONS] as const;
}

/** Chi tiết dự báo mới nhất kèm `price_history` (tối đa 520 phiên) của một tài sản. */
export function useForecastWithHistory(asset: AssetId) {
  return useQuery({
    queryKey: withHistoryKey(asset),
    queryFn: ({ signal }) => getForecastWithHistory(asset, PRICE_HISTORY_SESSIONS, signal),
  });
}

/** Trang Tổng quan giá: chi tiết + giá cuối phiên của cả 4 tài sản, mỗi tài sản một truy vấn. */
export function usePriceOverview() {
  return useQueries({
    queries: ASSET_IDS.map((asset) => ({
      queryKey: withHistoryKey(asset),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        getForecastWithHistory(asset, PRICE_HISTORY_SESSIONS, signal),
    })),
  });
}
