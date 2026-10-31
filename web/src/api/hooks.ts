import { useQuery } from "@tanstack/react-query";
import { AccuracyFormatError } from "../lib/accuracy";
import { ApiError } from "./client";
import { config } from "./config";
import { getAccuracy, getForecast, getForecasts, getHistory } from "./forecasts";
import type { AssetId } from "./types";

// Dữ liệu chỉ đổi mỗi ngày nên cache 10 phút (cấu hình ở QueryClient trong main.tsx).

export function useForecasts() {
  return useQuery({ queryKey: ["forecasts"], queryFn: ({ signal }) => getForecasts(signal) });
}

export function useForecast(asset: AssetId) {
  return useQuery({
    queryKey: ["forecast", asset],
    queryFn: ({ signal }) => getForecast(asset, signal),
  });
}

/** Độ tin cậy rolling_8w; lỗi định dạng (trạng thái lạ) không thử lại. */
export function useAccuracy(asset: AssetId) {
  return useQuery({
    queryKey: ["accuracy", asset],
    queryFn: ({ signal }) => getAccuracy(asset, signal),
    retry: (failureCount, error) =>
      !(error instanceof AccuracyFormatError) &&
      !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
      failureCount < 2,
  });
}

/**
 * Chỉ chạy khi có lịch sử (hiện: dữ liệu mẫu) vì API chưa có GET /history/{asset}.
 * Lỗi lịch sử không chặn trang: biểu đồ vẫn vẽ phần dự báo.
 */
export function useHistory(asset: AssetId) {
  return useQuery({
    queryKey: ["history", asset],
    queryFn: ({ signal }) => getHistory(asset, signal),
    enabled: config.historyAvailable,
    retry: false,
  });
}
