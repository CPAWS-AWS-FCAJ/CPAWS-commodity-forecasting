import { useQuery } from "@tanstack/react-query";
import { config } from "./config";
import { getForecast, getForecasts, getHistory } from "./forecasts";
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
