import { apiGet, ApiError } from "./client";
import { config } from "./config";
import type { AssetId, ForecastDetail, ForecastListResponse, HistoryResponse } from "./types";
import { isAssetId } from "./types";

// Dữ liệu mẫu nạp muộn: bản chạy với API thật không phải tải module này.
const loadSample = () => import("./sample");

export async function getForecasts(signal?: AbortSignal): Promise<ForecastListResponse> {
  if (config.useSample) return (await loadSample()).sampleList();
  return apiGet<ForecastListResponse>("/forecasts", signal);
}

export async function getForecast(asset: AssetId, signal?: AbortSignal): Promise<ForecastDetail> {
  if (!isAssetId(asset)) throw new ApiError(400, "invalid_asset", "Mã tài sản không hợp lệ.");
  if (config.useSample) return (await loadSample()).sampleDetail(asset);
  return apiGet<ForecastDetail>(`/forecasts/${asset}`, signal);
}

/** Lịch sử ~90 phiên cho biểu đồ quạt. Endpoint tạm giả định, xem ghi chú ở types.ts. */
export async function getHistory(asset: AssetId, signal?: AbortSignal): Promise<HistoryResponse> {
  if (config.useSample) return (await loadSample()).sampleHistory(asset);
  return apiGet<HistoryResponse>(`/history/${asset}?days=90`, signal);
}
